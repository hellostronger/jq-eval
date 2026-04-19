# RAG 系统管理 API 测试
import pytest
from httpx import AsyncClient
from app.models import RAGSystem


@pytest.mark.asyncio
async def test_list_rag_systems(client: AsyncClient, sample_rag_system: RAGSystem):
    """测试获取 RAG 系统列表"""
    response = await client.get("/rag-systems")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_create_rag_system(client: AsyncClient):
    """测试创建 RAG 系统"""
    response = await client.post("/rag-systems", json={
        "name": "New RAG System",
        "system_type": "dify",
        "description": "A Dify RAG system",
        "connection_config": {"api_url": "http://dify.example.com", "api_key": "test"}
    })
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["name"] == "New RAG System"
    assert data["system_type"] == "dify"


@pytest.mark.asyncio
async def test_get_rag_system(client: AsyncClient, sample_rag_system: RAGSystem):
    """测试获取 RAG 系统详情"""
    response = await client.get(f"/rag-systems/{sample_rag_system.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_rag_system.id)
    assert data["name"] == sample_rag_system.name


@pytest.mark.asyncio
async def test_update_rag_system(client: AsyncClient, sample_rag_system: RAGSystem):
    """测试更新 RAG 系统"""
    response = await client.put(f"/rag-systems/{sample_rag_system.id}", json={
        "name": "Updated RAG System",
        "description": "Updated description"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated RAG System"


@pytest.mark.asyncio
async def test_delete_rag_system(client: AsyncClient, sample_rag_system: RAGSystem):
    """测试删除 RAG 系统"""
    response = await client.delete(f"/rag-systems/{sample_rag_system.id}")
    assert response.status_code in [200, 204]