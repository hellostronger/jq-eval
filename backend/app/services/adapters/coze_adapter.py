# Coze 适配器
import httpx
import time
import json
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class CozeAdapter(BaseRAGAdapter):
    """Coze RAG系统适配器 (字节跳动)"""

    system_type = "coze"
    display_name = "Coze"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 支持 api_endpoint 或 api_url
        self.api_url = (config.get("api_endpoint") or config.get("api_url", "https://api.coze.cn/v3")).rstrip("/")
        self.access_token = config.get("access_token", "")
        self.bot_id = config.get("bot_id", "")

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询Coze Bot"""
        start_time = time.time()

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            # Coze v3 API
            payload = {
                "bot_id": self.bot_id,
                "user_id": kwargs.get("user_id", "eval-user"),
                "stream": False,
                "auto_save_history": True,
                "additional_messages": [
                    {
                        "role": "user",
                        "content": question,
                        "content_type": "text"
                    }
                ]
            }

            if conversation_id:
                payload["conversation_id"] = conversation_id

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            # 解析响应
            answer = ""
            contexts = []

            if data.get("data"):
                chat_data = data["data"]
                # 获取Bot回复
                for message in chat_data.get("messages", []):
                    if message.get("role") == "assistant" and message.get("type") == "answer":
                        answer = message.get("content", "")
                        break

                # 获取检索的文档
                for message in chat_data.get("messages", []):
                    if message.get("type") == "knowledge":
                        contexts.append(message.get("content", ""))

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
        """流式查询Coze Bot，返回首token延迟"""
        start_time = time.time()
        first_token_time = None

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "bot_id": self.bot_id,
                "user_id": kwargs.get("user_id", "eval-user"),
                "stream": True,
                "auto_save_history": True,
                "additional_messages": [
                    {
                        "role": "user",
                        "content": question,
                        "content_type": "text"
                    }
                ]
            }

            if conversation_id:
                payload["conversation_id"] = conversation_id

            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", f"{self.api_url}/chat", headers=headers, json=payload) as response:
                    response.raise_for_status()
                    answer_chunks = []
                    contexts = []

                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                # Coze流式响应处理
                                event = data.get("event")
                                if event == "message":
                                    msg_data = data.get("data", {})
                                    if msg_data.get("type") == "answer":
                                        content = msg_data.get("content", "")
                                        if content:
                                            if first_token_time is None:
                                                first_token_time = time.time() - start_time
                                            answer_chunks.append(content)
                                elif event == "done":
                                    break
                            except json.JSONDecodeError:
                                continue

                    response_time = time.time() - start_time
                    answer = "".join(answer_chunks)

                    return RAGResponse(
                        answer=answer,
                        contexts=contexts,
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
                    f"{self.api_url}/bots/{self.bot_id}",
                    headers={"Authorization": f"Bearer {self.access_token}"}
                )
                return response.status_code == 200
        except:
            return False

    async def get_conversations(
        self,
        page: int = 1,
        page_size: int = 20
    ) -> List[Dict[str, Any]]:
        """获取对话列表"""
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.api_url}/conversations",
                    headers=headers,
                    params={
                        "bot_id": self.bot_id,
                        "page": page,
                        "page_size": page_size
                    }
                )
                response.raise_for_status()
                data = response.json()

                return data.get("data", {}).get("conversations", [])
        except Exception as e:
            return []