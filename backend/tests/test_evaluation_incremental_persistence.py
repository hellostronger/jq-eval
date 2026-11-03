# 评估逐批落库 + 终态反推回归测试
#
# 真实故障：一条 5 样本的评估跑到 622s 时，远端 PG 掐线正好落在批次边界的
# SELECT evaluations.cancel_requested 上。原先的结果是：分数只在全部批次跑完后
# 才写库，于是十几分钟 ragas 打出来的真实分数整批凭空消失，评估被记成 failed，
# 用户只能从头再烧一遍 token。
from contextlib import asynccontextmanager

import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.tasks.evaluation_tasks as mod
from app.core.exceptions import TaskCancelled
from app.models.dataset import Dataset, QARecord
from app.models.evaluation import EvalResult, Evaluation, EvaluationStatus
from app.services.metrics import MetricResult
from app.tasks import persistence


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


@pytest.fixture
def no_sleep(monkeypatch):
    """退避等待不真等，但要拿替换前的 sleep，不然自引用递归"""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(persistence.asyncio, "sleep", lambda *_: real_sleep(0))
    return real_sleep


async def _evaluation(db: AsyncSession, dataset: Dataset, **kwargs) -> Evaluation:
    ev = Evaluation(
        name="e2e", dataset_id=dataset.id, metrics=["recall_k"],
        status=EvaluationStatus.RUNNING, batch_size=10, **kwargs,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


def _results(n: int):
    """伪造 n 条样本的指标结果"""
    return [{"recall_k": MetricResult(score=0.5, details={"k": 10}, error=None)} for _ in range(n)]


def _eval_data(db_dataset: Dataset, n: int):
    return [
        {
            "id": f"00000000-0000-0000-0000-00000000000{i + 1}",
            "question": f"q{i}", "answer": "a", "contexts": ["c"],
            "ground_truth": "g", "retrieval_ids": [], "target_chunk_ids": [],
            "invocation_result_id": None, "invocation_error": None,
        }
        for i in range(n)
    ]


class TestBatchPersister:
    @pytest.mark.asyncio
    async def test_each_batch_is_persisted_as_soon_as_it_finishes(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db, no_sleep
    ):
        """落库发生在批次边界，而不是全部跑完之后"""
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 3)
        persist = mod._batch_persister(ev.id, data)

        await persist(_results(2), 0)
        rows = (await db_session.execute(
            select(EvalResult).where(EvalResult.eval_id == ev.id)
        )).scalars().all()
        assert len(rows) == 2, "第一批跑完就该能看到 2 条结果"

        await persist(_results(1), 2)
        rows = (await db_session.execute(
            select(EvalResult).where(EvalResult.eval_id == ev.id)
        )).scalars().all()
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_retried_write_does_not_duplicate_rows(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db, no_sleep
    ):
        """commit_with_retry 会在"上一轮其实已提交"时重做 apply，写必须幂等

        不幂等就会让同一条问答在结果表里出现两次，均值被重复样本算歪。
        """
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 2)
        persist = mod._batch_persister(ev.id, data)

        await persist(_results(2), 0)
        await persist(_results(2), 0)

        rows = (await db_session.execute(
            select(EvalResult).where(EvalResult.eval_id == ev.id)
        )).scalars().all()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_transient_disconnect_is_retried_with_new_session(
        self, db_session: AsyncSession, sample_dataset: Dataset, monkeypatch, no_sleep
    ):
        """第一次写正好赶上连接断开：换新 session 重试后结果必须落库"""
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 1)
        state = {"n": 0}

        @asynccontextmanager
        async def flaky_db():
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("connection was closed in the middle of operation")
            yield db_session

        monkeypatch.setattr(mod, "get_db_context", flaky_db)
        await mod._batch_persister(ev.id, data)(_results(1), 0)

        rows = (await db_session.execute(
            select(EvalResult).where(EvalResult.eval_id == ev.id)
        )).scalars().all()
        assert len(rows) == 1
        assert state["n"] == 2


class TestCancelChecker:
    @pytest.mark.asyncio
    async def test_flag_set_raises_task_cancelled(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db
    ):
        ev = await _evaluation(db_session, sample_dataset)
        ev.cancel_requested = True
        await db_session.commit()

        with pytest.raises(TaskCancelled):
            await mod._cancel_checker(ev.id)()

    @pytest.mark.asyncio
    async def test_transient_read_failure_does_not_abort_the_run(
        self, db_session: AsyncSession, sample_dataset: Dataset, monkeypatch
    ):
        """本次线上故障的正解：读标志失败就继续评，别把十几分钟分数判废"""
        ev = await _evaluation(db_session, sample_dataset)

        @asynccontextmanager
        async def broken_db():
            raise RuntimeError("asyncpg.exceptions.ConnectionDoesNotExistError")
            yield None  # pragma: no cover

        monkeypatch.setattr(mod, "get_db_context", broken_db)
        assert await mod._cancel_checker(ev.id)() is None


class TestFinalize:
    @pytest.mark.asyncio
    async def test_all_results_persisted_means_completed_even_with_error(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db, no_sleep
    ):
        """每条样本都已落库时，收尾炸了也算跑完——与调用批次同一口径"""
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 2)
        await mod._batch_persister(ev.id, data)(_results(2), 0)

        status = await mod._finalize(ev.id, summary={"overall_score": 0.5},
                                     expected=2, error="收尾时连接中断")
        assert status == "completed"
        await db_session.refresh(ev)
        assert ev.error == "收尾时连接中断"
        assert ev.summary == {"overall_score": 0.5}

    @pytest.mark.asyncio
    async def test_partial_results_stay_failed(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db, no_sleep
    ):
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 1)
        await mod._batch_persister(ev.id, data)(_results(1), 0)

        status = await mod._finalize(ev.id, expected=3, error="炸在半路")
        assert status == "failed"
        await db_session.refresh(ev)
        assert ev.error == "炸在半路"

    @pytest.mark.asyncio
    async def test_cancel_flag_wins_over_counters(
        self, db_session: AsyncSession, sample_dataset: Dataset, patched_db, no_sleep
    ):
        ev = await _evaluation(db_session, sample_dataset)
        data = _eval_data(sample_dataset, 2)
        await mod._batch_persister(ev.id, data)(_results(2), 0)
        ev.cancel_requested = True
        await db_session.commit()

        assert await mod._finalize(ev.id, expected=2) == "cancelled"
        await db_session.refresh(ev)
        assert ev.cancel_requested is False


class TestEngineOnBatchCallback:
    @pytest.mark.asyncio
    async def test_callback_fires_per_batch_with_start_index(self):
        """引擎按批交出去，任务才能逐批落库"""
        from app.services.metrics.engine import MetricEngine

        engine = MetricEngine(metric_configs=[])

        async def fake_single(**kwargs):
            return {"recall_k": MetricResult(score=1.0)}
        engine.evaluate_single = fake_single

        seen = []

        async def on_batch(batch_results, start_index):
            seen.append((start_index, len(batch_results)))

        results = await engine.evaluate_batch(
            qa_records=[{"question": f"q{i}", "answer": "a"} for i in range(5)],
            batch_size=2,
            on_batch=on_batch,
        )
        assert seen == [(0, 2), (2, 2), (4, 1)]
        assert len(results) == 5
