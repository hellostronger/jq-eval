# 双协议代理端到端测试
#
# 出站层（outbound_client.call / stream_call）被 mock，其余链路全真：
# HTTP 请求 -> verify_mapping（含 Fernet 解密的密钥比对）-> 协议转换入站
# -> _execute_mapping -> 协议转换出站 -> SSE/JSON 组装。
# 这是 README 的头号卖点，面试演示"代理能用"的证据链。
import json
import pytest
from httpx import AsyncClient

from app.models import Model, ModelMapping
from app.services.llm import outbound_client
from app.services.llm.protocol_converter import InternalResponse, InternalStreamEvent


async def _make_mapping(client_db, llm_model: Model) -> ModelMapping:
    from app.api.v1.model_mappings import generate_mapping_api_key
    key = generate_mapping_api_key()
    mapping = ModelMapping(
        name="proxy-test", target_model_id=llm_model.id,
        api_key=key, auth_required=True, status="active",
    )
    client_db.add(mapping)
    await client_db.commit()
    await client_db.refresh(mapping)
    return mapping, key


@pytest.mark.asyncio
async def test_openai_inbound_nonstream(client: AsyncClient, db_session, sample_llm_model: Model, monkeypatch):
    """OpenAI 协议入站 + 非流式：鉴权、协议转换、响应结构全链路"""
    mapping, key = await _make_mapping(db_session, sample_llm_model)

    async def fake_call(target, req, outbound=None):
        assert req.messages[0].role == "user"
        assert req.messages[0].content == "hello"
        return InternalResponse(content="hi there", stop_reason="stop",
                                usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})

    monkeypatch.setattr(outbound_client, "call", fake_call)

    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "whatever", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "hi there"
    assert data["usage"]["total_tokens"] == 7


@pytest.mark.asyncio
async def test_wrong_key_rejected_with_openai_error_shape(client: AsyncClient, db_session, sample_llm_model: Model):
    mapping, _ = await _make_mapping(db_session, sample_llm_model)

    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/chat/completions",
        headers={"Authorization": "Bearer wrong-key"},
        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 401
    # OpenAI 协议错误形状（而非 FastAPI 默认 detail 形状）
    assert resp.json()["error"]["type"] == "invalid_request_error" or "error" in resp.json()


@pytest.mark.asyncio
async def test_anthropic_inbound_stream(client: AsyncClient, db_session, sample_llm_model: Model, monkeypatch):
    """Anthropic 协议入站 + 流式：SSE 事件序列与 stop_reason 收尾"""
    mapping, key = await _make_mapping(db_session, sample_llm_model)

    async def fake_stream(target, req, outbound=None):
        yield InternalStreamEvent(kind="start", usage={"input_tokens": 3})
        yield InternalStreamEvent(kind="delta", text="par")
        yield InternalStreamEvent(kind="delta", text="tial")
        yield InternalStreamEvent(kind="final", finish_reason="stop",
                                  usage={"output_tokens": 4})

    monkeypatch.setattr(outbound_client, "stream_call", fake_stream)

    async with client.stream(
        "POST",
        f"/api/v1/model-mappings/{mapping.id}/v1/messages",
        headers={"x-api-key": key, "content-type": "application/json"},
        json={"model": "m", "max_tokens": 100,
              "messages": [{"role": "user", "content": "go"}], "stream": True},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    # SSE 帧重组：event: 行 + data: 行
    events = []
    current = None
    for line in body.splitlines():
        if line.startswith("event:"):
            current = line[6:].strip()
        elif line.startswith("data:"):
            events.append((current, json.loads(line[5:].strip())))

    types = [t for t, _ in events]
    assert "message_start" in types
    assert "content_block_delta" in types
    deltas = "".join(d["delta"]["text"] for t, d in events if t == "content_block_delta")
    assert deltas == "partial"
    md = next(d for t, d in events if t == "message_delta")
    assert md["delta"]["stop_reason"] == "end_turn"  # openai stop -> anthropic end_turn


@pytest.mark.asyncio
async def test_tool_choice_named_survives_e2e(client: AsyncClient, db_session, sample_llm_model: Model, monkeypatch):
    """强制工具调用经代理链路到出站体仍保持 tool 指定（上轮归一化修复的端到端验证）"""
    mapping, key = await _make_mapping(db_session, sample_llm_model)

    seen = {}

    async def fake_call(target, req, outbound=None):
        seen["tool_choice"] = req.tool_choice
        return InternalResponse(content="", stop_reason="tool_calls",
                                tool_calls=[{"id": "c1", "name": "get_weather", "arguments": {"city": "BJ"}}])

    monkeypatch.setattr(outbound_client, "call", fake_call)

    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m",
            "messages": [{"role": "user", "content": "weather?"}],
            "tools": [{"type": "function", "function": {"name": "get_weather"}}],
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
        },
    )
    assert resp.status_code == 200
    # 内部表示已归一化为 {"name": ...}（而非原始 openai dict）
    assert seen["tool_choice"] == {"name": "get_weather"}
    # 响应里工具调用被正确回填
    assert resp.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert resp.json()["choices"][0]["finish_reason"] == "tool_calls"


# ---------------------------------------------------------------------------
# Embedding / Rerank 映射端点
# ---------------------------------------------------------------------------

async def _make_mapping_for(client_db, model: Model, log_enabled: bool = False):
    from app.api.v1.model_mappings import generate_mapping_api_key
    key = generate_mapping_api_key()
    mapping = ModelMapping(
        name=f"proxy-test-{model.model_type}", target_model_id=model.id,
        api_key=key, auth_required=True, status="active", log_enabled=log_enabled,
    )
    client_db.add(mapping)
    await client_db.commit()
    await client_db.refresh(mapping)
    return mapping, key


@pytest.mark.asyncio
async def test_embedding_mapping_e2e(client: AsyncClient, db_session,
                                     sample_embedding_model: Model, monkeypatch):
    """embedding 映射端到端：鉴权 -> 出站（model 归一）-> OpenAI 响应透传"""
    mapping, key = await _make_mapping_for(db_session, sample_embedding_model)

    seen = {}

    async def fake_call_embedding(target, payload):
        seen["payload"] = dict(payload)
        return {
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"object": "embedding", "index": 1, "embedding": [0.4, 0.5, 0.6]},
            ],
            "model": "text-embedding-ada-002",
            "usage": {"prompt_tokens": 12, "total_tokens": 12},
        }

    monkeypatch.setattr(outbound_client, "call_embedding", fake_call_embedding)

    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "whatever", "input": ["第一段文本", "第二段文本"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 2
    assert data["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    # 上游真实模型名被归一为名义名对外展示
    assert data["model"] == "text-embedding-ada-002"
    # 入站体原样传给出站层（model 归一在 call_embedding 内部，见下一条单测）
    assert seen["payload"]["input"] == ["第一段文本", "第二段文本"]


@pytest.mark.asyncio
async def test_call_embedding_rerank_normalize_outbound(sample_embedding_model: Model,
                                                        sample_reranker_model: Model,
                                                        monkeypatch):
    """出站层单测：model 归一为目标模型名，URL 按类型拼接"""
    captured = {}

    async def fake_post(target, url, headers, body):
        captured["url"] = url
        captured["body"] = dict(body)
        return {}

    monkeypatch.setattr(outbound_client, "_post_json", fake_post)

    await outbound_client.call_embedding(sample_embedding_model,
                                         {"model": "whatever", "input": ["x"]})
    assert captured["body"]["model"] == "text-embedding-ada-002"
    assert captured["url"].endswith("/embeddings")

    await outbound_client.call_rerank(sample_reranker_model,
                                      {"model": "whatever", "query": "q", "documents": ["d"]})
    assert captured["body"]["model"] == "bge-reranker-v2-m3"
    # endpoint 以 /v1 结尾时直接拼 /rerank
    assert captured["url"].endswith("/v1/rerank")


@pytest.mark.asyncio
async def test_embedding_mapping_rejects_llm_target(client: AsyncClient, db_session,
                                                    sample_llm_model: Model):
    """chat 映射拿去调 /v1/embeddings 应被端点类型校验拦下"""
    mapping, key = await _make_mapping_for(db_session, sample_llm_model)
    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m", "input": "hi"},
    )
    assert resp.status_code == 400
    assert "embedding" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_embedding_mapping_requires_input(client: AsyncClient, db_session,
                                                sample_embedding_model: Model):
    mapping, key = await _make_mapping_for(db_session, sample_embedding_model)
    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_rerank_mapping_e2e(client: AsyncClient, db_session,
                                  sample_reranker_model: Model, monkeypatch):
    """rerank 映射端到端：鉴权 -> 出站归一 -> results/score 字段归一响应"""
    mapping, key = await _make_mapping_for(db_session, sample_reranker_model)

    seen = {}

    async def fake_call_rerank(target, payload):
        seen["query"] = payload.get("query")
        seen["docs"] = payload.get("documents")
        seen["model"] = payload.get("model")
        # 模拟 SiliconFlow 风格上游响应（results + relevance_score）
        return {
            "id": "rr-1",
            "results": [
                {"index": 1, "relevance_score": 0.92},
                {"index": 0, "relevance_score": 0.31},
            ],
            "model": "bge-reranker-v2-m3",
        }

    monkeypatch.setattr(outbound_client, "call_rerank", fake_call_rerank)

    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/rerank",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "whatever", "query": "什么是向量检索",
              "documents": ["向量检索用向量相似度找文档", "今天天气不错"], "top_n": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "bge-reranker-v2-m3"
    assert data["results"][0]["index"] == 1
    assert data["results"][0]["relevance_score"] == 0.92
    assert seen["query"] == "什么是向量检索"
    assert len(seen["docs"]) == 2


@pytest.mark.asyncio
async def test_rerank_response_normalizes_cohere_shape(client: AsyncClient, db_session,
                                                       sample_reranker_model: Model, monkeypatch):
    """老版 Cohere 风格上游（data + score）也要归一成统一 results/relevance_score"""
    mapping, key = await _make_mapping_for(db_session, sample_reranker_model)

    # 出站层归一直测：call_rerank 内部对上游响应做字段兼容
    from app.services.llm.outbound_client import _normalize_rerank_results
    normalized = _normalize_rerank_results({"data": [{"index": 0, "score": 0.77}]})
    assert normalized == {"results": [{"index": 0, "relevance_score": 0.77}]}

    async def fake_call_rerank(target, payload):
        # 真实 call_rerank 会把上游响应归一后再交给代理层，mock 模拟归一后的形态
        return {"results": [{"index": 0, "relevance_score": 0.77}], "model": "m"}

    monkeypatch.setattr(outbound_client, "call_rerank", fake_call_rerank)
    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/rerank",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m", "query": "q", "documents": ["d1"]},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["relevance_score"] == 0.77


@pytest.mark.asyncio
async def test_rerank_mapping_rejects_embedding_target(client: AsyncClient, db_session,
                                                       sample_embedding_model: Model):
    """embedding 映射拿去调 /v1/rerank 同样被端点类型校验拦下"""
    mapping, key = await _make_mapping_for(db_session, sample_embedding_model)
    resp = await client.post(
        f"/api/v1/model-mappings/{mapping.id}/v1/rerank",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "m", "query": "q", "documents": ["d"]},
    )
    assert resp.status_code == 400
    assert "reranker" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_mapping_api_accepts_embedding_and_reranker_target(client: AsyncClient, db_session,
                                                                 sample_embedding_model: Model,
                                                                 sample_reranker_model: Model):
    """映射管理 API：embedding/reranker 目标可建映射（原来硬性要求 llm）"""
    for model in (sample_embedding_model, sample_reranker_model):
        resp = await client.post("/api/v1/model-mappings", json={
            "name": f"map-{model.model_type}", "target_model_id": str(model.id),
            "auth_required": True, "log_enabled": True,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_model_id"] == str(model.id)


@pytest.mark.asyncio
async def test_embedding_rerank_logs_recorded(client: AsyncClient, db_session, test_engine,
                                              sample_embedding_model: Model,
                                              sample_reranker_model: Model, monkeypatch):
    """开启 log_enabled 的 embedding/rerank 映射调用应落 model_request_logs（source=mapping）"""
    from app.models import ModelRequestLog
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    async def fake_emb(target, payload):
        return {"data": [{"index": 0, "embedding": [0.1] * 8}], "model": "m",
                "usage": {"prompt_tokens": 3, "total_tokens": 3}}

    async def fake_rr(target, payload):
        return {"results": [{"index": 0, "relevance_score": 0.5}], "model": "m"}

    monkeypatch.setattr(outbound_client, "call_embedding", fake_emb)
    monkeypatch.setattr(outbound_client, "call_rerank", fake_rr)

    emb_mapping, emb_key = await _make_mapping_for(db_session, sample_embedding_model, log_enabled=True)
    rr_mapping, rr_key = await _make_mapping_for(db_session, sample_reranker_model, log_enabled=True)

    # finish_log 用独立的 AsyncSessionLocal 落库，测试环境把它指到测试引擎
    # （默认指向 .env 配置的真实数据库，测试里写不进去）
    import app.services.llm.mapping_logger as ml
    monkeypatch.setattr(ml, "AsyncSessionLocal",
                        async_sessionmaker(test_engine, class_=AsyncSession,
                                           expire_on_commit=False))

    await client.post(f"/api/v1/model-mappings/{emb_mapping.id}/v1/embeddings",
                      headers={"Authorization": f"Bearer {emb_key}"},
                      json={"model": "m", "input": ["a", "b"]})
    await client.post(f"/api/v1/model-mappings/{rr_mapping.id}/v1/rerank",
                      headers={"Authorization": f"Bearer {rr_key}"},
                      json={"model": "m", "query": "q", "documents": ["d1", "d2"]})

    rows = (await db_session.execute(select(ModelRequestLog))).scalars().all()
    by_type = {r.request_type: r for r in rows}
    assert "embedding" in by_type and "rerank" in by_type
    emb_log = by_type["embedding"]
    assert emb_log.source == "mapping" and emb_log.status == "success"
    assert emb_log.mapping_id == emb_mapping.id
    assert emb_log.response_metadata.get("vector_dim") == 8
    rr_log = by_type["rerank"]
    assert rr_log.source == "mapping" and rr_log.status == "success"
    # prompt 摘要含 query 与文档条数，而不是整段文档正文
    assert "documents: 2条" in rr_log.prompt


