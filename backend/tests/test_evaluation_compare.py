# 跨系统对比（POST /evaluations/compare）回归测试
#
# 三路融合 vs LLMWiki vs PageIndex 这类结论就靠这个端点：
# 同一批题、不同 RAG 系统，要能一眼看出"同一道题在 A 漏召、在 B 召回了没答好"。
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, QARecord, InvocationBatch, InvocationResult, RAGSystem
from app.models.evaluation import Evaluation, EvalResult, EvaluationStatus


async def _add_record(db: AsyncSession, dataset: Dataset, question: str, gold: str):
    qr = QARecord(dataset_id=dataset.id, question=question, answer="a",
                  target_chunk_ids=[gold])
    db.add(qr)
    await db.commit()
    await db.refresh(qr)
    return qr


async def _make_eval(db: AsyncSession, dataset: Dataset, rag_system: RAGSystem,
                     name: str, cases: list) -> Evaluation:
    """cases: [(qa_record, 检索到的分片 id 列表)]，命中给高分、漏召给低分"""
    ev = Evaluation(name=name, dataset_id=dataset.id, rag_system_id=rag_system.id,
                    metrics=["faithfulness"], status=EvaluationStatus.COMPLETED)
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    batch = InvocationBatch(name=f"{name}-b", dataset_id=dataset.id,
                            rag_system_id=rag_system.id, status="completed")
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    for qr, ids in cases:
        ir = InvocationResult(
            batch_id=batch.id, qa_record_id=qr.id, rag_system_id=rag_system.id,
            question=qr.question, answer="ans", contexts=["ctx"],
            retrieval_ids=ids, status="success",
        )
        db.add(ir)
        await db.commit()
        await db.refresh(ir)
        hit = bool(set(qr.target_chunk_ids or []) & {str(x) for x in (ids or [])})
        db.add(EvalResult(
            eval_id=ev.id, qa_record_id=qr.id, invocation_result_id=ir.id,
            scores={"faithfulness": {"score": 0.9 if hit else 0.2, "details": None, "error": None}},
        ))
    await db.commit()
    return ev


async def _new_system(db: AsyncSession, name: str) -> RAGSystem:
    sys_row = RAGSystem(
        name=name, system_type="custom", description="d",
        connection_config={"api_url": "http://x/api"}, status="active",
    )
    db.add(sys_row)
    await db.commit()
    await db.refresh(sys_row)
    return sys_row


@pytest.mark.asyncio
async def test_compare_exposes_per_system_attribution(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset, sample_rag_system
):
    """同一数据集、两个系统：对比结果要给逐环归因和系统名"""
    r0 = await _add_record(db_session, sample_dataset, "cmp0", "doc:p0000")
    r1 = await _add_record(db_session, sample_dataset, "cmp1", "doc:p0001")
    fusion = await _new_system(db_session, "三路融合")

    await _make_eval(db_session, sample_dataset, fusion, "eval-fusion", [
        (r0, ["doc:p0000", "doc:p0077"]),
        (r1, ["doc:p0001"]),
    ])
    # 另一路只读到无关页：gold 没进检索轨迹 → 低分根因是漏召，不是生成
    await _make_eval(db_session, sample_dataset, sample_rag_system, "eval-other", [
        (r0, ["doc:p9999"]),
        (r1, ["doc:p9998"]),
    ])

    ids = [str(e.id) for e in (await db_session.execute(
        select(Evaluation).where(Evaluation.name.in_(["eval-fusion", "eval-other"]))
    )).scalars().all()]

    resp = await client.post("/api/v1/evaluations/compare", json={"eval_ids": ids})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    by_name = {e["name"]: e for e in body["evaluations"]}
    assert by_name["eval-fusion"]["attribution"]["counts"]["retrieved_ok"] == 2
    assert by_name["eval-fusion"]["rag_system_name"] == "三路融合"
    assert by_name["eval-other"]["attribution"]["counts"]["retrieval_miss"] == 2

    row = next(c for c in body["comparison"] if c["question"] == "cmp0")
    assert row["attribution"] == {"eval-fusion": "retrieved_ok", "eval-other": "retrieval_miss"}


@pytest.mark.asyncio
async def test_compare_rejects_incomplete_eval(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """未完成的评估不参与对比，否则对比表里会出现半空的列"""
    running = Evaluation(name="running-eval", dataset_id=sample_dataset.id,
                         metrics=["faithfulness"], status="running")
    db_session.add(running)
    await db_session.commit()

    resp = await client.post("/api/v1/evaluations/compare",
                             json={"eval_ids": [str(running.id), str(running.id)]})
    assert resp.status_code == 400
