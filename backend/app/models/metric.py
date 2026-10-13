# 指标定义模型
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from ..core.db_types import ArrayType, JSONType, UUIDType
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

    # 作用域：指标归属哪套评估体系。
    #   rag           —— 检索/生成评估，compute(question, answer, contexts, ground_truth)
    #   training_data —— 训练数据质量评估，compute 额外吃 chosen/rejected/positive_doc 等字段
    # 两个体系的 compute 语义不同，故保留各自的基类，但统一落到本表作为指标市场的唯一数据源，
    # 避免"训练数据指标自成一套、下拉框直读内存注册表"导致市场里看不到、配置无处存放。
    scope = Column(String(20), nullable=False, default='rag', index=True)

    # 适用的训练数据类型，仅 scope='training_data' 有值
    # (llm/embedding/reranker/dpo/vlm/vla/reward_model)
    data_types = Column(ArrayType(String(50)), nullable=True)

    # 参数Schema（JSON Schema格式）
    params_schema = Column(JSONType, nullable=True)
    default_params = Column(JSONType, default=dict)

    # 依赖声明
    requires_llm = Column(Boolean, default=True)
    requires_embedding = Column(Boolean, default=False)
    requires_ground_truth = Column(Boolean, default=False)
    requires_contexts = Column(Boolean, default=False)

    # 输出范围
    range_min = Column(Float, default=0.0)
    range_max = Column(Float, default=1.0)
    higher_is_better = Column(Boolean, default=True)

    # 通过阈值（训练数据指标靠它产出"合格/不合格"标签，RAG 指标为 NULL）
    default_threshold = Column(Float, nullable=True)
    threshold_type = Column(String(20), nullable=True, default='min')  # min/max/range

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
    owner_id = Column(UUIDType(as_uuid=True), nullable=True)
    source_url = Column(String(500), nullable=True)

    # 统计
    usage_count = Column(Integer, default=0)
    rating_avg = Column(Float, nullable=True)
    rating_count = Column(Integer, default=0)


class Tag(BaseModel):
    """标签维护表 - 通用标签，支持多种使用场景"""
    __tablename__ = "tags"

    name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(20), nullable=True)  # 标签颜色
    icon = Column(String(50), nullable=True)  # 标签图标

    # 使用场景：qa_record/dataset/invocation_batch
    usage_scenario = Column(String(50), nullable=False, index=True)

    # 是否内置标签（内置标签不可删除）
    is_builtin = Column(Boolean, default=False)

    # 排序
    sort_order = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint('name', 'usage_scenario', name='tags_name_usage_scenario_key'),
    )


class EntityTag(BaseModel):
    """实体标签绑定表 - 用于给各种实体打标签"""
    __tablename__ = "entity_tags"

    # 实体类型：qa_record/dataset/invocation_batch
    entity_type = Column(String(50), nullable=False, index=True)
    # 实体ID
    entity_id = Column(UUIDType(as_uuid=True), nullable=False, index=True)
    # 标签ID
    tag_id = Column(UUIDType(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)

    # 关系
    tag = relationship("Tag")

    __table_args__ = (
        # 同一实体同一标签只能绑定一次
        # UniqueConstraint('entity_type', 'entity_id', 'tag_id', name='uq_entity_tag'),
    )