# 数据集和QA记录模型
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel


class Dataset(BaseModel):
    """数据集表"""
    __tablename__ = "datasets"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String(50), nullable=True)
    source_url = Column(String(1000), nullable=True)
    record_count = Column(Integer, default=0)

    # 数据完整性标记
    has_ground_truth = Column(Boolean, default=False)
    has_contexts = Column(Boolean, default=False)

    status = Column(String(50), default="draft")  # draft/ready/archived
    dataset_metadata = Column(JSONB, default=dict)

    # 关系
    qa_records = relationship("QARecord", back_populates="dataset", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="dataset")


class QARecord(BaseModel):
    """QA评估记录表"""
    __tablename__ = "qa_records"

    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)

    # 问题与答案
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    ground_truth = Column(Text, nullable=True)

    # 关联原始分片（引用）
    doc_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)
    target_chunk_ids = Column(ARRAY(UUID(as_uuid=True)), default=list)

    # 快照（冻结历史数据）
    snapshot = Column(JSONB, default=dict)

    # 元信息
    question_type = Column(String(50), nullable=True)  # simple/complex/multi_hop
    difficulty = Column(String(20), nullable=True)  # easy/medium/hard
    qa_metadata = Column(JSONB, default=dict)

    # 关系
    dataset = relationship("Dataset", back_populates="qa_records")
    eval_results = relationship("EvalResult", back_populates="qa_record")