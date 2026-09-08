# RAG系统适配器基类
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime
from asyncio import iscoroutinefunction

import httpx


class RAGResponse(BaseModel):
    """RAG系统统一响应"""
    answer: str
    contexts: Optional[List[str]] = None
    retrieval_ids: Optional[List[str]] = None
    metadata: Dict[str, Any] = {}

    # 性能指标
    response_time: float = 0.0
    first_token_latency: Optional[float] = None  # 首token延迟（秒）
    token_usage: Optional[Dict[str, int]] = None

    # 状态
    success: bool = True
    error: Optional[str] = None


class BaseRAGAdapter(ABC):
    """RAG系统适配器基类"""

    system_type: str
    display_name: str

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """发送查询请求"""
        pass

    @abstractmethod
    async def query_stream(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """流式查询请求，返回首token延迟信息

        子类可重写此方法以支持流式输出
        默认实现调用query并返回response_time作为first_token_latency
        """
        response = await self.query(question, contexts, conversation_id, **kwargs)
        # 默认使用完整响应时间作为首token延迟的近似值
        response.first_token_latency = response.response_time
        return response

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    @staticmethod
    async def _http_health_check(method: str, url: str,
                                 headers: Optional[Dict[str, str]] = None,
                                 json_body: Optional[Dict[str, Any]] = None,
                                 ok_below: int = 200) -> bool:
        """health_check 通用实现：发起一次轻量请求，按状态码判定健康

        ok_below=200 表示仅 200 健康；传更大的值（如 500）表示该值以下的状态码都算健康。
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, url, headers=headers, json=json_body)
                return response.status_code < ok_below
        except Exception:
            return False

    def get_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        return {
            "system_type": self.system_type,
            "display_name": self.display_name
        }