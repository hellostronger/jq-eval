# RAG系统调用批次路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from ...core.database import get_db
from ...models import InvocationBatch, InvocationResult, Dataset, QARecord, RAGSystem

router = APIRouter()


# Pydantic Schemas
class InvocationBatchCreate(BaseModel):
    name: str
    dataset_id: UUID
    rag_system_id: UUID


class InvocationBatchResponse(BaseModel):
    id: UUID
    name: str
    dataset_id: UUID
    rag_system_id: UUID
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvocationResultResponse(BaseModel):
    id: UUID
    batch_id: UUID
    qa_record_id: UUID
    rag_system_id: UUID
    question: str
    answer: Optional[str] = None
    contexts: Optional[List[str]] = None
    latency: Optional[float] = None
    status: str
    error: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("", response_model=InvocationBatchResponse)
async def create_invocation_batch(
    data: InvocationBatchCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建调用批次"""
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == data.dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    # 检查RAG系统是否存在
    result = await db.execute(select(RAGSystem).where(RAGSystem.id == data.rag_system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    # 获取QA记录数量
    result = await db.execute(
        select(func.count(QARecord.id)).where(QARecord.dataset_id == data.dataset_id)
    )
    total_count = result.scalar() or 0

    batch = InvocationBatch(
        name=data.name,
        dataset_id=data.dataset_id,
        rag_system_id=data.rag_system_id,
        total_count=total_count,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


@router.get("", response_model=List[InvocationBatchResponse])
async def list_invocation_batches(
    dataset_id: Optional[UUID] = None,
    rag_system_id: Optional[UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取调用批次列表"""
    query = select(InvocationBatch)
    if dataset_id:
        query = query.where(InvocationBatch.dataset_id == dataset_id)
    if rag_system_id:
        query = query.where(InvocationBatch.rag_system_id == rag_system_id)
    if status:
        query = query.where(InvocationBatch.status == status)
    result = await db.execute(query.order_by(InvocationBatch.created_at.desc()))
    return result.scalars().all()


@router.get("/{batch_id}", response_model=InvocationBatchResponse)
async def get_invocation_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取调用批次详情"""
    result = await db.execute(select(InvocationBatch).where(InvocationBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="调用批次不存在")
    return batch


@router.post("/{batch_id}/run")
async def run_invocation_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行调用批次"""
    result = await db.execute(select(InvocationBatch).where(InvocationBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="调用批次不存在")

    if batch.status == "running":
        raise HTTPException(status_code=400, detail="调用批次正在执行中")

    # 更新状态为运行中
    batch.status = "running"
    await db.commit()

    # 提交 Celery 异步任务
    from ...tasks.invocation_tasks import invocation_task
    task = invocation_task.delay(str(batch_id))

    return {
        "message": "调用批次已启动",
        "batch_id": str(batch_id),
        "task_id": task.id
    }


@router.get("/{batch_id}/results", response_model=List[InvocationResultResponse])
async def get_invocation_results(
    batch_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取调用批次的结果"""
    result = await db.execute(select(InvocationBatch).where(InvocationBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="调用批次不存在")

    results = await db.execute(
        select(InvocationResult)
        .where(InvocationResult.batch_id == batch_id)
        .offset(skip)
        .limit(limit)
    )
    return results.scalars().all()


@router.delete("/{batch_id}")
async def delete_invocation_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除调用批次"""
    result = await db.execute(select(InvocationBatch).where(InvocationBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="调用批次不存在")

    if batch.status == "running":
        raise HTTPException(status_code=400, detail="调用批次正在执行中，无法删除")

    await db.delete(batch)
    await db.commit()
    return {"message": "删除成功"}