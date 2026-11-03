# 调用批次协作式取消回归测试
#
# 单条 RAG 调用 8min+、一批几十分钟，之前只能 SIGKILL worker：
# 批次状态永久停在 running，取消等于"什么都没发生"。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TaskCancelled
from app.models import Dataset, InvocationBatch
from app.tasks.invocation_tasks import _raise_if_cancelled


async def _running_batch(db: AsyncSession, dataset: Dataset, rag_system) -> InvocationBatch:
    batch = InvocationBatch(
        name="cancelling-batch", dataset_id=dataset.id,
        rag_system_id=rag_system.id, status="running", total_count=5,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


@pytest.mark.asyncio
async def test_cancel_sets_flag_and_reports_it(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    batch = await _running_batch(db_session, sample_dataset, sample_rag_system)

    resp = await client.post(f"/api/v1/invocations/{batch.id}/cancel")
    assert resp.status_code == 200, resp.text

    await db_session.refresh(batch)
    assert batch.cancel_requested is True
    # 响应模型必须带出该标志，否则界面无法把按钮置灰、用户会反复点
    detail = await client.get(f"/api/v1/invocations/{batch.id}")
    assert detail.json()["cancel_requested"] is True


@pytest.mark.asyncio
async def test_cancel_rejects_batch_not_running(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    batch = await _running_batch(db_session, sample_dataset, sample_rag_system)
    batch.status = "completed"
    await db_session.commit()

    resp = await client.post(f"/api/v1/invocations/{batch.id}/cancel")
    assert resp.status_code == 400
    assert "未在运行中" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_force_cancel_finalizes_orphan_batch(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    """worker 被杀后的残留 running 批次：协作式取消没人读标志，必须能强制收尾，
    否则 batch_in_flight 一直判"在飞"，重试与删除都被挡死"""
    batch = await _running_batch(db_session, sample_dataset, sample_rag_system)

    resp = await client.post(f"/api/v1/invocations/{batch.id}/cancel?force=true")
    assert resp.status_code == 200, resp.text

    await db_session.refresh(batch)
    assert batch.status == "cancelled"
    assert batch.cancel_requested is False


@pytest.mark.asyncio
async def test_worker_stops_at_next_item_when_flag_set(
    db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    """标志位真正被任务读到才算取消，只改库不生效是假取消"""
    batch = await _running_batch(db_session, sample_dataset, sample_rag_system)
    await _raise_if_cancelled(db_session, batch.id)  # 未置标志应正常返回

    batch.cancel_requested = True
    await db_session.commit()

    with pytest.raises(TaskCancelled):
        await _raise_if_cancelled(db_session, batch.id)
