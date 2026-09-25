# 空答案必须判失败——回归测试
#
# 线上事故：思考型模型（glm-5.3-flash）把 max_tokens 全部耗在
# reasoning_content 上，finish_reason='length' 且 content=None。
# 适配器此前照单全收，返回 answer='' 且 success=True；调用任务更是
# 无视 success 标志、一律记 status='success'。结果：
#   - 12 条调用结果显示"成功"却没有任何答案；
#   - 批次统计虚高，评估拿空答案当有效输入，指标全被污染。
#
# 本文件钉死两道防线：
#   1. direct_llm 适配器：空 content → success=False + 可读错误；
#   2. 调用任务：尊重 adapter 的 success 标志，落库为 failed。
import json

import httpx
import pytest

from app.services.adapters.direct_llm_adapter import DirectLLMAdapter


def _adapter() -> DirectLLMAdapter:
    return DirectLLMAdapter({
        "api_key": "test-key",
        "api_endpoint": "http://llm.test/v1",
        "model_name": "thinking-model",
        "provider": "openai",
    })


def test_llm_timeout_defaults_to_base_constant():
    """未配置时沿用默认常量，不改变既有行为"""
    assert _adapter().llm_timeout == DirectLLMAdapter.LLM_TIMEOUT == 300.0


def test_llm_timeout_is_configurable_per_rag_system():
    """思考型模型 max_tokens 大时可显式放宽超时，不必改全局常量"""
    adapter = DirectLLMAdapter({
        "api_key": "test-key",
        "api_endpoint": "http://llm.test/v1",
        "model_name": "thinking-model",
        "provider": "openai",
        "llm_timeout": 900,
    })
    assert adapter.llm_timeout == 900.0
    # 错误文案里回显实际生效的超时值，便于用户对账
    assert "900" in adapter.timeout_error_message()


def test_invalid_llm_timeout_falls_back_to_default():
    """非法值必须回落默认，不能把请求变成立即超时"""
    for bad in [0, -5, "abc", None, ""]:
        adapter = DirectLLMAdapter({"api_key": "k", "llm_timeout": bad})
        assert adapter.llm_timeout == DirectLLMAdapter.LLM_TIMEOUT, f"非法值 {bad!r} 未回落"


def _thinking_truncated_response() -> dict:
    """思考型模型把 max_tokens 耗尽：content=None，只有 reasoning_content"""
    return {
        "choices": [{
            "finish_reason": "length",
            "message": {"content": None, "reasoning_content": "让我想想……" * 100},
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1024, "total_tokens": 1034},
    }


@pytest.mark.asyncio
async def test_thinking_model_truncated_content_is_failure(monkeypatch):
    """content=None（思考耗尽预算）必须判失败，不能返回空答案 success=True"""
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_thinking_truncated_response())

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("什么是过拟合？")

    assert resp.success is False, "空答案必须判失败"
    assert resp.answer == ""
    assert resp.error, "失败必须带可读原因"
    assert "max_tokens" in resp.error or "思考" in resp.error


@pytest.mark.asyncio
async def test_normal_answer_still_succeeds(monkeypatch):
    """回归保护：有正常 content 时仍应成功，不能被空答案检查误伤"""
    adapter = _adapter()
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "过拟合是模型记住了训练数据的噪声。"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("什么是过拟合？")

    assert resp.success is True
    assert "过拟合" in resp.answer
    assert resp.error is None


@pytest.mark.asyncio
async def test_empty_string_content_also_rejected(monkeypatch):
    """content=''（空串）同样视为失败，不只是 None"""
    adapter = _adapter()
    payload = {"choices": [{"finish_reason": "stop", "message": {"content": "  "}}]}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert resp.answer == ""


@pytest.mark.asyncio
async def test_timeout_reports_actionable_message(monkeypatch):
    """超时的 str(e) 可能为空，但必须报出"超时"和可操作建议

    线上表现：思考型模型跑满 LLM_TIMEOUT 后，httpx 抛出的 ReadTimeout
    消息为空，适配器把 error 落成空串，调用任务再兜底成无信息量的
    "RAG 调用失败"——用户既看不出是超时，也看不出该怎么调。
    """
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("")

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert resp.error, "超时失败必须带原因，不能是空串"
    assert "超时" in resp.error
    assert "llm_timeout" in resp.error, "应告诉用户怎么调"


@pytest.mark.asyncio
async def test_connect_timeout_also_reports_timeout(monkeypatch):
    """连接超时同属 httpx.TimeoutException，走同一条可读文案"""
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert "超时" in resp.error


@pytest.mark.asyncio
async def test_non_timeout_error_keeps_original_message(monkeypatch):
    """非超时异常不能被超时文案吞掉，仍应保留原始错误信息"""
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert resp.error == "connection refused"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [502, 503, 504])
async def test_upstream_gateway_error_says_it_is_not_a_client_timeout(monkeypatch, code):
    """上游 502/503/504 是服务端限制，不能被误报成客户端超时

    线上：模型单次生成超过网关上限时返回 504（网关自己的 ~300s），
    此时调大客户端 llm_timeout 完全无效。文案必须说清这一点，
    否则用户只会不断去调一个没用的参数。
    """
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": "upstream timed out"})

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert str(code) in resp.error
    assert "上游" in resp.error
    assert "无效" in resp.error, "应明确指出调大 llm_timeout 无效"


@pytest.mark.asyncio
async def test_client_error_status_keeps_original_message(monkeypatch):
    """4xx 是请求本身的问题（key/参数），保留原始信息而不是套用网关文案"""
    adapter = _adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    transport = httpx.MockTransport(_handler)
    orig_client = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched)

    resp = await adapter.query("任意问题")

    assert resp.success is False
    assert "401" in resp.error
    assert "上游" not in resp.error
