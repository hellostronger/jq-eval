# PrivateGPT 连接器
#
# 参考文档（2026-10 快照）：
# - https://docs.privategpt.dev/
# - 上传：POST /v1/ingest（multipart file）
# - 问答：POST /v1/chat/completions（OpenAI 兼容，use_context=true）
#
# PrivateGPT 没有知识库概念，所有文档进入同一实例；这里用虚拟 KB
# privategpt:account 承接。分片不对外枚举，问答依赖返回的 sources/context。
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

ACCOUNT_KB = "privategpt:account"


class PrivateGPTConnector(BaseApiIngestConnector):
    system_type = "privategpt"
    display_name = "PrivateGPT"
    api_doc_url = "https://docs.privategpt.dev/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="按实例级文档接入（虚拟知识库 privategpt:account）；无分片枚举。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = self.base_url
        # 无状态接口：记录本次进程内上传成功的文档，供 wait_documents_ready 轮询
        self._uploaded: Dict[str, RemoteDocument] = {}

    async def _api(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        files: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        return await self.request_json(
            method,
            f"{self.api_root}{path}",
            json_body=json_body,
            files=files,
            timeout=timeout,
        )

    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        return [KnowledgeBase(id=ACCOUNT_KB, name="PrivateGPT 全部文档")]

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        payload = await self._api("POST", "/v1/ingest", files=files, timeout=self.upload_timeout)
        doc_id = dig(payload, "id") or dig(payload, "doc_id")
        if not doc_id:
            raise ConnectorError(f"PrivateGPT 上传 {file_name} 未返回 ID：{payload}")
        document = RemoteDocument(
            id=str(doc_id),
            name=str(dig(payload, "name", file_name)),
            status="done",
            progress=1.0,
            raw=payload if isinstance(payload, dict) else {},
        )
        self._uploaded[document.id] = document
        return document

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        # 没有稳定的“列全部文档”接口；只返回当前会话刚上传的文档，
        # 避免把实例里别人的文档误当成本次入库结果。
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
            "/v1/chat/completions",
            json_body={
                "model": self.config.get("model") or "private-gpt",
                "messages": [{"role": "user", "content": question}],
                "stream": False,
                "use_context": True,
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if isinstance(payload, dict):
            sources = (
                payload.get("sources")
                or payload.get("contexts")
                or payload.get("context")
                or []
            )
            if isinstance(sources, str):
                sources = [sources]
            for source in sources:
                if isinstance(source, str):
                    contexts.append(source)
                    continue
                if not isinstance(source, dict):
                    continue
                text = source.get("content") or source.get("text") or source.get("page_content")
                if text:
                    contexts.append(str(text))
                ref_id = source.get("id") or source.get("document_id") or source.get("file_name")
                if ref_id:
                    retrieval_ids.append(str(ref_id))
        return {
            "answer": dig(payload, "choices.0.message.content", "") or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
