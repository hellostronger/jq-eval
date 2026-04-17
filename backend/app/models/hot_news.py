# 热点新闻相关模型
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import BaseModel


class HotNewsSource(BaseModel):
    """热点新闻源配置表"""
    __tablename__ = "hot_news_sources"

    name = Column(String(200), nullable=False)
    domain = Column(String(50), nullable=False)  # tech/news/sports/finance/health/education
    source_url = Column(String(1000), nullable=False)
    source_type = Column(String(20), nullable=False)  # rss/web/custom

    # 爬取配置（CSS选择器、XPath、解析规则等）
    crawl_config = Column(JSONB, default=dict)

    # 爬取频率（cron表达式）
    crawl_frequency = Column(String(100), default="0 * * * *")  # 默认每小时

    # 状态
    is_active = Column(Boolean, default=True)
    last_crawl_at = Column(DateTime, nullable=True)
    last_crawl_status = Column(String(50), nullable=True)  # success/failed
    last_crawl_error = Column(Text, nullable=True)

    # 统计
    total_articles = Column(Integer, default=0)
    last_article_count = Column(Integer, default=0)

    # 所属用户（可选）
    owner_id = Column(UUID(as_uuid=True), nullable=True)

    # 关系
    articles = relationship("HotArticle", back_populates="source", cascade="all, delete-orphan")


class HotArticle(BaseModel):
    """热点文章表"""
    __tablename__ = "hot_articles"

    source_id = Column(UUID(as_uuid=True), ForeignKey("hot_news_sources.id", ondelete="CASCADE"), nullable=False, index=True)

    # 文章信息
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)
    author = Column(String(200), nullable=True)
    summary = Column(Text, nullable=True)

    # 时间
    published_at = Column(DateTime, nullable=True)
    crawled_at = Column(DateTime, default=datetime.utcnow)

    # 来源
    source_url = Column(String(1000), nullable=True)
    category = Column(String(100), nullable=True)
    tags = Column(ARRAY(String), default=list)

    # 去重
    content_hash = Column(String(64), nullable=True, index=True)

    # 关联文档（可选）
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)

    # 元数据
    article_metadata = Column(JSONB, default=dict)

    # 关系
    source = relationship("HotNewsSource", back_populates="articles")