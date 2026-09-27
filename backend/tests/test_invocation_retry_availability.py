# 调用批次「重试」可用性回归测试
#
# 真实故障：批次 status 永久停在 running（任务被 worker 丢掉/进程被杀，
# 或重试任务在置 running 之后夭折），而此时 14 条 QA 全部已有结果、
# completed_at 也已写入。旧代码只信 status，于是
# POST /retry 一律 400「调用批次正在执行中，无法重试」，
# 批次里的失败记录再也重试不了，界面上表现为"点了重试没反应"。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._common import batch_in_flight
from app.models import Dataset, InvocationBatch, RAGSystem


class _Batch:
    """最小批次替身，避免为测一个纯函数去建库"""

    def __init__(self, status, total, completed, failed):
        self.status = status
        self.total_count = total
        self.completed_count = completed
        self.failed_count = failed


class TestBatchInFlight:
    def test_not_running_is_never_in_flight(self):
        for status in ("completed", "failed", "pending", "cancelled"):
            assert batch_in_flight(_Batch(status, 14, 10, 4)) is False

    def test_running_with_outstanding_work_is_in_flight(self):
        # 刚开始跑：还没有任何结果
        assert batch_in_flight(_Batch("running", 14, 0, 0)) is True
        # 跑了一半
        assert batch_in_flight(_Batch("running", 14, 6, 2)) is True

    def test_running_but_every_result_exists_is_not_in_flight(self):
        """这就是线上那条卡住的批次：10 成功 + 4 失败 = 14 = total，没有任何待办"""
        assert batch_in_flight(_Batch("running", 14, 10, 4)) is False

    def test_running_with_unknown_total_is_conservatively_in_flight(self):
        assert batch_in_flight(_Batch("running", 0, 0, 0)) is True
        assert batch_in_flight(_Batch("running", None, 0, 0)) is True

    def test_unknown_counters_with_known_total_stay_in_flight(self):
        """计数为 None（还没统计出来）时按在跑处理，保守优先"""
        assert batch_in_flight(_Batch("running", 14, None, None)) is True


@pytest.mark.asyncio
async def test_retry_allowed_on_batch_stuck_in_running(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_dataset: Dataset,
    sample_rag_system,
):
    """卡在 running 但结果已齐全的批次，重试请求不应被 400 挡掉"""
    batch = InvocationBatch(
        name="stuck-running",
        dataset_id=sample_dataset.id,
        rag_system_id=sample_rag_system.id,
        total_count=14,
        completed_count=10,
        failed_count=4,
        status="running",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)

    # 没有可重试的失败结果时，接口应走到"没有需要重试的记录"分支
    # （说明没被 running 守卫拦下），而不是 400
    response = await client.post(f"/api/v1/invocations/{batch.id}/retry", json={})
    assert response.status_code == 200, response.text
    assert response.json()["retry_count"] == 0
    assert "正在执行中" not in response.json()["message"]


@pytest.mark.asyncio
async def test_retry_still_blocked_while_genuinely_running(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_dataset: Dataset,
    sample_rag_system,
):
    """真有未完成条目时，守卫必须照常拦截"""
    batch = InvocationBatch(
        name="really-running",
        dataset_id=sample_dataset.id,
        rag_system_id=sample_rag_system.id,
        total_count=14,
        completed_count=3,
        failed_count=0,
        status="running",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)

    response = await client.post(f"/api/v1/invocations/{batch.id}/retry", json={})
    assert response.status_code == 400
    assert "正在执行中" in response.json()["detail"]
