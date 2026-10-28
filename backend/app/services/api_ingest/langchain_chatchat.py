# Langchain-Chatchat 连接器
#
# 参考文档 / 源码（2026-10 快照）：
# - 仓库：https://github.com/chatchat-space/Langchain-Chatchat
# - API Server（默认 7861）：
#   GET  /knowledge_base/list_knowledge_bases
#   POST /knowledge_base/create_knowledge_base   {knowledge_base_name, vector_store_type, embed_model}
#   POST /knowledge_base/upload_docs             multipart files + knowledge_base_name
#   GET  /knowledge_base/list_files              ?knowledge_base_name=...
#   POST /chat/chat                              {query, knowledge_base_name, history, stream:false}
#
# 认证：若服务端配置了 api_key，则用 X-API-KEY 头（可用 api_key_header 覆盖）。
# 说明：upload_docs 会直接写入向量库，没有单独的解析/状态接口；
# 分片只能通过 search_docs 按查询取 TopK，无法枚举全量，故 list_chunks=False。
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


class LangchainChatchatConnector(BaseApiIngestConnector):
    system_type = "langchain_chatchat"
    display_name = "Langchain-Chatchat"
    api_doc_url = "https://github.com/chatchat-space/Langchain-Chatchat"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="上传即写入向量库；无分片枚举接口。建库需指定 vector_store_type 与 embed_model。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url

    def auth_headers(self) -> Dict[str, str]:
        if not self.api_key:
            return {}
        header = self.config.get("api_key_header") or "X-API-KEY"
        return {header: self.api_key}

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
        payload = await self.request_json(
            method,
            f"{self.api_root}{path}",
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )
        if isinstance(payload, dict) and "code" in payload and payload.get("code") not in (200, 0, None):
            raise ConnectorError(
                f"Langchain-Chatchat 返回 code={payload.get('code')}：{payload.get('msg') or payload}"
            )
        return payload

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        payload = await self._api("GET", "/knowledge_base/list_knowledge_bases")
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("knowledge_bases") or items.get("items") or []
        result: List[KnowledgeBase] = []
        for item in items or []:
            if isinstance(item, str):
                result.append(KnowledgeBase(id=item, name=item))
            elif isinstance(item, dict):
                name = item.get("knowledge_base_name") or item.get("name") or item.get("id")
                if name:
                    result.append(KnowledgeBase(id=str(name), name=str(name), raw=item))
        return result

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        await self._api(
            "POST",
            "/knowledge_base/create_knowledge_base",
            json_body={
                "knowledge_base_name": name,
                "vector_store_type": kwargs.get("vector_store_type")
                or self.config.get("vector_store_type")
                or "faiss",
                "embed_model": kwargs.get("embed_model")
                or self.config.get("embed_model")
                or "bge-m3",
                "kb_info": kwargs.get("description") or self.config.get("kb_description") or name,
            },
        )
        return KnowledgeBase(id=name, name=name)

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = [("files", (file_name, content, content_type or "application/octet-stream"))]
        payload = await self._api(
            "POST",
            "/knowledge_base/upload_docs",
            data={
                "knowledge_base_name": kb_id,
                "override": "true",
                "to_vector_store": "true",
                "chunk_size": str(self.config.get("chunk_size") or 750),
                "chunk_overlap": str(self.config.get("chunk_overlap") or 150),
                "zh_title_enhance": "false",
                "docs": "{}",
            },
            files=files,
            timeout=self.upload_timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        failed = dig(data, "failed_files", []) or []
        if failed:
            raise ConnectorError(f"Langchain-Chatchat 上传 {file_name} 失败：{failed}")
        return RemoteDocument(
            id=file_name,
            name=file_name,
            status="done",
            progress=1.0,
            raw=data if isinstance(data, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api(
            "GET",
            "/knowledge_base/list_files",
            params={"knowledge_base_name": kb_id},
        )
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("files") or items.get("items") or []
        return [
            RemoteDocument(
                id=str(item.get("file_name") or item.get("id") or item.get("name")),
                name=str(item.get("file_name") or item.get("name") or item.get("id")),
                status="done",
                progress=1.0,
                raw=item,
            )
            for item in items or []
            if isinstance(item, dict) and (item.get("file_name") or item.get("id"))
        ]

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        return []

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        kb_name = (
            chat_id
            or self.config.get("knowledge_base_name")
            or self.config.get("kb_name")
            or self.config.get("kb_id")
        )
        if not kb_name:
            raise ConnectorError("Langchain-Chatchat 问答需要 knowledge_base_name（chat_id）")
        payload = await self._api(
            "POST",
            "/chat/chat",
            json_body={
                "query": question,
                "knowledge_base_name": kb_name,
                "history": [],
                "stream": False,
                "model_name": self.config.get("model") or "qwen",
                "temperature": float(self.config.get("temperature") or 0.7),
                "top_k": int(self.config.get("top_k") or 3),
                "score_threshold": float(self.config.get("score_threshold") or 1.0),
                "max_tokens": int(self.config.get("max_tokens") or 1024),
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        docs = dig(data, "docs", []) or []
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            text = doc.get("page_content") or doc.get("content")
            if text:
                contexts.append(str(text))
            metadata = doc.get("metadata") or {}
            ref_id = metadata.get("id") or metadata.get("source") or metadata.get("file_name")
            if ref_id:
                retrieval_ids.append(str(ref_id))
        return {
            "answer": (dig(data, "answer", "") or dig(data, "response", "") or ""),
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": data if isinstance(data, dict) else {},
        }
