# 标注矫正结果模型
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel


class AnnotationCorrection(BaseModel):
    """标注矫正结果表"""
    __tablename__ = "annotation_corrections"

    # 关联调用结果
    invocation_result_id = Column(UUIDType(as_uuid=True), ForeignKey("invocation_results.id"), nullable=True, index=True)
    qa_record_id = Column(UUIDType(as_uuid=True), ForeignKey("qa_records.id"), nullable=True, index=True)
    batch_id = Column(UUIDType(as_uuid=True), ForeignKey("invocation_batches.id"), nullable=True, index=True)

    # 状态：pending/analyzing/completed/failed
    status = Column(String(50), default="pending")

    # 差异声明列表
    # 结构: [{"statement": "...", "source": "system/ground_truth", "type": "unique/conflicting"}]
    different_statements = Column(JSONType, default=list)

    # 证据验证结果
    # 结构: [{"statement": "...", "question": "...", "supported": bool,
    #         "supporting_chunks": [{"chunk_id": "...", "content": "...", "relevance_score": float}]}]
    evidence_results = Column(JSONType, default=list)

    # 是否存疑
    is_doubtful = Column(Boolean, default=False)
    doubt_reason = Column(Text, nullable=True)

    # 用户确认状态
    is_confirmed = Column(Boolean, default=False)
    confirmed_at = Column(DateTime, nullable=True)

    # 摘要
    summary = Column(Text, nullable=True)

    # 分析耗时
    analysis_duration = Column(Text, nullable=True)

    # 错误信息
    error = Column(Text, nullable=True)

    # 关系
    invocation_result = relationship("InvocationResult")
    qa_record = relationship("QARecord")
    batch = relationship("InvocationBatch")