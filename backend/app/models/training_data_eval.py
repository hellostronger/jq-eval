# 训练数据评估模型
import enum
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, ARRAY, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import Optional

from .base import BaseModel


class TrainingDataType(str, enum.Enum):
    """训练数据类型"""
    LLM = "llm"  # 大模型训练数据
    EMBEDDING = "embedding"  # Embedding训练数据
    RERANKER = "reranker"  # Reranker训练数据
    REWARD_MODEL = "reward_model"  # 奖励模型训练数据
    DPO = "dpo"  # DPO训练数据
    VLM = "vlm"  # VLM训练数据
    VLA = "vla"  # VLA训练数据


class TrainingDataEvalStatus(str, enum.Enum):
    """训练数据评估状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingDataEval(BaseModel):
    """训练数据评估任务表"""
    __tablename__ = "training_data_evals"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 数据关联
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)

    # 训练数据类型
    data_type = Column(String(50), nullable=False)  # llm/embedding/reranker/reward_model/dpo/vlm/vla

    # 评估配置
    config = Column(JSONB, default=dict)
    metrics = Column(ARRAY(String), nullable=False)

    # 状态
    status = Column(String(50), default="pending")
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 结果汇总
    summary = Column(JSONB, nullable=True)

    # 统计数据
    total_samples = Column(Integer, default=0)
    passed_samples = Column(Integer, default=0)
    failed_samples = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)

    # 质量分布
    quality_distribution = Column(JSONB, nullable=True)

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    dataset = relationship("Dataset", back_populates="training_data_evals")
    results = relationship("TrainingDataEvalResult", back_populates="evaluation", cascade="all, delete-orphan")
    metric_configs = relationship("TrainingDataMetricConfig", back_populates="evaluation", cascade="all, delete-orphan")


class TrainingDataMetricConfig(BaseModel):
    """训练数据评估指标配置表"""
    __tablename__ = "training_data_metric_configs"

    eval_id = Column(UUID(as_uuid=True), ForeignKey("training_data_evals.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    metric_type = Column(String(50), nullable=False)  # quality/diversity/completeness/consistency/safety

    # 用户自定义参数
    params = Column(JSONB, default=dict)
    weight = Column(Float, default=1.0)
    enabled = Column(Boolean, default=True)

    # 阈值配置
    threshold = Column(Float, nullable=True)
    threshold_type = Column(String(20), nullable=True)  # min/max/range

    # 关系
    evaluation = relationship("TrainingDataEval", back_populates="metric_configs")


class TrainingDataEvalResult(BaseModel):
    """训练数据评估结果表"""
    __tablename__ = "training_data_eval_results"

    eval_id = Column(UUID(as_uuid=True), ForeignKey("training_data_evals.id"), nullable=False, index=True)
    qa_record_id = Column(UUID(as_uuid=True), ForeignKey("qa_records.id"), nullable=False, index=True)

    # 各指标得分
    scores = Column(JSONB, nullable=False)

    # 详细分析过程
    details = Column(JSONB, nullable=True)

    # 质量标签
    quality_tags = Column(ARRAY(String), default=list)
    issues = Column(ARRAY(String), default=list)
    suggestions = Column(ARRAY(String), default=list)

    # 样本状态
    status = Column(String(20), default="passed")  # passed/failed/warning
    overall_score = Column(Float, default=0.0)

    # 关系
    evaluation = relationship("TrainingDataEval", back_populates="results")
    qa_record = relationship("QARecord", back_populates="training_data_eval_results")


class TrainingQualityChecker(BaseModel):
    """训练数据质量规则表"""
    __tablename__ = "training_quality_rules"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 规则适用的训练数据类型
    data_types = Column(ARRAY(String), default=list)  # ["llm", "embedding", ...]

    # 规则类型
    rule_type = Column(String(50), nullable=False)  # length/diversity/similarity/format/content/safety

    # 规则配置
    config = Column(JSONB, default=dict)

    # 阈值
    threshold_min = Column(Float, nullable=True)
    threshold_max = Column(Float, nullable=True)

    # 严重程度
    severity = Column(String(20), default="warning")  # error/warning/info

    # 自动修复
    auto_fixable = Column(Boolean, default=False)
    fix_config = Column(JSONB, nullable=True)

    # 状态
    is_enabled = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)

    # 使用统计
    usage_count = Column(Integer, default=0)
    pass_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)

    # 创建者
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)


class TrainingDataTemplate(BaseModel):
    """训练数据评估模版表"""
    __tablename__ = "training_data_templates"

    name = Column(String(200), nullable=False, unique=True)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 训练数据类型
    data_type = Column(String(50), nullable=False)

    # 适用的数据集类型
    dataset_types = Column(ARRAY(String), default=list)

    # 推荐的指标配置
    metric_configs = Column(JSONB, default=list)

    # 推荐的阈值
    default_thresholds = Column(JSONB, default=dict)

    # 样例数据
    sample_data = Column(JSONB, nullable=True)

    # 状态
    is_builtin = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)

    # 使用统计
    usage_count = Column(Integer, default=0)

    # 排序
    sort_order = Column(Integer, default=0)
