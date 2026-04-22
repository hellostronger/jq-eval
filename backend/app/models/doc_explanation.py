# 文档解释评估模型
import enum
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, ARRAY, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class DocExplanationStatus(str, enum.Enum):
    """解释状态枚举"""
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class DocExplanation(BaseModel):
    """文档解释表"""
    __tablename__ = "doc_explanations"

    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    explanation = Column(Text, nullable=False)
    source = Column(String(50), default="manual")
    status = Column(String(50), default=DocExplanationStatus.DRAFT.value)

    created_by = Column(UUID(as_uuid=True), nullable=True)

    explanation_metadata = Column(JSONB, default=dict)

    document = relationship("Document")


class DocExplanationEvalStatus(str, enum.Enum):
    """评估状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocExplanationEvaluation(BaseModel):
    """文档解释评估任务表"""
    __tablename__ = "doc_explanation_evaluations"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    llm_model_id = Column(UUID(as_uuid=True), ForeignKey("models.id"), nullable=False, index=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True, index=True)

    doc_ids = Column(JSONB, nullable=True)
    metrics = Column(ARRAY(String), nullable=False, default=["completeness", "accuracy", "info_missing", "explanation_error"])

    batch_size = Column(Integer, default=10)

    status = Column(String(50), default=DocExplanationEvalStatus.PENDING.value)
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    summary = Column(JSONB, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    llm_model = relationship("Model")
    dataset = relationship("Dataset")
    results = relationship("DocExplanationEvalResult", back_populates="evaluation", cascade="all, delete-orphan")


class DocExplanationEvalResult(BaseModel):
    """文档解释评估结果表"""
    __tablename__ = "doc_explanation_eval_results"

    eval_id = Column(UUID(as_uuid=True), ForeignKey("doc_explanation_evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    explanation_id = Column(UUID(as_uuid=True), ForeignKey("doc_explanations.id", ondelete="CASCADE"), nullable=False, index=True)

    scores = Column(JSONB, nullable=False, default=dict)
    details = Column(JSONB, nullable=True)

    evaluation = relationship("DocExplanationEvaluation", back_populates="results")
    document = relationship("Document")
    explanation = relationship("DocExplanation")