# 模型调用映射表
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from ..core.crypto import EncryptedText
from ..core.db_types import UUIDType
from .base import BaseModel


class ModelMapping(BaseModel):
    """模型调用映射（对外暴露的服务端点，映射到模型配置下的目标模型）"""
    __tablename__ = "model_mappings"

    name = Column(String(200), nullable=False)
    target_model_id = Column(UUIDType(as_uuid=True), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key = Column(EncryptedText, nullable=True)  # sk-mx- 前缀密钥（Fernet 加密存储，读回明文供 hmac 比对）
    auth_required = Column(Boolean, default=True)  # 是否校验 API Key
    log_enabled = Column(Boolean, default=False)  # 是否记录调用日志
    status = Column(String(20), default="active")  # active/disabled
    description = Column(Text, nullable=True)
    last_called_at = Column(DateTime, nullable=True)  # 最近调用时间
