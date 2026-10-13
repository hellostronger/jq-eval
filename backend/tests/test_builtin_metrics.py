# 内置指标同步（指标市场数据源）测试
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricDefinition
from app.services.builtin_metrics import (
    SCOPE_RAG,
    SCOPE_TRAINING_DATA,
    sync_builtin_metrics,
)
from app.services.metrics.engine import METRIC_REGISTRY
from app.services.training_data.engine import TRAINING_DATA_METRIC_REGISTRY

# 指标市场现在同时收录两套体系的指标
ALL_METRIC_NAMES = set(METRIC_REGISTRY) | set(TRAINING_DATA_METRIC_REGISTRY)


@pytest.mark.asyncio
async def test_sync_builtin_metrics_seeds_registry(db_session: AsyncSession):
    """内置指标注册表应被同步进 metric_definitions 表

    回归背景：指标市场读的是这张表，但原先只有用户自建指标会写入，
    内置指标从未落库，导致指标市场永远是空的。

    另：训练数据质量评估的指标原先只活在内存注册表里，市场中同样看不到，
    现在一并同步，用 scope 区分。
    """
    created = await sync_builtin_metrics(db_session)

    rows = (await db_session.execute(select(MetricDefinition))).scalars().all()
    assert created == len(rows)
    assert {r.name for r in rows} == ALL_METRIC_NAMES
    assert all(r.is_builtin for r in rows)


@pytest.mark.asyncio
async def test_training_data_metrics_synced_with_scope(db_session: AsyncSession):
    """训练数据指标应带 scope=training_data 与 data_types 落库"""
    await sync_builtin_metrics(db_session)

    rows = (
        (
            await db_session.execute(
                select(MetricDefinition).where(
                    MetricDefinition.scope == SCOPE_TRAINING_DATA
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.name for r in rows} == set(TRAINING_DATA_METRIC_REGISTRY)

    for row in rows:
        # 阈值字段是训练数据指标的必备信息，市场里要能直接拿到
        assert row.default_threshold is not None
        assert row.threshold_type in ("min", "max", "range")
        assert row.data_types, "训练数据指标必须声明适用类型，否则下拉框无法按类型过滤"

    rag_rows = (
        (
            await db_session.execute(
                select(MetricDefinition).where(MetricDefinition.scope == SCOPE_RAG)
            )
        )
        .scalars()
        .all()
    )
    assert {r.name for r in rag_rows} == set(METRIC_REGISTRY)
    assert all(r.data_types is None for r in rag_rows), "RAG 指标不应有 data_types"


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
    assert len(rows) == len(ALL_METRIC_NAMES), "重复同步产生了重复行"
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
    assert len(data) == len(ALL_METRIC_NAMES)
    assert {m["name"] for m in data} == ALL_METRIC_NAMES
    for metric in data:
        assert metric["is_builtin"] is True
        assert metric["display_name"]
        assert metric["scope"] in (SCOPE_RAG, SCOPE_TRAINING_DATA)


@pytest.mark.asyncio
async def test_metric_market_filters_by_scope(
    client: AsyncClient, db_session: AsyncSession
):
    """指标市场应能按 scope / data_type 筛选，训练数据页靠它取自己的指标"""
    await sync_builtin_metrics(db_session)

    resp = await client.get("/api/v1/metrics", params={"scope": SCOPE_TRAINING_DATA})
    assert resp.status_code == 200
    names = {m["name"] for m in resp.json()}
    assert names == set(TRAINING_DATA_METRIC_REGISTRY)

    resp = await client.get("/api/v1/metrics", params={"scope": SCOPE_RAG})
    assert resp.status_code == 200
    assert {m["name"] for m in resp.json()} == set(METRIC_REGISTRY)

    # 按训练数据类型过滤：llm 类指标都应声明适用于 llm
    resp = await client.get(
        "/api/v1/metrics",
        params={"scope": SCOPE_TRAINING_DATA, "data_type": "llm"},
    )
    assert resp.status_code == 200
    llm_metrics = resp.json()
    assert llm_metrics
    for m in llm_metrics:
        assert "llm" in m["data_types"]


@pytest.mark.asyncio
async def test_training_data_metrics_available_endpoint_uses_market(
    client: AsyncClient, db_session: AsyncSession
):
    """训练数据页的 /metrics/available 应改由指标市场供数（不再直读内存注册表）"""
    await sync_builtin_metrics(db_session)

    resp = await client.get(
        "/api/v1/training-data-evals/metrics/available", params={"data_type": "llm"}
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert metrics

    for m in metrics:
        # 必须带市场里的 id，配置行才能建立外键
        assert m["id"]
        assert m["name"] in TRAINING_DATA_METRIC_REGISTRY
        assert "llm" in m["data_types"]
        assert m["default_threshold"] is not None

    # 已下架的指标不应再出现在可选列表里
    name = metrics[0]["name"]
    row = (await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.name == name)
    )).scalar_one()
    row.is_active = False
    await db_session.commit()

    resp = await client.get(
        "/api/v1/training-data-evals/metrics/available", params={"data_type": "llm"}
    )
    assert name not in {m["name"] for m in resp.json()["metrics"]}


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


@pytest.mark.asyncio
async def test_removed_training_metric_is_deactivated(db_session: AsyncSession):
    """训练数据指标从注册表移除后同样应下架，而不是残留在市场里"""
    await sync_builtin_metrics(db_session)
    name = next(iter(TRAINING_DATA_METRIC_REGISTRY))
    row = (await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.name == name)
    )).scalar_one()
    row_id = row.id

    import app.services.builtin_metrics as bm
    original = dict(bm.TRAINING_DATA_METRIC_REGISTRY)
    bm.TRAINING_DATA_METRIC_REGISTRY.pop(name)
    try:
        await sync_builtin_metrics(db_session)
    finally:
        bm.TRAINING_DATA_METRIC_REGISTRY.update(original)

    after = (await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.id == row_id)
    )).scalar_one_or_none()
    assert after is not None, "下架的指标被物理删除了"
    assert after.is_active is False