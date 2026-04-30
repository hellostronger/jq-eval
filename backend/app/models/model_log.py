# 模型请求响应日志
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from .base import BaseModel


class ModelRequestLog(BaseModel):
    """模型请求响应日志"""
    __tablename__ = "model_request_logs"

    model_id = Column(UUID(as_uuid=True), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 关联会话（可选）

    # 请求信息
    request_type = Column(String(50), nullable=False)  # chat/embedding/rerank
    prompt = Column(Text, nullable=False)  # 用户输入/请求内容
    system_prompt = Column(Text, nullable=True)  # 系统提示（LLM）
    messages = Column(JSONB, nullable=True)  # 完整的消息列表（多轮对话）
    params = Column(JSONB, nullable=True)  # 请求参数（temperature, max_tokens等）

    # 响应信息
    response = Column(Text, nullable=True)  # 模型响应内容
    response_metadata = Column(JSONB, nullable=True)  # 响应元数据（tokens, latency等）

    # 状态
    status = Column(String(20), default="pending")  # pending/success/failed
    error_message = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)  # 响应耗时（毫秒）

    # 回放标记
    is_replay = Column(Boolean, default=False)  # 是否是回放测试
    replay_from_log_id = Column(UUID(as_uuid=True), nullable=True)  # 回放源日志ID
    replay_model_id = Column(UUID(as_uuid=True), ForeignKey("models.id", ondelete="SET NULL"), nullable=True)  # 回放使用的模型ID