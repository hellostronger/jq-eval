# 数据集管理 API 测试
import io
import json
import pytest
from httpx import AsyncClient
from app.models import Model, Dataset


@pytest.mark.asyncio
async def test_list_datasets(client: AsyncClient, sample_dataset: Dataset):
    """测试获取数据集列表"""
    response = await client.get("/api/v1/datasets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_import_invalid_json_returns_400(client: AsyncClient, sample_dataset: Dataset):
    """导入格式错误的 JSON 应返回 400 可读错误，而不是 500"""
    files = {"file": ("bad.json", io.BytesIO(b"{not valid json"), "application/json")}
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/import", files=files)
    assert response.status_code == 400
    assert "文件解析失败" in response.json()["detail"]


@pytest.mark.asyncio
async def test_import_csv_unbound_logger_regression(client: AsyncClient, sample_dataset: Dataset):
    """CSV 导入回归：函数内曾重复给 logger 赋值导致 UnboundLocalError（500）"""
    csv_content = "question,answer,ground_truth\nQ1,A1,G1\nQ2,A2,G2\n"
    files = {"file": ("data.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/import", files=files)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["imported_count"] == 2


@pytest.mark.asyncio
async def test_import_unsupported_filename_returns_400(client: AsyncClient, sample_dataset: Dataset):
    """无扩展名/无 filename 不应 AttributeError 500"""
    files = {"file": ("data.exe", io.BytesIO(b"binary"), "application/octet-stream")}
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/import", files=files)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_has_ground_truth_marked_with_answer_only_records(client: AsyncClient, db_session, sample_dataset: Dataset):
    """只含 answer 的记录导入后 has_ground_truth 应置位（与保存回退逻辑同源）"""
    records = [{"question": "Q1", "answer": "A1"}]
    files = {"file": ("d.json", io.BytesIO(json.dumps(records).encode()), "application/json")}
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/import", files=files)
    assert response.status_code == 200

    await db_session.refresh(sample_dataset)
    assert sample_dataset.has_ground_truth is True
    assert sample_dataset.record_count == 1


@pytest.mark.asyncio
async def test_get_dataset(client: AsyncClient, sample_dataset: Dataset):
    """测试获取数据集详情"""
    response = await client.get(f"/api/v1/datasets/{sample_dataset.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_dataset.id)
    assert data["name"] == sample_dataset.name


@pytest.mark.asyncio
async def test_create_dataset(client: AsyncClient):
    """测试创建数据集"""
    response = await client.post("/api/v1/datasets", json={
        "name": "New Dataset",
        "description": "A new dataset"
    })
    assert response.status_code in [200, 201]
    data = response.json()
    assert data["name"] == "New Dataset"


@pytest.mark.asyncio
async def test_delete_dataset(client: AsyncClient, sample_dataset: Dataset):
    """测试删除数据集"""
    response = await client.delete(f"/api/v1/datasets/{sample_dataset.id}")
    assert response.status_code in [200, 204]


@pytest.mark.asyncio
async def test_generate_dataset_validation(client: AsyncClient, sample_dataset: Dataset):
    """测试生成数据集请求验证 - 缺少必要参数（schema 校验失败为 422）"""
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/generate", json={
        "sources": [],
        "test_size": 10
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_dataset_with_invalid_model(client: AsyncClient, sample_dataset: Dataset):
    """测试生成数据集 - 使用无效的模型ID"""
    response = await client.post(f"/api/v1/datasets/{sample_dataset.id}/generate", json={
        "sources": [{"source_type": "text_input", "texts": ["test content"]}],
        "test_size": 10,
        "distributions": {"simple": 0.5, "reasoning": 0.3, "multi_context": 0.2},
        "llm_model_id": "00000000-0000-0000-0000-000000000000",
        "embedding_model_id": "00000000-0000-0000-0000-000000000000"
    })
    assert response.status_code == 400  # 模型不存在