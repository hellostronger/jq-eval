# 批次终态反推（_reconcile_terminal_state）回归测试
#
# 远端 PG/Redis 掉线常落在"最后一条跑完、写终态"这一步：每条调用结果都已逐条
# commit，却因为一条 UPDATE 失败被标成 failed，下游评估前置条件不满足，整批作废。
from contextlib import asynccontextmanager

import asyncio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.tasks.invocation_tasks as mod
from app.tasks.invocation_tasks import (
    _commit_with_retry,
    _reconcile_terminal_state,
    _write,
)
from app.models import Dataset, QARecord, RAGSystem
from app.models.invocation import InvocationBatch, InvocationResult


async def _batch_with_results(db: AsyncSession, dataset: Dataset, rag_system: RAGSystem,
                              total: int, success: int, **batch_kwargs) -> InvocationBatch:
    batch = InvocationBatch(
        name="reconcile-b", dataset_id=dataset.id, rag_system_id=rag_system.id,
        status="running", total_count=total, **batch_kwargs,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    for i in range(success):
        qr = QARecord(dataset_id=dataset.id, question=f"q{i}", answer="a")
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        db.add(InvocationResult(
            batch_id=batch.id, qa_record_id=qr.id, rag_system_id=rag_system.id,
            question=qr.question, answer="ans", contexts=["ctx"],
            retrieval_ids=["doc:p0001"], status="success",
        ))
    await db.commit()
    await db.refresh(batch)
    return batch


@pytest.fixture
def patched_db(monkeypatch, db_session: AsyncSession):
    """让任务里的 get_db_context 复用测试会话（默认指向远端 PG）"""
    calls = {"n": 0}

    @asynccontextmanager
    async def fake_db():
        calls["n"] += 1
        yield db_session

    monkeypatch.setattr(mod, "get_db_context", fake_db)
    return calls


@pytest.mark.asyncio
async def test_all_results_done_is_completed_even_with_error(
    db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system, patched_db
):
    """5 条全跑完、收尾时连接断了 → 批次仍是 completed，异常只记进 error"""
    batch = await _batch_with_results(db_session, sample_dataset, sample_rag_system, 5, 5)

    status = await _reconcile_terminal_state(
        batch.id, "connection was closed in the middle of operation"
    )
    await db_session.refresh(batch)
    assert status == "completed"
    assert batch.status == "completed"
    assert batch.completed_count == 5
    assert batch.failed_count == 0
    assert "closed" in (batch.error or "")


@pytest.mark.asyncio
async def test_partial_results_is_failed(db_session, sample_dataset, sample_rag_system, patched_db):
    """中途抛错、样本没跑完 → 老老实实落 failed，不能假装完成"""
    batch = await _batch_with_results(db_session, sample_dataset, sample_rag_system, 5, 2)

    status = await _reconcile_terminal_state(batch.id, "adapter 报错")
    await db_session.refresh(batch)
    assert status == "failed"
    assert batch.completed_count == 2
    assert batch.error == "adapter 报错"


@pytest.mark.asyncio
async def test_cancel_flag_wins_over_counts(
    db_session: AsyncSession, sample_dataset, sample_rag_system, patched_db
):
    """取消优先：已跑完的条数保留，但状态是 cancelled，标志回落到 False"""
    batch = await _batch_with_results(
        db_session, sample_dataset, sample_rag_system, 3, 3, cancel_requested=True
    )

    status = await _reconcile_terminal_state(batch.id)
    await db_session.refresh(batch)
    assert status == "cancelled"
    assert batch.completed_count == 3
    assert batch.cancel_requested is False


@pytest.mark.asyncio
async def test_retries_on_transient_connection_error(
    db_session: AsyncSession, sample_dataset, sample_rag_system, monkeypatch
):
    """写终态本身抖动时要换新 session 重试，而不是直接放弃"""
    batch = await _batch_with_results(db_session, sample_dataset, sample_rag_system, 2, 2)

    @asynccontextmanager
    async def flaky_db():
        flaky_db.n += 1
        if flaky_db.n == 1:
            raise ConnectionResetError("connection closed")
        yield db_session
    flaky_db.n = 0

    monkeypatch.setattr(mod, "get_db_context", flaky_db)
    real_sleep = asyncio.sleep
    # 退避等待在测试里没必要真等，但要拿替换前的 sleep，不然自引用递归
    monkeypatch.setattr(mod.asyncio, "sleep", lambda *_: real_sleep(0))

    status = await _reconcile_terminal_state(batch.id)
    assert flaky_db.n == 2
    assert status == "completed"


@pytest.mark.asyncio
async def test_result_write_survives_dropped_connection(
    db_session: AsyncSession, sample_dataset, sample_rag_system, monkeypatch
):
    """一条调用结果写不进去时换新 session 重做：几分钟的 RAG 调用不能白跑"""
    batch = await _batch_with_results(db_session, sample_dataset, sample_rag_system, 1, 0)
    qr = QARecord(dataset_id=sample_dataset.id, question="落库抖动", answer="a")
    db_session.add(qr)
    await db_session.commit()
    await db_session.refresh(qr)

    @asynccontextmanager
    async def flaky_db():
        flaky_db.n += 1
        if flaky_db.n == 1:
            raise ConnectionResetError("connection was closed in the middle of operation")
        yield db_session
    flaky_db.n = 0

    monkeypatch.setattr(mod, "get_db_context", flaky_db)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(mod.asyncio, "sleep", lambda *_: real_sleep(0))

    await _commit_with_retry(_write(
        batch_counters=(1, 0),
        batch_id=batch.id,
        qa_record_id=qr.id,
        rag_system_id=sample_rag_system.id,
        question=qr.question,
        answer="ans",
        contexts=["ctx"],
        retrieval_ids=["doc:p0001"],
        latency=250.0,
        status="success",
    ), batch.id)

    assert flaky_db.n == 2
    rows = (await db_session.execute(
        InvocationResult.__table__.select().where(InvocationResult.batch_id == batch.id)
    )).fetchall()
    assert len(rows) == 1
    assert rows[0]._mapping["status"] == "success"
    await db_session.refresh(batch)
    assert (batch.completed_count, batch.failed_count) == (1, 0)


@pytest.mark.asyncio
async def test_retry_write_replaces_old_row(
    db_session: AsyncSession, sample_dataset, sample_rag_system, patched_db
):
    """重试是"删旧行 + 插新行"同事务：不能留下两条同 QA 的结果"""
    batch = await _batch_with_results(db_session, sample_dataset, sample_rag_system, 1, 1)
    old = (await db_session.execute(
        InvocationResult.__table__.select().where(InvocationResult.batch_id == batch.id)
    )).fetchone()
    qr_id = old._mapping["qa_record_id"]

    await _commit_with_retry(_write(
        batch_id=batch.id,
        qa_record_id=qr_id,
        rag_system_id=sample_rag_system.id,
        question="重试后的新问题",
        answer="新答案",
        status="success",
        delete_result_id=old._mapping["id"],
    ), batch.id)

    rows = (await db_session.execute(
        InvocationResult.__table__.select().where(InvocationResult.batch_id == batch.id)
    )).fetchall()
    assert len(rows) == 1
    assert rows[0]._mapping["answer"] == "新答案"

