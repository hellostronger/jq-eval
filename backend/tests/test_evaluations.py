# 评估任务 API 测试
import pytest
from httpx import AsyncClient
from app.models import Dataset, Model, RAGSystem


@pytest.mark.asyncio
async def test_list_evaluations(client: AsyncClient):
    """测试获取评估列表"""
    response = await client.get("/api/v1/evaluations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_evaluation(
    client: AsyncClient,
    sample_dataset: Dataset,
    sample_llm_model: Model
):
    """测试创建评估任务"""
    response = await client.post("/api/v1/evaluations", json={
        "name": "Test Evaluation",
        "description": "A test evaluation",
        "dataset_id": str(sample_dataset.id),
        "llm_model_id": str(sample_llm_model.id),
        "metrics": ["faithfulness", "answer_relevance"],
        "batch_size": 10
    })
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["name"] == "Test Evaluation"


@pytest.mark.asyncio
async def test_get_metrics(client: AsyncClient):
    """测试获取指标列表"""
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_evaluation_detail_exposes_failure_reason(
    client: AsyncClient, db_session, sample_dataset: Dataset
):
    """评估详情必须带出失败原因

    回归背景：失败原因一直存在 evaluations.error 里、/status 接口也返回，
    但详情响应没带这个字段，前端对 failed 任务只能整页留白，
    用户点进失败任务看不到任何原因（实际线上就有一条失败任务是
    「需要配置 Embedding 模型」，完全无从得知）。
    """
    from app.models.evaluation import Evaluation

    evaluation = Evaluation(
        name="failed-eval",
        dataset_id=sample_dataset.id,
        metrics=["faithfulness"],
        batch_size=5,
        status="failed",
        progress=0,
        error="评估任务需要配置 Embedding 模型（所选指标依赖向量相似度）",
    )
    db_session.add(evaluation)
    await db_session.commit()
    await db_session.refresh(evaluation)

    response = await client.get(f"/api/v1/evaluations/{evaluation.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "评估任务需要配置 Embedding 模型（所选指标依赖向量相似度）"


@pytest.mark.asyncio
async def test_get_evaluation_detail_error_null_when_not_failed(
    client: AsyncClient, db_session, sample_dataset: Dataset
):
    """未失败的任务 error 应为 null，而不是缺字段或空串"""
    from app.models.evaluation import Evaluation

    evaluation = Evaluation(
        name="pending-eval",
        dataset_id=sample_dataset.id,
        metrics=["recall_k"],
        batch_size=5,
        status="pending",
        progress=0,
    )
    db_session.add(evaluation)
    await db_session.commit()
    await db_session.refresh(evaluation)

    response = await client.get(f"/api/v1/evaluations/{evaluation.id}")
    assert response.status_code == 200
    assert response.json()["error"] is None


@pytest.mark.asyncio
async def test_get_metric_categories(client: AsyncClient):
    """测试获取指标分类"""
    response = await client.get("/api/v1/metrics/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)