"""检索轨迹（trace）的收纳与分析。

为什么需要：调用结果原先只落 contexts / retrieval_ids，被测系统回传的通道级信息
（向量、全文、图各自排了哪些页，树定位跑了几轮、有没有掉进兜底取样）在写库时就丢了。
于是 badcase 归因只能得到「漏召」一个结论，而这至少分两种：
  - 各通道都没捞到 → 索引/分片/query 理解的问题；
  - 某一路捞到了、最终列表里却没有 → 融合配比或重排的问题。
两者要改的地方完全不同，光看 retrieval_ids 分不出来。

这里做两件事：落库前把轨迹收拢到可控体积（一次批次几千条，原始 trace 能到 MB 级），
以及分析时按 gold 在轨迹里的位置判定「断在哪一步」。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# 单条 trace 的收纳上限：够分析用，又不至于把结果表撑爆
CHANNEL_KEEP = 40
ROUNDS_KEEP = 8
IDS_IN_ROUND_KEEP = 20
TEXT_KEEP = 300
PAGES_KEEP = 60
BUDGET_BYTES = 48 * 1024

# 原样保留的标量/小字段
_SCALAR_KEYS = ("mode", "fallback", "citation_source", "answer_status", "doc_id", "unavailable")
_LIST_KEYS = ("read_pages", "read_nodes", "wiki_pages", "graph_entities", "terms", "anchors")
# 通道专属的规模计数（lexical_pool_total、rounds_total 等）：不知道被测系统会回传
# 什么字段，但"这一路到底给了多少候选"是判零候选还是判截断的根据，白名单会把它丢掉
_EXTRA_SCALAR_MAX = 12
# 明显是正文/答案的字段：轨迹里不该顺带存生成内容，体积大且与分析无关
_CONTENT_KEYS = frozenset({"answer", "context", "contexts", "text", "content",
                          "output", "response", "question", "query"})


def _shrink_ids(values: Any, keep: int) -> List[Any]:
    if not isinstance(values, list):
        return []
    return values[:keep]


def compact_trace(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把被测系统回传的检索轨迹收拢成可落库的小对象；无轨迹返回 None。

    保留的是"能不能归因"所需的结构，而不是原文：通道排序、定位轮次、兜底标记。
    超出上限的部分记录数量（*_total）并写进 truncated，避免分析时把截断当成"没有"。
    """
    if not isinstance(raw, dict) or not raw:
        return None

    out: Dict[str, Any] = {}
    for key in _SCALAR_KEYS:
        if raw.get(key) not in (None, "", {}, []):
            out[key] = raw[key]

    channels = raw.get("channels")
    if isinstance(channels, dict):
        out["channels"] = {
            name: _shrink_ids(ids, CHANNEL_KEEP)
            for name, ids in channels.items()
            if isinstance(ids, list)
        }
        out["channels_total"] = {
            name: len(ids) for name, ids in channels.items() if isinstance(ids, list)
        }

    rounds = raw.get("rounds")
    if isinstance(rounds, list) and rounds:
        slim = []
        for rnd in rounds[:ROUNDS_KEEP]:
            if not isinstance(rnd, dict):
                continue
            reason = str(rnd.get("reason") or "")
            slim.append({
                "round": rnd.get("round"),
                "expand": _shrink_ids(rnd.get("expand"), IDS_IN_ROUND_KEEP),
                "read": _shrink_ids(rnd.get("read"), IDS_IN_ROUND_KEEP),
                "attempts": rnd.get("attempts"),
                "reason": reason[:TEXT_KEEP],
            })
        out["rounds"] = slim
        out["rounds_total"] = len(rounds)

    for key in _LIST_KEYS:
        value = raw.get(key)
        if isinstance(value, list) and value:
            out[key] = _shrink_ids(value, PAGES_KEEP)
            out[f"{key}_total"] = len(value)

    lexical = raw.get("lexical")
    if isinstance(lexical, dict):
        # 词面命中只留规模，不留分词细节（terms/groups 动辄上百条）
        out["lexical"] = {
            k: (len(v) if isinstance(v, list) else v)
            for k, v in lexical.items()
            if k in ("terms", "groups", "pages", "nodes")
        }

    verification = raw.get("verification")
    if isinstance(verification, dict):
        out["verification"] = verification

    # 通道专属的规模计数：词法路的 lexical_pool_total、图路的 entity_count 等
    # 都是几个数字，留着才能区分"这一路压根没候选"和"候选被截断"。
    # 只在确实有通道结构时收，否则 {"answer": "..."} 这种无轨迹响应会被当成轨迹留下
    kept = 0
    if out.get("channels"):
        for key, value in raw.items():
            if key in out or key in ("channels", "rounds", "lexical", "verification") \
                    or key in _CONTENT_KEYS:
                continue
            if isinstance(value, bool) or isinstance(value, (int, float)):
                out[key] = value
                kept += 1
            elif isinstance(value, str) and len(value) <= 60:
                out[key] = value
                kept += 1
            if kept >= _EXTRA_SCALAR_MAX:
                break

    # 体积兜底：真实批次里一页正文摘要偶尔会把 trace 撑到几百 KB。
    # 结构必须保持不变（channels 仍是通道名 -> id 列表），否则分析层会把
    # "被截断" 当成 "没轨迹"，归因直接退回 no_trace，比少存几个 id 糟糕得多。
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > BUDGET_BYTES:
        slim = {
            "truncated": "trace 超过单条体积上限，通道排序只留前 10",
            "mode": out.get("mode"),
            "fallback": out.get("fallback"),
            "channels": {
                name: ids[:10] for name, ids in (out.get("channels") or {}).items()
            },
            "channels_total": out.get("channels_total"),
            "rounds": out.get("rounds", [])[:3],
        }
        # 规模计数本来就是几个数字，超预算时没必要一起丢——丢了就等于
        # "这一路给了多少候选"又查不出来了
        slim.update({
            k: v for k, v in out.items()
            if k not in slim and isinstance(v, (int, float, bool))
        })
        out = slim

    return out or None


def channel_rank_of(gold_ids: List[str], channels: Dict[str, Any]) -> Dict[str, int]:
    """gold 在各召回通道里的最好名次（没有就是没被这一路捞回来）。"""
    ranks: Dict[str, int] = {}
    for name, ids in (channels or {}).items():
        if not isinstance(ids, list):
            continue
        wanted = {str(g) for g in gold_ids}
        for position, pid in enumerate(ids, start=1):
            if str(pid) in wanted:
                ranks[name] = position
                break
    return ranks


def retrieval_step(item: Dict[str, Any]) -> str:
    """一条样本的检索断点判定，供 badcase 分步归因。

    - no_trace             被测系统没回传轨迹（老接入），无法下钻
    - no_gold              没有 gold，判不了
    - channel_all_miss     各通道都没捞到 gold → 索引/分片/query 理解层
    - lost_in_truncation   gold 在通道里排在最终列表长度之外 → 截断，改 top-k
    - lost_in_fusion       gold 在通道里本就靠前、却被融合挤出 → 融合配比/重排
    - gold_in_final        最终列表里有 → 检索没问题，往下游看

    把截断从融合里拆出来是必要的：实测单通道 vector 路被判成 lost_in_fusion 的
    样本，gold 在通道里排第 29/33，而最终列表只有 20 条 —— 按融合调配比去改不会
    有任何收益，真正该动的是 top-k。
    """
    gold = [str(g) for g in (item.get("target_chunk_ids") or [])]
    if not gold:
        return "no_gold"
    trace = item.get("trace") or {}
    channels = trace.get("channels") or {}
    final_ids = {str(r) for r in (item.get("retrieval_ids") or [])}
    if final_ids & set(gold):
        return "gold_in_final"
    if not channels:
        return "no_trace"
    ranks = channel_rank_of(gold, channels)
    if not ranks:
        return "channel_all_miss"
    # 通道名次落在最终窗口之外 = 压根没进入被排序/融合的那批候选
    if min(ranks.values()) > len(final_ids):
        return "lost_in_truncation"
    return "lost_in_fusion"


RETRIEVAL_STEPS = (
    "gold_in_final", "lost_in_fusion", "lost_in_truncation",
    "channel_all_miss", "no_trace", "no_gold",
)


def _ratio(part: int, whole: int) -> Optional[float]:
    if not whole:
        return None
    return round(part / whole, 4)


def analyze_retrieval_traces(items: List[Dict[str, Any]], top_k: int = 10) -> Dict[str, Any]:
    """按通道统计召回质量，并给出"漏在哪一步"的分布。

    这是把 badcase 从「漏召 N 条」推进到「全文通道能捞到、融合后没了」的关键：
    前者只能说检索差，后者直接指向 RRF 配比/重排，两者改法不同。
    只统计有轨迹的样本，coverage 用来提醒"多少条根本没轨迹"。
    """
    traced = [it for it in items if (it.get("trace") or {}).get("channels")]
    steps: Dict[str, int] = {name: 0 for name in RETRIEVAL_STEPS}
    channels: Dict[str, Dict[str, Any]] = {}

    for item in items:
        steps[retrieval_step(item)] += 1
        gold = [str(g) for g in (item.get("target_chunk_ids") or [])]
        if not gold:
            continue
        trace_channels = (item.get("trace") or {}).get("channels") or {}
        for name, ids in trace_channels.items():
            entry = channels.setdefault(name, {
                "samples": 0, "hit": 0, "hit_at_k": 0, "recall_sum": 0.0, "first_ranks": [],
            })
            entry["samples"] += 1
            ordered = [str(pid) for pid in (ids or [])]
            wanted = set(gold)
            got = [pid for pid in ordered if pid in wanted]
            if got:
                entry["hit"] += 1
                entry["first_ranks"].append(min(ordered.index(pid) for pid in got) + 1)
            if any(pid in wanted for pid in ordered[:top_k]):
                entry["hit_at_k"] += 1
            entry["recall_sum"] += len(set(got)) / len(wanted)

    per_channel = {}
    for name, entry in channels.items():
        n = entry["samples"]
        ranks = entry["first_ranks"]
        per_channel[name] = {
            "samples": n,
            "hit_rate": _ratio(entry["hit"], n),
            f"hit@{top_k}": _ratio(entry["hit_at_k"], n),
            "recall": round(entry["recall_sum"] / n, 4) if n else None,
            "mean_first_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        }

    retrievable = (steps["gold_in_final"] + steps["lost_in_fusion"]
                   + steps["lost_in_truncation"] + steps["channel_all_miss"])
    best_channel = None
    scored = {n: c[f"hit@{top_k}"] for n, c in per_channel.items() if c[f"hit@{top_k}"]}
    if scored:
        best_channel = max(scored, key=scored.get)

    return {
        "coverage": {
            "total": len(items),
            "with_channels": len(traced),
            "ratio": _ratio(len(traced), len(items)),
        },
        "top_k": top_k,
        "channels": per_channel,
        "best_channel": best_channel,
        "step_counts": steps,
        # 某一路已经捞到 gold、最终列表却没有了 → 问题在融合/重排，不在索引
        "fusion_loss_rate": _ratio(steps["lost_in_fusion"], retrievable),
        # gold 在通道里但排在最终窗口之外 → 是截断，改 top-k 才有效，改配比没用
        "truncation_loss_rate": _ratio(steps["lost_in_truncation"], retrievable),
        # 所有通道都找不到 gold → 才轮到动分片、索引或 query 理解
        "all_channel_miss_rate": _ratio(steps["channel_all_miss"], retrievable),
    }

