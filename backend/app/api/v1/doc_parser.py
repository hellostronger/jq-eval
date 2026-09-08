# 文档解析API路由（minerU 等解析服务）
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from ...core.database import get_db
from ...core.utc_datetime import UTCDatetime
from ...models import DocParseBatch, DocParseResult, Document, Model, Dataset
from ...services.storage import get_minio_service, MinIOService

router = APIRouter()
logger = logging.getLogger(__name__)

# 支持解析的源文件类型
PARSEABLE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".ppt", ".pptx", ".html", ".epub"}


class DocParseBatchCreate(BaseModel):
    name: Optional[str] = None
    parser_model_id: UUID
    object_names: List[str]  # MinIO documents bucket 中的对象名
    config: Dict[str, Any] = {}  # language/output_format/enable_ocr
    dataset_id: Optional[UUID] = None  # 归属数据集（数据集内触发解析时填写）


class DocParseBatchResponse(BaseModel):
    id: UUID
    name: str
    parser_model_id: UUID
    parser_model_name: Optional[str] = None
    dataset_id: Optional[UUID] = None
    status: str
    progress: int
    error: Optional[str] = None
    config: Dict[str, Any]
    total_files: int
    success_files: int
    failed_files: int
    evaluation_summary: Optional[Dict[str, Any]] = None
    started_at: Optional[UTCDatetime] = None
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class DocParseResultResponse(BaseModel):
    id: UUID
    batch_id: UUID
    file_name: str
    object_name: str
    file_size: Optional[int] = None
    status: str
    error: Optional[str] = None
    md_content: Optional[str] = None
    has_content_list: bool = False
    doc_id: Optional[UUID] = None
    duration: Optional[float] = None
    evaluation: Optional[Dict[str, Any]] = None
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None


class SourceFileResponse(BaseModel):
    """MinIO 源文件信息"""
    object_name: str
    file_name: str
    size: int
    last_modified: Optional[str] = None
    etag: Optional[str] = None
    content_type: Optional[str] = None
    parseable: bool
    # 数据集内触发解析时，新增的源文件可标注归属（仅信息展示，MinIO 不分区）
    dataset_id: Optional[UUID] = None


# ---------- 源文件管理 ----------

@router.get("/files")
async def list_source_files(
    dataset_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    minio: MinIOService = Depends(get_minio_service)
):
    """列出 MinIO documents bucket 中可解析的源文件

    dataset_id 填写时只返回该数据集前缀目录（datasets/<id>/）下的源文件。
    """
    try:
        prefix = f"datasets/{dataset_id}/" if dataset_id else ""
        files = await minio.list_files("documents", prefix, True)
        result = []
        for f in files:
            ext = ("." + f["object_name"].rsplit(".", 1)[-1].lower()) if "." in f["object_name"] else ""
            result.append({
                **f,
                "parseable": ext in PARSEABLE_EXTENSIONS,
                "file_name": f["object_name"].rsplit("/", 1)[-1],
                "dataset_id": dataset_id,
            })
        return {"items": result, "total": len(result)}
    except Exception as e:
        logger.error(f"列出源文件失败 dataset_id={dataset_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"列出源文件失败: {e}")


@router.post("/files/upload")
async def upload_source_file(
    file: UploadFile = File(...),
    dataset_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    minio: MinIOService = Depends(get_minio_service)
):
    """上传源文件到 MinIO documents bucket（保存待解析）

    dataset_id 填写时表示数据集内触发解析，源文件存入该数据集前缀目录下，
    批次/产物文档归属该数据集。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in file.filename else ""
    if ext not in PARSEABLE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，支持: {sorted(PARSEABLE_EXTENSIONS)}"
        )
    if dataset_id and not await db.get(Dataset, dataset_id):
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 数据集内上传的源文件带 datasets/<id>/ 前缀，便于按数据集筛选
    result = await minio.upload_file(
        bucket="documents",
        file_data=file.file,
        file_name=f"datasets/{dataset_id}/{file.filename}" if dataset_id else file.filename,
        content_type=file.content_type,
    )
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])

    ext = "." + result["object_name"].rsplit(".", 1)[-1].lower() if "." in result["object_name"] else ""
    return {
        **result,
        "file_name": result["object_name"].rsplit("/", 1)[-1],
        "parseable": ext in PARSEABLE_EXTENSIONS,
        "dataset_id": dataset_id,
    }


@router.delete("/files/{object_name:path}")
async def delete_source_file(
    object_name: str,
    minio: MinIOService = Depends(get_minio_service)
):
    """删除 MinIO documents bucket 中的源文件"""
    result = await minio.delete_file("documents", object_name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"message": "文件已删除"}


# ---------- 解析批次 ----------

@router.post("/batches", response_model=DocParseBatchResponse)
async def create_parse_batch(
    data: DocParseBatchCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建解析批次：挑选源文件并提交给解析服务"""
    result = await db.execute(select(Model).where(Model.id == data.parser_model_id))
    parser_model = result.scalar_one_or_none()
    if not parser_model or parser_model.model_type != "doc_parser":
        raise HTTPException(status_code=400, detail="解析服务不存在或类型错误")
    if not data.object_names:
        raise HTTPException(status_code=400, detail="请至少选择一个源文件")
    if data.dataset_id:
        dataset = await db.get(Dataset, data.dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    batch = DocParseBatch(
        name=data.name or f"解析任务_{datetime.utcnow().strftime('%m%d_%H%M')}",
        parser_model_id=data.parser_model_id,
        parser_model_name=parser_model.name,
        dataset_id=data.dataset_id,
        status="pending",
        config=data.config or {},
        total_files=len(data.object_names),
    )
    db.add(batch)
    await db.flush()

    for object_name in data.object_names:
        file_name = object_name.rsplit("/", 1)[-1]
        db.add(DocParseResult(
            batch_id=batch.id,
            file_name=file_name,
            object_name=object_name,
            status="pending",
        ))

    await db.commit()
    await db.refresh(batch)

    # 提交异步解析任务
    from ...tasks.doc_parse_tasks import doc_parse_task
    doc_parse_task.delay(str(batch.id))

    return batch


@router.get("/batches", response_model=List[DocParseBatchResponse])
async def list_parse_batches(
    status: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    include_global: bool = Query(True, description="dataset_id 过滤时是否同时返回全局解析任务"),
    db: AsyncSession = Depends(get_db)
):
    """获取解析批次列表（dataset_id 过滤数据集相关任务）"""
    query = select(DocParseBatch)
    if status:
        query = query.where(DocParseBatch.status == status)
    if dataset_id:
        if include_global:
            query = query.where(
                (DocParseBatch.dataset_id == dataset_id) | (DocParseBatch.dataset_id.is_(None))
            )
        else:
            query = query.where(DocParseBatch.dataset_id == dataset_id)
    query = query.order_by(DocParseBatch.created_at.desc())
    return (await db.execute(query)).scalars().all()


@router.get("/batches/{batch_id}", response_model=DocParseBatchResponse)
async def get_parse_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取解析批次详情"""
    batch = await db.get(DocParseBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="解析批次不存在")
    return batch


@router.get("/batches/{batch_id}/results", response_model=List[DocParseResultResponse])
async def list_parse_results(
    batch_id: UUID,
    with_content: bool = Query(False, description="是否返回完整 Markdown 内容"),
    db: AsyncSession = Depends(get_db)
):
    """获取批次内各文件的解析结果"""
    batch = await db.get(DocParseBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="解析批次不存在")

    results = (await db.execute(
        select(DocParseResult)
        .where(DocParseResult.batch_id == batch_id)
        .order_by(DocParseResult.created_at)
    )).scalars().all()

    return [
        DocParseResultResponse(
            id=r.id,
            batch_id=r.batch_id,
            file_name=r.file_name,
            object_name=r.object_name,
            file_size=r.file_size,
            status=r.status,
            error=r.error,
            md_content=r.md_content if with_content else (r.md_content[:300] if r.md_content else None),
            has_content_list=bool(r.content_list),
            doc_id=r.doc_id,
            duration=r.duration,
            evaluation=r.evaluation,
            completed_at=r.completed_at,
            created_at=r.created_at,
        )
        for r in results
    ]


@router.get("/results/{result_id}", response_model=DocParseResultResponse)
async def get_parse_result(
    result_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取单文件解析结果（含完整 Markdown）"""
    r = await db.get(DocParseResult, result_id)
    if not r:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return DocParseResultResponse(
        id=r.id,
        batch_id=r.batch_id,
        file_name=r.file_name,
        object_name=r.object_name,
        file_size=r.file_size,
        status=r.status,
        error=r.error,
        md_content=r.md_content,
        has_content_list=bool(r.content_list),
        doc_id=r.doc_id,
        duration=r.duration,
        evaluation=r.evaluation,
        completed_at=r.completed_at,
        created_at=r.created_at,
    )


@router.delete("/batches/{batch_id}")
async def delete_parse_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除解析批次（解析产物 Document 保留）"""
    batch = await db.get(DocParseBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="解析批次不存在")
    if batch.status == "running":
        raise HTTPException(status_code=400, detail="运行中的批次无法删除")
    await db.delete(batch)
    await db.commit()
    return {"message": "删除成功"}


# ---------- 解析结果评估 ----------

@router.post("/batches/{batch_id}/evaluate")
async def evaluate_parse_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """对批次内成功的解析结果进行质量评估"""
    batch = await db.get(DocParseBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="解析批次不存在")
    if batch.status == "running":
        raise HTTPException(status_code=400, detail="批次仍在解析中")

    from ...services.doc_parse_eval import compute_batch_summary, evaluate_result

    results = (await db.execute(
        select(DocParseResult).where(DocParseResult.batch_id == batch_id)
    )).scalars().all()

    evaluated = 0
    for r in results:
        if r.status != "success" or not r.md_content:
            continue
        r.evaluation = evaluate_result(r.file_name, r.md_content, r.duration)
        evaluated += 1

    if evaluated:
        batch.evaluation_summary = compute_batch_summary([
            {"file_name": r.file_name, "evaluation": r.evaluation}
            for r in results if r.evaluation
        ])
    await db.commit()

    return {
        "message": f"已评估 {evaluated} 个结果",
        "evaluated": evaluated,
        "evaluation_summary": batch.evaluation_summary,
    }
