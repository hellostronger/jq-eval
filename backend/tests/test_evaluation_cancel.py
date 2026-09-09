# 评估任务取消机制回归测试
#
# 曾经的 bug：cancel 端点"只改库（status=failed）不杀任务"是假取消——
# Celery 任务继续跑完，结束时把状态覆写回 completed。用户看到"已取消"
# 但任务其实照常消耗 token 完成。修复为协作式取消：
#   cancel → 置 cancel_requested 标志 → worker 在批次边界检查 → 落库 cancelled
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.core.exceptions import TaskCancelled
from app.models import Dataset
from app.models.evaluation import Evaluation, EvaluationStatus


async def _running_eval(db: AsyncSession, dataset: Dataset) -> Evaluation:
    ev = Evaluation(
        name="cancel-test", dataset_id=dataset.id,
        metrics=["bleu"], status=EvaluationStatus.RUNNING, batch_size=2,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


@pytest.mark.asyncio
async def test_cancel_endpoint_sets_cooperative_flag(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """取消端点：置 cancel_requested 而不是假装 failed；running 校验仍在"""
    ev = await _running_eval(db_session, sample_dataset)

    resp = await client.post(f"/api/v1/evaluations/{ev.id}/cancel")
    assert resp.status_code == 200

    await db_session.refresh(ev)
    assert ev.cancel_requested is True, "应置协作式取消标志"
    # 状态此时仍是 running——由 worker 检测到标志后落库 cancelled，
    # 端点不得提前把它改成 failed/completed 掩盖真实执行
    assert ev.status == EvaluationStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_non_running_returns_400(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """非 running 状态不可取消"""
    ev = Evaluation(name="pending-eval", dataset_id=sample_dataset.id,
                    metrics=["bleu"], status=EvaluationStatus.PENDING, batch_size=2)
    db_session.add(ev)
    await db_session.commit()

    resp = await client.post(f"/api/v1/evaluations/{ev.id}/cancel")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_engine_raises_when_cancel_requested(db_session: AsyncSession, sample_dataset: Dataset):
    """worker 批次边界检查：cancel_requested 置位后 evaluate_batch 抛 TaskCancelled"""
    from app.services.metrics.engine import MetricEngine

    ev = await _running_eval(db_session, sample_dataset)

    async def _check_cancel():
        from sqlalchemy import select
        flag = await db_session.execute(
            select(Evaluation.cancel_requested).where(Evaluation.id == ev.id)
        )
        if flag.scalar():
            raise TaskCancelled()

    # 模拟用户已点取消
    ev.cancel_requested = True
    await db_session.commit()

    engine = MetricEngine(metric_configs=[])
    with pytest.raises(TaskCancelled):
        await engine.evaluate_batch(
            qa_records=[{"question": "q", "answer": "a"}],
            batch_size=1,
            check_cancel=_check_cancel,
        )
