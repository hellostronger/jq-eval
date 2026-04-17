# 已有文档适配器
from typing import List, Dict, Any
from langchain.schema import Document
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import logging

from .base import DocumentAdapter
from app.models.document import Document as DBDocument, Chunk

logger = logging.getLogger(__name__)


class ExistingDocAdapter(DocumentAdapter):
    """已有文档选择适配器

    从数据库中已有的 Document/Chunk 加载
    """

    def __init__(self, document_ids: List[UUID], db: AsyncSession):
        """初始化

        Args:
            document_ids: 文档 ID 列表
            db: 数据库会话
        """
        self.document_ids = document_ids
        self.db = db

    async def load(self) -> List[Document]:
        """从数据库加载文档"""
        documents = []

        for doc_id in self.document_ids:
            try:
                # 查询文档
                result = await self.db.execute(
                    select(DBDocument).where(DBDocument.id == doc_id)
                )
                db_doc = result.scalar_one_or_none()

                if not db_doc:
                    logger.warning(f"文档 {doc_id} 不存在")
                    continue

                # 查询文档的分片
                chunks_result = await self.db.execute(
                    select(Chunk)
                    .where(Chunk.doc_id == doc_id)
                    .order_by(Chunk.chunk_index)
                )
                chunks = chunks_result.scalars().all()

                if chunks:
                    # 使用分片内容
                    for chunk in chunks:
                        doc = Document(
                            page_content=chunk.content,
                            metadata={
                                "source": f"document:{doc_id}",
                                "chunk_id": str(chunk.id),
                                "chunk_index": chunk.chunk_index,
                                "doc_title": db_doc.title,
                            }
                        )
                        documents.append(doc)
                else:
                    # 如果没有分片，使用文档原文
                    if db_doc.content:
                        doc = Document(
                            page_content=db_doc.content,
                            metadata={
                                "source": f"document:{doc_id}",
                                "doc_title": db_doc.title,
                                "file_path": db_doc.file_path,
                            }
                        )
                        documents.append(doc)

            except Exception as e:
                logger.error(f"加载文档 {doc_id} 失败: {e}")
                continue

        logger.info(f"从已有文档加载了 {len(documents)} 个分片/文档")
        return documents

    def get_source_info(self) -> Dict[str, Any]:
        """获取源信息"""
        return {
            "type": "existing_doc",
            "document_ids": [str(id) for id in self.document_ids],
            "document_count": len(self.document_ids)
        }