# 评估指标基类
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel
import numpy as np


class TrainingDataMetricResult(BaseModel):
    """训练数据指标计算结果"""
    score: float  # 0-1 之间的得分
    passed: bool  # 是否通过检查
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    suggestions: Optional[List[str]] = None


class BaseTrainingDataMetric(ABC):
    """训练数据评估指标基类"""

    name: str
    display_name: str
    description: str = ""

    # 指标分类：quality(质量)/diversity(多样性)/completeness(完整性)/consistency(一致性)/safety(安全性)
    category: str

    # 适用的训练数据类型
    data_types: List[str]  # ["llm", "embedding", "reranker", ...]

    # 依赖
    requires_llm: bool = False
    requires_embedding: bool = False
    requires_ground_truth: bool = False

    # 输出范围
    range_min: float = 0.0
    range_max: float = 1.0
    higher_is_better: bool = True

    # 阈值配置
    default_threshold: float = 0.5
    threshold_type: str = "min"  # min/max/range

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
    ) -> TrainingDataMetricResult:
        """计算指标得分"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """获取指标信息"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "data_types": self.data_types,
            "requires_llm": self.requires_llm,
            "requires_embedding": self.requires_embedding,
            "requires_ground_truth": self.requires_ground_truth,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "higher_is_better": self.higher_is_better,
            "default_threshold": self.default_threshold,
            "threshold_type": self.threshold_type
        }

    def check_threshold(self, score: float, threshold: Optional[float] = None) -> bool:
        """检查得分是否通过阈值"""
        if threshold is None:
            threshold = self.default_threshold

        if self.threshold_type == "min":
            return score >= threshold
        elif self.threshold_type == "max":
            return score <= threshold
        elif self.threshold_type == "range":
            # threshold 为 [min, max] 列表
            min_val, max_val = threshold if isinstance(threshold, (list, tuple)) else (0, threshold)
            return min_val <= score <= max_val
        return True
