# DocsGPT 连接器
#
# 参考文档（2026-10 快照）：
# - https://docs.docsgpt.cloud/
# - 上传：POST /api/upload（multipart file）
# - 文档：GET  /api/docs
# - 问答：POST /api/chat（{question, history, retriever}）
#
# DocsGPT 没有独立知识库 ID，按实例级文档接入（虚拟 KB docsgpt:account）。
# 上传接口通常只返回成功状态，因此文档 ID 用文件名；状态以 /api/docs 是否出现为准。
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

ACCOUNT_KB = "docsgpt:account"


class DocsGPTConnector(BaseApiIngestConnector):
    system_type = "docsgpt"
    display_name = "DocsGPT"
    api_doc_url = "https://docs.docsgpt.cloud/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="按实例级文档接入（虚拟知识库 docsgpt:account）；无分片枚举。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url

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
        return [KnowledgeBase(id=ACCOUNT_KB, name="DocsGPT 全部文档")]

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        payload = await self._api(
            "POST",
            "/api/upload",
            data={"name": file_name},
            files=files,
            timeout=self.upload_timeout,
        )
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ConnectorError(f"DocsGPT 上传 {file_name} 失败：{payload.get('message')}")
        doc_id = dig(payload, "id") or dig(payload, "data.id") or file_name
        return RemoteDocument(
            id=str(doc_id),
            name=str(dig(payload, "name", file_name)),
            status="done",
            progress=1.0,
            raw=payload if isinstance(payload, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api("GET", "/api/docs")
        items = payload.get("docs") if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("documents") or items.get("items") or []
        return [
            RemoteDocument(
                id=str(item.get("id") or item.get("name") or item.get("file_name")),
                name=str(item.get("name") or item.get("file_name") or item.get("id")),
                status="done",
                progress=1.0,
                raw=item,
            )
            for item in items or []
            if isinstance(item, dict) and (item.get("name") or item.get("id"))
        ]

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
                "question": question,
                "history": [],
                "retriever": self.config.get("retriever") or "classic",
                "stream": False,
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if isinstance(payload, dict):
            for source in payload.get("sources") or []:
                if isinstance(source, str):
                    contexts.append(source)
                    continue
                if not isinstance(source, dict):
                    continue
                text = source.get("text") or source.get("content") or source.get("page_content")
                if text:
                    contexts.append(str(text))
                ref_id = source.get("id") or source.get("source") or source.get("title")
                if ref_id:
                    retrieval_ids.append(str(ref_id))
        return {
            "answer": (payload.get("answer") or payload.get("response") or "") if isinstance(payload, dict) else "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
