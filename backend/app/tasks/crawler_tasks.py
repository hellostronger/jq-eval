# 爬虫定时任务
from typing import Dict, Any
from datetime import datetime
import logging

from app.core.celery_app import celery_app
from app.tasks._common import run_async
from app.core.database import get_db_context
from app.models.hot_news import HotNewsSource, HotArticle
from app.services.crawler import CrawlerFactory

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="crawl_source_task")
def crawl_source_task(self, source_id: str) -> Dict[str, Any]:
    """爬取单个新闻源"""
    return run_async(_run_crawl(self, source_id))


async def _run_crawl(task, source_id: str) -> Dict[str, Any]:
    """异步执行爬取"""
    async with get_db_context() as db:
        from sqlalchemy import select
        from uuid import UUID

        # 获取新闻源
        result = await db.execute(
            select(HotNewsSource).where(HotNewsSource.id == UUID(source_id))
        )
        source = result.scalar_one_or_none()
        if not source:
            return {"error": f"新闻源 {source_id} 不存在"}

        if not source.is_active:
            return {"error": "新闻源已禁用"}

        # 创建爬虫
        crawler = CrawlerFactory.create(
            source.source_type,
            {
                "source_url": source.source_url,
                "crawl_config": source.crawl_config or {}
            }
        )

        # 执行爬取
        task.update_state(state="RUNNING", meta={"source": source.name})
        crawl_result = await crawler.crawl(since=source.last_crawl_at)

        # 存储文章：先批量算出所有 hash，一次查询过滤已存在的
        article_hashes = [
            crawler.compute_hash(a.title, a.content) for a in crawl_result.articles
        ]
        existing_hashes = set()
        if article_hashes:
            existing_result = await db.execute(
                select(HotArticle.content_hash).where(HotArticle.content_hash.in_(article_hashes))
            )
            existing_hashes = {row[0] for row in existing_result.fetchall()}

        new_count = 0
        for article, content_hash in zip(crawl_result.articles, article_hashes):
            if content_hash in existing_hashes:
                continue

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

        logger.info(f"爬取完成: {source.name}, 新增 {new_count} 篇文章")

        return {
            "source_id": source_id,
            "source_name": source.name,
            "total_found": crawl_result.total,
            "new_articles": new_count,
            "errors": crawl_result.errors,
            "status": "success"
        }


@celery_app.task(name="crawl_all_active_sources")
def crawl_all_active_sources() -> Dict[str, Any]:
    """爬取所有活跃的新闻源"""
    return run_async(_crawl_all_sources())


async def _crawl_all_sources() -> Dict[str, Any]:
    """异步爬取所有活跃源"""
    async with get_db_context() as db:
        from sqlalchemy import select

        # 获取所有活跃源
        result = await db.execute(
            select(HotNewsSource).where(HotNewsSource.is_active == True)
        )
        sources = result.scalars().all()

        results = []
        for source in sources:
            # 触发单个爬取任务
            crawl_source_task.delay(str(source.id))
            results.append({
                "source_id": str(source.id),
                "source_name": source.name,
                "status": "triggered"
            })

        return {
            "total_sources": len(sources),
            "results": results
        }