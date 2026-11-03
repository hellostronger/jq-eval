# 分步归因（badcase attribution）回归测试
#
# /analysis 原先只有指标均值，回答不了"低分断在哪一步"：
# 样本量小或被调用失败拖空时，均值甚至会把根因指向错误的阶段。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.evaluations import ATTRIBUTION_BUCKETS, attribution_summary, classify_attribution
from app.models import Dataset, QARecord, InvocationBatch, InvocationResult
from app.models.evaluation import Evaluation, EvalResult, EvaluationStatus


def _item(gold_hit, faithfulness=None, invocation_error=None, target=("g1",)):
    scores = {}
    if faithfulness is not None:
        scores["faithfulness"] = {"score": faithfulness, "details": None, "error": None}
    return {
        "metric_scores": scores,
        "gold_hit": gold_hit,
        "invocation_error": invocation_error,
        "target_chunk_ids": list(target),
    }


def test_classify_attribution_per_bucket():
    """每个环各归各的桶：调用失败优先，其次看 gold 是否被召回，最后才看生成"""
    assert classify_attribution(_item(None, invocation_error="连接超时")) == "call_failed"
    assert classify_attribution(_item(False, 0.9)) == "retrieval_miss"
    assert classify_attribution(_item(True, 0.2)) == "retrieved_but_answer_weak"
    assert classify_attribution(_item(True, 0.9)) == "retrieved_ok"
    # 没有检索轨迹 ≠ 漏召：数据集缺 gold 与系统不回传 id 要分开
    assert classify_attribution(_item(None)) == "no_retrieval_trace"
    assert classify_attribution(_item(None, target=())) == "no_gold"


def test_attribution_summary_ratios():
    rows = [
        _item(False, 0.1), _item(False, 0.0), _item(True, 0.95),
        _item(None, invocation_error="boom"),
    ]
    out = attribution_summary(rows)
    assert out["total"] == 4
    assert set(out["counts"]) == set(ATTRIBUTION_BUCKETS)
    assert out["counts"]["retrieval_miss"] == 2
    assert out["retrieval_miss_rate"] == 0.5
    assert out["call_failed_rate"] == 0.25


async def _make_eval(db: AsyncSession, dataset: Dataset, rag_system, cases) -> Evaluation:
    ev = Evaluation(name="attr-eval", dataset_id=dataset.id,
                    metrics=["faithfulness"], status=EvaluationStatus.COMPLETED)
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    batch = InvocationBatch(name="b", dataset_id=dataset.id,
                            rag_system_id=rag_system.id, status="completed")
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    for idx, (faithfulness, retrieval_ids, inv_error) in enumerate(cases):
        qr = QARecord(dataset_id=dataset.id, question=f"q{idx}", answer="a",
                      target_chunk_ids=["mh_0001:p0076"])
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        ir = InvocationResult(
            batch_id=batch.id, qa_record_id=qr.id, rag_system_id=rag_system.id,
            question=f"q{idx}", answer="ans", contexts=["ctx"],
            retrieval_ids=retrieval_ids, status="failed" if inv_error else "success",
            error=inv_error,
        )
        db.add(ir)
        await db.commit()
        await db.refresh(ir)
        db.add(EvalResult(
            eval_id=ev.id, qa_record_id=qr.id, invocation_result_id=ir.id,
            scores={"faithfulness": {"score": faithfulness, "details": None, "error": None}},
        ))
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_analysis_reports_miss_as_retrieval_root_cause(
    client: AsyncClient, db_session: AsyncSession, sample_dataset, sample_rag_system
):
    """faithfulness 均值达标但 gold 大面积漏召 → 根因仍是检索，不能被均值掩盖"""
    ev = await _make_eval(db_session, sample_dataset, sample_rag_system, [
        (0.7, ["mh_0001:p0076"], None),
        (0.8, ["mh_0001:p0001"], None),
        (0.7, ["mh_0001:p0002"], None),
    ])
    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    assert resp.status_code == 200
    analysis = resp.json()["analysis"]
    assert analysis["root_cause"]["stage"] == "retrieval"
    assert analysis["attribution"]["counts"]["retrieval_miss"] == 2
    assert "evidence" in analysis["root_cause"]


@pytest.mark.asyncio
async def test_analysis_call_failures_dominate(
    client: AsyncClient, db_session: AsyncSession, sample_dataset, sample_rag_system
):
    """半数以上样本上游调用失败 → 先修接入层，指标均值此时不可用"""
    ev = await _make_eval(db_session, sample_dataset, sample_rag_system, [
        (0.0, None, "连接超时"),
        (0.0, None, "HTTP 500"),
        (0.9, ["mh_0001:p0076"], None),
    ])
    analysis = (await client.get(f"/api/v1/evaluations/{ev.id}/analysis")).json()["analysis"]
    assert analysis["root_cause"]["stage"] == "invocation"
    assert analysis["attribution"]["counts"]["call_failed"] == 2


@pytest.mark.asyncio
async def test_analysis_no_retrieval_trace_is_not_a_miss(
    client: AsyncClient, db_session: AsyncSession, sample_dataset, sample_rag_system
):
    """RAG 系统不回传分片 id 时只能说明"无法归因"，不能判成漏召"""
    ev = await _make_eval(db_session, sample_dataset, sample_rag_system, [
        (0.2, None, None),
        (0.3, None, None),
    ])
    analysis = (await client.get(f"/api/v1/evaluations/{ev.id}/analysis")).json()["analysis"]
    assert analysis["attribution"]["counts"]["no_retrieval_trace"] == 2
    assert analysis["root_cause"]["stage"] != "retrieval"


@pytest.mark.asyncio
async def test_results_can_filter_by_attribution(
    client: AsyncClient, db_session: AsyncSession, sample_dataset, sample_rag_system
):
    """前端 badcase 列表按环筛选：attribution=retrieval_miss 只返回漏召样本"""
    ev = await _make_eval(db_session, sample_dataset, sample_rag_system, [
        (0.7, ["mh_0001:p0076"], None),
        (0.2, ["mh_0001:p0001"], None),
        (0.0, None, "连接超时"),
    ])
    resp = await client.get(f"/api/v1/evaluations/{ev.id}/results?attribution=retrieval_miss")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["results"][0]["attribution"] == "retrieval_miss"
