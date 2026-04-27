# VLM/VLA训练数据评估指标
from typing import Optional, List, Dict, Any
import numpy as np
from .base import BaseTrainingDataMetric, TrainingDataMetricResult


class VLMImageTextAlignmentMetric(BaseTrainingDataMetric):
    """图文对齐度指标"""
    name = "vlm_image_text_alignment"
    display_name = "图文对齐度"
    description = "评估问题和回答与图像内容的对齐程度"
    category = "quality"
    data_types = ["vlm", "vla"]
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
        """评估图文对齐"""
        llm = kwargs.get('llm')
        image_description = kwargs.get('image_description')  # 图像描述信息

        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM或VLM模型进行评估"
            )

        try:
            # 评估问题和回答是否与图像内容相关
            if image_description:
                prompt = f"""请评估以下问题-回答对与给定图像描述的一致性。

图像描述：{image_description}

问题：{question}

回答：{answer}

请评分（满分10分）：
1. 问题是否与图像描述相关
2. 回答是否基于图像描述给出
3. 回答是否会出现幻觉（描述图像中不存在的内容）

输出总分（平均）。"""

                response = await llm.generate(prompt)
                try:
                    score = float(response.strip().split("\n")[0]) / 10.0
                except:
                    score = 0.7
            else:
                # 如果没有图像描述，基于文本质量评分
                score = 0.6
                details = {"message": "缺少图像描述信息"}

            score = max(0.0, min(1.0, score))

            suggestions = []
            if score < 0.6:
                suggestions.append("问题或回答与图像内容可能存在偏差")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"alignment_score": round(score, 4)},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class VLMQuestionRelevanceMetric(BaseTrainingDataMetric):
    """VLM问题相关性指标"""
    name = "vlm_question_relevance"
    display_name = "问题-图像相关性"
    description = "评估问题是否与视觉内容相关"
    category = "quality"
    data_types = ["vlm", "vla"]
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
        """评估问题与图像相关性"""
        llm = kwargs.get('llm')
        image_description = kwargs.get('image_description')

        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型"
            )

        try:
            # 检查问题是否为视觉问题
            visual_keywords = [
                "图片", "图像", "图", "photo", "image", "picture", "visual",
                "看到", "看见", "look", "see", "figure", "diagram"
            ]

            has_visual_kw = any(kw in question.lower() for kw in visual_keywords)

            # 使用LLM进一步评估
            if image_description:
                prompt = f"""给定图像描述：{image_description}

问题：{question}

请判断这个问题是否是基于图像提出的（而不是纯文本问题）。
是视觉相关问题吗？请评分（0-10，10表示完全是视觉问题）。"""

                response = await llm.generate(prompt)
                try:
                    relevance = float(response.strip()) / 10.0
                except:
                    relevance = 0.6 if has_visual_kw else 0.4
            else:
                relevance = 0.7 if has_visual_kw else 0.3

            score = relevance

            suggestions = []
            if score < 0.5:
                suggestions.append("问题可能不是基于视觉内容提出的")
            if not has_visual_kw and score < 0.6:
                suggestions.append("建议使用更明确的视觉相关表述")

            details = {
                "has_visual_keywords": has_visual_kw,
                "relevance_score": round(relevance, 4)
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


class VLMAnswerCompletenessMetric(BaseTrainingDataMetric):
    """VLM回答完整性指标"""
    name = "vlm_answer_completeness"
    display_name = "回答完整性"
    description = "评估VLM回答是否完整描述了图像内容"
    category = "completeness"
    data_types = ["vlm"]
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
        """评估回答完整性"""
        llm = kwargs.get('llm')
        image_description = kwargs.get('image_description')

        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型"
            )

        try:
            # 评估回答的完整性
            length = len(answer)

            if length < 20:
                score = 0.3
                details = {"message": "回答太短，可能不完整"}
            else:
                if image_description:
                    prompt = f"""给定图像描述：{image_description}

问题：{question}
回答：{answer}

请评估这个回答是否：
1. 完整回答了问题（0-5分）
2. 涵盖了图像描述中的主要元素（0-5分）

输出总分。"""

                    response = await llm.generate(prompt)
                    try:
                        score = float(response.strip()) / 10.0
                    except:
                        score = 0.6
                else:
                    score = 0.5
                    details = {"message": "缺少图像描述"}

            suggestions = []
            if length < 50:
                suggestions.append("回答可能缺少细节描述")

            return TrainingDataMetricResult(
                score=max(0.0, min(1.0, score)),
                passed=self.check_threshold(max(0.0, score)),
                details=details if 'details' in dir() else {"length": length},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class VLMHallucinationMetric(BaseTrainingDataMetric):
    """VLM幻觉检测指标"""
    name = "vlm_hallucination"
    display_name = "视觉幻觉检测"
    description = "检测VLM回答中是否包含图像中没有的幻觉内容"
    category = "quality"
    data_types = ["vlm", "vla"]
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
        """检测视觉幻觉"""
        llm = kwargs.get('llm')
        image_description = kwargs.get('image_description')

        if not llm:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型"
            )

        try:
            # 检测回答中是否包含图像中不存在的内容
            if image_description:
                prompt = f"""给定图像描述：{image_description}

问题：{question}
回答：{answer}

请检查回答中是否有以下情况：
1. 描述了图像中不存在的内容
2. 对图像中的对象、颜色、位置等有错误描述
3. 做出了图像无法支持的推断

请评估回答的无幻觉程度（0-10分，10表示完全无幻觉）。"""

                response = await llm.generate(prompt)
                try:
                    score = float(response.strip()) / 10.0
                except:
                    score = 0.7
            else:
                score = 0.6

            suggestions = []
            if score < 0.7:
                suggestions.append("回答可能包含图像中没有的信息（幻觉）")

            return TrainingDataMetricResult(
                score=max(0.0, min(1.0, score)),
                passed=self.check_threshold(score),
                details={"hallucination_free": round(score, 4)},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class VLAActionReasoningMetric(BaseTrainingDataMetric):
    """VLA动作推理性指标"""
    name = "vla_action_reasoning"
    display_name = "动作推理性"
    description = "评估VLA中动作指令与视觉场景的推理关系"
    category = "quality"
    data_types = ["vla"]
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
        """评估动作推理性"""
        llm = kwargs.get('llm')
        image_description = kwargs.get('image_description')
        action = kwargs.get('action')  # VLA动作指令

        if not llm or not action:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要LLM模型和action字段"
            )

        try:
            # 评估动作是否与视觉场景匹配
            if image_description:
                prompt = f"""给定场景描述：{image_description}

动作指令：{action}

请评估：
1. 这个动作在当前场景中是否可执行（0-10）
2. 动作与场景描述是否一致（0-10）

输出平均分数。"""

                response = await llm.generate(prompt)
                try:
                    score = float(response.strip()) / 10.0
                except:
                    score = 0.6
            else:
                score = 0.5

            score = max(0.0, min(1.0, score))

            suggestions = []
            if score < 0.5:
                suggestions.append("动作与场景描述可能不匹配")

            return TrainingDataMetricResult(
                score=score,
                passed=self.check_threshold(score),
                details={"action_validity": round(score, 4)},
                suggestions=suggestions
            )
        except Exception as e:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error=str(e)
            )


class VLAInstructionClarityMetric(BaseTrainingDataMetric):
    """VLA指令清晰度指标"""
    name = "vla_instruction_clarity"
    display_name = "指令清晰度"
    description = "评估VLA动作指令是否清晰明确"
    category = "quality"
    data_types = ["vla"]
    default_threshold = 0.7

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估指令清晰度"""
        action = kwargs.get('action')

        if not action:
            return TrainingDataMetricResult(
                score=0.0,
                passed=False,
                error="需要action字段"
            )

        try:
            # 检查动作指令的清晰度和明确性
            action_words = action.lower().split()

            # 检查是否包含方向词
            direction_words = ["forward", "backward", "left", "right", "up", "down",
                             "turn", "rotate", "move", "go", "前", "后", "左", "右", "上", "下", "转"]
            has_direction = any(w in direction_words for w in action_words)

            # 检查是否包含数量词
            has_quantity = any(char.isdigit() for char in action)

            # 检查长度
            words_count = len(action_words)

            if words_count < 3:
                clarity = 0.3
            elif words_count < 8:
                clarity = 0.6
            else:
                clarity = 0.8

            # 加分项
            if has_direction:
                clarity += 0.1
            if has_quantity:
                clarity += 0.1

            score = min(1.0, clarity)

            details = {
                "word_count": words_count,
                "has_direction": has_direction,
                "has_quantity": has_quantity
            }

            suggestions = []
            if not has_direction:
                suggestions.append("建议动作指令包含明确的方向")
            if not has_quantity:
                suggestions.append("建议动作指令包含具体数值（如距离、角度）")

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


class VLADatasetBalanceMetric(BaseTrainingDataMetric):
    """VLA数据集平衡性指标"""
    name = "vla_dataset_balance"
    display_name = "任务平衡性"
    description = "评估VLA训练数据中不同任务类型的分布平衡性"
    category = "diversity"
    data_types = ["vla"]
    default_threshold = 0.6

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> TrainingDataMetricResult:
        """评估任务平衡性"""
        action = kwargs.get('action')

        if not action:
            return TrainingDataMetricResult(
                score=0.5,
                passed=True,
                details={"message": "缺少action字段"}
            )

        try:
            # 识别动作类型
            action_types = {
                "navigation": ["move", "go", "walk", "to", "靠近", "走到", "移动"],
                "manipulation": ["pick", "grab", "place", "put", "拿", "放", "抓取", "放置"],
                "inspection": ["look", "check", "scan", "see", "看", "检查", "观察"],
                "interaction": ["press", "click", "touch", "按", "点击", "触摸"]
            }

            action_lower = action.lower()
            detected_types = []

            for atype, keywords in action_types.items():
                if any(kw in action_lower for kw in keywords):
                    detected_types.append(atype)

            score = 0.7 if detected_types else 0.4

            details = {
                "detected_action_types": detected_types,
                "type_count": len(detected_types)
            }

            suggestions = []
            if not detected_types:
                suggestions.append("无法识别动作类型，建议标注动作类别")

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


# VLM/VLA训练数据评估指标注册表
VLM_METRICS = {
    "vlm_image_text_alignment": VLMImageTextAlignmentMetric,
    "vlm_question_relevance": VLMQuestionRelevanceMetric,
    "vlm_answer_completeness": VLMAnswerCompletenessMetric,
    "vlm_hallucination": VLMHallucinationMetric,
}

VLA_METRICS = {
    "vla_action_reasoning": VLAActionReasoningMetric,
    "vla_instruction_clarity": VLAInstructionClarityMetric,
    "vla_dataset_balance": VLADatasetBalanceMetric,
    "vlm_image_text_alignment": VLMImageTextAlignmentMetric,  # VLA也适用
    "vlm_hallucination": VLMHallucinationMetric,
}

# 合并VLM和VLA指标
VLM_VLA_METRICS = {**VLM_METRICS, **VLA_METRICS}
