# 评测集之间差异对比引擎
#
# 回答四个问题：
#   1. 两个集考的东西一样吗          → 分布距离（TV / JS）
#   2. 两个集的能力覆盖差多少        → 学科 Jaccard + 差集
#   3. 两个集的分数能直接比吗        → 格式兼容性判定
#   4. 两个集是不是同一批题          → 跨集污染 + 答案冲突
#
# 纯函数，无 IO。每个指标都选了可解释的口径：
#   总变差距离 TV = 0.5·Σ|p−q|   主指标，对用户说得出"题型差了 62%"
#   Jensen-Shannon                 辅助，长尾分布更平滑
#   Jaccard                        集合覆盖，可直接给差集清单
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# 参与集间对比的分布维度
DIMENSION_TASK_FORMAT = "task_format"
DIMENSION_ANSWER_TYPE = "answer_type"
DIMENSION_SUBJECT = "subject"
DIMENSION_LANGUAGE = "language"
DIMENSION_DIFFICULTY = "difficulty"

# 跨集污染：题干过短时指纹易撞，不计入重叠率
MIN_HASH_QUESTION_LEN = 10


# ---------------------------------------------------------------------------
# 距离度量
# ---------------------------------------------------------------------------
def total_variation(p: Dict[str, float], q: Dict[str, float]) -> float:
    """总变差距离：0.5·Σ|p−q|，范围 [0,1]，对称、bounded。"""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    return round(0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys), 4)


def jensen_shannon(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon 距离（log₂，取根号），范围 [0,1]。长尾分布比 TV 更平滑。"""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    m = {k: (p.get(k, 0.0) + q.get(k, 0.0)) / 2 for k in keys}

    def _kl(a: Dict[str, float], b: Dict[str, float]) -> float:
        total = 0.0
        for k, v in a.items():
            if v <= 0:
                continue
            bv = b.get(k, 0.0)
            if bv <= 0:
                continue
            total += v * math.log2(v / bv)
        return total

    js = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
    return round(math.sqrt(max(js, 0.0)), 4)


def jaccard(a: set, b: set) -> float:
    """杰卡德相似度：|A∩B| / |A∪B|。"""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return round(len(a & b) / len(union), 4)


def cosine(p: Dict[str, float], q: Dict[str, float]) -> float:
    keys = set(p) | set(q)
    dot = sum(p.get(k, 0.0) * q.get(k, 0.0) for k in keys)
    np = math.sqrt(sum(p.get(k, 0.0) ** 2 for k in keys))
    nq = math.sqrt(sum(q.get(k, 0.0) ** 2 for k in keys))
    if not np or not nq:
        return 0.0
    return round(dot / (np * nq), 4)


def jaccard_grade(value: float) -> str:
    """把 Jaccard 翻成人话。"""
    if value >= 0.8:
        return "几乎完全重合"
    if value >= 0.6:
        return "高度重合"
    if value >= 0.4:
        return "部分重合"
    if value >= 0.2:
        return "覆盖差异较大"
    return "覆盖面基本不重叠"


def tv_grade(value: float) -> str:
    if value >= 0.6:
        return "差异很大"
    if value >= 0.35:
        return "差异明显"
    if value >= 0.15:
        return "略有差异"
    return "高度一致"


# ---------------------------------------------------------------------------
# 从画像里取各维度分布
# ---------------------------------------------------------------------------
def _dist_map(items: Optional[List[Dict[str, Any]]], key: str = "key") -> Dict[str, float]:
    if not items:
        return {}
    out: Dict[str, float] = {}
    for it in items:
        k = it.get(key)
        if k:
            out[k] = float(it.get("ratio") or 0.0)
    return out


def extract_dimensions(profile: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """把一份画像拆成各维度分布，供两两对比。"""
    task = profile.get("task_profile") or {}
    cap = profile.get("capability") or {}
    return {
        DIMENSION_TASK_FORMAT: _dist_map(task.get("formats")),
        DIMENSION_ANSWER_TYPE: _dist_map(task.get("answer_types")),
        DIMENSION_SUBJECT: _dist_map(cap.get("subjects")),
        DIMENSION_LANGUAGE: _dist_map(cap.get("languages")),
        DIMENSION_DIFFICULTY: _dist_map(cap.get("difficulties")),
    }


# ---------------------------------------------------------------------------
# 格式兼容性
# ---------------------------------------------------------------------------
def check_format_compatibility(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """两个集能否直接横向比分数。

    最常见的坑：选择题算 ExactMatch，生成题要数值容差匹配，
    两者准确率不在同一量纲，混在一起排名就是错的。
    """
    a_task = a.get("task_profile") or {}
    b_task = b.get("task_profile") or {}
    a_fmt = a_task.get("primary_format")
    b_fmt = b_task.get("primary_format")
    a_label = a_task.get("primary_format_label") or a_fmt
    b_label = b_task.get("primary_format_label") or b_fmt

    reasons: List[str] = []
    if a_fmt and b_fmt and a_fmt != b_fmt:
        reasons.append(
            f"题型不同（{a_label} vs {b_label}），"
            f"判分方式不一致，准确率不在同一量纲，不能直接横向对比"
        )

    a_ans = ((a.get("answer_profile") or {}).get("choice_items") or 0)
    b_ans = ((b.get("answer_profile") or {}).get("choice_items") or 0)
    if a_ans and not b_ans:
        reasons.append(f"一方是选择题（需 ExactMatch），另一方需自由文本/数值匹配")
    elif b_ans and not a_ans:
        reasons.append(f"一方是选择题（需 ExactMatch），另一方需自由文本/数值匹配")

    a_model = a.get("model_type")
    b_model = b.get("model_type")
    if a_model and b_model and a_model != b_model:
        reasons.append(f"归属不同（{a_model} vs {b_model}），评测的是不同能力，应分开看")

    # 单题 prompt 开销差 3 倍以上，成本对比会失真
    a_tok = ((a.get("overview") or {}).get("tokens") or {}).get("avg") or 0
    b_tok = ((b.get("overview") or {}).get("tokens") or {}).get("avg") or 0
    if a_tok and b_tok:
        ratio = max(a_tok, b_tok) / max(min(a_tok, b_tok), 1)
        if ratio > 3:
            reasons.append(
                f"单题开销相差 {ratio:.1f} 倍（{a_tok} vs {b_tok} token），"
                f"成本收益不可直接比较"
            )

    return {
        "compatible": not reasons,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# 跨集污染 / 答案冲突
# ---------------------------------------------------------------------------
def detect_contamination(
    a_rows: List[Dict[str, Any]],
    b_rows: List[Dict[str, Any]],
    sample_limit: int = 20,
) -> Dict[str, Any]:
    """按题干指纹找出跨集重复题，并区分"完全重复"与"同题干不同答案"。

    必须用 question_hash（仅题干）而非 qa_hash（含答案）：
    同一知识点在 C-Eval 与 CMMLU 里选项不同，用含答案的指纹会系统性低估重叠率。
    """
    def _index(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            h = r.get("question_hash")
            if not h:
                continue
            # 题干过短的指纹易撞，剔除后再统计
            if len(r.get("question") or "") < MIN_HASH_QUESTION_LEN:
                continue
            out.setdefault(h, r)
        return out

    a_idx, b_idx = _index(a_rows), _index(b_rows)
    overlap = set(a_idx) & set(b_idx)

    conflicts: List[Dict[str, Any]] = []
    for h in overlap:
        ra, rb = a_idx[h], b_idx[h]
        if (ra.get("qa_hash") or "") != (rb.get("qa_hash") or ""):
            conflicts.append({
                "question": (ra.get("question") or "")[:300],
                "a_answer": ",".join(ra.get("answer_labels") or []) or (ra.get("answer_text") or "")[:80],
                "b_answer": ",".join(rb.get("answer_labels") or []) or (rb.get("answer_text") or "")[:80],
                "a_subject": ra.get("subject"),
                "b_subject": rb.get("subject"),
            })

    b_total = max(len(b_idx), 1)
    return {
        "overlap_count": len(overlap),
        "overlap_rate": round(len(overlap) / b_total, 4),
        "a_compared": len(a_idx),
        "b_compared": len(b_idx),
        "answer_conflicts": len(conflicts),
        "conflicts": conflicts[:sample_limit],
        "min_question_len": MIN_HASH_QUESTION_LEN,
    }


# ---------------------------------------------------------------------------
# 两两对比
# ---------------------------------------------------------------------------
def compare_pair(
    a: Dict[str, Any],
    b: Dict[str, Any],
    a_rows: Optional[List[Dict[str, Any]]] = None,
    b_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """对比两份画像。a/b 传 profile 的 JSON 合并结果。"""
    dims_a = extract_dimensions(a)
    dims_b = extract_dimensions(b)

    per_dimension = []
    for dim in (DIMENSION_TASK_FORMAT, DIMENSION_ANSWER_TYPE, DIMENSION_SUBJECT,
                DIMENSION_LANGUAGE, DIMENSION_DIFFICULTY):
        pa, pb = dims_a.get(dim, {}), dims_b.get(dim, {})
        if not pa or not pb:
            continue
        tv = total_variation(pa, pb)
        js = jensen_shannon(pa, pb)
        per_dimension.append({
            "dimension": dim,
            "tv_distance": tv,
            "js_distance": js,
            "cosine": cosine(pa, pb),
            "tv_grade": tv_grade(tv),
            "a_dist": pa,
            "b_dist": pb,
        })

    a_subj = set(dims_a.get(DIMENSION_SUBJECT, {}))
    b_subj = set(dims_b.get(DIMENSION_SUBJECT, {}))
    subject_jac = jaccard(a_subj, b_subj)

    compat = check_format_compatibility(a, b)

    result: Dict[str, Any] = {
        "a_id": a.get("id"),
        "b_id": b.get("id"),
        "a_name": a.get("name"),
        "b_name": b.get("name"),
        "a_model_type": a.get("model_type"),
        "b_model_type": b.get("model_type"),
        "subject_jaccard": subject_jac,
        "subject_jaccard_grade": jaccard_grade(subject_jac),
        "only_in_a_subjects": sorted(a_subj - b_subj)[:50],
        "only_in_b_subjects": sorted(b_subj - a_subj)[:50],
        "shared_subjects": len(a_subj & b_subj),
        "per_dimension": per_dimension,
        "format_compatible": compat["compatible"],
        "compat_reasons": compat["reasons"],
    }

    # 题型维度的总体距离提升到顶层，方便前端直接展示
    for d in per_dimension:
        if d["dimension"] == DIMENSION_TASK_FORMAT:
            result["tv_distance"] = d["tv_distance"]
            result["js_distance"] = d["js_distance"]
            result["tv_grade"] = d["tv_grade"]
            break
    else:
        result["tv_distance"] = 0.0
        result["js_distance"] = 0.0
        result["tv_grade"] = "无题型分布"

    if a_rows and b_rows:
        result["contamination"] = detect_contamination(a_rows, b_rows)

    return result


# ---------------------------------------------------------------------------
# 多集对比
# ---------------------------------------------------------------------------
def build_coverage_matrix(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """学科 × 集 的覆盖矩阵（用于热力图）。"""
    all_subjects: List[str] = []
    per_set: List[Dict[str, float]] = []
    for p in profiles:
        dims = extract_dimensions(p)
        subj = dims.get(DIMENSION_SUBJECT, {})
        per_set.append(subj)
        for s in subj:
            if s not in all_subjects:
                all_subjects.append(s)
    all_subjects.sort()
    return {
        "subjects": all_subjects[:100],
        "matrix": [
            [round(per_set[i].get(s, 0.0), 4) for s in all_subjects[:100]]
            for i in range(len(per_set))
        ],
        "truncated": len(all_subjects) > 100,
    }


def build_recommendations(
    comparisons: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
) -> List[str]:
    """基于对比结果给出可执行建议（规则生成，保证可复现，不用 LLM）。"""
    recs: List[str] = []
    if not comparisons:
        return ["只选择了一个评测集，无法进行集间对比；加入至少两个集可查看差异"]

    # 1) 不可直接对比的先警示
    for c in comparisons:
        if not c.get("format_compatible"):
            reasons = "；".join(c.get("compat_reasons") or [])
            recs.append(
                f"「{c.get('a_name')}」与「{c.get('b_name')}」不可直接横向对比：{reasons}。"
                f"若要合并看分数，需先用同一套提示词与判分器重跑。"
            )

    # 2) 学科覆盖差异 → 互补使用
    for c in comparisons:
        only_a = c.get("only_in_a_subjects") or []
        only_b = c.get("only_in_b_subjects") or []
        jac = c.get("subject_jaccard") or 0
        if only_a and only_b:
            recs.append(
                f"「{c.get('a_name')}」独有 {len(only_a)} 个学科、"
                f"「{c.get('b_name')}」独有 {len(only_b)} 个学科"
                f"（Jaccard {jac:.0%}，{c.get('subject_jaccard_grade')}）。"
                f"两者互补：用两个集分别测能覆盖更完整的能力面，也更难被单一数据集过拟合。"
            )
        elif jac >= 0.8 and only_a:
            recs.append(
                f"「{c.get('a_name')}」与「{c.get('b_name')}」学科覆盖高度重合"
                f"（Jaccard {jac:.0%}），选其一即可，另选一个覆盖差异更大的集收益更高。"
            )

    # 3) 污染与冲突
    for c in comparisons:
        cont = c.get("contamination") or {}
        conflicts = cont.get("answer_conflicts") or 0
        if conflicts:
            recs.append(
                f"「{c.get('a_name')}」与「{c.get('b_name')}」有 {conflicts} 道同题干不同答案的冲突题，"
                f"至少一方存在标注错误，必须先人工复核，否则两边的分数都不可信。"
            )
        elif cont.get("overlap_count"):
            rate = cont.get("overlap_rate") or 0
            recs.append(
                f"两个集有 {cont.get('overlap_count')} 道重复题（重叠率 {rate:.1%}）。"
                f"若模型已在其中一个集上训练或调过参，另一集的重复题应先剔除再测，"
                f"否则分数会因数据泄漏而虚高。"
            )

    # 4) 选某类目标时的建议
    for p in profiles:
        tp = p.get("task_profile") or {}
        if tp.get("mismatch"):
            recs.append(f"「{p.get('name')}」{tp['mismatch']}，建议先确认归类是否正确。")

    return recs


def compare_profiles(
    profiles: List[Dict[str, Any]],
    rows_by_id: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """N 个评测集的完整对比报告。

    profiles  —— 每项含 id/name/model_type/overview/task_profile/answer_profile/capability
    rows_by_id —— 可选，提供样本行以启用污染检测
    """
    rows_by_id = rows_by_id or {}
    comparisons: List[Dict[str, Any]] = []
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            a, b = profiles[i], profiles[j]
            comparisons.append(compare_pair(
                a, b,
                rows_by_id.get(a.get("id")),
                rows_by_id.get(b.get("id")),
            ))

    return {
        "profiles": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "model_type": p.get("model_type"),
                "benchmark_key": p.get("benchmark_key"),
                "total_samples": (p.get("overview") or {}).get("total"),
                "primary_format": (p.get("task_profile") or {}).get("primary_format"),
                "primary_format_label": (p.get("task_profile") or {}).get("primary_format_label"),
            }
            for p in profiles
        ],
        "pairwise": comparisons,
        "coverage_matrix": build_coverage_matrix(profiles),
        "recommendations": build_recommendations(comparisons, profiles),
    }