# 数据集管理路由
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Dataset, QARecord, Model

router = APIRouter()


# Pydantic Schemas
class DatasetCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None


class DatasetResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    source_type: Optional[str]
    record_count: int
    has_ground_truth: bool
    has_contexts: bool
    status: str

    class Config:
        from_attributes = True


class QARecordCreate(BaseModel):
    question: str
    answer: Optional[str] = None
    ground_truth: Optional[str] = None
    contexts: Optional[List[str]] = None
    question_type: Optional[str] = None
    difficulty: Optional[str] = None
    metadata: dict = {}


class QARecordResponse(BaseModel):
    id: UUID
    question: str
    answer: Optional[str]
    ground_truth: Optional[str]
    question_type: Optional[str]
    difficulty: Optional[str]

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    """生成测试数据请求"""
    # 文档源配置
    sources: List[Dict[str, Any]] = []

    # 生成参数
    test_size: int = 10
    distributions: Dict[str, float] = {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.2}

    # 模型配置
    llm_model_id: UUID
    embedding_model_id: UUID


class GenerateResponse(BaseModel):
    """生成任务响应"""
    task_id: str
    dataset_id: UUID
    status: str
    message: str


@router.post("", response_model=DatasetResponse)
async def create_dataset(
    data: DatasetCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建数据集"""
    dataset = Dataset(
        name=data.name,
        description=data.description,
        source_type=data.source_type,
        source_url=data.source_url
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("", response_model=List[DatasetResponse])
async def list_datasets(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集列表"""
    query = select(Dataset)
    if status:
        query = query.where(Dataset.status == status)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集详情"""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return dataset


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除数据集"""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    await db.delete(dataset)
    await db.commit()
    return {"message": "删除成功"}


@router.get("/{dataset_id}/records", response_model=List[QARecordResponse])
async def list_qa_records(
    dataset_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集的QA记录"""
    result = await db.execute(
        select(QARecord)
        .where(QARecord.dataset_id == dataset_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/{dataset_id}/records", response_model=QARecordResponse)
async def create_qa_record(
    dataset_id: UUID,
    data: QARecordCreate,
    db: AsyncSession = Depends(get_db)
):
    """添加QA记录"""
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    qa_record = QARecord(
        dataset_id=dataset_id,
        question=data.question,
        answer=data.answer,
        ground_truth=data.ground_truth,
        question_type=data.question_type,
        difficulty=data.difficulty,
        metadata=data.metadata
    )

    # 更新数据集统计
    dataset.record_count += 1
    if data.ground_truth:
        dataset.has_ground_truth = True
    if data.contexts:
        dataset.has_contexts = True

    db.add(qa_record)
    await db.commit()
    await db.refresh(qa_record)
    return qa_record


@router.post("/{dataset_id}/import")
async def import_data(
    dataset_id: UUID,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db)
):
    """导入数据文件（JSON/JSONL/CSV）

    支持 JSON、JSONL、CSV 格式文件导入 QA 数据。
    异步处理，返回任务 ID。
    """
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 上传文件到 MinIO
    from ...services.storage.minio_service import get_minio_service
    import io

    minio_service = get_minio_service()
    file_content = await file.read()

    upload_result = await minio_service.upload_file(
        bucket="datasets",
        file_data=io.BytesIO(file_content),
        file_name=file.filename,
        content_type=file.content_type
    )

    if not upload_result.get("success"):
        raise HTTPException(status_code=500, detail="文件上传失败")

    # 确定文件类型
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in ["json", "jsonl", "csv"]:
        raise HTTPException(status_code=400, detail="不支持文件类型，仅支持 JSON、JSONL、CSV")

    # 启动异步导入任务
    from ...tasks.dataset_tasks import import_dataset_task

    task = import_dataset_task.delay(
        str(dataset_id),
        upload_result["object_name"],
        file_ext
    )

    return {
        "message": "数据导入任务已创建",
        "task_id": task.id,
        "filename": file.filename,
        "dataset_id": str(dataset_id),
        "file_type": file_ext
    }


@router.post("/{dataset_id}/generate", response_model=GenerateResponse)
async def generate_dataset(
    dataset_id: UUID,
    data: GenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """生成测试数据集

    使用 Ragas 从源文档自动生成测试数据：
    - 支持上传文件、直接文本、已有文档作为源
    - 自动生成 question、ground_truth、contexts
    - 异步处理，返回任务 ID
    """
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 检查模型是否存在
    llm_result = await db.execute(select(Model).where(Model.id == data.llm_model_id))
    llm_model = llm_result.scalar_one_or_none()
    if not llm_model or llm_model.model_type != "llm":
        raise HTTPException(status_code=400, detail="LLM 模型不存在或类型错误")

    embedding_result = await db.execute(select(Model).where(Model.id == data.embedding_model_id))
    embedding_model = embedding_result.scalar_one_or_none()
    if not embedding_model or embedding_model.model_type != "embedding":
        raise HTTPException(status_code=400, detail="Embedding 模型不存在或类型错误")

    # 检查源配置
    if not data.sources:
        raise HTTPException(status_code=400, detail="至少需要一个文档源")

    # 验证源配置
    for source in data.sources:
        source_type = source.get("source_type")
        if source_type not in ["file_upload", "text_input", "existing_doc"]:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的源类型: {source_type}"
            )

        if source_type == "file_upload" and not source.get("file_paths"):
            raise HTTPException(status_code=400, detail="file_upload 类型需要 file_paths")

        if source_type == "text_input" and not source.get("texts"):
            raise HTTPException(status_code=400, detail="text_input 类型需要 texts")

        if source_type == "existing_doc" and not source.get("document_ids"):
            raise HTTPException(status_code=400, detail="existing_doc 类型需要 document_ids")

    # 启动异步生成任务
    from ...tasks.dataset_tasks import generate_dataset_task

    config = {
        "sources": data.sources,
        "test_size": data.test_size,
        "distributions": data.distributions,
        "llm_model_id": str(data.llm_model_id),
        "embedding_model_id": str(data.embedding_model_id),
    }

    task = generate_dataset_task.delay(str(dataset_id), config)

    return GenerateResponse(
        task_id=task.id,
        dataset_id=dataset_id,
        status="pending",
        message=f"生成任务已创建，预计生成 {data.test_size} 条数据"
    )


@router.get("/{dataset_id}/generate/status/{task_id}")
async def get_generate_status(
    dataset_id: UUID,
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """获取生成任务状态"""
    from celery.result import AsyncResult
    from ...core.celery_app import celery_app

    task_result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "dataset_id": str(dataset_id),
        "status": task_result.status,
        "result": None,
        "progress": None
    }

    if task_result.status == "PROGRESS":
        response["progress"] = task_result.info

    elif task_result.status == "SUCCESS":
        response["result"] = task_result.result

    elif task_result.status == "FAILURE":
        response["result"] = {"error": str(task_result.info)}

    return response


@router.get("/{dataset_id}/validate")
async def validate_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """验证数据集完整性"""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 统计数据
    total_count = await db.execute(
        select(func.count(QARecord.id)).where(QARecord.dataset_id == dataset_id)
    )
    with_ground_truth = await db.execute(
        select(func.count(QARecord.id))
        .where(QARecord.dataset_id == dataset_id, QARecord.ground_truth != None)
    )

    return {
        "dataset_id": str(dataset_id),
        "total_records": total_count.scalar(),
        "with_ground_truth": with_ground_truth.scalar(),
        "completeness": {
            "has_ground_truth": dataset.has_ground_truth,
            "has_contexts": dataset.has_contexts
        }
    }