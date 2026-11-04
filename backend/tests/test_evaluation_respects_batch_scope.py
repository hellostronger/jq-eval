# 评估范围必须跟着调用批次的取样范围走
#
# 现场：给 2556 题的 MultiHop 数据集建了 50 题的取样批次，复用该批次发起检索
# 指标评估——评估任务却按整个数据集取 QA，范围外的 2506 条没有调用结果，
# 只能拿空上下文参与打分。进度条停在 0%（分母是 2556），十几分钟只写出几十行，
# 而最终的 hit@k / recall 会被稀释成"看着像大面积漏召"的假数字。
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from app.models.dataset import Dataset, QARecord
from app.models.evaluation import EvalResult, Evaluation
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem

pytestmark = pytest.mark.asyncio


class FakeTask:
    def update_state(self, *args, **kwargs):
        pass


@pytest.fixture
def scope_env(monkeypatch, db_session):
    from contextlib import asynccontextmanager

    from app.tasks import evaluation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(evaluation_tasks, "get_db_context", fake_ctx)
    return db_session


async def _seed(db, total=6, qa_limit=3, qa_offset=1):
    dataset = Dataset(name="DS", description="d", status="active")
    db.add(dataset)
    await db.flush()
    rag = RAGSystem(name="RAG", system_type="direct_llm", description="d",
                    connection_config={"provider": "openai"}, status="active")
    db.add(rag)
    await db.flush()

    base = datetime(2026, 1, 1)
    records = []
    for i in range(total):
        # created_at 决定取样顺序，必须拉开间隔，否则 limit/offset 取到的是随机一批
        qa = QARecord(dataset_id=dataset.id, question=f"问题{i}", answer=f"答案{i}",
                      ground_truth=f"答案{i}", created_at=base + timedelta(minutes=i))
        db.add(qa)
        records.append(qa)
    await db.flush()

    batch = InvocationBatch(name="B", dataset_id=dataset.id, rag_system_id=rag.id,
                            status="completed", qa_limit=qa_limit, qa_offset=qa_offset,
                            total_count=qa_limit, completed_count=qa_limit)
    db.add(batch)
    await db.flush()

    scoped = records[qa_offset:qa_offset + qa_limit]
    for qa in scoped:
        db.add(InvocationResult(
            batch_id=batch.id, qa_record_id=qa.id, rag_system_id=rag.id,
            question=qa.question, answer=qa.ground_truth, contexts=["上下文"],
            retrieval_ids=["p1"], status="success",
        ))
    await db.commit()
    return dataset, batch, scoped


async def _run(db, batch):
    from app.tasks.evaluation_tasks import _run_evaluation

    evaluation = Evaluation(
        name="E", dataset_id=batch.dataset_id, invocation_batch_id=batch.id,
        reuse_invocation=True, metrics=["hit_rate_k"], status="pending",
    )
    db.add(evaluation)
    await db.commit()
    await _run_evaluation(FakeTask(), evaluation.id)
    await db.refresh(evaluation)
    rows = (await db.execute(
        select(EvalResult).where(EvalResult.eval_id == evaluation.id)
    )).scalars().all()
    return evaluation, rows


async def test_evaluation_only_covers_batch_scope(scope_env):
    db = scope_env
    _dataset, batch, scoped = await _seed(db)
    evaluation, rows = await _run(db, batch)

    assert len(rows) == 3, "评估把取样范围外的题目也算进来了"
    assert {str(r.qa_record_id) for r in rows} == {str(q.id) for q in scoped}
    summary = evaluation.summary or {}
    assert summary["total_records"] == 3, "分母应当是范围内条数"
    assert summary["scored_records"] == 3


async def test_evaluation_without_batch_still_covers_whole_dataset(scope_env):
    """没挂调用批次时行为不变：整数据集评估不该被取样逻辑误伤"""
    db = scope_env
    dataset, batch, _scoped = await _seed(db)
    from app.tasks.evaluation_tasks import _run_evaluation

    evaluation = Evaluation(name="E2", dataset_id=dataset.id, reuse_invocation=False,
                            metrics=["rouge_l"], status="pending")
    db.add(evaluation)
    await db.commit()
    await _run_evaluation(FakeTask(), evaluation.id)

    rows = (await db.execute(
        select(EvalResult).where(EvalResult.eval_id == evaluation.id)
    )).scalars().all()
    assert len(rows) == 6
