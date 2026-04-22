# 压测任务API路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models import LoadTest, LoadTestStatus, RAGSystem, Dataset

router = APIRouter()


# Pydantic Schemas
class LoadTestCreate(BaseModel):
    name: str
    description: Optional[str] = None
    rag_system_id: UUID
    test_type: str  # first_token / full_response
    latency_threshold: float  # 时延阈值（秒）
    concurrency: int  # 并发数
    dataset_id: Optional[UUID] = None
    questions: Optional[List[str]] = None


class LoadTestUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    test_type: Optional[str] = None
    latency_threshold: Optional[float] = None
    concurrency: Optional[int] = None
    dataset_id: Optional[UUID] = None
    questions: Optional[List[str]] = None


class LoadTestResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    rag_system_id: UUID
    test_type: str
    latency_threshold: float
    concurrency: int
    dataset_id: Optional[UUID] = None
    questions: Optional[List[str]] = None
    status: str
    progress: int
    error: Optional[str] = None
    result: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("", response_model=LoadTestResponse)
async def create_load_test(
    data: LoadTestCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建压测任务"""
    # 检查RAG系统是否存在
    result = await db.execute(select(RAGSystem).where(RAGSystem.id == data.rag_system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    # 如果指定了数据集，检查数据集是否存在
    if data.dataset_id:
        result = await db.execute(select(Dataset).where(Dataset.id == data.dataset_id))
        dataset = result.scalar_one_or_none()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    load_test = LoadTest(
        name=data.name,
        description=data.description,
        rag_system_id=data.rag_system_id,
        test_type=data.test_type,
        latency_threshold=data.latency_threshold,
        concurrency=data.concurrency,
        dataset_id=data.dataset_id,
        questions=data.questions,
        status=LoadTestStatus.PENDING.value
    )
    db.add(load_test)
    await db.commit()
    await db.refresh(load_test)
    return load_test


@router.get("", response_model=List[LoadTestResponse])
async def list_load_tests(
    rag_system_id: Optional[UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取压测任务列表"""
    query = select(LoadTest)
    if rag_system_id:
        query = query.where(LoadTest.rag_system_id == rag_system_id)
    if status:
        query = query.where(LoadTest.status == status)
    result = await db.execute(query.order_by(LoadTest.created_at.desc()))
    return result.scalars().all()


@router.get("/{load_test_id}", response_model=LoadTestResponse)
async def get_load_test(
    load_test_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取压测任务详情"""
    result = await db.execute(select(LoadTest).where(LoadTest.id == load_test_id))
    load_test = result.scalar_one_or_none()
    if not load_test:
        raise HTTPException(status_code=404, detail="压测任务不存在")
    return load_test


@router.put("/{load_test_id}", response_model=LoadTestResponse)
async def update_load_test(
    load_test_id: UUID,
    data: LoadTestUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新压测任务"""
    result = await db.execute(select(LoadTest).where(LoadTest.id == load_test_id))
    load_test = result.scalar_one_or_none()
    if not load_test:
        raise HTTPException(status_code=404, detail="压测任务不存在")

    if load_test.status == LoadTestStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="运行中的任务无法修改")

    # 更新字段
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(load_test, key, value)

    await db.commit()
    await db.refresh(load_test)
    return load_test


@router.delete("/{load_test_id}")
async def delete_load_test(
    load_test_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除压测任务"""
    result = await db.execute(select(LoadTest).where(LoadTest.id == load_test_id))
    load_test = result.scalar_one_or_none()
    if not load_test:
        raise HTTPException(status_code=404, detail="压测任务不存在")

    if load_test.status == LoadTestStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="运行中的任务无法删除")

    await db.delete(load_test)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{load_test_id}/run")
async def run_load_test(
    load_test_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行压测任务"""
    result = await db.execute(select(LoadTest).where(LoadTest.id == load_test_id))
    load_test = result.scalar_one_or_none()
    if not load_test:
        raise HTTPException(status_code=404, detail="压测任务不存在")

    if load_test.status == LoadTestStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="任务正在执行中")

    # 更新状态为运行中
    load_test.status = LoadTestStatus.RUNNING.value
    await db.commit()

    # 提交 Celery 异步任务
    from ...tasks.load_test_tasks import load_test_task
    task = load_test_task.delay(str(load_test_id))

    return {
        "message": "压测任务已启动",
        "load_test_id": str(load_test_id),
        "task_id": task.id
    }