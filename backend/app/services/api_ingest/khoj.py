# Khoj 连接器
#
# 参考文档（2026-10 快照）：
# - https://docs.khoj.dev/
# - 上传：PUT /api/content/（multipart files）
# - 问答：POST /api/chat（{q, ...}）；流式是默认，非流式时取 response/references
#
# Khoj 没有知识库概念，按实例级文档接入（虚拟 KB khoj:account）。
# 它不提供“列全部分片”的接口，问答 references 只包含本次命中的内容。
from typing import Any, Dict, List, Optional

from .base import (
    BaseApiIngestConnector,
    ConnectorError,
    IngestCapabilities,
    KnowledgeBase,
    RemoteChunk,
    RemoteDocument,
    dig,
)

ACCOUNT_KB = "khoj:account"


class KhojConnector(BaseApiIngestConnector):
    system_type = "khoj"
    display_name = "Khoj"
    api_doc_url = "https://docs.khoj.dev/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="按实例级文档接入（虚拟知识库 khoj:account）；answers 的 references 作为上下文。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url
        self._uploaded: Dict[str, RemoteDocument] = {}

    async def _api(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return await self.request_json(
            method,
            f"{self.api_root}{path}",
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )

    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        return [KnowledgeBase(id=ACCOUNT_KB, name="Khoj 全部文档")]

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = [("files", (file_name, content, content_type or "application/octet-stream"))]
        payload = await self._api(
            "PUT",
            "/api/content/",
            files=files,
            timeout=self.upload_timeout,
        )
        doc_id = dig(payload, "id") or dig(payload, "file_name") or file_name
        document = RemoteDocument(
            id=str(doc_id),
            name=str(dig(payload, "file_name", file_name)),
            status="done",
            progress=1.0,
            raw=payload if isinstance(payload, dict) else {},
        )
        self._uploaded[document.id] = document
        return document

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        return list(self._uploaded.values())

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        return []

    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = await self._api(
            "POST",
            "/api/chat",
            json_body={
                "q": question,
                "stream": False,
                "conversation_id": conversation_id or chat_id or "jq-eval",
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if isinstance(payload, dict):
            for reference in payload.get("references") or []:
                if not isinstance(reference, dict):
                    continue
                additional = reference.get("additional") or {}
                text = (
                    reference.get("content")
                    or reference.get("snippet")
                    or additional.get("compiled")
                    or additional.get("snippet")
                )
                if text:
                    contexts.append(str(text))
                ref_id = additional.get("file") or reference.get("id")
                if ref_id:
                    retrieval_ids.append(str(ref_id))
        return {
            "answer": (payload.get("response") or payload.get("answer") or "") if isinstance(payload, dict) else "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
