# 模型管理 API 测试
import pytest
from httpx import AsyncClient
from app.models import Model


@pytest.mark.asyncio
async def test_list_llm_models(client: AsyncClient, sample_llm_model: Model):
    """测试获取 LLM 模型列表"""
    response = await client.get("/models?type=llm")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(m["model_type"] == "llm" for m in data)


@pytest.mark.asyncio
async def test_list_embedding_models(client: AsyncClient, sample_embedding_model: Model):
    """测试获取 Embedding 模型列表"""
    response = await client.get("/models?type=embedding")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(m["model_type"] == "embedding" for m in data)


@pytest.mark.asyncio
async def test_create_model(client: AsyncClient):
    """测试创建模型"""
    response = await client.post("/models", json={
        "name": "New LLM Model",
        "model_type": "llm",
        "provider": "anthropic",
        "model_name": "claude-3",
        "endpoint": "https://api.anthropic.com",
        "api_key": "test-api-key",
        "params": {"temperature": 0.5, "max_tokens": 2000},
        "is_default": False,
        "status": "active"
    })
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["name"] == "New LLM Model"
    assert data["model_type"] == "llm"


@pytest.mark.asyncio
async def test_get_model(client: AsyncClient, sample_llm_model: Model):
    """测试获取单个模型"""
    response = await client.get(f"/models/{sample_llm_model.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_llm_model.id)
    assert data["name"] == sample_llm_model.name


@pytest.mark.asyncio
async def test_update_model(client: AsyncClient, sample_llm_model: Model):
    """测试更新模型"""
    response = await client.put(f"/models/{sample_llm_model.id}", json={
        "name": "Updated LLM",
        "params": {"temperature": 0.9, "max_tokens": 500}
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated LLM"


@pytest.mark.asyncio
async def test_delete_model(client: AsyncClient, sample_llm_model: Model):
    """测试删除模型"""
    response = await client.delete(f"/models/{sample_llm_model.id}")
    assert response.status_code in [200, 204]

    # 验证已删除
    response = await client.get(f"/models/{sample_llm_model.id}")
    assert response.status_code == 404