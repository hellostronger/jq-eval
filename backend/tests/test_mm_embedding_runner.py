# 多模态评测执行器单测：分组 / 去重编码 / 排序指标
import pytest

from app.services.mm_embedding.runner import (
    bind_items,
    build_groups,
    encode_groups,
    materialize_images,
    score_groups,
    summarize,
)


class FakeClient:
    image_transport = "data_url"

    def __init__(self, vectors):
        self.vectors = vectors
        self.encoded_items = []

    async def embed(self, items, progress_cb=None, cancel_cb=None):
        self.encoded_items.extend(items)
        result = [self.vectors.get(item.text, [0.0, 0.0]) for item in items]
        if progress_cb:
            await progress_cb(len(result), len(items))
        return result


class Sample:
    def __init__(self, qid, subset, query_text, target_text, label,
                 query_image=None, target_image=None):
        self.qid = qid
        self.subset = subset
        self.query_text = query_text
        self.query_image = query_image
        self.target_text = target_text
        self.target_image = target_image
        self.label = label


@pytest.mark.asyncio
async def test_grouping_encoding_and_metrics():
    samples = [
        Sample("q1", "T→T", "q1", "good", 1),
        Sample("q1", "T→T", "q1", "bad", 0),
        Sample("q2", "T→T", "q2", "pos2", 1),
        Sample("q2", "T→T", "q2", "neg2", 0),
    ]
    groups, skipped, stats = build_groups(samples)
    assert skipped == 0
    assert stats == {"T→T": {"queries": 2, "candidates": 4}}

    images = await materialize_images(groups, image_loader=_missing_image)
    bind_items(groups, images)

    client = FakeClient(
        {
            "q1": [1.0, 0.0],
            "good": [1.0, 0.0],
            "bad": [0.0, 1.0],
            "q2": [1.0, 0.0],
            "pos2": [0.6, 0.8],
            "neg2": [1.0, 0.0],
        }
    )
    vectors = await encode_groups(client, groups)
    outcomes = score_groups(groups, vectors, top_k=10)

    by_qid = {outcome.qid: outcome for outcome in outcomes}
    assert by_qid["q1"].rank == 1
    assert by_qid["q1"].metrics["recall@1"] == 1.0
    assert by_qid["q2"].rank == 2
    assert by_qid["q2"].metrics["recall@1"] == 0.0
    assert by_qid["q2"].metrics["mrr@10"] == pytest.approx(0.5)
    assert by_qid["q2"].retrieved_top[0]["label"] == 0

    overall, subsets = summarize(outcomes)
    assert overall["query_count"] == 2
    assert overall["recall@1"] == pytest.approx(0.5)
    assert overall["mrr@10"] == pytest.approx(0.75)
    assert subsets["T→T"]["query_count"] == 2


@pytest.mark.asyncio
async def test_dedupes_identical_items_before_encoding():
    samples = [
        Sample("q1", "T→T", "same query", "same target", 1),
        Sample("q1", "T→T", "same query", "other", 0),
        Sample("q2", "T→T", "same query", "same target", 1),
        Sample("q2", "T→T", "same query", "other2", 0),
    ]
    groups, _, _ = build_groups(samples)
    images = await materialize_images(groups, image_loader=_missing_image)
    bind_items(groups, images)

    client = FakeClient({"same query": [1.0, 0.0], "same target": [1.0, 0.0]})
    await encode_groups(client, groups)
    # q1/q2 的查询文本相同、q1/q2 的正例也相同 -> 唯一输入 4 个而不是 6 个
    assert len(client.encoded_items) == 4
    assert sum(1 for item in client.encoded_items if item.text == "same query") == 1


def test_skips_queries_with_single_candidate():
    samples = [Sample("lonely", "T→T", "q", "a", 1)]
    groups, skipped, _ = build_groups(samples)
    assert groups == []
    assert skipped == 1


async def _missing_image(key):
    raise AssertionError(f"没有图片时应不加载：{key}")
