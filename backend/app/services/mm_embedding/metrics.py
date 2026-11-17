# 多模态检索指标
#
# 口径与 MMEB/MIEB 榜单一致：每个查询在候选池内排序，
#   Recall@k —— 前 k 里是否至少有一个正例
#   MRR@10   —— 首个正例排名的倒数（排名 >10 记 0）
#   nDCG@10  —— 二值相关性下的归一化折损累计增益
# 相似度用归一化向量的点积（即余弦相似度）。
import math
from typing import Iterable, List, Optional

import numpy as np

KS = (1, 5, 10)
NDCG_K = 10
MRR_K = 10


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """按行 L2 归一化；零向量保持不变（后续相似度为 0）"""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        norm = float(np.linalg.norm(matrix))
        return matrix / norm if norm > 0 else matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def rank_of_first_positive(scores: np.ndarray, labels: Iterable[int]) -> Optional[int]:
    """返回首个正例的排名（1 起），无正例返回 None。

    同分时按候选原始顺序（stable sort），避免指标随数据行顺序漂移。
    """
    labels_arr = np.asarray(list(labels), dtype=np.int8)
    if not np.any(labels_arr == 1):
        return None
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")
    positions = np.flatnonzero(labels_arr[order] == 1)
    return int(positions[0]) + 1


def evaluate_query(scores: np.ndarray, labels: Iterable[int]) -> dict:
    labels_arr = np.asarray(list(labels), dtype=np.int8)
    n_pos = int(np.sum(labels_arr == 1))
    if n_pos == 0:
        raise ValueError("候选池内没有正例，无法计算检索指标")

    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")
    rank = rank_of_first_positive(scores, labels_arr)

    result = {}
    for k in KS:
        result[f"recall@{k}"] = 1.0 if rank is not None and rank <= k else 0.0
    result[f"mrr@{MRR_K}"] = (
        1.0 / rank if rank is not None and rank <= MRR_K else 0.0
    )

    top = order[:NDCG_K]
    gains = labels_arr[top]
    dcg = sum(
        float(gains[i]) / math.log2(i + 2) for i in range(len(gains))
    )
    ideal_positions = min(n_pos, NDCG_K)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_positions))
    result[f"ndcg@{NDCG_K}"] = dcg / idcg if idcg > 0 else 0.0
    return result


def aggregate_metrics(rows: List[dict]) -> dict:
    """宏平均：每条查询权重相同（不按候选池大小加权）"""
    if not rows:
        return {"query_count": 0}
    keys = [k for k in rows[0] if k.startswith(("recall@", "mrr@", "ndcg@"))]
    summary = {"query_count": len(rows)}
    for key in keys:
        summary[key] = round(sum(float(row[key]) for row in rows) / len(rows), 6)
    return summary
