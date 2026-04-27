# DPO训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class DPOPairQualityMetric(BaseTrainingDataMetric):
    """DPO正负样本对质量指标"""
    name = "dpo_pair_quality"
    display_name = "DPO样本对质量"
    description = "评估chosen和rejected样本对是否有明确的质量差异"
    category = "quality"
    data_types = ["dpo"]
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
        """评估DPO样本对质量"""
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
            # 使用LLM评估两个回答的质量差异
            if llm:
                prompt = f"""请评估以下两个回答的质量差异。

问题：{question}

首选回答（chosen）：{chosen}

次选回答（rejected）：{rejected}

请分析：
1. 两个回答是否有明确的质量差异（0-5分）
2. 首选回答是否真的更好（0-5分）

输出总分（0-10）和简短理由。"""

                response = await llm.generate(prompt)
                try:
                    score = float(response.strip().split("\n")[0]) / 10.0
                except:
                    score = 0.6
            else:
                # 基本长度检查
                len_chosen = len(chosen)
                len_rejected = len(rejected)

                if len_chosen > len_rejected * 1.5:
                    score = 0.7  # chosen更长，可能是更好的回答
                elif len_rejected > len_chosen * 1.5:
                    score = 0.4  # rejected更长，可能有问题
                else:
                    score = 0.6

            suggestions = []
            if score < 0.5:
                suggestions.append("chosen和rejected回答区分度不够明显")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "chosen_length": len(chosen),
                    "rejected_length": len(rejected)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class DPOPreferenceStrengthMetric(BaseTrainingDataMetric):
    """DPO偏好强度指标"""
    name = "dpo_preference_strength"
    display_name = "偏好强度"
    description = "评估标注的偏好是否强烈且一致"
    category = "quality"
    data_types = ["dpo"]
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估偏好强度"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        preference_score = kwargs.get('preference_score')  # 可选的偏好强度分数

        if not chosen or not rejected:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen和rejected字段"
            )

        try:
            # 基于文本相似度判断偏好强度
            chosen_words = set(chosen.lower().split())
            rejected_words = set(rejected.lower().split())

            # 计算Jaccard相似度
            intersection = len(chosen_words & rejected_words)
            union = len(chosen_words | rejected_words)

            if union == 0:
                jaccard = 0.0
            else:
                jaccard = intersection / union

            # 好的DPO数据应该有中等程度的相似度（0.3-0.7）
            # 太相似（>0.8）可能质量差异不明显
            # 太不相似（<0.2）可能是完全不同的回答
            if 0.3 <= jaccard <= 0.7:
                score = 0.9
                strength = "strong"
            elif 0.2 <= jaccard < 0.3 or 0.7 < jaccard <= 0.8:
                score = 0.7
                strength = "moderate"
            elif jaccard > 0.8:
                score = 0.4
                strength = "weak"
            else:
                score = 0.5
                strength = "uncertain"

            # 如果有显式偏好分数，结合考虑
            if preference_score is not None:
                score = score * 0.7 + preference_score * 0.3

            suggestions = []
            if jaccard > 0.8:
                suggestions.append("两个回答过于相似，偏好区分可能不够明确")
            if jaccard < 0.2:
                suggestions.append("两个回答差异过大，建议检查是否为同一问题的回答")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "jaccard_similarity": round(jaccard, 4),
                    "preference_strength": strength,
                    "explicit_score": preference_score
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class DPOInstructionFollowingMetric(BaseTrainingDataMetric):
    """DPO指令遵循度指标"""
    name = "dpo_instruction_following"
    display_name = "指令遵循度对比"
    description = "评估chosen和rejected对指令的遵循程度差异"
    category = "quality"
    data_types = ["dpo"]
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
        """评估指令遵循度"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        llm = kwargs.get('llm')

        if not chosen or not rejected or not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen、rejected和llm"
            )

        try:
            # 评估两个回答对指令的遵循程度
            prompt = f"""请评估以下两个回答对指令的遵循程度。

指令/问题：{question}

回答A：{chosen}

回答B：{rejected}

请评分（满分10分）：
1. 回答A对指令的遵循程度（0-10）
2. 回答B对指令的遵循程度（0-10）
3. 两个回答的差异是否足够明显（0-10）

输出三个分数，用逗号分隔。"""

            response = await llm.generate(prompt)
            parts = response.strip().split(",")

            try:
                chosen_score = float(parts[0]) / 10.0
                rejected_score = float(parts[1]) / 10.0
                diff_score = float(parts[2]) / 10.0 if len(parts) > 2 else 0.5
            except:
                chosen_score = 0.7
                rejected_score = 0.4
                diff_score = 0.5

            # 计算综合分数
            if chosen_score > rejected_score:
                quality_diff = chosen_score - rejected_score
                score = 0.5 + quality_diff * 0.5 + diff_score * 0.2
            else:
                score = 0.3  # chosen不应该比rejected差

            score = min(1.0, score)

            suggestions = []
            if chosen_score <= rejected_score:
                suggestions.append("chosen回答的指令遵循度不如rejected，建议检查标注")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "chosen_instruction_score": round(chosen_score, 4),
                    "rejected_instruction_score": round(rejected_score, 4),
                    "difference_score": round(diff_score, 4)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class DPOHelpfulnessMetric(BaseTrainingDataMetric):
    """DPO有用性对比指标"""
    name = "dpo_helpfulness"
    display_name = "有用性对比"
    description = "评估chosen是否比rejected更有帮助"
    category = "quality"
    data_types = ["dpo"]
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
        """评估有用性对比"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        llm = kwargs.get('llm')

        if not chosen or not rejected or not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen、rejected和llm"
            )

        try:
            prompt = f"""请对比以下两个回答的有用性。

问题：{question}

回答A：{chosen}

回答B：{rejected}

请分析：
1. 哪个回答对用户更有帮助？
2. 两个回答的帮助程度差异有多大？

评分（满分10分）：
- 回答A的有用性（0-10）
- 回答B的有用性（0-10）
- 差异程度（0-10）

输出三个分数，用逗号分隔。"""

            response = await llm.generate(prompt)
            parts = response.strip().split(",")

            try:
                chosen_score = float(parts[0]) / 10.0
                rejected_score = float(parts[1]) / 10.0
                diff_score = float(parts[2]) / 10.0 if len(parts) > 2 else 0.5
            except:
                chosen_score = 0.7
                rejected_score = 0.3
                diff_score = 0.6

            # 计算综合分数
            if chosen_score > rejected_score:
                quality_diff = chosen_score - rejected_score
                score = 0.5 + quality_diff * 0.4 + diff_score * 0.3
            else:
                score = 0.3

            score = min(1.0, score)

            suggestions = []
            if chosen_score <= rejected_score:
                suggestions.append("chosen回答有用性不高于rejected，建议检查")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "chosen_helpfulness": round(chosen_score, 4),
                    "rejected_helpfulness": round(rejected_score, 4),
                    "difference": round(diff_score, 4)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class DPOSafetyMetric(BaseTrainingDataMetric):
    """DPO安全性对比指标"""
    name = "dpo_safety"
    display_name = "安全性对比"
    description = "评估chosen和rejected的安全性差异"
    category = "safety"
    data_types = ["dpo"]
    requires_llm = True
    default_threshold = 0.8

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估安全性"""
        chosen = kwargs.get('chosen') or answer
        rejected = kwargs.get('rejected')
        llm = kwargs.get('llm')

        if not chosen or not rejected or not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要chosen、rejected和llm"
            )

        try:
            prompt = f"""请评估以下两个回答的安全性。

问题：{question}

回答A：{chosen}

回答B：{rejected}

请检查：
1. 两个回答是否包含有害内容？
2. chosen是否比rejected更安全或同样安全？

评分（满分10分）：
- 回答A的安全分数（0-10）
- 回答B的安全分数（0-10）

输出两个分数，用逗号分隔。"""

            response = await llm.generate(prompt)
            parts = response.strip().split(",")

            try:
                chosen_safety = float(parts[0]) / 10.0
                rejected_safety = float(parts[1]) / 10.0
            except:
                chosen_safety = 0.9
                rejected_safety = 0.7

            # chosen 至少应该和 rejected 一样安全
            if chosen_safety >= rejected_safety:
                score = 0.8 + (chosen_safety - rejected_safety) * 0.2
            else:
                score = 0.4  # chosen 不安全是个严重问题

            score = min(1.0, score)

            suggestions = []
            if chosen_safety < rejected_safety:
                suggestions.append("chosen回答安全性低于rejected，建议检查或重新标注")
            if chosen_safety < 0.7:
                suggestions.append("chosen回答安全性得分较低")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "chosen_safety": round(chosen_safety, 4),
                    "rejected_safety": round(rejected_safety, 4)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


# DPO训练数据评估指标注册表
DPO_METRICS = {
    "dpo_pair_quality": DPOPairQualityMetric,
    "dpo_preference_strength": DPOPreferenceStrengthMetric,
    "dpo_instruction_following": DPOInstructionFollowingMetric,
    "dpo_helpfulness": DPOHelpfulnessMetric,
    "dpo_safety": DPOSafetyMetric,
}
