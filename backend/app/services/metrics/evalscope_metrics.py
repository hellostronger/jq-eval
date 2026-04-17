# EvalScope评估指标实现
from typing import Optional, List, Dict, Any
import re
from collections import Counter

from .base import BaseMetric, MetricResult


class EvalScopeBLEU(BaseMetric):
    """BLEU评分 - EvalScope实现"""

    name = "bleu"
    display_name = "BLEU评分"
    category = "quality"
    framework = "evalscope"
    eval_stage = "result"

    requires_llm = False
    requires_ground_truth = True

    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        self.max_n = params.get("max_n", 4) if params else 4

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算BLEU分数"""
        try:
            try:
                from evalscope.metrics import bleu

                score = bleu.compute(
                    predictions=[answer],
                    references=[ground_truth],
                    max_n=self.max_n
                )

                return MetricResult(
                    score=score.get('bleu', 0.0),
                    details=score
                )

            except ImportError:
                return self._compute_bleu(answer, ground_truth)

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    def _compute_bleu(self, prediction: str, reference: str) -> MetricResult:
        """简化版BLEU计算"""
        if not prediction or not reference:
            return MetricResult(score=0.0)

        pred_tokens = prediction.lower().split()
        ref_tokens = reference.lower().split()

        if not pred_tokens or not ref_tokens:
            return MetricResult(score=0.0)

        # 计算n-gram匹配
        scores = []
        for n in range(1, min(self.max_n, len(pred_tokens), len(ref_tokens)) + 1):
            pred_ngrams = Counter(self._get_ngrams(pred_tokens, n))
            ref_ngrams = Counter(self._get_ngrams(ref_tokens, n))

            overlap = sum((pred_ngrams & ref_ngrams).values())
            total = sum(pred_ngrams.values())

            if total > 0:
                scores.append(overlap / total)

        if not scores:
            return MetricResult(score=0.0)

        # 简单平均
        bleu_score = sum(scores) / len(scores)
        return MetricResult(score=bleu_score, details={"n_scores": scores})

    def _get_ngrams(self, tokens: List[str], n: int) -> List[tuple]:
        """获取n-grams"""
        return [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]


class EvalScopeROUGE(BaseMetric):
    """ROUGE评分 - EvalScope实现"""

    name = "rouge_l"
    display_name = "ROUGE-L评分"
    category = "quality"
    framework = "evalscope"
    eval_stage = "result"

    requires_llm = False
    requires_ground_truth = True

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算ROUGE-L分数"""
        try:
            try:
                from evalscope.metrics import rouge

                score = rouge.compute(
                    predictions=[answer],
                    references=[ground_truth],
                    rouge_types=['rougeL']
                )

                return MetricResult(
                    score=score.get('rougeL', 0.0),
                    details=score
                )

            except ImportError:
                return self._compute_rouge_l(answer, ground_truth)

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    def _compute_rouge_l(self, prediction: str, reference: str) -> MetricResult:
        """简化版ROUGE-L计算（基于最长公共子序列）"""
        if not prediction or not reference:
            return MetricResult(score=0.0)

        pred_tokens = prediction.lower().split()
        ref_tokens = reference.lower().split()

        if not pred_tokens or not ref_tokens:
            return MetricResult(score=0.0)

        # 计算LCS长度
        lcs_length = self._lcs_length(pred_tokens, ref_tokens)

        # 计算F1
        precision = lcs_length / len(pred_tokens) if pred_tokens else 0
        recall = lcs_length / len(ref_tokens) if ref_tokens else 0

        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0

        return MetricResult(
            score=f1,
            details={
                "precision": precision,
                "recall": recall,
                "lcs_length": lcs_length
            }
        )

    def _lcs_length(self, seq1: List[str], seq2: List[str]) -> int:
        """计算最长公共子序列长度"""
        m, n = len(seq1), len(seq2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i-1] == seq2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])

        return dp[m][n]


class SemanticSimilarity(BaseMetric):
    """语义相似度 - 自研（基于Embedding）"""

    name = "semantic_similarity"
    display_name = "语义相似度"
    category = "quality"
    framework = "custom"
    eval_stage = "result"

    requires_llm = False
    requires_embedding = True
    requires_ground_truth = True

    def __init__(self, embedding_model=None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.embedding_model = embedding_model

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算语义相似度"""
        try:
            if not self.embedding_model:
                # 简化计算（基于字符重叠）
                return self._compute_char_similarity(answer, ground_truth)

            # 获取Embedding
            answer_emb = await self._get_embedding(answer)
            gt_emb = await self._get_embedding(ground_truth)

            if answer_emb is None or gt_emb is None:
                return MetricResult(score=0.0, error="无法获取Embedding")

            # 计算cosine similarity
            similarity = self._cosine_similarity(answer_emb, gt_emb)

            return MetricResult(
                score=float(similarity),
                details={"method": "embedding_cosine"}
            )

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本Embedding"""
        try:
            if hasattr(self.embedding_model, 'embed'):
                return await self.embedding_model.embed(text)
            return None
        except:
            return None

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _compute_char_similarity(self, text1: str, text2: str) -> MetricResult:
        """基于字符的相似度计算"""
        if not text1 or not text2:
            return MetricResult(score=0.0)

        set1 = set(text1)
        set2 = set(text2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        jaccard = intersection / union if union > 0 else 0.0

        return MetricResult(
            score=jaccard,
            details={"method": "jaccard_char"}
        )


# 导出所有EvalScope指标
EVALSCOPE_METRICS = {
    "bleu": EvalScopeBLEU,
    "rouge_l": EvalScopeROUGE,
    "semantic_similarity": SemanticSimilarity,
}