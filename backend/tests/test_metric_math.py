# 自研指标算法正确性测试
#
# 评估平台的"尺子"本身必须先被校准：这些测试不 mock、不依赖 LLM，
# 用人工可推算的样例锁定检索指标（MRR/HitRate/Recall@K）与简化 BLEU/ROUGE-L
# 的数学行为——包括截断、去重、分母口径这些最容易悄悄写错的细节。
import pytest

from app.services.metrics.retrieval_metrics import HitRateAtK, MRRAtK, RecallAtK
from app.services.metrics.evalscope_metrics import EvalScopeBLEU, EvalScopeROUGE


def _kw(retrieval, target):
    return {"question": "q", "answer": "a", "retrieval_ids": retrieval, "target_chunk_ids": target}


# ---------- MRR@K ----------

@pytest.mark.asyncio
async def test_mrr_first_position_full_score():
    r = await MRRAtK({"k": 3}).compute(**_kw(["d1", "d2", "d3"], ["d1"]))
    assert r.score == 1.0
    assert r.details["first_match_position"] == 1


@pytest.mark.asyncio
async def test_mrr_second_position_half():
    r = await MRRAtK({"k": 3}).compute(**_kw(["d1", "d2", "d3"], ["d2"]))
    assert abs(r.score - 0.5) < 1e-9


@pytest.mark.asyncio
async def test_mrr_k_truncation_outside_k_scores_zero():
    """第 4 位命中但 k=3 → 截断后无命中，0 分"""
    r = await MRRAtK({"k": 3}).compute(**_kw(["a", "b", "c", "target"], ["target"]))
    assert r.score == 0.0


@pytest.mark.asyncio
async def test_mrr_only_first_match_counts():
    """多个相关文档取第一个排名"""
    r = await MRRAtK({"k": 5}).compute(**_kw(["x", "t1", "t2", "y", "z"], ["t1", "t2"]))
    assert abs(r.score - 0.5) < 1e-9


# ---------- HitRate@K ----------

@pytest.mark.asyncio
async def test_hit_rate_binary_and_truncation():
    hit = await HitRateAtK({"k": 3}).compute(**_kw(["a", "t", "c", "d"], ["t"]))
    miss = await HitRateAtK({"k": 3}).compute(**_kw(["a", "b", "c", "t"], ["t"]))
    assert hit.score == 1.0
    assert miss.score == 0.0  # t 在第 4 位，k=3 截断


# ---------- Recall@K ----------

@pytest.mark.asyncio
async def test_recall_fraction_and_dedup():
    """3 个目标只找回 1 个 → 1/3；重复检索不重复计数"""
    r = await RecallAtK({"k": 5}).compute(**_kw(["t1", "n1", "t1", "n2"], ["t1", "t2", "t3"]))
    assert abs(r.score - 1 / 3) < 1e-9


@pytest.mark.asyncio
async def test_recall_full_and_over_k():
    r = await RecallAtK({"k": 2}).compute(**_kw(["t1", "t2"], ["t1", "t2"]))
    assert r.score == 1.0
    # k 截断丢一部分
    r2 = await RecallAtK({"k": 1}).compute(**_kw(["t1", "t2"], ["t1", "t2"]))
    assert abs(r2.score - 0.5) < 1e-9


@pytest.mark.asyncio
async def test_empty_inputs_error_not_crash():
    for cls in (MRRAtK, HitRateAtK, RecallAtK):
        r = await cls({"k": 3}).compute(**_kw([], ["t"]))
        assert r.error and r.score == 0.0
        r = await cls({"k": 3}).compute(**_kw(["t"], []))
        assert r.error and r.score == 0.0


# ---------- 简化 BLEU（fallback 路径，不依赖 nltk/evalscope）----------

@pytest.mark.asyncio
async def test_bleu_identical_sentences_full():
    r = await EvalScopeBLEU().compute(
        question="q", answer="the cat sat on the mat",
        ground_truth="the cat sat on the mat")
    # 完全一致：unigram..4gram 全部命中
    assert r.score > 0.99


@pytest.mark.asyncio
async def test_bleu_no_overlap_zero():
    r = await EvalScopeBLEU().compute(
        question="q", answer="alpha beta gamma", ground_truth="one two three")
    assert r.score == 0.0


@pytest.mark.asyncio
async def test_bleu_partial_clip_counting():
    """unigram 精度：pred 3 词中 2 个在 ref（重复词按 clip 计）"""
    r = await EvalScopeBLEU().compute(
        question="q", answer="a b b", ground_truth="a b c")
    # n=1: clip(a)=1, clip(b)=2(出现2次≤ref1次? ref b 出现1次 → clip=1) ...
    # 精确校验细节交给 details
    assert 0.0 < r.score < 1.0
    n1 = r.details["n_scores"][0]
    assert abs(n1 - 2 / 3) < 1e-9  # clip: a=1, b=min(2,1)=1 → 2/3


@pytest.mark.asyncio
async def test_bleu_empty_inputs_zero():
    r = await EvalScopeBLEU().compute(question="q", answer="", ground_truth="x")
    assert r.score == 0.0


# ---------- ROUGE-L（LCS F1，fallback 路径）----------

@pytest.mark.asyncio
async def test_rouge_l_identical_full():
    r = await EvalScopeROUGE().compute(
        question="q", answer="a b c d", ground_truth="a b c d")
    assert r.score == 1.0


@pytest.mark.asyncio
async def test_rouge_l_subsequence_f1():
    """pred ⊂ ref 时 P=1、R<1，F1 精确可算：LCS=2, pred=2, ref=4 → P=1, R=0.5, F=2/3"""
    r = await EvalScopeROUGE().compute(
        question="q", answer="x a y b z", ground_truth="a w b")
    # pred: x a y b z (5), ref: a w b (3), LCS(a,b)=2
    p = 2 / 5
    rec = 2 / 3
    expected = 2 * p * rec / (p + rec)
    assert abs(r.score - expected) < 1e-9
    assert abs(r.details["precision"] - p) < 1e-9


@pytest.mark.asyncio
async def test_rouge_l_no_common_zero():
    r = await EvalScopeROUGE().compute(
        question="q", answer="a b", ground_truth="c d")
    assert r.score == 0.0
