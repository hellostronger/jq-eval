# 自定义 RAG系统适配器
import httpx
import time
import json
import re
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class CustomAdapter(BaseRAGAdapter):
    """自定义RAG系统适配器"""

    system_type = "custom"
    display_name = "自定义系统"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("api_url", "")
        self.request_method = config.get("request_method", "POST")
        self.request_template = config.get("request_template", {})
        self.response_parser = config.get("response_parser", {})
        self.auth_config = config.get("auth_config", {})

    def _build_request(self, question: str, **kwargs) -> Dict[str, Any]:
        """构建请求"""
        body_template = self.request_template.get("body_template", '{"question": "{{question}}"}')

        # 变量替换
        variables = {
            "question": question,
            **kwargs
        }

        for key, value in variables.items():
            if isinstance(value, str):
                body_template = body_template.replace(f"{{{{{key}}}}}", value)
            elif isinstance(value, (list, dict)):
                body_template = body_template.replace(f"{{{{{key}}}}}", json.dumps(value))

        try:
            return json.loads(body_template)
        except:
            return {"question": question}

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = self.request_template.get("headers", {})
        headers["Content-Type"] = "application/json"

        # 添加认证
        if "type" in self.auth_config:
            if self.auth_config["type"] == "bearer":
                headers["Authorization"] = f"Bearer {self.auth_config.get('token', '')}"
            elif self.auth_config["type"] == "api_key":
                key_name = self.auth_config.get("key_name", "X-API-Key")
                headers[key_name] = self.auth_config.get("key_value", "")

        return headers

    def _parse_response(self, data: Dict[str, Any]) -> tuple:
        """解析响应"""
        parser = self.response_parser

        # 提取答案
        answer_path = parser.get("answer_path", "answer")
        answer = self._extract_value(data, answer_path)

        # 提取上下文
        contexts_path = parser.get("contexts_path")
        contexts = []
        if contexts_path:
            contexts = self._extract_value(data, contexts_path) or []

        return answer, contexts

    def _extract_value(self, data: Dict[str, Any], path: str) -> Any:
        """从嵌套字典中提取值"""
        keys = path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                return None
        return value

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询自定义API"""
        start_time = time.time()

        try:
            payload = self._build_request(
                question=question,
                contexts=contexts,
                conversation_id=conversation_id,
                **kwargs
            )

            headers = self._get_headers()

            async with httpx.AsyncClient(timeout=60.0) as client:
                if self.request_method == "POST":
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        json=payload
                    )
                else:
                    response = await client.get(
                        self.api_url,
                        headers=headers,
                        params=payload
                    )

                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            answer, contexts = self._parse_response(data)

            return RAGResponse(
                answer=answer or "",
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
                response = await client.post(
                    self.api_url,
                    headers=self._get_headers(),
                    json={"health_check": True}
                )
                return response.status_code < 500
        except:
            return False