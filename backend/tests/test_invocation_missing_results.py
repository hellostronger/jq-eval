# 缺失调用结果补齐（POST /invocations/{id}/retry）回归测试
#
# 真实故障：5 条题全部调用成功，但第 5 条的落库事务赶上远端 PG 连接中断，
# 结果表里既没有 success 也没有 failed 行。旧代码只按 status=failed 筛重试，
# 于是批次永久停在 4/5：评估要求 completed，重试又"没有需要重试的记录"，
# 只能人工改库或整批重跑（每条几分钟的真实调用成本）。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, QARecord, InvocationBatch, InvocationResult


class _FakeTask:
    def __init__(self):
        self.delayed_with = None

    def delay(self, batch_id, result_ids):
        self.delayed_with = (batch_id, result_ids)
        return self

    @property
    def id(self):
        return "fake-task"


@pytest.fixture
def fake_celery(monkeypatch):
    task = _FakeTask()
    monkeypatch.setattr("app.tasks.invocation_tasks.retry_invocation_task", task)
    return task


async def _batch(db: AsyncSession, dataset: Dataset, rag_system, status: str, results: dict):
    batch = InvocationBatch(
        name="gap-batch", dataset_id=dataset.id, rag_system_id=rag_system.id,
        total_count=len(results), status=status,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    for question, st in results.items():
        qr = QARecord(dataset_id=dataset.id, question=question, answer="a")
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        if st is not None:
            db.add(InvocationResult(
                batch_id=batch.id, qa_record_id=qr.id, rag_system_id=rag_system.id,
                question=question, answer="ans", status=st,
            ))
    await db.commit()
    return batch


@pytest.mark.asyncio
async def test_retry_backfills_missing_rows_and_dispatches(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset,
    sample_rag_system, fake_celery
):
    """结果表缺一行 → 重试自动补一条 failed 占位并派发，而不是回 0 条"""
    batch = await _batch(
        db_session, sample_dataset, sample_rag_system, "failed",
        {"q1": "success", "q2": "success", "q3": None},  # q3 的结果行丢了
    )

    resp = await client.post(f"/api/v1/invocations/{batch.id}/retry", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["retry_count"] == 1

    rows = (await db_session.execute(
        InvocationResult.__table__.select().where(InvocationResult.batch_id == batch.id)
    )).fetchall()
    assert len(rows) == 3
    placeholder = [r for r in rows if r._mapping["question"] == "q3"][0]
    assert placeholder._mapping["status"] == "failed"
    assert "未落库" in placeholder._mapping["error"]
    assert len(fake_celery.delayed_with[1]) == 1


@pytest.mark.asyncio
async def test_retry_does_not_backfill_running_batch(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system,
    fake_celery
):
    """批次还在跑时不补：worker 自己会写这条，抢写会重复调用一次"""
    batch = await _batch(
        db_session, sample_dataset, sample_rag_system, "running",
        {"q1": "success", "q2": None},
    )
    batch.total_count = 5
    batch.completed_count = 1
    batch.failed_count = 0
    await db_session.commit()

    resp = await client.post(f"/api/v1/invocations/{batch.id}/retry", json={})
    assert resp.status_code == 400
    assert "正在执行中" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_retry_on_complete_batch_reports_nothing_to_do(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system,
    fake_celery
):
    """结果齐全且无失败 → 仍然不动库里已有行"""
    batch = await _batch(
        db_session, sample_dataset, sample_rag_system, "completed",
        {"q1": "success", "q2": "success"},
    )

    resp = await client.post(f"/api/v1/invocations/{batch.id}/retry", json={})
    assert resp.status_code == 200
    assert resp.json()["retry_count"] == 0

    rows = (await db_session.execute(
        InvocationResult.__table__.select().where(InvocationResult.batch_id == batch.id)
    )).fetchall()
    assert len(rows) == 2
