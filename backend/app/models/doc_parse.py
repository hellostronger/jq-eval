# 文档解析模型（minerU 等解析服务）
from sqlalchemy import Column, String, Text, Integer, Float, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class DocParseBatch(BaseModel):
    """文档解析批次表：一次提交多个源文件给解析服务"""
    __tablename__ = "doc_parse_batches"

    name = Column(String(200), nullable=False)
    # 解析服务（models 表中 model_type=doc_parser 的记录）
    parser_model_id = Column(UUID(as_uuid=True), ForeignKey("models.id"), nullable=False, index=True)
    parser_model_name = Column(String(200), nullable=True)

    # 状态: pending/running/completed/failed
    status = Column(String(50), default="pending")
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 解析参数快照（language/output_format/is_ocr 等）
    config = Column(JSONB, default=dict)

    # 统计
    total_files = Column(Integer, default=0)
    success_files = Column(Integer, default=0)
    failed_files = Column(Integer, default=0)

    # 评估汇总（评估后写入）
    evaluation_summary = Column(JSONB, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    results = relationship("DocParseResult", back_populates="batch", cascade="all, delete-orphan")


class DocParseResult(BaseModel):
    """单文件解析结果"""
    __tablename__ = "doc_parse_results"

    batch_id = Column(UUID(as_uuid=True), ForeignKey("doc_parse_batches.id", ondelete="CASCADE"), nullable=False, index=True)

    # 源文件（MinIO documents bucket）
    file_name = Column(String(500), nullable=False)
    object_name = Column(String(1000), nullable=False)
    file_size = Column(Integer, nullable=True)

    # 状态: pending/running/success/failed
    status = Column(String(50), default="pending")
    error = Column(Text, nullable=True)

    # 解析产物
    md_content = Column(Text, nullable=True)          # full.md
    content_list = Column(JSONB, nullable=True)       # {file}_content_list.json
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)  # 生成的 Document

    # 中间状态（官方API）：task_id / batch_id
    remote_task_id = Column(String(200), nullable=True)

    # 耗时（秒）
    duration = Column(Float, nullable=True)

    # 解析质量评估结果
    evaluation = Column(JSONB, nullable=True)

    completed_at = Column(DateTime, nullable=True)

    batch = relationship("DocParseBatch", back_populates="results")
    document = relationship("Document")
