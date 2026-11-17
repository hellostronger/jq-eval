# 多模态嵌入评测 API 回归测试
import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MMDataset, MMEvalQueryResult, MMEvalRun, Model
from app.api.v1 import mm_embeddings as api_module


def _jsonl_bytes(rows):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")


def _sample_rows():
    return [
        {"qid": "q1", "subset": "T→T", "qry": "q1", "tgt": "a", "label": 1},
        {"qid": "q1", "subset": "T→T", "qry": "q1", "tgt": "b", "label": 0},
        {"qid": "q2", "subset": "T→T", "qry": "q2", "tgt": "c", "label": 1},
        {"qid": "q2", "subset": "T→T", "qry": "q2", "tgt": "d", "label": 0},
    ]


async def _import_dataset(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/mm-embeddings/datasets",
        data={"name": "api-test", "description": ""},
        files={"file": ("data.jsonl", _jsonl_bytes(_sample_rows()), "application/jsonl")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_import_list_and_detail(client: AsyncClient):
    dataset = await _import_dataset(client)
    assert dataset["status"] == "ready"
    assert dataset["record_count"] == 4
    assert dataset["query_count"] == 2
    assert dataset["subset_stats"]["T→T"]["queries"] == 2

    listed = await client.get("/api/v1/mm-embeddings/datasets")
    assert listed.status_code == 200
    assert any(item["id"] == dataset["id"] for item in listed.json())

    detail = await client.get(f"/api/v1/mm-embeddings/datasets/{dataset['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["samples"]) == 4
    assert body["samples"][0]["qid"] == "q1"


@pytest.mark.asyncio
async def test_import_rejects_unsupported_file(client: AsyncClient):
    resp = await client.post(
        "/api/v1/mm-embeddings/datasets",
        data={"name": "bad"},
        files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
    )
    assert resp.status_code == 400
    assert "仅支持" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_run_dispatches_and_validates_model(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_embedding_model: Model,
    sample_llm_model: Model,
    monkeypatch,
):
    dataset = await _import_dataset(client)
    dispatched = {}
    monkeypatch.setattr(
        api_module.mm_embedding_eval_task,
        "delay",
        lambda run_id: dispatched.setdefault("run_id", run_id),
    )

    resp = await client.post(
        "/api/v1/mm-embeddings/runs",
        json={
            "dataset_id": dataset["id"],
            "model_id": str(sample_embedding_model.id),
            "params": {"batch_size": 4, "top_k": 5},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["dataset_name"] == "api-test"
    assert dispatched["run_id"] == body["id"]

    # LLM 模型不能用于嵌入评测
    bad = await client.post(
        "/api/v1/mm-embeddings/runs",
        json={"dataset_id": dataset["id"], "model_id": str(sample_llm_model.id)},
    )
    assert bad.status_code == 400
    assert "embedding" in bad.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_and_rerun_flow(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_embedding_model: Model,
    monkeypatch,
):
    dataset = await _import_dataset(client)
    monkeypatch.setattr(
        api_module.mm_embedding_eval_task, "delay", lambda run_id: None
    )
    created = (
        await client.post(
            "/api/v1/mm-embeddings/runs",
            json={
                "dataset_id": dataset["id"],
                "model_id": str(sample_embedding_model.id),
            },
        )
    ).json()

    cancel = await client.post(f"/api/v1/mm-embeddings/runs/{created['id']}/cancel")
    assert cancel.status_code == 200
    run = await db_session.get(MMEvalRun, created["id"])
    await db_session.refresh(run)
    assert run.cancel_requested is True

    # 模拟 worker 已收敛为 cancelled 后再重跑
    run.status = "cancelled"
    run.completed_at = run.created_at
    await db_session.commit()

    rerun = await client.post(f"/api/v1/mm-embeddings/runs/{created['id']}/rerun")
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["status"] == "running"


@pytest.mark.asyncio
async def test_query_results_filter_only_missed(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_embedding_model: Model,
    monkeypatch,
):
    dataset = await _import_dataset(client)
    monkeypatch.setattr(
        api_module.mm_embedding_eval_task, "delay", lambda run_id: None
    )
    created = (
        await client.post(
            "/api/v1/mm-embeddings/runs",
            json={
                "dataset_id": dataset["id"],
                "model_id": str(sample_embedding_model.id),
                "params": {"top_k": 5},
            },
        )
    ).json()

    run = await db_session.get(MMEvalRun, created["id"])
    db_session.add_all(
        [
            MMEvalQueryResult(run_id=run.id, qid="hit", subset="T→T", rank=1,
                              candidate_count=2, positive_count=1,
                              metrics={"recall@1": 1.0}, retrieved_top=[]),
            MMEvalQueryResult(run_id=run.id, qid="miss", subset="T→T", rank=9,
                              candidate_count=10, positive_count=1,
                              metrics={"recall@1": 0.0}, retrieved_top=[]),
        ]
    )
    await db_session.commit()

    all_rows = await client.get(f"/api/v1/mm-embeddings/runs/{run.id}/queries")
    assert all_rows.status_code == 200
    assert all_rows.json()["total"] == 2

    missed = await client.get(
        f"/api/v1/mm-embeddings/runs/{run.id}/queries",
        params={"only_missed": "true", "top_k": 5},
    )
    assert missed.status_code == 200
    body = missed.json()
    assert body["total"] == 1
    assert body["items"][0]["qid"] == "miss"


@pytest.mark.asyncio
async def test_delete_dataset_blocked_when_run_exists(
    client: AsyncClient,
    db_session: AsyncSession,
    sample_embedding_model: Model,
    monkeypatch,
):
    dataset = await _import_dataset(client)
    monkeypatch.setattr(
        api_module.mm_embedding_eval_task, "delay", lambda run_id: None
    )
    run = MMEvalRun(
        name="ref-run",
        dataset_id=dataset["id"],
        model_id=sample_embedding_model.id,
        status="completed",
        params={},
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/mm-embeddings/datasets/{dataset['id']}")
    assert resp.status_code == 400
    assert "引用" in resp.json()["detail"]
