# 基准评测确定性指标（StratRAG / CRAG 风格，无需 LLM）
# - exact_match: 生成阶段精确匹配（CRAG 常用）
# - token_f1: 生成阶段词元级 F1（StratRAG Generation F1 / SQuAD 风格）
# 与检索阶段指标（mrr_k/hit_rate_k/recall_k）配合，实现检索与生成完全解耦评测
import string
from typing import Optional, List

from .base import BaseMetric, MetricResult

# 中英文标点（归一化时剔除）
_PUNCT_TABLE = str.maketrans("", "", string.punctuation + "，。！？；：、（）【】《》“”‘’—…·")


def _normalize_text(text: str) -> str:
    """小写、去标点、压缩空白"""
    lowered = (text or "").lower()
    stripped = lowered.translate(_PUNCT_TABLE)
    return " ".join(stripped.split())


def _tokenize(text: str) -> List[str]:
    """分词：英文按空白切分；纯中文/无空格文本按字符切分"""
    normalized = _normalize_text(text)
    if not normalized:
        return []
    tokens = normalized.split()
    if len(tokens) <= 1:
        # 中文等无空格语言回退到字符级
        tokens = [ch for ch in normalized if not ch.isspace()]
    return tokens


class ExactMatch(BaseMetric):
    """Exact Match (EM) 精确匹配

    归一化（小写、去标点、压缩空白）后判断答案与标准答案是否完全一致。
    CRAG 等端到端基准常用指标。
    """

    name = "exact_match"
    display_name = "Exact Match 精确匹配"
    category = "generation"
    framework = "custom"
    eval_stage = "result"

    requires_llm = False
    requires_embedding = False
    requires_ground_truth = True

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        if not ground_truth:
            return MetricResult(score=0.0, error="缺少标准答案 (ground_truth)")
        if not answer:
            return MetricResult(score=0.0, details={"normalized_answer": "", "normalized_ground_truth": _normalize_text(ground_truth)})

        norm_answer = _normalize_text(answer)
        norm_truth = _normalize_text(ground_truth)
        score = 1.0 if norm_answer == norm_truth else 0.0

        return MetricResult(
            score=score,
            details={
                "normalized_answer": norm_answer,
                "normalized_ground_truth": norm_truth,
            }
        )


class TokenF1(BaseMetric):
    """Token F1 词元级 F1（Generation F1）

    SQuAD 风格的词元级 F1：计算答案与标准答案的词元重叠的精确率/召回率调和平均。
    中文文本自动回退到字符级。StratRAG 的 Generation F1 即此类指标。
    """

    name = "token_f1"
    display_name = "Token F1 词元级F1"
    category = "generation"
    framework = "custom"
    eval_stage = "result"

    requires_llm = False
    requires_embedding = False
    requires_ground_truth = True

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        if not ground_truth:
            return MetricResult(score=0.0, error="缺少标准答案 (ground_truth)")

        pred_tokens = _tokenize(answer or "")
        truth_tokens = _tokenize(ground_truth)

        if not pred_tokens or not truth_tokens:
            return MetricResult(
                score=0.0,
                details={
                    "pred_token_count": len(pred_tokens),
                    "truth_token_count": len(truth_tokens),
                }
            )

        from collections import Counter
        common = Counter(pred_tokens) & Counter(truth_tokens)
        overlap = sum(common.values())

        if overlap == 0:
            return MetricResult(score=0.0, details={"overlap": 0})

        precision = overlap / len(pred_tokens)
        recall = overlap / len(truth_tokens)
        f1 = 2 * precision * recall / (precision + recall)

        return MetricResult(
            score=f1,
            details={
                "precision": precision,
                "recall": recall,
                "overlap": overlap,
                "pred_token_count": len(pred_tokens),
                "truth_token_count": len(truth_tokens),
            }
        )


# 导出所有基准确定性指标
BENCHMARK_METRICS = {
    "exact_match": ExactMatch,
    "token_f1": TokenF1,
}
