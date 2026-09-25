# 内置指标同步（指标市场数据源）测试
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricDefinition
from app.services.builtin_metrics import sync_builtin_metrics
from app.services.metrics.engine import METRIC_REGISTRY


@pytest.mark.asyncio
async def test_sync_builtin_metrics_seeds_registry(db_session: AsyncSession):
    """内置指标注册表应被同步进 metric_definitions 表

    回归背景：指标市场读的是这张表，但原先只有用户自建指标会写入，
    内置指标从未落库，导致指标市场永远是空的。
    """
    created = await sync_builtin_metrics(db_session)
    assert created == len(METRIC_REGISTRY)

    rows = (await db_session.execute(select(MetricDefinition))).scalars().all()
    assert len(rows) == len(METRIC_REGISTRY)
    assert {r.name for r in rows} == set(METRIC_REGISTRY)
    assert all(r.is_builtin for r in rows)


@pytest.mark.asyncio
async def test_sync_builtin_metrics_is_idempotent(db_session: AsyncSession):
    """重复执行不应产生重复行，也不该把 usage_count 之类的统计清零"""
    await sync_builtin_metrics(db_session)
    row = (await db_session.execute(
        select(MetricDefinition).where(
            MetricDefinition.name == next(iter(METRIC_REGISTRY))
        )
    )).scalar_one()
    row.usage_count = 7
    await db_session.commit()

    created_again = await sync_builtin_metrics(db_session)
    assert created_again == 0

    rows = (await db_session.execute(select(MetricDefinition))).scalars().all()
    assert len(rows) == len(METRIC_REGISTRY), "重复同步产生了重复行"
    assert any(r.usage_count == 7 for r in rows), "同步把运行期统计清零了"


@pytest.mark.asyncio
async def test_metric_market_not_empty_after_sync(
    client: AsyncClient, db_session: AsyncSession
):
    """同步后指标市场接口应能列出内置指标"""
    await sync_builtin_metrics(db_session)
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(METRIC_REGISTRY)
    assert {m["name"] for m in data} == set(METRIC_REGISTRY)
    for metric in data:
        assert metric["is_builtin"] is True
        assert metric["display_name"]


@pytest.mark.asyncio
async def test_removed_builtin_metric_is_deactivated_not_deleted(
    db_session: AsyncSession
):
    """指标从注册表移除后应下架（is_active=False）而不是被物理删除

    历史评估结果仍按 id 引用着这些行，删掉会导致旧报告查不到指标名。
    """
    await sync_builtin_metrics(db_session)
    name = next(iter(METRIC_REGISTRY))
    row = (await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.name == name)
    )).scalar_one()
    row_id = row.id

    # 模拟注册表里这个指标被移除
    import app.services.builtin_metrics as bm
    original = dict(bm.METRIC_REGISTRY)
    bm.METRIC_REGISTRY.pop(name)
    try:
        await sync_builtin_metrics(db_session)
    finally:
        bm.METRIC_REGISTRY.update(original)

    after = (await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.id == row_id)
    )).scalar_one_or_none()
    assert after is not None, "下架的指标被物理删除了"
    assert after.is_active is False
