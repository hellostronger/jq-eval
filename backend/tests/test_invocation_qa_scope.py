# 调用批次取样范围（qa_limit / qa_offset）
#
# 原先批次只能整数据集跑：2556 题的 MultiHop、每题几分钟的 UltraData 想
# "先试 40 题"只能再建一个小数据集绕开，同一份语料在库里留下多份副本，
# 各副本的评估口径互不相通。取样范围必须贯穿创建、执行、重试补齐、终态判定
# 四处——任何一处漏套，total_count 与实际派发条数就会不一致。
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord
from app.models.invocation import InvocationBatch
from app.services.dataset.qa_scope import (
    apply_scope,
    count_in_scope,
    missing_qa_in_scope,
    qa_ids_in_scope,
)


async def _dataset_with_qa(db: AsyncSession, n: int) -> Dataset:
    ds = Dataset(name=f"DS{n}", description="d", status="active")
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    for i in range(n):
        # created_at 决定取样顺序，逐条写入保证顺序稳定
        db.add(QARecord(dataset_id=ds.id, question=f"q{i}", answer=f"a{i}"))
        await db.commit()
    return ds


def _batch(ds: Dataset, rag_system=None, **kwargs) -> InvocationBatch:
    return InvocationBatch(
        name="scoped", dataset_id=ds.id,
        rag_system_id=rag_system.id if rag_system is not None else None,
        status="pending", **kwargs,
    )


class TestScopeQueries:
    @pytest.mark.asyncio
    async def test_limit_truncates_without_changing_order(self, db_session: AsyncSession):
        ds = await _dataset_with_qa(db_session, 10)
        batch = _batch(ds, qa_limit=3)
        ids = await qa_ids_in_scope(db_session, batch)
        assert len(ids) == 3
        assert ids == await qa_ids_in_scope(db_session, batch), "同范围必须取到同一批题"

        # 顺序就是 created_at 顺序，取的是最前面 3 条
        all_rows = (await db_session.execute(
            select(QARecord.id).where(QARecord.dataset_id == ds.id).order_by(QARecord.created_at)
        )).all()
        assert ids == [r[0] for r in all_rows[:3]]

    @pytest.mark.asyncio
    async def test_offset_skips_prefix(self, db_session: AsyncSession):
        ds = await _dataset_with_qa(db_session, 10)
        batch = _batch(ds, qa_limit=2, qa_offset=5)
        assert await count_in_scope(db_session, batch) == 2
        full = await qa_ids_in_scope(db_session, _batch(ds))
        assert set(await qa_ids_in_scope(db_session, batch)) == set(full[5:7])

    @pytest.mark.asyncio
    async def test_no_scope_covers_whole_dataset(self, db_session: AsyncSession):
        ds = await _dataset_with_qa(db_session, 4)
        batch = _batch(ds)
        assert await count_in_scope(db_session, batch) == 4

    @pytest.mark.asyncio
    async def test_scope_helper_is_a_noop_for_legacy_batches(self, db_session: AsyncSession):
        """老批次（两列为 NULL）不得被改动查询——迁移后旧数据行为必须不变"""
        ds = await _dataset_with_qa(db_session, 3)
        stmt = select(QARecord.id).where(QARecord.dataset_id == ds.id).order_by(QARecord.created_at)
        from sqlalchemy import select as _s
        before = str(apply_scope(stmt, _batch(ds)))
        assert "LIMIT" not in before.upper() and "OFFSET" not in before.upper()


class TestMissingBackfill:
    @pytest.mark.asyncio
    async def test_backfill_stays_inside_scope(self, db_session: AsyncSession, sample_rag_system):
        """只跑 40 题的批次，补齐不能补出整个数据集的占位行"""
        ds = await _dataset_with_qa(db_session, 10)
        batch = _batch(ds, sample_rag_system, qa_limit=3, total_count=3)
        db_session.add(batch)
        await db_session.commit()

        covered = await qa_ids_in_scope(db_session, batch)
        # 前 3 条里只落了 1 条
        missing = await missing_qa_in_scope(db_session, batch, covered[:1])
        assert len(missing) == 2
        assert {m.id for m in missing} == set(covered[1:])


@pytest.mark.asyncio
async def test_create_batch_counts_scope_not_whole_dataset(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system
):
    """total_count 必须是范围内条数：界面进度与终态判定都按它算"""
    ds = await _dataset_with_qa(db_session, 12)
    resp = await client.post("/api/v1/invocations", json={
        "name": "试点 5 题", "dataset_id": str(ds.id),
        "rag_system_id": str(sample_rag_system.id), "qa_limit": 5,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 5
    assert body["qa_limit"] == 5

    batch = await db_session.get(InvocationBatch, __import__("uuid").UUID(body["id"]))
    assert batch.qa_limit == 5


@pytest.mark.asyncio
async def test_create_batch_clamps_limit_to_dataset_size(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system
):
    """范围超出语料时按实际条数落，而不是建出一个永远跑不完的批次"""
    ds = await _dataset_with_qa(db_session, 3)
    resp = await client.post("/api/v1/invocations", json={
        "name": "超范围", "dataset_id": str(ds.id),
        "rag_system_id": str(sample_rag_system.id), "qa_limit": 40,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_count"] == 3


@pytest.mark.asyncio
async def test_create_batch_rejects_offset_beyond_dataset(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system
):
    ds = await _dataset_with_qa(db_session, 3)
    resp = await client.post("/api/v1/invocations", json={
        "name": "空范围", "dataset_id": str(ds.id),
        "rag_system_id": str(sample_rag_system.id), "qa_limit": 5, "qa_offset": 9,
    })
    assert resp.status_code == 400
    assert "不会有任何题目" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_legacy_batch_without_scope_still_creates_full_count(
    client: AsyncClient, db_session: AsyncSession, sample_rag_system
):
    """不传范围＝旧行为，total_count 仍是数据集条数"""
    ds = await _dataset_with_qa(db_session, 6)
    resp = await client.post("/api/v1/invocations", json={
        "name": "整批", "dataset_id": str(ds.id), "rag_system_id": str(sample_rag_system.id),
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_count"] == 6
    assert resp.json()["qa_limit"] is None
