# 调用结果状态落库的回归测试
#
# 线上事故：适配器已用 success=False 表达"调用失败"（空答案/截断），
# 但调用任务无视该标志、一律写 status="success"。后果是
#   - 12 条结果显示成功却没有任何答案；
#   - 批次统计虚高；
#   - 评估拿空答案当有效输入，指标全被污染。
#
# 适配器侧有测试（test_empty_answer_rejection.py），但"任务落库"这一层
# 一直没有覆盖——而这正是漏掉的那个环节。这里直接驱动 _run_invocation，
# 用一个假适配器精确控制每次 query 的返回值。

import pytest

from app.models.dataset import Dataset, QARecord
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem
from app.services.adapters.base import RAGResponse


class FakeTask:
    """Celery task 的最小替身，够 _run_invocation 用"""

    def __init__(self):
        self.states = []

    def update_state(self, *args, **kwargs):
        self.states.append(kwargs.get("meta"))


class ScriptedAdapter:
    """按调用顺序返回预设响应，并记录收到的参数"""

    system_type = "direct_llm"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def query(self, question, contexts=None, conversation_id=None, **kwargs):
        self.calls.append(question)
        return self._responses.pop(0) if self._responses else RAGResponse(
            answer="", success=False, error="没有更多预设响应"
        )


@pytest.fixture
def task_env(monkeypatch, db_session):
    """让 _run_invocation 复用测试库，并可替换适配器

    _run_invocation 内部自己开 get_db_context()，直接连的是真实数据库。
    这里把它换成 db_session 的上下文，测试才能在内存 SQLite 上跑。
    """
    from contextlib import asynccontextmanager

    from app.tasks import invocation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)

    def install(adapter):
        monkeypatch.setattr(
            invocation_tasks.AdapterFactory, "create", lambda *a, **k: adapter
        )

    return type("Env", (), {"install": staticmethod(install), "db": db_session})()


async def _seed(db, *, n_records: int):
    dataset = Dataset(name="DS", description="d", status="active")
    db.add(dataset)
    await db.flush()
    rag = RAGSystem(
        name="RAG",
        system_type="direct_llm",
        description="d",
        connection_config={"provider": "openai"},
        status="active",
    )
    db.add(rag)
    await db.flush()
    batch = InvocationBatch(
        name="B", dataset_id=dataset.id, rag_system_id=rag.id, status="pending"
    )
    db.add(batch)
    await db.flush()
    for i in range(n_records):
        db.add(QARecord(dataset_id=dataset.id, question=f"问题{i}", answer="答案"))
    await db.commit()
    return batch


@pytest.mark.asyncio
async def test_failed_adapter_response_is_stored_as_failed(task_env):
    """适配器 success=False 时必须落库为 failed，且带上失败原因"""
    from sqlalchemy import select
    from app.tasks.invocation_tasks import _run_invocation

    db = task_env.db
    batch = await _seed(db, n_records=1)
    task_env.install(ScriptedAdapter([
        RAGResponse(answer="", success=False, error="模型未返回答案内容（finish_reason=length）"),
    ]))

    await _run_invocation(FakeTask(), batch.id)

    rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed", "适配器已判失败，落库不能是 success"
    assert "finish_reason" in (rows[0].error or ""), "失败必须带可读原因"
    assert batch.completed_count == 0
    assert batch.failed_count == 1


@pytest.mark.asyncio
async def test_successful_and_failed_responses_are_counted_separately(task_env):
    """成功/失败必须分别计数，不能一律记成功"""
    from sqlalchemy import select
    from app.tasks.invocation_tasks import _run_invocation

    db = task_env.db
    batch = await _seed(db, n_records=3)
    task_env.install(ScriptedAdapter([
        RAGResponse(answer="有答案", success=True),
        RAGResponse(answer="", success=False, error="上游服务返回 504"),
        RAGResponse(answer="另一个答案", success=True),
    ]))

    await _run_invocation(FakeTask(), batch.id)

    rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    by_status = {}
    for r in rows:
        by_status.setdefault(r.status, []).append(r)
    assert len(by_status.get("success", [])) == 2
    assert len(by_status.get("failed", [])) == 1
    # 成功的必须有实际答案——"成功却没答案"正是本次要消灭的状态
    for r in by_status["success"]:
        assert (r.answer or "").strip()

    assert batch.completed_count == 2
    assert batch.failed_count == 1
    assert batch.status == "completed"


@pytest.mark.asyncio
async def test_adapter_exception_is_stored_as_failed_with_reason(task_env):
    """适配器直接抛异常时，落库 failed 且错误非空"""
    from sqlalchemy import select
    from app.tasks.invocation_tasks import _run_invocation

    class BoomAdapter(ScriptedAdapter):
        async def query(self, question, contexts=None, conversation_id=None, **kwargs):
            raise RuntimeError("上游连接被重置")

    db = task_env.db
    batch = await _seed(db, n_records=1)
    task_env.install(BoomAdapter([]))

    await _run_invocation(FakeTask(), batch.id)

    rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    assert rows[0].status == "failed"
    assert rows[0].error == "上游连接被重置"


@pytest.mark.asyncio
async def test_empty_message_exception_still_yields_non_empty_error(task_env):
    """str() 为空的异常（如 httpx.ConnectError("")）也必须留下原因"""
    import httpx
    from sqlalchemy import select
    from app.tasks.invocation_tasks import _run_invocation

    class EmptyMsgAdapter(ScriptedAdapter):
        async def query(self, question, contexts=None, conversation_id=None, **kwargs):
            raise httpx.ConnectError("")

    db = task_env.db
    batch = await _seed(db, n_records=1)
    task_env.install(EmptyMsgAdapter([]))

    await _run_invocation(FakeTask(), batch.id)

    rows = (await db.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalars().all()
    assert rows[0].status == "failed"
    assert (rows[0].error or "").strip(), "空消息异常也会让 error 变空串"
