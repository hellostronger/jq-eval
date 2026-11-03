# RAG系统调用结果模型
from sqlalchemy import Column, String, Text, Integer, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel


class InvocationBatch(BaseModel):
    """RAG系统批量调用批次"""
    __tablename__ = "invocation_batches"

    name = Column(String(200), nullable=False)
    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    rag_system_id = Column(UUIDType(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True)

    # 状态
    status = Column(String(50), default="pending")  # pending/running/completed/failed/cancelled
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 取样范围：批次默认把整个数据集跑一遍，而大语料（MultiHop 2556 题、
    # UltraData 每题几分钟）根本没法"先试 40 题"。原先只能再建一个小数据集绕开，
    # 于是同一份语料在库里出现 N 份副本，评估口径还各不相同。
    # 这两列让批次自己决定跑哪一段，进度/重试/终态反推都以它为准。
    qa_limit = Column(Integer, nullable=True)    # 只跑前 N 条（按 created_at 排序）
    qa_offset = Column(Integer, nullable=True)   # 跳过前 M 条，配合 qa_limit 分页试点
    # 协作式取消标志：跑一个批次要几十分钟（慢速 RAG 单条 8min+），
    # 之前只能 SIGKILL worker，批次永远停在 running，既不能重试也无法判定。
    cancel_requested = Column(Boolean, nullable=False, default=False)

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    dataset = relationship("Dataset", back_populates="invocation_batches")
    rag_system = relationship("RAGSystem", back_populates="invocation_batches")
    results = relationship("InvocationResult", back_populates="batch", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="invocation_batch")


class InvocationResult(BaseModel):
    """单条RAG调用结果"""
    __tablename__ = "invocation_results"

    batch_id = Column(UUIDType(as_uuid=True), ForeignKey("invocation_batches.id"), nullable=False, index=True)
    qa_record_id = Column(UUIDType(as_uuid=True), ForeignKey("qa_records.id"), nullable=False, index=True)
    rag_system_id = Column(UUIDType(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True)

    # 问题快照
    question = Column(Text, nullable=False)

    # 调用结果
    answer = Column(Text, nullable=True)
    contexts = Column(JSONType, nullable=True)  # 检索到的上下文片段列表
    retrieval_ids = Column(JSONType, nullable=True)  # 检索到的chunk ID列表（用于检索指标计算）

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