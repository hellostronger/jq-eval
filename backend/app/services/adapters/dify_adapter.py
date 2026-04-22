# Dify 适配器
import httpx
import time
import json
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class DifyAdapter(BaseRAGAdapter):
    """Dify RAG系统适配器"""

    system_type = "dify"
    display_name = "Dify"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 支持 api_endpoint 或 api_url
        self.api_url = (config.get("api_endpoint") or config.get("api_url", "")).rstrip("/")
        self.api_key = config.get("api_key", "")
        self.app_type = config.get("app_type", "chat-app")
        self.user_id = config.get("user_id", "eval-user")

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询Dify"""
        start_time = time.time()

        try:
            endpoint = f"{self.api_url}/chat-messages"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "inputs": {},
                "query": question,
                "user": self.user_id,
                "response_mode": "blocking"
            }

            if conversation_id:
                payload["conversation_id"] = conversation_id

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            # 解析响应
            answer = data.get("answer", "")
            contexts = []
            retrieval_ids = []

            if "metadata" in data:
                metadata = data["metadata"]
                if "retriever_resources" in metadata:
                    for resource in metadata["retriever_resources"]:
                        contexts.append(resource.get("content", ""))
                        retrieval_ids.append(resource.get("dataset_id", ""))

            return RAGResponse(
                answer=answer,
                contexts=contexts,
                retrieval_ids=retrieval_ids,
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

    async def query_stream(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """流式查询Dify，返回首token延迟"""
        start_time = time.time()
        first_token_time = None

        try:
            endpoint = f"{self.api_url}/chat-messages"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "inputs": {},
                "query": question,
                "user": self.user_id,
                "response_mode": "streaming"
            }

            if conversation_id:
                payload["conversation_id"] = conversation_id

            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    answer_chunks = []
                    contexts = []
                    retrieval_ids = []

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                event = data.get("event")

                                if event == "message":
                                    # 记录首token时间（首次收到内容）
                                    if first_token_time is None and data.get("answer"):
                                        first_token_time = time.time() - start_time

                                if event == "message_end":
                                    break

                                if "answer" in data and data["answer"]:
                                    answer_chunks.append(data["answer"])

                                if "metadata" in data and "retriever_resources" in data["metadata"]:
                                    for resource in data["metadata"]["retriever_resources"]:
                                        contexts.append(resource.get("content", ""))
                                        retrieval_ids.append(resource.get("dataset_id", ""))
                            except json.JSONDecodeError:
                                continue

                    response_time = time.time() - start_time
                    answer = "".join(answer_chunks)

                    return RAGResponse(
                        answer=answer,
                        contexts=contexts,
                        retrieval_ids=retrieval_ids,
                        response_time=response_time,
                        first_token_latency=first_token_time,
                        metadata={"streaming": True},
                        success=True
                    )

        except Exception as e:
            response_time = time.time() - start_time
            return RAGResponse(
                answer="",
                response_time=response_time,
                first_token_latency=first_token_time,
                error=str(e),
                success=False
            )

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_url}/parameters",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                return response.status_code == 200
        except:
            return False