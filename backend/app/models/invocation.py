# RAG系统调用结果模型
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class InvocationBatch(BaseModel):
    """RAG系统批量调用批次"""
    __tablename__ = "invocation_batches"

    name = Column(String(200), nullable=False)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    rag_system_id = Column(UUID(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True)

    # 状态
    status = Column(String(50), default="pending")  # pending/running/completed/failed
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    dataset = relationship("Dataset", back_populates="invocation_batches")
    rag_system = relationship("RAGSystem", back_populates="invocation_batches")
    results = relationship("InvocationResult", back_populates="batch", cascade="all, delete-orphan")


class InvocationResult(BaseModel):
    """单条RAG调用结果"""
    __tablename__ = "invocation_results"

    batch_id = Column(UUID(as_uuid=True), ForeignKey("invocation_batches.id"), nullable=False, index=True)
    qa_record_id = Column(UUID(as_uuid=True), ForeignKey("qa_records.id"), nullable=False, index=True)
    rag_system_id = Column(UUID(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True)

    # 问题快照
    question = Column(Text, nullable=False)

    # 调用结果
    answer = Column(Text, nullable=True)
    contexts = Column(JSONB, nullable=True)  # 检索到的上下文片段列表

    # 性能指标
    latency = Column(Float, nullable=True)  # 响应耗时（秒）

    # 状态
    status = Column(String(50), default="pending")  # pending/success/failed
    error = Column(Text, nullable=True)

    # 关系
    batch = relationship("InvocationBatch", back_populates="results")
    qa_record = relationship("QARecord", back_populates="invocation_results")
    rag_system = relationship("RAGSystem")
    eval_results = relationship("EvalResult", back_populates="invocation_result")