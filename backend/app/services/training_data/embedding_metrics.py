# Embedding训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class EmbeddingQualityMetric(BaseTrainingDataMetric):
    """Embedding数据质量指标"""
    name = "embedding_quality"
    display_name = "Embedding质量"
    description = "评估文本-向量对的质量"
    category = "quality"
    data_types = ["embedding"]
    requires_embedding = True
    default_threshold = 0.75

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估Embedding数据质量"""
        embedding_model = kwargs.get('embedding_model')

        if not embedding_model or not contexts:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要Embedding模型和上下文数据"
            )

        try:
            # 计算问题和上下文之间的语义相似度
            similarities = []
            for ctx in contexts:
                if ctx.strip():
                    # 使用简单字符匹配作为相似度估计
                    q_words = set(question.lower().split())
                    c_words = set(ctx.lower().split())
                    if len(q_words) > 0:
                        overlap = len(q_words & c_words) / len(q_words)
                        similarities.append(overlap)

            avg_similarity = np.mean(similarities) if similarities else 0.0

            # 评估文本质量
            text_quality = 1.0
            suggestions = []

            if len(question) < 5:
                text_quality -= 0.3
                suggestions.append("问题太短")

            if not contexts or all(not ctx.strip() for ctx in contexts):
                text_quality -= 0.5
                suggestions.append("上下文为空")

            score = (avg_similarity + text_quality) / 2

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "semantic_similarity": avg_similarity,
                    "text_quality": text_quality
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class EmbeddingDiversityMetric(BaseTrainingDataMetric):
    """Embedding多样性指标"""
    name = "embedding_diversity"
    display_name = "Embedding多样性"
    description = "评估向量分布的多样性（避免模式崩溃）"
    category = "diversity"
    data_types = ["embedding"]
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估多样性"""
        # 计算文本特征的多样性指标
        suggestions = []

        # 词汇多样性
        if contexts and len(contexts) > 0:
            all_text = " ".join(contexts)
            words = all_text.split()
            unique_words = len(set(w.lower() for w in words))
            total_words = len(words)
            lexical_diversity = unique_words / total_words if total_words > 0 else 0

            # 长度多样性
            lengths = [len(ctx) for ctx in contexts]
            length_variance = np.var(lengths) if len(lengths) > 1 else 0
            length_diversity = min(length_variance / 10000, 1.0)  # 归一化

            score = (lexical_diversity + length_diversity) / 2

            if lexical_diversity < 0.3:
                suggestions.append("词汇多样性较低，建议增加文本变化")
            if length_diversity < 0.2:
                suggestions.append("文本长度变化较小")
        else:
            score = 0.0
            suggestions.append("上下文为空")

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={
                "lexical_diversity": locals().get('lexical_diversity', 0),
                "length_diversity": locals().get('length_diversity', 0)
            },
            suggestions=suggestions
        )


class EmbeddingCompletenessMetric(BaseTrainingDataMetric):
    """Embedding数据完整性指标"""
    name = "embedding_completeness"
    display_name = "数据完整性"
    description = "评估文本-向量对是否完整"
    category = "completeness"
    data_types = ["embedding"]
    default_threshold = 0.9

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估数据完整性"""
        completeness_checks = []
        suggestions = []

        # 检查问题是否完整
        if question and len(question.strip()) > 0:
            completeness_checks.append(1.0)
            if len(question) < 10:
                completeness_checks.append(0.5)
                suggestions.append("问题可能不完整，建议补充")
        else:
            completeness_checks.append(0.0)
            suggestions.append("问题为空")

        # 检查上下文
        context_complete = 0
        if contexts:
            non_empty = sum(1 for ctx in contexts if ctx and ctx.strip())
            context_complete = non_empty / len(contexts) if contexts else 0
            completeness_checks.append(context_complete)
            if context_complete < 1.0:
                suggestions.append("部分上下文为空")
        else:
            completeness_checks.append(0.0)
            suggestions.append("缺少上下文数据")

        score = np.mean(completeness_checks)

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={
                "question_complete": completeness_checks[0],
                "context_complete": context_complete if contexts else 0
            },
            suggestions=suggestions
        )


class EmbeddingTextLengthMetric(BaseTrainingDataMetric):
    """Embedding文本长度指标"""
    name = "embedding_text_length"
    display_name = "文本长度"
    description = "评估文本长度是否适合Embedding"
    category = "quality"
    data_types = ["embedding"]
    default_threshold = 0.85

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估文本长度"""
        params = self.params or {}
        min_len = params.get('min_length', 20)
        max_len = params.get('max_length', 512)
        optimal_len = params.get('optimal_length', 100)

        scores = []
        suggestions = []

        # 评估问题长度
        q_len = len(question)
        if min_len <= q_len <= max_len:
            q_score = 1.0 - min(abs(q_len - optimal_len) / optimal_len * 0.2, 0.2)
        else:
            q_score = 0.5 - (abs(q_len - optimal_len) / max_len * 0.5)
            if q_len < min_len:
                suggestions.append(f"问题太短（{q_len}字），建议{min_len}-{max_len}字")
            else:
                suggestions.append(f"问题太长（{q_len}字），建议不超过{max_len}字")
        scores.append(max(0, q_score))

        # 评估上下文长度
        if contexts:
            ctx_scores = []
            for i, ctx in enumerate(contexts):
                c_len = len(ctx)
                if min_len <= c_len <= max_len:
                    ctx_scores.append(1.0)
                elif c_len < min_len:
                    ctx_scores.append(0.5)
                else:
                    ctx_scores.append(max(0.3, 1.0 - (c_len - max_len) / max_len))

            avg_ctx_score = np.mean(ctx_scores) if ctx_scores else 0
            scores.append(avg_ctx_score)

        score = np.mean(scores)

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={
                "question_length": q_len,
                "context_count": len(contexts) if contexts else 0
            },
            suggestions=suggestions
        )


class EmbeddingConsistencyMetric(BaseTrainingDataMetric):
    """Embedding一致性指标"""
    name = "embedding_consistency"
    display_name = "语义一致性"
    description = "评估问题与Context的语义一致性"
    category = "consistency"
    data_types = ["embedding"]
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估语义一致性"""
        if not contexts:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要上下文数据进行一致性评估"
            )

        suggestions = []

        # 关键词匹配
        q_words = set(question.lower().split())
        consistency_scores = []

        for ctx in contexts:
            ctx_words = set(ctx.lower().split())
            if q_words:
                overlap = len(q_words & ctx_words) / len(q_words)
                consistency_scores.append(overlap)

        score = np.mean(consistency_scores) if consistency_scores else 0

        if score < 0.3:
            suggestions.append("问题与上下文语义不一致，建议检查匹配关系")

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={"consistency_score": score},
            suggestions=suggestions
        )


class EmbeddingNoiseDetectionMetric(BaseTrainingDataMetric):
    """Embedding噪声检测指标"""
    name = "embedding_noise_detection"
    display_name = "噪声检测"
    description = "检测文本中的噪声内容"
    category = "quality"
    data_types = ["embedding"]
    default_threshold = 0.8

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """检测噪声"""
        noise_indicators = []
        suggestions = []

        # 检查问题中的噪声
        noise_chars = ['|　', '�', '�', '�', '　', '\x00']
        q_noise = sum(question.count(c) for c in noise_chars)
        if q_noise > 0:
            noise_indicators.append(0.3)
            suggestions.append("问题包含特殊字符或乱码")
        else:
            noise_indicators.append(1.0)

        # 检查上下文中的噪声
        if contexts:
            ctx_noises = []
            for ctx in contexts:
                c_noise = sum(ctx.count(c) for c in noise_chars)
                if c_noise > 0:
                    ctx_noises.append(0.5)
                else:
                    ctx_noises.append(1.0)
            noise_indicators.append(np.mean(ctx_noises))
        else:
            noise_indicators.append(0.0)

        score = np.mean(noise_indicators)

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={"noise_score": score},
            suggestions=suggestions
        )


# Embedding训练数据评估指标注册表
EMBEDDING_METRICS = {
    "embedding_quality": EmbeddingQualityMetric,
    "embedding_diversity": EmbeddingDiversityMetric,
    "embedding_completeness": EmbeddingCompletenessMetric,
    "embedding_text_length": EmbeddingTextLengthMetric,
    "embedding_consistency": EmbeddingConsistencyMetric,
    "embedding_noise_detection": EmbeddingNoiseDetectionMetric,
}
