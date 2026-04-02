# 模型配置表
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from .base import BaseModel


class Model(BaseModel):
    """模型配置表 (LLM/Embedding/Reranker)"""
    __tablename__ = "models"

    name = Column(String(200), nullable=False)
    model_type = Column(String(50), nullable=False)  # llm/embedding/reranker
    provider = Column(String(100), nullable=True)  # openai/anthropic/local/custom
    endpoint = Column(String(500), nullable=True)
    api_key_encrypted = Column(Text, nullable=True)
    params = Column(JSONB, default=dict)
    is_default = Column(Boolean, default=False)
    status = Column(String(50), default="active")  # active/inactive

    # Embedding特有字段
    dimension = Column(Integer, nullable=True)  # 向量维度
    max_input_length = Column(Integer, nullable=True)  # 最大输入长度