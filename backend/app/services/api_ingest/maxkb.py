# MaxKB 全链路连接器
#
# 参考文档（2026-10 快照）：
# - 官方文档：https://docs.fit2cloud.com/maxkb/
# - 知识库 API：/api/dataset 系列；应用 API：/api/application/{app_id}/chat/completions
#   GET  /api/dataset                         列知识库
#   POST /api/dataset                         {name, desc, type}
#   POST /api/dataset/{dataset_id}/document   multipart file
#   GET  /api/dataset/{dataset_id}/document   文档列表/状态
#   GET  /api/dataset/{dataset_id}/document/{document_id}/paragraph  分段列表
#   POST /api/application/{app_id}/chat/completions                  OpenAI 兼容问答
#
# 认证：知识库与应用各有一把 API Key，都是 Authorization: Bearer <key>。
# 版本差异：MaxKB 1.x/2.x 的字段命名略有不同（如 data 直接是列表或 {records,total}），
# 这里对两种形状都做兼容；返回 code 非 2xx/0 时按 ConnectorError 上抛。
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


class MaxKBConnector(BaseApiIngestConnector):
    system_type = "maxkb"
    display_name = "MaxKB"
    api_doc_url = "https://docs.fit2cloud.com/maxkb/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,          # 上传后自动排队解析
        list_chunks=True,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="知识库 Key 与应用 Key 分开填写；应用问答需要 application_id。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        base = self.base_url
        self.api_root = base if base.endswith("/api") else f"{base}/api"
        self.dataset_key = (
            self.config.get("dataset_api_key")
            or self.config.get("knowledge_api_key")
            or self.api_key
        )
        self.app_key = (
            self.config.get("chat_api_key")
            or self.config.get("app_api_key")
            or self.api_key
        )

    def _headers(self, key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _unwrap(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            code = payload.get("code")
            if code not in (None, 0, 200):
                message = payload.get("message") or payload.get("msg") or payload
                raise ConnectorError(f"MaxKB 返回 code={code}：{message}")
            if "data" in payload:
                return payload.get("data")
        return payload

    async def _dataset(
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
            headers=self._headers(self.dataset_key),
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=timeout,
            auth=False,
        )
        return self._unwrap(payload)

    async def _app(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        payload = await self.request_json(
            method,
            f"{self.api_root}{path}",
            headers=self._headers(self.app_key),
            json_body=json_body,
            timeout=timeout,
            auth=False,
        )
        return self._unwrap(payload)

    @staticmethod
    def _items(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("records", "items", "list", "documents", "paragraphs"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        data = await self._dataset("GET", "/dataset", params={"page": 1, "page_size": 100})
        return [
            KnowledgeBase(
                id=str(item.get("id")),
                name=str(item.get("name") or item.get("id")),
                raw=item,
            )
            for item in self._items(data)
            if item.get("id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        data = await self._dataset(
            "POST",
            "/dataset",
            json_body={
                "name": name,
                "desc": kwargs.get("description") or self.config.get("kb_description") or "",
                "type": "1",
            },
        )
        kb_id = dig(data, "id")
        if not kb_id:
            raise ConnectorError(f"MaxKB 建库未返回 ID：{data}")
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
        data = await self._dataset(
            "POST",
            f"/dataset/{kb_id}/document",
            files=files,
            timeout=self.upload_timeout,
        )
        document = data[0] if isinstance(data, list) and data else data
        doc_id = dig(document, "id") or dig(document, "document_id")
        if not doc_id:
            # 有些版本上传只返回成功，不给 ID；按文件名回查一次
            documents = await self.list_documents(kb_id)
            match = next((doc for doc in documents if doc.name == file_name), None)
            if not match:
                raise ConnectorError(f"MaxKB 上传 {file_name} 后未能定位文档：{data}")
            return match
        return RemoteDocument(
            id=str(doc_id),
            name=str(dig(document, "name", file_name)),
            status="pending",
            raw=document if isinstance(document, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        documents: List[RemoteDocument] = []
        page = 1
        while True:
            data = await self._dataset(
                "GET",
                f"/dataset/{kb_id}/document",
                params={"page": page, "page_size": 100},
            )
            items = self._items(data)
            documents.extend(self._map_document(item) for item in items)
            if len(items) < 100:
                break
            page += 1
        return documents

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(item.get("status") or "").upper()
        if raw_status in ("SUCCESS", "COMPLETED", "DONE", "FINISHED"):
            status = "done"
        elif raw_status in ("FAIL", "FAILED", "ERROR"):
            status = "failed"
        elif raw_status in ("PENDING", "STARTED", "RUNNING", "PARSING", "QUEUED"):
            status = "running"
        else:
            status = "pending"

        progress = item.get("progress")
        try:
            progress_value = float(progress) if progress is not None else (1.0 if status == "done" else 0.0)
        except (TypeError, ValueError):
            progress_value = 1.0 if status == "done" else 0.0
        if progress_value > 1.0:
            progress_value /= 100.0

        error = None
        if status == "failed":
            error = str(item.get("error") or "") or "解析失败"

        return RemoteDocument(
            id=str(item.get("id")),
            name=str(item.get("name") or item.get("file_name") or item.get("id")),
            status=status,
            progress=progress_value,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        chunks: List[RemoteChunk] = []
        page = 1
        while True:
            data = await self._dataset(
                "GET",
                f"/dataset/{kb_id}/document/{document_id}/paragraph",
                params={"page": page, "page_size": 100},
            )
            items = self._items(data)
            for position, item in enumerate(items):
                content = item.get("content") or item.get("text") or ""
                if not content:
                    continue
                chunks.append(
                    RemoteChunk(
                        id=str(item.get("id") or f"{document_id}-{len(chunks)}"),
                        content=content,
                        document_id=document_id,
                        index=int(item.get("position") or len(chunks)),
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
        app_id = (
            chat_id
            or self.config.get("application_id")
            or self.config.get("app_id")
        )
        if not app_id:
            raise ConnectorError("MaxKB 问答需要 application_id（应用 ID）")
        payload = await self._app(
            "POST",
            f"/application/{app_id}/chat/completions",
            json_body={
                "messages": [{"role": "user", "content": question}],
                "stream": False,
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        references = []
        if isinstance(payload, dict):
            references = (
                payload.get("reference")
                or payload.get("references")
                or payload.get("sources")
                or []
            )
        for reference in references:
            if isinstance(reference, str):
                contexts.append(reference)
                continue
            if not isinstance(reference, dict):
                continue
            text = reference.get("content") or reference.get("text")
            if text:
                contexts.append(str(text))
            ref_id = reference.get("id") or reference.get("document_id") or reference.get("paragraph_id")
            if ref_id:
                retrieval_ids.append(str(ref_id))

        return {
            "answer": dig(payload, "choices.0.message.content", "") or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
