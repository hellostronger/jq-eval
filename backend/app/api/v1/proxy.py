# 模型调用映射代理路由 - 对外暴露 OpenAI/Anthropic 协议端点，转发到目标模型
import asyncio
import hmac
import json
import logging
import time
from typing import AsyncIterator, Dict, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...core.database import get_db
from ...models import Model, ModelMapping
from ...services.llm import outbound_client
from ...services.llm.mapping_logger import finish_log, start_log
from ...services.llm.outbound_client import OutboundError
from ...services.llm.protocol_converter import (
    InternalRequest,
    InternalStreamEvent,
    anthropic_request_to_internal,
    internal_to_anthropic_response,
    internal_to_openai_response,
    openai_request_to_internal,
    merge_usage,
    sse_format,
    usage_to_openai,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 鉴权与校验
# ---------------------------------------------------------------------------

def _extract_api_key(request: Request) -> Optional[str]:
    """提取密钥：Authorization: Bearer 优先，其次 x-api-key"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.headers.get("x-api-key")


async def verify_mapping(mapping_id: UUID, request: Request,
                         db: AsyncSession) -> Tuple[ModelMapping, Model]:
    """校验映射服务与密钥，返回 (mapping, target)"""
    result = await db.execute(select(ModelMapping).where(ModelMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射服务不存在")
    if mapping.status != "active":
        raise HTTPException(status_code=403, detail="映射服务已停用")

    if mapping.auth_required:
        key = _extract_api_key(request)
        if not key:
            raise HTTPException(status_code=401, detail="缺少 API Key")
        if not mapping.api_key or not hmac.compare_digest(key, mapping.api_key):
            raise HTTPException(status_code=401, detail="API Key 无效")

    result = await db.execute(select(Model).where(Model.id == mapping.target_model_id))
    target = result.scalar_one_or_none()
    if not target or target.model_type != "llm":
        raise HTTPException(status_code=400, detail="目标模型不存在或不是 LLM 类型")
    if target.status != "active":
        raise HTTPException(status_code=403, detail="目标模型已停用")

    return mapping, target


# ---------------------------------------------------------------------------
# 入站协议错误响应
# ---------------------------------------------------------------------------

def _is_anthropic_inbound(inbound: str) -> bool:
    return inbound == "anthropic"


def protocol_error(status_code: int, message: str, inbound: str,
                   error_type: Optional[str] = None) -> JSONResponse:
    """按入站协议格式返回错误"""
    if _is_anthropic_inbound(inbound):
        type_map = {401: "authentication_error", 403: "permission_error",
                    404: "not_found_error", 400: "invalid_request_error"}
        return JSONResponse(
            status_code=status_code,
            content={"type": "error",
                     "error": {"type": error_type or type_map.get(status_code, "api_error"),
                               "message": message}},
        )
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message,
                           "type": "invalid_request_error" if status_code < 500 else "api_error",
                           "code": str(status_code)}},
    )


async def _http_exception_response(e: HTTPException, inbound: str) -> JSONResponse:
    return protocol_error(e.status_code, str(e.detail), inbound)


# ---------------------------------------------------------------------------
# 公共执行流程
# ---------------------------------------------------------------------------

async def _execute_mapping(mapping: ModelMapping, target: Model,
                           internal: InternalRequest, inbound: str,
                           raw_request: Dict, db: AsyncSession):
    """统一执行：出站调用 + 日志 + 协议响应"""
    outbound = "anthropic" if (target.provider or "") == "anthropic" else "openai"
    start_time = time.time()

    # 记录调用
    log_id = None
    if mapping.log_enabled:
        try:
            log_id = await start_log(db, mapping, target, internal, inbound, outbound, raw_request)
        except Exception as e:
            logger.warning(f"写入映射调用日志失败: {e}")

    if not internal.stream:
        # 非流式
        try:
            result = await outbound_client.call(target, internal, outbound)
        except OutboundError as e:
            if log_id:
                await finish_log(log_id, None, status="failed", error=e.message,
                                 latency_ms=int((time.time() - start_time) * 1000),
                                 mapping_id=mapping.id)
            return protocol_error(e.status_code if e.status_code >= 400 else 502, e.message, inbound)
        except Exception as e:
            if log_id:
                await finish_log(log_id, None, status="failed", error=str(e),
                                 latency_ms=int((time.time() - start_time) * 1000),
                                 mapping_id=mapping.id)
            return protocol_error(502, f"上游调用失败: {e}", inbound)

        latency_ms = int((time.time() - start_time) * 1000)
        if log_id:
            await finish_log(
                log_id, result.content, usage=result.usage,
                finish_reason=result.stop_reason, raw_stop_reason=result.raw_stop_reason,
                latency_ms=latency_ms, status="success",
                outbound_protocol=outbound, mapping_id=mapping.id,
            )

        if inbound == "anthropic":
            return internal_to_anthropic_response(result)
        return internal_to_openai_response(result)

    # 流式：SSE 转发
    return _build_streaming_response(mapping, target, internal, inbound, outbound,
                                     log_id, start_time)


def _inbound_sse_generator(mapping: ModelMapping, target: Model,
                           internal: InternalRequest, inbound: str, outbound: str,
                           log_id, start_time: float) -> AsyncIterator[str]:
    """流式生成器：出站内部事件 -> 入站协议 SSE（聚合日志回填放 finally）"""
    collected = []
    first_token_ts = None
    final_usage = None
    finish_reason = None
    raw_stop_reason = None
    chunk_count = 0
    error_message = None
    # openai 入站流式工具调用聚合：anthropic 出站事件 -> openai tool_calls 增量
    tool_state: Dict[int, Dict] = {}

    import uuid as _uuid

    if inbound == "openai":
        chunk_id = f"chatcmpl-{_uuid.uuid4().hex[:24]}"
        created = int(time.time())
        model_name = target.model_name or target.name

    async def gen():
        nonlocal first_token_ts, final_usage, finish_reason, raw_stop_reason, chunk_count, error_message

        # anthropic 入站先发 message_start
        if inbound == "anthropic":
            yield sse_format("message_start", {
                "type": "message_start",
                "message": {
                    "id": f"msg_{_uuid.uuid4().hex[:24]}", "type": "message", "role": "assistant",
                    "model": target.model_name or target.name, "content": [],
                    "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            })
            block_started = False
        else:
            block_started = True  # openai 无需 content_block 管理

        upstream_error = None
        completed = False
        try:
            async for ev in outbound_client.stream_call(target, internal, outbound):
                if ev.kind == "start":
                    # anthropic message_start 携带 input usage：先落底，后续 final 合并
                    if ev.usage:
                        final_usage = usage_to_openai(ev.usage)
                    continue

                if ev.kind == "delta" and ev.text:
                    if first_token_ts is None:
                        first_token_ts = (time.time() - start_time) * 1000
                    collected.append(ev.text)
                    chunk_count += 1
                    if inbound == "openai":
                        yield sse_format(None, {
                            "id": chunk_id, "object": "chat.completion.chunk",
                            "created": created, "model": model_name,
                            "choices": [{"index": 0, "delta": {"content": ev.text}, "finish_reason": None}],
                        })
                    else:
                        if not block_started:
                            block_started = True
                            yield sse_format("content_block_start", {
                                "type": "content_block_start", "index": 0,
                                "content_block": {"type": "text", "text": ""},
                            })
                        yield sse_format("content_block_delta", {
                            "type": "content_block_delta", "index": 0,
                            "delta": {"type": "text_delta", "text": ev.text},
                        })

                elif ev.kind == "delta" and ev.raw:  # 工具调用增量
                    if inbound == "openai":
                        chunk_count += 1
                        # anthropic 出站的工具事件（content_block_start/input_json_delta）
                        # 需转换为 openai tool_calls 增量格式；openai 出站直接透传 raw
                        raw = ev.raw or {}
                        if raw.get("type") in ("content_block_start", "content_block_delta"):
                            converted = _anthropic_tool_event_to_openai_chunk(tool_state, raw)
                            if converted:
                                converted.update({"id": chunk_id, "object": "chat.completion.chunk",
                                                  "created": created, "model": model_name})
                                yield sse_format(None, converted)
                        else:
                            yield sse_format(None, ev.raw)
                    # anthropic 入站暂不支持流式工具调用透传（openai 中间格式无法映射回 anthropic 块）

                elif ev.kind == "final":
                    if ev.finish_reason:
                        finish_reason = ev.finish_reason
                    if ev.raw_stop_reason:
                        raw_stop_reason = ev.raw_stop_reason
                    if ev.usage:
                        # 合并 start（input）与 final（output/total）两侧的 usage
                        final_usage = merge_usage(final_usage, usage_to_openai(ev.usage))
                    completed = True

                elif ev.kind == "error":
                    upstream_error = (ev.raw or {}).get("error", {}).get("message") or "上游流式调用失败"
                    break

            if upstream_error:
                error_message = upstream_error
                if inbound == "openai":
                    yield sse_format(None, {
                        "id": chunk_id, "object": "chat.completion.chunk",
                        "created": created, "model": model_name,
                        "choices": [{"index": 0, "delta": {"content": f"\n[上游错误] {upstream_error}"},
                                     "finish_reason": "stop"}],
                    })
                    yield "data: [DONE]\n\n"
                else:
                    yield sse_format("error", {
                        "type": "error",
                        "error": {"type": "api_error", "message": upstream_error},
                    })
                return

            # 正常收尾
            if inbound == "openai":
                yield sse_format(None, {
                    "id": chunk_id, "object": "chat.completion.chunk",
                    "created": created, "model": model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason or "stop"}],
                })
                if final_usage:
                    yield sse_format(None, {
                        "id": chunk_id, "object": "chat.completion.chunk",
                        "created": created, "model": model_name,
                        "choices": [],
                        "usage": final_usage,
                    })
                yield "data: [DONE]\n\n"
            else:
                if block_started:
                    yield sse_format("content_block_stop", {"type": "content_block_stop", "index": 0})
                anthropic_stop = _openai_to_anthropic_stop(finish_reason)
                yield sse_format("message_delta", {
                    "type": "message_delta",
                    "delta": {"stop_reason": anthropic_stop, "stop_sequence": None},
                    "usage": {
                        "input_tokens": (final_usage or {}).get("prompt_tokens", 0),
                        "output_tokens": (final_usage or {}).get("completion_tokens", 0),
                    },
                })
                yield sse_format("message_stop", {"type": "message_stop"})

        except asyncio.CancelledError:
            # 客户端断连：不吞掉取消异常，让 finally 落日志
            error_message = error_message or "client disconnected"
            raise
        except Exception as e:
            error_message = str(e)
            logger.warning(f"映射流式转发异常: {e}")
            try:
                if inbound == "openai":
                    yield "data: [DONE]\n\n"
                else:
                    yield sse_format("error", {"type": "error",
                                               "error": {"type": "api_error", "message": str(e)}})
            except Exception:
                pass
        finally:
            status = "success" if (completed and not error_message) else "failed"
            if log_id:
                latency_ms = int((time.time() - start_time) * 1000)
                await asyncio.shield(finish_log(
                    log_id, "".join(collected) or None,
                    usage=final_usage, finish_reason=finish_reason,
                    raw_stop_reason=raw_stop_reason,
                    first_token_ms=int(first_token_ts) if first_token_ts else None,
                    latency_ms=latency_ms,
                    error=error_message, status=status,
                    outbound_protocol=outbound,
                    extra_metadata={"stream": True, "chunk_count": chunk_count},
                    mapping_id=mapping.id,
                ))

    return gen()


def _anthropic_tool_event_to_openai_chunk(state: Dict, raw: Dict) -> Optional[Dict]:
    """anthropic 工具流事件（content_block_start tool_use / input_json_delta）-> openai chunk delta 片段"""
    dtype = raw.get("type")
    index = raw.get("index", 0)
    if dtype == "content_block_start":
        block = raw.get("content_block", {}) or {}
        entry = {"id": block.get("id", ""), "name": block.get("name", ""), "arguments": ""}
        state[index] = entry
        return {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": index, "id": entry["id"], "type": "function",
             "function": {"name": entry["name"], "arguments": ""}},
        ]}, "finish_reason": None}]}
    if dtype == "content_block_delta":
        delta = raw.get("delta", {}) or {}
        if delta.get("type") == "input_json_delta":
            partial = delta.get("partial_json", "") or ""
            if index in state:
                state[index]["arguments"] += partial
            return {"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": index, "function": {"arguments": partial}},
            ]}, "finish_reason": None}]}
    return None


def _openai_to_anthropic_stop(finish_reason: Optional[str]) -> str:
    from ...services.llm.protocol_converter import openai_finish_to_anthropic
    return openai_finish_to_anthropic(finish_reason)


def _build_streaming_response(mapping: ModelMapping, target: Model,
                              internal: InternalRequest, inbound: str, outbound: str,
                              log_id, start_time: float) -> StreamingResponse:
    gen = _inbound_sse_generator(mapping, target, internal, inbound, outbound, log_id, start_time)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# 代理端点（OpenAI 入站 + Anthropic 入站，带/不带 /v1 别名）
# ---------------------------------------------------------------------------

async def _handle_openai_inbound(mapping_id: UUID, request: Request, db: AsyncSession):
    inbound = "openai"
    try:
        mapping, target = await verify_mapping(mapping_id, request, db)
    except HTTPException as e:
        return await _http_exception_response(e, inbound)

    try:
        body = await request.json()
    except Exception:
        return protocol_error(400, "请求体不是合法 JSON", inbound)
    if not isinstance(body, dict):
        return protocol_error(400, "请求体必须是 JSON 对象", inbound)

    internal = openai_request_to_internal(body)
    return await _execute_mapping(mapping, target, internal, inbound, body, db)


async def _handle_anthropic_inbound(mapping_id: UUID, request: Request, db: AsyncSession):
    inbound = "anthropic"
    try:
        mapping, target = await verify_mapping(mapping_id, request, db)
    except HTTPException as e:
        return await _http_exception_response(e, inbound)

    try:
        body = await request.json()
    except Exception:
        return protocol_error(400, "请求体不是合法 JSON", inbound)
    if not isinstance(body, dict):
        return protocol_error(400, "请求体必须是 JSON 对象", inbound)

    internal = anthropic_request_to_internal(body)
    return await _execute_mapping(mapping, target, internal, inbound, body, db)


@router.post("/{mapping_id}/v1/chat/completions")
@router.post("/{mapping_id}/chat/completions")
async def proxy_openai_chat(mapping_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """[OI] 协议入站（chat/completions）"""
    return await _handle_openai_inbound(mapping_id, request, db)


@router.post("/{mapping_id}/v1/messages")
@router.post("/{mapping_id}/messages")
async def proxy_anthropic_messages(mapping_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Anthropic 协议入站（v1/messages）"""
    return await _handle_anthropic_inbound(mapping_id, request, db)


@router.get("/{mapping_id}/v1/models")
async def proxy_list_models(mapping_id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """[OI] SDK list 兼容：返回目标模型单条列表"""
    inbound = "openai"
    try:
        mapping, target = await verify_mapping(mapping_id, request, db)
    except HTTPException as e:
        return await _http_exception_response(e, inbound)

    model_name = target.model_name or target.name
    return {
        "object": "list",
        "data": [{"id": model_name, "object": "model", "owned_by": "jq-eval-mapping"}],
    }
