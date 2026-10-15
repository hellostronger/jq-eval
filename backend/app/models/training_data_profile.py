# 训练数据画像模型
#
# 现有 qa_records 表面向 RAG 问答评估（question/answer/ground_truth/contexts），
# 而真实训练数据（UltraData 等）是预训练纯文本、多轮对话列表、Agent 轨迹
# （messages+tools）、偏好对（chosen/rejected）等形态，无法映射到 QA 结构。
# 因此新增两张表：
#   training_data_records —— 训练样本落库（原始 payload + 归一化列，可回读可重算）
#   training_data_profiles —— 数据集级画像（概览/字段/分类/质量/样本预览）
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from ..core.db_types import ArrayType, JSONType, UUIDType
from .base import BaseModel


class TrainingDataRecord(BaseModel):
    """训练数据样本表（兼容任意训练数据格式）"""
    __tablename__ = "training_data_records"

    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    seq = Column(Integer, default=0)  # 导入顺序，保证样本预览稳定

    # 归一化列（画像直接按这些列聚合，不必反复解 payload）
    format = Column(String(20), default="other")  # sft/chat/preference/agent/pretrain/qa/other
    language = Column(String(20), nullable=True)  # zh/en/mixed/other
    labels = Column(ArrayType(String), default=list)  # 领域标签（代码/数学/对话…）

    instruction = Column(Text, nullable=True)
    response = Column(Text, nullable=True)
    text = Column(Text, nullable=True)        # 预训练正文
    messages = Column(JSONType, nullable=True)  # 多轮消息 [{role, content}]
    score = Column(Float, nullable=True)      # 数据自带质量分（如 Ultra-FineWeb score）

    char_length = Column(Integer, default=0)
    est_tokens = Column(Integer, default=0)
    content_hash = Column(String(64), nullable=True, index=True)  # 去重
    turn_count = Column(Integer, default=0)   # 消息条数（注意：不是轮次）
    round_count = Column(Integer, default=0, index=True)  # 对话轮次（user 消息数），画像按它统计
    has_tools = Column(Boolean, default=False)

    payload = Column(JSONType, default=dict)          # 原始记录，原样保留
    record_metadata = Column(JSONType, default=dict)  # 归一化时摘出的附加字段

    dataset = relationship("Dataset", back_populates="training_data_records")


class TrainingDataProfile(BaseModel):
    """训练数据画像表（数据集级概览 + 分类 + 质量画像）"""
    __tablename__ = "training_data_profiles"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    source = Column(String(50), default="dataset")  # dataset/ultradata

    # 画像结果
    format = Column(String(20), nullable=True)  # 主格式（占比最高的样本格式）
    level = Column(String(10), nullable=True)   # 借 UltraData L1-L4 口径的层级建议
    tags = Column(ArrayType(String), default=list)

    status = Column(String(20), default="pending")  # pending/running/completed/failed
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    total_samples = Column(Integer, default=0)
    unique_samples = Column(Integer, default=0)
    duplicate_rate = Column(Float, default=0.0)
    sampled = Column(Boolean, default=False)  # 是否只统计了前 N 条

    overview = Column(JSONType, nullable=True)        # 规模 / 长度 / token 概览
    schema_profile = Column(JSONType, nullable=True)  # 字段画像（覆盖率/类型/值分布/示例）
    classification = Column(JSONType, nullable=True)  # 格式/语言/领域/长度分布
    quality = Column(JSONType, nullable=True)         # 质量信号
    samples = Column(JSONType, nullable=True)         # 样本预览
    summary = Column(Text, nullable=True)             # 规则生成的自然语言摘要（一眼看懂全貌）

    # LLM 深度分析（可选）：off=不调 LLM / sample=抽样过一遍 / full=逐条过一遍（分批）
    llm_mode = Column(String(20), default="off")
    llm_model_id = Column(UUIDType(as_uuid=True), nullable=True)
    llm_sample_size = Column(Integer, default=40)
    llm_analysis = Column(JSONType, nullable=True)    # LLM 结论（摘要/特征/建议/风险…）

    source_meta = Column(JSONType, nullable=True)  # 外部来源元数据（UltraData 目录项）
    completed_at = Column(DateTime, nullable=True)

    dataset = relationship("Dataset", back_populates="profiles")
