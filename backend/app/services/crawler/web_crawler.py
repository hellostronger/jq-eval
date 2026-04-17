# Playwright网页爬虫
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
import asyncio

from .base import BaseCrawler, CrawledArticle, CrawlResult

logger = logging.getLogger(__name__)


class WebCrawler(BaseCrawler):
    """网页爬虫（使用Playwright）"""

    source_type = "web"
    display_name = "网页源"

    async def crawl(self, since: Optional[datetime] = None) -> CrawlResult:
        """爬取网页"""
        url = self.config.get("source_url")
        crawl_config = self.config.get("crawl_config", {})

        if not url:
            return CrawlResult(errors=[{"error": "缺少网页URL"}])

        try:
            from playwright.async_api import async_playwright

            articles = []
            errors = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # 设置超时
                page.set_default_timeout(30000)  # 30秒

                # 访问页面
                await page.goto(url, wait_until="networkidle")

                # 获取文章列表
                article_list_selector = crawl_config.get("article_list_selector", "article, .article, .news-item")
                article_elements = await page.query_selector_all(article_list_selector)

                logger.info(f"找到 {len(article_elements)} 个文章元素")

                # 解析每篇文章
                for elem in article_elements[:crawl_config.get("max_articles", 20)]:
                    try:
                        article = await self._parse_article(elem, crawl_config, page)
                        if article:
                            articles.append(article)
                    except Exception as e:
                        errors.append({"error": str(e)})

                await browser.close()

            return CrawlResult(
                total=len(articles),
                articles=articles,
                errors=errors,
                source_type=self.source_type
            )

        except ImportError:
            logger.error("Playwright未安装，请运行: pip install playwright && playwright install chromium")
            return CrawlResult(errors=[{"error": "Playwright未安装"}])
        except Exception as e:
            logger.error(f"网页爬取失败: {e}")
            return CrawlResult(errors=[{"error": str(e)}])

    async def _parse_article(
        self,
        elem: Any,
        config: Dict[str, Any],
        page: Any
    ) -> Optional[CrawledArticle]:
        """解析文章元素"""
        selectors = config.get("selectors", {})

        # 获取标题
        title_selector = selectors.get("title", "h1, h2, .title, .article-title")
        title_elem = await elem.query_selector(title_selector)
        title = await title_elem.inner_text() if title_elem else ""

        if not title:
            return None

        # 获取链接
        link_selector = selectors.get("link", "a")
        link_elem = await elem.query_selector(link_selector)
        href = await link_elem.get_attribute("href") if link_elem else ""

        # 处理相对链接
        if href and not href.startswith("http"):
            base_url = self.config.get("source_url")
            if base_url:
                from urllib.parse import urljoin
                href = urljoin(base_url, href)

        # 获取内容
        content = ""
        content_selector = selectors.get("content", ".content, .article-content, p")

        # 如果配置了进入文章页面获取详细内容
        if config.get("fetch_full_content", False) and href:
            try:
                await page.goto(href, wait_until="networkidle")
                content_elem = await page.query_selector(content_selector)
                content = await content_elem.inner_text() if content_elem else ""
                await page.go_back()
            except Exception as e:
                logger.warning(f"获取文章内容失败: {e}")
        else:
            content_elem = await elem.query_selector(content_selector)
            content = await content_elem.inner_text() if content_elem else ""

        # 获取作者
        author_selector = selectors.get("author", ".author, .by")
        author_elem = await elem.query_selector(author_selector)
        author = await author_elem.inner_text() if author_elem else None

        # 获取发布时间
        time_selector = selectors.get("time", "time, .date, .publish-time")
        time_elem = await elem.query_selector(time_selector)
        time_text = await time_elem.inner_text() if time_elem else ""
        published_at = self._parse_time(time_text)

        # 获取分类
        category_selector = selectors.get("category", ".category, .tag")
        category_elem = await elem.query_selector(category_selector)
        category = await category_elem.inner_text() if category_elem else None

        return CrawledArticle(
            title=title.strip(),
            content=content.strip(),
            author=author.strip() if author else None,
            published_at=published_at,
            source_url=href,
            category=category.strip() if category else None,
            tags=[category.strip()] if category else [],
            metadata={"time_text": time_text}
        )

    def _parse_time(self, time_text: str) -> Optional[datetime]:
        """解析时间文本"""
        if not time_text:
            return None

        time_text = time_text.strip()

        # 尝试多种格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y年%m月%d日",
            "%Y/%m/%d",
            "%m-%d %H:%M",  # 如 "04-17 10:30"
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(time_text, fmt)
                # 如果没有年份，使用当前年份
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue

        return None

    async def test_connection(self) -> Dict[str, Any]:
        """测试网页连接"""
        url = self.config.get("source_url")
        if not url:
            return {"success": False, "error": "缺少网页URL"}

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                page.set_default_timeout(10000)

                await page.goto(url, wait_until="networkidle")

                # 获取页面标题
                page_title = await page.title()

                # 检查文章列表选择器
                crawl_config = self.config.get("crawl_config", {})
                selector = crawl_config.get("article_list_selector", "article")
                article_count = len(await page.query_selector_all(selector))

                await browser.close()

                return {
                    "success": True,
                    "page_title": page_title,
                    "article_count": article_count,
                    "url": url
                }

        except ImportError:
            return {"success": False, "error": "Playwright未安装"}
        except Exception as e:
            return {"success": False, "error": str(e)}