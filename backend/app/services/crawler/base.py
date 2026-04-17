# 爬虫基类
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from datetime import datetime
import hashlib


class CrawledArticle(BaseModel):
    """爬取的文章结果"""
    title: str
    content: Optional[str] = None
    author: Optional[str] = None
    summary: Optional[str] = None
    published_at: Optional[datetime] = None
    source_url: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    metadata: Dict[str, Any] = {}


class CrawlResult(BaseModel):
    """爬取结果"""
    total: int = 0
    articles: List[CrawledArticle] = []
    errors: List[Dict[str, Any]] = []
    source_type: str = ""


class BaseCrawler(ABC):
    """爬虫基类"""

    source_type: str
    display_name: str

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    async def crawl(self, since: Optional[datetime] = None) -> CrawlResult:
        """执行爬取"""
        pass

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        pass

    def compute_hash(self, title: str, content: Optional[str] = None) -> str:
        """计算内容哈希用于去重"""
        text = title
        if content:
            text += content[:500]  # 取前500字符参与哈希
        return hashlib.sha256(text.encode()).hexdigest()

    def deduplicate(self, articles: List[CrawledArticle], existing_hashes: List[str] = None) -> List[CrawledArticle]:
        """去重"""
        if existing_hashes is None:
            existing_hashes = []

        seen = set(existing_hashes)
        result = []
        for article in articles:
            hash_val = self.compute_hash(article.title, article.content)
            if hash_val not in seen:
                seen.add(hash_val)
                result.append(article)
        return result