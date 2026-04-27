# 大模型训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class LLMResponseQualityMetric(BaseTrainingDataMetric):
    """LLM响应质量指标"""
    name = "llm_response_quality"
    display_name = "响应质量"
    description = "评估回答是否相关、连贯、语法正确"
    category = "quality"
    data_types = ["llm", "dpo"]
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
        """使用LLM评估响应质量"""
        llm = kwargs.get('llm')
        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型进行评估"
            )

        try:
            prompt = f"""请评估以下问答对的质量。

问题：{question}

回答：{answer}

请从以下几个方面评分（满分1.0）：
1. 相关性：回答是否准确回应了问题（0-0.3）
2. 连贯性：回答是否逻辑清晰、表达流畅（0-0.3）
3. 完整性：回答是否完整涵盖了问题的要点（0-0.2）
4. 语法正确性：回答是否有语法错误（0-0.2）

请输出总分（0-1之间的小数）和简短的理由。格式：分数|理由"""

            response = await llm.generate(prompt)
            # 解析响应
            parts = response.split("|")
            score = float(parts[0].strip()) if parts else 0.5
            score = max(0.0, min(1.0, score))

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"reason": parts[1].strip() if len(parts) > 1 else ""},
                suggestions=["建议改进回答质量"] if score < 0.7 else []
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class LLMCoherenceMetric(BaseTrainingDataMetric):
    """LLM逻辑连贯性指标"""
    name = "llm_coherence"
    display_name = "逻辑连贯性"
    description = "评估回答是否具有逻辑性和连贯性"
    category = "quality"
    data_types = ["llm", "dpo"]
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
        """评估逻辑连贯性"""
        llm = kwargs.get('llm')
        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型进行评估"
            )

        try:
            prompt = f"""请评估以下回答的逻辑连贯性。

问题：{question}

回答：{answer}

请从以下维度评分（满分1.0）：
1. 逻辑一致性：回答中的论点是否一致（0-0.3）
2. 结构清晰度：回答是否有清晰的结构（0-0.3）
3. 过渡自然度：段落/句子之间的过渡是否自然（0-0.2）
4. 整体流畅度：整体阅读体验（0-0.2）

请输出总分（0-1之间的小数）。"""

            response = await llm.generate(prompt)
            response_clean = response.strip().split("\n")[0]
            score = float(response_clean) if response_clean.replace(".", "").replace("-", "").isdigit() else 0.5
            score = max(0.0, min(1.0, score))

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                suggestions=["建议改进逻辑结构"] if score < 0.7 else []
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class LLMHelpfulnessMetric(BaseTrainingDataMetric):
    """LLM有用性指标"""
    name = "llm_helpfulness"
    display_name = "有用性"
    description = "评估回答对用户是否有帮助"
    category = "quality"
    data_types = ["llm", "dpo"]
    requires_llm = True
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估有用性"""
        llm = kwargs.get('llm')
        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型进行评估"
            )

        try:
            prompt = f"""请评估以下回答对用户的帮助程度。

问题：{question}

回答：{answer}

请评分（满分1.0）：
- 回答是否真正解决了用户的问题？
- 回答是否足够详细和实用？
- 用户对此回答会有多满意？

请输出分数（0-1之间的小数）和简要说明（用|分隔）。"""

            response = await llm.generate(prompt)
            parts = response.split("|")
            score_text = parts[0].strip()
            score = float(score_text) if score_text.replace(".", "").isdigit() else 0.5
            score = max(0.0, min(1.0, score))

            suggestions = []
            if score < 0.5:
                suggestions.append("回答不够详细，建议补充更多信息")
            if score < 0.6:
                suggestions.append("回答可能没有完全解决用户的问题")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"explanation": parts[1].strip() if len(parts) > 1 else ""},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class LLMResponseLengthMetric(BaseTrainingDataMetric):
    """LLM回复长度指标"""
    name = "llm_response_length"
    display_name = "回复长度"
    description = "评估回复长度是否在合理范围内"
    category = "quality"
    data_types = ["llm", "dpo", "vlm"]
    default_threshold = 0.8
    threshold_type = "range"

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估回复长度"""
        params = self.params or {}
        min_length = params.get('min_length', 10)
        max_length = params.get('max_length', 2000)
        optimal_mid = params.get('optimal_mid', 200)

        length = len(answer)

        if length < min_length:
            score = length / min_length * 0.5
            suggestions = [f"回答太短（{length}字），建议不少于{min_length}字"]
        elif length > max_length:
            score = 0.5 - (length - max_length) / max_length * 0.5
            score = max(0.0, score)
            suggestions = [f"回答太长（{length}字），建议控制在{max_length}字以内"]
        else:
            # 在合理范围内，根据与目标中点的距离计算分数
            distance = abs(length - optimal_mid) / optimal_mid
            score = 1.0 - min(distance * 0.3, 0.3)
            suggestions = []

        return TrainingDataMetricResult(
            score=score,
            passed=self.check_threshold(score, [0.6, 1.0]),
            details={
                "length": length,
                "min_length": min_length,
                "max_length": max_length
            },
            suggestions=suggestions
        )


class LLMHallucinationMetric(BaseTrainingDataMetric):
    """LLM幻觉检测指标"""
    name = "llm_hallucination"
    display_name = "幻觉检测"
    description = "检测回答中是否存在幻觉内容"
    category = "quality"
    data_types = ["llm", "vlm"]
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
        """检测幻觉"""
        llm = kwargs.get('llm')
        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型进行评估"
            )

        try:
            if contexts:
                context_str = "\n\n".join(contexts)
                prompt = f"""请检测以下回答是否包含幻觉（基于上下文不存在的信息）。

上下文信息：
{context_str}

问题：{question}

回答：{answer}

请分析回答中是否有以下情况：
1. 与上下文矛盾的信息
2. 上下文未提及但声称存在的信息
3. 无法验证的夸张陈述

如果存在幻觉，请指出来。输出幻觉程度评分（0-1，1表示无幻觉）|具体说明（用|分隔）。"""
            else:
                prompt = f"""请评估以下回答的可靠性。

问题：{question}

回答：{answer}

请检查回答中是否有以下情况：
1. 可能存在的事实错误
2. 无法验证的断言
3. 过于绝对的表述

请评分（0-1，1表示完全可信）并说明理由。"""

            response = await llm.generate(prompt)
            parts = response.split("|")
            score_text = parts[0].strip()
            score = float(score_text) if score_text.replace(".", "").isdigit() else 0.7
            score = max(0.0, min(1.0, score))

            suggestions = []
            if score < 0.8:
                suggestions.append("回答可能包含幻觉内容，建议核查")
            if score < 0.6:
                suggestions.append("回答中包含难以验证的信息，建议提供更多上下文")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={
                    "analysis": parts[1].strip() if len(parts) > 1 else "",
                    "has_contexts": bool(contexts)
                },
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class LLMInstructionFollowingMetric(BaseTrainingDataMetric):
    """LLM指令遵循度指标"""
    name = "llm_instruction_following"
    display_name = "指令遵循度"
    description = "评估模型是否遵循了问题的指令"
    category = "quality"
    data_types = ["llm", "dpo"]
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
        """评估指令遵循度"""
        llm = kwargs.get('llm')
        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型进行评估"
            )

        try:
            prompt = f"""请评估以下回答是否遵循了问题的指令。

问题：{question}

回答：{answer}

请分析：
1. 问题是否有明确的指令（如"列举"、"解释"、"比较"等）
2. 回答是否按照指令进行了输出

请评分（0-1，1表示完全遵循）并说明遵循/未遵循的具体内容。"""

            response = await llm.generate(prompt)
            parts = response.split("|")
            score_text = parts[0].strip()
            score = float(score_text) if score_text.replace(".", "").isdigit() else 0.8
            score = max(0.0, min(1.0, score))

            suggestions = []
            if score < 0.8:
                suggestions.append("回答未完全遵循指令要求")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"analysis": parts[1].strip() if len(parts) > 1 else ""},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


# LLM训练数据评估指标注册表
LLM_METRICS = {
    "llm_response_quality": LLMResponseQualityMetric,
    "llm_coherence": LLMCoherenceMetric,
    "llm_helpfulness": LLMHelpfulnessMetric,
    "llm_response_length": LLMResponseLengthMetric,
    "llm_hallucination": LLMHallucinationMetric,
    "llm_instruction_following": LLMInstructionFollowingMetric,
}
