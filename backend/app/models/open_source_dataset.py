# 开源数据集模型
from sqlalchemy import Column, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from .base import BaseModel


class OpenSourceDataset(BaseModel):
    """开源数据集表"""
    __tablename__ = "open_source_datasets"

    # 数据集名称
    name = Column(String(200), nullable=False)

    # 数据集URL
    url = Column(String(1000), nullable=False)

    # 描述信息
    description = Column(Text, nullable=True)

    # 数据集类型（如：文本、图像、音频等）
    dataset_type = Column(String(50), nullable=True)

    # 数据规模/大小描述
    size_info = Column(String(200), nullable=True)

    # 语言
    language = Column(String(50), nullable=True)

    # 是否公开可访问
    is_public = Column(Boolean, default=True)

    # 标签（用于分类和搜索）
    tags = Column(JSONB, default=list)

    # 元数据
    osd_metadata = Column(JSONB, default=dict)

    # 状态（active/archived）
    status = Column(String(50), default="active")