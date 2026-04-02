# RAG系统适配器基类
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime


class RAGResponse(BaseModel):
    """RAG系统统一响应"""
    answer: str
    contexts: Optional[List[str]] = None
    retrieval_ids: Optional[List[str]] = None
    metadata: Dict[str, Any] = {}

    # 性能指标
    response_time: float = 0.0
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
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        return {
            "system_type": self.system_type,
            "display_name": self.display_name
        }