# Open WebUI 全链路连接器
#
# 参考文档 / 源码（2026-10 快照）：
# - API 文档：https://docs.openwebui.com/
# - 路由源码：backend/open_webui/routers/knowledge.py、files.py
#   GET  /api/v1/knowledge/                 列知识库
#   POST /api/v1/knowledge/create           {name, description}
#   GET  /api/v1/knowledge/{id}             含 files
#   POST /api/v1/knowledge/{id}/file/add    {file_id}
#   POST /api/v1/files/                     multipart file
#   POST /api/chat/completions              OpenAI 兼容；files=[{type:"collection", id}]
#
# 认证：Authorization: Bearer <API Key>（Settings → Account → API Keys）。
# 说明：Open WebUI 的“知识库”是 knowledge collection；文件先上传到 /files，
# 再加入 knowledge 时同步完成抽取与向量化，所以没有单独的解析接口。
# 分片只在检索时以 TopK 形式出现，无法枚举全量，故 list_chunks=False。
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


class OpenWebUIConnector(BaseApiIngestConnector):
    system_type = "open_webui"
    display_name = "Open WebUI"
    api_doc_url = "https://docs.openwebui.com/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="knowledge collection 即知识库；上传后加入知识库即完成向量化。无分片枚举接口。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        base = self.base_url
        self.api_root = base if base.endswith("/api") else f"{base}/api"

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

    def _knowledge_items(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        items = payload.get("items") or payload.get("data") or []
        return items if isinstance(items, list) else []

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        payload = await self._api("GET", "/v1/knowledge/")
        return [
            KnowledgeBase(
                id=str(item.get("id")),
                name=str(item.get("name") or item.get("id")),
                raw=item,
            )
            for item in self._knowledge_items(payload)
            if item.get("id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        payload = await self._api(
            "POST",
            "/v1/knowledge/create",
            json_body={
                "name": name,
                "description": kwargs.get("description")
                or self.config.get("kb_description")
                or "",
            },
        )
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        kb_id = dig(data, "id")
        if not kb_id:
            raise ConnectorError(f"Open WebUI 建知识库未返回 ID：{payload}")
        return KnowledgeBase(id=str(kb_id), name=str(dig(data, "name", name)), raw=data or {})

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        uploaded = await self._api(
            "POST",
            "/v1/files/",
            data={"process": "true"},
            files=files,
            timeout=self.upload_timeout,
        )
        file_data = uploaded.get("data") if isinstance(uploaded, dict) and "data" in uploaded else uploaded
        file_id = dig(file_data, "id")
        if not file_id:
            raise ConnectorError(f"Open WebUI 上传 {file_name} 未返回文件 ID：{uploaded}")

        # 加入知识库时服务端会 process_file，把内容写进 collection
        await self._api(
            "POST",
            f"/v1/knowledge/{kb_id}/file/add",
            json_body={"file_id": str(file_id)},
            timeout=self.upload_timeout,
        )
        return RemoteDocument(
            id=str(file_id),
            name=str(dig(file_data, "filename", file_name)),
            status="done",
            progress=1.0,
            raw=file_data if isinstance(file_data, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api("GET", f"/v1/knowledge/{kb_id}")
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        files = dig(data, "files", []) or []
        return [
            RemoteDocument(
                id=str(item.get("id")),
                name=str(item.get("filename") or item.get("name") or item.get("id")),
                status="done",
                progress=1.0,
                raw=item,
            )
            for item in files
            if item.get("id")
        ]

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        return []

    # ---------------------------------------------------------------- 问答
    def _collect_sources(self, payload: Any) -> tuple:
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if not isinstance(payload, dict):
            return contexts, retrieval_ids
        for key in ("sources", "citations"):
            for source in payload.get(key) or []:
                if isinstance(source, str):
                    contexts.append(source)
                    continue
                if not isinstance(source, dict):
                    continue
                text = (
                    source.get("content")
                    or source.get("text")
                    or source.get("source")
                    or dig(source, "document.content")
                )
                if text:
                    contexts.append(str(text))
                source_id = source.get("id") or source.get("document_id") or source.get("title")
                if source_id:
                    retrieval_ids.append(str(source_id))
        return contexts, retrieval_ids

    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        model = self.config.get("model") or self.config.get("chat_model")
        if not model:
            raise ConnectorError(
                "Open WebUI 问答需要指定模型：请在连接配置里填写 model（与 Open WebUI 模型列表里的 ID 一致）。"
            )
        body: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": question}],
            "stream": False,
        }
        collection = chat_id or self.config.get("chat_id") or self.config.get("kb_id")
        if collection:
            body["files"] = [{"type": "collection", "id": collection}]
        payload = await self._api(
            "POST",
            "/chat/completions",
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts, retrieval_ids = self._collect_sources(payload)
        return {
            "answer": dig(payload, "choices.0.message.content", "") or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
