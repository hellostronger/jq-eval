# Dify 知识库 + 应用 API 全链路连接器
#
# 参考文档：
# - 知识库 API（dataset key，Bearer dataset-xxx）：
#   https://docs.dify.ai/guides/knowledge-base/knowledge-base-api
# - 应用 API（app key，Bearer app-xxx）：
#   https://docs.dify.ai/guides/application-publishing/developing-with-apis
#
# 注意 Dify 有**两把 key**：
# - api_key / chat_api_key：应用（chat-messages）用
# - dataset_api_key：知识库维护用
# 同一个 key 通常不能同时调两类接口；未单独配置 dataset_api_key 时回退 api_key，
# 并在报 401 时给出可读提示。
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


class DifyConnector(BaseApiIngestConnector):
    """Dify：知识库维护 + 应用问答"""

    system_type = "dify"
    display_name = "Dify"
    api_doc_url = "https://docs.dify.ai/guides/knowledge-base/knowledge-base-api"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,  # 上传即自动排队解析，无需显式触发
        list_chunks=True,
        create_chat=False,  # 应用需在 Dify 控制台创建，API 只能调用
        ask=True,
        docs_url=api_doc_url,
        notes="知识库接口需 dataset key，问答接口需 app key；可在连接配置里分别填写。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        base = self.base_url
        self.api_root = base if base.endswith("/v1") else f"{base}/v1"
        self.dataset_api_key = (
            self.config.get("dataset_api_key")
            or self.config.get("knowledge_api_key")
            or self.api_key
        )
        self.chat_api_key = (
            self.config.get("chat_api_key")
            or self.config.get("app_api_key")
            or self.api_key
        )

    def _dataset_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.dataset_api_key}"} if self.dataset_api_key else {}

    def _chat_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.chat_api_key}"} if self.chat_api_key else {}

    async def _dataset_request(
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
        try:
            return await self.request_json(
                method,
                f"{self.api_root}{path}",
                headers=self._dataset_headers(),
                params=params,
                json_body=json_body,
                data=data,
                files=files,
                timeout=timeout,
                auth=False,
            )
        except ConnectorError as exc:
            if exc.status_code in (401, 403):
                raise ConnectorError(
                    "Dify 知识库接口鉴权失败：请确认填写的是知识库 API Key（dataset-xxx），"
                    "而不是应用 API Key（app-xxx）。",
                    status_code=exc.status_code,
                    response_body=exc.response_body,
                ) from exc
            raise

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        knowledge_bases: List[KnowledgeBase] = []
        page = 1
        while True:
            data = await self._dataset_request(
                "GET", "/datasets", params={"page": page, "limit": 100}
            )
            items = data.get("data", []) if isinstance(data, dict) else []
            knowledge_bases.extend(
                KnowledgeBase(
                    id=str(item.get("id")),
                    name=item.get("name") or str(item.get("id")),
                    raw=item,
                )
                for item in items
                if item.get("id")
            )
            if not data.get("has_more"):
                break
            page += 1
        return knowledge_bases

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        technique = (
            kwargs.get("indexing_technique")
            or self.config.get("indexing_technique")
            or "high_quality"
        )
        body: Dict[str, Any] = {
            "name": name,
            "description": kwargs.get("description") or self.config.get("kb_description") or "",
            "indexing_technique": technique,
            "permission": "only_me",
        }

        if technique == "high_quality":
            provider = kwargs.get("embedding_model_provider") or self.config.get(
                "embedding_model_provider"
            )
            model = kwargs.get("embedding_model") or self.config.get("embedding_model")
            if not provider or not model:
                raise ConnectorError(
                    "Dify 高质量索引建库需要 embedding 模型：请在连接配置里填写 "
                    "embedding_model_provider 与 embedding_model（如 openai / text-embedding-3-small），"
                    "或直接在 Dify 控制台建库后，在 jq-eval 里选择已有知识库。"
                )
            body["embedding_model_provider"] = provider
            body["embedding_model"] = model

        retrieval_model = kwargs.get("retrieval_model") or self.config.get("retrieval_model")
        if retrieval_model:
            body["retrieval_model"] = retrieval_model

        data = await self._dataset_request("POST", "/datasets", json_body=body)
        kb_id = dig(data, "id")
        if not kb_id:
            raise ConnectorError(f"Dify 建库未返回 ID：{data}")
        return KnowledgeBase(id=str(kb_id), name=dig(data, "name", name), raw=data or {})

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        import json

        data_field = {
            "indexing_technique": self.config.get("indexing_technique") or "high_quality",
            "process_rule": self.config.get("process_rule") or {"mode": "automatic"},
        }
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        data = await self._dataset_request(
            "POST",
            f"/datasets/{kb_id}/document/create-by-file",
            data={"data": json.dumps(data_field, ensure_ascii=False)},
            files=files,
            timeout=self.upload_timeout,
        )
        document = data.get("document", {}) if isinstance(data, dict) else {}
        doc_id = dig(document, "id")
        if not doc_id:
            raise ConnectorError(f"Dify 上传 {file_name} 未返回文档 ID：{data}")
        return RemoteDocument(
            id=str(doc_id),
            name=dig(document, "name", file_name),
            status="pending",
            raw={"document": document, "batch": data.get("batch")},
        )

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        documents: List[RemoteDocument] = []
        page = 1
        while True:
            data = await self._dataset_request(
                "GET",
                f"/datasets/{kb_id}/documents",
                params={"page": page, "limit": 100},
            )
            items = data.get("data", []) if isinstance(data, dict) else []
            documents.extend(self._map_document(item) for item in items)
            if not data.get("has_more"):
                break
            page += 1
        return documents

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(item.get("indexing_status") or "").lower()
        if raw_status == "completed":
            status = "done"
        elif raw_status == "error":
            status = "failed"
        elif raw_status in ("waiting", "parsing", "cleaning", "splitting", "indexing", "paused"):
            status = "running"
        else:
            status = "pending"

        error = None
        if status == "failed":
            error = item.get("error") or item.get("indexing_status") or "解析失败"

        return RemoteDocument(
            id=str(item.get("id")),
            name=item.get("name") or str(item.get("id")),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        chunks: List[RemoteChunk] = []
        page = 1
        while True:
            data = await self._dataset_request(
                "GET",
                f"/datasets/{kb_id}/documents/{document_id}/segments",
                params={"page": page, "limit": 100},
            )
            items = data.get("data", []) if isinstance(data, dict) else []
            for position, item in enumerate(items):
                chunks.append(
                    RemoteChunk(
                        id=str(item.get("id") or f"{document_id}-{len(chunks)}"),
                        content=item.get("content") or "",
                        document_id=str(item.get("document_id") or document_id),
                        index=int(item.get("position") or len(chunks)),
                        raw=item,
                    )
                )
            if len(items) < 100:
                break
            page += 1
        return [chunk for chunk in chunks if chunk.content]

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "inputs": self.config.get("inputs") or {},
            "query": question,
            "user": self.config.get("user_id") or "jq-eval",
            "response_mode": "blocking",
        }
        if conversation_id:
            body["conversation_id"] = conversation_id

        data = await self.request_json(
            "POST",
            f"{self.api_root}/chat-messages",
            headers=self._chat_headers(),
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
            auth=False,
        )

        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for resource in dig(data, "metadata.retriever_resources", []) or []:
            if resource.get("content"):
                contexts.append(resource["content"])
            if resource.get("segment_id") or resource.get("dataset_id"):
                retrieval_ids.append(str(resource.get("segment_id") or resource.get("dataset_id")))

        return {
            "answer": data.get("answer", ""),
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": data,
        }
