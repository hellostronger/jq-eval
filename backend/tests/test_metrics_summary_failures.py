# 评估汇总必须暴露"指标算失败了"，不能只报成功算出来的那部分
#
# 隐患：MetricResult 带 error 的记录此前直接从均值里剔除，且不留痕迹。
# 若某指标对所有记录都失败，它会整个从汇总里消失——报告上和
# "压根没配这个指标"长得一模一样，用户看不出是系统出了问题。
import math

from app.services.metrics.base import MetricResult
from app.services.metrics.engine import MetricEngine


def _r(score, error=None):
    return MetricResult(score=score, error=error)


def test_failed_metrics_are_excluded_from_mean_but_counted():
    """失败的记录不参与均值，但必须留下 failed_count"""
    results = [
        {"faithfulness": _r(0.9)},
        {"faithfulness": _r(0.0, error="答案为空")},
        {"faithfulness": _r(0.7)},
    ]
    s = MetricEngine.compute_summary(results)
    m = s["metrics_summary"]["faithfulness"]
    assert m["count"] == 2, "只有成功的 2 条参与统计"
    assert m["failed_count"] == 1, "失败的那条必须被记账"
    assert abs(m["mean"] - 0.8) < 1e-9, "均值只算成功的两条"
    assert "metric_errors" in s
    assert s["metric_errors"]["faithfulness"] == ["答案为空"]


def test_metric_failing_on_every_record_is_reported_not_silently_dropped():
    """全军覆没的指标必须显式报错，而不是从报告里消失"""
    results = [
        {"faithfulness": _r(0.0, error="缺少contexts数据")},
        {"faithfulness": _r(0.0, error="缺少contexts数据")},
    ]
    s = MetricEngine.compute_summary(results)
    assert "metric_errors" in s, "全失败的指标必须出现在 metric_errors 里"
    assert "faithfulness" in s["metric_errors"]
    # 没有有效分数就不该有均值条目，但错误必须留痕
    assert "faithfulness" not in s["metrics_summary"]
    assert s["overall_score"] == 0.0


def test_duplicate_errors_are_deduped():
    """同一错误重复上千次不该把 summary 撑爆"""
    results = [{"m": _r(0.0, error="超时")} for _ in range(50)]
    s = MetricEngine.compute_summary(results)
    assert s["metric_errors"]["m"] == ["超时"], "相同原因只留一条"
    # 全部失败 → 没有有效分数 → 不产出均值条目（这是正确的）
    assert "m" not in s["metrics_summary"]


def test_failed_count_reflects_total_not_deduped():
    """去重只影响错误文案列表，失败总数必须如实计数"""
    results = (
        [{"m": _r(0.0, error="超时")} for _ in range(30)]
        + [{"m": _r(0.0, error="缺少contexts")} for _ in range(20)]
        + [{"m": _r(0.8)} for _ in range(50)]
    )
    s = MetricEngine.compute_summary(results)
    m = s["metrics_summary"]["m"]
    assert m["count"] == 50, "只有成功的 50 条参与统计"
    assert m["failed_count"] == 50, "两种失败原因合计 50 条"
    assert abs(m["mean"] - 0.8) < 1e-9
    assert set(s["metric_errors"]["m"]) == {"超时", "缺少contexts"}, "两种原因各留一条"


def test_no_failures_means_no_metric_errors_key():
    """全部成功时不应凭空多出字段，避免前端误判"""
    results = [{"m": _r(0.5)}, {"m": _r(0.9)}]
    s = MetricEngine.compute_summary(results)
    assert "metric_errors" not in s
    assert s["metrics_summary"]["m"]["failed_count"] == 0


def test_nan_scores_still_excluded_without_being_counted_as_failures():
    """NaN 仍应被排除，但它不是"失败"，不要混进 metric_errors"""
    results = [
        {"m": _r(0.5)},
        {"m": _r(float("nan"))},
    ]
    s = MetricEngine.compute_summary(results)
    assert s["metrics_summary"]["m"]["count"] == 1
    assert "metric_errors" not in s, "NaN 是解析问题，不是计算失败"
