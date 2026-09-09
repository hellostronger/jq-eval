# 协议转换器与日志截断回归测试
#
# 覆盖本轮修复：
# 1. openai 入站 tool_choice 指定函数形式必须归一化为内部 {"name": x}，
#    否则出站转换器判 "name" 失配，强制调用静默退化为 auto
# 2. Anthropic 出站必须合并相邻同角色消息（并行 tool_calls 场景）
# 3. mapping_logger.truncate 对嵌套 dict/list 递归生效
import pytest

from app.services.llm.protocol_converter import (
    openai_request_to_internal,
    internal_to_anthropic_call_body,
    internal_to_openai_call_body,
    InternalMessage,
    InternalRequest,
)
from app.services.llm.mapping_logger import truncate, RAW_REQUEST_MAX_LEN


def test_openai_tool_choice_named_function_normalized():
    req = openai_request_to_internal({
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
        "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
    })
    assert req.tool_choice == {"name": "get_weather"}

    # 出站双向都保持强制调用语义
    anthropic_body = internal_to_anthropic_call_body(req, "claude-3")
    assert anthropic_body["tool_choice"] == {"type": "tool", "name": "get_weather"}
    openai_body = internal_to_openai_call_body(req, "gpt-4")
    assert openai_body["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}


@pytest.mark.parametrize("tc", ["auto", "none", "required"])
def test_openai_tool_choice_strings_passthrough(tc):
    req = openai_request_to_internal({
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": tc,
    })
    assert req.tool_choice == tc


def test_anthropic_outbound_merges_parallel_tool_results():
    """并行工具调用的多条 tool 结果必须合并为一条 user（角色交替约束）"""
    req = InternalRequest(
        model="claude-3",
        messages=[
            InternalMessage(role="user", content="weather both cities"),
            InternalMessage(
                role="assistant", content="",
                tool_calls=[
                    {"id": "call_1", "name": "get_weather", "arguments": {"city": "A"}},
                    {"id": "call_2", "name": "get_weather", "arguments": {"city": "B"}},
                ],
            ),
            InternalMessage(role="tool", tool_call_id="call_1", content="sunny"),
            InternalMessage(role="tool", tool_call_id="call_2", content="rainy"),
            InternalMessage(role="user", content="thanks"),
        ],
    )
    body = internal_to_anthropic_call_body(req, "claude-3")
    roles = [m["role"] for m in body["messages"]]
    # 不允许相邻同角色
    assert all(a != b for a, b in zip(roles, roles[1:])), f"相邻同角色未合并: {roles}"
    # tool 结果与紧随的 user 文本合并进同一条 user 的多块 content
    user_msgs = [m for m in body["messages"] if m["role"] == "user"]
    merged = [m for m in user_msgs if any(b.get("type") == "tool_result" for b in m["content"])]
    assert len(merged) == 1
    kinds = [b.get("type") for b in merged[0]["content"]]
    assert kinds.count("tool_result") == 2 and "text" in kinds


def test_truncate_recursive_in_nested_dict():
    big = "x" * (RAW_REQUEST_MAX_LEN + 500)
    payload = {
        "messages": [
            {"role": "user", "content": big},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + big}}]},
        ],
        "model": "gpt-4",
    }
    out = truncate(payload)
    assert len(out["messages"][0]["content"]) < len(big)
    assert out["messages"][0]["content"].endswith("...[truncated]")
    nested_url = out["messages"][1]["content"][0]["image_url"]["url"]
    assert nested_url.endswith("...[truncated]")
    assert len(nested_url) < len(big)
    assert out["model"] == "gpt-4"
