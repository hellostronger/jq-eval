# 检索评估指标实现
from typing import Optional, List, Dict, Any, Set
from .base import BaseMetric, MetricResult


class MRRAtK(BaseMetric):
    """Mean Reciprocal Rank at K (MRR@K)

    计算检索结果中第一个相关文档的排名倒数，并取平均值。
    如果前 K 个结果中没有相关文档，则贡献 0 分。

    公式: MRR@K = (1/N) * Σ(1/rank_i) where rank_i <= K
    """

    name = "mrr_k"
    display_name = "MRR@K"
    category = "retrieval"
    framework = "custom"
    eval_stage = "process"

    requires_llm = False
    requires_embedding = False
    requires_ground_truth = False  # 使用 target_chunk_ids 替代
    requires_contexts = False  # 使用 retrieval_ids 替代

    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        self.k = params.get("k", 10) if params else 10

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算 MRR@K"""
        # 获取检索结果的 chunk IDs
        retrieval_ids = kwargs.get("retrieval_ids", [])
        # 获取 ground truth 的 chunk IDs
        target_chunk_ids = kwargs.get("target_chunk_ids", [])

        if not retrieval_ids:
            return MetricResult(
                score=0.0,
                error="缺少检索结果ID列表 (retrieval_ids)",
                details={"k": self.k}
            )

        if not target_chunk_ids:
            return MetricResult(
                score=0.0,
                error="缺少目标chunk ID列表 (target_chunk_ids)",
                details={"k": self.k}
            )

        # 将 target_chunk_ids 转换为字符串集合
        target_set: Set[str] = {str(tid) for tid in target_chunk_ids}

        # 在前 K 个检索结果中查找第一个匹配的位置
        # 只考虑前 K 个结果
        top_k_retrieval = retrieval_ids[:self.k]

        reciprocal_rank = 0.0
        first_match_position = None

        for i, rid in enumerate(top_k_retrieval):
            if str(rid) in target_set:
                # 找到第一个匹配，位置是从 1 开始的
                rank = i + 1
                reciprocal_rank = 1.0 / rank
                first_match_position = rank
                break

        return MetricResult(
            score=reciprocal_rank,
            details={
                "k": self.k,
                "first_match_position": first_match_position,
                "retrieval_count": len(retrieval_ids),
                "target_count": len(target_chunk_ids),
                "top_k_retrieval_ids": [str(rid) for rid in top_k_retrieval],
                "target_chunk_ids": [str(tid) for tid in target_chunk_ids]
            }
        )


class HitRateAtK(BaseMetric):
    """Hit Rate at K (命中率@K)

    检查前 K 个检索结果中是否包含任何相关文档。
    如果包含至少一个相关文档，则贡献 1 分，否则贡献 0 分。

    公式: HitRate@K = (1/N) * Σ(hit_i) where hit_i = 1 if any relevant doc in top K
    """

    name = "hit_rate_k"
    display_name = "HitRate@K"
    category = "retrieval"
    framework = "custom"
    eval_stage = "process"

    requires_llm = False
    requires_embedding = False
    requires_ground_truth = False  # 使用 target_chunk_ids 替代
    requires_contexts = False  # 使用 retrieval_ids 替代

    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        self.k = params.get("k", 10) if params else 10

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算 HitRate@K"""
        # 获取检索结果的 chunk IDs
        retrieval_ids = kwargs.get("retrieval_ids", [])
        # 获取 ground truth 的 chunk IDs
        target_chunk_ids = kwargs.get("target_chunk_ids", [])

        if not retrieval_ids:
            return MetricResult(
                score=0.0,
                error="缺少检索结果ID列表 (retrieval_ids)",
                details={"k": self.k}
            )

        if not target_chunk_ids:
            return MetricResult(
                score=0.0,
                error="缺少目标chunk ID列表 (target_chunk_ids)",
                details={"k": self.k}
            )

        # 将 target_chunk_ids 转换为字符串集合
        target_set: Set[str] = {str(tid) for tid in target_chunk_ids}

        # 只考虑前 K 个结果
        top_k_retrieval = retrieval_ids[:self.k]

        # 计算命中数和匹配位置
        hit_count = 0
        match_positions = []

        for i, rid in enumerate(top_k_retrieval):
            if str(rid) in target_set:
                hit_count += 1
                match_positions.append(i + 1)

        # HitRate: 是否至少有一个命中 (1 或 0)
        hit_rate = 1.0 if hit_count > 0 else 0.0

        return MetricResult(
            score=hit_rate,
            details={
                "k": self.k,
                "hit_count": hit_count,
                "match_positions": match_positions,
                "retrieval_count": len(retrieval_ids),
                "target_count": len(target_chunk_ids),
                "top_k_retrieval_ids": [str(rid) for rid in top_k_retrieval],
                "target_chunk_ids": [str(tid) for tid in target_chunk_ids]
            }
        )


class RecallAtK(BaseMetric):
    """Recall at K (召回率@K)

    计算前 K 个检索结果中找到的相关文档数量占所有相关文档总数的比例。

    公式: Recall@K = |relevant docs in top K| / |all relevant docs|
    """

    name = "recall_k"
    display_name = "Recall@K"
    category = "retrieval"
    framework = "custom"
    eval_stage = "process"

    requires_llm = False
    requires_embedding = False
    requires_ground_truth = False  # 使用 target_chunk_ids 替代
    requires_contexts = False  # 使用 retrieval_ids 替代

    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        self.k = params.get("k", 10) if params else 10

    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算 Recall@K"""
        # 获取检索结果的 chunk IDs
        retrieval_ids = kwargs.get("retrieval_ids", [])
        # 获取 ground truth 的 chunk IDs
        target_chunk_ids = kwargs.get("target_chunk_ids", [])

        if not retrieval_ids:
            return MetricResult(
                score=0.0,
                error="缺少检索结果ID列表 (retrieval_ids)",
                details={"k": self.k}
            )

        if not target_chunk_ids:
            return MetricResult(
                score=0.0,
                error="缺少目标chunk ID列表 (target_chunk_ids)",
                details={"k": self.k}
            )

        # 将 target_chunk_ids 转换为字符串集合
        target_set: Set[str] = {str(tid) for tid in target_chunk_ids}
        total_relevant = len(target_set)

        # 只考虑前 K 个结果
        top_k_retrieval = retrieval_ids[:self.k]

        # 计算召回的相关文档数
        retrieved_relevant = 0
        match_positions = []

        for i, rid in enumerate(top_k_retrieval):
            if str(rid) in target_set:
                retrieved_relevant += 1
                match_positions.append(i + 1)

        # Recall: 找到的相关文档 / 总相关文档
        recall = retrieved_relevant / total_relevant if total_relevant > 0 else 0.0

        return MetricResult(
            score=min(recall, 1.0),  # 限制最大为 1.0
            details={
                "k": self.k,
                "retrieved_relevant": retrieved_relevant,
                "total_relevant": total_relevant,
                "match_positions": match_positions,
                "retrieval_count": len(retrieval_ids),
                "top_k_retrieval_ids": [str(rid) for rid in top_k_retrieval],
                "target_chunk_ids": [str(tid) for tid in target_chunk_ids]
            }
        )


# 导出所有检索指标
RETRIEVAL_METRICS = {
    "mrr_k": MRRAtK,
    "hit_rate_k": HitRateAtK,
    "recall_k": RecallAtK,
}