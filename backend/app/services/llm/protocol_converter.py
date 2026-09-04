# 协议转换服务 - [OI] 协议与 Anthropic 协议互转（以内部中间表示为中心）
# 纯函数、无 IO，入站协议与出站协议解耦
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部中间表示（Internal IR）
# ---------------------------------------------------------------------------

@dataclass
class InternalMessage:
    """内部消息表示"""
    role: str  # system/user/assistant/tool
    content: str = ""  # 纯文本聚合
    tool_calls: Optional[List[Dict]] = None  # assistant 发起的工具调用 [{id,name,arguments(dict)}]
    tool_call_id: Optional[str] = None  # tool 角色消息对应的调用ID


@dataclass
class InternalRequest:
    """内部请求表示"""
    model: Optional[str] = None  # 出站时使用 target 模型名
    messages: List[InternalMessage] = field(default_factory=list)
    system: Optional[str] = None  # 独立的系统提示
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[List[str]] = None
    tools: Optional[List[Dict]] = None  # 内部格式 {name,description,parameters}
    tool_choice: Optional[Any] = None  # 内部格式 auto/none/required/{name}
    stream: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)  # 其余透传字段


@dataclass
class InternalResponse:
    """内部响应表示"""
    content: str = ""
    tool_calls: Optional[List[Dict]] = None
    stop_reason: str = "stop"  # 统一用 openai 语义: stop/length/tool_calls
    raw_stop_reason: Optional[str] = None  # 上游原始值（排查用）
    usage: Optional[Dict[str, int]] = None  # {prompt_tokens, completion_tokens, total_tokens}
    model: Optional[str] = None


@dataclass
class InternalStreamEvent:
    """内部流式事件"""
    kind: str  # start/delta/final/error
    text: Optional[str] = None  # kind=delta 时的内容增量
    finish_reason: Optional[str] = None  # kind=final 时的结束原因（openai 语义）
    raw_stop_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None  # start 时 input 侧 / final 时完整 usage
    raw: Optional[Dict[str, Any]] = None  # 原始事件数据（透传/排查用）


# ---------------------------------------------------------------------------
# 结束原因与用量映射
# ---------------------------------------------------------------------------

# anthropic stop_reason -> openai finish_reason
ANTHROPIC_TO_OPENAI_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}

# openai finish_reason -> anthropic stop_reason
OPENAI_TO_ANTHROPIC_STOP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
}


def anthropic_finish_to_openai(stop_reason: Optional[str]) -> str:
    """anthropic stop_reason 转 openai finish_reason"""
    if not stop_reason:
        return "stop"
    return ANTHROPIC_TO_OPENAI_FINISH.get(stop_reason, "stop")


def openai_finish_to_anthropic(finish_reason: Optional[str]) -> str:
    """openai finish_reason 转 anthropic stop_reason"""
    if not finish_reason:
        return "end_turn"
    return OPENAI_TO_ANTHROPIC_STOP.get(finish_reason, "end_turn")


def usage_to_openai(usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """anthropic 用量转 openai 用量"""
    if not usage:
        return None
    if "prompt_tokens" in usage:  # 已是 openai 格式
        return usage
    prompt = usage.get("input_tokens") or 0
    completion = usage.get("output_tokens") or 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def usage_to_anthropic(usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """openai 用量转 anthropic 用量"""
    if not usage:
        return None
    if "input_tokens" in usage:  # 已是 anthropic 格式
        return usage
    return {
        "input_tokens": usage.get("prompt_tokens") or 0,
        "output_tokens": usage.get("completion_tokens") or 0,
    }


# ---------------------------------------------------------------------------
# 内容块解析辅助
# ---------------------------------------------------------------------------

def _text_from_anthropic_content(content: Any) -> str:
    """anthropic content（str 或块数组）聚合为纯文本"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _text_from_openai_content(content: Any) -> str:
    """openai content（str 或多段数组）聚合为纯文本"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _openai_tool_calls_to_internal(tool_calls: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """openai tool_calls -> 内部格式（arguments JSON 字符串转 dict）"""
    if not tool_calls:
        return None
    result = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}
        result.append({
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "arguments": args or {},
        })
    return result


def _internal_tool_calls_to_anthropic_blocks(tool_calls: Optional[List[Dict]]) -> List[Dict]:
    """内部工具调用 -> anthropic tool_use content 块"""
    blocks = []
    for tc in tool_calls or []:
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": tc.get("name", ""),
            "input": tc.get("arguments") or {},
        })
    return blocks


def _internal_tools_to_anthropic(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """内部工具定义 -> anthropic tools"""
    if not tools:
        return None
    return [
        {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
        }
        for t in tools
    ]


def _anthropic_tools_to_internal(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """anthropic tools -> 内部工具定义"""
    if not tools:
        return None
    return [
        {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
        }
        for t in tools
    ]


def _anthropic_tool_choice_to_internal(tool_choice: Optional[Any]) -> Optional[Any]:
    """anthropic tool_choice -> 内部格式"""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type")
        if tc_type == "auto":
            return "auto"
        if tc_type == "any":
            return "required"
        if tc_type == "tool":
            return {"name": tool_choice.get("name", "")}
    return "auto"


def _internal_tool_choice_to_anthropic(tool_choice: Optional[Any]) -> Optional[Dict]:
    """内部 tool_choice -> anthropic 格式；none 时由调用方去掉 tools"""
    if tool_choice is None or tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice == "required":
        return {"type": "any"}
    if isinstance(tool_choice, dict) and "name" in tool_choice:
        return {"type": "tool", "name": tool_choice["name"]}
    return {"type": "auto"}


def _internal_tool_choice_to_openai(tool_choice: Optional[Any]) -> Optional[Any]:
    """内部 tool_choice -> openai 格式"""
    if tool_choice is None:
        return None
    if tool_choice == "auto":
        return "auto"
    if tool_choice == "none":
        return "none"
    if tool_choice == "required":
        return "required"
    if isinstance(tool_choice, dict) and "name" in tool_choice:
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return "auto"


def _anthropic_tool_choice_to_internal_full(tool_choice: Optional[Any]) -> Optional[Any]:
    """anthropic tool_choice -> 内部格式（含 none 语义处理占位）"""
    return _anthropic_tool_choice_to_internal(tool_choice)


# ---------------------------------------------------------------------------
# 入站请求 -> 内部表示
# ---------------------------------------------------------------------------

def openai_request_to_internal(body: Dict[str, Any]) -> InternalRequest:
    """[OI] /chat/completions 请求体 -> InternalRequest"""
    messages: List[InternalMessage] = []
    system_parts: List[str] = []

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "system" or role == "developer":
            text = _text_from_openai_content(content)
            if text:
                system_parts.append(text)
            continue

        if role == "tool":
            messages.append(InternalMessage(
                role="tool",
                content=_text_from_openai_content(content),
                tool_call_id=msg.get("tool_call_id"),
            ))
            continue

        im = InternalMessage(role=role, content=_text_from_openai_content(content))
        if role == "assistant" and msg.get("tool_calls"):
            im.tool_calls = _openai_tool_calls_to_internal(msg.get("tool_calls"))
        messages.append(im)

    stop = body.get("stop") or body.get("stop_sequences")
    if isinstance(stop, str):
        stop = [stop]

    # 工具定义
    tools = None
    if body.get("tools"):
        tools = []
        for t in body["tools"]:
            fn = t.get("function", {})
            if fn.get("name"):
                tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                })
        if not tools:
            tools = None

    known = {"model", "messages", "temperature", "top_p", "max_tokens", "max_completion_tokens",
             "stop", "stop_sequences", "tools", "tool_choice", "stream", "stream_options", "n", "user"}
    extra = {k: v for k, v in body.items() if k not in known}

    return InternalRequest(
        model=body.get("model"),
        messages=messages,
        system="\n".join(system_parts) if system_parts else None,
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        max_tokens=body.get("max_tokens") or body.get("max_completion_tokens"),
        stop=stop,
        tools=tools,
        tool_choice=body.get("tool_choice"),
        stream=bool(body.get("stream", False)),
        extra=extra,
    )


def anthropic_request_to_internal(body: Dict[str, Any]) -> InternalRequest:
    """Anthropic /v1/messages 请求体 -> InternalRequest"""
    messages: List[InternalMessage] = []

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content")

        # content 为字符串：简单消息
        if isinstance(content, str):
            messages.append(InternalMessage(role=role, content=content))
            continue

        blocks = content if isinstance(content, list) else []
        text_parts: List[str] = []
        tool_results: List[Dict] = []  # user 消息里的 tool_result 块
        tool_uses: List[Dict] = []  # assistant 消息里的 tool_use 块

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_uses.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": block.get("input") or {},
                })
            elif btype == "tool_result":
                tool_results.append({
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": _text_from_anthropic_content(block.get("content")),
                })

        # tool_result 块拆成独立的 tool 消息
        for tr in tool_results:
            messages.append(InternalMessage(
                role="tool",
                content=tr["content"],
                tool_call_id=tr["tool_use_id"],
            ))

        im = InternalMessage(role=role, content="".join(text_parts))
        if role == "assistant" and tool_uses:
            im.tool_calls = tool_uses
        messages.append(im)

    # 顶层 system（字符串或块数组）
    system = _text_from_anthropic_content(body.get("system")) or None

    return InternalRequest(
        model=body.get("model"),
        messages=messages,
        system=system,
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        max_tokens=body.get("max_tokens"),
        stop=body.get("stop_sequences"),
        tools=_anthropic_tools_to_internal(body.get("tools")),
        tool_choice=_anthropic_tool_choice_to_internal(body.get("tool_choice")),
        stream=bool(body.get("stream", False)),
        extra={k: v for k, v in body.items()
               if k not in {"model", "messages", "system", "temperature", "top_p",
                            "max_tokens", "stop_sequences", "tools", "tool_choice", "stream", "metadata"}},
    )


# ---------------------------------------------------------------------------
# 内部表示 -> 出站请求体
# ---------------------------------------------------------------------------

def internal_to_openai_call_body(req: InternalRequest, model_name: str) -> Dict[str, Any]:
    """InternalRequest -> [OI] /chat/completions 出站请求体"""
    messages: List[Dict] = []

    if req.system:
        messages.append({"role": "system", "content": req.system})

    for m in req.messages:
        if m.role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id or "",
                "content": m.content,
            })
            continue

        msg: Dict[str, Any] = {"role": m.role, "content": m.content}
        if m.role == "assistant" and m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ]
            if not msg["content"]:
                msg["content"] = None
        messages.append(msg)

    body: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": req.stream,
    }

    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.top_p is not None:
        body["top_p"] = req.top_p
    if req.max_tokens is not None:
        body["max_tokens"] = req.max_tokens
    if req.stop:
        body["stop"] = req.stop

    # 工具
    tool_choice = req.tool_choice
    if req.tools and tool_choice != "none":
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for t in req.tools
        ]
        mapped = _internal_tool_choice_to_openai(tool_choice)
        if mapped is not None:
            body["tool_choice"] = mapped

    # 透传扩展字段
    for k, v in req.extra.items():
        body.setdefault(k, v)

    return body


def internal_to_anthropic_call_body(req: InternalRequest, model_name: str,
                                    default_max_tokens: int = 2048) -> Dict[str, Any]:
    """InternalRequest -> Anthropic /v1/messages 出站请求体"""
    messages: List[Dict] = []

    for m in req.messages:
        if m.role == "system":
            # 不应出现（入站已抽取），兜底放 messages
            messages.append({"role": "user", "content": m.content})
            continue

        if m.role == "tool":
            # tool 消息转为 user 消息内的 tool_result 块
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                ],
            })
            continue

        blocks: List[Dict] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        if m.role == "assistant" and m.tool_calls:
            blocks.extend(_internal_tool_calls_to_anthropic_blocks(m.tool_calls))
        if not blocks:
            blocks.append({"type": "text", "text": ""})
        messages.append({"role": m.role, "content": blocks})

    body: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        # anthropic max_tokens 必填，缺省兜底
        "max_tokens": req.max_tokens if req.max_tokens is not None else default_max_tokens,
        "stream": req.stream,
    }

    if req.system:
        body["system"] = req.system
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.top_p is not None:
        body["top_p"] = req.top_p
    if req.stop:
        body["stop_sequences"] = req.stop

    # 工具（tool_choice=none 时不带 tools）
    tool_choice = req.tool_choice
    if req.tools and tool_choice != "none":
        body["tools"] = _internal_tools_to_anthropic(req.tools)
        body["tool_choice"] = _internal_tool_choice_to_anthropic(tool_choice)

    # 透传扩展字段
    for k, v in req.extra.items():
        body.setdefault(k, v)

    return body


# ---------------------------------------------------------------------------
# 出站响应 -> 内部表示
# ---------------------------------------------------------------------------

def openai_response_to_internal(data: Dict[str, Any], model: Optional[str] = None) -> InternalResponse:
    """[OI] chat.completion 响应 -> InternalResponse"""
    choices = data.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message", {}) or {}
    finish_reason = choice.get("finish_reason") or "stop"

    tool_calls = _openai_tool_calls_to_internal(message.get("tool_calls"))

    return InternalResponse(
        content=_text_from_openai_content(message.get("content")),
        tool_calls=tool_calls,
        stop_reason=finish_reason,
        raw_stop_reason=finish_reason,
        usage=usage_to_openai(data.get("usage")),
        model=data.get("model") or model,
    )


def anthropic_response_to_internal(data: Dict[str, Any], model: Optional[str] = None) -> InternalResponse:
    """Anthropic messages 响应 -> InternalResponse"""
    content = data.get("content") or []

    text_parts: List[str] = []
    tool_calls: List[Dict] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "arguments": block.get("input") or {},
            })

    stop_reason = data.get("stop_reason") or "end_turn"

    return InternalResponse(
        content="".join(text_parts),
        tool_calls=tool_calls or None,
        stop_reason=anthropic_finish_to_openai(stop_reason),
        raw_stop_reason=stop_reason,
        usage=usage_to_openai(data.get("usage")),
        model=data.get("model") or model,
    )


# ---------------------------------------------------------------------------
# 内部表示 -> 入站响应
# ---------------------------------------------------------------------------

def internal_to_openai_response(resp: InternalResponse) -> Dict[str, Any]:
    """InternalResponse -> [OI] chat.completion 响应"""
    import time as _time
    import uuid as _uuid

    message: Dict[str, Any] = {"role": "assistant", "content": resp.content}
    if resp.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                },
            }
            for tc in resp.tool_calls
        ]
        if not resp.content:
            message["content"] = None

    return {
        "id": f"chatcmpl-{_uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(_time.time()),
        "model": resp.model or "",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": resp.stop_reason or "stop",
            }
        ],
        "usage": usage_to_openai(resp.usage) or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def internal_to_anthropic_response(resp: InternalResponse) -> Dict[str, Any]:
    """InternalResponse -> Anthropic messages 响应"""
    import time as _time
    import uuid as _uuid

    content: List[Dict] = []
    if resp.content:
        content.append({"type": "text", "text": resp.content})
    if resp.tool_calls:
        content.extend(_internal_tool_calls_to_anthropic_blocks(resp.tool_calls))
    if not content:
        content.append({"type": "text", "text": ""})

    usage = usage_to_anthropic(resp.usage) or {"input_tokens": 0, "output_tokens": 0}

    return {
        "id": f"msg_{_uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": resp.model or "",
        "content": content,
        "stop_reason": openai_finish_to_anthropic(resp.stop_reason),
        "stop_sequence": None,
        "usage": usage,
    }


# ---------------------------------------------------------------------------
# SSE 格式化与流式解析
# ---------------------------------------------------------------------------

def sse_format(event: Optional[str], data: Any) -> str:
    """SSE 帧格式化。anthropic 需要 event:+data: 两行，openai 仅 data: 行"""
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False)
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def openai_chunk_to_events(chunk: Dict[str, Any]) -> List[InternalStreamEvent]:
    """[OI] 流式 chunk -> 内部流式事件列表"""
    events: List[InternalStreamEvent] = []

    if chunk.get("usage"):  # include_usage 的末端 chunk（choices 为空）
        events.append(InternalStreamEvent(kind="final", usage=usage_to_openai(chunk["usage"])))
        return events

    choices = chunk.get("choices") or []
    if not choices:
        return events
    choice = choices[0]
    delta = choice.get("delta", {}) or {}

    text = delta.get("content")
    if text:
        events.append(InternalStreamEvent(kind="delta", text=text, raw=chunk))

    if delta.get("tool_calls"):
        # 工具调用增量：透传 raw 供客户端（一期仅透传给 openai 入站）
        events.append(InternalStreamEvent(kind="delta", text=None, raw=chunk))

    finish_reason = choice.get("finish_reason")
    if finish_reason:
        events.append(InternalStreamEvent(kind="final", finish_reason=finish_reason,
                                          raw_stop_reason=finish_reason))

    return events


def parse_openai_stream_line(line: str) -> List[InternalStreamEvent]:
    """解析 [OI] SSE 的一行，返回内部事件（无事件返回空列表）"""
    stripped = line.strip()
    if not stripped or not stripped.startswith("data:"):
        return []
    data_str = stripped[5:].strip()
    if data_str == "[DONE]":
        return [InternalStreamEvent(kind="final", finish_reason="stop")]
    try:
        chunk = json.loads(data_str)
    except json.JSONDecodeError:
        return []
    return openai_chunk_to_events(chunk)


class AnthropicStreamAggregator:
    """跨行聚合 Anthropic SSE 事件（event: 行 + data: 行累积 + 空行分发）"""

    def __init__(self):
        self._event_name: Optional[str] = None
        self._data_lines: List[str] = []

    def feed_line(self, line: str) -> List[InternalStreamEvent]:
        """喂入一行，返回完成的事件列表"""
        stripped = line.strip()

        # 空行：事件边界
        if not stripped:
            return self._flush()

        if stripped.startswith("event:"):
            self._event_name = stripped[6:].strip()
            return []
        if stripped.startswith("data:"):
            self._data_lines.append(stripped[5:].strip())
            return []

        return []

    def _flush(self) -> List[InternalStreamEvent]:
        if not self._data_lines:
            self._event_name = None
            return []
        data_str = "\n".join(self._data_lines)
        self._data_lines = []
        event_name = self._event_name
        self._event_name = None

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return []

        return self._to_events(event_name, data)

    def _to_events(self, event_name: Optional[str], data: Dict[str, Any]) -> List[InternalStreamEvent]:
        dtype = data.get("type") or event_name

        if dtype == "message_start":
            message = data.get("message", {}) or {}
            usage = message.get("usage", {}) or {}
            return [InternalStreamEvent(kind="start", usage={"input_tokens": usage.get("input_tokens") or 0}, raw=data)]

        if dtype == "content_block_delta":
            delta = data.get("delta", {}) or {}
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if text:
                    return [InternalStreamEvent(kind="delta", text=text, raw=data)]
            return []

        if dtype == "message_delta":
            delta = data.get("delta", {}) or {}
            stop_reason = delta.get("stop_reason")
            usage = data.get("usage", {}) or {}
            return [InternalStreamEvent(
                kind="final",
                finish_reason=anthropic_finish_to_openai(stop_reason),
                raw_stop_reason=stop_reason,
                usage={"output_tokens": usage.get("output_tokens") or 0},
                raw=data,
            )]

        if dtype == "message_stop":
            return [InternalStreamEvent(kind="final", raw=data)]

        if dtype == "error":
            err = data.get("error", {}) or {}
            return [InternalStreamEvent(kind="error", raw={"error": err})]

        return []
