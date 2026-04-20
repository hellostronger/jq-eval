# 评估引擎
from typing import Dict, List, Any, Optional, Type
import asyncio
from datetime import datetime

from .base import BaseMetric, MetricResult
from .ragas_metrics import RAGAS_METRICS
from .evalscope_metrics import EVALSCOPE_METRICS


# 指标注册表
METRIC_REGISTRY: Dict[str, Type[BaseMetric]] = {}
METRIC_REGISTRY.update(RAGAS_METRICS)
METRIC_REGISTRY.update(EVALSCOPE_METRICS)


class MetricEngine:
    """统一指标计算引擎"""

    def __init__(
        self,
        llm=None,
        embedding_model=None,
        metric_configs: List[Dict[str, Any]] = None
    ):
        self.llm = llm
        self.embedding_model = embedding_model
        self.metric_configs = metric_configs or []

        # 初始化指标实例
        self.metrics: Dict[str, BaseMetric] = {}
        self._init_metrics()

    def _init_metrics(self):
        """初始化指标实例"""
        for config in self.metric_configs:
            metric_name = config.get('metric_name') or config.get('name')
            params = config.get('params', {})

            if metric_name in METRIC_REGISTRY:
                metric_class = METRIC_REGISTRY[metric_name]

                # 根据指标依赖注入模型
                kwargs = {'params': params}
                if metric_class.requires_llm:
                    kwargs['llm'] = self.llm
                if metric_class.requires_embedding:
                    kwargs['embedding_model'] = self.embedding_model

                self.metrics[metric_name] = metric_class(**kwargs)

    async def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: Optional[List[str]] = None,
        ground_truth: Optional[str] = None,
        **kwargs
    ) -> Dict[str, MetricResult]:
        """评估单个QA记录"""
        results = {}

        # 并行计算所有指标
        tasks = []
        for metric_name, metric in self.metrics.items():
            task = metric.compute(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
                **kwargs
            )
            tasks.append((metric_name, task))

        # 执行并行计算
        for metric_name, task in tasks:
            try:
                result = await task
                results[metric_name] = result
            except Exception as e:
                results[metric_name] = MetricResult(
                    score=0.0,
                    error=f"计算失败: {str(e)}"
                )

        return results

    async def evaluate_batch(
        self,
        qa_records: List[Dict[str, Any]],
        batch_size: int = 10,
        progress_callback=None
    ) -> List[Dict[str, MetricResult]]:
        """批量评估"""
        results = []
        total = len(qa_records)

        # 分批处理
        for i in range(0, total, batch_size):
            batch = qa_records[i:i + batch_size]

            # 并行处理一批
            batch_tasks = [
                self.evaluate_single(
                    question=r['question'],
                    answer=r.get('answer'),
                    contexts=r.get('contexts'),
                    ground_truth=r.get('ground_truth')
                )
                for r in batch
            ]

            batch_results = await asyncio.gather(*batch_tasks)
            results.extend(batch_results)

            # 进度回调
            if progress_callback:
                progress = min((i + batch_size) / total * 100, 100)
                progress_callback(progress, i + len(batch), total)

        return results

    def get_metric_info(self) -> List[Dict[str, Any]]:
        """获取所有可用指标信息"""
        info = []
        for name, cls in METRIC_REGISTRY.items():
            info.append({
                "name": name,
                "display_name": cls.display_name,
                "category": cls.category,
                "framework": cls.framework,
                "eval_stage": cls.eval_stage,
                "requires_llm": cls.requires_llm,
                "requires_embedding": cls.requires_embedding,
                "requires_ground_truth": cls.requires_ground_truth,
                "requires_contexts": cls.requires_contexts,
            })
        return info

    @staticmethod
    def get_supported_metrics() -> List[str]:
        """获取支持的指标列表"""
        return list(METRIC_REGISTRY.keys())

    @staticmethod
    def compute_summary(results: List[Dict[str, MetricResult]]) -> Dict[str, Any]:
        """计算评估汇总"""
        import numpy as np

        summary = {
            "total_records": len(results),
            "metrics_summary": {}
        }

        # 获取所有指标名称
        metric_names = set()
        for r in results:
            metric_names.update(r.keys())

        for metric in metric_names:
            scores = [
                r[metric].score
                for r in results
                if metric in r and r[metric].error is None
            ]

            if scores:
                summary["metrics_summary"][metric] = {
                    "mean": float(np.mean(scores)),
                    "std": float(np.std(scores)),
                    "min": float(np.min(scores)),
                    "max": float(np.max(scores)),
                    "median": float(np.median(scores)),
                    "p25": float(np.percentile(scores, 25)),
                    "p75": float(np.percentile(scores, 75)),
                    "count": len(scores)
                }

        return summary


def get_metric_engine(
    llm=None,
    embedding_model=None,
    metric_names: List[str] = None
) -> MetricEngine:
    """创建评估引擎"""
    metric_configs = []
    if metric_names:
        for name in metric_names:
            metric_configs.append({"metric_name": name})

    return MetricEngine(
        llm=llm,
        embedding_model=embedding_model,
        metric_configs=metric_configs
    )