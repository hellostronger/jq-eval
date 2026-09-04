# RSS爬虫
from typing import Dict, List, Any, Optional
from datetime import datetime
import re
import feedparser
import logging
import asyncio
import httpx
from langdetect import detect, LangDetectException
from bs4 import BeautifulSoup
from markdownify import markdownify as md

try:
    import trafilatura
except ImportError:
    trafilatura = None

from .base import BaseCrawler, CrawledArticle, CrawlResult
from .image_transfer import transfer_article_images

logger = logging.getLogger(__name__)


def detect_text_language(text: str) -> Optional[str]:
    """检测文本语言

    langdetect 对短中文文本易误判（vi/en等），先按中文字符占比判定
    """
    if not text or len(text) < 20:
        return None
    sample = text[:500]
    chinese = len(re.findall(r"[一-鿿]", sample))
    if chinese / max(len(sample), 1) > 0.15:
        return "zh"
    try:
        return detect(sample)
    except LangDetectException:
        return None


# 常见的文章正文选择器
# 注意：宽泛的选择器（如 article、[class*='content']）容易命中广告/侧栏容器，
# 实际提取时会取"文本最长的候选"，这里顺序只影响优先级
ARTICLE_CONTENT_SELECTORS = [
    ".article-content",
    ".article-body",
    ".post-content",
    ".entry-content",
    ".post-body",
    ".story-body",
    "#article-content",
    "article",
    ".content",
    "[class*='content']",
    "[class*='article']",
]

# 正文最小长度：低于此值的候选视为误命中（广告、摘要、骨架页），继续尝试下一个
MIN_CONTENT_LENGTH = 200

# 默认浏览器 UA，部分站点（雪球、开源中国等）对无 UA 请求直接返回 403
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _cleanup_element(elem) -> None:
    """移除脚本、样式、导航等干扰元素"""
    for tag in elem.select(
        "script, style, nav, header, footer, aside, .sidebar, "
        ".ads, .ad, [class*='ad-'], [class*='-ad'], "
        ".recommend, .comment, "
        "[class*='share'], [class*='social'], [class*='reaction'], "
        "[class*='button'], button, form, iframe, svg"
    ):
        tag.decompose()


async def _get_page_text(client: "httpx.AsyncClient", url: str) -> Optional[str]:
    """请求页面，带UA失败时用裸头重试（部分站点对伪造UA的指纹校验更严）"""
    response = await client.get(url)
    if response.status_code != 200 or len(response.text) < 1000:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as bare_client:
            retry = await bare_client.get(url)
        if retry.status_code == 200 and len(retry.text) >= len(response.text):
            return retry.text
    if response.status_code != 200:
        response.raise_for_status()
    return response.text


def _cleanup_extracted(text: str) -> str:
    """清理 trafilatura 提取结果中的互动按钮等残留（如单独成行的 +1）"""
    text = re.sub(r"^\s*[-*]?\s*\+1\s*$", "", text, flags=re.M)
    return text.strip()


async def fetch_full_content(url: str, content_format: str = "markdown") -> Optional[str]:
    """获取文章完整内容

    策略：优先用 trafilatura（通用正文提取算法，自动识别正文/过滤广告导航等噪音）；
    未安装或提取失败时，回退到"候选选择器取最长文本 + 段落汇总"的启发式方案。

    Args:
        url: 文章链接
        content_format: 内容格式 - "text"(纯文本), "markdown"(Markdown), "html"(原始HTML)

    Returns:
        格式化后的文章内容，提取失败返回 None
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            page_text = await _get_page_text(client, url)
            if not page_text:
                return None

            soup = BeautifulSoup(page_text, "lxml")

            # 优先：trafilatura 通用正文提取
            if trafilatura is not None and content_format != "html":
                output_format = "markdown" if content_format == "markdown" else "txt"
                try:
                    extracted = trafilatura.extract(
                        page_text,
                        output_format=output_format,
                        include_comments=False,
                        include_tables=True,
                        include_images=True,
                    )
                except Exception as e:
                    logger.warning(f"trafilatura 提取失败，回退到选择器方案: {url}, 错误: {e}")
                    extracted = None
                if extracted and len(extracted) >= MIN_CONTENT_LENGTH:
                    return _cleanup_extracted(extracted)

            # 回退：遍历选择器，记录文本最长的正文容器
            best_elem = None
            best_length = 0

            for selector in ARTICLE_CONTENT_SELECTORS:
                elem = soup.select_one(selector)
                if not elem:
                    continue
                _cleanup_element(elem)
                text_length = len(elem.get_text(strip=True))
                if text_length > best_length:
                    best_elem = elem
                    best_length = text_length

            if best_elem is not None and best_length >= MIN_CONTENT_LENGTH:
                if content_format == "html":
                    return str(best_elem)
                elif content_format == "markdown":
                    return md(str(best_elem), heading_style="atx", bullets="-")
                else:
                    return best_elem.get_text(strip=True, separator="\n")

            # 兜底：汇总所有有效段落
            paragraphs = [p for p in soup.select("p") if len(p.get_text(strip=True)) > 50]
            if not paragraphs:
                return None

            if content_format == "html":
                return "\n".join(str(p) for p in paragraphs)
            elif content_format == "markdown":
                return md("\n".join(str(p) for p in paragraphs), heading_style="atx")
            else:
                text = "\n".join(p.get_text(strip=True) for p in paragraphs)
                return text if len(text) >= MIN_CONTENT_LENGTH else None
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

                kept = []
                for i, article in enumerate(articles):
                    if article.source_url and contents[i]:
                        # 全文抓取成功，无条件覆盖（RSS原始content可能是HTML，
                        # 直接按长度比较会让原始HTML反而胜出）
                        article.content = contents[i]
                        article.metadata["content_length"] = len(article.content)
                        article.metadata["content_format"] = content_format
                        # 重新检测语言
                        lang = detect_text_language(article.content or "")
                        if lang:
                            article.metadata["language"] = lang
                        kept.append(article)
                    elif article.source_url:
                        # 全文抓取失败，保留RSS摘要但标记，避免与全文混淆；
                        # 摘要若是HTML则转为纯文本
                        if article.content and "<" in article.content:
                            article.content = BeautifulSoup(article.content, "lxml").get_text(separator="\n", strip=True)
                        article.metadata["full_content_fetched"] = False
                        kept.append(article)
                    else:
                        kept.append(article)
                articles = kept

            # 图片转存MinIO：下载正文图片并替换URL（markdown/HTML格式才处理）
            if content_format in ("markdown", "html") and articles:
                for article in articles:
                    if not article.content or "http" not in article.content:
                        continue
                    try:
                        new_content, count = await transfer_article_images(article.content)
                        if count > 0:
                            article.content = new_content
                            article.metadata["images_transferred"] = count
                            article.metadata["content_length"] = len(article.content)
                    except Exception as e:
                        logger.warning(f"图片转存失败({article.title[:30]}): {e}")

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
        language = detect_text_language(content)

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