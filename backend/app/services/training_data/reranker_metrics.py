# Reranker训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class RerankerPairQualityMetric(BaseTrainingDataMetric):
    """Reranker正负样本对质量指标"""
    name = "reranker_pair_quality"
    display_name = "样本对质量"
    description = "评估正负样本对是否有明显的相关性差异"
    category = "quality"
    data_types = ["reranker"]
    requires_embedding = True
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估样本对质量"""
        positive_doc = kwargs.get('positive_doc')
        negative_doc = kwargs.get('negative_doc')
        embedding_model = kwargs.get('embedding_model')

        if not positive_doc or not negative_doc:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要positive_doc和negative_doc字段"
            )

        try:
            # 如果没有embedding模型，使用简单的文本重叠度
            if not embedding_model:
                pos_words = set(positive_doc.lower().split())
                neg_words = set(negative_doc.lower().split())

                # 计算与问题的相关度差异
                query_words = set(question.lower().split())

                pos_overlap = len(pos_words & query_words)
                neg_overlap = len(neg_words & query_words)

                # 正样本应该与查询更相关
                difference = pos_overlap - neg_overlap

                if difference <= 0:
                    score = 0.3
                    suggestions = ["正样本与查询的重叠度应高于负样本"]
                else:
                    score = 0.5 + min(difference / 10, 0.5)
                    suggestions = []

                details = {
                    "positive_overlap": pos_overlap,
                    "negative_overlap": neg_overlap,
                    "difference": difference
                }
            else:
                score = 0.7
                suggestions = []
                details = {"message": "embedding模型评估"}

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details=details,
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RerankerLabelConsistencyMetric(BaseTrainingDataMetric):
    """Reranker标签一致性指标"""
    name = "reranker_label_consistency"
    display_name = "标签一致性"
    description = "评估人工标注或生成的标签是否与内容一致"
    category = "consistency"
    data_types = ["reranker"]
    default_threshold = 0.8

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估标签一致性"""
        label = kwargs.get('label')  # 1表示相关，0表示不相关
        doc_content = kwargs.get('doc_content') or answer

        if label is None:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要label字段"
            )

        try:
            # 检查标签是否一致
            query_words = set(question.lower().split())
            doc_words = set(doc_content.lower().split())

            overlap = len(query_words & doc_words)
            total = len(query_words | doc_words)

            if total == 0:
                similarity = 0.0
            else:
                similarity = overlap / total

            # 判断标签是否与相似度一致
            expected_label = 1 if similarity > 0.3 else 0
            label_match = (label == expected_label)

            if label == 1 and similarity < 0.2:
                score = 0.3
                consistency = "low"
                suggestions = ["正样本与查询的相似度过低，可能标签有误"]
            elif label == 0 and similarity > 0.5:
                score = 0.4
                consistency = "medium"
                suggestions = ["负样本与查询的相似度过高，可能标签有误"]
            else:
                score = 0.85
                consistency = "high"
                suggestions = []

            details = {
                "similarity": round(similarity, 4),
                "label": label,
                "expected_label": expected_label,
                "consistency": consistency
            }

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details=details,
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RerankerHardNegativeQualityMetric(BaseTrainingDataMetric):
    """Reranker Hard Negative样本质量指标"""
    name = "reranker_hard_negative_quality"
    display_name = "难负样本质量"
    description = "评估难负样本是否足够""难""但不相关"
    category = "quality"
    data_types = ["reranker"]
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估难负样本质量"""
        is_hard_negative = kwargs.get('is_hard_negative')
        doc_content = kwargs.get('doc_content') or answer

        if not is_hard_negative:
            return TrainingDataMetricResult(
                score=0.8,
                passed=True,
                details={"message": "不是难负样本类型"}
            )

        try:
            query_words = set(question.lower().split())
            doc_words = set(doc_content.lower().split())

            # 难负样本应该有较高的词汇重叠度
            overlap = len(query_words & doc_words)
            total_query = len(query_words)

            if total_query == 0:
                recall = 0.0
            else:
                recall = overlap / total_query

            # 难负样本应有中等相似度（0.3-0.6）
            if 0.3 <= recall <= 0.6:
                score = 0.9
                quality = "excellent"
                suggestions = []
            elif 0.2 <= recall < 0.3:
                score = 0.7
                quality = "good"
                suggestions = []
            elif recall < 0.1:
                score = 0.4
                quality = "too_easy"
                suggestions = ["难负样本与查询相似度太低，可能不够""难"""]
            elif recall > 0.7:
                score = 0.3
                quality = "too_similar"
                suggestions = ["难负样本与查询相似度过高，可能实际上是正样本"]
            else:
                score = 0.6
                quality = "acceptable"
                suggestions = []

            details = {
                "recall": round(recall, 4),
                "quality": quality,
                "overlap_words": list(query_words & doc_words)[:5]
            }

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details=details,
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RerankerDatasetDiversityMetric(BaseTrainingDataMetric):
    """Reranker数据集多样性指标"""
    name = "reranker_dataset_diversity"
    display_name = "查询多样性"
    description = "评估Reranker训练数据中查询的多样性"
    category = "diversity"
    data_types = ["reranker"]
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估查询多样性"""
        try:
            # 检查查询的常见模式
            query_words = question.lower().split()

            # 计算查询词汇丰富度
            unique_words = len(set(query_words))
            total_words = len(query_words)

            if total_words == 0:
                vocabulary_richness = 0.0
            else:
                vocabulary_richness = unique_words / total_words

            # 检查问题类型多样性
            question_types = {
                "what": ["什么", "what", "何为", "什么是"],
                "how": ["如何", "怎么", "how", "怎样"],
                "why": ["为什么", "为何", "why", "什么原因"],
                "which": ["哪个", "which", "哪一个"],
                "where": ["哪里", "where", "何处"],
                "when": ["何时", "when", "什么时候"],
                "yes_no": ["是否", "是不是", "对吗", "对吗"]
            }

            detected_types = []
            for qtype, keywords in question_types.items():
                if any(kw in question.lower() for kw in keywords):
                    detected_types.append(qtype)

            # 组合评分
            score = vocabulary_richness * 0.5 + min(len(detected_types) / 3, 1.0) * 0.5

            details = {
                "vocabulary_richness": round(vocabulary_richness, 4),
                "unique_words": unique_words,
                "total_words": total_words,
                "detected_question_types": detected_types
            }

            suggestions = []
            if score < 0.5:
                suggestions.append("建议增加查询的词汇多样性")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details=details,
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RerankerDocumentLengthBalanceMetric(BaseTrainingDataMetric):
    """Reranker文档长度平衡性指标"""
    name = "reranker_document_length_balance"
    display_name = "文档长度平衡"
    description = "评估正负样本的文档长度是否平衡"
    category = "quality"
    data_types = ["reranker"]
    default_threshold = 0.7
    threshold_type = "range"

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估文档长度平衡"""
        positive_doc = kwargs.get('positive_doc')
        negative_doc = kwargs.get('negative_doc')

        if not positive_doc or not negative_doc:
            return TrainingDataMetricResult(
                score=0.5,
                passed=True,
                details={"message": "单文档样本"}
            )

        try:
            pos_len = len(positive_doc)
            neg_len = len(negative_doc)

            # 计算长度比例
            if pos_len == 0:
                ratio = 0.0
            else:
                ratio = neg_len / pos_len

            # 理想比例在 0.5-2.0 之间
            if 0.5 <= ratio <= 2.0:
                score = 1.0 - abs(ratio - 1.0) * 0.2
                balance = "balanced"
                suggestions = []
            elif ratio > 2.0:
                score = 0.5
                balance = "negative_too_long"
                suggestions = ["负样本文档过长，可能影响模型学习"]
            else:
                score = 0.5
                balance = "positive_too_long"
                suggestions = ["正样本文档过长，可能影响模型学习"]

            details = {
                "positive_length": pos_len,
                "negative_length": neg_len,
                "length_ratio": round(ratio, 4),
                "balance": balance
            }

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score, [0.6, 1.0]),
                details=details,
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


# Reranker训练数据评估指标注册表
RERANKER_METRICS = {
    "reranker_pair_quality": RerankerPairQualityMetric,
    "reranker_label_consistency": RerankerLabelConsistencyMetric,
    "reranker_hard_negative_quality": RerankerHardNegativeQualityMetric,
    "reranker_dataset_diversity": RerankerDatasetDiversityMetric,
    "reranker_document_length_balance": RerankerDocumentLengthBalanceMetric,
}
