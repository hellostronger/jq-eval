# 评估任务 API 测试
import pytest
from httpx import AsyncClient
from app.models import Dataset, Model, RAGSystem


@pytest.mark.asyncio
async def test_list_evaluations(client: AsyncClient):
    """测试获取评估列表"""
    response = await client.get("/evaluations")
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
    response = await client.post("/evaluations", json={
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
    response = await client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_metric_categories(client: AsyncClient):
    """测试获取指标分类"""
    response = await client.get("/metrics/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)