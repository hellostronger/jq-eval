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
async def test_timeout_with_empty_message_still_reports_reason(monkeypatch):
    """超时的 str(e) 可能为空——失败原因不能因此丢失

    线上表现：思考型模型跑满 300s LLM_TIMEOUT 后，httpx 抛出的超时异常
    消息为空，适配器把 error 落成空串，调用任务再兜底成无信息量的
    "RAG 调用失败"，用户完全看不出是超时。这里钉死：空消息也必须有原因。
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
    assert resp.error == "ReadTimeout"


@pytest.mark.asyncio
async def test_connect_timeout_with_empty_message_still_reports_reason(monkeypatch):
    """连接超时同理：str() 为空时兜底为异常类名"""
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
    assert resp.error == "ConnectTimeout"
