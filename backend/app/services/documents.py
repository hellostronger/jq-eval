# 文档共享服务：文档提取/创建/响应构建，供 datasets 与 doc_explanations 等路由复用
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord
from app.models.document import Document, Chunk


def extract_text_from_upload(file_content: bytes, filename: Optional[str]) -> str:
    """按扩展名提取上传文件的文本内容（txt/md 直接解码，pdf 用 PyMuPDF）"""
    file_ext = filename.rsplit(".", 1)[-1].lower() if filename else "txt"

    if file_ext in ("txt", "md"):
        content = file_content.decode("utf-8", errors="ignore")
    elif file_ext == "pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise HTTPException(status_code=400, detail="PDF处理库未安装，请安装 PyMuPDF")
        pdf_doc = fitz.open(stream=file_content, filetype="pdf")
        content = "".join(page.get_text() for page in pdf_doc)
        pdf_doc.close()
    else:
        content = file_content.decode("utf-8", errors="ignore")

    return content


async def create_document(
    db: AsyncSession, title: str, content: str, file_type: str,
    source_type: str, dataset_id: Optional[UUID] = None,
    doc_metadata: Optional[dict] = None,
) -> Document:
    """创建并落库文档（不自动分片；dataset_id 归属数据集时填写）"""
    document = Document(
        title=title,
        content=content,
        file_type=file_type,
        source_type=source_type,
        dataset_id=dataset_id,
        doc_metadata=doc_metadata or {},
    )
    db.add(document)
    await db.flush()
    return document


async def count_chunks(db: AsyncSession, doc_id) -> int:
    result = await db.execute(select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id))
    return result.scalar() or 0


async def chunk_counts_for(db: AsyncSession, doc_ids: list) -> dict:
    """批量统计多个文档的 chunk 数量，返回 {doc_id: count}"""
    if not doc_ids:
        return {}
    rows = await db.execute(
        select(Chunk.doc_id, func.count(Chunk.id)).where(Chunk.doc_id.in_(doc_ids)).group_by(Chunk.doc_id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def refresh_dataset_stats(db: AsyncSession, dataset_id, added: int = 0, removed: int = 0,
                                mark_ground_truth: Optional[bool] = None,
                                mark_contexts: Optional[bool] = None) -> None:
    """更新数据集统计（record_count 与 has_ground_truth/has_contexts 标记）

    added/removed: 本次增删的记录数，直接累加到 record_count。
    mark_ground_truth/mark_contexts: True 表示本批记录确认含标准答案/上下文，
        只置位不清除；None 表示不修改。
    """
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        return
    dataset.record_count = (dataset.record_count or 0) + added - removed
    if mark_ground_truth:
        dataset.has_ground_truth = True
    if mark_contexts:
        dataset.has_contexts = True

