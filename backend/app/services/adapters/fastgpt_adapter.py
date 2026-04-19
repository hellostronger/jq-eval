# FastGPT 适配器
import httpx
import time
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class FastGPTAdapter(BaseRAGAdapter):
    """FastGPT RAG系统适配器"""

    system_type = "fastgpt"
    display_name = "FastGPT"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 支持 api_endpoint 或 api_url，用户输入如 https://cloud.fastgpt.cn/api
        base_url = (config.get("api_endpoint") or config.get("api_url", "")).rstrip("/")
        # 自动拼接 /v1
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self.api_url = base_url
        self.api_key = config.get("api_key", "")
        self.chat_id = config.get("chat_id", "eval-chat")

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询FastGPT"""
        start_time = time.time()

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "chatId": conversation_id or self.chat_id,
                "stream": False,
                "detail": True,  # 返回详细信息包括引用
                "messages": [
                    {
                        "role": "user",
                        "content": question
                    }
                ]
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            # 解析响应
            answer = ""
            contexts = []
            retrieval_ids = []

            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                answer = message.get("content", "")

                # FastGPT返回引用信息
                if "annotations" in choices[0]:
                    annotations = choices[0]["annotations"]
                    if "references" in annotations:
                        for ref in annotations["references"]:
                            contexts.append(ref.get("content", ""))
                            retrieval_ids.append(ref.get("id", ""))

            return RAGResponse(
                answer=answer,
                contexts=contexts,
                retrieval_ids=retrieval_ids,
                response_time=response_time,
                token_usage={
                    "input": data.get("usage", {}).get("prompt_tokens", 0),
                    "output": data.get("usage", {}).get("completion_tokens", 0)
                },
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
                response = await client.get(
                    f"{self.api_url}/app",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                return response.status_code == 200
        except:
            return False

    async def get_knowledge_bases(self) -> List[Dict[str, Any]]:
        """获取知识库列表"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.api_url}/knowledge/list",
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
        except Exception as e:
            return []

    async def get_dataset_list(
        self,
        knowledge_id: str,
        page: int = 1,
        page_size: int = 20
    ) -> List[Dict[str, Any]]:
        """获取知识库数据列表"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/knowledge/dataset/list",
                    headers=headers,
                    json={
                        "knowledgeId": knowledge_id,
                        "pageNum": page,
                        "pageSize": page_size
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", {}).get("list", [])
        except Exception as e:
            return []