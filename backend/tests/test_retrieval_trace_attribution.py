# 检索轨迹落库与通道级 badcase 归因
#
# 背景：调用结果原先只有 contexts / retrieval_ids，被测系统回传的通道排序、
# 树定位轮次、兜底标记在写库时就丢了。于是 badcase 归因只能给"漏召 N 条"，
# 分不清「各通道都没捞到」（要改分片/索引）和「某一路捞到了、融合后被挤掉」
# （要改 RRF 配比/重排）——实测多跳语料上全文通道封顶、融合层反而变差，
# 没有通道级数据就指不到这一步。
import pytest

from app.models.dataset import Dataset, QARecord
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem
from app.services.adapters.base import RAGResponse
from app.services.diagnostics.trace import (
    analyze_retrieval_traces,
    channel_rank_of,
    compact_trace,
    retrieval_step,
)


# ------------------------------------------------------------------ 收纳

def test_compact_trace_keeps_channel_order_and_marks_truncation():
    """通道排序要留够分析用的长度，同时记录原始规模，避免把截断读成「没有」"""
    raw = {
        "mode": "search+vector+fulltext+graph",
        "channels": {"vector": [f"mh_0001:p{i:04d}" for i in range(1, 201)],
                     "fulltext": ["mh_0001:p0076"]},
        "fallback": "none",
        "graph_entities": [f"e{i}" for i in range(50)],
    }
    out = compact_trace(raw)
    assert out["channels"]["fulltext"] == ["mh_0001:p0076"]
    assert len(out["channels"]["vector"]) == 40
    assert out["channels_total"]["vector"] == 200
    assert out["mode"].startswith("search+")
    assert out["graph_entities_total"] == 50


def test_compact_trace_without_input_is_none():
    """老系统不回传轨迹时必须落 NULL：分析层要区分「没轨迹」和「没命中」"""
    assert compact_trace(None) is None
    assert compact_trace({}) is None
    assert compact_trace({"answer": "x"}) is None  # 没有可分析字段就不留空壳


def test_compact_trace_respects_size_budget():
    """单条批次结果攒几千条，轨迹必须封顶，否则结果表被 JSON 撑爆"""
    long_id = "mh_0001:p0001:" + "x" * 400
    big = {"channels": {f"c{i}": [f"{long_id}{j}" for j in range(40)] for i in range(8)}}
    out = compact_trace(big)
    assert "truncated" in out
    assert all(len(v) <= 10 for v in out["channels"].values())


# ------------------------------------------------------------------ 断点判定

def _item(gold, final, channels):
    return {
        "target_chunk_ids": gold,
        "retrieval_ids": final,
        "trace": {"channels": channels} if channels is not None else None,
    }


def test_retrieval_step_separates_index_from_fusion():
    """同样是漏召，断在索引层和断在融合层必须能分开"""
    gold = ["mh_0001:p0076"]
    assert retrieval_step(_item(gold, ["mh_0001:p0001"], {"fulltext": gold})) == "lost_in_fusion"
    assert retrieval_step(_item(gold, ["mh_0001:p0001"], {"fulltext": ["mh_0001:p0002"]})) == "channel_all_miss"
    assert retrieval_step(_item(gold, ["mh_0001:p0076"], {"fulltext": gold})) == "gold_in_final"
    assert retrieval_step(_item(gold, ["mh_0001:p0001"], {})) == "no_trace"
    assert retrieval_step(_item([], ["mh_0001:p0001"], {"fulltext": ["x"]})) == "no_gold"


def test_channel_rank_of_reports_best_position():
    ranks = channel_rank_of(
        ["a", "z"], {"vector": ["b", "a", "c"], "fulltext": ["a", "b", "c", "z"]}
    )
    assert ranks == {"vector": 2, "fulltext": 1}


def test_analyze_retrieval_traces_exposes_fusion_loss():
    items = [
        _item(["p1"], ["p9"], {"vector": ["p1"], "fulltext": ["p1"]}),
        _item(["p2"], ["p2"], {"vector": ["p5"], "fulltext": ["p2"]}),
        _item(["p3"], ["p9"], {"vector": ["p8"], "fulltext": ["p7"]}),
    ]
    out = analyze_retrieval_traces(items, top_k=10)
    assert out["channels"]["vector"]["hit@10"] == round(1 / 3, 4)
    assert out["channels"]["fulltext"]["hit@10"] == round(2 / 3, 4)
    assert out["step_counts"]["lost_in_fusion"] == 1
    assert out["step_counts"]["channel_all_miss"] == 1
    assert out["step_counts"]["gold_in_final"] == 1
    assert out["fusion_loss_rate"] == round(1 / 3, 4)
    assert out["best_channel"] == "fulltext"
    assert out["coverage"]["with_channels"] == 3


# ------------------------------------------------------------------ 落库链路

class _TaskStub:
    def update_state(self, *args, **kwargs):
        pass


class _TraceAdapter:
    """返回带通道轨迹的响应，模拟 jq_search /api/eval_search"""

    system_type = "generic"

    async def query(self, question, contexts=None, conversation_id=None, **kwargs):
        return RAGResponse(
            answer="",
            contexts=["正文"],
            retrieval_ids=["mh_0001:p0001"],
            trace={
                "channels": {"vector": ["mh_0001:p0076"], "fulltext": ["mh_0001:p0001"]},
                "mode": "search+vector+fulltext",
                "unavailable": {},
            },
            success=True,
        )


@pytest.fixture
def trace_env(monkeypatch, db_session):
    from contextlib import asynccontextmanager

    from app.tasks import invocation_tasks

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    monkeypatch.setattr(invocation_tasks, "get_db_context", fake_ctx)
    monkeypatch.setattr(invocation_tasks.AdapterFactory, "create", lambda *a, **k: _TraceAdapter())
    return db_session


async def _seed(db):
    dataset = Dataset(name="DS", description="d", status="active")
    db.add(dataset)
    await db.flush()
    rag = RAGSystem(
        name="RAG", system_type="generic", description="d",
        connection_config={"base_url": "http://127.0.0.1:8010"}, status="active",
    )
    db.add(rag)
    await db.flush()
    batch = InvocationBatch(name="B", dataset_id=dataset.id, rag_system_id=rag.id, status="pending")
    db.add(batch)
    await db.flush()
    db.add(QARecord(dataset_id=dataset.id, question="问题", answer="答案"))
    await db.commit()
    return batch


@pytest.mark.asyncio
async def test_invocation_persists_retrieval_trace(trace_env):
    """adapter 回传了通道信息，结果行必须留下它，否则评估阶段无从下钻"""
    from sqlalchemy import select

    from app.tasks.invocation_tasks import _run_invocation

    db = trace_env
    batch = await _seed(db)
    await _run_invocation(_TaskStub(), batch.id)

    row = (await db.execute(select(InvocationResult).where(InvocationResult.batch_id == batch.id))).scalar_one()
    assert row.trace["channels"]["vector"] == ["mh_0001:p0076"]
    assert row.trace["mode"] == "search+vector+fulltext"


# ------------------------------------------------------------------ 分析端点

async def _seed_eval(db, dataset, rows):
    """造一条评估：每题一行调用结果（含轨迹）+ 一行评估分数"""
    from app.models.evaluation import EvalResult, Evaluation, EvaluationStatus
    from app.models.invocation import InvocationBatch, InvocationResult
    from app.models.rag_system import RAGSystem

    rag = RAGSystem(name="RAG-API", system_type="generic", description="d",
                    connection_config={"base_url": "http://127.0.0.1:8010"}, status="active")
    db.add(rag)
    await db.flush()
    batch = InvocationBatch(name="B-API", dataset_id=dataset.id, rag_system_id=rag.id,
                            status="completed", total_count=len(rows))
    db.add(batch)
    await db.flush()
    ev = Evaluation(name="EV-API", dataset_id=dataset.id, invocation_batch_id=batch.id,
                    metrics=["recall_k"], status=EvaluationStatus.COMPLETED)
    db.add(ev)
    await db.flush()

    created = []
    for gold, final, channels, score in rows:
        qr = QARecord(dataset_id=dataset.id, question=f"Q{len(created)}", answer="a",
                      target_chunk_ids=gold)
        db.add(qr)
        await db.flush()
        ir = InvocationResult(batch_id=batch.id, qa_record_id=qr.id, rag_system_id=rag.id,
                              question=qr.question, answer="", retrieval_ids=final,
                              trace=compact_trace({"channels": channels}) if channels else None,
                              status="success")
        db.add(ir)
        await db.flush()
        db.add(EvalResult(eval_id=ev.id, qa_record_id=qr.id, invocation_result_id=ir.id,
                          scores={"recall_k": {"score": score, "details": None, "error": None}}))
        await db.commit()
        created.append((qr, ir))
    return ev, created


@pytest.mark.asyncio
async def test_analysis_reports_per_channel_and_fusion_loss(client, db_session, sample_dataset):
    """漏召必须继续拆到「通道都没捞到」与「融合挤掉」，否则给不出改哪儿"""
    ev, _ = await _seed_eval(db_session, sample_dataset, [
        (["p1"], ["p9"], {"vector": ["p1"], "fulltext": ["p1", "p9"]}, 0.0),
        (["p2"], ["p9"], {"vector": ["p5"], "fulltext": ["p7"]}, 0.0),
        (["p3"], ["p3"], {"vector": ["p3"]}, 1.0),
    ])

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    assert resp.status_code == 200
    trace_analysis = resp.json()["analysis"]["retrieval_trace_analysis"]
    assert trace_analysis["step_counts"]["lost_in_fusion"] == 1
    assert trace_analysis["step_counts"]["channel_all_miss"] == 1
    # 通道统计只数"这一路有结果的样本"：vector 3 条里 2 条含 gold，fulltext 2 条里 1 条
    assert trace_analysis["channels"]["vector"]["hit@10"] == round(2 / 3, 4)
    assert trace_analysis["channels"]["fulltext"]["hit@10"] == 0.5
    assert trace_analysis["channels"]["fulltext"]["samples"] == 2
    # 一半漏召其实是融合丢的 → 根因要指到 fusion 这一层，而不是笼统的 retrieval
    root = resp.json()["analysis"]["root_cause"]
    assert root.get("sub_stage") == "fusion"
    assert any("融合" in r or "重排" in r for r in resp.json()["analysis"]["recommendations"])


@pytest.mark.asyncio
async def test_results_expose_step_filter_without_dumping_full_trace(client, db_session, sample_dataset):
    ev, _ = await _seed_eval(db_session, sample_dataset, [
        (["p1"], ["p9"], {"vector": ["p1"], "fulltext": ["p1"]}, 0.0),
        (["p2"], ["p9"], {"vector": ["p5"]}, 0.0),
    ])

    listing = await client.get(f"/api/v1/evaluations/{ev.id}/results")
    results = listing.json()["results"]
    assert all("trace" not in r for r in results)          # 列表不携带原始轨迹
    by_step = {r["trace_summary"]["retrieval_step"]: r for r in results}
    assert set(by_step) == {"lost_in_fusion", "channel_all_miss"}

    filtered = await client.get(f"/api/v1/evaluations/{ev.id}/results?step=lost_in_fusion")
    body = filtered.json()
    assert body["total"] == 1
    assert body["results"][0]["trace_summary"]["gold_channel_ranks"]["vector"] == 1

    # 下钻用列表里的结果 id（EvalResult.id），前端拿到的就是这个
    detail = await client.get(
        f"/api/v1/evaluations/{ev.id}/results/{by_step['lost_in_fusion']['id']}/trace"
    )
    data = detail.json()
    assert data["retrieval_step"] == "lost_in_fusion"
    assert data["trace"]["channels"]["fulltext"] == ["p1"]
    assert data["gold_channel_ranks"] == {"vector": 1, "fulltext": 1}


@pytest.mark.asyncio
async def test_legacy_result_without_trace_is_not_counted_as_miss(client, db_session, sample_dataset):
    """老系统不回传轨迹：判 no_trace，不能算成「各通道都没命中」"""
    ev, _ = await _seed_eval(db_session, sample_dataset, [(["p1"], ["p9"], None, 0.0)])
    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    trace_analysis = resp.json()["analysis"]["retrieval_trace_analysis"]
    assert trace_analysis["step_counts"]["no_trace"] == 1
    assert trace_analysis["coverage"]["with_channels"] == 0


@pytest.mark.asyncio
async def test_profile_adapter_passes_trace_through(monkeypatch):
    """generic 系统走 ProfileAdapter：连接器给出的 trace 必须透传，
    否则最常用的 profile 接入全是 no_trace，通道级归因形同虚设"""
    from app.services.adapters.profile_adapter import ProfileAdapter

    class _FakeConnector:
        display_name = "通用 HTTP"

        async def ask(self, question, *, chat_id=None, conversation_id=None):
            return {
                "answer": "",
                "contexts": ["正文"],
                "retrieval_ids": ["mh_0001:p0001"],
                "trace": {"channels": {"vector": ["mh_0001:p0001"]}, "mode": "search+vector"},
                "metadata": {},
            }

    monkeypatch.setattr(
        "app.services.adapters.profile_adapter.create_connector",
        lambda *a, **k: _FakeConnector(),
    )
    response = await ProfileAdapter({}).query("问题")
    assert response.success is True
    assert response.trace == {"channels": {"vector": ["mh_0001:p0001"]}, "mode": "search+vector"}
