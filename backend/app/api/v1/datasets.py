# 数据集管理路由
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Dataset, QARecord

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
    db: AsyncSession = Depends(get_db)
):
    """导入数据"""
    # TODO: 实现文件解析和数据导入
    return {
        "message": "数据导入任务已创建",
        "filename": file.filename,
        "dataset_id": str(dataset_id)
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