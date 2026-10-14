# 评测集画像计算
#
# 与 training_data/profiling.py 对称，但画像维度不同：
# 训练数据问「这份语料质量如何」，评测集问「这个集考什么、怎么判分、有没有坑」。
#
# 三个评测集独有的高价值维度：
#   1. 答案位置分布（answer_position_dist）——正确项落在 A/B/C/D 的分布，
#      偏斜则模型可从选项位置猜答案，分数虚高。这是选择题评测集最重要的质量信号。
#   2. 选项长度偏置（choice_length_bias）——正确项恒为最长/最短，可被长度启发式破解。
#   3. 答案泄漏（answer_leak_rate）——答案字面出现在题干里。
#
# 纯函数、无 IO、无 LLM，便于单测。
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .normalize import (
    ANSWER_LABELS,
    ANSWER_NONE,
    FORMAT_LABELS,
    MODEL_LABELS,
    MODEL_LLM,
    normalize_for_hash,
)

# 截断上限（与训练画像保持同量级，避免画像 JSON 过大）
PAYLOAD_PROFILE_LIMIT = 1000
SAMPLE_PREVIEW_LIMIT = 5
MAX_TEXT_PREVIEW = 500
MAX_DISTINCT_FOR_VALUES = 20
MAX_VALUE_BUCKETS = 10
MAX_SUBJECTS = 50
MAX_CATEGORIES = 30

QUALITY_GRADE_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "acceptable": "一般",
    "poor": "较差",
}

# 题干长度分桶（评测集关注 prompt 开销，桶比训练数据更细）
LENGTH_BUCKETS = [(0, 30), (30, 100), (100, 300), (300, 1000), (1000, None)]
BUCKET_LABELS = ["0-30", "30-100", "100-300", "300-1k", "1k+"]

# 各 model_type 期望的题型，用于「这个集和它的归属匹配吗」体检
EXPECTED_FORMATS = {
    "embedding": {"retrieval", "pair_similarity", "rerank"},
    "reranker": {"rerank"},
    "llm": {"mc", "generate", "judge", "agentic"},
    "retrieval": {"retrieval", "mc", "generate"},
}


def _pct(part: float, total: float) -> float:
    return round(part / total, 4) if total else 0.0


def _dist(counter: Counter, labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Counter → 带占比的分布列表，按占比降序。"""
    total = sum(counter.values())
    out = [
        {
            "key": key,
            "label": (labels or {}).get(key, key),
            "count": count,
            "ratio": _pct(count, total),
        }
        for key, count in counter.items()
    ]
    out.sort(key=lambda x: -x["count"])
    return out


def _percentiles(values: List[int]) -> Dict[str, Any]:
    """min/max/avg/p50/p90，线性插值分位。"""
    if not values:
        return {"min": 0, "max": 0, "avg": 0, "p50": 0, "p90": 0}
    ordered = sorted(values)

    def _p(pct: float) -> int:
        if len(ordered) == 1:
            return ordered[0]
        idx = (len(ordered) - 1) * pct
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return ordered[lo]
        return int(round(ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)))

    return {
        "min": ordered[0],
        "max": ordered[-1],
        "avg": int(round(statistics.fmean(ordered))),
        "p50": _p(0.5),
        "p90": _p(0.9),
    }


def _bucket(length: int) -> str:
    for (lo, hi), label in zip(LENGTH_BUCKETS, BUCKET_LABELS):
        if length >= lo and (hi is None or length < hi):
            return label
    return BUCKET_LABELS[-1]


# ---------------------------------------------------------------------------
# 题型画像
# ---------------------------------------------------------------------------
def build_task_profile(rows: List[Dict[str, Any]], model_type: str) -> Dict[str, Any]:
    fmt_counter = Counter(r.get("task_format") or "other" for r in rows)
    ans_counter = Counter(r.get("answer_type") or ANSWER_NONE for r in rows)
    primary = fmt_counter.most_common(1)[0][0] if fmt_counter else "other"
    total = len(rows)

    result = {
        "formats": _dist(fmt_counter, FORMAT_LABELS),
        "answer_types": _dist(ans_counter, ANSWER_LABELS),
        "primary_format": primary,
        "primary_format_label": FORMAT_LABELS.get(primary, primary),
        "model_type": model_type,
        "model_type_label": MODEL_LABELS.get(model_type, model_type),
        "total": total,
    }

    # 归属体检：声称是 embedding 集却全是选择题，说明归类错了或数据被混装
    expected = EXPECTED_FORMATS.get(model_type, set())
    unexpected = [k for k in fmt_counter if k not in expected and k != "other"]
    if unexpected:
        result["mismatch"] = (
            f"标记为「{MODEL_LABELS.get(model_type, model_type)}」，"
            f"但存在不匹配的题型：{'、'.join(FORMAT_LABELS.get(k, k) for k in unexpected)}"
        )
    else:
        result["mismatch"] = None
    return result


# ---------------------------------------------------------------------------
# 答案形态画像（评测集最有诊断价值的部分）
# ---------------------------------------------------------------------------
def build_answer_profile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    choice_rows = [r for r in rows if r.get("choices")]
    result: Dict[str, Any] = {
        "choice_items": len(choice_rows),
        "choice_count_dist": [],
        "answer_position_dist": [],
        "answer_position_bias": 0.0,
        "multi_choice_combos": [],
        "answer_length": {"min": 0, "max": 0, "avg": 0, "p50": 0},
        "choice_length_stats": {},
    }
    if not choice_rows:
        return result

    # 选项数分布
    choice_counter = Counter(len(r["choices"]) for r in choice_rows)
    total = len(choice_rows)
    result["choice_count_dist"] = [
        {"count": n, "ratio": _pct(c, total)} for n, c in sorted(choice_counter.items())
    ]

    # 答案位置分布：多选题每个正确项各计一次
    pos_counter: Counter = Counter()
    for r in choice_rows:
        for label in r.get("answer_labels") or []:
            pos_counter[label] += 1
    total_positions = sum(pos_counter.values())
    if total_positions:
        labels_seen = sorted(pos_counter.keys())
        result["answer_position_dist"] = [
            {"label": lb, "count": pos_counter[lb], "ratio": _pct(pos_counter[lb], total_positions)}
            for lb in labels_seen
        ]
        # 偏置度：实际占比与均匀占比(1/选项数)的最大偏离
        uniform = 1.0 / max(len(labels_seen), 1)
        result["answer_position_bias"] = round(
            max(abs(pos_counter[lb] / total_positions - uniform) for lb in labels_seen), 4
        )

    # 多选组合
    combo_counter = Counter(
        "".join(sorted(r.get("answer_labels") or []))
        for r in choice_rows
        if len(r.get("answer_labels") or []) > 1
    )
    result["multi_choice_combos"] = [
        {"combo": combo, "count": c, "ratio": _pct(c, sum(combo_counter.values()))}
        for combo, c in combo_counter.most_common(MAX_VALUE_BUCKETS)
    ]

    # 生成题/判别题参考答案长度
    text_lengths = [
        len(r.get("answer_text") or "") for r in rows
        if (r.get("answer_text") or "").strip() and not r.get("choices")
    ]
    if text_lengths:
        result["answer_length"] = _percentiles(text_lengths)

    # 选项长度偏置：正确项 vs 干扰项平均长度
    correct_lens: List[int] = []
    distractor_lens: List[int] = []
    for r in choice_rows:
        choices = r["choices"]
        labels = r.get("answer_labels") or []
        for i, text in enumerate(choices):
            label = r["choice_labels"][i] if i < len(r.get("choice_labels") or []) else None
            (correct_lens if label in labels else distractor_lens).append(len(text))
    if correct_lens and distractor_lens:
        c_avg = statistics.fmean(correct_lens)
        d_avg = statistics.fmean(distractor_lens)
        result["choice_length_stats"] = {
            "correct_avg": int(round(c_avg)),
            "distractor_avg": int(round(d_avg)),
            # 正值表示正确项更长；相对偏离度，>0.2 视为可被长度启发式破解
            "bias": round((c_avg - d_avg) / d_avg, 4) if d_avg else 0.0,
        }
    return result


# ---------------------------------------------------------------------------
# 能力维度画像
# ---------------------------------------------------------------------------
def build_capability(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    subject_counter = Counter(r["subject"] for r in rows if r.get("subject"))
    category_counter = Counter(r["category"] for r in rows if r.get("category"))
    lang_counter = Counter(r.get("language") or "other" for r in rows)
    diff_counter = Counter(r.get("difficulty") or "unspecified" for r in rows)
    total = len(rows)

    result: Dict[str, Any] = {
        "subjects": _dist(subject_counter)[:MAX_SUBJECTS],
        "subject_count": len(subject_counter),
        "categories": _dist(category_counter)[:MAX_CATEGORIES],
        "languages": _dist(lang_counter, {"zh": "中文", "en": "英文", "mixed": "中英混合", "other": "其他"}),
        "difficulties": _dist(diff_counter),
        "labeled_ratio": _pct(
            sum(1 for r in rows if r.get("subject") or r.get("category")), total
        ),
    }
    # embedding / reranker 集常无学科字段，改看正负例规模画像
    pos_counts = [r.get("pos_count") or 0 for r in rows]
    neg_counts = [r.get("neg_count") or 0 for r in rows]
    if any(pos_counts) or any(neg_counts):
        result["retrieval_shape"] = {
            "avg_positives": round(statistics.fmean(pos_counts), 2) if any(pos_counts) else 0,
            "avg_negatives": round(statistics.fmean(neg_counts), 2) if any(neg_counts) else 0,
            "items_with_negative": _pct(sum(1 for n in neg_counts if n > 0), total),
        }
    return result


# ---------------------------------------------------------------------------
# 质量与风险
# ---------------------------------------------------------------------------
def build_quality(
    rows: List[Dict[str, Any]],
    unique: int,
    total: int,
    answer_profile: Dict[str, Any],
) -> Dict[str, Any]:
    duplicate_rate = _pct(total - unique, total)

    empty_question = sum(1 for r in rows if not (r.get("question") or "").strip())
    has_answer = [
        r for r in rows
        if (r.get("answer_labels") or (r.get("answer_text") or "").strip()
            or r.get("pos_count") or r.get("passages"))
    ]
    empty_answer = len(rows) - len(has_answer)
    too_long = sum(1 for r in rows if (r.get("question_length") or 0) > 4000)
    explanation_count = sum(1 for r in rows if r.get("explanation"))
    dup_choices = 0
    for r in rows:
        choices = r.get("choices") or []
        if choices and len({normalize_for_hash(c) for c in choices}) < len(choices):
            dup_choices += 1

    # 答案泄漏：答案字面出现在题干里。
    # 注意：短答案必须放行到 2 个字符——「答案就是 42」这类数值答案恰好是最易泄漏的，
    # 而 42 归一化后只有 2 字符，若卡在 >=3 会把最该抓的样本全放过去（实测踩过）
    leaked = 0
    for r in rows:
        q_norm = normalize_for_hash(r.get("question") or "")
        if not q_norm or len(q_norm) < 6:
            continue  # 题干过短容易误判
        targets = [normalize_for_hash(c) for c in (r.get("choices") or [])]
        targets.append(normalize_for_hash(r.get("answer_text") or ""))
        for t in targets:
            if not t:
                continue
            # 纯数字短答案（如 42）直接判泄漏；其余仍要求 >=3 字符避免空转
            is_numeric = t.isdigit()
            if len(t) >= 3 or is_numeric:
                if t in q_norm:
                    leaked += 1
                    break

    signals = {
        "empty_question_rate": _pct(empty_question, total),
        "empty_answer_rate": _pct(empty_answer, total),
        "answer_leak_rate": _pct(leaked, total),
        "duplicate_choice_rate": _pct(dup_choices, total),
        "truncated_rate": _pct(too_long, total),
        "explanation_ratio": _pct(explanation_count, total),
        "answer_conflict_rate": _pct(
            sum(1 for r in rows if r.get("answer_conflict")), total
        ),
    }

    # 质量分：与训练画像同口径（重复/空值/过短/超长），保证可横向理解
    score = 1.0 - duplicate_rate
    if total:
        score -= empty_question / total
        score -= 0.5 * (empty_answer / total)
        score -= 0.25 * (_pct(too_long, total))
    score = max(0.0, min(1.0, score))
    grade = (
        "excellent" if score >= 0.9 else "good" if score >= 0.75
        else "acceptable" if score >= 0.6 else "poor"
    )

    issues = _quality_issues(signals, answer_profile, total)
    return {"score": round(score, 4), "grade": grade, "grade_label": QUALITY_GRADE_LABELS[grade],
            "signals": signals, "issues": issues}


def _quality_issues(
    signals: Dict[str, float],
    answer_profile: Dict[str, Any],
    total: int,
) -> List[str]:
    """把信号翻译成人话。每条都是可操作的判断，不是模板化输出。"""
    issues: List[str] = []
    if total <= 0:
        return issues

    bias = answer_profile.get("answer_position_bias") or 0
    dist = answer_profile.get("answer_position_dist") or []
    if bias > 0.10 and dist:
        worst = max(dist, key=lambda d: d["ratio"])
        uniform = 1.0 / max(len(dist), 1)
        issues.append(
            f"答案位置分布偏斜：正确项落在 {worst['label']} 的占 {worst['ratio']:.0%}"
            f"（均匀分布应为 {uniform:.0%}），模型可能从选项位置猜答案，分数会被高估"
        )

    if signals.get("answer_leak_rate", 0) > 0.01:
        issues.append(
            f"答案泄漏：{signals['answer_leak_rate']:.1%} 的题目中，正确答案的字面文本"
            f"直接出现在题干里，属于必须清理的数据缺陷"
        )

    stats = answer_profile.get("choice_length_stats") or {}
    if abs(stats.get("bias", 0)) > 0.20:
        direction = "更长" if stats["bias"] > 0 else "更短"
        issues.append(
            f"选项长度存在偏置：正确项平均 {stats['correct_avg']} 字，"
            f"干扰项平均 {stats['distractor_avg']} 字，正确项恒{direction}，"
            f"可被长度启发式破解"
        )

    if signals.get("duplicate_choice_rate", 0) > 0.01:
        issues.append(
            f"{signals['duplicate_choice_rate']:.1%} 的题目存在完全重复的选项，出题质量存疑"
        )
    if signals.get("empty_question_rate", 0) > 0:
        issues.append(f"存在空题干：{signals['empty_question_rate']:.1%}")
    if signals.get("empty_answer_rate", 0) > 0.05:
        issues.append(
            f"{signals['empty_answer_rate']:.1%} 的题目没有标准答案，无法自动判分"
        )
    if signals.get("answer_conflict_rate", 0) > 0:
        issues.append(
            f"集内存在 {signals['answer_conflict_rate']:.1%} 的同题干不同答案冲突，需人工复核"
        )
    if signals.get("explanation_ratio", 0) < 0.2 and (answer_profile.get("choice_items") or 0) > 0:
        issues.append(
            f"仅 {signals['explanation_ratio']:.0%} 的题目带解析，"
            f"出错时难以定位模型是知识不会还是推理出错"
        )
    if signals.get("truncated_rate", 0) > 0.05:
        issues.append(f"{signals['truncated_rate']:.1%} 的题干超过 4000 字，可能被上下文截断")

    if not issues:
        issues.append("未发现明显结构性问题")
    return issues


# ---------------------------------------------------------------------------
# 字段画像（复用训练画像口径）
# ---------------------------------------------------------------------------
def build_schema_profile(payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from ..training_data.profiling import build_schema_profile as _base
    return _base(payloads[:PAYLOAD_PROFILE_LIMIT])


def build_samples(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows[:SAMPLE_PREVIEW_LIMIT]:
        payload = r.get("payload") or {}
        truncated = {
            k: (v[:MAX_TEXT_PREVIEW] if isinstance(v, str) and len(v) > MAX_TEXT_PREVIEW else v)
            for k, v in payload.items()
        }
        out.append({
            "question": (r.get("question") or "")[:300],
            "task_format": r.get("task_format"),
            "answer_type": r.get("answer_type"),
            "choices": (r.get("choices") or [])[:8],
            "answer_labels": r.get("answer_labels"),
            "answer_text": (r.get("answer_text") or "")[:200] or None,
            "subject": r.get("subject"),
            "payload": truncated,
        })
    return out


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------
def build_overview(rows: List[Dict[str, Any]], unique: int, model_type: str) -> Dict[str, Any]:
    total = len(rows)
    q_len = [r.get("question_length") or 0 for r in rows]
    c_len = [r.get("context_length") or 0 for r in rows]
    tokens = [r.get("est_tokens") or 0 for r in rows]
    return {
        "total": total,
        "unique": unique,
        "duplicate_count": total - unique,
        "duplicate_rate": _pct(total - unique, total),
        "question_length": _percentiles(q_len),
        "context_length": _percentiles(c_len),
        "tokens": {
            "total": sum(tokens),
            "avg": int(round(statistics.fmean(tokens))) if tokens else 0,
        },
        "length_buckets": _dist(Counter(_bucket(n) for n in q_len), dict(zip(BUCKET_LABELS, BUCKET_LABELS))),
        "scored_ratio": _pct(
            sum(1 for r in rows
                if r.get("answer_labels") or (r.get("answer_text") or "").strip()
                or r.get("pos_count") or r.get("passages")),
            total,
        ),
        "model_type": model_type,
    }


# ---------------------------------------------------------------------------
# 自然语言摘要（规则生成，不调 LLM，保证可复现）
# ---------------------------------------------------------------------------
def build_summary_text(
    overview: Dict[str, Any],
    task_profile: Dict[str, Any],
    answer_profile: Dict[str, Any],
    capability: Dict[str, Any],
    quality: Dict[str, Any],
    model_type: str,
) -> str:
    total = overview["total"]
    if not total:
        return "评测集为空，没有可统计的样本。"

    parts: List[str] = []
    model_label = MODEL_LABELS.get(model_type, model_type)
    parts.append(
        f"这是一个面向「{model_label}」的评测集，共 {total:,} 条，"
        f"主要题型为「{task_profile['primary_format_label']}」"
    )

    if task_profile.get("mismatch"):
        parts.append(f"注意：{task_profile['mismatch']}")

    # 学科/能力覆盖
    subj = capability.get("subjects") or []
    if subj:
        top = [s["label"] for s in subj[:5]]
        parts.append(
            f"覆盖 {capability['subject_count']} 个学科/类别，"
            f"占比最高的是：{'、'.join(top)}"
        )
    elif capability.get("retrieval_shape"):
        shape = capability["retrieval_shape"]
        parts.append(
            f"检索形态：平均每条 {shape['avg_positives']} 个正例、"
            f"{shape['avg_negatives']} 个负例，"
            f"{shape['items_with_negative']:.0%} 的条目带负例（可算 hard negative 指标）"
        )

    # 语言
    langs = capability.get("languages") or []
    if langs and langs[0]["key"] not in ("other",):
        parts.append(f"语言以{langs[0]['label']}为主")

    # 长度与开销
    ql = overview["question_length"]
    parts.append(
        f"题干长度中位数 {ql['p50']} 字、P90 {ql['p90']} 字，"
        f"平均每条约 {overview['tokens']['avg']} token"
    )

    # 答案形态 —— 评测集最该看的
    if answer_profile.get("choice_items"):
        dist = answer_profile.get("answer_position_dist") or []
        bias = answer_profile.get("answer_position_bias") or 0
        ci = answer_profile.get("choice_count_dist") or []
        ci_desc = "、".join(f"{c['count']} 选项 {c['ratio']:.0%}" for c in ci[:4])
        parts.append(
            f"其中 {answer_profile['choice_items']} 条为选择题（{ci_desc}）"
        )
        if dist:
            pos_desc = "、".join(f"{d['label']} {d['ratio']:.0%}" for d in dist)
            parts.append(f"正确答案位置分布：{pos_desc}，偏离均匀 {bias:.0%}")
    elif overview.get("scored_ratio") is not None:
        parts.append(f"{overview['scored_ratio']:.0%} 的条目可自动判分")

    # 重复
    if overview["duplicate_rate"] > 0:
        parts.append(f"重复率 {overview['duplicate_rate']:.1%}")

    # 质量
    parts.append(f"质量评级 {quality['grade_label']}（{quality['score']:.2f}）")
    if quality["issues"] and quality["issues"][0] != "未发现明显结构性问题":
        parts.append(f"主要问题：{quality['issues'][0]}")
    return "。".join(parts) + "。"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def build_profile(
    rows: List[Dict[str, Any]],
    model_type: str = MODEL_LLM,
    payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """由归一化后的行计算完整画像。

    rows     —— normalize_record() 的输出列表
    payloads —— 原始记录列表（字段画像用），不传则从 rows 的 payload 字段取
    """
    if not rows:
        raise ValueError("评测集为空，无法生成画像")

    total = len(rows)
    hashes = [r.get("question_hash") for r in rows if r.get("question_hash")]
    unique = len(set(hashes)) if hashes else total

    if payloads is None:
        payloads = [r.get("payload") or {} for r in rows]

    task_profile = build_task_profile(rows, model_type)
    answer_profile = build_answer_profile(rows)
    capability = build_capability(rows)
    quality = build_quality(rows, unique, total, answer_profile)
    overview = build_overview(rows, unique, model_type)

    summary = build_summary_text(
        overview, task_profile, answer_profile, capability, quality, model_type
    )

    tags = [task_profile["primary_format_label"]]
    tags += [s["label"] for s in (capability.get("subjects") or [])[:3]]
    tags += [capability["languages"][0]["label"]] if capability.get("languages") else []

    return {
        "model_type": model_type,
        "task_profile": task_profile,
        "answer_profile": answer_profile,
        "capability": capability,
        "quality": quality,
        "overview": overview,
        "schema_profile": build_schema_profile([p for p in payloads if isinstance(p, dict)]),
        "samples": build_samples(rows),
        "summary": summary,
        "tags": list(dict.fromkeys(tags))[:10],
    }