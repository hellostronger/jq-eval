# 出站客户端 - 映射代理调用目标模型（openai 兼容 / anthropic 协议，httpx 直调）
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.models.model import Model

from .protocol_converter import (
    InternalRequest,
    InternalResponse,
    InternalStreamEvent,
    anthropic_response_to_internal,
    internal_to_anthropic_call_body,
    internal_to_openai_call_body,
    openai_response_to_internal,
    parse_openai_stream_line,
    AnthropicStreamAggregator,
)

logger = logging.getLogger(__name__)


class OutboundError(Exception):
    """出站调用失败（上游返回非 200 或网络错误）"""

    def __init__(self, status_code: int, message: str, body: Optional[Dict] = None):
        self.status_code = status_code
        self.message = message
        self.body = body or {}
        super().__init__(message)


# 流式读超时：read 必须为 None，避免长思考模型的 token 间隔被掐断
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
# 非流式超时
CALL_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def _openai_chat_url(model: Model) -> str:
    """openai 系出站 URL（azure 走 deployments 路径）"""
    endpoint = (model.endpoint or "").rstrip("/")
    provider = model.provider or "openai"
    model_name = model.model_name or model.name

    if provider == "azure":
        return f"{endpoint}/deployments/{model_name}/chat/completions?api-version=2024-02-01"
    return f"{endpoint}/chat/completions"


def _openai_headers(model: Model) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    provider = model.provider or "openai"
    if provider == "azure":
        headers["api-key"] = model.api_key_encrypted or ""
    else:
        headers["Authorization"] = f"Bearer {model.api_key_encrypted or ''}"
    return headers


def _anthropic_messages_url(model: Model) -> str:
    """anthropic 出站 URL（endpoint 已含 /v1 时智能拼接）"""
    endpoint = (model.endpoint or "").rstrip("/")
    if endpoint.endswith("/v1"):
        return f"{endpoint}/messages"
    return f"{endpoint}/v1/messages"


def _anthropic_headers(model: Model) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": model.api_key_encrypted or "",
        "anthropic-version": "2023-06-01",
    }


def _resolve_outbound(target: Model, outbound: Optional[str]) -> str:
    """决定出站协议：provider=anthropic 走 Messages API，其余走 chat/completions"""
    if outbound:
        return outbound
    return "anthropic" if (target.provider or "") == "anthropic" else "openai"


def _default_max_tokens(target: Model) -> int:
    params = target.params or {}
    return int(params.get("max_tokens") or 2048)


async def call(target: Model, req: InternalRequest, outbound: Optional[str] = None) -> InternalResponse:
    """非流式出站调用"""
    outbound = _resolve_outbound(target, outbound)
    model_name = target.model_name or target.name

    if outbound == "anthropic":
        url = _anthropic_messages_url(target)
        headers = _anthropic_headers(target)
        body = internal_to_anthropic_call_body(req, model_name, _default_max_tokens(target))
    else:
        url = _openai_chat_url(target)
        headers = _openai_headers(target)
        body = internal_to_openai_call_body(req, model_name)

    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as e:
        raise OutboundError(504, f"上游模型请求超时: {e}") from e
    except httpx.HTTPError as e:
        raise OutboundError(502, f"无法连接上游模型: {e}") from e

    if response.status_code != 200:
        _raise_upstream_error(response)

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as e:
        raise OutboundError(502, f"上游响应解析失败: {e}") from e

    if outbound == "anthropic":
        return anthropic_response_to_internal(data, model=model_name)
    return openai_response_to_internal(data, model=model_name)


def _raise_upstream_error(response: httpx.Response):
    """上游非 200：提取错误信息抛 OutboundError"""
    try:
        data = response.json()
    except Exception:
        data = {}
    # openai 风格: {"error": {"message": ...}}；anthropic 风格: {"error": {"type", "message"}}
    err = data.get("error")
    if isinstance(err, dict):
        message = err.get("message") or str(err)
    elif isinstance(err, str):
        message = err
    else:
        message = response.text[:500] or f"上游返回 {response.status_code}"
    raise OutboundError(response.status_code, message, body=data)


def _stream_request_body(target: Model, req: InternalRequest, outbound: str,
                         include_usage: bool) -> Dict[str, Any]:
    """构建流式出站请求体"""
    model_name = target.model_name or target.name
    if outbound == "anthropic":
        return internal_to_anthropic_call_body(req, model_name, _default_max_tokens(target))
    body = internal_to_openai_call_body(req, model_name)
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    return body


async def _openai_stream_iter(target: Model, req: InternalRequest,
                              include_usage: bool) -> AsyncIterator[InternalStreamEvent]:
    """[OI] 出站流式：解析 data: 行 / [DONE]"""
    url = _openai_chat_url(target)
    headers = _openai_headers(target)
    body = _stream_request_body(target, req, "openai", include_usage)

    try:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    await response.aread()
                    _raise_upstream_error(response)

                async for line in response.aiter_lines():
                    for event in parse_openai_stream_line(line):
                        yield event
    except httpx.TimeoutException as e:
        yield InternalStreamEvent(kind="error", raw={"error": {"message": f"上游模型请求超时: {e}"}})


async def _anthropic_stream_iter(target: Model, req: InternalRequest) -> AsyncIterator[InternalStreamEvent]:
    """anthropic 出站流式：跨行聚合 event:/data: 事件"""
    url = _anthropic_messages_url(target)
    headers = _anthropic_headers(target)
    body = _stream_request_body(target, req, "anthropic", False)

    aggregator = AnthropicStreamAggregator()
    try:
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    await response.aread()
                    _raise_upstream_error(response)

                async for line in response.aiter_lines():
                    for event in aggregator.feed_line(line):
                        yield event
                # 流结束时冲刷残留事件
                for event in aggregator._flush():
                    yield event
    except httpx.TimeoutException as e:
        yield InternalStreamEvent(kind="error", raw={"error": {"message": f"上游模型请求超时: {e}"}})


async def stream_call(target: Model, req: InternalRequest,
                      outbound: Optional[str] = None) -> AsyncIterator[InternalStreamEvent]:
    """流式出站调用，产出内部流式事件。

    openai 上游对 stream_options.include_usage 支持参差（部分兼容网关报 400），
    首次因该参数 400 时去掉参数重试一次。
    """
    outbound = _resolve_outbound(target, outbound)

    if outbound == "anthropic":
        async for event in _anthropic_stream_iter(target, req):
            yield event
        return

    # openai 出站：先带 include_usage 尝试；若上游因该参数报 400，去参重试一次
    try:
        async for event in _openai_stream_iter(target, req, include_usage=True):
            yield event
    except OutboundError as e:
        if "stream_options" in e.message or "stream_options" in str(e.body):
            async for event in _openai_stream_iter(target, req, include_usage=False):
                yield event
        else:
            raise
