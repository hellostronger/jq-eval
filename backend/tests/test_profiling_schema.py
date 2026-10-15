# 通用 schema 探测与可插拔统计器测试
#
# 覆盖两件事：
#   1. 任意字段命名/形态都能被识别（不靠硬编码列名）
#   2. 统计器按能力分派：适用的启用，不适用的显式跳过而非输出 0 值
import pytest

from app.services.profiling.profilers import (
    profile_conversation,
    run_profilers,
    round_bucket_of,
)
from app.services.profiling.schema import (
    CAP_HAS_CHOICES,
    CAP_HAS_CONVERSATION,
    CAP_HAS_POSITIVE_NEGATIVE,
    CAP_HAS_SCORE,
    CAP_HAS_SUBJECT,
    ROLE_CHOICES,
    ROLE_CONVERSATION,
    ROLE_SCORE,
    ROLE_SUBJECT,
    count_rounds,
    detect_schema,
    extract_conversation,
)


def _chat(roles):
    return {"messages": [{"role": r, "content": "c" * (i + 1)} for i, r in enumerate(roles)]}


# ---------------------------------------------------------------------------
# 语义角色识别：不同字段名都要认出来
# ---------------------------------------------------------------------------
def test_detects_messages_as_conversation():
    s = detect_schema([_chat(["user", "assistant"])])
    assert s.field_for(ROLE_CONVERSATION) == "messages"
    assert CAP_HAS_CONVERSATION in s.capabilities


def test_detects_sharegpt_conversation_field():
    """ShareGPT 用 conversation + from/value，且字段名不是 messages。"""
    records = [{"conversation": [{"from": "human", "value": "q"},
                                 {"from": "gpt", "value": "a"}]}] * 5
    s = detect_schema(records)
    assert s.field_for(ROLE_CONVERSATION) == "conversation"
    assert CAP_HAS_CONVERSATION in s.capabilities


def test_detects_ultrachat_plain_string_history():
    """UltraChat 的 history 是纯字符串数组：形态不是 CONVERSATION，仍须识别为对话。

    回归：曾因 derive_capabilities 严格要求 kind==CONVERSATION 而漏判，
    导致轮次算对了但统计器不被启用。
    """
    records = [{"history": ["q", "a", "q2", "a2", "q3"]}] * 4
    s = detect_schema(records)
    assert s.field_for(ROLE_CONVERSATION) == "history"
    assert CAP_HAS_CONVERSATION in s.capabilities


def test_detects_json_string_dialogue():
    """dialogue 是 JSON 字符串形态，同样须识别为对话。"""
    records = [{"dialogue": '[{"role":"user","content":"q"},{"role":"assistant","content":"a"}]'}] * 3
    s = detect_schema(records)
    assert s.field_for(ROLE_CONVERSATION) == "dialogue"
    assert CAP_HAS_CONVERSATION in s.capabilities


def test_detects_preference_pair_as_conversation():
    records = [{"chosen": [{"role": "user", "content": "q"},
                           {"role": "assistant", "content": "好"}],
                "rejected": [{"role": "assistant", "content": "差"}]}] * 3
    s = detect_schema(records)
    assert CAP_HAS_CONVERSATION in s.capabilities


def test_detects_choices_by_alias_not_hardcoded_column():
    """选择题列名各异：options / candidates / distractors 都应命中。"""
    for col in ("options", "candidates", "distractors"):
        s = detect_schema([{"stem": "q", col: ["A", "B"], "answerKey": "A"}])
        assert s.field_for(ROLE_CHOICES) == col, f"{col} 未识别为选项字段"
        assert CAP_HAS_CHOICES in s.capabilities


def test_detects_score_by_alias():
    """打分字段名不一：score / rating / quality 都应命中。"""
    for col in ("score", "rating", "quality"):
        s = detect_schema([{"text": "t", col: 0.5}] * 3)
        assert s.field_for(ROLE_SCORE) == col, f"{col} 未识别为打分字段"
        assert CAP_HAS_SCORE in s.capabilities


def test_detects_subject_by_alias():
    """学科字段名不一：discipline 不在原始别名表也不该漏。"""
    s = detect_schema([{"question": "q", "discipline": "数学", "answer": "a"}] * 3)
    assert s.field_for(ROLE_SUBJECT) == "discipline"
    assert CAP_HAS_SUBJECT in s.capabilities


def test_detects_positive_negative():
    records = [{"query": "q", "positive_passages": [{"text": "p"}],
                "negative_passages": [{"text": "n"}]}] * 3
    s = detect_schema(records)
    assert CAP_HAS_POSITIVE_NEGATIVE in s.capabilities


def test_schema_empty_records():
    s = detect_schema([])
    assert s.capabilities == set()


# ---------------------------------------------------------------------------
# 轮次：数量级必须正确
# ---------------------------------------------------------------------------
def test_round_count_is_user_messages_not_messages():
    """标准 SFT [{user},{assistant}] 是 1 轮，不是 2 轮。

    回归：曾用 len(messages) 当轮次，把 1 轮问答显示成 2 轮。
    """
    s = detect_schema([_chat(["user", "assistant"])])
    conv = extract_conversation(_chat(["user", "assistant"]), s.field_for(ROLE_CONVERSATION))
    assert len(conv) == 2          # 2 条消息
    assert count_rounds(conv) == 1  # 但只有 1 轮


def test_round_count_multi_turn():
    s = detect_schema([_chat(["user", "assistant", "user", "assistant", "user", "assistant"])])
    conv = extract_conversation(
        _chat(["user", "assistant", "user", "assistant", "user", "assistant"]),
        s.field_for(ROLE_CONVERSATION))
    assert count_rounds(conv) == 3


def test_round_count_plain_string_alternating():
    """纯字符串按 user/assistant 交替，5 条 → 3 轮。"""
    s = detect_schema([{"history": ["q", "a", "q2", "a2", "q3"]}])
    conv = extract_conversation({"history": ["q", "a", "q2", "a2", "q3"]}, s.field_for(ROLE_CONVERSATION))
    assert count_rounds(conv) == 3


def test_round_count_falls_back_when_no_user_role():
    """角色名异常时按交替推断，不应返回 0。"""
    conv = [{"role": "sys", "content": "x"}, {"role": "sys2", "content": "y"}]
    assert count_rounds(conv) == 1


@pytest.mark.parametrize("n,label", [
    (1, "1轮"), (2, "2轮"), (3, "3-4轮"), (4, "3-4轮"),
    (5, "5-8轮"), (8, "5-8轮"), (9, "9-16轮"), (16, "9-16轮"), (30, "16轮+"),
])
def test_round_bucket_boundaries(n, label):
    assert round_bucket_of(n) == label


# ---------------------------------------------------------------------------
# 统计器分派
# ---------------------------------------------------------------------------
def test_profilers_dispatch_by_capability():
    records = [_chat(["user", "assistant"])] * 10
    r = run_profilers(records)
    assert "conversation" in r["applied"]
    conv = r["dimensions"]["conversation"]
    assert conv["stats"]["p50"] == 1
    assert conv["ratios"]["single_turn"] == 1.0


def test_skipped_profilers_explain_reason():
    """不适用的统计器要显式说明跳过原因，不能静默产出 0 值。"""
    r = run_profilers([_chat(["user", "assistant"])] * 3)
    skipped_names = {s["name"] for s in r["skipped"]}
    assert {"choices", "positive_negative", "score", "subject"} <= skipped_names
    for s in r["skipped"]:
        assert s["reason"], "跳过必须有原因"


def test_choice_profiler_on_question_dataset():
    records = [{"question": "q", "options": ["A", "B", "C", "D"], "answerKey": "A"}] * 8
    r = run_profilers(records)
    assert "choices" in r["applied"]
    assert r["dimensions"]["choices"]["choice_count_dist"][0]["count"] == 4
    assert "conversation" not in r["applied"]


def test_subject_profiler_reports_concentration():
    records = [{"question": "q", "subject": "数学", "answer": "a"}] * 7
    records += [{"question": "q", "subject": "物理", "answer": "a"}] * 3
    r = run_profilers(records)
    assert r["dimensions"]["subject"]["distinct"] == 2
    assert r["dimensions"]["subject"]["observations"]


def test_score_profiler_stats():
    records = [{"text": "t", "score": v} for v in [0.1, 0.5, 0.9]]
    r = run_profilers(records)
    s = r["dimensions"]["score"]["stats"]
    assert s["min"] == 0.1 and s["max"] == 0.9


def test_long_tail_rounds_produce_observation():
    """中位 1 轮但 P90 很高时应给出长尾告警——这正是只看均值会漏的情况。"""
    records = [{"history": ["q", "a"]}] * 10
    records += [{"history": ["q", "a"] * 12}] * 2
    conv = run_profilers(records)["dimensions"]["conversation"]
    assert conv["stats"]["p50"] == 1
    assert conv["stats"]["p90"] >= 5
    assert any("长尾" in o or "平均值" in o for o in conv["observations"])


def test_all_single_turn_produces_observation():
    conv = run_profilers([_chat(["user", "assistant"])] * 5)["dimensions"]["conversation"]
    assert any("单轮" in o for o in conv["observations"])


def test_profile_conversation_returns_empty_without_field():
    assert profile_conversation([{"text": "x"}], detect_schema([{"text": "x"}])) == {}