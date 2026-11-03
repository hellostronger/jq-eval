# 检索 gold 回填（backfill-targets）
#
# 开源基准导入后最常见的坑是 target_chunk_ids 为空或口径不对：recall/mrr 全部
# 报"缺少目标 chunk ID 列表"，整批评估只能看到生成指标。原先唯一的补救办法是重建
# 数据集，可调用批次和评估结果都挂在旧 dataset_id 上，重建等于把它们作废——实测
# 本地就因此堆出了 "MultiHop-RAG 规范导入"（无 gold）+ "smoke5 gold 两页对齐"
# （5 题副本）两份口径不同的数据。这里只补 gold，不动题目和答案。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord

pytestmark = pytest.mark.asyncio


async def _seed(db: AsyncSession, questions) -> Dataset:
    ds = Dataset(name="DS-gold", description="d", status="active")
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    for q in questions:
        db.add(QARecord(dataset_id=ds.id, question=q, answer="a", target_chunk_ids=[]))
    await db.commit()
    return ds


async def _rows(db: AsyncSession, ds: Dataset):
    from sqlalchemy import select
    return (await db.execute(
        select(QARecord).where(QARecord.dataset_id == ds.id).order_by(QARecord.created_at)
    )).scalars().all()


@pytest.mark.asyncio
async def test_backfill_fills_empty_targets(client: AsyncClient, db_session: AsyncSession):
    ds = await _seed(db_session, ["Who is A?", "Which B?"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [
            {"question": "Who is A?", "target_chunk_ids": ["mh_0001:p0011", "mh_0001:p0012"]},
            {"question": "Which B?", "gold_chunk_ids": ["mh_0001:p0076"]},
        ]
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched"] == 2 and body["filled"] == 2

    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == ["mh_0001:p0011", "mh_0001:p0012"]
    assert rows[1].target_chunk_ids == ["mh_0001:p0076"], "gold_chunk_ids 别名也要认"


@pytest.mark.asyncio
async def test_existing_gold_not_overwritten_by_default(client: AsyncClient, db_session: AsyncSession):
    """只补空是默认口径：重跑回填不能悄悄改掉已经人工核对过的 gold"""
    ds = await _seed(db_session, ["Q keep"])
    rows = await _rows(db_session, ds)
    rows[0].target_chunk_ids = ["gold:1"]
    await db_session.commit()

    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [{"question": "Q keep", "target_chunk_ids": ["gold:2"]}]
    })
    body = resp.json()
    assert body["filled"] == 0 and body["kept_existing"] == 1
    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == ["gold:1"]

    forced = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [{"question": "Q keep", "target_chunk_ids": ["gold:2"]}], "overwrite": True
    })
    assert forced.json()["filled"] == 1
    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == ["gold:2"]


@pytest.mark.asyncio
async def test_dry_run_reports_without_writing(client: AsyncClient, db_session: AsyncSession):
    """先看清会补多少条：2556 题的库不试一把就直接写不安全"""
    ds = await _seed(db_session, ["Q dry"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [{"question": "Q dry", "target_chunk_ids": ["p1"]}], "dry_run": True
    })
    body = resp.json()
    assert body["dry_run"] is True and body["filled"] == 1
    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == [], "dry_run 不该写库"


@pytest.mark.asyncio
async def test_question_whitespace_and_case_still_match(client: AsyncClient, db_session: AsyncSession):
    ds = await _seed(db_session, ["Does  The Verge  claim X?"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [{"question": "does the verge claim x?\n", "target_chunk_ids": ["p0001"]}]
    })
    assert resp.json()["filled"] == 1, "首尾空格/换行/大小写差异不该让 gold 补不进去"


@pytest.mark.asyncio
async def test_stringified_id_list_is_parsed(client: AsyncClient, db_session: AsyncSession):
    """基准原始 jsonl 里 positive_ids 常是字符串 "['11','12']"，不能整条丢掉"""
    ds = await _seed(db_session, ["Q str"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [{"question": "Q str", "positive_ids": "['11', '12']"}]
    })
    assert resp.json()["filled"] == 1
    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == ["11", "12"]


@pytest.mark.asyncio
async def test_conflicting_gold_for_same_question_is_skipped(client: AsyncClient, db_session: AsyncSession):
    """同一道题给了两份不同 gold：宁可不补，也不随便挑一份写进库"""
    ds = await _seed(db_session, ["Q conflict"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [
            {"question": "Q conflict", "target_chunk_ids": ["a"]},
            {"question": "Q conflict", "target_chunk_ids": ["b"]},
        ]
    })
    body = resp.json()
    assert body["payload_ambiguous"] == 1
    assert body["filled"] == 0
    rows = await _rows(db_session, ds)
    assert rows[0].target_chunk_ids == []


@pytest.mark.asyncio
async def test_unmatched_and_invalid_are_reported(client: AsyncClient, db_session: AsyncSession):
    ds = await _seed(db_session, ["Q known"])
    resp = await client.post(f"/api/v1/datasets/{ds.id}/qa-records/backfill-targets", json={
        "records": [
            {"question": "Q known", "target_chunk_ids": ["x"]},
            {"question": "Q absent", "target_chunk_ids": ["y"]},
            {"question": "Q known"},
        ]
    })
    body = resp.json()
    assert body["filled"] == 1
    assert body["not_in_dataset"] == 1
    assert body["payload_invalid"] == 1, "没有 gold 的记录要单独计数，否则补了个空没人知道"


@pytest.mark.asyncio
async def test_missing_dataset_returns_404(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/api/v1/datasets/11111111-1111-1111-1111-111111111111/qa-records/backfill-targets",
        json={"records": [{"question": "x", "target_chunk_ids": ["y"]}]}
    )
    assert resp.status_code == 404
