# 评估指标基类
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class MetricResult(BaseModel):
    """指标计算结果"""
    score: float
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BaseMetric(ABC):
    """评估指标基类"""

    name: str
    display_name: str
    category: str  # retrieval/generation/quality/performance/custom
    framework: str  # ragas/evalscope/custom
    eval_stage: str  # process/result

    # 依赖
    requires_llm: bool = True
    requires_embedding: bool = False
    requires_ground_truth: bool = False
    requires_contexts: bool = False

    # 输出范围
    range_min: float = 0.0
    range_max: float = 1.0
    higher_is_better: bool = True

    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}

    @abstractmethod
    async def compute(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> MetricResult:
        """计算指标得分"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """获取指标信息"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "category": self.category,
            "framework": self.framework,
            "eval_stage": self.eval_stage,
            "requires_llm": self.requires_llm,
            "requires_embedding": self.requires_embedding,
            "requires_ground_truth": self.requires_ground_truth,
            "requires_contexts": self.requires_contexts,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "higher_is_better": self.higher_is_better
        }