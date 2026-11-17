# 多模态检索指标单测：口径必须与 MMEB/MIEB 一致
import numpy as np
import pytest

from app.services.mm_embedding.metrics import (
    aggregate_metrics,
    evaluate_query,
    l2_normalize,
    rank_of_first_positive,
)


def test_rank_uses_stable_order_on_ties():
    scores = np.array([0.5, 0.9, 0.9, 0.1])
    labels = [0, 0, 1, 0]
    # 同分时先出现的候选排前面 -> 正例排第 2
    assert rank_of_first_positive(scores, labels) == 2


def test_evaluate_query_metrics():
    scores = np.array([0.9, 0.8, 0.7])
    labels = [0, 1, 0]
    result = evaluate_query(scores, labels)
    assert result["recall@1"] == 0.0
    assert result["recall@5"] == 1.0
    assert result["recall@10"] == 1.0
    assert result["mrr@10"] == pytest.approx(0.5)
    # 正例在第 2 位：DCG=1/log2(3)，IDCG=1
    assert result["ndcg@10"] == pytest.approx(1 / np.log2(3), rel=1e-5)


def test_evaluate_query_multiple_positives():
    scores = np.array([0.9, 0.8, 0.7, 0.6])
    labels = [1, 0, 1, 0]
    result = evaluate_query(scores, labels)
    assert result["recall@1"] == 1.0
    assert result["mrr@10"] == 1.0
    expected_dcg = 1 + 1 / np.log2(4)
    expected_idcg = 1 + 1 / np.log2(3)
    assert result["ndcg@10"] == pytest.approx(expected_dcg / expected_idcg, rel=1e-5)


def test_evaluate_query_requires_positive():
    with pytest.raises(ValueError):
        evaluate_query(np.array([0.1, 0.2]), [0, 0])


def test_aggregate_is_macro_average():
    summary = aggregate_metrics(
        [
            {"recall@1": 1.0, "recall@5": 1.0, "mrr@10": 1.0, "ndcg@10": 1.0},
            {"recall@1": 0.0, "recall@5": 1.0, "mrr@10": 0.5, "ndcg@10": 0.5},
        ]
    )
    assert summary["query_count"] == 2
    assert summary["recall@1"] == pytest.approx(0.5)
    assert summary["mrr@10"] == pytest.approx(0.75)


def test_l2_normalize_handles_zero_vector():
    matrix = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32))
    assert np.linalg.norm(matrix[0]) == pytest.approx(1.0)
    assert np.linalg.norm(matrix[1]) == pytest.approx(0.0)
