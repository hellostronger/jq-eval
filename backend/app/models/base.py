# 基础模型
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class BaseModel(Base):
    """基础模型抽象类"""
    __abstract__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)