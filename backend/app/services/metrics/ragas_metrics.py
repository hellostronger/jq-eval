# Ragas评估指标实现
from typing import Optional, List, Dict, Any
import asyncio

from .base import BaseMetric, MetricResult


class RagasFaithfulness(BaseMetric):
    """忠实度 - Ragas实现"""

    name = "faithfulness"
    display_name = "忠实度"
    category = "generation"
    framework = "ragas"
    eval_stage = "result"

    requires_llm = True
    requires_contexts = True
    requires_ground_truth = False

    def __init__(self, llm=None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.llm = llm

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算忠实度"""
        try:
            # 尝试使用ragas库
            try:
                from ragas import evaluate
                from ragas.metrics import faithfulness
                from datasets import Dataset

                if self.llm:
                    faithfulness.llm = self.llm

                data = Dataset.from_dict({
                    "question": [question],
                    "answer": [answer],
                    "contexts": [contexts or []]
                })

                result = evaluate(data, metrics=[faithfulness])
                score = result['faithfulness'][0]

                return MetricResult(score=float(score))

            except ImportError:
                # ragas库未安装，使用简化计算
                return await self._compute_simple(question, answer, contexts or [])

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    async def _compute_simple(
        self,
        question: str,
        answer: str,
        contexts: List[str]
    ) -> MetricResult:
        """简化版忠实度计算（无LLM时使用关键词匹配）"""
        # 简化实现：检查答案中的关键词是否在上下文中出现
        answer_words = set(answer.lower().split())
        context_words = set(" ".join(contexts).lower().split())

        # 移除常见词
        common_words = {"的", "是", "在", "和", "了", "有", "不", "这", "我", "他"}
        answer_words = answer_words - common_words
        context_words = context_words - common_words

        if not answer_words:
            return MetricResult(score=1.0)

        overlap = len(answer_words & context_words)
        score = overlap / len(answer_words) if answer_words else 0.0

        return MetricResult(
            score=min(score, 1.0),
            details={"method": "keyword_overlap", "overlap_ratio": score}
        )


class RagasContextPrecision(BaseMetric):
    """上下文精确度 - Ragas实现"""

    name = "context_precision"
    display_name = "上下文精确度"
    category = "retrieval"
    framework = "ragas"
    eval_stage = "process"

    requires_llm = True
    requires_contexts = True
    requires_ground_truth = False

    def __init__(self, llm=None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.llm = llm

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算上下文精确度"""
        try:
            try:
                from ragas import evaluate
                from ragas.metrics import context_precision
                from datasets import Dataset

                if self.llm:
                    context_precision.llm = self.llm

                data = Dataset.from_dict({
                    "question": [question],
                    "contexts": [contexts or []]
                })

                result = evaluate(data, metrics=[context_precision])
                score = result['context_precision'][0]

                return MetricResult(score=float(score))

            except ImportError:
                return await self._compute_simple(question, contexts or [])

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    async def _compute_simple(
        self,
        question: str,
        contexts: List[str]
    ) -> MetricResult:
        """简化版精确度计算"""
        # 简化实现：基于问题关键词在上下文中的出现
        question_words = set(question.lower().split())
        common_words = {"的", "是", "在", "和", "了", "有", "不", "这", "我", "他", "什么", "怎么", "如何"}
        question_words = question_words - common_words

        if not contexts or not question_words:
            return MetricResult(score=0.5)

        relevant_count = 0
        for ctx in contexts:
            ctx_words = set(ctx.lower().split())
            if question_words & ctx_words:
                relevant_count += 1

        score = relevant_count / len(contexts) if contexts else 0.0
        return MetricResult(
            score=min(score, 1.0),
            details={"relevant_count": relevant_count, "total_contexts": len(contexts)}
        )


class RagasContextRecall(BaseMetric):
    """上下文召回率 - Ragas实现"""

    name = "context_recall"
    display_name = "上下文召回率"
    category = "retrieval"
    framework = "ragas"
    eval_stage = "process"

    requires_llm = True
    requires_contexts = True
    requires_ground_truth = True

    def __init__(self, llm=None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.llm = llm

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算上下文召回率"""
        try:
            try:
                from ragas import evaluate
                from ragas.metrics import context_recall
                from datasets import Dataset

                if self.llm:
                    context_recall.llm = self.llm

                data = Dataset.from_dict({
                    "question": [question],
                    "ground_truth": [ground_truth],
                    "contexts": [contexts or []]
                })

                result = evaluate(data, metrics=[context_recall])
                score = result['context_recall'][0]

                return MetricResult(score=float(score))

            except ImportError:
                return await self._compute_simple(ground_truth, contexts or [])

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    async def _compute_simple(
        self,
        ground_truth: str,
        contexts: List[str]
    ) -> MetricResult:
        """简化版召回率计算"""
        if not ground_truth or not contexts:
            return MetricResult(score=0.0)

        # 简化实现：基于ground_truth关键词在上下文中的覆盖
        gt_words = set(ground_truth.lower().split())
        common_words = {"的", "是", "在", "和", "了", "有", "不", "这", "我", "他"}
        gt_words = gt_words - common_words

        if not gt_words:
            return MetricResult(score=1.0)

        context_words = set(" ".join(contexts).lower().split())
        overlap = len(gt_words & context_words)
        score = overlap / len(gt_words)

        return MetricResult(
            score=min(score, 1.0),
            details={"coverage_ratio": score}
        )


class RagasAnswerRelevancy(BaseMetric):
    """答案相关性 - Ragas实现"""

    name = "answer_relevancy"
    display_name = "答案相关性"
    category = "generation"
    framework = "ragas"
    eval_stage = "result"

    requires_llm = True
    requires_embedding = True
    requires_contexts = False
    requires_ground_truth = False

    def __init__(self, llm=None, embedding_model=None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.llm = llm
        self.embedding_model = embedding_model

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算答案相关性"""
        try:
            try:
                from ragas import evaluate
                from ragas.metrics import answer_relevancy
                from datasets import Dataset

                if self.llm:
                    answer_relevancy.llm = self.llm

                data = Dataset.from_dict({
                    "question": [question],
                    "answer": [answer]
                })

                result = evaluate(data, metrics=[answer_relevancy])
                score = result['answer_relevancy'][0]

                return MetricResult(score=float(score))

            except ImportError:
                return await self._compute_simple(question, answer)

        except Exception as e:
            return MetricResult(score=0.0, error=str(e))

    async def _compute_simple(
        self,
        question: str,
        answer: str
    ) -> MetricResult:
        """简化版相关性计算"""
        # 基于关键词重叠
        q_words = set(question.lower().split())
        a_words = set(answer.lower().split())
        common_words = {"的", "是", "在", "和", "了", "有", "不", "这", "我", "他"}

        q_words = q_words - common_words
        a_words = a_words - common_words

        if not q_words:
            return MetricResult(score=0.5)

        overlap = len(q_words & a_words)
        score = overlap / len(q_words)

        return MetricResult(
            score=min(score, 1.0),
            details={"keyword_overlap": score}
        )


# 导出所有Ragas指标
RAGAS_METRICS = {
    "faithfulness": RagasFaithfulness,
    "context_precision": RagasContextPrecision,
    "context_recall": RagasContextRecall,
    "answer_relevancy": RagasAnswerRelevancy,
}