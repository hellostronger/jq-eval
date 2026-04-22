# 压测任务模型
import enum
from sqlalchemy import Column, String, Text, Integer, Float, ForeignKey, ARRAY, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class LoadTestStatus(str, enum.Enum):
    """压测状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LoadTestType(str, enum.Enum):
    """压测类型枚举"""
    FIRST_TOKEN = "first_token"  # 首token时间
    FULL_RESPONSE = "full_response"  # 完整响应时间


class LoadTestMode(str, enum.Enum):
    """压测模式枚举"""
    QPS_LIMIT = "qps_limit"  # QPS上限测试 - 自动递增并发找上限
    LATENCY_DIST = "latency_dist"  # 响应时间分布测试 - 多个并发级别测试


class LoadTest(BaseModel):
    """压测任务表"""
    __tablename__ = "load_tests"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 关联RAG系统
    rag_system_id = Column(UUID(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True)

    # 测试配置
    test_mode = Column(String(50), nullable=False, default=LoadTestMode.QPS_LIMIT.value)  # qps_limit / latency_dist
    test_type = Column(String(50), nullable=False, default=LoadTestType.FULL_RESPONSE.value)  # first_token / full_response
    latency_threshold = Column(Float, nullable=True)  # 时延阈值（秒），latency_dist模式下可选

    # QPS上限测试参数 (test_mode=qps_limit)
    initial_concurrency = Column(Integer, nullable=True, default=10)  # 起始并发数
    step = Column(Integer, nullable=True, default=10)  # 递增步长
    max_concurrency = Column(Integer, nullable=True, default=100)  # 最大并发上限

    # 响应时间分布测试参数 (test_mode=latency_dist)
    concurrency_levels = Column(JSONB, nullable=True)  # 并发级别数组，如 [1, 5, 10, 20, 50, 100]

    # 兼容旧字段（单次测试模式）
    concurrency = Column(Integer, nullable=True, default=1)  # 单次测试并发数（已废弃）

    # 测试数据来源
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True, index=True)
    questions = Column(JSONB, nullable=True)  # 用户输入的测试问题列表

    # 状态
    status = Column(String(50), default=LoadTestStatus.PENDING.value)
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # 结果
    result = Column(JSONB, nullable=True)  # 存储QPS、延迟分布等结果

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    rag_system = relationship("RAGSystem", back_populates="load_tests")
    dataset = relationship("Dataset")