# RAG系统适配器基类
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

import httpx

from app.core.exceptions import format_error


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

    # LLM 生成类请求的默认超时（秒）：推理型模型/慢网关一次补全可达 60s+，
    # 取 300 覆盖最坏情况；健康检查仍用各自的短超时。
    #
    # 这只是默认值。思考型模型把 max_tokens 拉到 4096 时，300s 会被真实
    # 跑满（表现为 ReadTimeout），此时应通过连接配置里的 llm_timeout 放宽，
    # 而不是把这里的常量无限调大——不同 RAG 系统的时延差异极大。
    LLM_TIMEOUT = 300.0

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # 实例级超时：连接配置可覆盖默认常量。
        # 非法值（0/负数/非数字）一律回落默认，避免把请求变成立即超时。
        try:
            override = float(config.get("llm_timeout") or 0)
        except (TypeError, ValueError):
            override = 0.0
        self.llm_timeout = override if override > 0 else self.LLM_TIMEOUT

    def timeout_error_message(self) -> str:
        """超时的可读错误文案——超时是最常见的失败原因，不该只报一个类名"""
        return (
            f"请求 RAG 系统超时（{self.llm_timeout:.0f}s）。"
            "若模型为思考型且 max_tokens 较大，请在 RAG 系统连接配置中"
            "调大 llm_timeout，或改用非思考模型。"
        )

    def error_message(self, exc: BaseException) -> str:
        """把异常转成可读错误文案：超时单独识别，其余交给 format_error 兜底"""
        if isinstance(exc, httpx.TimeoutException):
            return self.timeout_error_message()
        return format_error(exc)

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