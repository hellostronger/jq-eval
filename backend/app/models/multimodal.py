# 多模态嵌入模型评测
#
# 现有 qa_records + Evaluation 面向"RAG 调用 + LLM 打分"链路：问题与上下文都是
# 纯文本，指标依赖 LLM/文本 embedding。多模态嵌入模型（EmbeddingGemma 2、
# MMEB 类模型）的评测形态不同：拿一批 (query, candidate) 对，把两侧编码成向量，
# 按余弦相似度排序后算 Recall@k / MRR / nDCG。因此单独建表，不塞进 QARecord。
#
# 一条 mm_samples 是一对 (query, candidate)：同一 qid 的多行构成该查询的候选池，
# label=1 为正例。图片一律先落 MinIO，列里存 object key（不是 URL），保证
# 评测时不受源站可用性影响。
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, DateTime, Index
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel


class MMDataset(BaseModel):
    """多模态评测集（导入的 zip/jsonl 归一化后落库的容器）"""
    __tablename__ = "mm_datasets"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String(50), default="upload")  # upload
    status = Column(String(20), default="ready")  # importing/ready/failed
    error = Column(Text, nullable=True)

    record_count = Column(Integer, default=0)  # 样本对总数
    query_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    # {"T→I": {"queries": 100, "candidates": 500}, ...}
    subset_stats = Column(JSONType, default=dict)
    source_meta = Column(JSONType, default=dict)  # 原文件名/大小/解析统计


class MMSample(BaseModel):
    """(query, candidate) 对；同一 qid 的所有行共享 query 侧"""
    __tablename__ = "mm_samples"

    dataset_id = Column(
        UUIDType(as_uuid=True), ForeignKey("mm_datasets.id"), nullable=False, index=True
    )
    seq = Column(Integer, default=0)

    subset = Column(String(100), nullable=True, index=True)  # MMEB subset/task 或推断的模态组合
    qid = Column(String(200), nullable=False, index=True)

    query_text = Column(Text, nullable=True)
    query_image = Column(String(500), nullable=True)  # MinIO object key
    target_text = Column(Text, nullable=True)
    target_image = Column(String(500), nullable=True)

    label = Column(Integer, default=0)  # 1=相关
    sample_metadata = Column(JSONType, default=dict)

    __table_args__ = (
        Index("ix_mm_samples_dataset_qid", "dataset_id", "qid"),
    )


class MMEvalRun(BaseModel):
    """一次嵌入模型评测运行"""
    __tablename__ = "mm_eval_runs"

    name = Column(String(200), nullable=False)
    dataset_id = Column(
        UUIDType(as_uuid=True), ForeignKey("mm_datasets.id"), nullable=False, index=True
    )
    # 不设 FK：模型配置被删除时历史运行仍应可回看（训练数据画像同样处理）
    model_id = Column(UUIDType(as_uuid=True), nullable=False, index=True)
    model_snapshot = Column(JSONType, default=dict)  # 运行时的模型名/provider/endpoint

    status = Column(String(20), default="pending")  # pending/running/completed/failed/cancelled
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, default=False)

    # image_transport=data_url|url / request_format=content_array|messages|text_only
    # batch_size / normalize
    params = Column(JSONType, default=dict)

    query_count = Column(Integer, default=0)
    skipped_queries = Column(Integer, default=0)  # 候选池 <2 等原因跳过
    encoded_items = Column(Integer, default=0)

    # {"query_count": N, "recall@1": .., "recall@5": .., "recall@10": .., "mrr@10": .., "ndcg@10": ..}
    metrics = Column(JSONType, default=dict)
    subset_metrics = Column(JSONType, default=dict)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class MMEvalQueryResult(BaseModel):
    """单条查询的评测明细（badcase 排查用）"""
    __tablename__ = "mm_eval_query_results"

    run_id = Column(
        UUIDType(as_uuid=True), ForeignKey("mm_eval_runs.id"), nullable=False, index=True
    )
    subset = Column(String(100), nullable=True, index=True)
    qid = Column(String(200), nullable=False)
    rank = Column(Integer, nullable=True)  # 首个正例的排名（1 起）；无正例时为空（已跳过）
    candidate_count = Column(Integer, default=0)
    positive_count = Column(Integer, default=0)
    metrics = Column(JSONType, default=dict)
    retrieved_top = Column(JSONType, default=list)  # 前 10 候选（label/score/文本/图片 key）
