# 可插拔统计器（Profiler）
#
# 每个统计器声明：
#   name        —— 唯一名
#   capability  —— 需要哪项能力才会启用（由 schema 探测得出）
#   profile()   —— 基于原始记录计算该维度指标
#
# 新增一种数据形态 = 新增一个统计器，不改归一化与画像主流程；
# 数据集缺某项能力时该统计器自动跳过，不会产出误导性的 0 值。
from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from .schema import (
    CAP_HAS_CHOICES,
    CAP_HAS_CONVERSATION,
    CAP_HAS_POSITIVE_NEGATIVE,
    CAP_HAS_SCORE,
    CAP_HAS_SUBJECT,
    ROLE_CHOICES,
    ROLE_CONVERSATION,
    ROLE_SCORE,
    ROLE_SUBJECT,
    Schema,
    count_rounds,
    detect_schema,
    extract_conversation,
)

# 轮次分桶（对数式：轮次跨度大，等距分桶会让「1 轮」挤成一根柱子）
ROUND_BUCKETS = [(0, 1), (1, 2), (2, 4), (4, 8), (8, 16), (16, None)]
ROUND_BUCKET_LABELS = ["1轮", "2轮", "3-4轮", "5-8轮", "9-16轮", "16轮+"]


def round_bucket_of(n: int) -> str:
    for (lo, hi), label in zip(ROUND_BUCKETS, ROUND_BUCKET_LABELS):
        if n > lo and (hi is None or n <= hi):
            return label
    return ROUND_BUCKET_LABELS[-1]


def _percentile(values: List[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    idx = (len(ordered) - 1) * pct
    lo, hi = int(idx // 1), min(int(idx) + 1, len(ordered) - 1)
    if lo == hi:
        return float(ordered[lo])
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo))


# ---------------------------------------------------------------------------
# 统计器实现
# ---------------------------------------------------------------------------
def profile_conversation(
    records: List[Dict[str, Any]], schema: Schema
) -> Dict[str, Any]:
    """对话轮次画像。

    只给出均值是不够的：平均 4 轮可能是「绝大多数 2 轮 + 少量 20 轮长对话」，
    两种数据在训练难度、截断风险、显存开销上完全不同。
    """
    field = schema.field_for(ROLE_CONVERSATION)
    if not field:
        return {}

    rounds: List[int] = []
    for record in records:
        conv = extract_conversation(record, field)
        if not conv:
            continue
        n = count_rounds(conv)
        if n > 0:
            rounds.append(n)

    if not rounds:
        return {}

    buckets = Counter(round_bucket_of(n) for n in rounds)
    return {
        "field": field,
        "samples": len(rounds),
        "stats": {
            "min": min(rounds),
            "max": max(rounds),
            "avg": round(statistics.fmean(rounds), 2),
            "p50": round(_percentile(rounds, 0.5)),
            "p90": round(_percentile(rounds, 0.9)),
        },
        "distribution": [
            {"key": label, "count": buckets.get(label, 0)}
            for label in ROUND_BUCKET_LABELS
        ],
        "ratios": {
            "single_turn": round(sum(1 for n in rounds if n <= 1) / len(rounds), 4),
            "multi_turn": round(sum(1 for n in rounds if 2 <= n <= 4) / len(rounds), 4),
            "deep_turn": round(sum(1 for n in rounds if n >= 5) / len(rounds), 4),
        },
        "observations": _round_observations(rounds, buckets, len(records)),
    }


def _round_observations(
    rounds: List[int], buckets: Counter, total: int
) -> List[str]:
    """把轮次分布翻译成可操作的判断。"""
    notes: List[str] = []
    if not rounds:
        return notes
    n = len(rounds)
    coverage = n / total if total else 0
    p50 = _percentile(rounds, 0.5)
    p90 = _percentile(rounds, 0.9)

    single = sum(1 for x in rounds if x <= 1) / n
    deep = sum(1 for x in rounds if x >= 5) / n

    if single >= 0.9:
        notes.append(
            f"{single:.0%} 为单轮问答，几乎没有多轮交互信号；"
            f"若目标是训练对话/追问能力，需要补充多轮样本"
        )
    if deep >= 0.3:
        notes.append(
            f"{deep:.0%} 为 5 轮以上的深度对话（P90 达 {p90:.0f} 轮，"
            f"最长 {max(rounds)} 轮），训练时需关注上下文截断与显存开销"
        )
    elif p50 <= 1 and p90 >= 5:
        notes.append(
            f"轮次呈长尾分布：中位 {p50:.0f} 轮但 P90 达 {p90:.0f} 轮，"
            f"平均值不具代表性，应按分位数制定截断策略"
        )
    if coverage < 0.5 and coverage > 0:
        notes.append(
            f"仅 {coverage:.0%} 的样本含对话结构，其余为单轮/纯语料形态，"
            f"混合数据建议按形态分桶配置采样比例"
        )
    return notes


def profile_choices(records: List[Dict[str, Any]], schema: Schema) -> Dict[str, Any]:
    """选择题答案形态：答案位置偏置是选择题评测/训练数据最重要的质量信号。"""
    field = schema.field_for(ROLE_CHOICES)
    if not field:
        return {}
    counts = Counter()
    n = 0
    for record in records:
        choices = record.get(field)
        if isinstance(choices, (list, tuple)) and len(choices) >= 2:
            counts[len(choices)] += 1
            n += 1
    if not n:
        return {}
    return {
        "field": field,
        "items": n,
        "choice_count_dist": [
            {"count": c, "ratio": round(v / n, 4)} for c, v in sorted(counts.items())
        ],
    }


def profile_positive_negative(
    records: List[Dict[str, Any]], schema: Schema
) -> Dict[str, Any]:
    """正负例规模：判断检索/对比学习数据的难度与判分空间。"""
    pos_fields = [k for k in schema.fields if "positive" in k.lower() or k.lower() in ("pos",)]
    neg_fields = [k for k in schema.fields if "negative" in k.lower() or k.lower() in ("neg",)]
    if not (pos_fields or neg_fields):
        return {}

    pos_counts: List[int] = []
    neg_counts: List[int] = []
    for record in records:
        pos_counts.append(_len_of(record.get(pos_fields[0])) if pos_fields else 0)
        neg_counts.append(_len_of(record.get(neg_fields[0])) if neg_fields else 0)
    return {
        "positive_fields": pos_fields,
        "negative_fields": neg_fields,
        "avg_positives": round(statistics.fmean(pos_counts), 2) if pos_counts else 0,
        "avg_negatives": round(statistics.fmean(neg_counts), 2) if neg_counts else 0,
        "items_with_negative": round(sum(1 for n in neg_counts if n > 0) / len(records), 4)
        if records else 0.0,
    }


def _len_of(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, str, dict)):
        return len(value)
    return 1


def profile_score(records: List[Dict[str, Any]], schema: Schema) -> Dict[str, Any]:
    """数值打分字段的分布。"""
    field = schema.field_for(ROLE_SCORE)
    if not field:
        return {}
    values: List[float] = []
    for record in records:
        v = record.get(field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            values.append(float(v))
    if not values:
        return {}
    return {
        "field": field,
        "count": len(values),
        "stats": {
            "min": min(values),
            "max": max(values),
            "avg": round(statistics.fmean(values), 3),
            "p50": round(_percentile(values, 0.5), 3),
        },
    }


def profile_subject(records: List[Dict[str, Any]], schema: Schema) -> Dict[str, Any]:
    """能力覆盖：学科/类别的广度与集中度。"""
    field = schema.field_for(ROLE_SUBJECT)
    if not field:
        return {}
    counter = Counter()
    for record in records:
        v = record.get(field)
        if v not in (None, "", [], {}):
            counter[str(v)] += 1
    if not counter:
        return {}
    total = sum(counter.values())
    top = counter.most_common(1)[0]
    return {
        "field": field,
        "distinct": len(counter),
        "coverage_ratio": round(len(counter) / total, 4) if total else 0,
        "top": [{"key": k, "count": v, "ratio": round(v / total, 4)} for k, v in counter.most_common(20)],
        "observations": (
            [f"覆盖 {len(counter)} 个类别，分布集中：「{top[0]}」占 {top[1] / total:.0%}"]
            if len(counter) > 0 else []
        ),
    }


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
class Profiler:
    __slots__ = ("name", "capability", "fn")

    def __init__(self, name: str, capability: str, fn: Callable):
        self.name = name
        self.capability = capability
        self.fn = fn


PROFILERS: List[Profiler] = [
    Profiler("conversation", CAP_HAS_CONVERSATION, profile_conversation),
    Profiler("choices", CAP_HAS_CHOICES, profile_choices),
    Profiler("positive_negative", CAP_HAS_POSITIVE_NEGATIVE, profile_positive_negative),
    Profiler("score", CAP_HAS_SCORE, profile_score),
    Profiler("subject", CAP_HAS_SUBJECT, profile_subject),
]


def run_profilers(
    records: List[Dict[str, Any]], schema: Optional[Schema] = None
) -> Dict[str, Any]:
    """按 schema 推导出的能力选择并执行统计器。

    返回 {"schema": {...}, "applied": [...], "skipped": [...], "dimensions": {...}}
    """
    schema = schema or detect_schema(records)

    caps = schema.capabilities
    applied, skipped, dimensions = [], [], {}

    for profiler in PROFILERS:
        if profiler.capability not in caps:
            skipped.append({"name": profiler.name, "reason": f"数据不含{_cap_label(profiler.capability)}"})
            continue
        try:
            result = profiler.fn(records, schema)
        except Exception as exc:  # 单个统计器失败不应拖垮整个画像
            skipped.append({"name": profiler.name, "reason": f"统计失败：{type(exc).__name__}"})
            continue
        if result:
            dimensions[profiler.name] = result
            applied.append(profiler.name)
        else:
            skipped.append({"name": profiler.name, "reason": "形态不匹配或无有效数据"})

    return {
        "schema": schema.to_dict(),
        "capabilities": sorted(caps),
        "applied": applied,
        "skipped": skipped,
        "dimensions": dimensions,
    }


def _cap_label(cap: str) -> str:
    return {
        CAP_HAS_CONVERSATION: "对话结构",
        CAP_HAS_CHOICES: "选项结构",
        CAP_HAS_POSITIVE_NEGATIVE: "正负例结构",
        CAP_HAS_SCORE: "数值打分字段",
        CAP_HAS_SUBJECT: "学科/类别字段",
    }.get(cap, cap)