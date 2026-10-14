# 评测集画像测试
#
# 覆盖三件事：
#   1. 归一化能否吃下各开源评测集的真实字段形态（这里每条都是踩过的坑）
#   2. 画像能否抓到评测集独有的质量风险（答案位置偏置/答案泄漏/选项长度偏置）
#   3. 跨集指纹能否正确区分「重复」与「答案冲突」
import random

import pytest

from app.services.evalset.normalize import (
    ANSWER_MULTI,
    ANSWER_NONE,
    ANSWER_SINGLE,
    FORMAT_GENERATE,
    FORMAT_MC,
    FORMAT_PAIR_SIMILARITY,
    FORMAT_RERANK,
    FORMAT_RETRIEVAL,
    MODEL_EMBEDDING,
    MODEL_LLM,
    MODEL_RERANKER,
    MODEL_RETRIEVAL,
    normalize_record,
    qa_hash,
    question_hash,
)
from app.services.evalset.profiling import build_profile


# ---------------------------------------------------------------------------
# 归一化：各评测集的真实字段形态
# ---------------------------------------------------------------------------
def test_ceval_sibling_columns_are_choices():
    """CEval 把选项铺成同级列 A/B/C/D，漏识别会把选择题误判成判别题并丢掉全部选项。"""
    r = normalize_record({
        "question": "已知函数 f(x)=x^2，则 f'(1) 等于？",
        "A": "1", "B": "2", "C": "0", "D": "-1",
        "answer": "B", "subject": "高中数学",
    }, model_type=MODEL_LLM)
    assert r["task_format"] == FORMAT_MC
    assert r["answer_type"] == ANSWER_SINGLE
    assert r["choices"] == ["1", "2", "0", "-1"]
    assert r["answer_labels"] == ["B"]
    assert r["subject"] == "高中数学"


def test_mmlu_zero_based_index_answer():
    r = normalize_record({
        "question": "Which gas do plants absorb?",
        "choices": ["Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen"],
        "answer": 1,
    }, model_type=MODEL_LLM)
    assert r["task_format"] == FORMAT_MC
    assert r["answer_labels"] == ["B"]


def test_answer_matching_choice_text():
    """答案直接写选项文本（ARC 形态）。"""
    r = normalize_record({
        "question": "What is the capital of France?",
        "choices": ["Lyon", "Paris", "Marseille"],
        "answerKey": "Paris",
    }, model_type=MODEL_LLM)
    assert r["answer_labels"] == ["B"]


def test_multi_choice_list_answer():
    """多选：answer 是标签数组。回归：曾用 {"_": item} 递归导致恒返回空。"""
    r = normalize_record({
        "question": "以下哪些是关系型数据库？",
        "options": ["MySQL", "MongoDB", "PostgreSQL", "Redis"],
        "answer": ["A", "C"],
    }, model_type=MODEL_LLM)
    assert r["answer_type"] == ANSWER_MULTI
    assert r["answer_labels"] == ["A", "C"]


def test_humaneval_is_generation():
    """HumanEval 的 prompt 是函数头，canonical_solution/test 不能当答案。"""
    r = normalize_record({
        "task_id": "HumanEval/0",
        "prompt": 'def add(a, b):\n    """Return the sum."""',
        "canonical_solution": "    return a + b\n",
        "test": "assert add(1, 2) == 3",
        "entry_point": "add",
    }, model_type=MODEL_LLM)
    assert r["task_format"] == FORMAT_GENERATE
    assert "def add" in r["question"]


def test_gsm8k_hash_notation_not_scraped_as_choices():
    """回归：'#### 8' 里的 H/E/A 曾被逐字符扫成选项标签，答案显示为 'H,E,A'。"""
    r = normalize_record({
        "question": "Tom has 3 apples and buys 5 more. How many?",
        "answer": "He has 3+5=8 apples.\n#### 8",
    }, model_type=MODEL_LLM)
    assert r["task_format"] == FORMAT_GENERATE
    assert r["answer_labels"] == []
    assert r["answer_text"] == "8"


def test_choice_question_answer_text_stays_empty():
    """选择题的 answer_text 必须为空，否则把标签 "B" 写进去污染答案长度画像。"""
    r = normalize_record({
        "question": "q", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "B",
    }, model_type=MODEL_LLM)
    # 空串会被 _first 语义归一为 None，两者都表示"选择题不写 answer_text"
    assert not r["answer_text"]


def test_embedding_stsb_pair_similarity():
    r = normalize_record({
        "sentence1": "A man is playing a guitar.",
        "sentence2": "A man is playing an instrument.",
        "score": 4.6,
    }, model_type=MODEL_EMBEDDING)
    assert r["task_format"] == FORMAT_PAIR_SIMILARITY


def test_embedding_miracl_positive_negative_passages():
    r = normalize_record({
        "query": "新能源汽车有哪些电池技术路线？",
        "positive_passages": [{"text": "三元锂和磷酸铁锂是主流路线。"}],
        "negative_passages": [{"text": "今天天气不错。"}],
    }, model_type=MODEL_EMBEDDING)
    assert r["task_format"] == FORMAT_RETRIEVAL
    assert r["pos_count"] == 1
    assert r["neg_count"] == 1


def test_embedding_beir_id_style_positives():
    """BEIR 正例在独立 corpus 里，本表只存 id。回归：曾判成 other。"""
    r = normalize_record({
        "query": "什么是 RAG?",
        "positive_ids": ["doc-1", "doc-3"],
        "negative_ids": ["doc-9"],
    }, model_type=MODEL_EMBEDDING)
    assert r["task_format"] == FORMAT_RETRIEVAL
    assert r["pos_count"] == 2
    assert r["neg_count"] == 1


def test_reranker_passages_with_relevance():
    r = normalize_record({
        "query": "如何申请退款?",
        "passages": [
            {"text": "订单页点击申请售后。", "relevance": 2},
            {"text": "配送范围覆盖全国。", "relevance": 0},
        ],
    }, model_type=MODEL_RERANKER)
    assert r["task_format"] == FORMAT_RERANK
    assert len(r["passages"]) == 2
    assert r["relevance_labels"] == ["2", "0"]


def test_reranker_pos_neg_shape():
    r = normalize_record({
        "query": "什么是向量检索?",
        "positive": ["向量检索用 embedding 做相似度排序。"],
        "negative": ["今天股市大涨。"],
    }, model_type=MODEL_RERANKER)
    assert r["task_format"] == FORMAT_RERANK
    assert r["relevance_labels"] == ["1", "0"]


def test_retrieval_gold_chunk_ids():
    r = normalize_record({
        "question": "公司的年营业额是多少?",
        "answer": "1200 万元。",
        "target_chunk_ids": ["chunk-a1"],
        "contexts": ["年报显示营业额 1200 万元。"],
    }, model_type=MODEL_RETRIEVAL)
    assert r["task_format"] == FORMAT_RETRIEVAL


# ---------------------------------------------------------------------------
# 指纹与污染检测
# ---------------------------------------------------------------------------
def test_question_hash_ignores_formatting_noise():
    """全角/半角、标点、空格差异不应导致同一题被判为两题。"""
    a = question_hash("下列说法正确的是（  ）。")
    b = question_hash("下列说法正确的是。")
    assert a == b


def test_question_hash_differs_for_different_questions():
    assert question_hash("题目甲是什么？") != question_hash("题目乙是什么？")


def test_qa_hash_detects_answer_conflict():
    """同题干不同答案必须 qa_hash 不同，才能报答案冲突。"""
    q = "下列说法正确的是？"
    assert qa_hash(q, "A") != qa_hash(q, "B")


def test_contamination_detection_end_to_end():
    """A 集 20 题，B 集含其中 4 题原题，其中 1 题答案被改动。"""
    a = [{"question": f"题目 {i}", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "A"} for i in range(20)]
    b = a[:4] + [{"question": f"另一题 {i}", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "A"} for i in range(16)]
    b[0] = dict(b[0], answer="B")  # 同题干改成另一个答案

    a_map = {r["question_hash"]: r for r in map(lambda x: normalize_record(x, model_type=MODEL_LLM), a)}
    b_map = {r["question_hash"]: r for r in map(lambda x: normalize_record(x, model_type=MODEL_LLM), b)}

    overlap = set(a_map) & set(b_map)
    conflicts = [h for h in overlap if a_map[h]["qa_hash"] != b_map[h]["qa_hash"]]

    assert len(overlap) == 4
    assert len(conflicts) == 1  # 只有被改动答案的那道


# ---------------------------------------------------------------------------
# 画像：质量风险必须抓得到
# ---------------------------------------------------------------------------
def _biased_mc_rows(n=200, target_ratio=0.55):
    """构造答案位置偏斜的选择题集。"""
    random.seed(7)
    rows = []
    for i in range(n):
        idx = 2 if random.random() < target_ratio else random.randrange(4)
        choices = [f"干扰项内容{i}-{j}" for j in range(4)]
        choices[idx] = f"这是唯一正确的选项，因为{i}"
        rows.append({
            "question": f"第 {i} 道题的题干内容是什么？",
            "A": choices[0], "B": choices[1], "C": choices[2], "D": choices[3],
            "answer": "ABCD"[idx],
        })
    return rows


def test_profile_detects_answer_position_bias():
    """本功能最有诊断价值的维度：答案位置偏斜意味着模型可从位置猜答案。"""
    rows = [normalize_record(r, model_type=MODEL_LLM) for r in _biased_mc_rows()]
    prof = build_profile(rows, model_type=MODEL_LLM)

    ap = prof["answer_profile"]
    assert ap["choice_items"] == 200
    assert ap["answer_position_bias"] > 0.10
    dist = {d["label"]: d["ratio"] for d in ap["answer_position_dist"]}
    assert dist["C"] > 0.45

    issues = " ".join(prof["quality"]["issues"])
    assert "答案位置分布偏斜" in issues


def test_profile_detects_choice_length_bias():
    """正确项恒更长可被长度启发式破解。"""
    rows = []
    for i in range(60):
        rows.append(normalize_record({
            "question": f"题目 {i}",
            "A": "正确" * 20,
            "B": "错" * 3,
            "C": "错" * 3,
            "D": "错" * 3,
            "answer": "A",
        }, model_type=MODEL_LLM))
    prof = build_profile(rows, model_type=MODEL_LLM)
    stats = prof["answer_profile"]["choice_length_stats"]
    assert stats["bias"] > 0.20
    assert "选项长度存在偏置" in " ".join(prof["quality"]["issues"])


def test_profile_detects_answer_leak():
    """答案字面出现在题干里属于必须清理的数据缺陷。"""
    rows = []
    for i in range(50):
        rows.append(normalize_record({
            "question": f"这道题的答案就是 42，选项有哪些？第{i}题",
            "A": "41", "B": "42", "C": "43", "D": "44",
            "answer": "B",
        }, model_type=MODEL_LLM))
    prof = build_profile(rows, model_type=MODEL_LLM)
    assert prof["quality"]["signals"]["answer_leak_rate"] > 0.01
    assert "答案泄漏" in " ".join(prof["quality"]["issues"])


def test_profile_detects_duplicate_choices_and_empty_question():
    rows = [
        normalize_record({"question": "", "A": "x", "B": "y", "C": "z", "D": "w", "answer": "A"}, model_type=MODEL_LLM),
        normalize_record({"question": "重复选项题", "A": "一样", "B": "一样", "C": "别的", "D": "也", "answer": "C"}, model_type=MODEL_LLM),
    ]
    prof = build_profile(rows, model_type=MODEL_LLM)
    signals = prof["quality"]["signals"]
    assert signals["empty_question_rate"] > 0
    assert signals["duplicate_choice_rate"] > 0


def test_profile_model_type_mismatch_is_flagged():
    """把选择题集标成 embedding 集应被归属体检抓出来。"""
    rows = [normalize_record({"question": f"q{i}", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "A"},
                             model_type=MODEL_EMBEDDING) for i in range(10)]
    prof = build_profile(rows, model_type=MODEL_EMBEDDING)
    assert prof["task_profile"]["mismatch"]


def test_profile_embedding_reports_retrieval_shape():
    rows = [normalize_record({
        "query": f"查询 {i}",
        "positive_passages": [{"text": f"正例{i}"}],
        "negative_passages": [{"text": f"负例{i}"}, {"text": f"负例{i}b"}],
    }, model_type=MODEL_EMBEDDING) for i in range(20)]
    prof = build_profile(rows, model_type=MODEL_EMBEDDING)
    shape = prof["capability"]["retrieval_shape"]
    assert shape["avg_positives"] == 1.0
    assert shape["avg_negatives"] == 2.0
    assert shape["items_with_negative"] == 1.0


def test_profile_summary_is_readable_chinese():
    rows = [normalize_record(r, model_type=MODEL_LLM) for r in _biased_mc_rows(n=40)]
    prof = build_profile(rows, model_type=MODEL_LLM)
    summary = prof["summary"]
    assert "这是一个面向" in summary
    assert "选择题" in summary
    assert "正确答案位置分布" in summary


def test_build_profile_rejects_empty():
    with pytest.raises(ValueError):
        build_profile([], model_type=MODEL_LLM)