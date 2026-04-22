# 直连LLM适配器 - 直接调用LLM的OpenAI兼容API
import httpx
import time
import json
from typing import Optional, List, Dict, Any
from .base import BaseRAGAdapter, RAGResponse


class DirectLLMAdapter(BaseRAGAdapter):
    """直连LLM适配器 - 直接调用LLM的Chat Completions API"""

    system_type = "direct_llm"
    display_name = "直连LLM"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # 从配置获取LLM连接信息
        self.api_endpoint = config.get("api_endpoint", "")
        self.api_key = config.get("api_key", "")
        self.model_name = config.get("model_name", "")
        # 可选参数
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2048)
        self.provider = config.get("provider", "openai")  # openai/azure/zhipuai等

    def _get_chat_url(self) -> str:
        """获取Chat Completions API URL"""
        endpoint = self.api_endpoint.rstrip("/")

        if self.provider == "azure":
            # Azure OpenAI 使用 deployments 路径
            return f"{endpoint}/deployments/{self.model_name}/chat/completions?api-version=2024-02-01"
        else:
            # OpenAI 及兼容格式 (智谱、百度、阿里云、火山引擎等)
            return f"{endpoint}/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}

        if self.provider == "azure":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询LLM"""
        start_time = time.time()

        try:
            # 构建消息
            messages = []

            # 如果有上下文，添加到系统消息
            if contexts:
                context_text = "\n\n".join(contexts)
                messages.append({
                    "role": "system",
                    "content": f"请根据以下上下文信息回答问题：\n\n{context_text}"
                })

            # 添加用户问题
            messages.append({"role": "user", "content": question})

            # 构建请求体
            request_body = {
                "model": self.model_name,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._get_chat_url(),
                    headers=self._get_headers(),
                    json=request_body
                )
                response.raise_for_status()
                data = response.json()

            response_time = time.time() - start_time

            # 解析响应
            answer = ""
            token_usage = None

            if "choices" in data and len(data["choices"]) > 0:
                answer = data["choices"][0].get("message", {}).get("content", "")

            if "usage" in data:
                token_usage = {
                    "prompt_tokens": data["usage"].get("prompt_tokens", 0),
                    "completion_tokens": data["usage"].get("completion_tokens", 0),
                    "total_tokens": data["usage"].get("total_tokens", 0)
                }

            return RAGResponse(
                answer=answer,
                contexts=contexts or [],
                response_time=response_time,
                token_usage=token_usage,
                metadata={"model": self.model_name, "provider": self.provider},
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
        """流式查询LLM，返回首token延迟"""
        start_time = time.time()
        first_token_time = None

        try:
            # 构建消息
            messages = []
            if contexts:
                context_text = "\n\n".join(contexts)
                messages.append({
                    "role": "system",
                    "content": f"请根据以下上下文信息回答问题：\n\n{context_text}"
                })
            messages.append({"role": "user", "content": question})

            request_body = {
                "model": self.model_name,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True
            }

            answer_chunks = []

            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    self._get_chat_url(),
                    headers=self._get_headers(),
                    json=request_body
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.strip() and line.startswith("data:"):
                            data_str = line[5:].strip()  # 去掉 "data:" 前缀
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        if first_token_time is None:
                                            first_token_time = time.time() - start_time
                                        answer_chunks.append(content)
                            except json.JSONDecodeError:
                                continue

            response_time = time.time() - start_time
            answer = "".join(answer_chunks)

            return RAGResponse(
                answer=answer,
                contexts=contexts or [],
                response_time=response_time,
                first_token_latency=first_token_time,
                metadata={"model": self.model_name, "provider": self.provider, "streaming": True},
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
        """健康检查 - 发送简单测试请求"""
        try:
            messages = [{"role": "user", "content": "Hello"}]
            request_body = {
                "model": self.model_name,
                "messages": messages,
                "max_tokens": 10
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._get_chat_url(),
                    headers=self._get_headers(),
                    json=request_body
                )
                return response.status_code == 200
        except:
            return False