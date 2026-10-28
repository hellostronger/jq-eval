# QAnything 连接器
#
# 参考文档 / 源码（2026-10 快照）：
# - 仓库：https://github.com/netease-youdao/QAnything
# - 本地 API（默认 8777，前缀 /api/local_doc_qa）：
#   POST /create_kb      {user_id, kb_name}
#   POST /list_kbs       {user_id}
#   POST /upload_files   multipart files + user_id / kb_id / mode
#   POST /list_files     {user_id, kb_id}
#   POST /chat           {user_id, kb_ids, question, history}
#
# 认证：本地部署默认无鉴权；如果放在网关后，可用 api_key + api_key_header 注入。
# QAnything 的文档上传后异步解析，list_files 返回状态；分片不对外枚举，
# 问答返回 source_documents 作为上下文。
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


class QAnythingConnector(BaseApiIngestConnector):
    system_type = "qanything"
    display_name = "QAnything"
    api_doc_url = "https://github.com/netease-youdao/QAnything"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="user_id + kb_id 隔离；上传后自动解析，无分片枚举接口。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        self.api_root = f"{self.base_url}/api/local_doc_qa"
        self.user_id = str(self.config.get("user_id") or "jq-eval")

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
        payload = await self.request_json(
            method,
            f"{self.api_root}{path}",
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )
        if isinstance(payload, dict) and "code" in payload and payload.get("code") not in (200, 0, None):
            raise ConnectorError(
                f"QAnything 返回 code={payload.get('code')}：{payload.get('msg') or payload}"
            )
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        data = await self._api("POST", "/list_kbs", json_body={"user_id": self.user_id})
        items = data if isinstance(data, list) else (data or {}).get("kbs") or []
        return [
            KnowledgeBase(
                id=str(item.get("kb_id")),
                name=str(item.get("kb_name") or item.get("kb_id")),
                raw=item,
            )
            for item in items
            if item.get("kb_id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        data = await self._api(
            "POST",
            "/create_kb",
            json_body={"user_id": self.user_id, "kb_name": name},
        )
        data = data or {}
        kb_id = data.get("kb_id") if isinstance(data, dict) else None
        if not kb_id:
            # 有的版本只返回成功，回查一次
            for kb in await self.list_knowledge_bases():
                if kb.name == name:
                    return kb
            raise ConnectorError(f"QAnything 建库未返回 kb_id：{data}")
        return KnowledgeBase(id=str(kb_id), name=str(data.get("kb_name") or name), raw=data)

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = [("files", (file_name, content, content_type or "application/octet-stream"))]
        data = await self._api(
            "POST",
            "/upload_files",
            data={"user_id": self.user_id, "kb_id": kb_id, "mode": "soft"},
            files=files,
            timeout=self.upload_timeout,
        )
        item = data[0] if isinstance(data, list) and data else (data or {})
        doc_id = item.get("file_id") or item.get("doc_id") or item.get("file_name") or file_name
        return RemoteDocument(
            id=str(doc_id),
            name=str(item.get("file_name") or file_name),
            status="pending",
            raw=item if isinstance(item, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        data = await self._api(
            "POST",
            "/list_files",
            json_body={"user_id": self.user_id, "kb_id": kb_id},
        )
        items = data if isinstance(data, list) else (data or {}).get("files") or []
        return [self._map_document(item) for item in items if isinstance(item, dict)]

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(item.get("status") or "").lower()
        if raw_status in ("success", "done", "completed", "green", "ready"):
            status = "done"
        elif raw_status in ("failed", "error", "red"):
            status = "failed"
        elif raw_status in ("pending", "processing", "parsing", "running", "yellow"):
            status = "running"
        else:
            status = "pending"
        error = None
        if status == "failed":
            error = str(item.get("error") or item.get("status") or "解析失败")
        return RemoteDocument(
            id=str(item.get("file_id") or item.get("doc_id") or item.get("file_name")),
            name=str(item.get("file_name") or item.get("file_id")),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

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
        kb_id = chat_id or self.config.get("kb_id")
        if not kb_id:
            raise ConnectorError("QAnything 问答需要 kb_id（chat_id）")
        payload = await self._api(
            "POST",
            "/chat",
            json_body={
                "user_id": self.user_id,
                "kb_ids": [kb_id],
                "question": question,
                "history": [],
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if isinstance(payload, dict):
            for source in payload.get("source_documents") or []:
                if not isinstance(source, dict):
                    continue
                text = source.get("content") or source.get("text")
                if text:
                    contexts.append(str(text))
                ref_id = source.get("file_id") or source.get("doc_id") or source.get("file_name")
                if ref_id:
                    retrieval_ids.append(str(ref_id))
        return {
            "answer": (payload.get("response") or payload.get("answer") or "") if isinstance(payload, dict) else "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
