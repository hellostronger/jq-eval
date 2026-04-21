# 数据集管理路由
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
import io
import csv
import json

from ...core.database import get_db
from ...models import Dataset, QARecord, Model
from ...models.document import Document, Chunk

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
    contexts: Optional[List[str]] = None
    question_type: Optional[str]
    difficulty: Optional[str]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_contexts(cls, qa_record: QARecord):
        """从 ORM 模型创建响应，提取 contexts"""
        data = {
            "id": qa_record.id,
            "question": qa_record.question,
            "answer": qa_record.answer,
            "ground_truth": qa_record.ground_truth,
            "question_type": qa_record.question_type,
            "difficulty": qa_record.difficulty,
        }
        # 从 snapshot 中提取 contexts
        if qa_record.snapshot and "contexts" in qa_record.snapshot:
            data["contexts"] = qa_record.snapshot["contexts"]
        return cls(**data)


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


class QARecordListResponse(BaseModel):
    """QA记录列表响应（分页）"""
    items: List[QARecordResponse]
    total: int


@router.get("/{dataset_id}/qa-records", response_model=QARecordListResponse)
async def list_qa_records(
    dataset_id: UUID,
    page: int = 1,
    size: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集的QA记录（分页）"""
    # 计算偏移量
    skip = (page - 1) * size

    # 查询总数
    total_result = await db.execute(
        select(func.count(QARecord.id)).where(QARecord.dataset_id == dataset_id)
    )
    total = total_result.scalar() or 0

    # 查询记录
    result = await db.execute(
        select(QARecord)
        .where(QARecord.dataset_id == dataset_id)
        .offset(skip)
        .limit(size)
    )
    records = result.scalars().all()

    # 使用 from_orm_with_contexts 转换每个记录
    items = [QARecordResponse.from_orm_with_contexts(record) for record in records]

    return QARecordListResponse(items=items, total=total)


@router.get("/{dataset_id}/debug")
async def debug_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """调试接口：检查数据集和QA记录状态"""
    # 查询数据集
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()

    if not dataset:
        return {"error": "数据集不存在", "dataset_id": str(dataset_id)}

    # 查询所有QA记录（不分页）
    all_records_result = await db.execute(
        select(QARecord).where(QARecord.dataset_id == dataset_id)
    )
    all_records = all_records_result.scalars().all()

    # 统计
    total_count = len(all_records)
    with_ground_truth = sum(1 for r in all_records if r.ground_truth)
    with_contexts = sum(1 for r in all_records if r.snapshot and "contexts" in r.snapshot)

    return {
        "dataset": {
            "id": str(dataset.id),
            "name": dataset.name,
            "record_count": dataset.record_count,
            "has_ground_truth": dataset.has_ground_truth,
            "has_contexts": dataset.has_contexts,
            "status": dataset.status,
        },
        "qa_records": {
            "total": total_count,
            "with_ground_truth": with_ground_truth,
            "with_contexts": with_contexts,
            "sample": [
                {
                    "id": str(r.id),
                    "question": r.question[:50] + "..." if len(r.question) > 50 else r.question,
                    "has_ground_truth": bool(r.ground_truth),
                    "has_contexts": bool(r.snapshot and "contexts" in r.snapshot),
                }
                for r in all_records[:3]
            ] if all_records else []
        }
    }


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
        qa_metadata=data.metadata
    )

    # 处理 contexts，存储到 snapshot 字段
    if data.contexts:
        qa_record.snapshot = {"contexts": data.contexts}

    # 更新数据集统计
    dataset.record_count += 1
    if data.ground_truth:
        dataset.has_ground_truth = True
    if data.contexts:
        dataset.has_contexts = True

    db.add(qa_record)
    await db.commit()
    await db.refresh(qa_record)

    return QARecordResponse.from_orm_with_contexts(qa_record)


@router.delete("/{dataset_id}/qa-records/{record_id}")
async def delete_qa_record(
    dataset_id: UUID,
    record_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除单条QA记录"""
    # 查询记录
    result = await db.execute(
        select(QARecord).where(
            QARecord.id == record_id,
            QARecord.dataset_id == dataset_id
        )
    )
    qa_record = result.scalar_one_or_none()

    if not qa_record:
        raise HTTPException(status_code=404, detail="QA记录不存在")

    # 删除记录
    await db.delete(qa_record)

    # 更新数据集统计
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()
    if dataset:
        dataset.record_count -= 1
        # 重新检查是否有 ground_truth 和 contexts
        gt_count = await db.execute(
            select(func.count(QARecord.id))
            .where(QARecord.dataset_id == dataset_id, QARecord.ground_truth != None)
        )
        ctx_count = await db.execute(
            select(func.count(QARecord.id))
            .where(QARecord.dataset_id == dataset_id, QARecord.snapshot != None)
        )
        dataset.has_ground_truth = gt_count.scalar() > 0
        dataset.has_contexts = ctx_count.scalar() > 0

    await db.commit()

    return {"message": "删除成功", "record_id": str(record_id)}


@router.post("/{dataset_id}/qa-records/batch-delete")
async def batch_delete_qa_records(
    dataset_id: UUID,
    record_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    """批量删除QA记录"""
    if not record_ids:
        raise HTTPException(status_code=400, detail="请提供要删除的记录ID")

    # 查询并删除记录
    result = await db.execute(
        select(QARecord).where(
            QARecord.id.in_(record_ids),
            QARecord.dataset_id == dataset_id
        )
    )
    records = result.scalars().all()

    if not records:
        raise HTTPException(status_code=404, detail="未找到要删除的记录")

    deleted_count = len(records)
    for record in records:
        await db.delete(record)

    # 更新数据集统计
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()
    if dataset:
        dataset.record_count -= deleted_count
        # 重新检查是否有 ground_truth 和 contexts
        gt_count = await db.execute(
            select(func.count(QARecord.id))
            .where(QARecord.dataset_id == dataset_id, QARecord.ground_truth != None)
        )
        ctx_count = await db.execute(
            select(func.count(QARecord.id))
            .where(QARecord.dataset_id == dataset_id, QARecord.snapshot != None)
        )
        dataset.has_ground_truth = gt_count.scalar() > 0
        dataset.has_contexts = ctx_count.scalar() > 0

    await db.commit()

    return {
        "message": "批量删除成功",
        "deleted_count": deleted_count,
        "dataset_id": str(dataset_id)
    }


@router.post("/{dataset_id}/import")
async def import_data(
    dataset_id: UUID,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db)
):
    """导入数据文件（JSON/JSONL/CSV）

    支持 JSON、JSONL、CSV 格式文件导入 QA 数据。
    默认同步处理，直接返回导入结果。
    """
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 读取文件内容
    file_content = await file.read()

    # 确定文件类型
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in ["json", "jsonl", "csv"]:
        raise HTTPException(status_code=400, detail="不支持文件类型，仅支持 JSON、JSONL、CSV")

    # 同步处理导入
    records = []

    # 解析文件
    if file_ext == "json":
        import json
        data = json.loads(file_content.decode("utf-8"))
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict) and "test_cases" in data:
            records = data["test_cases"]

    elif file_ext == "jsonl":
        import json
        lines = file_content.decode("utf-8").strip().split("\n")
        records = [json.loads(line) for line in lines if line]

    elif file_ext == "csv":
        import csv
        import io
        import logging
        logger = logging.getLogger(__name__)

        # 使用 utf-8-sig 解码，自动处理 BOM
        content = file_content.decode('utf-8-sig')
        logger.info(f"CSV文件内容（前200字符）: {content[:200]}")

        reader = csv.DictReader(io.StringIO(content))

        # 打印CSV字段名
        logger.info(f"CSV字段名: {reader.fieldnames}")

        records = []
        for row in reader:
            # 打印每行数据的完整内容
            logger.info(f"CSV行数据: {row}")
            records.append(row)

        logger.info(f"CSV解析完成，共 {len(records)} 条记录")

    # 调试日志
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"导入文件解析结果: file_type={file_ext}, total_records={len(records)}")
    if records:
        logger.info(f"第一条记录完整内容: {records[0]}")
        logger.info(f"第一条记录字段名: {list(records[0].keys())}")
        logger.info(f"第一条记录question字段值: '{records[0].get('question', '')}'")

    # 保存到数据库
    import json
    saved_count = 0

    for record in records:
        # 打印即将保存的每条记录
        question_value = record.get("question", "")
        logger.info(f"准备保存记录 - question值: '{question_value}'")

        # 处理 contexts（CSV 中可能是 JSON 字符串）
        contexts = record.get("contexts")
        if contexts:
            if isinstance(contexts, str):
                try:
                    contexts = json.loads(contexts)
                except:
                    contexts = [contexts]
            elif not isinstance(contexts, list):
                contexts = [contexts]

        # 处理 metadata（CSV 中可能是 JSON 字符串）
        metadata = record.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}

        qa_record = QARecord(
            dataset_id=dataset_id,
            question=question_value,  # 明确使用提取的值
            answer=record.get("answer"),
            ground_truth=record.get("ground_truth"),
            question_type=record.get("question_type", "simple"),
            difficulty=record.get("difficulty"),
            qa_metadata=metadata,
        )

        # 存储 contexts 到 snapshot
        if contexts:
            qa_record.snapshot = {"contexts": contexts}

        db.add(qa_record)
        saved_count += 1

    logger.info(f"成功添加 {saved_count} 条QA记录到数据库")

    # 更新统计
    dataset.record_count += len(records)
    dataset.has_ground_truth = any(r.get("ground_truth") for r in records)
    dataset.has_contexts = any(r.get("contexts") for r in records)
    dataset.status = "ready"

    await db.commit()

    return {
        "message": "数据导入成功",
        "imported_count": len(records),
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

    # 保存任务信息到数据库（用于恢复轮询）
    dataset.generate_task_id = task.id
    dataset.generate_task_status = "PENDING"
    await db.commit()

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

    # 获取数据集并更新任务状态
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()

    response = {
        "task_id": task_id,
        "dataset_id": str(dataset_id),
        "status": task_result.status,
        "result": None,
        "progress": None
    }

    if task_result.status == "PROGRESS":
        response["progress"] = task_result.info
        if dataset:
            dataset.generate_task_status = "PROGRESS"
            await db.commit()

    elif task_result.status == "SUCCESS":
        response["result"] = task_result.result
        if dataset:
            dataset.generate_task_status = "SUCCESS"
            dataset.generate_task_id = None  # 清除任务ID
            await db.commit()

    elif task_result.status == "FAILURE":
        response["result"] = {"error": str(task_result.info)}
        if dataset:
            dataset.generate_task_status = "FAILURE"
            dataset.generate_task_id = None  # 清除任务ID
            await db.commit()

    return response


@router.get("/{dataset_id}/generate/current")
async def get_current_generate_task(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取当前数据集的生成任务信息（用于恢复轮询）"""
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    return {
        "task_id": dataset.generate_task_id,
        "status": dataset.generate_task_status,
        "has_active_task": dataset.generate_task_id is not None
    }


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


@router.get("/templates/{format}")
async def download_template(format: str):
    """下载导入数据模板

    支持 JSON、JSONL、CSV 格式模板下载

    Args:
        format: 模板格式，可选值：json, jsonl, csv

    Returns:
        StreamingResponse: 模板文件流
    """
    # 示例数据
    example_data = [
        {
            "question": "什么是机器学习？",
            "answer": "机器学习是人工智能的一个分支...",
            "ground_truth": "机器学习是一种使计算机系统能够从数据中学习和改进的技术，无需明确编程。",
            "contexts": [
                "机器学习是人工智能的核心研究领域之一...",
                "机器学习算法可以从数据中识别模式..."
            ],
            "question_type": "simple",
            "difficulty": "medium",
            "metadata": {"source": "example"}
        },
        {
            "question": "深度学习和机器学习有什么区别？",
            "answer": "深度学习是机器学习的一个子集...",
            "ground_truth": "深度学习使用多层神经网络来处理数据，而机器学习包括更广泛的算法。",
            "contexts": [
                "深度学习是一种特殊的机器学习方法...",
                "机器学习包括监督学习、非监督学习等..."
            ],
            "question_type": "reasoning",
            "difficulty": "hard",
            "metadata": {"source": "example"}
        }
    ]

    if format == "json":
        # JSON 格式：整个文件是一个数组，使用纯 UTF-8 编码
        content = json.dumps(example_data, ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode('utf-8')),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=dataset_template.json",
                "Content-Type": "application/json; charset=utf-8"
            }
        )

    elif format == "jsonl":
        # JSONL 格式：每行一个 JSON 对象，使用纯 UTF-8 编码
        lines = [json.dumps(item, ensure_ascii=False) for item in example_data]
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode('utf-8')),
            media_type="application/jsonl; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=dataset_template.jsonl",
                "Content-Type": "application/jsonl; charset=utf-8"
            }
        )

    elif format == "csv":
        # CSV 格式 - 使用纯 UTF-8 编码（现代 Excel 可通过 Content-Type 正确识别）
        output = io.StringIO()
        writer = csv.writer(output)

        # 写入表头
        writer.writerow([
            "question", "answer", "ground_truth", "contexts",
            "question_type", "difficulty", "metadata"
        ])

        # 写入示例数据
        for item in example_data:
            writer.writerow([
                item["question"],
                item["answer"],
                item["ground_truth"],
                json.dumps(item["contexts"], ensure_ascii=False),  # contexts 作为 JSON 字符串
                item["question_type"],
                item["difficulty"],
                json.dumps(item["metadata"], ensure_ascii=False)  # metadata 作为 JSON 字符串
            ])

        content = output.getvalue()
        # 使用纯 UTF-8 编码，通过 Content-Type 指定编码，Excel 可正确识别
        return StreamingResponse(
            io.BytesIO(content.encode('utf-8')),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=dataset_template.csv",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )

    else:
        raise HTTPException(status_code=400, detail="不支持的格式，仅支持 json、jsonl、csv")


# 文档和分片相关API

class DocumentResponse(BaseModel):
    """文档响应"""
    id: UUID
    title: Optional[str]
    content: Optional[str]
    file_type: Optional[str]
    source_type: Optional[str]
    chunk_count: Optional[int] = None

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    """分片响应"""
    id: UUID
    doc_id: UUID
    content: str
    chunk_index: int
    start_char: Optional[int]
    end_char: Optional[int]
    milvus_id: Optional[str]
    document_title: Optional[str] = None

    class Config:
        from_attributes = True


class ChunkListResponse(BaseModel):
    """分片列表响应"""
    items: List[ChunkResponse]
    total: int


class DocumentListResponse(BaseModel):
    """文档列表响应"""
    items: List[DocumentResponse]
    total: int


class DocumentCreate(BaseModel):
    """创建文档请求"""
    title: Optional[str] = None
    content: str
    source_type: Optional[str] = "upload"
    file_type: Optional[str] = None


class ChunkDocumentRequest(BaseModel):
    """分片文档请求"""
    chunk_size: int = 500
    chunk_overlap: int = 50
    chunk_strategy: str = "recursive"  # recursive/fixed/sentence


class CreateFromNewsRequest(BaseModel):
    """从热点新闻创建文档请求"""
    article_ids: List[UUID]


@router.get("/{dataset_id}/documents", response_model=DocumentListResponse)
async def list_dataset_documents(
    dataset_id: UUID,
    page: int = 1,
    size: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集关联的文档列表"""
    # 获取数据集的所有 QARecord 的 doc_ids
    qa_records_result = await db.execute(
        select(QARecord.doc_ids).where(QARecord.dataset_id == dataset_id)
    )
    doc_ids_lists = qa_records_result.scalars().all()

    # 收集所有唯一的 doc_ids
    all_doc_ids = set()
    for doc_ids in doc_ids_lists:
        if doc_ids:
            for doc_id in doc_ids:
                all_doc_ids.add(doc_id)

    if not all_doc_ids:
        return DocumentListResponse(items=[], total=0)

    # 查询总数
    total = len(all_doc_ids)

    # 分页查询文档
    skip = (page - 1) * size
    paginated_ids = list(all_doc_ids)[skip:skip + size]

    if not paginated_ids:
        return DocumentListResponse(items=[], total=total)

    # 查询文档
    docs_result = await db.execute(
        select(Document).where(Document.id.in_(paginated_ids))
    )
    documents = docs_result.scalars().all()

    # 查询每个文档的 chunk 数量
    doc_chunk_counts = {}
    for doc in documents:
        count_result = await db.execute(
            select(func.count(Chunk.id)).where(Chunk.doc_id == doc.id)
        )
        doc_chunk_counts[str(doc.id)] = count_result.scalar() or 0

    items = []
    for doc in documents:
        items.append(DocumentResponse(
            id=doc.id,
            title=doc.title,
            content=doc.content[:500] if doc.content and len(doc.content) > 500 else doc.content,
            file_type=doc.file_type,
            source_type=doc.source_type,
            chunk_count=doc_chunk_counts.get(str(doc.id), 0)
        ))

    return DocumentListResponse(items=items, total=total)


@router.get("/{dataset_id}/documents/{doc_id}", response_model=DocumentResponse)
async def get_document_detail(
    dataset_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取文档详情"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 查询 chunk 数量
    count_result = await db.execute(
        select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id)
    )
    chunk_count = count_result.scalar() or 0

    return DocumentResponse(
        id=document.id,
        title=document.title,
        content=document.content,
        file_type=document.file_type,
        source_type=document.source_type,
        chunk_count=chunk_count
    )


@router.get("/{dataset_id}/chunks", response_model=ChunkListResponse)
async def list_dataset_chunks(
    dataset_id: UUID,
    page: int = 1,
    size: int = 10,
    doc_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取数据集关联的分片列表"""
    # 如果指定了 doc_id，直接查询该文档的分片
    if doc_id:
        # 查询总数
        total_result = await db.execute(
            select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id)
        )
        total = total_result.scalar() or 0

        # 分页查询
        skip = (page - 1) * size
        chunks_result = await db.execute(
            select(Chunk)
            .where(Chunk.doc_id == doc_id)
            .order_by(Chunk.chunk_index)
            .offset(skip)
            .limit(size)
        )
        chunks = chunks_result.scalars().all()

        # 获取文档标题
        doc_result = await db.execute(select(Document.title).where(Document.id == doc_id))
        doc_title = doc_result.scalar()

        items = [
            ChunkResponse(
                id=c.id,
                doc_id=c.doc_id,
                content=c.content,
                chunk_index=c.chunk_index,
                start_char=c.start_char,
                end_char=c.end_char,
                milvus_id=c.milvus_id,
                document_title=doc_title
            )
            for c in chunks
        ]

        return ChunkListResponse(items=items, total=total)

    # 否则从 QARecord 的 target_chunk_ids 获取
    qa_records_result = await db.execute(
        select(QARecord.target_chunk_ids).where(QARecord.dataset_id == dataset_id)
    )
    chunk_ids_lists = qa_records_result.scalars().all()

    # 收集所有唯一的 chunk_ids
    all_chunk_ids = set()
    for chunk_ids in chunk_ids_lists:
        if chunk_ids:
            for chunk_id in chunk_ids:
                all_chunk_ids.add(chunk_id)

    if not all_chunk_ids:
        return ChunkListResponse(items=[], total=0)

    total = len(all_chunk_ids)

    # 分页
    skip = (page - 1) * size
    paginated_ids = list(all_chunk_ids)[skip:skip + size]

    if not paginated_ids:
        return ChunkListResponse(items=[], total=total)

    # 查询分片
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.id.in_(paginated_ids))
    )
    chunks = chunks_result.scalars().all()

    # 获取文档信息
    doc_ids = set(c.doc_id for c in chunks)
    docs_result = await db.execute(
        select(Document.id, Document.title).where(Document.id.in_(doc_ids))
    )
    doc_titles = {str(row.id): row.title for row in docs_result.fetchall()}

    items = [
        ChunkResponse(
            id=c.id,
            doc_id=c.doc_id,
            content=c.content[:300] if c.content and len(c.content) > 300 else c.content,
            chunk_index=c.chunk_index,
            start_char=c.start_char,
            end_char=c.end_char,
            milvus_id=c.milvus_id,
            document_title=doc_titles.get(str(c.doc_id))
        )
        for c in chunks
    ]

    return ChunkListResponse(items=items, total=total)


@router.get("/{dataset_id}/chunks/{chunk_id}", response_model=ChunkResponse)
async def get_chunk_detail(
    dataset_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取分片详情"""
    result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
    chunk = result.scalar_one_or_none()

    if not chunk:
        raise HTTPException(status_code=404, detail="分片不存在")

    # 获取文档标题
    doc_result = await db.execute(
        select(Document.title).where(Document.id == chunk.doc_id)
    )
    doc_title = doc_result.scalar()

    return ChunkResponse(
        id=chunk.id,
        doc_id=chunk.doc_id,
        content=chunk.content,
        chunk_index=chunk.chunk_index,
        start_char=chunk.start_char,
        end_char=chunk.end_char,
        milvus_id=chunk.milvus_id,
        document_title=doc_title
    )


@router.post("/{dataset_id}/documents/upload")
async def upload_document(
    dataset_id: UUID,
    file: UploadFile = File(...),
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """上传文档并自动分片

    支持上传 txt、md、pdf 等文档，自动进行分片处理
    """
    import logging
    logger = logging.getLogger(__name__)

    # 检查数据集是否存在
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 读取文件内容
    file_content = await file.read()

    # 根据文件类型处理
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"

    content = ""
    if file_ext == "txt" or file_ext == "md":
        content = file_content.decode("utf-8", errors="ignore")
    elif file_ext == "pdf":
        # PDF处理
        try:
            import fitz  # PyMuPDF
            pdf_doc = fitz.open(stream=file_content, filetype="pdf")
            content = ""
            for page in pdf_doc:
                content += page.get_text()
            pdf_doc.close()
        except ImportError:
            raise HTTPException(status_code=400, detail="PDF处理库未安装，请安装 PyMuPDF")
    else:
        # 尝试作为文本处理
        content = file_content.decode("utf-8", errors="ignore")

    if not content:
        raise HTTPException(status_code=400, detail="文档内容为空")

    # 创建文档
    document = Document(
        title=file.filename or f"文档_{len(content)}字符",
        content=content,
        file_type=file_ext,
        source_type="upload",
        doc_metadata={"original_filename": file.filename, "size": len(file_content)}
    )
    db.add(document)
    await db.flush()  # 获取文档ID

    # 分片处理
    chunks = _split_text(content, chunk_size, chunk_overlap)

    # 创建分片记录
    chunk_records = []
    for i, chunk_text in enumerate(chunks):
        chunk_record = Chunk(
            doc_id=document.id,
            content=chunk_text["content"],
            chunk_index=i,
            start_char=chunk_text["start"],
            end_char=chunk_text["end"]
        )
        db.add(chunk_record)
        chunk_records.append(chunk_record)

    await db.commit()

    logger.info(f"上传文档成功: doc_id={document.id}, chunks={len(chunk_records)}")

    return {
        "document_id": str(document.id),
        "title": document.title,
        "content_length": len(content),
        "chunk_count": len(chunk_records),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap
    }


@router.post("/{dataset_id}/documents/from-news")
async def create_documents_from_news(
    dataset_id: UUID,
    data: CreateFromNewsRequest,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """从热点新闻创建文档

    选择热点新闻文章，创建为文档并自动分片
    """
    import logging
    logger = logging.getLogger(__name__)

    from ...models.hot_news import HotArticle

    # 检查数据集是否存在
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    if not data.article_ids:
        raise HTTPException(status_code=400, detail="请选择至少一篇新闻文章")

    # 查询新闻文章
    articles_result = await db.execute(
        select(HotArticle).where(HotArticle.id.in_(data.article_ids))
    )
    articles = articles_result.scalars().all()

    if not articles:
        raise HTTPException(status_code=404, detail="未找到指定的新闻文章")

    created_docs = []
    for article in articles:
        # 使用文章标题和内容创建文档
        content = article.content or ""
        if not content and article.title:
            content = article.title  # 至少有标题

        if not content:
            continue

        document = Document(
            title=article.title or f"新闻_{article.id}",
            content=content,
            file_type="news",
            source_type="hot_news",
            doc_metadata={
                "article_id": str(article.id),
                "source_url": article.source_url,
                "published_at": article.published_at,
                "author": article.author,
                "tags": article.tags
            }
        )
        db.add(document)
        await db.flush()

        # 分片处理
        chunks = _split_text(content, chunk_size, chunk_overlap)

        chunk_records = []
        for i, chunk_text in enumerate(chunks):
            chunk_record = Chunk(
                doc_id=document.id,
                content=chunk_text["content"],
                chunk_index=i,
                start_char=chunk_text["start"],
                end_char=chunk_text["end"]
            )
            db.add(chunk_record)
            chunk_records.append(chunk_record)

        created_docs.append({
            "document_id": str(document.id),
            "title": document.title,
            "content_length": len(content),
            "chunk_count": len(chunk_records),
            "article_id": str(article.id)
        })

    await db.commit()

    logger.info(f"从新闻创建文档成功: 共 {len(created_docs)} 个文档")

    return {
        "created_count": len(created_docs),
        "documents": created_docs
    }


@router.post("/{dataset_id}/documents/text")
async def create_document_from_text(
    dataset_id: UUID,
    data: DocumentCreate,
    chunk_data: ChunkDocumentRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """从文本内容创建文档并自动分片"""
    import logging
    logger = logging.getLogger(__name__)

    # 检查数据集是否存在
    dataset_result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    if not data.content:
        raise HTTPException(status_code=400, detail="文档内容不能为空")

    # 创建文档
    document = Document(
        title=data.title or f"文档_{len(data.content)}字符",
        content=data.content,
        file_type=data.file_type or "text",
        source_type=data.source_type or "text_input"
    )
    db.add(document)
    await db.flush()

    # 分片参数
    chunk_size = chunk_data.chunk_size if chunk_data else 500
    chunk_overlap = chunk_data.chunk_overlap if chunk_data else 50

    # 分片处理
    chunks = _split_text(data.content, chunk_size, chunk_overlap)

    chunk_records = []
    for i, chunk_text in enumerate(chunks):
        chunk_record = Chunk(
            doc_id=document.id,
            content=chunk_text["content"],
            chunk_index=i,
            start_char=chunk_text["start"],
            end_char=chunk_text["end"]
        )
        db.add(chunk_record)
        chunk_records.append(chunk_record)

    await db.commit()

    return {
        "document_id": str(document.id),
        "title": document.title,
        "content_length": len(data.content),
        "chunk_count": len(chunk_records),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap
    }


def _split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[Dict[str, Any]]:
    """文本分片函数

    Args:
        text: 要分片的文本
        chunk_size: 每个分片的最大字符数
        chunk_overlap: 分片之间的重叠字符数

    Returns:
        分片列表，每个分片包含 content、start、end
    """
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        if end >= text_len:
            # 最后一个分片
            chunks.append({
                "content": text[start:].strip(),
                "start": start,
                "end": text_len
            })
            break

        # 寻找合适的分割点（优先在句子结尾）
        # 向前查找最近的句子结束符
        split_pos = end
        for i in range(end, max(start, end - 100), -1):
            if text[i] in ['。', '！', '？', '.', '!', '?', '\n', '；', ';']:
                split_pos = i + 1
                break

        # 如果没找到合适的分割点，尝试在空格处分割
        if split_pos == end and end < text_len:
            for i in range(end, max(start, end - 50), -1):
                if text[i] in [' ', '　', '\t']:
                    split_pos = i + 1
                    break

        chunk_content = text[start:split_pos].strip()
        if chunk_content:
            chunks.append({
                "content": chunk_content,
                "start": start,
                "end": split_pos
            })

        # 下一个分片的起始位置（考虑重叠）
        start = split_pos - chunk_overlap
        if start < 0:
            start = 0

    return chunks


@router.get("/{dataset_id}/documents/{doc_id}/chunks", response_model=ChunkListResponse)
async def list_document_chunks(
    dataset_id: UUID,
    doc_id: UUID,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """获取指定文档的所有分片（带原文位置标注）"""
    # 查询总数
    total_result = await db.execute(
        select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id)
    )
    total = total_result.scalar() or 0

    # 分页查询
    skip = (page - 1) * size
    chunks_result = await db.execute(
        select(Chunk)
        .where(Chunk.doc_id == doc_id)
        .order_by(Chunk.chunk_index)
        .offset(skip)
        .limit(size)
    )
    chunks = chunks_result.scalars().all()

    # 获取文档标题
    doc_result = await db.execute(select(Document.title, Document.content).where(Document.id == doc_id))
    doc_row = doc_result.fetchone()
    doc_title = doc_row.title if doc_row else None
    doc_content = doc_row.content if doc_row else None

    items = [
        ChunkResponse(
            id=c.id,
            doc_id=c.doc_id,
            content=c.content,
            chunk_index=c.chunk_index,
            start_char=c.start_char,
            end_char=c.end_char,
            milvus_id=c.milvus_id,
            document_title=doc_title
        )
        for c in chunks
    ]

    return ChunkListResponse(items=items, total=total)