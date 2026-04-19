# RSS爬虫
from typing import Dict, List, Any, Optional
from datetime import datetime
import feedparser
import logging
import asyncio
import httpx
from langdetect import detect, LangDetectException
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from .base import BaseCrawler, CrawledArticle, CrawlResult

logger = logging.getLogger(__name__)


# 常见的文章正文选择器
ARTICLE_CONTENT_SELECTORS = [
    "article",
    ".article-content",
    ".post-content",
    ".entry-content",
    ".content",
    ".article-body",
    ".post-body",
    ".story-body",
    "#article-content",
    "[class*='content']",
    "[class*='article']",
]


async def fetch_full_content(url: str, content_format: str = "markdown") -> Optional[str]:
    """获取文章完整内容

    Args:
        url: 文章链接
        content_format: 内容格式 - "text"(纯文本), "markdown"(Markdown), "html"(原始HTML)

    Returns:
        格式化后的文章内容
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # 尝试多种选择器找到文章正文
            for selector in ARTICLE_CONTENT_SELECTORS:
                elem = soup.select_one(selector)
                if elem:
                    # 清理：移除脚本、样式、导航等
                    for tag in elem.select("script, style, nav, header, footer, aside, .sidebar, .ads"):
                        tag.decompose()

                    if content_format == "html":
                        # 保留HTML格式
                        return str(elem)
                    elif content_format == "markdown":
                        # 转换为Markdown
                        html = str(elem)
                        return md(html, heading_style="atx", bullets="-")
                    else:
                        # 纯文本格式
                        text = elem.get_text(strip=True, separator="\n")
                        if len(text) > 200:
                            return text

            # 如果没有找到，尝试获取所有p标签内容
            paragraphs = soup.select("p")
            if paragraphs:
                if content_format == "html":
                    return "\n".join(str(p) for p in paragraphs if len(p.get_text(strip=True)) > 50)
                elif content_format == "markdown":
                    html = "\n".join(str(p) for p in paragraphs if len(p.get_text(strip=True)) > 50)
                    return md(html, heading_style="atx")
                else:
                    text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 50)
                    if len(text) > 200:
                        return text

            return None
    except Exception as e:
        logger.warning(f"获取文章完整内容失败: {url}, 错误: {e}")
        return None


class RSSCrawler(BaseCrawler):
    """RSS源爬虫"""

    source_type = "rss"
    display_name = "RSS源"

    async def crawl(self, since: Optional[datetime] = None) -> CrawlResult:
        """爬取RSS源"""
        url = self.config.get("source_url")
        crawl_config = self.config.get("crawl_config", {})
        fetch_full = crawl_config.get("fetch_full_content", False)
        content_format = crawl_config.get("content_format", "markdown")  # text/markdown/html

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

            # 如果配置了获取完整内容，并行获取
            if fetch_full and articles:
                logger.info(f"开始获取 {len(articles)} 篇文章的完整内容 (格式: {content_format})...")
                urls = [a.source_url for a in articles if a.source_url]
                contents = await asyncio.gather(
                    *[fetch_full_content(url, content_format) for url in urls]
                )

                for i, article in enumerate(articles):
                    if article.source_url and contents[i]:
                        article.content = contents[i]
                        article.metadata["content_length"] = len(article.content)
                        article.metadata["content_format"] = content_format
                        # 重新检测语言
                        if len(article.content) > 50:
                            try:
                                article.metadata["language"] = detect(article.content[:500])
                            except LangDetectException:
                                pass

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

        # 计算内容长度
        content_length = len(content) if content else 0

        # 检测语言
        language = None
        if content and len(content) > 50:
            try:
                language = detect(content[:500])
            except LangDetectException:
                language = None

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
                "content_length": content_length,
                "language": language,
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