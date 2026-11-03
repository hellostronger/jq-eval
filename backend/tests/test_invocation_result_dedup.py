# 调用结果去重：同一批次里一条 QA 只能留一行结果
#
# 真实故障：worker 被 SIGKILL 后 Celery 把 invocation_task 重投，重投从第一条重新开始跑，
# 旧实现每跑一条就 INSERT 一行。5 题的 smoke 批次因此长出 6 行（同一题两行 success），
# 而批次终态是"按结果表反推"的，于是 completed_count=6、total_count=5：
#   - 进度条超过 100%，看不出批次到底跑完没有；
#   - 下游评估把这 6 行都当样本，那道题被双计一次，均值跟着偏。
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, QARecord, RAGSystem
from app.models.invocation import InvocationBatch, InvocationResult


class _FakeTask:
    def update_state(self, *args, **kwargs):
        pass


class _Adapter:
    """每次都返回成功，用来模拟重投后"同样的题再跑一遍" """

    system_type = "direct_llm"

    def __init__(self):
        self.calls = []

    async def query(self, question, contexts=None, conversation_id=None, **kwargs):
        from app.services.adapters.base import RAGResponse
        self.calls.append(question)
        return RAGResponse(answer=f"答：{question}", success=True, retrieval_ids=["c1"])


@pytest.fixture
def env(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    from app.tasks import invocation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)
    adapter = _Adapter()
    monkeypatch.setattr(invocation_tasks.AdapterFactory, "create", lambda *a, **k: adapter)
    return type("Env", (), {"db": db_session, "adapter": adapter, "mod": invocation_tasks})()


async def _seed(db: AsyncSession, n: int = 3) -> InvocationBatch:
    ds = Dataset(name="DS", description="d", status="active")
    rag = RAGSystem(name="RAG", system_type="direct_llm", description="d",
                    connection_config={"provider": "openai"}, status="active")
    db.add_all([ds, rag])
    await db.flush()
    batch = InvocationBatch(name="B", dataset_id=ds.id, rag_system_id=rag.id,
                            status="pending", total_count=n)
    db.add(batch)
    for i in range(n):
        db.add(QARecord(dataset_id=ds.id, question=f"问题{i}", answer="答案"))
    await db.commit()
    return batch


@pytest.mark.asyncio
async def test_rerun_replaces_rows_instead_of_appending(env):
    """同一批次重跑（含 Celery 重投）后，每条 QA 仍只有一行结果、计数不超额"""
    db = env.db
    batch = await _seed(db, n=3)

    await env.mod._run_invocation(_FakeTask(), batch.id)
    first_rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    assert len(first_rows) == 3

    await env.mod._run_invocation(_FakeTask(), batch.id)
    rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    assert len(rows) == 3, "重投追加了重复行"
    assert len({r.qa_record_id for r in rows}) == 3

    await db.refresh(batch)
    assert (batch.completed_count, batch.total_count) == (3, 3), "重复行使进度超过 100%"
    assert batch.status == "completed"


@pytest.mark.asyncio
async def test_terminal_counters_ignore_duplicate_history(env):
    """库里已有的重复行（老数据）也不能把终态计数顶出 total_count"""
    db = env.db
    batch = await _seed(db, n=2)
    qas = (await db.execute(select(QARecord).where(QARecord.dataset_id == batch.dataset_id))).scalars().all()

    # 第一条 QA 造两行（一失败一成功，成功在后），第二条 QA 一行失败。
    # 逐条 commit：终态按 created_at 取"最后一次调用"，同批写入的时间戳相同会不稳定。
    for qa_index, st in ((0, "failed"), (0, "success"), (1, "failed")):
        db.add(InvocationResult(batch_id=batch.id, qa_record_id=qas[qa_index].id,
                                rag_system_id=batch.rag_system_id,
                                question=f"问题{qa_index}", status=st))
        await db.commit()

    status = await env.mod._reconcile_terminal_state(batch.id)
    await db.refresh(batch)
    assert status == "completed"
    assert batch.completed_count == 1, "按行数统计会把重复行算成两条成功"
    assert batch.failed_count == 1
    assert batch.completed_count + batch.failed_count == batch.total_count
