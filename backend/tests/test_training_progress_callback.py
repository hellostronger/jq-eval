# 批量评估的进度回调：任务层要靠它把进度落库，页面才能看到真实百分比
#
# 两个曾经踩过的坑：
# 1. 回调只支持同步写法时，任务层的协程回调不会被 await，
#    progress 永远落不了库（页面全程 0%，长任务看着像卡死）
# 2. 进度用 i + batch_size 算，最后一批不满时会提前顶到 100%
import asyncio

from app.services.training_data.base import TrainingDataMetricResult
from app.services.training_data.engine import TrainingDataMetricEngine


class _StubMetric:
    """最小指标替身：只关心批次回调，不关心分数"""

    name = "stub"
    data_types = ["llm"]
    category = "quality"
    requires_llm = False
    requires_embedding = False
    requires_ground_truth = False
    default_threshold = 0.5
    threshold_type = "min"

    def __init__(self, params=None, llm=None, embedding_model=None):
        self.params = params or {}

    async def compute(self, question, answer, contexts=None, ground_truth=None, **kwargs):
        return TrainingDataMetricResult(score=1.0, passed=True)


def _engine(total_records):
    e = TrainingDataMetricEngine(data_type="llm", pass_threshold=0.6)
    e.metrics = {"stub": _StubMetric()}
    e.metric_configs = [{"metric_name": "stub", "weight": 1.0, "enabled": True}]
    return e


def _records(n):
    return [{"question": f"q{i}", "answer": f"a{i}"} for i in range(n)]


def test_async_progress_callback_is_awaited():
    calls = []

    async def cb(progress, current, total):
        calls.append((progress, current, total))

    e = _engine(6)
    asyncio.run(e.evaluate_batch(_records(6), batch_size=2, progress_callback=cb))

    assert [c[1] for c in calls] == [2, 4, 6], "每批回调一次，current 为已处理条数"
    assert [round(c[0], 2) for c in calls] == [33.33, 66.67, 100.0]


def test_sync_progress_callback_still_supported():
    calls = []
    e = _engine(4)
    asyncio.run(e.evaluate_batch(_records(4), batch_size=2, progress_callback=lambda *a: calls.append(a)))
    assert [c[1] for c in calls] == [2, 4]


def test_last_partial_batch_does_not_report_100_early():
    """7 条 / 每批 3 条：最后一批只有 1 条，中途不能出现 100%"""
    calls = []

    async def cb(progress, current, total):
        calls.append(progress)

    e = _engine(7)
    asyncio.run(e.evaluate_batch(_records(7), batch_size=3, progress_callback=cb))

    assert [round(p, 2) for p in calls] == [42.86, 85.71, 100.0]