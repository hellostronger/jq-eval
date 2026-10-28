# LightRAG（lightrag-server）连接器
#
# 参考文档 / 源码（2026-10 快照）：
# - 仓库：https://github.com/HKUDS/LightRAG
# - Server API：lightrag/api/routers/document_routes.py、query_routes.py
#   POST /documents           multipart file（或 JSON text）上传并建图/向量
#   GET  /documents           文档状态（statuses / documents）
#   GET  /documents/{doc_id}  单文档状态
#   GET  /chunks              分段列表（按 document_id 过滤）
#   POST /query               {query, mode:"mix", include_references:true}
#
# 认证：X-API-Key: <LIGHTRAG_API_KEY>；不同部署也可能改成 Authorization: Bearer，
# 连接配置里的 api_key_header 可覆盖。
#
# LightRAG 没有“知识库”概念，所有文档在同一实例里；这里用一个虚拟 KB
# （lightrag:account）承接，入库与问答都按账号级处理。
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

ACCOUNT_KB = "lightrag:account"


class LightRAGConnector(BaseApiIngestConnector):
    system_type = "lightrag"
    display_name = "LightRAG"
    api_doc_url = "https://github.com/HKUDS/LightRAG"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=False,
        list_chunks=True,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="按实例级文档接入（虚拟知识库 lightrag:account）；图谱与向量混合检索。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url

    def auth_headers(self) -> Dict[str, str]:
        if not self.api_key:
            return {}
        header = self.config.get("api_key_header") or "X-API-Key"
        if header.lower() == "authorization":
            return {"Authorization": f"Bearer {self.api_key}"}
        return {header: self.api_key}

    async def _api(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        files: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return await self.request_json(
            method,
            f"{self.api_root}{path}",
            params=params,
            json_body=json_body,
            files=files,
            timeout=timeout,
        )

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        return [KnowledgeBase(id=ACCOUNT_KB, name="LightRAG 全部文档")]

    # ---------------------------------------------------------------- 文档
    @staticmethod
    def _document_items(payload: Any) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        statuses = payload.get("statuses")
        if isinstance(statuses, dict):
            items = []
            for doc_id, value in statuses.items():
                if isinstance(value, dict):
                    items.append({"id": doc_id, **value})
                else:
                    items.append({"id": doc_id, "status": value})
            return items
        for key in ("documents", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [
                    {"id": doc_id, **detail}
                    for doc_id, detail in value.items()
                    if isinstance(detail, dict)
                ]
        return []

    async def _find_document(self, file_name: str) -> Optional[Dict[str, Any]]:
        payload = await self._api("GET", "/documents")
        for item in self._document_items(payload):
            file_path = str(item.get("file_path") or item.get("file_name") or item.get("name") or "")
            if file_path == file_name or file_path.endswith(f"/{file_name}") or file_path.endswith(file_name):
                return item
        return None

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        payload = await self._api("POST", "/documents", files=files, timeout=self.upload_timeout)
        if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "error":
            raise ConnectorError(f"LightRAG 上传 {file_name} 失败：{payload.get('message') or payload}")

        matched = await self._find_document(file_name)
        if matched:
            return RemoteDocument(
                id=str(matched.get("id") or payload.get("track_id") or file_name),
                name=str(matched.get("file_path") or file_name),
                status="pending",
                raw=matched,
            )
        return RemoteDocument(
            id=str(payload.get("track_id") or payload.get("doc_id") or file_name),
            name=file_name,
            status="pending",
            raw=payload if isinstance(payload, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api("GET", "/documents")
        return [self._map_document(item) for item in self._document_items(payload)]

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(item.get("status") or "").lower()
        if raw_status in ("processed", "completed", "done", "success", "finished"):
            status = "done"
        elif raw_status in ("failed", "error"):
            status = "failed"
        elif raw_status in ("pending", "processing", "parsing", "queued", "running"):
            status = "running"
        else:
            status = "pending"
        error = None
        if status == "failed":
            error = str(item.get("error") or "") or "解析失败"
        return RemoteDocument(
            id=str(item.get("id") or item.get("doc_id")),
            name=str(item.get("file_path") or item.get("file_name") or item.get("name") or item.get("id")),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        chunks: List[RemoteChunk] = []
        page = 1
        while True:
            payload = await self._api(
                "GET",
                "/chunks",
                params={"document_id": document_id, "page": page, "page_size": 100},
            )
            if not isinstance(payload, dict):
                break
            items = payload.get("chunks") or payload.get("data") or payload.get("items") or []
            if not isinstance(items, list):
                break
            for item in items:
                content = item.get("content") or item.get("text") or ""
                if not content:
                    continue
                chunks.append(
                    RemoteChunk(
                        id=str(item.get("id") or item.get("chunk_id") or f"{document_id}-{len(chunks)}"),
                        content=content,
                        document_id=str(item.get("document_id") or document_id),
                        index=int(item.get("chunk_order_index") or item.get("index") or len(chunks)),
                        raw=item,
                    )
                )
            if len(items) < 100:
                break
            page += 1
        return chunks

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = await self._api(
            "POST",
            "/query",
            json_body={
                "query": question,
                "mode": self.config.get("query_mode") or "mix",
                "include_references": True,
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if isinstance(payload, dict):
            for reference in payload.get("references") or []:
                if not isinstance(reference, dict):
                    continue
                text = reference.get("content") or reference.get("text")
                if text:
                    contexts.append(str(text))
                ref_id = reference.get("reference_id") or reference.get("id")
                if ref_id:
                    retrieval_ids.append(str(ref_id))
        return {
            "answer": (payload.get("response") or payload.get("answer") or "") if isinstance(payload, dict) else "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
