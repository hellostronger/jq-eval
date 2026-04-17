# 指标定义模型
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel


class MetricDefinition(BaseModel):
    """指标定义表"""
    __tablename__ = "metric_definitions"

    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    display_name_en = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)

    # 分类
    category = Column(String(50), nullable=False)  # retrieval/generation/quality/performance/custom
    framework = Column(String(50), nullable=True)  # ragas/evalscope/custom
    eval_stage = Column(String(20), nullable=False, default='result')  # process/result

    # 参数Schema（JSON Schema格式）
    params_schema = Column(JSONB, nullable=True)
    default_params = Column(JSONB, default=dict)

    # 依赖声明
    requires_llm = Column(Boolean, default=True)
    requires_embedding = Column(Boolean, default=False)
    requires_ground_truth = Column(Boolean, default=False)
    requires_contexts = Column(Boolean, default=False)

    # 输出范围
    range_min = Column(Float, default=0.0)
    range_max = Column(Float, default=1.0)
    higher_is_better = Column(Boolean, default=True)

    # 显示配置
    icon = Column(String(50), nullable=True)
    color = Column(String(20), nullable=True)
    weight = Column(Float, default=1.0)
    sort_order = Column(Integer, default=0)

    # 状态
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)

    # 来源
    owner_id = Column(UUID(as_uuid=True), nullable=True)
    source_url = Column(String(500), nullable=True)

    # 统计
    usage_count = Column(Integer, default=0)
    rating_avg = Column(Float, nullable=True)
    rating_count = Column(Integer, default=0)

    # 关系
    tags = relationship("MetricTag", back_populates="metric", cascade="all, delete-orphan")


class MetricTag(BaseModel):
    """指标标签表"""
    __tablename__ = "metric_tags"

    metric_id = Column(UUID(as_uuid=True), ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String(50), nullable=False)

    # 关系
    metric = relationship("MetricDefinition", back_populates="tags")

    __table_args__ = (
        # UniqueConstraint('metric_id', 'tag', name='uq_metric_tag'),
    )