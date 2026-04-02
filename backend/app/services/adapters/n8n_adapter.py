# n8n 适配器
import httpx
import time
import base64
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class N8nAdapter(BaseRAGAdapter):
    """n8n Workflow RAG系统适配器"""

    system_type = "n8n"
    display_name = "n8n"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.webhook_url = config.get("webhook_url", "")
        self.auth_type = config.get("auth_type", "none")
        self.auth_config = config.get("auth_config", {})

    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证头"""
        headers = {"Content-Type": "application/json"}

        if self.auth_type == "basic":
            cred = base64.b64encode(
                f"{self.auth_config.get('username', '')}:{self.auth_config.get('password', '')}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {cred}"

        elif self.auth_type == "header":
            header_name = self.auth_config.get("header_name", "X-API-Key")
            header_value = self.auth_config.get("header_value", "")
            headers[header_name] = header_value

        elif self.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.auth_config.get('token', '')}"

        return headers

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """调用n8n Webhook"""
        start_time = time.time()

        try:
            headers = self._get_auth_headers()

            payload = {
                "question": question,
                "conversation_id": conversation_id,
                "contexts": contexts,
                **kwargs
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.webhook_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            # n8n返回格式由workflow定义，假设标准格式
            answer = data.get("answer", data.get("response", ""))
            contexts = data.get("contexts", data.get("references", []))

            return RAGResponse(
                answer=answer,
                contexts=contexts,
                response_time=response_time,
                metadata=data,
                success=True
            )

        except Exception as e:
            response_time = time.time() - start_time
            return RAGResponse(
                answer="",
                response_time=response_time,
                error=str(e),
                success=False
            )

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # n8n webhook健康检查需要发送测试请求
                response = await client.post(
                    self.webhook_url,
                    headers=self._get_auth_headers(),
                    json={"test": True, "health_check": True}
                )
                return response.status_code == 200
        except:
            return False