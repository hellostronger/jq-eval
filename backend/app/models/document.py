# 文档和分片模型
from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.orm import relationship
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel

class Document(BaseModel):
    """文档表"""
    __tablename__ = "documents"

    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=True)
    file_path = Column(String(1000), nullable=True)
    file_type = Column(String(50), nullable=True)
    source_type = Column(String(50), nullable=True)  # upload/huggingface/api/sync
    source_url = Column(String(1000), nullable=True)
    content_hash = Column(String(64), nullable=True)
    doc_metadata = Column(JSONType, default=dict)
    # 归属数据集（数据集内触发解析/创建的文档）；全局文档为 NULL
    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=True, index=True)

    # 关系
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(BaseModel):
    """分片表"""
    __tablename__ = "chunks"

    doc_id = Column(UUIDType(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)

    # Milvus向量相关
    milvus_id = Column(String(100), nullable=True, index=True)
    embedding_model = Column(String(100), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)

    chunk_metadata = Column(JSONType, default=dict)

    # 关系
    document = relationship("Document", back_populates="chunks")

    # 唯一约束
    __table_args__ = (
        # UniqueConstraint('doc_id', 'chunk_index', name='uq_chunk_doc_index'),
    )