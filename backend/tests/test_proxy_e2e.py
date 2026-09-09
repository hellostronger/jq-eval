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
