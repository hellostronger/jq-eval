# 多模态评测数据导入解析单测：MMEB 官方 / 通用分组 / zip
import io
import json
import zipfile

import pytest

from app.services.mm_embedding.parsing import parse_dataset_file


def _jsonl(rows):
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode("utf-8")


def test_parse_mmeb_flat_pairs_grouped_by_qid():
    raw = _jsonl(
        [
            {"qid": "q1", "qry": "a photo of a cat", "qry_image_path": "img/q1.jpg",
             "tgt": "a cat", "tgt_image_path": "img/c1.jpg", "label": 1},
            {"qid": "q1", "qry": "a photo of a cat", "qry_image_path": "img/q1.jpg",
             "tgt": "a dog", "tgt_image_path": "img/c2.jpg", "label": 0},
        ]
    )
    parsed = parse_dataset_file("mmeb.jsonl", raw)
    assert len(parsed.samples) == 2
    assert {s.qid for s in parsed.samples} == {"q1"}
    assert all(s.subset == "I→I" for s in parsed.samples)
    assert [s.label for s in parsed.samples] == [1, 0]


def test_parse_mmeb_nested_query_target_objects():
    raw = _jsonl(
        [
            {
                "qid": "q1",
                "qry": {"text": "describe", "image": "a.jpg"},
                "tgt": {"text": "caption", "image": "b.jpg"},
                "label": True,
            },
            {
                "qid": "q1",
                "qry": {"text": "describe", "image": "a.jpg"},
                "tgt": {"text": "other", "image": "c.jpg"},
                "label": False,
            },
        ]
    )
    parsed = parse_dataset_file("mmeb_nested.jsonl", raw)
    assert len(parsed.samples) == 2
    assert parsed.samples[0].query_text == "describe"
    assert parsed.samples[0].target_image_ref == "b.jpg"
    assert parsed.samples[0].label == 1
    assert parsed.samples[1].label == 0


def test_parse_pos_neg_fields_split_into_two_samples():
    raw = _jsonl(
        [
            {
                "qid": "q1",
                "qry_text": "query",
                "pos_text": "good",
                "hard_neg_text": "bad",
            }
        ]
    )
    parsed = parse_dataset_file("posneg.jsonl", raw)
    assert len(parsed.samples) == 2
    labels = {s.target_text: s.label for s in parsed.samples}
    assert labels == {"good": 1, "bad": 0}


def test_parse_generic_grouped_candidates():
    payload = [
        {
            "query_id": "g1",
            "subset": "text→image",
            "query": {"text": "red car"},
            "candidates": [
                {"image": "red.jpg", "label": 1},
                {"image": "blue.jpg", "label": 0},
            ],
        }
    ]
    parsed = parse_dataset_file("generic.json", json.dumps(payload).encode())
    assert len(parsed.samples) == 2
    assert parsed.samples[0].subset == "text→image"
    assert parsed.samples[0].target_image_ref == "red.jpg"
    assert parsed.samples[1].label == 0


def test_parse_zip_with_images_and_multiple_manifests():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "subset_a.jsonl",
            "\n".join(
                [
                    json.dumps({"qid": "a1", "qry": "q", "qry_image_path": "images/q.png", "tgt": "t", "label": 1}),
                    json.dumps({"qid": "a1", "qry": "q", "qry_image_path": "images/q.png", "tgt": "u", "label": 0}),
                ]
            ),
        )
        zf.writestr("images/q.png", b"\x89PNG\r\n\x1a\nfake")
    parsed = parse_dataset_file("bundle.zip", buf.getvalue())
    assert len(parsed.samples) == 2
    assert "images/q.png" in parsed.images
    # 无显式 subset 时用清单文件名兜底
    assert parsed.samples[0].subset == "subset_a"
    assert parsed.source_meta["format"] == "zip"


def test_parse_rejects_group_without_positive():
    raw = _jsonl(
        [
            {"qid": "q1", "qry": "q", "tgt": "a", "label": 0},
            {"qid": "q1", "qry": "q", "tgt": "b", "label": 0},
        ]
    )
    with pytest.raises(ValueError, match="正例"):
        parse_dataset_file("bad.jsonl", raw)


def test_parse_rejects_zip_slip_paths():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.jsonl", "{}")
    with pytest.raises(ValueError, match="非法路径"):
        parse_dataset_file("evil.zip", buf.getvalue())


def test_parse_requires_supported_extension():
    with pytest.raises(ValueError, match="仅支持"):
        parse_dataset_file("data.csv", b"a,b,c")
