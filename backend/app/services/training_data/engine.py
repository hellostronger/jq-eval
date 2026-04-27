# 训练数据评估引擎
from typing import Dict, List, Any, Optional, Type
import asyncio
from datetime import datetime
import numpy as np

from .base import BaseTrainingDataMetric, TrainingDataMetricResult
from .llm_metrics import LLM_METRICS
from .embedding_metrics import EMBEDDING_METRICS
from .reranker_metrics import RERANKER_METRICS
from .vlm_vla_metrics import VLM_VLA_METRICS
from .dpo_metrics import DPO_METRICS


# 训练数据评估指标注册表
TRAINING_DATA_METRIC_REGISTRY: Dict[str, Type[BaseTrainingDataMetric]] = {}
TRAINING_DATA_METRIC_REGISTRY.update(LLM_METRICS)
TRAINING_DATA_METRIC_REGISTRY.update(EMBEDDING_METRICS)
TRAINING_DATA_METRIC_REGISTRY.update(RERANKER_METRICS)
TRAINING_DATA_METRIC_REGISTRY.update(VLM_VLA_METRICS)
TRAINING_DATA_METRIC_REGISTRY.update(DPO_METRICS)


class TrainingDataMetricEngine:
    """训练数据评估引擎"""

    def __init__(
        self,
        data_type: str,
        llm=None,
        embedding_model=None,
        metric_configs: List[Dict[str, Any]] = None
    ):
        self.data_type = data_type
        self.llm = llm
        self.embedding_model = embedding_model
        self.metric_configs = metric_configs or []

        # 初始化指标实例
        self.metrics: Dict[str, BaseTrainingDataMetric] = {}
        self._init_metrics()

    def _init_metrics(self):
        """初始化指标实例"""
        for config in self.metric_configs:
            metric_name = config.get('metric_name') or config.get('name')
            params = config.get('params', {})

            if metric_name in TRAINING_DATA_METRIC_REGISTRY:
                metric_class = TRAINING_DATA_METRIC_REGISTRY[metric_name]

                # 检查指标是否适用于当前数据类型
                if self.data_type not in metric_class.data_types:
                    continue

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
    ) -> Dict[str, TrainingDataMetricResult]:
        """评估单个训练样本"""
        results = {}

        # 并行计算所有指标
        tasks = []
        for metric_name, metric in self.metrics.items():
            task = metric.compute(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
                llm=self.llm,
                embedding_model=self.embedding_model,
                **kwargs
            )
            tasks.append((metric_name, task))

        # 执行并行计算
        for metric_name, task in tasks:
            try:
                result = await task
                results[metric_name] = result
            except Exception as e:
                results[metric_name] = TrainingDataMetricResult(
                    score=0.0,
                    passed=False,
                    error=f"计算失败: {str(e)}"
                )

        return results

    async def evaluate_batch(
        self,
        records: List[Dict[str, Any]],
        batch_size: int = 10,
        progress_callback=None
    ) -> List[Dict[str, TrainingDataMetricResult]]:
        """批量评估训练数据"""
        results = []
        total = len(records)

        # 分批处理
        for i in range(0, total, batch_size):
            batch = records[i:i + batch_size]

            # 并行处理一批
            batch_tasks = [
                self.evaluate_single(
                    question=r.get('question', ''),
                    answer=r.get('answer', ''),
                    contexts=r.get('contexts'),
                    ground_truth=r.get('ground_truth'),
                    **{k: v for k, v in r.items() if k not in ['question', 'answer', 'contexts', 'ground_truth']}
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

    def compute_summary(
        self,
        results: List[Dict[str, TrainingDataMetricResult]]
    ) -> Dict[str, Any]:
        """计算评估汇总"""
        summary = {
            "total_samples": len(results),
            "metrics_summary": {},
            "passed_samples": 0,
            "failed_samples": 0,
            "pass_rate": 0.0,
            "quality_distribution": {
                "excellent": 0,  # >= 0.9
                "good": 0,       # 0.8-0.9
                "acceptable": 0, # 0.6-0.8
                "poor": 0        # < 0.6
            }
        }

        # 获取所有指标名称
        metric_names = set()
        for r in results:
            metric_names.update(r.keys())

        # 计算每个指标的统计
        for metric_name in metric_names:
            scores = []
            passed_count = 0

            for r in results:
                if metric_name in r and r[metric_name].error is None:
                    score = r[metric_name].score
                    if score is not None:
                        scores.append(score)
                        if r[metric_name].passed:
                            passed_count += 1

            if scores:
                summary["metrics_summary"][metric_name] = {
                    "mean": float(np.mean(scores)),
                    "std": float(np.std(scores)),
                    "min": float(np.min(scores)),
                    "max": float(np.max(scores)),
                    "median": float(np.median(scores)),
                    "p25": float(np.percentile(scores, 25)),
                    "p75": float(np.percentile(scores, 75)),
                    "count": len(scores),
                    "passed": passed_count,
                    "pass_rate": passed_count / len(scores)
                }

        # 计算整体质量分布
        overall_scores = []
        for r in results:
            # 计算每个样本的平均得分
            valid_scores = [v.score for v in r.values() if v.error is None and v.score is not None]
            if valid_scores:
                avg_score = np.mean(valid_scores)
                overall_scores.append(avg_score)

                if avg_score >= 0.9:
                    summary["quality_distribution"]["excellent"] += 1
                elif avg_score >= 0.8:
                    summary["quality_distribution"]["good"] += 1
                elif avg_score >= 0.6:
                    summary["quality_distribution"]["acceptable"] += 1
                else:
                    summary["quality_distribution"]["poor"] += 1

        # 计算总体通过率
        if overall_scores:
            summary["passed_samples"] = sum(1 for s in overall_scores if s >= 0.6)
            summary["failed_samples"] = len(overall_scores) - summary["passed_samples"]
            summary["pass_rate"] = summary["passed_samples"] / len(overall_scores)
            summary["average_score"] = float(np.mean(overall_scores))

        return summary

    def generate_suggestions(
        self,
        results: List[Dict[str, TrainingDataMetricResult]]
    ) -> List[str]:
        """生成改进建议"""
        suggestions = []

        # 分析每个样本的问题
        sample_issues = []
        for r in results:
            issues = []
            for metric_name, result in r.items():
                if not result.passed and result.suggestions:
                    issues.extend(result.suggestions)
            if issues:
                sample_issues.append(issues)

        # 统计常见的问题类型
        from collections import Counter
        all_issues = [issue for issues in sample_issues for issue in issues]
        common_issues = Counter(all_issues).most_common(10)

        for issue, count in common_issues:
            suggestions.append(f"{issue} (影响 {count} 个样本)")

        return suggestions

    @staticmethod
    def get_supported_metrics(data_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取支持的指标列表"""
        metrics = []
        for name, cls in TRAINING_DATA_METRIC_REGISTRY.items():
            if data_type is None or data_type in cls.data_types:
                instance = cls()
                metrics.append(instance.get_info())
        return metrics

    @staticmethod
    def get_metric_by_name(name: str) -> Optional[Type[BaseTrainingDataMetric]]:
        """根据名称获取指标类"""
        return TRAINING_DATA_METRIC_REGISTRY.get(name)


def get_training_data_engine(
    data_type: str,
    llm=None,
    embedding_model=None,
    metric_names: List[str] = None
) -> TrainingDataMetricEngine:
    """创建训练数据评估引擎"""
    metric_configs = []

    if metric_names:
        for name in metric_names:
            if name in TRAINING_DATA_METRIC_REGISTRY:
                metric_class = TRAINING_DATA_METRIC_REGISTRY[name]
                if data_type in metric_class.data_types:
                    metric_configs.append({"metric_name": name})
    else:
        # 自动选择适用于该数据类型的所有指标
        for name, cls in TRAINING_DATA_METRIC_REGISTRY.items():
            if data_type in cls.data_types:
                metric_configs.append({"metric_name": name})

    return TrainingDataMetricEngine(
        data_type=data_type,
        llm=llm,
        embedding_model=embedding_model,
        metric_configs=metric_configs
    )
