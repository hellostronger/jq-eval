# 「排队中」与「运行中」的区分（POST /invocations/{id}/run 后的状态语义）
#
# 实测困惑：worker 是单并发（Windows 上 --pool=solo --concurrency=1），一次只跑一个任务。
# 派发时 start_task() 就把 status 置成 running，而 started_at 要等 worker 真正领取任务才写，
# 于是排在后面的批次会以 running/0 条进度停几十分钟。界面上看不出来"在排队"还是"卡住了"，
# 只能靠 pg_stat_activity 或 worker 日志判断。
#
# 契约就此固定下来：status=running 且 started_at 为空 ＝ 已派发未领取；
# 重跑必须清掉上一轮的 started_at，否则排队中的批次会被读成"已经在跑"。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invocation import InvocationBatch


class _FakeDelay:
    def __init__(self):
        self.args = None

    def delay(self, *args):
        self.args = args
        return self

    @property
    def id(self):
        return "fake-task"


@pytest.fixture
def fake_invocation_task(monkeypatch):
    task = _FakeDelay()
    monkeypatch.setattr("app.tasks.invocation_tasks.invocation_task", task)
    return task


async def _make_batch(db, sample_rag_system, sample_dataset, **kwargs):
    batch = InvocationBatch(
        name="queued", dataset_id=sample_dataset.id, rag_system_id=sample_rag_system.id,
        status="pending", total_count=2, **kwargs,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


@pytest.mark.asyncio
async def test_run_leaves_started_at_empty_while_queued(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system, sample_dataset,
    fake_invocation_task,
):
    """派发后状态是 running，但 started_at 必须仍为空——这是"排队中"的唯一判据"""
    from datetime import datetime

    batch = await _make_batch(db_session, sample_rag_system, sample_dataset,
                              started_at=datetime(2026, 1, 1))
    resp = await client.post(f"/api/v1/invocations/{batch.id}/run")
    assert resp.status_code == 200, resp.text

    await db_session.refresh(batch)
    assert batch.status == "running"
    assert batch.started_at is None, "上一轮的 started_at 没清，界面会把排队显示成运行中"
    assert fake_invocation_task.args == (str(batch.id),)

    body = (await client.get(f"/api/v1/invocations/{batch.id}")).json()
    assert body["started_at"] is None


@pytest.mark.asyncio
async def test_worker_start_writes_started_at(db_session, monkeypatch):
    """worker 领取任务后必须写上 started_at，排队判据才会消失（与上一条互补）"""
    from contextlib import asynccontextmanager

    from app.models import Dataset, QARecord, RAGSystem
    from app.services.adapters.base import RAGResponse
    from app.tasks import invocation_tasks
    from app.tasks.invocation_tasks import _run_invocation

    class FakeTask:
        def update_state(self, *args, **kwargs):
            pass

    class _AlwaysOkAdapter:
        system_type = "direct_llm"

        async def query(self, question, contexts=None, conversation_id=None, **kwargs):
            return RAGResponse(answer="ok", success=True)

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    # _run_invocation 自己开 get_db_context()，默认连真库；换成测试会话才能在内存 SQLite 上跑
    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)
    monkeypatch.setattr(invocation_tasks.AdapterFactory, "create", lambda *a, **k: _AlwaysOkAdapter())

    db = db_session
    dataset = Dataset(name="DS", description="d", status="active")
    rag = RAGSystem(name="RAG", system_type="direct_llm", description="d",
                    connection_config={"provider": "openai"}, status="active")
    db.add_all([dataset, rag])
    await db.flush()
    batch = InvocationBatch(name="B", dataset_id=dataset.id, rag_system_id=rag.id,
                            status="running", total_count=1)
    db.add(batch)
    db.add(QARecord(dataset_id=dataset.id, question="问题", answer="答案"))
    await db.commit()

    await _run_invocation(FakeTask(), batch.id)
    await db.refresh(batch)
    assert batch.started_at is not None
