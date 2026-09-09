# 基础模型
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime

from ..core.database import Base
from ..core.db_types import UUIDType


class BaseModel(Base):
    """基础模型抽象类"""
    __abstract__ = True

    id = Column(UUIDType(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)