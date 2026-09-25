# RAG 调用失败的原因必须一路带到评估报告里
#
# 隐患：InvocationResult.error 记录了真实失败原因（超时/504/连接失败），
# 但评估任务只取了 answer/contexts，把 error 丢掉了。后果是报告里只会
# 出现"答案为空"这类下游报错——用户看到分数低，会误以为是 RAG 回答
# 质量差，实际上是压根没调用成功，排查方向从第一步就错了。
#
# 这里直接驱动 _run_evaluation（SQLite），验证两件事：
#   1. 复用调用结果时，失败原因落到 EvalResult.details；
#   2. 汇总里有 invocation_failed_count，能和"指标算失败"区分开。
import pytest
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
def eval_env(monkeypatch, db_session):
    """让 _run_evaluation 复用测试库"""
    from contextlib import asynccontextmanager

    from app.tasks import evaluation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(evaluation_tasks, "get_db_context", fake_ctx)
    return db_session


async def _seed(db):
    """一条数据集 + 一个 RAG 系统 + 一条 QA + 一条失败的调用结果"""
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

    qa = QARecord(
        dataset_id=dataset.id,
        question="问题",
        answer="静态答案",
        ground_truth="参考答案",
    )
    db.add(qa)
    await db.flush()

    batch = InvocationBatch(
        name="B", dataset_id=dataset.id, rag_system_id=rag.id, status="completed"
    )
    db.add(batch)
    await db.flush()

    db.add(
        InvocationResult(
            batch_id=batch.id,
            qa_record_id=qa.id,
            rag_system_id=rag.id,
            question="问题",
            answer=None,
            contexts=None,
            status="failed",
            error="上游服务返回 504（网关/反向代理超时或不可用）",
        )
    )
    await db.commit()
    return dataset, batch, qa


async def _run(db, batch, reuse=True):
    """建一个复用调用结果的评估并跑完，返回 (evaluation, eval_result)"""
    from app.tasks.evaluation_tasks import _run_evaluation

    evaluation = Evaluation(
        name="E",
        dataset_id=batch.dataset_id,
        invocation_batch_id=batch.id,
        reuse_invocation=reuse,
        metrics=["rouge_l"],  # 不依赖 LLM/Embedding，测试库里即可跑
        status="pending",
    )
    db.add(evaluation)
    await db.commit()

    await _run_evaluation(FakeTask(), evaluation.id)
    await db.refresh(evaluation)

    rows = (await db.execute(
        select(EvalResult).where(EvalResult.eval_id == evaluation.id)
    )).scalars().all()
    return evaluation, rows


async def test_failed_invocation_reason_reaches_eval_result(eval_env):
    """上游失败原因必须留在明细里，而不是只剩"答案为空" """
    db = eval_env
    _dataset, batch, _qa = await _seed(db)
    _evaluation, rows = await _run(db, batch)

    assert len(rows) == 1
    details = rows[0].details or {}
    assert "invocation_error" in details, "调用失败原因被丢掉了"
    assert "504" in details["invocation_error"], "要保留可读的上游原因"
    assert rows[0].invocation_result_id is not None, "应关联到那条调用结果"


async def test_summary_reports_invocation_failures_separately(eval_env):
    """汇总里要能区分"调用失败"与"指标算失败" """
    db = eval_env
    _dataset, batch, _qa = await _seed(db)
    evaluation, _rows = await _run(db, batch)

    summary = evaluation.summary or {}
    assert summary.get("invocation_failed_count") == 1
    assert any("504" in e for e in summary.get("invocation_errors", []))
    # 关键：不能被算成指标层面的失败
    assert "metric_errors" not in summary, (
        "RAG 没调用成功，不该报成指标计算失败——那是两个不同的问题"
    )


async def test_failed_invocations_are_excluded_from_metric_means(eval_env):
    """调用失败的样本绝不能进指标均值——纯 Python 指标会把空答案安静算成 0 分

    这是实测踩到的：14 条里 4 条上游 504，rouge_l 给出 count=14、
    mean=0.01，报告读起来像"RAG 质量极差"，真相是 4 条压根没输出。
    """
    db = eval_env
    _dataset, batch, qa = await _seed(db)

    # 再加一条成功的调用结果，让"该被排除的"和"该被统计的"同时存在
    ok_qa = QARecord(dataset_id=batch.dataset_id, question="问题2", answer="答案2",
                     ground_truth="参考答案2")
    db.add(ok_qa)
    await db.flush()
    db.add(
        InvocationResult(
            batch_id=batch.id,
            qa_record_id=ok_qa.id,
            rag_system_id=batch.rag_system_id,
            question="问题2",
            answer="参考答案2",
            contexts=None,
            status="success",
            error=None,
        )
    )
    await db.commit()

    evaluation, rows = await _run(db, batch)
    summary = evaluation.summary or {}

    # 两条 QA、只有一条拿到了 RAG 输出
    assert summary["total_records"] == 2, "总数是 QA 数，不是成功数"
    assert summary["scored_records"] == 1, "只有成功的调用参与统计"
    assert summary["invocation_failed_count"] == 1
    # 失败那条的 rouge_l 是 0.0（空答案），若混入统计会把 mean 拉成 0.5
    m = summary["metrics_summary"]["rouge_l"]
    assert m["count"] == 1, "失败样本混进了指标统计"
    assert m["mean"] == 1.0, "空答案的 0 分污染了均值"
    # 结果行仍要保留，便于追溯
    assert len(rows) == 2, "明细要留着，剔除只发生在统计口径上"


async def test_successful_invocations_still_enter_the_mean(eval_env):
    """对照组：排除逻辑不能误伤真正成功的样本"""
    db = eval_env
    _dataset, batch, qa = await _seed(db)
    row = (await db.execute(
        select(InvocationResult).where(InvocationResult.qa_record_id == qa.id)
    )).scalar_one()
    row.status = "success"
    row.error = None
    row.answer = "参考答案"
    await db.commit()

    evaluation, _rows = await _run(db, batch)
    summary = evaluation.summary or {}
    assert summary["scored_records"] == 1
    assert "rouge_l" in summary["metrics_summary"]
    assert summary["metrics_summary"]["rouge_l"]["count"] == 1


async def test_successful_invocation_adds_no_failure_fields(eval_env):
    """调用成功时不凭空多出失败字段"""
    db = eval_env
    _dataset, batch, qa = await _seed(db)
    # 把上一条失败改成成功
    row = (await db.execute(
        select(InvocationResult).where(InvocationResult.qa_record_id == qa.id)
    )).scalar_one()
    row.status = "success"
    row.error = None
    row.answer = "RAG 的回答"
    await db.commit()

    evaluation, rows = await _run(db, batch)
    summary = evaluation.summary or {}
    assert "invocation_failed_count" not in summary
    assert "invocation_errors" not in summary
    assert (rows[0].details or {}) == {} or rows[0].details is None
