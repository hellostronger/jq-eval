# 评测集画像接入通用层（schema 探测 + 可插拔统计器）的测试
#
# 重点验证：评测集与训练数据画像共用同一套能力探测口径，
# 且评测集特有类型（多轮 agentic / 检索 / 选择题）都能被正确分派。
import pytest

from app.services.evalset.normalize import MODEL_EMBEDDING, MODEL_LLM, normalize_record
from app.services.evalset.profiling import build_profile
from app.services.profiling.schema import CAP_HAS_CHOICES, CAP_HAS_CONVERSATION


def _agentic(turns):
    msgs = []
    for t in range(turns):
        msgs.append({"role": "user", "content": f"q{t}"})
        msgs.append({"role": "assistant", "content": f"a{t}"})
    return {"messages": msgs, "task": "tool_use"}


def test_agentic_eval_set_gets_round_stats():
    """多轮工具调用评测集此前没有任何轮次统计——这正是通用层补上的能力。"""
    records = [_agentic(2)] * 8 + [_agentic(6)] * 4
    prof = build_profile([normalize_record(r, model_type=MODEL_LLM) for r in records],
                         model_type=MODEL_LLM)

    assert "conversation" in prof["capability"]["generic"]["applied"]
    conv = prof["capability"]["generic"]["dimensions"]["conversation"]
    assert conv["stats"]["p50"] == 2
    assert conv["stats"]["max"] == 6
    assert conv["ratios"]["single_turn"] == 0.0
    assert conv["ratios"]["deep_turn"] > 0


def test_retrieval_eval_set_uses_positive_negative_not_conversation():
    records = [{"query": f"q{i}", "positive_passages": [{"text": "p"}],
                "negative_passages": [{"text": "n1"}, {"text": "n2"}]} for i in range(9)]
    prof = build_profile([normalize_record(r, model_type=MODEL_EMBEDDING) for r in records],
                         model_type=MODEL_EMBEDDING)

    assert "positive_negative" in prof["capability"]["generic"]["applied"]
    assert "conversation" not in prof["capability"]["generic"]["applied"]
    pn = prof["capability"]["generic"]["dimensions"]["positive_negative"]
    assert pn["avg_positives"] == 1.0
    assert pn["avg_negatives"] == 2.0


def test_mcq_eval_set_uses_choices():
    records = [{"question": "q", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "B"}] * 10
    prof = build_profile([normalize_record(r, model_type=MODEL_LLM) for r in records],
                         model_type=MODEL_LLM)

    assert "choices" in prof["capability"]["generic"]["applied"]
    assert prof["capability"]["generic"]["dimensions"]["choices"]["choice_count_dist"][0]["count"] == 4


def test_generic_block_shape_matches_training_profile():
    """两套画像的 generic 结构必须一致，前端才能复用同一套渲染。"""
    records = [_agentic(2)] * 4
    prof = build_profile([normalize_record(r, model_type=MODEL_LLM) for r in records],
                         model_type=MODEL_LLM)
    g = prof["capability"]["generic"]
    assert set(g) == {"schema", "capabilities", "applied", "skipped", "dimensions"}
    assert all("name" in s and "reason" in s for s in g["skipped"])


def test_skipped_profilers_have_reasons():
    records = [{"query": "q", "positive_passages": [{"text": "p"}]}] * 3
    prof = build_profile([normalize_record(r, model_type=MODEL_EMBEDDING) for r in records],
                         model_type=MODEL_EMBEDDING)
    assert prof["capability"]["generic"]["skipped"]
    for s in prof["capability"]["generic"]["skipped"]:
        assert s["reason"]


def test_eval_specific_dimensions_preserved():
    """接入通用层不能挤掉评测集特有的诊断维度。"""
    records = []
    for i in range(50):
        idx = 2 if i < 30 else i % 4  # 偏向 C
        ch = ["d"] * 4
        ch[idx] = "正确"
        records.append({"question": f"q{i}", "A": ch[0], "B": ch[1], "C": ch[2],
                        "D": ch[3], "answer": "ABCD"[idx]})
    prof = build_profile([normalize_record(r, model_type=MODEL_LLM) for r in records],
                         model_type=MODEL_LLM)

    assert prof["answer_profile"]["answer_position_bias"] > 0.10
    assert any("答案位置分布偏斜" in i for i in prof["quality"]["issues"])
    assert prof["task_profile"]["primary_format"] == "mc"
    # 通用层同时给出能力与选项分布
    assert "choices" in prof["capability"]["generic"]["applied"]


def test_capability_detection_agrees_with_normalizer():
    """同一份数据，通用层探测到的能力应与归一化层的题型判定一致。"""
    records = [{"question": "q", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "A"}] * 6
    rows = [normalize_record(r, model_type=MODEL_LLM) for r in records]
    prof = build_profile(rows, model_type=MODEL_LLM)
    # 归一化判定为选择题 → 通用层也必须探测到选项能力
    assert rows[0]["task_format"] == "mc"
    assert CAP_HAS_CHOICES in prof["capability"]["generic"]["capabilities"]

    chat_records = [_agentic(2)] * 4
    chat_prof = build_profile(
        [normalize_record(r, model_type=MODEL_LLM) for r in chat_records], model_type=MODEL_LLM)
    assert CAP_HAS_CONVERSATION in chat_prof["capability"]["generic"]["capabilities"]
    assert CAP_HAS_CHOICES not in chat_prof["capability"]["generic"]["capabilities"]
