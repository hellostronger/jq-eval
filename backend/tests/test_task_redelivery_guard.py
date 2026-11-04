# 任务重复投递（重投）不能再跑一遍已经落终态的批次/评估
#
# 现场：远端 Redis 断线，kombu 重连时把"已投递未 ack"的消息重新入队
# （日志里的 Restoring N unacknowledged message(s)）。于是
#   - 已完成的调用批次被整批重跑，每条都是几分钟的真实 RAG 开销；
#   - 已被用户取消的评估复活，重新打了一轮 ragas（5 分钟），还撞上当天模型配额上限。
# 手工重跑是另一条路：POST /run 与 /retry 都会先把状态置回 running 再派发，
# 所以终态拦截不会把用户自己要跑的那次挡掉。
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord
from app.models.evaluation import Evaluation, EvaluationStatus
from app.models.invocation import InvocationBatch, InvocationResult


class _CountingAdapter:
    system_type = "direct_llm"

    def __init__(self):
        self.calls = []

    async def query(self, question, contexts=None, conversation_id=None, **kwargs):
        from app.services.adapters.base import RAGResponse
        self.calls.append(question)
        return RAGResponse(answer="答", success=True)


@pytest.fixture
def invocation_env(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    from app.tasks import invocation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)
    adapter = _CountingAdapter()
    monkeypatch.setattr(invocation_tasks.AdapterFactory, "create", lambda *a, **k: adapter)
    return type("Env", (), {"db": db_session, "adapter": adapter, "mod": invocation_tasks})()


async def _batch(db: AsyncSession, status: str, n: int = 2) -> InvocationBatch:
    ds = Dataset(name="DS", description="d", status="active")
    from app.models.rag_system import RAGSystem
    rag = RAGSystem(name="RAG", system_type="direct_llm", description="d",
                    connection_config={"provider": "openai"}, status="active")
    db.add_all([ds, rag])
    await db.flush()
    batch = InvocationBatch(name="B", dataset_id=ds.id, rag_system_id=rag.id,
                            status=status, total_count=n)
    db.add(batch)
    for i in range(n):
        db.add(QARecord(dataset_id=ds.id, question=f"问题{i}", answer="答案"))
    await db.commit()
    return batch


class _FakeTask:
    def update_state(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
async def test_redelivered_invocation_task_does_not_recall_rag(invocation_env, terminal):
    db = invocation_env.db
    batch = await _batch(db, terminal)

    out = await invocation_env.mod._run_invocation(_FakeTask(), batch.id)

    assert out["status"] == f"already_{terminal}"
    assert invocation_env.adapter.calls == [], "终态批次仍被重新调用，白烧 token"
    await db.refresh(batch)
    assert batch.status == terminal, "重投把终态批次翻回 running"
    assert (await db.execute(select(InvocationResult.id).where(
        InvocationResult.batch_id == batch.id))).all() == [], "重投还写了新结果行"


@pytest.mark.asyncio
async def test_manual_rerun_is_not_blocked_by_the_guard(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system, sample_dataset, monkeypatch
):
    """POST /run 先把状态置回 running，所以用户主动重跑照常执行"""
    from contextlib import asynccontextmanager

    from app.tasks import invocation_tasks

    class _Delay:
        def delay(self, *args):
            return self

        id = "fake"

    monkeypatch.setattr(invocation_tasks, "invocation_task", _Delay())

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)
    adapter = _CountingAdapter()
    monkeypatch.setattr(invocation_tasks.AdapterFactory, "create", lambda *a, **k: adapter)

    batch = await _batch(db_session, "completed", n=1)
    resp = await client.post(f"/api/v1/invocations/{batch.id}/run")
    assert resp.status_code == 200, resp.text
    await db_session.refresh(batch)
    assert batch.status == "running"

    out = await invocation_tasks._run_invocation(_FakeTask(), batch.id)
    assert adapter.calls, "手工重跑被终态拦截误伤"
    assert out["status"] == "completed"


@pytest.mark.asyncio
async def test_redelivered_evaluation_task_skips_cancelled(monkeypatch, db_session: AsyncSession):
    from contextlib import asynccontextmanager

    from app.tasks import evaluation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(evaluation_tasks, "get_db_context", fake_ctx)

    ds = Dataset(name="DS2", description="d", status="active")
    db_session.add(ds)
    await db_session.commit()
    await db_session.refresh(ds)
    ev = Evaluation(
        name="已取消的评估", dataset_id=ds.id, status=EvaluationStatus.CANCELLED,
        metrics=["recall_k"], batch_size=2,
    )
    db_session.add(ev)
    await db_session.commit()

    out = await evaluation_tasks._run_evaluation(_FakeTask(), ev.id)

    assert out["status"] == "already_cancelled"
    await db_session.refresh(ev)
    assert ev.status == EvaluationStatus.CANCELLED, "取消被重投推翻"
