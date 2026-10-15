# 训练数据画像计算
#
# 输入是归一化后的样本行（见 normalize.normalize_record），输出直接落到
# training_data_profiles 的各 JSON 列。全部为纯函数，便于单测与离线重算。
import statistics
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .normalize import (
    BUCKET_LABELS,
    FORMAT_LABELS,
    FORMAT_AGENT,
    FORMAT_OTHER,
    FORMAT_PREFERENCE,
    FORMAT_PRETRAIN,
    FORMAT_QA,
    FORMAT_SFT,
    LENGTH_BUCKETS,
    _s,
)
from ..profiling.profilers import run_profilers

# 样本预览与字段画像的抽样上限（避免大 payload 把画像列撑爆）
PAYLOAD_PROFILE_LIMIT = 1000
SAMPLE_PREVIEW_LIMIT = 5
MAX_TEXT_PREVIEW = 500

# 低基数字段做值分布统计的阈值（唯一值不超过这个数就展开 top 占比）
MAX_DISTINCT_FOR_VALUES = 20
MAX_VALUE_BUCKETS = 10

LEVEL_LABELS = {
    "L1": "L1·过滤数据",
    "L2": "L2·精筛数据",
    "L3": "L3·合成/增强数据",
    "L4": "L4·编排数据",
}
GRADE_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "acceptable": "一般",
    "poor": "较差",
}


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = (len(ordered) - 1) * pct
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    frac = idx - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def bucket_of(char_length: int) -> str:
    for (low, high), label in zip(LENGTH_BUCKETS, BUCKET_LABELS):
        if char_length >= low and (high is None or char_length < high):
            return label
    return BUCKET_LABELS[-1]


# 对话轮次分桶（对数式：轮次跨度大，等距分桶会让「1 轮」挤成一根柱子）
ROUND_BUCKETS = [(0, 1), (1, 2), (2, 4), (4, 8), (8, 16), (16, None)]
ROUND_BUCKET_LABELS = ["1轮", "2轮", "3-4轮", "5-8轮", "9-16轮", "16轮+"]


def round_bucket_of(n: int) -> str:
    for (low, high), label in zip(ROUND_BUCKETS, ROUND_BUCKET_LABELS):
        if n > low and (high is None or n <= high):
            return label
    return ROUND_BUCKET_LABELS[-1]


def round_stats(values: List[int]) -> Dict[str, Any]:
    """轮次的集中趋势与离散程度。

    对多轮对话数据均值会骗人：少量超长对话会把均值拉高，
    要判断「典型样本到底几轮」必须看 p50/p90。
    """
    if not values:
        return {"min": 0, "max": 0, "avg": 0.0, "p50": 0, "p90": 0, "samples": 0}
    return {
        "min": min(values),
        "max": max(values),
        "avg": _round(statistics.fmean(values), 2),
        "p50": _round(_percentile(values, 0.5)),
        "p90": _round(_percentile(values, 0.9)),
        "samples": len(values),
    }


def _field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def build_schema_profile(payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """字段画像：覆盖率 / 类型分布 / 示例值 + 值分布、数值统计、文本长度统计

    对前 PAYLOAD_PROFILE_LIMIT 条 payload 统计：
      - coverage: 非空占比
      - types:    值类型分布
      - example:  首个非空示例
      - values:   低基数字段（唯一值 ≤ MAX_DISTINCT_FOR_VALUES）的 top 值占比
      - numeric:  数值字段 min/max/mean
      - text:     字符串字段 avg_len/max_len
    """
    if not payloads:
        return []
    total = len(payloads)
    stats: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            entry = stats.setdefault(key, {
                "covered": 0, "types": Counter(), "example": None,
                "distinct": set(), "numeric": [], "str_lens": [],
            })
            if value not in (None, "", [], {}):
                entry["covered"] += 1
                entry["types"][_field_type(value)] += 1
                if entry["example"] is None:
                    text = _s(value).strip().replace("\n", " ")
                    entry["example"] = text[:120]
                # 值分布收集（仅标量，控制规模）
                if isinstance(value, (str, int, float, bool)) and len(entry["distinct"]) <= MAX_DISTINCT_FOR_VALUES * 2:
                    entry["distinct"].add(value if not isinstance(value, str) else value[:80])
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    entry["numeric"].append(float(value))
                elif isinstance(value, str):
                    entry["str_lens"].append(len(value))
    out = []
    for key, entry in stats.items():
        item: Dict[str, Any] = {
            "name": key,
            "coverage": _round(entry["covered"] / total, 3),
            "types": dict(entry["types"].most_common(4)),
            "example": entry["example"],
        }
        distinct = entry["distinct"]
        if entry["covered"] and len(distinct) <= MAX_DISTINCT_FOR_VALUES:
            counter = Counter()
            for payload in payloads:
                if isinstance(payload, dict):
                    v = payload.get(key)
                    if v not in (None, "", [], {}) and isinstance(v, (str, int, float, bool)):
                        counter[v if not isinstance(v, str) else v[:80]] += 1
            item["values"] = [
                {"value": value, "count": count,
                 "ratio": _round(count / entry["covered"], 4)}
                for value, count in counter.most_common(MAX_VALUE_BUCKETS)
            ]
        if entry["numeric"]:
            nums = entry["numeric"]
            item["numeric"] = {
                "min": _round(min(nums), 4), "max": _round(max(nums), 4),
                "mean": _round(statistics.fmean(nums), 4),
            }
        if entry["str_lens"]:
            item["text"] = {
                "avg_len": _round(statistics.fmean(entry["str_lens"]), 1),
                "max_len": max(entry["str_lens"]),
            }
        out.append(item)
    # 覆盖率高、名字靠前的字段排前面
    out.sort(key=lambda item: (-item["coverage"], item["name"]))
    return out[:40]


def suggest_level(
    fmt_counts: Counter,
    domain_counts: Counter,
    score_mean: Optional[float],
    has_tools: bool,
    source: str = "dataset",
) -> Tuple[str, str]:
    """借 UltraData 的 L1-L4 分级口径给本地数据一个层级建议（启发式）。

    UltraData 口径：
      L1 过滤数据 / L2 精筛数据 / L3 合成与增强数据 / L4 编排数据
    本地信号到层级的映射：
      - 带质量分且均值不错        -> L2（做过质量筛选）
      - 偏好/Agent/合成标签       -> L3（模型生成或增强）
      - 纯预训练正文且无分数      -> L1（只做了基础过滤）
      - 多来源混合 / 工具编排      -> L4（结构化编排）
    """
    total = sum(fmt_counts.values()) or 1
    top_fmt, top_count = (fmt_counts.most_common(1) or [(FORMAT_OTHER, 0)])[0]
    synthetic = (
        fmt_counts[FORMAT_PREFERENCE] + fmt_counts[FORMAT_AGENT] + fmt_counts[FORMAT_SFT]
    ) / total
    blended = domain_counts.get("合成数据", 0) > 0 or source == "ultradata-mixed"

    if has_tools and top_fmt == FORMAT_AGENT:
        return "L3", "Agent 轨迹 + 工具调用，属模型生成的增强数据"
    if score_mean is not None:
        return "L2", f"样本自带质量分（均值 {score_mean:.2f}），已完成质量筛选"
    if blended:
        return "L4", "多来源混合编排"
    if synthetic >= 0.5:
        return "L3", "以指令微调/偏好/Agent 等合成数据为主"
    if top_fmt in (FORMAT_PRETRAIN, FORMAT_QA) or top_count / total >= 0.6:
        return "L1", "以原始语料为主，仅做过基础过滤"
    return "L1", "缺少质量分级信号，默认按过滤层归类"


def build_profile(
    rows: Sequence[Dict[str, Any]],
    payloads: Optional[Sequence[Dict[str, Any]]] = None,
    source: str = "dataset",
    preview_payloads: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """计算画像主体，返回可直接落库的 JSON 字典"""
    payloads = list(payloads or [])
    total = len(rows)

    char_lengths = [int(r.get("char_length") or 0) for r in rows]
    est_tokens = [int(r.get("est_tokens") or 0) for r in rows]
    hashes = [r.get("content_hash") for r in rows if r.get("content_hash")]
    unique = len(set(hashes))
    duplicate_count = total - unique if hashes else 0
    duplicate_rate = _round(duplicate_count / total, 4) if total else 0.0

    fmt_counts = Counter(r.get("format") or FORMAT_OTHER for r in rows)
    lang_counts = Counter(r.get("language") or "other" for r in rows)
    domain_counts: Counter = Counter()
    for r in rows:
        for label in (r.get("labels") or []):
            domain_counts[label] += 1
    bucket_counts = Counter(bucket_of(n) for n in char_lengths)

    scores = [float(r["score"]) for r in rows if r.get("score") is not None]
    score_mean = statistics.fmean(scores) if scores else None

    turn_counts = [int(r.get("turn_count") or 0) for r in rows]
    with_turns = [t for t in turn_counts if t > 0]

    # 对话轮次：优先用 round_count（=user 消息数）；存量数据该列可能为 0，
    # 此时回退到消息条数折半，保证老数据集重跑画像也有轮次分布
    rounds: List[int] = []
    for r in rows:
        rc = int(r.get("round_count") or 0)
        if rc <= 0:
            msgs = int(r.get("turn_count") or 0)
            rc = (msgs + 1) // 2 if msgs > 0 else 0
        if rc > 0:
            rounds.append(rc)
    round_bucket_counts = Counter(round_bucket_of(n) for n in rounds)
    single_turn = sum(1 for n in rounds if n <= 1)
    multi_turn = sum(1 for n in rounds if 2 <= n <= 4)
    deep_turn = sum(1 for n in rounds if n >= 5)
    tool_count = sum(1 for r in rows if r.get("has_tools"))
    thinking_count = sum(1 for r in rows if any(
        kw in (str(r.get("text") or "") + str(r.get("instruction") or ""))[:2000].lower()
        for kw in ("think", "reasoning", "思考")
    ))

    empty_count = sum(1 for n in char_lengths if n == 0)
    overlong_count = sum(1 for n in char_lengths if n > 8192)
    too_short_count = sum(1 for n in char_lengths if 0 < n < 16)

    quality_score = 1.0
    quality_score -= duplicate_rate
    quality_score -= empty_count / total if total else 0
    quality_score -= 0.5 * (too_short_count / total if total else 0)
    quality_score -= 0.25 * (overlong_count / total if total else 0)
    if score_mean is not None:
        quality_score += 0.1 if score_mean >= 0.75 else (-0.1 if score_mean < 0.4 else 0)
    quality_score = max(0.0, min(1.0, quality_score))
    if quality_score >= 0.9:
        grade = "excellent"
    elif quality_score >= 0.75:
        grade = "good"
    elif quality_score >= 0.6:
        grade = "acceptable"
    else:
        grade = "poor"

    top_format = (fmt_counts.most_common(1) or [(FORMAT_OTHER, 0)])[0][0]
    level, level_reason = suggest_level(fmt_counts, domain_counts, score_mean, tool_count > 0, source)

    overview = {
        "total": total,
        "unique": unique,
        "duplicate_count": duplicate_count,
        "duplicate_rate": duplicate_rate,
        "char_length": {
            "min": min(char_lengths) if char_lengths else 0,
            "max": max(char_lengths) if char_lengths else 0,
            "avg": _round(statistics.fmean(char_lengths), 1) if char_lengths else 0,
            "p50": _round(_percentile(char_lengths, 0.5), 1),
            "p90": _round(_percentile(char_lengths, 0.9), 1),
        },
        "tokens": {
            "total": sum(est_tokens),
            "avg": _round(statistics.fmean(est_tokens), 1) if est_tokens else 0,
        },
        "avg_turns": _round(statistics.fmean(with_turns), 2) if with_turns else 0,
        "scored_ratio": _round(len(scores) / total, 4) if total else 0.0,
        "score_mean": _round(score_mean, 3) if score_mean is not None else None,
    }

    classification = {
        "formats": [
            {"key": key, "label": FORMAT_LABELS.get(key, key), "count": count,
             "ratio": _round(count / total, 4) if total else 0}
            for key, count in fmt_counts.most_common()
        ],
        "languages": [
            {"key": key, "count": count, "ratio": _round(count / total, 4) if total else 0}
            for key, count in lang_counts.most_common()
        ],
        "domains": [
            {"key": key, "count": count, "ratio": _round(count / total, 4) if total else 0}
            for key, count in domain_counts.most_common(20)
        ],
        "length_buckets": [
            {"key": label, "count": bucket_counts.get(label, 0)}
            for label in BUCKET_LABELS
        ],
        "structure": {
            # 对话轮次画像：均值不够用，必须给分布。
            # 平均 4 轮可能是「绝大多数 2 轮 + 少量 20 轮长对话」，两者是完全不同的数据。
            "round_stats": round_stats(rounds),
            "round_distribution": [
                {"key": label, "count": round_bucket_counts.get(label, 0)}
                for label in ROUND_BUCKET_LABELS
            ],
            "single_turn_ratio": _round(single_turn / total, 4) if total else 0.0,
            "multi_turn_ratio": _round(multi_turn / total, 4) if total else 0.0,
            "deep_turn_ratio": _round(deep_turn / total, 4) if total else 0.0,
            "avg_turns": _round(statistics.fmean(with_turns), 2) if with_turns else 0,
            "multi_turn_ratio_msgs": _round(len(with_turns) / total, 4) if total else 0.0,
            "tool_call_ratio": _round(tool_count / total, 4) if total else 0.0,
            "thinking_ratio": _round(thinking_count / total, 4) if total else 0.0,
        },
        "primary_format": top_format,
        "primary_format_label": FORMAT_LABELS.get(top_format, top_format),
        "level": level,
        "level_reason": level_reason,
    }

    quality = {
        "score": _round(quality_score, 3),
        "grade": grade,
        "empty_rate": _round(empty_count / total, 4) if total else 0.0,
        "duplicate_rate": duplicate_rate,
        "overlong_rate": _round(overlong_count / total, 4) if total else 0.0,
        "too_short_rate": _round(too_short_count / total, 4) if total else 0.0,
        "score_mean": _round(score_mean, 3) if score_mean is not None else None,
        "score_p50": _round(_percentile(scores, 0.5), 3) if scores else None,
        "score_min": _round(min(scores), 3) if scores else None,
        "score_max": _round(max(scores), 3) if scores else None,
        "issues": _quality_issues(duplicate_rate, empty_count / total if total else 0,
                                  overlong_count / total if total else 0,
                                  too_short_count / total if total else 0),
    }

    tags = [top_format]
    tags.extend(key for key, _ in domain_counts.most_common(4))
    if lang_counts:
        tags.append(lang_counts.most_common(1)[0][0])
    tags.append(level)

    classification["top_domains"] = [
        {"key": key, "count": count, "ratio": _round(count / total, 4) if total else 0}
        for key, count in domain_counts.most_common(5)
    ]

    # ---- 通用层：schema 探测 + 按能力分派的统计器 ----
    # 不再假定固定字段名：先探测这份数据到底有哪些结构（对话/选项/正负例/打分/学科），
    # 再只运行适用的统计器，把不适用的维度显式标为 skipped 而不是输出 0 值。
    generic = run_profilers(
        [r.get("payload") for r in rows if isinstance(r.get("payload"), dict)],
    )
    classification["generic"] = {
        "schema": generic["schema"],
        "capabilities": generic["capabilities"],
        "applied": generic["applied"],
        "skipped": generic["skipped"],
        "dimensions": generic["dimensions"],
    }
    # 用通用层探测到的轮次画像覆盖归一化层的估计（字段名不同也能算对）
    conv_dim = (generic["dimensions"] or {}).get("conversation") or {}
    if conv_dim:
        classification["structure"].update({
            "round_field": conv_dim.get("field"),
            "round_stats": conv_dim.get("stats"),
            "round_distribution": conv_dim.get("distribution"),
            "round_observations": conv_dim.get("observations"),
            "single_turn_ratio": (conv_dim.get("ratios") or {}).get("single_turn"),
            "multi_turn_ratio": (conv_dim.get("ratios") or {}).get("multi_turn"),
            "deep_turn_ratio": (conv_dim.get("ratios") or {}).get("deep_turn"),
        })

    return {
        "format": top_format,
        "level": level,
        "tags": tags,
        "total": total,
        "unique": unique,
        "duplicate_rate": duplicate_rate,
        "overview": overview,
        "schema_profile": build_schema_profile(payloads),
        "classification": classification,
        "quality": quality,
        "samples": build_samples(preview_payloads if preview_payloads is not None else payloads),
        "summary": build_summary_text(
            total=total, unique=unique, duplicate_rate=duplicate_rate,
            char_length=overview["char_length"], tokens=overview["tokens"],
            fmt_counts=fmt_counts, lang_counts=lang_counts,
            domain_counts=domain_counts, bucket_counts=bucket_counts,
            score_mean=score_mean, scored_ratio=overview["scored_ratio"],
            quality_score=quality_score, grade=grade,
            level=level, level_reason=level_reason,
            structure=classification["structure"], issues=quality["issues"],
        ),
    }


def _pct(count: int, total: int) -> str:
    return f"{count / total:.0%}" if total else "0%"


def build_summary_text(
    *, total: int, unique: int, duplicate_rate: float,
    char_length: Dict[str, float], tokens: Dict[str, float],
    fmt_counts: Counter, lang_counts: Counter, domain_counts: Counter,
    bucket_counts: Counter, score_mean: Optional[float], scored_ratio: float,
    quality_score: float, grade: str, level: str, level_reason: str,
    structure: Dict[str, float], issues: List[str],
) -> str:
    """规则生成的自然语言摘要：没接触过数据集的人读这一段就能看懂全貌"""
    parts: List[str] = []

    top_fmt, top_fmt_count = (fmt_counts.most_common(1) or [(FORMAT_OTHER, 0)])[0]
    fmt_label = FORMAT_LABELS.get(top_fmt, top_fmt)
    if len(fmt_counts) == 1:
        parts.append(f"共 {total:,} 条样本，全部为「{fmt_label}」格式。")
    else:
        fmt_desc = "、".join(
            f"{FORMAT_LABELS.get(k, k)} {_pct(c, total)}"
            for k, c in fmt_counts.most_common(3)
        )
        parts.append(f"共 {total:,} 条样本，以「{fmt_label}」为主（{_pct(top_fmt_count, total)}），整体构成为：{fmt_desc}。")

    if lang_counts:
        lang_desc = "、".join(
            f"{'中文' if k == 'zh' else '英文' if k == 'en' else '中英混合' if k == 'mixed' else '其他'} {_pct(c, total)}"
            for k, c in lang_counts.most_common(3)
        )
        parts.append(f"语言分布：{lang_desc}。")

    if domain_counts:
        domain_desc = "、".join(f"{k}({_pct(c, total)})" for k, c in domain_counts.most_common(5))
        parts.append(f"内容主题主要集中在：{domain_desc}。")

    avg_len = char_length.get("avg", 0)
    p50 = char_length.get("p50", 0)
    dominant_bucket = (bucket_counts.most_common(1) or [("未知", 0)])[0][0]
    parts.append(
        f"样本长度中位数约 {p50:.0f} 字符、平均 {avg_len:.0f} 字符"
        f"（约 {tokens.get('avg', 0):.0f} tokens/条，全量估算 {tokens.get('total', 0):,} tokens），"
        f"多数落在「{dominant_bucket}」区间。"
    )

    if duplicate_rate > 0:
        parts.append(f"去重后 {unique:,} 条（重复率 {duplicate_rate:.1%}）。")

    if score_mean is not None:
        parts.append(
            f"{_pct(int(scored_ratio * total), total)} 的样本自带质量分"
            f"（均值 {score_mean:.2f}，0-1 量纲）。"
        )

    parts.append(f"整体质量评级：{GRADE_LABELS.get(grade, grade)}（{quality_score:.2f}）。")

    rs = structure.get("round_stats") or {}
    if rs.get("samples"):
        parts.append(
            f"对话轮次：中位数 {rs['p50']} 轮、P90 {rs['p90']} 轮、最长 {rs['max']} 轮"
            f"（单轮占 {_pct(int(structure.get('single_turn_ratio', 0) * total), total)}，"
            f"多轮 2-4 轮占 {_pct(int(structure.get('multi_turn_ratio', 0) * total), total)}，"
            f"5 轮以上占 {_pct(int(structure.get('deep_turn_ratio', 0) * total), total)}）"
        )
    if structure.get("multi_turn_ratio_msgs", 0) >= 0.3:
        parts.append(
            f"{_pct(int(structure['multi_turn_ratio_msgs'] * total), total)} 为多消息对话样本"
            f"（平均 {structure.get('avg_turns', 0):.1f} 条消息）"
        )
    if structure.get("tool_call_ratio", 0) > 0:
        parts.append(f"{_pct(int(structure['tool_call_ratio'] * total), total)} 含工具调用。")

    real_issues = [i for i in issues if "未发现" not in i]
    if real_issues:
        parts.append("需要注意：" + "；".join(real_issues) + "。")
    else:
        parts.append("未发现明显的重复、空文本、过短/过长等结构性问题。")

    parts.append(f"按 UltraData 口径建议归入「{LEVEL_LABELS.get(level, level)}」：{level_reason}。")
    return "".join(parts)


def _quality_issues(duplicate_rate: float, empty_rate: float,
                    overlong_rate: float, too_short_rate: float) -> List[str]:
    issues = []
    if duplicate_rate >= 0.05:
        issues.append(f"重复样本占比 {duplicate_rate:.1%}，建议去重后再训练")
    if empty_rate > 0:
        issues.append(f"存在 {empty_rate:.1%} 的空文本样本")
    if overlong_rate >= 0.05:
        issues.append(f"{overlong_rate:.1%} 样本超过 8192 字符，注意截断策略")
    if too_short_rate >= 0.1:
        issues.append(f"{too_short_rate:.1%} 样本过短（<16 字符），信息量可能不足")
    if not issues:
        issues.append("未发现明显结构性问题")
    return issues


def build_samples(payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """样本预览：原样保留字段，只做长度截断"""
    out = []
    for payload in list(payloads)[:SAMPLE_PREVIEW_LIMIT]:
        if isinstance(payload, dict):
            item = {}
            for key, value in payload.items():
                text = _s(value).replace("\n", " ")
                item[key] = text[:MAX_TEXT_PREVIEW]
        else:
            item = {"value": _s(payload)[:MAX_TEXT_PREVIEW]}
        out.append(item)
    return out
