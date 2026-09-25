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
        """把异常转成可读错误文案：超时与上游 5xx 单独识别，其余交给 format_error"""
        if isinstance(exc, httpx.TimeoutException):
            return self.timeout_error_message()
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            # 上游网关 502/503/504 与"调大客户端超时"无关：请求根本没等到
            # 客户端超时就被网关掐了，继续调大 llm_timeout 没有意义。
            if code in (502, 503, 504):
                return (
                    f"上游服务返回 {code}（网关/反向代理超时或不可用）。"
                    "这是服务端限制，调大 llm_timeout 无效——通常是模型单次"
                    "生成耗时超过网关上限，请减少 max_tokens、改用非思考型"
                    "模型，或更换 RAG 系统/网关。"
                )
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