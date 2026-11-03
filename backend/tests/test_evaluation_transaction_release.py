# 打分阶段不能挂着未结束的事务
#
# 评估任务的准备阶段（读 evaluation、模型配置、调用结果）都在同一个 session 上
# 开事务，然后一路带进 evaluate_batch。单批 ragas 打分能跑十几分钟，这期间连接
# 既不执行也不放锁，实测两个后果：
#   1) 远端 PG 里堆积 idle-in-transaction 连接，ALTER TABLE 被挡成
#      LockNotAvailableError，加列/建索引全都做不了；
#   2) 跨公网的空闲连接常被服务端掐断，等收尾落库时才发现连接没了
#      （那次 622s 的 ConnectionDoesNotExistError 就是这么来的）。
# 所以进入长耗时打分之前必须先 commit/结束事务。
import pytest
from sqlalchemy import select

from app.models.dataset import Dataset, QARecord
from app.models.evaluation import Evaluation
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem
from app.tasks import evaluation_tasks

pytestmark = pytest.mark.asyncio


class FakeTask:
    def update_state(self, *args, **kwargs):
        pass


@pytest.fixture
def eval_env(monkeypatch, db_session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(evaluation_tasks, "get_db_context", fake_ctx)
    return db_session, monkeypatch


async def _seed_one(db):
    dataset = Dataset(name="DS", description="d", status="active")
    db.add(dataset)
    await db.flush()
    rag = RAGSystem(
        name="RAG", system_type="direct_llm", description="d",
        connection_config={"provider": "openai"}, status="active",
    )
    db.add(rag)
    await db.flush()
    qa = QARecord(dataset_id=dataset.id, question="问题", answer="参考答案")
    db.add(qa)
    await db.flush()
    batch = InvocationBatch(
        name="B", dataset_id=dataset.id, rag_system_id=rag.id, status="completed"
    )
    db.add(batch)
    await db.flush()
    db.add(InvocationResult(
        batch_id=batch.id, qa_record_id=qa.id, rag_system_id=rag.id,
        question="问题", answer="参考答案", contexts=None, status="success",
    ))
    await db.commit()
    return batch


async def test_transaction_is_released_before_long_scoring(eval_env):
    """evaluate_batch 被调用时，任务会话不能再持有事务"""
    db, monkeypatch = eval_env
    batch = await _seed_one(db)

    real_factory = evaluation_tasks.get_metric_engine
    seen = {}

    class Probe:
        """包一层真引擎，只在批边界记录"此刻是否还开着事务" """

        def __init__(self, inner):
            self._inner = inner

        async def evaluate_batch(self, *args, **kwargs):
            seen["in_transaction"] = db.in_transaction()
            return await self._inner.evaluate_batch(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(
        evaluation_tasks, "get_metric_engine",
        lambda **kw: Probe(real_factory(**kw)),
    )

    evaluation = Evaluation(
        name="E", dataset_id=batch.dataset_id, invocation_batch_id=batch.id,
        reuse_invocation=True, metrics=["rouge_l"], status="pending",
    )
    db.add(evaluation)
    await db.commit()

    await evaluation_tasks._run_evaluation(FakeTask(), evaluation.id)
    assert seen, "探针没被调用，测试没真正跑到 evaluate_batch"
    assert seen["in_transaction"] is False, (
        "打分期间还挂着 idle-in-transaction：会挡住 DDL，也容易被远端掐断连接"
    )


async def test_scores_still_land_after_release(eval_env):
    """收尾不能因为提前 commit 而丢结果行/汇总"""
    from app.models.evaluation import EvalResult

    db, _monkeypatch = eval_env
    batch = await _seed_one(db)
    evaluation = Evaluation(
        name="E2", dataset_id=batch.dataset_id, invocation_batch_id=batch.id,
        reuse_invocation=True, metrics=["rouge_l"], status="pending",
    )
    db.add(evaluation)
    await db.commit()

    await evaluation_tasks._run_evaluation(FakeTask(), evaluation.id)
    await db.refresh(evaluation)

    rows = (await db.execute(
        select(EvalResult).where(EvalResult.eval_id == evaluation.id)
    )).scalars().all()
    assert evaluation.status == "completed", evaluation.error
    assert len(rows) == 1
    assert (evaluation.summary or {})["scored_records"] == 1


def test_engines_cap_idle_transactions():
    """空闲事务上限必须是两个引擎共用的一份配置

    兜底用：worker 被强杀、本机断网、reload 重启都会留下"本地 socket 已没了、
    服务端事务还挂着"的幽灵连接；asyncpg 不开 TCP keepalive，PG 会一直等，
    表锁也就一直不放（实测挡住 ALTER TABLE 70 分钟）。
    只靠任务层 commit 挡不住遗弃连接，所以连接建立时就得带上这个 GUC。
    """
    from app.core import database

    for name in ("jq_eval_api", "jq_eval_celery"):
        ss = database.server_settings(name)
        assert ss["application_name"] == name, "排障时靠这个字段区分 API 与 worker"
        cap = int(ss["idle_in_transaction_session_timeout"])
        assert 60_000 <= cap <= 30 * 60_000, (
            f"{name} 的空闲事务上限 {cap}ms 不合理：太短会掐断慢速 RAG 的单条调用，"
            "太长则幽灵连接长时间挡住 DDL"
        )
