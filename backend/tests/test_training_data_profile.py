# 训练数据画像测试
#
# 用例覆盖：真实 UltraData 形态的格式识别/归一化、画像指标计算、
# UltraData 目录 md 容错解析，以及「上传 → 落库 → 画像 → 明细 → 删除」闭环。
import io
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Dataset, TrainingDataProfile, TrainingDataRecord
from app.models.dataset import QARecord
from app.services.training_data.normalize import (
    FORMAT_AGENT,
    FORMAT_CHAT,
    FORMAT_PREFERENCE,
    FORMAT_PRETRAIN,
    FORMAT_QA,
    FORMAT_SFT,
    detect_format,
    normalize_record,
)
from app.services.training_data.profiling import build_profile, build_schema_profile
from app.services.training_data.ultradata import list_samples, parse_dataset_md

# ---- 真实 UltraData 样本形态（与 backend/app/data/ultradata_samples 对齐） ----
SFT = {
    "task": "Coding",
    "dataset": "codecontest",
    "instruction": "Write Python code to solve the task.",
    "response": "Step 1: analyze the problem...",
    "id": "abc_1_1",
    "parent_id": "abc",
}
CHAT = {"id": "0", "data": ["How to run?", "Use python app.py", "thanks", "np"]}
PREFERENCE = {
    "source": "evol_instruct",
    "instruction": "Write a C++ program that checks borders.",
    "models": ["alpaca-7b", "gpt-4"],
    "completions": [
        {"overall_score": 4.0, "response": "Here is the code...", "model": "gpt-4"},
        {"overall_score": 2.0, "response": "Sure...", "model": "alpaca-7b"},
    ],
    "correct_answers": ["None"],
    "incorrect_answers": ["None"],
}
AGENT = {
    "uuid": "Code_Agent_000001",
    "messages": [
        '{"role":"system","content":"You are a coding agent."}',
        '{"role":"user","content":"list files"}',
        '{"role":"assistant","content":"running ls"}',
        '{"role":"tool","content":"a.py b.py"}',
    ],
    "tools": [{"type": "function", "function": {"name": "shell", "description": "run cmd"}}],
    "source": "codex-like-codex.jsonl",
    "domain": "Code_Agent",
}
PRETRAIN = {"content": "An ST-elevation myocardial infarction ...", "score": "0.8745", "source": "FineWeb"}
PRETRAIN_NO_SCORE = {"text": "plain corpus text without any score column"}
QA = {"question": "What is RAG?", "answer": "Retrieval augmented generation", "ground_truth": "RAG"}


# ---------------------------------------------------------------------------
# 归一化 / 格式识别
# ---------------------------------------------------------------------------
def test_detect_format_real_ultradata_shapes():
    assert detect_format(SFT) == FORMAT_SFT
    assert detect_format(CHAT) == FORMAT_CHAT
    assert detect_format(PREFERENCE) == FORMAT_PREFERENCE
    assert detect_format(AGENT) == FORMAT_AGENT
    assert detect_format(PRETRAIN) == FORMAT_PRETRAIN
    assert detect_format(QA) == FORMAT_QA


def test_normalize_chat_uses_alternating_roles():
    row = normalize_record(CHAT)
    assert row["format"] == FORMAT_CHAT
    assert [m["role"] for m in row["messages"]] == ["user", "assistant", "user", "assistant"]
    assert row["turn_count"] == 4
    assert row["char_length"] > 0
    assert row["language"] == "en"


def test_normalize_agent_parses_json_messages_and_tools():
    row = normalize_record(AGENT)
    assert row["format"] == FORMAT_AGENT
    assert row["has_tools"] is True
    assert row["turn_count"] == 4
    assert row["messages"][0]["role"] == "system"
    assert row["messages"][-1]["role"] == "tool"
    # 领域标签既取数据自带 domain，也有关键词规则兜底
    assert "Code_Agent" in row["labels"] or "代码" in row["labels"]
    assert row["payload"]["tools"][0]["function"]["name"] == "shell"


def test_normalize_score_scales_to_unit_interval():
    """不同数据集量纲不一（0-1 / 1-5 / 1-10），统一到 0-1"""
    assert normalize_record(PRETRAIN)["score"] == pytest.approx(0.8745)
    assert normalize_record(PREFERENCE)["score"] == pytest.approx(0.6)  # (4+2)/2 /5
    assert normalize_record({"score": 8.5})["score"] == pytest.approx(0.85)
    assert normalize_record(PRETRAIN_NO_SCORE)["score"] is None


def test_duplicate_hash_covers_full_content():
    """同一 instruction 的多个 response 不应被判为重复"""
    a = normalize_record({**SFT, "response": "answer one"}, seq=0)
    b = normalize_record({**SFT, "response": "answer two"}, seq=1)
    assert a["content_hash"] != b["content_hash"]
    c = normalize_record({**SFT, "response": "answer one"}, seq=2)
    assert a["content_hash"] == c["content_hash"]


def test_normalize_non_dict_records():
    """裸字符串样本归一化为 pretrain（content 字段）"""
    row = normalize_record("just a string", seq=0)
    assert row["format"] == FORMAT_PRETRAIN
    assert row["text"] == "just a string"
    assert row["char_length"] > 0


def test_normalize_csv_style_flat_strings():
    """CSV 导入进来全是字符串：question/answer 应识别为 QA"""
    row = normalize_record({"question": "问题", "answer": "答案", "difficulty": "easy"})
    assert row["format"] == FORMAT_QA
    assert row["language"] == "zh"


# ---------------------------------------------------------------------------
# 画像指标
# ---------------------------------------------------------------------------
def _rows(*records):
    return [normalize_record(r, i) for i, r in enumerate(records)]


def test_build_profile_distributions_and_quality():
    rows = _rows(SFT, SFT, CHAT, PREFERENCE, AGENT, PRETRAIN, PRETRAIN_NO_SCORE, QA)
    payload = [r["payload"] for r in rows]
    profile = build_profile(rows, payloads=payload)

    assert profile["total"] == 8
    assert profile["unique"] == 7
    assert profile["duplicate_rate"] == pytest.approx(1 / 8)

    fmt_keys = {f["key"] for f in profile["classification"]["formats"]}
    assert fmt_keys == {FORMAT_SFT, FORMAT_CHAT, FORMAT_PREFERENCE,
                        FORMAT_AGENT, FORMAT_PRETRAIN, FORMAT_QA}
    for item in profile["classification"]["formats"]:
        assert 0 < item["ratio"] <= 1

    assert profile["classification"]["level"] in {"L1", "L2", "L3", "L4"}
    assert profile["overview"]["char_length"]["max"] >= profile["overview"]["char_length"]["avg"]
    assert profile["overview"]["tokens"]["total"] > 0
    assert profile["quality"]["grade"] in {"excellent", "good", "acceptable", "poor"}
    assert profile["quality"]["issues"]
    assert len(profile["samples"]) == 8 or len(profile["samples"]) == 5
    assert profile["schema_profile"], "字段画像不应为空"


def test_build_profile_flags_duplicates_and_empty():
    rows = _rows(PRETRAIN, dict(PRETRAIN), {"content": ""})
    profile = build_profile(rows, payloads=[r["payload"] for r in rows])
    assert profile["total"] == 3
    assert profile["duplicate_rate"] > 0
    assert profile["quality"]["empty_rate"] > 0
    assert any("重复" in issue for issue in profile["quality"]["issues"])


def test_schema_profile_coverage_and_example():
    schema = build_schema_profile([{"a": 1, "b": "x"}, {"a": 2, "b": ""}, {"a": 3}])
    by_name = {f["name"]: f for f in schema}
    assert by_name["a"]["coverage"] == 1.0
    assert by_name["b"]["coverage"] == pytest.approx(0.333, abs=0.01)
    assert by_name["a"]["types"] == {"integer": 3}
    assert by_name["b"]["example"] == "x"


def test_length_buckets_cover_all_samples():
    rows = _rows(
        {"text": "s" * 10},
        {"text": "s" * 100},
        {"text": "s" * 500},
        {"text": "s" * 2000},
        {"text": "s" * 5000},
    )
    profile = build_profile(rows)
    buckets = profile["classification"]["length_buckets"]
    assert sum(b["count"] for b in buckets) == 5
    assert {b["key"] for b in buckets} == {"0-64", "64-256", "256-1k", "1k-4k", "4k+"}


# ---------------------------------------------------------------------------
# UltraData 目录解析
# ---------------------------------------------------------------------------
def test_parse_dataset_md_strict_json():
    md = json.dumps({"id": "UltraChat", "name": "UltraChat", "level": "L3", "tags": ["SFT"]})
    parsed = parse_dataset_md(md)
    assert parsed["level"] == "L3"
    assert parsed["tags"] == ["SFT"]


def test_parse_dataset_md_tolerates_js_object_literal():
    """真实目录里 md 历史数据是 JS 字面量：裸键名 + 单引号 + 尾逗号"""
    md = """  {
    id: 'UltraChat',
    name: 'UltraChat',
    level: 'L3',
    tags: ['英文', 'SFT'],
    license: 'MIT',
    links: { "hf": 'https://huggingface.co/datasets/stingning/ultrachat' },
    downloads: 468,
  }"""
    parsed = parse_dataset_md(md)
    assert parsed["id"] == "UltraChat"
    assert parsed["tags"] == ["英文", "SFT"]
    assert parsed["license"] == "MIT"
    assert parsed["downloads"] == 468


def test_parse_dataset_md_garbage_returns_empty():
    assert parse_dataset_md("not an object at all") == {}
    assert parse_dataset_md(None) == {}
    assert parse_dataset_md({"already": "dict"}) == {"already": "dict"}


def test_local_samples_registered():
    samples = list_samples()
    assert len(samples) >= 10
    for s in samples:
        assert s["available"], f"样例 {s['key']} 文件缺失"
        assert s["rows"] > 0
        assert s["level"].startswith("L")


# ---------------------------------------------------------------------------
# API 闭环
# ---------------------------------------------------------------------------
def _upload_file(records, name="data.jsonl"):
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    return {"file": (name, io.BytesIO(payload.encode("utf-8")), "application/jsonl")}


@pytest.mark.asyncio
async def test_upload_then_profile_roundtrip(client: AsyncClient, db_session, sample_dataset: Dataset):
    """上传 → 训练样本落库 → 生成画像 → 明细/列表/删除"""
    records = [SFT, CHAT, PREFERENCE, AGENT, PRETRAIN, QA] * 3
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import", files=_upload_file(records)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["training_records"] == len(records)

    # 训练样本已落库（原始 payload 完整保留）
    stored = (await db_session.execute(
        select(TrainingDataRecord).where(TrainingDataRecord.dataset_id == sample_dataset.id)
    )).scalars().all()
    assert len(stored) == len(records)
    assert any(r.format == FORMAT_AGENT for r in stored)
    assert all(isinstance(r.payload, dict) and r.payload for r in stored)

    # 生成画像（样本量小，同步算完返回 completed）
    resp = await client.post("/api/v1/training-data-profiles", json={"dataset_id": str(sample_dataset.id)})
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    assert profile["status"] == "completed"
    assert profile["total_samples"] == len(records)
    assert profile["overview"]["total"] == len(records)
    assert {f["key"] for f in profile["classification"]["formats"]} >= {FORMAT_SFT, FORMAT_AGENT}
    assert profile["schema_profile"]
    assert profile["quality"]["issues"]
    assert profile["level"].startswith("L")
    profile_id = profile["id"]

    # 列表 / 详情 / 状态
    resp = await client.get("/api/v1/training-data-profiles")
    assert resp.status_code == 200
    assert any(p["id"] == profile_id for p in resp.json())

    resp = await client.get(f"/api/v1/training-data-profiles/{profile_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    resp = await client.get(f"/api/v1/training-data-profiles/{profile_id}/status")
    assert resp.status_code == 200
    assert resp.json()["progress"] == 100

    # 样本明细：分页 + 按格式过滤
    resp = await client.get(f"/api/v1/training-data-profiles/{profile_id}/records", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(records)
    assert len(body["records"]) == 5
    resp = await client.get(
        f"/api/v1/training-data-profiles/{profile_id}/records", params={"format": FORMAT_AGENT}
    )
    assert resp.json()["total"] == 3  # 18 条中 AGENT 出现 3 次

    # 重跑画像
    resp = await client.post(f"/api/v1/training-data-profiles/{profile_id}/run")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 删除画像（数据集与样本不受影响）
    resp = await client.delete(f"/api/v1/training-data-profiles/{profile_id}")
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/training-data-profiles/{profile_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_profile_from_legacy_qa_only_dataset(client: AsyncClient, db_session, sample_dataset: Dataset):
    """画像功能上线前导入的数据集只有 qa_records，也要能出画像（现场归一化）"""
    db_session.add(QARecord(dataset_id=sample_dataset.id, question="Q1", answer="A1"))
    db_session.add(QARecord(dataset_id=sample_dataset.id, question="Q2", answer="A2"))
    await db_session.commit()

    resp = await client.post("/api/v1/training-data-profiles", json={"dataset_id": str(sample_dataset.id)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["total_samples"] == 2
    assert body["classification"]["formats"][0]["key"] == FORMAT_QA


@pytest.mark.asyncio
async def test_profile_empty_dataset_returns_400(client: AsyncClient, sample_dataset: Dataset):
    resp = await client.post("/api/v1/training-data-profiles", json={"dataset_id": str(sample_dataset.id)})
    assert resp.status_code == 400
    assert "没有样本" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_profile_missing_dataset_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/training-data-profiles",
        json={"dataset_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ultradata_samples_endpoint(client: AsyncClient):
    resp = await client.get("/api/v1/training-data-profiles/ultradata/samples")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 10
    assert all(item["available"] for item in body["items"])


@pytest.mark.asyncio
async def test_ultradata_import_creates_dataset_and_profile(client: AsyncClient, db_session):
    """内置真实样例一键导入：建数据集 + 落样本 + 出画像（离线闭环）"""
    resp = await client.post(
        "/api/v1/training-data-profiles/ultradata/import", json={"sample": "ultrachat"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] > 0
    assert body["profile"]["status"] == "completed"
    dataset_id = body["dataset_id"]

    dataset = await db_session.get(Dataset, dataset_id)
    assert dataset is not None
    assert dataset.source_type == "ultradata"
    assert dataset.record_count == body["imported"]

    count = (await db_session.execute(
        select(TrainingDataRecord).where(TrainingDataRecord.dataset_id == dataset.id)
    )).scalars().all()
    assert len(count) == body["imported"]
    assert all(r.format == FORMAT_CHAT for r in count)

    # 幂等：重复导入复用同一数据集，不重复堆积样本
    resp2 = await client.post(
        "/api/v1/training-data-profiles/ultradata/import", json={"sample": "ultrachat"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["dataset_id"] == dataset_id
    count2 = (await db_session.execute(
        select(TrainingDataRecord).where(TrainingDataRecord.dataset_id == dataset.id)
    )).scalars().all()
    assert len(count2) == body["imported"]


@pytest.mark.asyncio
async def test_ultradata_import_unknown_sample_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/training-data-profiles/ultradata/import", json={"sample": "nope"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 字段分布 / 自然语言摘要
# ---------------------------------------------------------------------------
def test_schema_profile_includes_value_distribution_and_numeric_stats():
    payloads = [
        {"task": "Coding", "score": 4.5, "instruction": "a"},
        {"task": "Coding", "score": 3.5, "instruction": "b"},
        {"task": "Math", "score": 5.0, "instruction": "c"},
    ]
    schema = {f["name"]: f for f in build_schema_profile(payloads)}
    assert [v["value"] for v in schema["task"]["values"]] == ["Coding", "Math"]
    assert schema["task"]["values"][0]["ratio"] == pytest.approx(2 / 3, abs=0.01)
    assert schema["score"]["numeric"]["min"] == pytest.approx(3.5)
    assert schema["score"]["numeric"]["max"] == pytest.approx(5.0)
    assert schema["instruction"]["text"]["avg_len"] == 1.0


def test_profile_contains_readable_summary():
    """摘要要让没接触过数据集的人一眼看懂：规模/格式/语言/主题/质量/层级"""
    rows = _rows(SFT, SFT, CHAT, PREFERENCE, AGENT, PRETRAIN, PRETRAIN_NO_SCORE, QA)
    profile = build_profile(rows, payloads=[r["payload"] for r in rows])
    summary = profile["summary"]
    assert "8 条样本" in summary
    assert "指令微调" in summary  # 主格式中文标签
    assert "质量评级" in summary
    assert "L" in summary  # 层级建议
    assert isinstance(profile["classification"]["top_domains"], list)


# ---------------------------------------------------------------------------
# LLM 深度分析（注入假 completer，不打真实网络）
# ---------------------------------------------------------------------------
SAMPLE_LLM_REPLY = json.dumps({
    "what_is_it": "一个混合训练数据集。",
    "content_summary": "包含指令、对话、代码等多种内容。",
    "style_and_format": "指令-回答配对为主。",
    "quality_impression": "格式一致。",
    "strengths": ["格式多样"],
    "weaknesses": ["规模小"],
    "suggested_uses": ["SFT"],
    "risks": [],
    "representative_examples": [1],
    "notes": "",
}, ensure_ascii=False)

FULL_BATCH_REPLY = json.dumps([
    {"idx": 0, "topics": ["代码"], "quality": 4, "issue": ""},
    {"idx": 1, "topics": ["代码", "推理"], "quality": 3, "issue": "回答过短"},
], ensure_ascii=False)

FULL_SUMMARY_REPLY = json.dumps({
    "what_is_it": "代码类数据集。",
    "content_summary": "以代码生成为主。",
    "style_and_format": "SFT。",
    "quality_impression": "整体尚可。",
    "strengths": ["垂直"],
    "weaknesses": ["单一"],
    "suggested_uses": ["代码SFT"],
    "risks": [],
    "notes": "",
}, ensure_ascii=False)


async def _fake_complete_sample(prompt: str) -> str:
    return SAMPLE_LLM_REPLY


async def _fake_complete_full(prompt: str) -> str:
    return FULL_BATCH_REPLY if "标注员" in prompt else FULL_SUMMARY_REPLY


def test_build_sample_prompt_includes_records_and_context():
    from app.services.training_data.llm_analysis import build_sample_prompt
    prompt = build_sample_prompt([SFT, CHAT], {"total": 100, "format": "sft"})
    assert "instruction" in prompt
    assert "100" in prompt
    assert "sft" in prompt


@pytest.mark.asyncio
async def test_llm_analyze_sample_and_full_modes():
    from app.services.training_data import llm_analysis as la

    records = [normalize_record(SFT, i) for i in range(3)]
    payloads = [r["payload"] for r in records]
    sample_result = await la.analyze_sample(payloads, {"total": 3, "format": "sft"}, _fake_complete_sample)
    assert sample_result["mode"] == "sample"
    assert sample_result["analyzed_records"] == 3
    assert sample_result["what_is_it"]

    full_result = await la.analyze_full(payloads, {"total": 3}, _fake_complete_full, batch_size=2)
    assert full_result["mode"] == "full"
    # 3 条 / 批大小 2 -> 2 批；假回复每批都返回 2 条标注（内容相同）
    assert full_result["analyzed_records"] == 4
    assert full_result["topic_counts"]["代码"] == 4
    assert full_result["quality_hist"]["4"] == 2  # 每批一条 4 分
    assert full_result["quality_hist"]["3"] == 2  # 每批一条 3 分
    assert full_result["issues"] == ["回答过短", "回答过短"]
    assert full_result["per_record"][0]["topics"] == ["代码"]


@pytest.mark.asyncio
async def test_profile_with_llm_mode_off_has_no_llm_analysis(client: AsyncClient, sample_dataset: Dataset):
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import",
        files=_upload_file([SFT, CHAT, QA]),
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/api/v1/training-data-profiles",
        json={"dataset_id": str(sample_dataset.id), "llm_mode": "off"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["llm_mode"] == "off"
    assert body["llm_analysis"] is None
    assert body["summary"]


@pytest.mark.asyncio
async def test_profile_llm_mode_invalid_400(client: AsyncClient, sample_dataset: Dataset):
    resp = await client.post(
        "/api/v1/training-data-profiles",
        json={"dataset_id": str(sample_dataset.id), "llm_mode": "everything"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_profile_llm_mode_sample_without_model_degrades_gracefully(
    client: AsyncClient, sample_dataset: Dataset, monkeypatch
):
    """没有可用 LLM 模型时：规则画像照常完成，llm_analysis 标记 skipped 而非失败"""
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import", files=_upload_file([SFT, QA])
    )
    assert resp.status_code == 200

    from app.services.training_data import llm_analysis as la

    async def _no_model(db, llm_model_id=None):
        return None

    monkeypatch.setattr(la, "resolve_completer", _no_model)

    resp = await client.post(
        "/api/v1/training-data-profiles",
        json={"dataset_id": str(sample_dataset.id), "llm_mode": "sample"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["summary"]
    assert body["llm_analysis"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_profile_llm_mode_sample_with_fake_llm(
    client: AsyncClient, sample_dataset: Dataset, monkeypatch
):
    resp = await client.post(
        f"/api/v1/datasets/{sample_dataset.id}/import", files=_upload_file([SFT, CHAT, QA])
    )
    assert resp.status_code == 200

    from app.services.training_data import llm_analysis as la

    async def _fake_completer(db, llm_model_id=None):
        return _fake_complete_sample

    monkeypatch.setattr(la, "resolve_completer", _fake_completer)

    resp = await client.post(
        "/api/v1/training-data-profiles",
        json={"dataset_id": str(sample_dataset.id), "llm_mode": "sample", "llm_sample_size": 10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    analysis = body["llm_analysis"]
    assert analysis["status"] == "completed"
    assert analysis["mode"] == "sample"
    assert analysis["what_is_it"] == "一个混合训练数据集。"
    assert analysis["analyzed_records"] == 3


@pytest.mark.asyncio
async def test_resolve_completer_real_db_path(db_session, sample_llm_model, monkeypatch):
    """真实 DB 路径：默认模型选择 + 指定 model_id + 非 LLM 类型报错"""
    from app.models import Model
    from app.services.training_data import llm_analysis as la

    captured = {}

    class _FakeLLM:
        async def ainvoke(self, prompt):
            captured["prompt"] = prompt

            class R:
                content = '{"ok": true}'
            return R()

    async def _fake_create(model, param_overrides=None):
        captured["model"] = model
        return _FakeLLM()

    from app.services.llm import llm_client
    monkeypatch.setattr(llm_client, "create_llm_from_config", _fake_create)

    # 不指定 id：选中一个 active 的默认 LLM（共享库中可能有其他测试留下的模型，
    # 这里只断言选中的是 LLM 类型且是本 fixture 的模型或另一个默认模型）
    completer = await la.resolve_completer(db_session)
    assert completer is not None
    assert captured["model"].model_type == "llm"
    text = await completer("hi")
    assert text == '{"ok": true}'

    # 指定 id：精确命中
    captured.clear()
    completer2 = await la.resolve_completer(db_session, sample_llm_model.id)
    assert completer2 is not None
    assert captured["model"].id == sample_llm_model.id

    # 非 LLM 模型（embedding）：显式指定时报错
    emb = Model(
        name="emb", model_type="embedding", provider="openai",
        model_name="e", endpoint="http://x", api_key_encrypted="k",
        is_default=False, status="active",
    )
    db_session.add(emb)
    await db_session.commit()
    with pytest.raises(ValueError, match="不是 LLM"):
        await la.resolve_completer(db_session, emb.id)

    # 不存在的 id
    with pytest.raises(ValueError, match="不存在"):
        await la.resolve_completer(db_session, "00000000-0000-0000-0000-000000000001")
