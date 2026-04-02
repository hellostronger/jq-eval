# 评估任务和结果模型
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, ARRAY, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class Evaluation(BaseModel):
    """评估任务表"""
    __tablename__ = "evaluations"

    name = Column(String(200), nullable=False)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)

    # 评估配置
    config = Column(JSONB, nullable=False)
    metrics = Column(ARRAY(String), nullable=False)

    # 关联RAG系统（可选）
    rag_system_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)

    # 状态
    status = Column(String(50), default="pending")  # pending/running/completed/failed
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 结果汇总
    summary = Column(JSONB, nullable=True)

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    dataset = relationship("Dataset", back_populates="evalations")
    results = relationship("EvalResult", back_populates="evaluation", cascade="all, delete-orphan")
    metric_configs = relationship("EvaluationMetricConfig", back_populates="evaluation", cascade="all, delete-orphan")


class EvaluationMetricConfig(BaseModel):
    """评估指标配置表"""
    __tablename__ = "evaluation_metric_configs"

    eval_id = Column(UUID(as_uuid=True), ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id = Column(UUID(as_uuid=True), ForeignKey("metric_definitions.id"), nullable=False)

    # 用户自定义参数
    params = Column(JSONB, default=dict)
    weight = Column(Float, default=1.0)
    enabled = Column(Boolean, default=True)

    # 关系
    evaluation = relationship("Evaluation", back_populates="metric_configs")


class EvalResult(BaseModel):
    """评估结果表"""
    __tablename__ = "eval_results"

    eval_id = Column(UUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=False, index=True)
    qa_record_id = Column(UUID(as_uuid=True), ForeignKey("qa_records.id"), nullable=False, index=True)

    # 评估时的检索结果快照
    retrieved_chunks_snapshot = Column(JSONB, nullable=True)

    # 各指标得分
    scores = Column(JSONB, nullable=False)

    # 详细分析过程
    details = Column(JSONB, nullable=True)

    # 关系
    evaluation = relationship("Evaluation", back_populates="results")
    qa_record = relationship("QARecord", back_populates="eval_results")