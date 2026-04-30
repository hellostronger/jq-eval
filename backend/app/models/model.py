# 模型配置表
from sqlalchemy import Column, String, Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB

from .base import BaseModel


class Model(BaseModel):
    """模型配置表 (LLM/Embedding/Reranker)"""
    __tablename__ = "models"

    name = Column(String(200), nullable=False)
    model_type = Column(String(50), nullable=False)  # llm/embedding/reranker
    provider = Column(String(100), nullable=True)  # openai/anthropic/local/custom
    model_name = Column(String(200), nullable=True)  # 模型名称，如 gpt-4o-mini
    endpoint = Column(String(500), nullable=True)  # API地址
    api_key_encrypted = Column(Text, nullable=True)  # API密钥（加密存储）
    params = Column(JSONB, nullable=True)  # 参数配置，如 temperature, max_tokens
    is_default = Column(Boolean, default=False)
    status = Column(String(50), default="active")  # active/inactive

    # Embedding特有字段
    dimension = Column(Integer, nullable=True)  # 向量维度
    max_input_length = Column(Integer, nullable=True)  # 最大输入长度

    # 日志保存
    save_logs = Column(Boolean, default=False)  # 是否保存请求响应日志