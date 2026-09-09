# RAG系统配置模型
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime
from sqlalchemy.orm import relationship
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel


class RAGSystemType(BaseModel):
    """RAG系统类型定义表（内置）"""
    __tablename__ = "rag_system_types"

    type_code = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # 连接配置Schema（JSON Schema格式）
    connection_schema = Column(JSONType, nullable=False)

    # 支持的能力
    capabilities = Column(JSONType, default=dict)

    # API文档链接
    api_doc_url = Column(String(500), nullable=True)

    # Logo/图标
    logo_url = Column(String(500), nullable=True)

    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class RAGSystem(BaseModel):
    """用户配置的RAG系统"""
    __tablename__ = "rag_systems"

    name = Column(String(100), nullable=False)
    system_type = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # 连接配置
    connection_config = Column(JSONType, nullable=False)

    # 模型配置（可选）
    llm_config = Column(JSONType, default=dict)

    # 检索配置
    retrieval_config = Column(JSONType, default=dict)

    # 状态
    status = Column(String(50), default="active")
    health_status = Column(String(50), nullable=True)
    health_check_at = Column(DateTime, nullable=True)

    # 统计
    total_calls = Column(Integer, default=0)
    last_call_at = Column(DateTime, nullable=True)

    # 所属用户
    owner_id = Column(UUIDType(as_uuid=True), nullable=True)

    # 关系
    invocation_batches = relationship("InvocationBatch", back_populates="rag_system")
    invocation_results = relationship("InvocationResult", back_populates="rag_system")
    load_tests = relationship("LoadTest", back_populates="rag_system")