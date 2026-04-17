# RSS爬虫
from typing import Dict, List, Any, Optional
from datetime import datetime
import feedparser
import logging

from .base import BaseCrawler, CrawledArticle, CrawlResult

logger = logging.getLogger(__name__)


class RSSCrawler(BaseCrawler):
    """RSS源爬虫"""

    source_type = "rss"
    display_name = "RSS源"

    async def crawl(self, since: Optional[datetime] = None) -> CrawlResult:
        """爬取RSS源"""
        url = self.config.get("source_url")
        if not url:
            return CrawlResult(errors=[{"error": "缺少RSS URL"}])

        try:
            # 解析RSS
            feed = feedparser.parse(url)

            if feed.bozo and feed.bozo_exception:
                logger.warning(f"RSS解析警告: {feed.bozo_exception}")

            articles = []
            errors = []

            # 解析条目
            for entry in feed.entries:
                try:
                    article = self._parse_entry(entry, since)
                    if article:
                        articles.append(article)
                except Exception as e:
                    errors.append({
                        "title": entry.get("title", "未知"),
                        "error": str(e)
                    })

            return CrawlResult(
                total=len(articles),
                articles=articles,
                errors=errors,
                source_type=self.source_type
            )

        except Exception as e:
            logger.error(f"RSS爬取失败: {e}")
            return CrawlResult(errors=[{"error": str(e)}])

    def _parse_entry(self, entry: Any, since: Optional[datetime] = None) -> Optional[CrawledArticle]:
        """解析RSS条目"""
        # 获取发布时间
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6])
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published_at = datetime(*entry.updated_parsed[:6])

        # 过滤：只爬取指定时间之后的文章
        if since and published_at and published_at < since:
            return None

        # 获取内容
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary
        elif hasattr(entry, "description"):
            content = entry.description

        # 获取作者
        author = None
        if hasattr(entry, "author"):
            author = entry.author
        elif hasattr(entry, "author_detail"):
            author = entry.author_detail.get("name")

        # 获取标签/分类
        tags = []
        if hasattr(entry, "tags"):
            tags = [tag.term for tag in entry.tags if hasattr(tag, "term")]

        return CrawledArticle(
            title=entry.get("title", ""),
            content=content,
            author=author,
            summary=entry.get("summary", ""),
            published_at=published_at,
            source_url=entry.get("link", ""),
            category=tags[0] if tags else None,
            tags=tags,
            metadata={
                "feed_title": entry.get("title_detail", {}).get("base", ""),
            }
        )

    async def test_connection(self) -> Dict[str, Any]:
        """测试RSS连接"""
        url = self.config.get("source_url")
        if not url:
            return {"success": False, "error": "缺少RSS URL"}

        try:
            feed = feedparser.parse(url)
            if feed.bozo and feed.bozo_exception:
                return {
                    "success": True,
                    "warning": str(feed.bozo_exception),
                    "feed_title": feed.feed.get("title", ""),
                    "entries_count": len(feed.entries)
                }

            return {
                "success": True,
                "feed_title": feed.feed.get("title", ""),
                "entries_count": len(feed.entries),
                "last_updated": feed.feed.get("updated", "")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}