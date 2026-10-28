# 通用连接器适配器
#
# 用途：所有已经在 api_ingest 里实现了 ask 的系统（原生连接器或 profile），
# 评测侧不再各写一份 HTTP 逻辑——直接用同一个连接器，保证
# 「入库时的鉴权/字段」与「评测时的鉴权/字段」不会漂移。
from typing import Any, Dict, List, Optional

from app.services.api_ingest import create_connector

from .base import BaseRAGAdapter, RAGResponse


class ConnectorAdapter(BaseRAGAdapter):
    """把 api_ingest 连接器包装成评测适配器"""

    system_type = ""
    display_name = "API 接入系统"

    def __init__(self, config: Dict[str, Any], system_type: Optional[str] = None):
        super().__init__(config)
        if system_type:
            self.system_type = system_type
        self.connector = create_connector(self.system_type, config)
        self.display_name = self.connector.display_name

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs: Any,
    ) -> RAGResponse:
        import time

        start_time = time.time()
        try:
            data = await self.connector.ask(question, conversation_id=conversation_id)
            return RAGResponse(
                answer=data.get("answer") or "",
                contexts=data.get("contexts") or [],
                retrieval_ids=data.get("retrieval_ids") or [],
                response_time=time.time() - start_time,
                metadata=data.get("metadata") or {},
                success=True,
            )
        except Exception as e:
            return RAGResponse(
                answer="",
                response_time=time.time() - start_time,
                error=self.error_message(e),
                success=False,
            )

    async def query_stream(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs: Any,
    ) -> RAGResponse:
        response = await self.query(question, contexts, conversation_id, **kwargs)
        response.first_token_latency = response.response_time
        return response

    async def health_check(self) -> bool:
        result = await self.connector.check_connection()
        return bool(result.get("healthy"))
