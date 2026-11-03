# 外部基准检索 ground truth + badcase 逐条归因 回归测试
#
# 覆盖三处修复：
# 1. target_chunk_ids 允许非 UUID 的 gold key（StratRAG / MultiHop 用 "doc:p0076"）
# 2. GET /evaluations/{id}/results 支持按指标分数筛 badcase，并返回 gold/检索命中对照
# 3. 上下文预算：整页式 RAG 的 15 万字符 contexts 不再原样喂给 LLM 指标
import io
import json
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, QARecord, InvocationBatch, InvocationResult
from app.models.evaluation import Evaluation, EvalResult, EvaluationStatus
from app.services.metrics.context_budget import apply_context_budget


def _jsonl(rows) -> io.BytesIO:
    return io.BytesIO(("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)).encode("utf-8"))


@pytest.mark.asyncio
async def test_import_keeps_non_uuid_gold_chunk_ids(client: AsyncClient, sample_dataset: Dataset):
    """非 UUID 的 gold 分片 key 必须原样入库，否则检索指标全部报「缺少目标chunk ID列表」"""
    rows = [{
        "question": "哪篇文章报道了 FTX 审判？",
        "answer": "The FTX trial is bigger than Sam Bankman-Fried",
        "ground_truth": "Sam Bankman-Fried",
        "positive_ids": ["mh_0001:p0011", "mh_0001:p0012", "mh_0001:p0176"],
    }]
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import",
        files={"file": ("gold.jsonl", _jsonl(rows), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text

    listed = await client.get(f"/api/v1/datasets/{sample_dataset.id}/qa-records")
    record = next(r for r in listed.json()["items"] if r["question"].startswith("哪篇文章"))
    assert record["target_chunk_ids"] == ["mh_0001:p0011", "mh_0001:p0012", "mh_0001:p0176"]


@pytest.mark.asyncio
async def test_import_still_accepts_uuid_gold_ids(client: AsyncClient, sample_dataset: Dataset):
    """存量 UUID 形式（本地 Chunk 主键）继续可用"""
    rows = [{
        "question": "UUID 形式 gold 是否保留",
        "answer": "a",
        "gold_chunk_ids": ["11111111-1111-1111-1111-111111111111"],
    }]
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import",
        files={"file": ("u.jsonl", _jsonl(rows), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    listed = await client.get(f"/api/v1/datasets/{sample_dataset.id}/qa-records")
    record = next(r for r in listed.json()["items"] if r["question"] == "UUID 形式 gold 是否保留")
    assert record["target_chunk_ids"] == ["11111111-1111-1111-1111-111111111111"]


async def _make_eval_with_invocations(
    db: AsyncSession, dataset: Dataset, rag_system, scores_per_case
) -> Evaluation:
    """3 条样本：命中/未命中 gold、含 1 条上游调用失败"""
    ev = Evaluation(name="badcase-eval", dataset_id=dataset.id,
                    metrics=["faithfulness"], status=EvaluationStatus.COMPLETED)
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    batch = InvocationBatch(name="b", dataset_id=dataset.id,
                            rag_system_id=rag_system.id, status="completed")
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    for idx, (faithfulness, retrieval_ids, inv_error) in enumerate(scores_per_case):
        qr = QARecord(
            dataset_id=dataset.id,
            question=f"q{idx}",
            answer="a",
            target_chunk_ids=["mh_0001:p0076"],
        )
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
            details={"invocation_error": inv_error} if inv_error else None,
        ))
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_results_expose_gold_and_retrieval_side_by_side(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    """badcase 明细要能一眼看出低分出在检索还是生成：gold_hit 由后端算好"""
    ev = await _make_eval_with_invocations(db_session, sample_dataset, sample_rag_system, [
        (0.9, ["mh_0001:p0076", "mh_0001:p0077"], None),
        (0.2, ["mh_0001:p0001"], None),
        (0.0, None, "连接超时"),
    ])

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/results")
    assert resp.status_code == 200
    items = resp.json()["results"]
    assert resp.json()["total"] == 3
    hits = {it["gold_hit"] for it in items}
    # 第三条上游失败、没有检索轨迹 → gold_hit=None（"无从判断"），
    # 不能记成 False，否则调用失败会被误算成检索漏召
    assert hits == {True, False, None}
    failed = next(it for it in items if it["invocation_error"])
    assert failed["retrieval_ids"] == []
    assert all(it["target_chunk_ids"] == ["mh_0001:p0076"] for it in items)


@pytest.mark.asyncio
async def test_results_filter_low_metric_scores(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    """metric + max_score 只回低分样本，total 同步收窄（翻页才不会错位）"""
    ev = await _make_eval_with_invocations(db_session, sample_dataset, sample_rag_system, [
        (0.9, ["mh_0001:p0076"], None),
        (0.2, ["mh_0001:p0001"], None),
        (0.0, [], "连接超时"),
    ])

    resp = await client.get(
        f"/api/v1/evaluations/{ev.id}/results?metric=faithfulness&max_score=0.6"
    )
    body = resp.json()
    assert body["total"] == 2
    assert sorted(round(i["metric_scores"]["faithfulness"]["score"], 1) for i in body["results"]) == [0.0, 0.2]

    err_only = await client.get(f"/api/v1/evaluations/{ev.id}/results?only_errors=true")
    assert err_only.json()["total"] == 1


def test_context_budget_truncates_and_reports():
    """超预算时截断并给出可回写的统计；未超预算保持原样且不产生统计"""
    contexts = ["甲" * 5000, "乙" * 100, "丙" * 100]
    budgeted, stats = apply_context_budget(contexts, per_chunk_chars=1000, total_chars=2500)
    assert len(budgeted[0]) == 1000
    assert stats["context_chunks_truncated"] == 1
    assert stats["context_chars_original"] == 5200
    assert stats["context_chars_used"] <= 2500

    untouched, none_stats = apply_context_budget(["短上下文"], per_chunk_chars=1000, total_chars=2000)
    assert untouched == ["短上下文"]
    assert none_stats is None
