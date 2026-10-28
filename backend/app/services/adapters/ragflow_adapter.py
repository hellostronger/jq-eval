# RAGFlow 查询适配器（评测调用链）
#
# 与 api_ingest.RAGFlowConnector 的区别：
# - Connector 负责建库/上传/解析/拉分片（准备阶段）
# - 本适配器只负责 query/query_stream/health_check（评测阶段），
#   由 AdapterFactory 统一创建，接口与 Dify/FastGPT 适配器一致。
#
# 参考：https://ragflow.io/docs/dev/http_api_reference
# 对话接口：POST /api/v1/chats/{chat_id}/completions
#   body: {"question": "...", "stream": false, "session_id": "..."}
#   resp: data.answer / data.reference.chunks[{id, content, document_id, similarity}]
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseRAGAdapter, RAGResponse


class RAGFlowAdapter(BaseRAGAdapter):
    """RAGFlow 对话适配器"""

    system_type = "ragflow"
    display_name = "RAGFlow"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        base = (config.get("api_endpoint") or config.get("api_url") or "").rstrip("/")
        if base.endswith("/api/v1"):
            self.api_root = base
        elif base.endswith("/v1"):
            self.api_root = base
        else:
            self.api_root = f"{base}/api/v1"
        self.api_key = config.get("api_key", "")
        self.chat_id = config.get("chat_id", "")
        self.session_id = config.get("session_id", "")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _check(self, data: Dict[str, Any]) -> None:
        code = data.get("code")
        if code not in (None, 0):
            raise RuntimeError(
                f"RAGFlow API 返回 code={code}: {data.get('message') or data}"
            )

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        """查询 RAGFlow 会话助手"""
        start_time = time.time()
        if not self.chat_id:
            return RAGResponse(
                answer="",
                error="RAGFlow 未配置 chat_id：请先在 RAGFlow 创建会话助手，或在连接配置中填写 chat_id",
                success=False,
            )

        try:
            body: Dict[str, Any] = {"question": question, "stream": False}
            session_id = conversation_id or self.session_id
            if session_id:
                body["session_id"] = session_id

            async with httpx.AsyncClient(timeout=self.llm_timeout) as client:
                response = await client.post(
                    f"{self.api_root}/chats/{self.chat_id}/completions",
                    headers=self._headers(),
                    json=body,
                )
                response.raise_for_status()
                data = response.json()

            self._check(data)
            payload = data.get("data") or {}
            answer = payload.get("answer") or ""
            refs = ((payload.get("reference") or {}).get("chunks") or [])
            ref_contexts = [
                ref.get("content") or ref.get("content_with_weight") or ""
                for ref in refs
                if ref.get("content") or ref.get("content_with_weight")
            ]
            ref_ids = [str(ref.get("id")) for ref in refs if ref.get("id")]

            return RAGResponse(
                answer=answer,
                contexts=ref_contexts,
                retrieval_ids=ref_ids,
                response_time=time.time() - start_time,
                metadata=payload,
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
        **kwargs
    ) -> RAGResponse:
        """流式查询：RAGFlow 以 SSE 返回 answer/reference"""
        start_time = time.time()
        first_token_time = None
        if not self.chat_id:
            return RAGResponse(
                answer="",
                error="RAGFlow 未配置 chat_id",
                success=False,
            )

        try:
            body: Dict[str, Any] = {"question": question, "stream": True}
            session_id = conversation_id or self.session_id
            if session_id:
                body["session_id"] = session_id

            answer_chunks: List[str] = []
            ref_contexts: List[str] = []
            ref_ids: List[str] = []

            async with httpx.AsyncClient(timeout=self.llm_timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_root}/chats/{self.chat_id}/completions",
                    headers=self._headers(),
                    json=body,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        payload = data.get("data") or data
                        if payload.get("answer"):
                            if first_token_time is None:
                                first_token_time = time.time() - start_time
                            answer_chunks.append(payload["answer"])
                        for ref in ((payload.get("reference") or {}).get("chunks") or []):
                            content = ref.get("content") or ref.get("content_with_weight")
                            if content:
                                ref_contexts.append(content)
                            if ref.get("id"):
                                ref_ids.append(str(ref["id"]))
                        if payload.get("final"):
                            break

            return RAGResponse(
                answer="".join(answer_chunks),
                contexts=ref_contexts,
                retrieval_ids=ref_ids,
                response_time=time.time() - start_time,
                first_token_latency=first_token_time,
                metadata={"streaming": True},
                success=True,
            )
        except Exception as e:
            return RAGResponse(
                answer="",
                response_time=time.time() - start_time,
                first_token_latency=first_token_time,
                error=self.error_message(e),
                success=False,
            )

    async def health_check(self) -> bool:
        return await self._http_health_check(
            "GET",
            f"{self.api_root}/datasets",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
