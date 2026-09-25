# Ragas评估指标实现
from typing import Optional, List, Dict, Any
import asyncio
import logging

from .base import BaseMetric, MetricResult
from app.core.exceptions import format_error

logger = logging.getLogger(__name__)


async def _run_sync(func, *args, **kwargs):
    """在异步环境中运行同步函数"""
    return await asyncio.to_thread(func, *args, **kwargs)


async def _ragas_evaluate_single(metric_obj, metric_key: str, data_dict: dict, llm=None, embedding_model=None) -> MetricResult:
    """Ragas 指标公共计算路径：构造单条数据集 -> evaluate -> 取分数

    ragas.evaluate 是同步函数，放到线程中执行；ragas 未安装时由调用方走简化计算。
    """
    from ragas import evaluate
    from ragas.run_config import RunConfig
    from datasets import Dataset

    # 默认 RunConfig.timeout=180s：单条生成含多轮 LLM 调用，思考型模型
    # （一次补全 60s+）必然超时，且超时被 ragas 吞掉后分数变 NaN。
    # 放宽到 600s 与平台 300s 出站超时（含重试）量级匹配。
    run_config = RunConfig(timeout=600, max_retries=2)

    if llm:
        metric_obj.llm = llm
    # answer_relevancy 等指标依赖 embeddings；不注入则静默使用 ragas 全局默认
    # 模型（走环境变量里的另一套配置），分数来源与页面所选模型不一致
    if embedding_model is not None and hasattr(metric_obj, "embeddings"):
        metric_obj.embeddings = embedding_model

    data = Dataset.from_dict(data_dict)
    result = await _run_sync(evaluate, data, metrics=[metric_obj], run_config=run_config)
    raw_score = result[metric_key][0]
    # ragas 吞掉执行异常后给出 NaN（如 LLM 输出带 ```json 围栏解析失败、内部超时）。
    # 返回 NaN 会让该记录在汇总中被静默丢弃；显式报错让上层知道这条没算出来。
    import math
    if raw_score is None or (isinstance(raw_score, float) and math.isnan(raw_score)):
        raise RuntimeError("ragas 指标计算返回 NaN（LLM 输出解析失败或内部超时）")
    return MetricResult(score=float(raw_score))


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
        if not answer:
            return MetricResult(score=0.0, error="答案为空")

        # 如果没有 contexts，无法计算忠实度
        if not contexts or len(contexts) == 0:
            return MetricResult(score=0.0, error="缺少contexts数据")

        try:
            from ragas.metrics import faithfulness

            contexts_list = [str(c) if c else "" for c in contexts]
            return await _ragas_evaluate_single(
                faithfulness, "faithfulness",
                {"question": [question], "answer": [answer], "contexts": [contexts_list]},
                llm=self.llm,
            )
        except ImportError:
            # ragas库未安装，使用简化计算
            return await self._compute_simple(question, answer, contexts)
        except Exception as e:
            return MetricResult(score=0.0, error=format_error(e))

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
        # 如果没有 contexts，无法计算
        if not contexts or len(contexts) == 0:
            return MetricResult(score=0.0, error="缺少contexts数据")

        try:
            from ragas.metrics import context_precision

            contexts_list = [str(c) if c else "" for c in contexts]
            return await _ragas_evaluate_single(
                context_precision, "context_precision",
                {"question": [question], "contexts": [contexts_list]},
                llm=self.llm,
            )
        except ImportError:
            return await self._compute_simple(question, contexts or [])
        except Exception as e:
            return MetricResult(score=0.0, error=format_error(e))

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
        if not ground_truth:
            return MetricResult(score=0.0, error="缺少ground_truth")

        # 如果没有 contexts，无法计算
        if not contexts or len(contexts) == 0:
            return MetricResult(score=0.0, error="缺少contexts数据")

        try:
            from ragas.metrics import context_recall

            contexts_list = [str(c) if c else "" for c in contexts]
            return await _ragas_evaluate_single(
                context_recall, "context_recall",
                {"question": [question], "ground_truth": [ground_truth], "contexts": [contexts_list]},
                llm=self.llm,
            )
        except ImportError:
            return await self._compute_simple(ground_truth, contexts)
        except Exception as e:
            return MetricResult(score=0.0, error=format_error(e))

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


class RagasAnswerRelevance(BaseMetric):
    """答案相关性 - Ragas实现"""

    name = "answer_relevancy"
    display_name = "答案相关性"
    category = "generation"
    framework = "ragas"
    eval_stage = "result"

    requires_llm = True
    requires_embedding = True
    requires_contexts = True  # ragas 0.1.7 需要 contexts
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
        if not answer:
            return MetricResult(score=0.0, error="答案为空")

        # ragas 0.1.7 需要 contexts
        if not contexts or len(contexts) == 0:
            return MetricResult(score=0.0, error="缺少contexts数据")

        try:
            from ragas.metrics import answer_relevancy

            contexts_list = [str(c) if c else "" for c in contexts]
            return await _ragas_evaluate_single(
                answer_relevancy, "answer_relevancy",
                {"question": [question], "answer": [answer], "contexts": [contexts_list]},
                llm=self.llm,
                embedding_model=self.embedding_model,
            )
        except ImportError:
            return await self._compute_simple(question, answer)
        except Exception as e:
            return MetricResult(score=0.0, error=format_error(e))

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


class RagasAnswerCorrectness(BaseMetric):
    """答案正确性 - Ragas实现"""

    name = "answer_correctness"
    display_name = "答案正确性"
    category = "generation"
    framework = "ragas"
    eval_stage = "result"

    requires_llm = True
    requires_embedding = False
    requires_contexts = False
    requires_ground_truth = True

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
        """计算答案正确性"""
        logger.info(f"[answer_correctness] 开始计算 | question={question[:50]}... | answer={answer[:50] if answer else None}... | ground_truth={ground_truth[:50] if ground_truth else None}...")

        if not answer:
            logger.warning("[answer_correctness] 答案为空")
            return MetricResult(score=0.0, error="答案为空")

        if not ground_truth:
            logger.warning("[answer_correctness] 缺少ground_truth")
            return MetricResult(score=0.0, error="缺少ground_truth")

        try:
            from ragas.metrics import answer_correctness

            logger.info(f"[answer_correctness] llm={self.llm}, embedding_model={self.embedding_model}")
            result = await _ragas_evaluate_single(
                answer_correctness, "answer_correctness",
                {"question": [question], "answer": [answer], "ground_truth": [ground_truth]},
                llm=self.llm,
            )
            logger.info(f"[answer_correctness] 计算完成, score={result.score}")
            return result
        except ImportError:
            logger.warning("[answer_correctness] ragas未安装，使用简化计算")
            return await self._compute_simple(answer, ground_truth)
        except Exception as e:
            logger.error(f"[answer_correctness] 计算失败: {e}")
            return MetricResult(score=0.0, error=format_error(e))

    async def _compute_simple(
        self,
        answer: str,
        ground_truth: str
    ) -> MetricResult:
        """简化版正确性计算"""
        if not answer or not ground_truth:
            return MetricResult(score=0.0)

        a_words = set(answer.lower().split())
        gt_words = set(ground_truth.lower().split())
        common_words = {"的", "是", "在", "和", "了", "有", "不", "这", "我", "他"}

        a_words = a_words - common_words
        gt_words = gt_words - common_words

        if not gt_words:
            return MetricResult(score=1.0)

        overlap = len(a_words & gt_words)
        score = overlap / len(gt_words)

        return MetricResult(
            score=min(score, 1.0),
            details={"method": "keyword_overlap", "overlap_ratio": score}
        )


# 导出所有Ragas指标
RAGAS_METRICS = {
    "faithfulness": RagasFaithfulness,
    "context_precision": RagasContextPrecision,
    "context_recall": RagasContextRecall,
    "answer_relevancy": RagasAnswerRelevance,
    "answer_correctness": RagasAnswerCorrectness,
}