# 多模态嵌入评测执行器
#
# 流程：样本 -> 查询分组 -> 去重编码（文本/图片各只编码一次）-> 组内余弦排序
# -> 单查询指标 -> 按 subset 汇总。持久化与进度上报留给 Celery 任务层，
# 这里只负责计算，便于单测直接注入假编码器。
import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import numpy as np

from .client import MediaItem, MMEmbeddingClient
from .metrics import aggregate_metrics, evaluate_query, l2_normalize, rank_of_first_positive


@dataclass
class Candidate:
    text: Optional[str]
    image_key: Optional[str]
    label: int
    item: MediaItem = field(default_factory=MediaItem)


@dataclass
class QueryGroup:
    qid: str
    subset: str
    query_text: Optional[str]
    query_image_key: Optional[str]
    candidates: List[Candidate] = field(default_factory=list)
    query: MediaItem = field(default_factory=MediaItem)


@dataclass
class QueryOutcome:
    qid: str
    subset: str
    rank: Optional[int]
    candidate_count: int
    positive_count: int
    metrics: dict
    retrieved_top: List[dict]


def build_groups(
    samples, min_candidates: int = 2
) -> Tuple[List[QueryGroup], int, Dict[str, dict]]:
    """把落库样本按 qid 聚成候选池；候选数不足的查询跳过并计数"""
    groups: Dict[str, QueryGroup] = {}
    order: List[str] = []

    for sample in samples:
        qid = sample.qid
        if qid not in groups:
            groups[qid] = QueryGroup(
                qid=qid,
                subset=sample.subset or "未分组",
                query_text=sample.query_text,
                query_image_key=sample.query_image,
            )
            order.append(qid)
        groups[qid].candidates.append(
            Candidate(
                text=sample.target_text,
                image_key=sample.target_image,
                label=int(sample.label or 0),
            )
        )

    kept: List[QueryGroup] = []
    skipped = 0
    for qid in order:
        group = groups[qid]
        if len(group.candidates) < max(2, min_candidates):
            skipped += 1
            continue
        kept.append(group)
    return kept, skipped, subset_stats(kept)


def subset_stats(groups: List[QueryGroup]) -> Dict[str, dict]:
    stats: Dict[str, dict] = {}
    for group in groups:
        entry = stats.setdefault(group.subset, {"queries": 0, "candidates": 0})
        entry["queries"] += 1
        entry["candidates"] += len(group.candidates)
    return stats


async def materialize_images(
    groups: List[QueryGroup],
    image_loader: Callable[[str], Awaitable[bytes]],
    image_url_builder: Optional[Callable[[str], Awaitable[str]]] = None,
    concurrency: int = 8,
    load_bytes: bool = True,
) -> Dict[str, MediaItem]:
    """为分组内出现的图片 key 加载字节（可同时生成预签名 URL）

    image_transport=url 时只需预签名地址，跳过字节下载，避免整库图片白拉一遍。
    """
    needed = set()
    for group in groups:
        if group.query_image_key:
            needed.add(group.query_image_key)
        for candidate in group.candidates:
            if candidate.image_key:
                needed.add(candidate.image_key)

    semaphore = asyncio.Semaphore(concurrency)
    resolved: Dict[str, MediaItem] = {}

    async def load(key: str) -> None:
        async with semaphore:
            data = await image_loader(key) if load_bytes else None
            url = await image_url_builder(key) if image_url_builder else None
            from .media import mime_from_key

            resolved[key] = MediaItem(
                image_bytes=data, image_mime=mime_from_key(key), image_url=url
            )

    await asyncio.gather(*(load(key) for key in sorted(needed)))
    return resolved


def bind_items(groups: List[QueryGroup], images: Dict[str, MediaItem]) -> None:
    """把图片字节/URL 与文本合并成待编码的 MediaItem"""
    for group in groups:
        image = images.get(group.query_image_key) if group.query_image_key else None
        group.query = MediaItem(
            text=group.query_text,
            image_bytes=image.image_bytes if image else None,
            image_mime=image.image_mime if image else None,
            image_url=image.image_url if image else None,
        )
        for candidate in group.candidates:
            image = images.get(candidate.image_key) if candidate.image_key else None
            candidate.item = MediaItem(
                text=candidate.text,
                image_bytes=image.image_bytes if image else None,
                image_mime=image.image_mime if image else None,
                image_url=image.image_url if image else None,
            )


def item_key(item: MediaItem) -> Tuple[str, str]:
    """编码去重键：文本 + 图片内容标识（URL 或字节哈希）"""
    if item.image_url:
        image_part = f"url:{item.image_url.split('?', 1)[0]}"
    elif item.image_bytes is not None:
        image_part = f"bytes:{hashlib.sha1(item.image_bytes).hexdigest()}"
    else:
        image_part = ""
    return (item.text or "", image_part)


async def encode_groups(
    client: MMEmbeddingClient,
    groups: List[QueryGroup],
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    cancel_cb: Optional[Callable[[], Awaitable[None]]] = None,
) -> Dict[Tuple[str, str], np.ndarray]:
    """对所有 query/candidate 输入去重后统一编码"""
    unique: Dict[Tuple[str, str], MediaItem] = {}
    for group in groups:
        unique.setdefault(item_key(group.query), group.query)
        for candidate in group.candidates:
            unique.setdefault(item_key(candidate.item), candidate.item)

    keys = list(unique.keys())
    items = [unique[key] for key in keys]
    vectors = await client.embed(items, progress_cb=progress_cb, cancel_cb=cancel_cb)
    matrix = l2_normalize(np.asarray(vectors, dtype=np.float32))
    return {key: matrix[i] for i, key in enumerate(keys)}


def score_groups(
    groups: List[QueryGroup],
    vectors: Dict[Tuple[str, str], np.ndarray],
    top_k: int = 10,
) -> List[QueryOutcome]:
    outcomes: List[QueryOutcome] = []
    for group in groups:
        query_vec = vectors[item_key(group.query)]
        candidate_vecs = np.stack(
            [vectors[item_key(candidate.item)] for candidate in group.candidates]
        )
        scores = candidate_vecs @ query_vec
        labels = [candidate.label for candidate in group.candidates]
        outcomes.append(
            QueryOutcome(
                qid=group.qid,
                subset=group.subset,
                rank=rank_of_first_positive(scores, labels),
                candidate_count=len(group.candidates),
                positive_count=sum(labels),
                metrics=evaluate_query(scores, labels),
                retrieved_top=_top_candidates(group, scores, top_k),
            )
        )
    return outcomes


def _top_candidates(group: QueryGroup, scores: np.ndarray, k: int) -> List[dict]:
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")[:k]
    top: List[dict] = []
    for idx in order:
        candidate = group.candidates[int(idx)]
        top.append(
            {
                "label": candidate.label,
                "score": round(float(scores[int(idx)]), 6),
                "text": (candidate.text or "")[:200] or None,
                "image": candidate.image_key,
            }
        )
    return top


def summarize(outcomes: List[QueryOutcome]) -> Tuple[dict, Dict[str, dict]]:
    """总体 + 按 subset 汇总"""
    overall = aggregate_metrics([outcome.metrics for outcome in outcomes])
    by_subset: Dict[str, List[dict]] = {}
    for outcome in outcomes:
        by_subset.setdefault(outcome.subset, []).append(outcome.metrics)
    subset_metrics = {
        subset: aggregate_metrics(rows) for subset, rows in sorted(by_subset.items())
    }
    return overall, subset_metrics
