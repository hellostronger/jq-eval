# 奖励模型训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class RewardModelPairQualityMetric(BaseTrainingDataMetric):
    """奖励模型正负样本对质量指标"""
    name = "reward_model_pair_quality"
    display_name = "偏好对质量"
    description = "评估chosen和rejected偏好对的质量差异"
    category = "quality"
    data_types = ["reward_model", "dpo"]
    requires_llm = True
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估偏好对质量"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        llm = kwargs.get('llm')

        if not chosen or not rejected:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen和rejected字段"
            )

        try:
            # 使用LLM评估两个回答的偏好质量
            if llm:
                prompt = f"""请评估以下偏好对的质量，这对数据将用于训练奖励模型。

问题/指令：{question}

被选中的回答（chosen）：{chosen}

被舍弃的回答（rejected）：{rejected}

请分析：
1. 这个偏好标注是否合理（chosen确实优于rejected）
2. 两个回答的质量差异是否明显
3. 是否存在ground truth可以明确区分这两个回答

评分标准（0-10分）：
- 8-10分：差异明显合理，非常适合训练
- 5-7分：有一定差异，可以训练
- 0-4分：差异不明显或标注有问题

请输出分数和简短理由（用|分隔）。"""

                response = await llm.generate(prompt)
                parts = response.strip().split("|")
                try:
                    score = float(parts[0]) / 10.0
                except:
                    score = 0.6
            else:
                # 基本长度和重叠度检查
                score = self._basic_quality_check(chosen, rejected)

            suggestions = []
            if score < 0.5:
                suggestions.append("偏好对质量较低，建议人工审核标注")
            if score < 0.7:
                suggestions.append("建议在标注时使用更明确的质量标准")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "chosen_length": len(chosen),
                    "rejected_length": len(rejected),
                    "reason": parts[1].strip() if len(parts) > 1 else ""
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )

    def _basic_quality_check(self, chosen: str, rejected: str) -> float:
        """基本质量检查"""
        len_chosen = len(chosen)
        len_rejected = len(rejected)

        # 计算文本重叠度
        chosen_words = set(chosen.lower().split())
        rejected_words = set(rejected.lower().split())

        if not chosen_words or not rejected_words:
            return 0.4

        jaccard = len(chosen_words & rejected_words) / len(chosen_words | rejected_words)

        # 理想情况：有一定相似度（0.3-0.6）但有差异
        if 0.3 <= jaccard <= 0.6:
            return 0.8
        elif 0.2 <= jaccard < 0.3 or 0.6 < jaccard <= 0.7:
            return 0.6
        elif jaccard > 0.8:
            return 0.4  # 太相似
        else:
            return 0.5


class RewardModelLabelConfidenceMetric(BaseTrainingDataMetric):
    """奖励模型标注置信度指标"""
    name = "reward_model_label_confidence"
    display_name = "标注置信度"
    description = "评估偏好标注的可信程度，基于多轮标注一致性"
    category = "quality"
    data_types = ["reward_model", "dpo"]
    default_threshold = 0.75

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估标注置信度"""
        # 多轮标注结果
        annotations = kwargs.get('annotations', [])  # 多个标注者的结果
        # 或置信度分数
        confidence = kwargs.get('confidence')

        if confidence is not None:
            # 直接使用提供的置信度
            score = confidence
            confidence_type = "explicit"
        elif annotations and len(annotations) > 1:
            # 基于多轮标注计算一致性
            agreement = self._compute_agreement(annotations)
            score = agreement
            confidence_type = "inter_annotator"
        else:
            # 单标注，默认中等置信度
            score = 0.6
            confidence_type = "single"

        suggestions = []
        if score < 0.6:
            suggestions.append("标注置信度较低，建议增加多轮标注验证")

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score),
            details={
                "confidence_type": confidence_type,
                "annotation_count": len(annotations) if annotations else 1
            },
            suggestions=suggestions
        )

    def _compute_agreement(self, annotations: List[Dict]) -> float:
        """计算标注一致性"""
        if not annotations:
            return 0.5

        # 统计chosen的选择
        chosen_count = sum(1 for a in annotations if a.get('chosen_idx') == 0)
        total = len(annotations)

        # 计算一致性比例
        agreement = max(chosen_count, total - chosen_count) / total
        return agreement


class RewardModelPreferenceDistributionMetric(BaseTrainingDataMetric):
    """奖励模型偏好分布均匀性指标"""
    name = "reward_model_preference_distribution"
    display_name = "偏好分布均匀性"
    description = "评估数据中偏好分布是否平衡，避免偏向某一侧"
    category = "quality"
    data_types = ["reward_model", "dpo"]
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估偏好分布（需要数据集级别的统计）"""
        # 这个指标更适合在数据集级别计算
        # 这里只返回样本级别的占位
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')

        if not chosen or not rejected:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen和rejected字段"
            )

        try:
            # 单样本分布检查：评估两个回答的相对质量
            # 使用算法作为代理：更长不一定是更好
            len_ratio = len(chosen) / max(len(rejected), 1)

            if 0.8 <= len_ratio <= 2.0:
                score = 0.8
                distribution = "balanced"
            elif 0.5 <= len_ratio < 0.8 or 2.0 < len_ratio <= 3.0:
                score = 0.6
                distribution = "slight_imbalance"
            else:
                score = 0.4
                distribution = "imbalanced"

            suggestions = []
            if score < 0.6:
                suggestions.append("回答长度差异过大，建议检查偏好标注是否合理")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "length_ratio": round(len_ratio, 4),
                    "distribution_type": distribution
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RewardModelResponseRelevanceMetric(BaseTrainingDataMetric):
    """奖励模型回答相关性指标"""
    name = "reward_model_response_relevance"
    display_name = "回答相关性"
    description = "评估both chosen和rejected回答与问题的相关性"
    category = "quality"
    data_types = ["reward_model", "dpo"]
    requires_llm = True
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估回答相关性"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        llm = kwargs.get('llm')

        if not chosen or not rejected:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen和rejected字段"
            )

        try:
            if llm:
                prompt = f"""请评估以下两个回答与问题的相关程度。

问题：{question}

回答A：{chosen}

回答B：{rejected}

请评分（满分10分）：
- 回答A与问题的相关性
- 回答B与问题的相关性

输出两个分数，用逗号分隔。"""

                response = await llm.generate(prompt)
                parts = response.strip().split(",")
                try:
                    chosen_rel = float(parts[0]) / 10.0
                    rejected_rel = float(parts[1]) / 10.0

                    # 两个回答都相关才得高分
                    avg_relevance = (chosen_rel + rejected_rel) / 2
                    score = avg_relevance
                except:
                    score = 0.6
            else:
                # 基于关键词匹配
                q_words = set(question.lower().split())
                chosen_words = set(chosen.lower().split())
                rejected_words = set(rejected.lower().split())

                chosen_overlap = len(q_words & chosen_words) / max(len(q_words), 1)
                rejected_overlap = len(q_words & rejected_words) / max(len(q_words), 1)

                score = (chosen_overlap + rejected_overlap) / 2

            suggestions = []
            if score < 0.6:
                suggestions.append("回答与问题相关性较低，建议检查数据质量")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"average_relevance": round(score, 4)},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RewardModelAnnotatedRankingsConsistencyMetric(BaseTrainingDataMetric):
    """奖励模型人工排序一致性指标"""
    name = "reward_model_rankings_consistency"
    display_name = "排序一致性"
    description = "评估如果存在多个人工排序，是否一致"
    category = "consistency"
    data_types = ["reward_model"]
    default_threshold = 0.8

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估排序一致性"""
        rankings = kwargs.get('rankings', [])  # 多个排序结果

        if not rankings or len(rankings) < 2:
            return TrainingDataMetricResult(
                score=0.7,  # 单排序默认中等
                passed=True,
                details={"message": "只有一组排序，无法评估一致性"}
            )

        try:
            # 计算肯德尔tau系数或简单的一致性
            # 简化为检查top选择是否一致
            top_choices = [r[0] if isinstance(r, list) and len(r) > 0 else None for r in rankings]
            top_choices = [t for t in top_choices if t is not None]

            if not top_choices:
                return TrainingDataMetricResult(
                    score=0.5,
                    passed=False,
                    error="无法解析排序数据"
                )

            # 统计最常见的top选择
            from collections import Counter
            top_counter = Counter(top_choices)
            most_common = top_counter.most_common(1)[0][1]

            consistency = most_common / len(top_choices)

            if consistency >= 0.8:
                score = 0.9
            elif consistency >= 0.6:
                score = 0.7
            else:
                score = 0.4

            suggestions = []
            if consistency < 0.6:
                suggestions.append("人工排序一致性较低，建议规范标注标准和流程")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "top_consistency": round(consistency, 4),
                    "ranking_count": len(rankings)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class RewardModelFavoriteDurationMetric(BaseTrainingDataMetric):
    """奖励模型偏好决策时长指标"""
    name = "reward_model_decision_duration"
    display_name = "决策时长"
    description = "评估人工标注时的决策时长，过长可能表示样本模糊"
    category = "quality"
    data_types = ["reward_model"]
    default_threshold = 0.6
    threshold_type = "range"

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估决策时长"""
        duration_ms = kwargs.get('annotation_duration_ms')

        if duration_ms is None:
            return TrainingDataMetricResult(
                score=0.7,
                passed=True,
                details={"message": "无时长数据"}
            )

        # 转换为秒
        duration_sec = duration_ms / 1000.0

        # 理想的标注时长：10秒到5分钟
        if 10 <= duration_sec <= 300:
            score = 1.0 - abs(duration_sec - 60) / 300  # 1分钟最佳
            duration_quality = "optimal"
        elif 5 <= duration_sec < 10:
            score = 0.7
            duration_quality = "slight_fast"
        elif 300 < duration_sec <= 600:
            score = 0.6
            duration_quality = "slow"
        elif duration_sec < 5:
            score = 0.3
            duration_quality = "too_fast"
        else:
            score = 0.4
            duration_quality = "too_slow"

        suggestions = []
        if duration_sec < 5:
            suggestions.append("标注决策过快，可能草率")
        if duration_sec > 300:
            suggestions.append("标注决策过慢，可能样本过于复杂或模糊")

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score, [0.6, 1.0]),
            details={
                "duration_seconds": round(duration_sec, 2),
                "duration_quality": duration_quality
            },
            suggestions=suggestions
        )


# 奖励模型训练数据评估指标注册表
REWARD_MODEL_METRICS = {
    "reward_model_pair_quality": RewardModelPairQualityMetric,
    "reward_model_label_confidence": RewardModelLabelConfidenceMetric,
    "reward_model_preference_distribution": RewardModelPreferenceDistributionMetric,
    "reward_model_response_relevance": RewardModelResponseRelevanceMetric,
    "reward_model_rankings_consistency": RewardModelAnnotatedRankingsConsistencyMetric,
    "reward_model_decision_duration": RewardModelFavoriteDurationMetric,
}
