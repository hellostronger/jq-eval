# R2R（SciPhi）连接器
#
# 参考文档（2026-10 快照，仓库最后更新 2025-11）：
# - https://r2r-docs.sciphi.ai/
# - 上传：POST /v3/documents（multipart file + metadata）
# - 文档：GET  /v3/documents、GET /v3/documents/{id}
# - 分片：GET  /v3/documents/{id}/chunks
# - 检索/问答：POST /v3/retrieval（chunk_search_results + generated_answer）
#
# 认证：Authorization: Bearer <R2R API Key>。
# R2R 没有知识库概念，按实例级文档接入（虚拟 KB r2r:account）。
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

ACCOUNT_KB = "r2r:account"


class R2RConnector(BaseApiIngestConnector):
    system_type = "r2r"
    display_name = "R2R"
    api_doc_url = "https://r2r-docs.sciphi.ai/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=False,
        list_chunks=True,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="按实例级文档接入（虚拟知识库 r2r:account）；仓库近一年未更新，按 v3 契约实现。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url

    async def _api(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return await self.request_json(
            method,
            f"{self.api_root}{path}",
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )

    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        return [KnowledgeBase(id=ACCOUNT_KB, name="R2R 全部文档")]

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        import json

        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        payload = await self._api(
            "POST",
            "/v3/documents",
            data={"metadata": json.dumps({"title": file_name}, ensure_ascii=False)},
            files=files,
            timeout=self.upload_timeout,
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        document = results[0] if isinstance(results, list) and results else results
        doc_id = (
            dig(document, "document_id")
            or dig(document, "id")
            or dig(payload, "document_id")
            or file_name
        )
        if isinstance(document, dict) and document.get("success") is False:
            raise ConnectorError(f"R2R 上传 {file_name} 失败：{document}")
        return RemoteDocument(
            id=str(doc_id),
            name=str(dig(document, "title", file_name)),
            status="pending",
            raw=document if isinstance(document, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api(
            "GET",
            "/v3/documents",
            params={"page_size": 100},
        )
        items = payload.get("results") if isinstance(payload, dict) else payload
        return [self._map_document(item) for item in items or [] if isinstance(item, dict)]

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(
            item.get("status") or item.get("ingestion_status") or item.get("processing_status") or ""
        ).lower()
        if raw_status in ("success", "completed", "done", "processed", "ready"):
            status = "done"
        elif raw_status in ("failed", "error"):
            status = "failed"
        elif raw_status in ("pending", "processing", "parsing", "running", "queued"):
            status = "running"
        else:
            status = "pending"
        error = None
        if status == "failed":
            error = str(item.get("error") or item.get("message") or "解析失败")
        return RemoteDocument(
            id=str(item.get("id") or item.get("document_id")),
            name=str(item.get("title") or item.get("name") or item.get("id")),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        payload = await self._api("GET", f"/v3/documents/{document_id}/chunks")
        items = payload.get("results") if isinstance(payload, dict) else payload
        chunks: List[RemoteChunk] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            content = item.get("text") or item.get("content") or ""
            if not content:
                continue
            chunks.append(
                RemoteChunk(
                    id=str(item.get("id") or f"{document_id}-{len(chunks)}"),
                    content=content,
                    document_id=str(item.get("document_id") or document_id),
                    index=int(item.get("chunk_order") or item.get("index") or len(chunks)),
                    raw=item,
                )
            )
        return chunks

    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": question,
            "search_settings": {"limit": int(self.config.get("top_k") or 10)},
        }
        model = self.config.get("model")
        if model:
            body["rag_generation_config"] = {"model": model, "stream": False}
        payload = await self._api(
            "POST",
            "/v3/retrieval",
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        results = payload.get("results") if isinstance(payload, dict) else {}
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for item in (results or {}).get("chunk_search_results") or []:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content")
            if text:
                contexts.append(str(text))
            ref_id = item.get("id") or item.get("chunk_id")
            if ref_id:
                retrieval_ids.append(str(ref_id))
        return {
            "answer": (payload.get("generated_answer") or "") if isinstance(payload, dict) else "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
