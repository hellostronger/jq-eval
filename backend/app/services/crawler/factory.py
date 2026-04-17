# 爬虫工厂
from typing import Dict, Any, Type

from .base import BaseCrawler
from .rss_crawler import RSSCrawler
from .web_crawler import WebCrawler


CRAWLER_REGISTRY: Dict[str, Type[BaseCrawler]] = {
    "rss": RSSCrawler,
    "web": WebCrawler,
}


class CrawlerFactory:
    """爬虫工厂"""

    @staticmethod
    def create(source_type: str, config: Dict[str, Any]) -> BaseCrawler:
        """创建爬虫实例"""
        crawler_class = CRAWLER_REGISTRY.get(source_type)

        if not crawler_class:
            raise ValueError(f"不支持的爬虫类型: {source_type}")

        return crawler_class(config)

    @staticmethod
    def get_supported_types() -> list:
        """获取支持的爬虫类型"""
        return [
            {
                "type": "rss",
                "display_name": "RSS源",
                "description": "RSS/Atom订阅源，适合大部分新闻网站"
            },
            {
                "type": "web",
                "display_name": "网页源",
                "description": "使用Playwright爬取网页，支持动态页面"
            }
        ]