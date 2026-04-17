# 热点新闻路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models.hot_news import HotNewsSource, HotArticle
from ...services.crawler import CrawlerFactory

router = APIRouter()


# Pydantic Schemas
class NewsSourceCreate(BaseModel):
    name: str
    domain: str  # tech/news/sports/finance/health/education
    source_url: str
    source_type: str  # rss/web
    crawl_config: Optional[Dict[str, Any]] = None
    crawl_frequency: str = "0 * * * *"


class NewsSourceUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    crawl_config: Optional[Dict[str, Any]] = None
    crawl_frequency: Optional[str] = None
    is_active: Optional[bool] = None


class NewsSourceResponse(BaseModel):
    id: UUID
    name: str
    domain: str
    source_url: str
    source_type: str
    crawl_config: Dict[str, Any]
    crawl_frequency: str
    is_active: bool
    last_crawl_at: Optional[datetime]
    last_crawl_status: Optional[str]
    total_articles: int

    class Config:
        from_attributes = True


class ArticleResponse(BaseModel):
    id: UUID
    source_id: UUID
    title: str
    content: Optional[str]
    author: Optional[str]
    published_at: Optional[datetime]
    crawled_at: datetime
    source_url: Optional[str]
    category: Optional[str]
    tags: List[str]

    class Config:
        from_attributes = True


# API endpoints
@router.get("/supported-types")
async def get_supported_types():
    """获取支持的爬虫类型"""
    return CrawlerFactory.get_supported_types()


@router.get("/domains")
async def get_domains():
    """获取支持的领域分类"""
    return [
        {"code": "tech", "name": "科技"},
        {"code": "news", "name": "综合新闻"},
        {"code": "finance", "name": "财经"},
        {"code": "sports", "name": "体育"},
        {"code": "health", "name": "健康"},
        {"code": "education", "name": "教育"},
        {"code": "science", "name": "科学"},
        {"code": "entertainment", "name": "娱乐"},
        {"code": "lifestyle", "name": "生活"},
    ]


@router.get("/sources", response_model=List[NewsSourceResponse])
async def list_sources(
    domain: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取新闻源列表"""
    query = select(HotNewsSource)

    if domain:
        query = query.where(HotNewsSource.domain == domain)
    if is_active is not None:
        query = query.where(HotNewsSource.is_active == is_active)

    query = query.order_by(HotNewsSource.created_at.desc())
    result = await db.execute(query)
    sources = result.scalars().all()

    return [NewsSourceResponse(
        id=s.id,
        name=s.name,
        domain=s.domain,
        source_url=s.source_url,
        source_type=s.source_type,
        crawl_config=s.crawl_config or {},
        crawl_frequency=s.crawl_frequency,
        is_active=s.is_active,
        last_crawl_at=s.last_crawl_at,
        last_crawl_status=s.last_crawl_status,
        total_articles=s.total_articles
    ) for s in sources]


@router.post("/sources", response_model=NewsSourceResponse)
async def create_source(
    data: NewsSourceCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建新闻源"""
    # 测试连接
    crawler = CrawlerFactory.create(
        data.source_type,
        {
            "source_url": data.source_url,
            "crawl_config": data.crawl_config or {}
        }
    )
    test_result = await crawler.test_connection()

    if not test_result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=f"连接测试失败: {test_result.get('error', '未知错误')}"
        )

    source = HotNewsSource(
        name=data.name,
        domain=data.domain,
        source_url=data.source_url,
        source_type=data.source_type,
        crawl_config=data.crawl_config or {},
        crawl_frequency=data.crawl_frequency,
        is_active=True
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    return NewsSourceResponse(
        id=source.id,
        name=source.name,
        domain=source.domain,
        source_url=source.source_url,
        source_type=source.source_type,
        crawl_config=source.crawl_config,
        crawl_frequency=source.crawl_frequency,
        is_active=source.is_active,
        last_crawl_at=source.last_crawl_at,
        last_crawl_status=source.last_crawl_status,
        total_articles=source.total_articles
    )


@router.get("/sources/{source_id}", response_model=NewsSourceResponse)
async def get_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取新闻源详情"""
    result = await db.execute(
        select(HotNewsSource).where(HotNewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="新闻源不存在")

    return NewsSourceResponse(
        id=source.id,
        name=source.name,
        domain=source.domain,
        source_url=source.source_url,
        source_type=source.source_type,
        crawl_config=source.crawl_config or {},
        crawl_frequency=source.crawl_frequency,
        is_active=source.is_active,
        last_crawl_at=source.last_crawl_at,
        last_crawl_status=source.last_crawl_status,
        total_articles=source.total_articles
    )


@router.put("/sources/{source_id}", response_model=NewsSourceResponse)
async def update_source(
    source_id: UUID,
    data: NewsSourceUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新新闻源"""
    result = await db.execute(
        select(HotNewsSource).where(HotNewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="新闻源不存在")

    # 更新字段
    if data.name is not None:
        source.name = data.name
    if data.domain is not None:
        source.domain = data.domain
    if data.source_url is not None:
        source.source_url = data.source_url
    if data.source_type is not None:
        source.source_type = data.source_type
    if data.crawl_config is not None:
        source.crawl_config = data.crawl_config
    if data.crawl_frequency is not None:
        source.crawl_frequency = data.crawl_frequency
    if data.is_active is not None:
        source.is_active = data.is_active

    await db.commit()
    await db.refresh(source)

    return NewsSourceResponse(
        id=source.id,
        name=source.name,
        domain=source.domain,
        source_url=source.source_url,
        source_type=source.source_type,
        crawl_config=source.crawl_config or {},
        crawl_frequency=source.crawl_frequency,
        is_active=source.is_active,
        last_crawl_at=source.last_crawl_at,
        last_crawl_status=source.last_crawl_status,
        total_articles=source.total_articles
    )


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除新闻源"""
    result = await db.execute(
        select(HotNewsSource).where(HotNewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="新闻源不存在")

    await db.delete(source)
    await db.commit()
    return {"message": "删除成功", "source_id": str(source_id)}


@router.post("/sources/{source_id}/test")
async def test_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """测试新闻源连接"""
    result = await db.execute(
        select(HotNewsSource).where(HotNewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="新闻源不存在")

    crawler = CrawlerFactory.create(
        source.source_type,
        {
            "source_url": source.source_url,
            "crawl_config": source.crawl_config or {}
        }
    )

    test_result = await crawler.test_connection()
    return test_result


@router.post("/sources/{source_id}/crawl")
async def trigger_crawl(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """手动触发爬取"""
    result = await db.execute(
        select(HotNewsSource).where(HotNewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="新闻源不存在")

    # 创建爬虫
    crawler = CrawlerFactory.create(
        source.source_type,
        {
            "source_url": source.source_url,
            "crawl_config": source.crawl_config or {}
        }
    )

    # 执行爬取
    crawl_result = await crawler.crawl(since=source.last_crawl_at)

    # 存储文章
    new_count = 0
    for article in crawl_result.articles:
        # 检查是否已存在
        content_hash = crawler.compute_hash(article.title, article.content)
        existing = await db.execute(
            select(HotArticle).where(HotArticle.content_hash == content_hash)
        )
        if existing.scalar_one_or_none():
            continue

        # 创建新文章
        hot_article = HotArticle(
            source_id=source.id,
            title=article.title,
            content=article.content,
            author=article.author,
            summary=article.summary,
            published_at=article.published_at,
            source_url=article.source_url,
            category=article.category,
            tags=article.tags,
            content_hash=content_hash,
            article_metadata=article.metadata
        )
        db.add(hot_article)
        new_count += 1

    # 更新源状态
    source.last_crawl_at = datetime.utcnow()
    source.last_crawl_status = "success" if not crawl_result.errors else "partial"
    source.last_article_count = new_count
    source.total_articles += new_count
    if crawl_result.errors:
        source.last_crawl_error = str(crawl_result.errors[0])

    await db.commit()

    return {
        "source_id": str(source_id),
        "total_found": crawl_result.total,
        "new_articles": new_count,
        "errors": crawl_result.errors,
        "status": "success"
    }


@router.get("/articles", response_model=List[ArticleResponse])
async def list_articles(
    source_id: Optional[UUID] = None,
    domain: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """获取文章列表"""
    query = select(HotArticle)

    if source_id:
        query = query.where(HotArticle.source_id == source_id)
    if domain:
        # 关联source获取domain
        query = query.join(HotNewsSource).where(HotNewsSource.domain == domain)

    query = query.order_by(HotArticle.crawled_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    articles = result.scalars().all()

    return [ArticleResponse(
        id=a.id,
        source_id=a.source_id,
        title=a.title,
        content=a.content,
        author=a.author,
        published_at=a.published_at,
        crawled_at=a.crawled_at,
        source_url=a.source_url,
        category=a.category,
        tags=a.tags or []
    ) for a in articles]


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db)
):
    """获取统计信息"""
    # 源统计
    sources_count = await db.execute(
        select(func.count(HotNewsSource.id))
    )
    active_sources = await db.execute(
        select(func.count(HotNewsSource.id)).where(HotNewsSource.is_active == True)
    )

    # 文章统计
    articles_count = await db.execute(
        select(func.count(HotArticle.id))
    )
    today_articles = await db.execute(
        select(func.count(HotArticle.id)).where(
            HotArticle.crawled_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        )
    )

    # 按领域统计
    domain_stats = await db.execute(
        select(
            HotNewsSource.domain,
            func.count(HotArticle.id)
        )
        .join(HotArticle)
        .group_by(HotNewsSource.domain)
    )
    domain_counts = {row[0]: row[1] for row in domain_stats.fetchall()}

    return {
        "sources": {
            "total": sources_count.scalar(),
            "active": active_sources.scalar()
        },
        "articles": {
            "total": articles_count.scalar(),
            "today": today_articles.scalar()
        },
        "by_domain": domain_counts
    }