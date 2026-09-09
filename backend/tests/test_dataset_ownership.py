# 数据集子资源归属校验回归测试
#
# 曾经的 bug：/{dataset_id}/documents/{doc_id}、/{dataset_id}/chunks/{chunk_id} 等
# 端点按 doc_id/chunk_id 直取，不校验归属——任意数据集路径可读任意文档/分片（越权读）。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset
from app.services.documents import create_document
from app.models.document import Chunk


async def _make_doc_in(db: AsyncSession, dataset: Dataset, title: str) -> dict:
    document = await create_document(
        db, title=title, content="正文内容", file_type="txt",
        source_type="upload", dataset_id=dataset.id,
    )
    chunk = Chunk(doc_id=document.id, content="分片内容", chunk_index=0)
    db.add(chunk)
    await db.commit()
    await db.refresh(document)
    await db.refresh(chunk)
    return {"doc_id": str(document.id), "chunk_id": str(chunk.id)}


@pytest.mark.asyncio
async def test_document_detail_cross_dataset_404(
    client: AsyncClient, db_session: AsyncSession,
    sample_dataset: Dataset,
):
    """归属 datasetA 的文档不能经 datasetB 路径读取"""
    other = Dataset(name="Other Dataset", status="active")
    db_session.add(other)
    await db_session.commit()

    ids = await _make_doc_in(db_session, sample_dataset, "doc-a")

    # 本数据集内可读
    ok = await client.get(f"/api/v1/datasets/{sample_dataset.id}/documents/{ids['doc_id']}")
    assert ok.status_code == 200

    # 越界按 404（不泄露资源是否存在）
    cross = await client.get(f"/api/v1/datasets/{other.id}/documents/{ids['doc_id']}")
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_chunk_detail_cross_dataset_404(
    client: AsyncClient, db_session: AsyncSession,
    sample_dataset: Dataset,
):
    """归属 datasetA 文档的分片不能经 datasetB 路径读取"""
    other = Dataset(name="Other Dataset 2", status="active")
    db_session.add(other)
    await db_session.commit()

    ids = await _make_doc_in(db_session, sample_dataset, "doc-b")

    ok = await client.get(f"/api/v1/datasets/{sample_dataset.id}/chunks/{ids['chunk_id']}")
    assert ok.status_code == 200

    cross = await client.get(f"/api/v1/datasets/{other.id}/chunks/{ids['chunk_id']}")
    assert cross.status_code == 404
