# 数据集管理 API 测试
import pytest
from httpx import AsyncClient
from app.models import Model, Dataset


@pytest.mark.asyncio
async def test_list_datasets(client: AsyncClient, sample_dataset: Dataset):
    """测试获取数据集列表"""
    response = await client.get("/datasets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_dataset(client: AsyncClient, sample_dataset: Dataset):
    """测试获取数据集详情"""
    response = await client.get(f"/datasets/{sample_dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_dataset.id)
    assert data["name"] == sample_dataset.name


@pytest.mark.asyncio
async def test_create_dataset(client: AsyncClient):
    """测试创建数据集"""
    response = await client.post("/datasets", json={
        "name": "New Dataset",
        "description": "A new dataset"
    })
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["name"] == "New Dataset"


@pytest.mark.asyncio
async def test_delete_dataset(client: AsyncClient, sample_dataset: Dataset):
    """测试删除数据集"""
    response = await client.delete(f"/datasets/{sample_dataset.id}")
    assert response.status_code in [200, 204]


@pytest.mark.asyncio
async def test_generate_dataset_validation(client: AsyncClient, sample_dataset: Dataset):
    """测试生成数据集请求验证 - 缺少必要参数"""
    response = await client.post(f"/datasets/{sample_dataset.id}/generate", json={
        "sources": [],
        "test_size": 10
    })
    assert response.status_code == 400  # 应该返回验证错误


@pytest.mark.asyncio
async def test_generate_dataset_with_invalid_model(client: AsyncClient, sample_dataset: Dataset):
    """测试生成数据集 - 使用无效的模型ID"""
    response = await client.post(f"/datasets/{sample_dataset.id}/generate", json={
        "sources": [{"source_type": "text_input", "texts": ["test content"]}],
        "test_size": 10,
        "distributions": {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.2},
        "llm_model_id": "00000000-0000-0000-0000-000000000000",
        "embedding_model_id": "00000000-0000-0000-0000-000000000000"
    })
    assert response.status_code == 400  # 模型不存在