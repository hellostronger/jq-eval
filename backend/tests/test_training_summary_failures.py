# 训练数据评估汇总同样必须暴露失败，而不是静默剔除
#
# 与 RAG 评估侧 (test_metrics_summary_failures.py) 是同一个问题：
# 带 error 的记录被剔除后不留痕迹，指标全失败时直接从报告里消失，
# 和"用户没配这个指标"长得一模一样。
import pytest

from app.services.training_data.base import TrainingDataMetricResult
from app.services.training_data.engine import TrainingDataMetricEngine


def _r(score, error=None, passed=False):
    return TrainingDataMetricResult(score=score, error=error, passed=passed)


def _engine():
    return TrainingDataMetricEngine(
        data_type="llm",
        metric_configs=[{"metric_name": "accuracy", "weight": 1.0}],
        pass_threshold=0.7,
    )


def test_failed_metrics_excluded_from_mean_but_counted():
    e = _engine()
    results = [
        {"accuracy": _r(0.9, passed=True)},
        {"accuracy": _r(0.0, error="模型超时")},
        {"accuracy": _r(0.5)},
    ]
    s = e.compute_summary(results)
    m = s["metrics_summary"]["accuracy"]
    assert m["count"] == 2, "只有成功的两条参与统计"
    assert m["failed_count"] == 1
    assert abs(m["mean"] - 0.7) < 1e-9
    assert s["metric_errors"]["accuracy"] == ["模型超时"]


def test_metric_failing_everywhere_is_reported():
    """全失败的指标必须显式报错，且样本数要能被解释"""
    e = _engine()
    results = [{"accuracy": _r(0.0, error="超时")} for _ in range(3)]
    s = e.compute_summary(results)
    assert "metric_errors" in s
    assert s["metric_errors"]["accuracy"] == ["超时"]
    assert "accuracy" not in s["metrics_summary"], "无有效分数就不产出均值条目"
    # 三条都没算出来，不能凭空报出一个 0 分的通过率
    assert s["unscored_samples"] == 3
    assert s["pass_rate"] == 0.0


def test_partially_failed_sample_still_scored():
    """部分指标失败但还有有效分的样本，照常计分，不算 unscored"""
    e = TrainingDataMetricEngine(
        data_type="llm",
        metric_configs=[{"metric_name": "accuracy"}, {"metric_name": "fluency"}],
        pass_threshold=0.7,
    )
    results = [
        {"accuracy": _r(0.9, passed=True), "fluency": _r(0.0, error="超时")},
    ]
    s = e.compute_summary(results)
    # 还有有效分 → 样本正常计分，不进 unscored（该键仅在有此类样本时出现）
    assert s.get("unscored_samples", 0) == 0
    assert s["metrics_summary"]["accuracy"]["count"] == 1
    assert s["metrics_summary"]["accuracy"]["failed_count"] == 0
    # 失败的那个指标照样要留痕
    assert s["metric_errors"]["fluency"] == ["超时"]


def test_no_failures_means_no_extra_fields():
    e = _engine()
    s = e.compute_summary([{"accuracy": _r(0.9, passed=True)}])
    assert "metric_errors" not in s
    assert "unscored_samples" not in s
    assert s["metrics_summary"]["accuracy"]["failed_count"] == 0
