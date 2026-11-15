# 内置基准评测集测试：文件有效性 / 幂等入库 / 版本冻结升版 / API
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord
from app.models.evaluation import Evaluation
from app.services.builtin_benchmarks import (
    BUILTIN_BENCHMARKS,
    VALID_DIFFICULTIES,
    VALID_QUESTION_TYPES,
    compute_quality_report,
    load_benchmark_records,
    sync_builtin_benchmarks,
    provision_builtin_benchmark,
)

BENCHMARK_ID = "rag_qa_zh_v1"
STRESS_ID = "rag_stress_zh_v1"


def _get_meta(benchmark_id: str = BENCHMARK_ID):
    return next(m for m in BUILTIN_BENCHMARKS if m["benchmark_id"] == benchmark_id)


def _get_records(benchmark_id: str):
    return load_benchmark_records(_get_meta(benchmark_id))


async def _get_builtin_dataset(db, benchmark_id: str):
    datasets = (await db.execute(
        select(Dataset).where(Dataset.source_type == "builtin")
    )).scalars().all()
    return next(
        d for d in datasets
        if (d.dataset_metadata or {}).get("benchmark_id") == benchmark_id
    )


# ---------- 文件有效性（不依赖数据库） ----------

def test_benchmark_records_valid_and_tiered():
    """所有内置基准文件都应通过校验：必填字段/枚举/去重/难度×题型覆盖"""
    for meta in BUILTIN_BENCHMARKS:
        records, file_hash = load_benchmark_records(meta)

        assert len(records) >= 50, f"{meta['benchmark_id']} 样本过少，无统计意义"
        assert len(file_hash) == 64

        # 双维度分层：难度、题型各自的分布都要有量，交叉组合不能为空
        by_difficulty = {d: 0 for d in VALID_DIFFICULTIES}
        by_type = {t: 0 for t in VALID_QUESTION_TYPES}
        combos = set()
        for r in records:
            by_difficulty[r["difficulty"]] += 1
            by_type[r["question_type"]] += 1
            combos.add((r["difficulty"], r["question_type"]))
            assert r["question"] and r["answer"] and r["ground_truth"]
            assert r["ability"] and r["subject"], "能力/学科标注缺失，评估结果无法按维度拆解"

        assert all(v >= 5 for v in by_difficulty.values()), (meta["benchmark_id"], by_difficulty)
        assert all(v >= 5 for v in by_type.values()), (meta["benchmark_id"], by_type)
        missing = [
            f"{d}/{t}"
            for d in VALID_DIFFICULTIES
            for t in VALID_QUESTION_TYPES
            if (d, t) not in combos
        ]
        assert not missing, f"{meta['benchmark_id']} 缺少难度×题型组合: {missing}"


def test_stress_benchmark_probe_coverage():
    """诊断基准的 8 类探针每类都要有量，且探针不变量成立"""
    records, _ = _get_records(STRESS_ID)
    by_probe = {}
    for r in records:
        by_probe[r["probe"]] = by_probe.get(r["probe"], 0) + 1
    assert len(by_probe) == 8, by_probe
    assert all(v >= 5 for v in by_probe.values()), by_probe

    for r in records:
        if r["probe"] == "unanswerable":
            # 拒答题的参考答案必须给出标准拒答口径，否则判分无所适从
            assert r["answer"].startswith("应拒答"), r["question"]
        else:
            assert not r["answer"].startswith("应拒答")
        # 命题材料只属于冲突探针：带材料的题必须声明冲突探针，反之亦然
        assert bool(r["contexts"]) == (r["probe"] == "knowledge_conflict"), r["question"]
        assert r["probe_note"], f"缺少探针说明: {r['question']}"


def test_benchmark_no_duplicate_questions():
    """集内不允许重复题干（归一化口径）——loader 校验的回归测试"""
    for meta in BUILTIN_BENCHMARKS:
        records, _ = load_benchmark_records(meta)
        questions = [" ".join(r["question"].split()).casefold() for r in records]
        assert len(questions) == len(set(questions)), meta["benchmark_id"]


def test_benchmark_quality_report_shape():
    """质量报告应包含分层分布与长度统计，供前端/画像直接展示"""
    for meta in BUILTIN_BENCHMARKS:
        records, _ = load_benchmark_records(meta)
        report = compute_quality_report(records)

        assert report["total"] == len(records)
        assert sum(report["by_difficulty"].values()) == len(records)
        assert sum(report["by_question_type"].values()) == len(records)
        assert sum(report["by_probe"].values()) == (
            len(records) if meta.get("require_probe") else 0
        )
        assert report["by_ability"] and report["by_subject"]
        assert report["duplicate_rate"] == 0.0
        assert report["question_length"]["min"] > 0
        assert report["answer_length"]["avg"] > 0


# ---------- 入库与幂等 ----------

async def _qa_count(db, dataset_id) -> int:
    return await db.scalar(
        select(func.count(QARecord.id)).where(QARecord.dataset_id == dataset_id)
    )


@pytest.mark.asyncio
async def test_sync_seeds_builtin_dataset(db_session: AsyncSession):
    """同步应创建全部内置数据集并落库样本（含能力/学科标注）"""
    created = await sync_builtin_benchmarks(db_session)
    assert created == len(BUILTIN_BENCHMARKS)

    dataset = await _get_builtin_dataset(db_session, BENCHMARK_ID)
    assert dataset.dataset_kind == "evaluation"
    assert dataset.has_ground_truth is True
    assert dataset.status == "ready"

    meta = _get_meta()
    records, file_hash = load_benchmark_records(meta)
    assert dataset.record_count == len(records)
    assert await _qa_count(db_session, dataset.id) == len(records)
    assert (dataset.dataset_metadata or {}).get("file_hash") == file_hash
    assert (dataset.dataset_metadata or {}).get("benchmark_id") == BENCHMARK_ID

    sample = (await db_session.execute(
        select(QARecord).where(QARecord.dataset_id == dataset.id).limit(1)
    )).scalar_one()
    qa_meta = sample.qa_metadata or {}
    assert qa_meta.get("benchmark_id") == BENCHMARK_ID
    assert "ability" in qa_meta and "subject" in qa_meta
    assert sample.ground_truth == sample.answer


@pytest.mark.asyncio
async def test_sync_seeds_stress_dataset_with_contexts(db_session: AsyncSession):
    """诊断基准应入库：冲突探针带命题材料（snapshot.contexts），qa_metadata 带探针标注"""
    await sync_builtin_benchmarks(db_session)
    dataset = await _get_builtin_dataset(db_session, STRESS_ID)

    meta = _get_meta(STRESS_ID)
    records, _ = load_benchmark_records(meta)
    assert dataset.record_count == len(records)
    # 只有冲突探针带材料，但 has_contexts 应被标记（faithfulness 指标依赖）
    assert dataset.has_contexts is True

    with_context = (await db_session.execute(
        select(QARecord).where(QARecord.dataset_id == dataset.id).limit(50)
    )).scalars().all()
    conflict = [r for r in with_context if (r.qa_metadata or {}).get("probe") == "knowledge_conflict"]
    assert conflict, "冲突探针样本未落库"
    for r in conflict:
        assert (r.snapshot or {}).get("contexts"), "冲突探针缺少命题材料"

    plain = [r for r in with_context if (r.qa_metadata or {}).get("probe") == "unanswerable"]
    assert plain, "拒答探针样本未落库"
    assert all(not (r.snapshot or {}).get("contexts") for r in plain)
    # 报告里应能看到探针分布
    report = (dataset.dataset_metadata or {}).get("quality_report") or {}
    assert sum(report.get("by_probe", {}).values()) == len(records)


@pytest.mark.asyncio
async def test_sync_is_idempotent(db_session: AsyncSession):
    """重复同步不产生重复数据集/重复样本"""
    await sync_builtin_benchmarks(db_session)
    created_again = await sync_builtin_benchmarks(db_session)
    assert created_again == 0

    datasets = (await db_session.execute(
        select(Dataset).where(Dataset.source_type == "builtin")
    )).scalars().all()
    assert len(datasets) == len(BUILTIN_BENCHMARKS)
    for meta in BUILTIN_BENCHMARKS:
        records, _ = load_benchmark_records(meta)
        dataset = await _get_builtin_dataset(db_session, meta["benchmark_id"])
        assert await _qa_count(db_session, dataset.id) == len(records)


# ---------- 版本冻结与升版 ----------

@pytest.mark.asyncio
async def test_stale_hash_upgrades_when_unused(db_session: AsyncSession):
    """文件内容变化且数据集未被引用：原地重建并更新冻结哈希"""
    await sync_builtin_benchmarks(db_session)
    dataset = await _get_builtin_dataset(db_session, BENCHMARK_ID)

    # 模拟旧版本：改哈希 + 删两条样本造成内容漂移
    meta = _get_meta()
    records, file_hash = load_benchmark_records(meta)
    dataset.dataset_metadata = {**(dataset.dataset_metadata or {}), "file_hash": "0" * 64}
    first_id = (await db_session.execute(
        select(QARecord.id).where(QARecord.dataset_id == dataset.id).limit(1)
    )).scalar_one()
    stale = await db_session.get(QARecord, first_id)
    await db_session.delete(stale)
    await db_session.commit()
    assert await _qa_count(db_session, dataset.id) == len(records) - 1

    result = await provision_builtin_benchmark(db_session, BENCHMARK_ID)
    assert result["upgraded"] is True
    assert result["upgrade_skipped"] is False
    assert await _qa_count(db_session, dataset.id) == len(records), "升版后样本数未恢复"
    refreshed = await db_session.get(Dataset, dataset.id)
    assert (refreshed.dataset_metadata or {}).get("file_hash") == file_hash


@pytest.mark.asyncio
async def test_stale_hash_skipped_when_in_use(db_session: AsyncSession):
    """文件内容变化但数据集已被评估引用：跳过升版，历史结果不被撕断"""
    await sync_builtin_benchmarks(db_session)
    dataset = await _get_builtin_dataset(db_session, BENCHMARK_ID)

    db_session.add(Evaluation(
        name="历史评估",
        dataset_id=dataset.id,
        metrics=["answer_correctness"],
    ))
    meta = _get_meta()
    records, file_hash = load_benchmark_records(meta)
    dataset.dataset_metadata = {**(dataset.dataset_metadata or {}), "file_hash": "0" * 64}
    await db_session.commit()

    count_before = await _qa_count(db_session, dataset.id)
    result = await provision_builtin_benchmark(db_session, BENCHMARK_ID)
    assert result["upgrade_skipped"] is True
    assert result["upgraded"] is False
    assert await _qa_count(db_session, dataset.id) == count_before, "被引用的数据集被原地重建了"
    refreshed = await db_session.get(Dataset, dataset.id)
    assert (refreshed.dataset_metadata or {}).get("file_hash") == "0" * 64


# ---------- API ----------

@pytest.mark.asyncio
async def test_builtin_list_and_provision_api(client: AsyncClient, db_session: AsyncSession):
    """列表接口暴露注册表+入库状态；provision 幂等可重复调用"""
    # 前面的同步测试可能已把基准入库，先清掉保证从零验证 provision。
    # 顺序必须是 evaluation → qa_record → dataset：删 dataset 时 ORM 会把
    # 子表外键置 NULL，evaluations.dataset_id 非空，留着会先炸 NOT NULL 约束
    existing = (await db_session.execute(
        select(Dataset).where(Dataset.source_type == "builtin")
    )).scalars().all()
    for ds in existing:
        await db_session.execute(delete(Evaluation).where(Evaluation.dataset_id == ds.id))
        await db_session.execute(delete(QARecord).where(QARecord.dataset_id == ds.id))
        await db_session.delete(ds)
    await db_session.commit()

    resp = await client.get("/api/v1/datasets/builtin")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["benchmark_id"] for i in items] == [m["benchmark_id"] for m in BUILTIN_BENCHMARKS]
    item = next(i for i in items if i["benchmark_id"] == BENCHMARK_ID)
    assert item["load_error"] is None
    assert item["file_hash"]

    resp = await client.post(f"/api/v1/datasets/builtin/{BENCHMARK_ID}/provision")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    dataset_id = body["dataset"]["id"]
    assert body["dataset"]["record_count"] > 0

    # 幂等：再调一次不重复创建
    resp = await client.post(f"/api/v1/datasets/builtin/{BENCHMARK_ID}/provision")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is False and body["upgraded"] is False
    assert body["dataset"]["id"] == dataset_id

    # 诊断基准同样可一键导入，报告含探针分布
    resp = await client.post(f"/api/v1/datasets/builtin/{STRESS_ID}/provision")
    assert resp.status_code == 200
    stress_body = resp.json()
    assert stress_body["created"] is True
    assert stress_body["record_count"] > 0
    probe_total = sum(stress_body["quality_report"]["by_probe"].values())
    assert probe_total == stress_body["record_count"]

    # 质量报告随列表返回
    resp = await client.get("/api/v1/datasets/builtin")
    item = next(
        i for i in resp.json()["items"] if i["benchmark_id"] == BENCHMARK_ID
    )
    assert item["dataset"]["version_match"] is True
    assert item["dataset"]["quality_report"]["total"] > 0

    # 未知 benchmark_id → 404
    resp = await client.post("/api/v1/datasets/builtin/not_exist/provision")
    assert resp.status_code == 404
