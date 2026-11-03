# RAG系统调用批次路由
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from ...core.database import get_db
from ...services.dataset.qa_scope import missing_qa_in_scope
from ._common import get_or_404, start_task, batch_in_flight
from ...core.utc_datetime import UTCDatetime
from ...models import InvocationBatch, InvocationResult, Dataset, QARecord, RAGSystem

router = APIRouter()


# Pydantic Schemas
class InvocationBatchCreate(BaseModel):
    name: str
    dataset_id: UUID
    rag_system_id: UUID
    # 取样范围：大语料（MultiHop 2556 题、UltraData 每题几分钟）先跑一小段试点，
    # 不用为此再建一个重复数据集。留空＝沿用旧行为，跑整个数据集
    qa_limit: Optional[int] = Field(None, ge=1, description="只跑前 N 条（按创建时间排序）")
    qa_offset: Optional[int] = Field(None, ge=0, description="跳过前 M 条，配合 qa_limit 分页试点")


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
    # 取消请求是否已提交（界面据此把「取消」按钮置灰，避免重复点击以为没生效）
    cancel_requested: bool = False
    qa_limit: Optional[int] = None
    qa_offset: Optional[int] = None
    started_at: Optional[UTCDatetime] = None
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None

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
    retrieval_ids: Optional[List[str]] = None  # 检索命中的 chunk/page id，检索指标与 badcase 归因都靠它
    latency: Optional[float] = None
    status: str
    error: Optional[str] = None
    created_at: Optional[UTCDatetime] = None
    ground_truth: Optional[str] = None  # 标准答案（从QA记录关联获取）

    class Config:
        from_attributes = True


class RetryRequest(BaseModel):
    result_ids: Optional[List[UUID]] = None  # 指定重试的结果ID列表，为空则重试全部失败


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

    # 数据集里的总条数，取样范围要按它裁剪
    result = await db.execute(
        select(func.count(QARecord.id)).where(QARecord.dataset_id == data.dataset_id)
    )
    dataset_count = result.scalar() or 0
    if dataset_count == 0:
        raise HTTPException(status_code=400, detail="数据集里没有问答记录，无法发起调用")

    qa_limit = data.qa_limit
    qa_offset = data.qa_offset or 0
    if qa_limit is not None:
        if qa_offset >= dataset_count:
            raise HTTPException(
                status_code=400,
                detail=f"取样起点 {qa_offset} 已超出数据集条数 {dataset_count}，这一批不会有任何题目",
            )
        qa_limit = min(qa_limit, dataset_count - qa_offset)
    elif qa_offset:
        # 只给偏移不给条数＝从这一条起跑到结尾，同样不能越过末尾
        if qa_offset >= dataset_count:
            raise HTTPException(
                status_code=400,
                detail=f"取样起点 {qa_offset} 已超出数据集条数 {dataset_count}，这一批不会有任何题目",
            )

    # total_count 必须是"取样范围内的条数"，不是数据集总条数：
    # 界面按它显示进度、终态按它判定跑完没有，口径不一致就会永远差一截
    total_count = qa_limit if qa_limit is not None else dataset_count - qa_offset

    batch = InvocationBatch(
        name=data.name,
        dataset_id=data.dataset_id,
        rag_system_id=data.rag_system_id,
        total_count=total_count,
        qa_limit=qa_limit,
        qa_offset=qa_offset or None,
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
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")
    return batch


@router.post("/{batch_id}/run")
async def run_invocation_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行调用批次"""
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    if batch_in_flight(batch):
        raise HTTPException(status_code=400, detail="调用批次正在执行中")

    # 置运行中并派发；broker 不可达时状态自动回滚
    from ...tasks.invocation_tasks import invocation_task
    task = await start_task(db, batch, lambda: invocation_task.delay(str(batch_id)))

    return {
        "message": "调用批次已启动",
        "batch_id": str(batch_id),
        "task_id": task.id
    }


@router.post("/{batch_id}/cancel")
async def cancel_invocation_batch(
    batch_id: UUID,
    force: bool = Query(False, description="worker 已不在跑（进程被杀/掉线）时立即落库 cancelled"),
    db: AsyncSession = Depends(get_db)
):
    """取消运行中的调用批次（协作式）

    单条 RAG 调用可能 8min+，一批要跑几十分钟。此前只能硬杀 worker，
    批次状态永久停在 running：既不能重试（"正在执行中"），也无法判定结果，
    还占着队列。改为置标志位，由 worker 在下一条 QA 边界停下并落库 cancelled，
    已完成的每条结果保留（每次调用都是真实的 token 开销，不该丢）。

    force：协作式取消依赖 worker 还活着。进程被杀/机器重启后标志没人读，
    批次会永远停在 running 且挡死重试（batch_in_flight 按"还有没跑完的条目"
    判定在飞）。这种残留状态由用户显式 force 收尾。
    """
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    if batch.status not in ("running", "pending"):
        raise HTTPException(status_code=400, detail="调用批次未在运行中，无法取消")

    if not force:
        batch.cancel_requested = True
        await db.commit()
        return {
            "message": "取消请求已提交，批次将在当前这条问答结束后停止",
            "batch_id": str(batch_id),
        }

    batch.status = "cancelled"
    batch.error = "批次已被用户强制取消（worker 不在运行）"
    batch.cancel_requested = False
    batch.completed_at = datetime.utcnow()
    await db.commit()
    return {"message": "批次已强制取消", "batch_id": str(batch_id)}


@router.post("/{batch_id}/retry")
async def retry_invocation_batch(
    batch_id: UUID,
    data: RetryRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """重试调用批次（支持重试全部失败或指定条目）"""
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    if batch_in_flight(batch):
        raise HTTPException(status_code=400, detail="调用批次正在执行中，无法重试")

    # 确定要重试的结果
    if data and data.result_ids:
        # 重试指定的结果（必须属于本批次，否则会重跑他批结果并错计本批数量）
        results_to_retry = await db.execute(
            select(InvocationResult).where(
                InvocationResult.id.in_(data.result_ids),
                InvocationResult.batch_id == batch_id,
            )
        )
        retry_list = results_to_retry.scalars().all()
    else:
        # 重试所有失败的结果
        results_to_retry = await db.execute(
            select(InvocationResult).where(
                InvocationResult.batch_id == batch_id,
                InvocationResult.status == "failed"
            )
        )
        retry_list = list(results_to_retry.scalars().all())

        # 补齐"根本没有结果行"的 QA：调用跑完了但落库时连接断了，这条题目在
        # 批次里既不是 success 也不是 failed，而是凭空消失。只按 failed 筛永远
        # 找不到它，批次会永久停在 n-1/total，评估又要求 completed → 死锁。
        # 只在批次已落定终态时补：running 的批次 worker 还可能自己写这条。
        if batch.status in ("completed", "failed", "cancelled"):
            have = await db.execute(
                select(InvocationResult.qa_record_id).where(InvocationResult.batch_id == batch_id)
            )
            covered = {r[0] for r in have.all()}
            # 只在批次的取样范围内补齐：不带范围会给只跑 40 题的批次
            # 补出整个数据集的占位行，total_count 与进度瞬间失真
            for qa in await missing_qa_in_scope(db, batch, covered):
                placeholder = InvocationResult(
                    batch_id=batch_id,
                    qa_record_id=qa.id,
                    rag_system_id=batch.rag_system_id,
                    question=qa.question,
                    status="failed",
                    error="调用结果未落库（上一轮执行中或收尾时连接中断）",
                )
                db.add(placeholder)
                retry_list.append(placeholder)
            if retry_list:
                # placeholder 要有主键才能进 result_ids，先 flush
                await db.flush()
                await db.commit()

    if not retry_list:
        return {"message": "没有需要重试的记录", "batch_id": str(batch_id), "retry_count": 0}

    # 提交重试任务
    from ...tasks.invocation_tasks import retry_invocation_task
    result_ids = [str(r.id) for r in retry_list]
    task = retry_invocation_task.delay(str(batch_id), result_ids)

    return {
        "message": "重试任务已启动",
        "batch_id": str(batch_id),
        "task_id": task.id,
        "retry_count": len(retry_list)
    }


@router.post("/{batch_id}/results/{result_id}/retry")
async def retry_single_result(
    batch_id: UUID,
    result_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """重试单条调用结果"""
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    if batch_in_flight(batch):
        raise HTTPException(status_code=400, detail="调用批次正在执行中，无法重试")

    result = await db.execute(
        select(InvocationResult).where(
            InvocationResult.id == result_id,
            InvocationResult.batch_id == batch_id,
        )
    )
    inv_result = result.scalar_one_or_none()
    if not inv_result:
        raise HTTPException(status_code=404, detail="调用结果不存在")

    # 提交重试任务
    from ...tasks.invocation_tasks import retry_invocation_task
    task = retry_invocation_task.delay(str(batch_id), [str(result_id)])

    return {
        "message": "重试任务已启动",
        "batch_id": str(batch_id),
        "result_id": str(result_id),
        "task_id": task.id
    }


@router.get("/{batch_id}/results", response_model=List[InvocationResultResponse])
async def get_invocation_results(
    batch_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取调用批次的结果"""
    await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    # 关联QA记录获取ground_truth
    query = (
        select(InvocationResult, QARecord.ground_truth)
        .join(QARecord, InvocationResult.qa_record_id == QARecord.id)
        .where(InvocationResult.batch_id == batch_id)
    )
    if status:
        query = query.where(InvocationResult.status == status)

    # 稳定排序，防翻页重复/漏行
    query = query.order_by(InvocationResult.id).offset(skip).limit(limit)
    results = await db.execute(query)
    rows = results.all()

    # 转换结果
    response_items = []
    for row in rows:
        inv_result = row[0]
        ground_truth = row[1]
        item = {
            "id": inv_result.id,
            "batch_id": inv_result.batch_id,
            "qa_record_id": inv_result.qa_record_id,
            "rag_system_id": inv_result.rag_system_id,
            "question": inv_result.question,
            "answer": inv_result.answer,
            "contexts": inv_result.contexts,
            "retrieval_ids": inv_result.retrieval_ids,
            "latency": inv_result.latency,
            "status": inv_result.status,
            "error": inv_result.error,
            "created_at": inv_result.created_at,
            "ground_truth": ground_truth,
        }
        response_items.append(item)

    return response_items


@router.get("/{batch_id}/stats")
async def get_invocation_stats(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取调用批次的统计信息"""
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    # 统计各状态数量
    stats = await db.execute(
        select(
            InvocationResult.status,
            func.count(InvocationResult.id)
        ).where(InvocationResult.batch_id == batch_id).group_by(InvocationResult.status)
    )
    status_counts = {row[0]: row[1] for row in stats.fetchall()}

    return {
        "batch_id": str(batch_id),
        "total": batch.total_count,
        "completed": batch.completed_count,
        "failed": batch.failed_count,
        "status_counts": status_counts
    }


@router.delete("/{batch_id}")
async def delete_invocation_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除调用批次"""
    batch = await get_or_404(db, InvocationBatch, batch_id, "调用批次不存在")

    if batch_in_flight(batch):
        raise HTTPException(status_code=400, detail="调用批次正在执行中，无法删除")

    await db.delete(batch)
    await db.commit()
    return {"message": "删除成功"}