# FastGPT API 全链路连接器
#
# 参考文档：
# - Dataset API: https://doc.fastgpt.io/en/openapi/dataset
# - Chat API:    https://doc.fastgpt.io/en/openapi/chat
#
# 路径以官方文档为准（base 为 http://host:3000/api）：
#   POST /core/dataset/create
#   POST /core/dataset/list
#   POST /core/dataset/collection/create/localFile   （multipart: file + data JSON）
#   POST /core/dataset/collection/listV2
#   GET  /core/dataset/collection/detail?id=
#   POST /core/dataset/data/v2/list
#   POST /v1/chat/completions
#
# 两把 key：
# - 知识库维护使用「知识库 API Key」（dataset_api_key）
# - 应用问答使用「应用 API Key」（api_key）
# 自部署版本常把两者配成同一把，故未单独配置时回退。
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


class FastGPTConnector(BaseApiIngestConnector):
    """FastGPT：知识库维护 + 应用问答"""

    system_type = "fastgpt"
    display_name = "FastGPT"
    api_doc_url = "https://doc.fastgpt.io/en/openapi/dataset"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,  # 上传后自动训练
        list_chunks=True,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="知识库接口使用知识库 API Key；问答使用应用 API Key。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        base = self.base_url
        # 用户可能填 http://host:3000、http://host:3000/api 或 .../api/v1
        if base.endswith("/api/v1"):
            base = base[: -len("/v1")]
        if not base.endswith("/api"):
            base = f"{base}/api"
        self.api_root = base
        self.dataset_api_key = (
            self.config.get("dataset_api_key")
            or self.config.get("knowledge_api_key")
            or self.api_key
        )

    def _dataset_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.dataset_api_key}"} if self.dataset_api_key else {}

    async def _core_request(
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
        """调用 /core 管理接口并解包 FastGPT 的 {code, data} 信封"""
        try:
            payload = await self.request_json(
                method,
                f"{self.api_root}/core{path}",
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
                    "FastGPT 知识库接口鉴权失败：请确认填写的是知识库 API Key。",
                    status_code=exc.status_code,
                    response_body=exc.response_body,
                ) from exc
            raise

        if isinstance(payload, dict) and payload.get("code") not in (None, 200):
            raise ConnectorError(
                f"FastGPT API 返回错误 code={payload.get('code')}："
                f"{payload.get('message') or payload.get('statusText') or payload}"
            )
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        data = await self._core_request(
            "POST", "/dataset/list", params={"parentId": ""}, json_body={"parentId": None}
        )
        items = data if isinstance(data, list) else (dig(data, "list", []) or [])
        return [
            KnowledgeBase(
                id=str(item.get("_id") or item.get("id")),
                name=item.get("name") or str(item.get("_id") or item.get("id")),
                raw=item,
            )
            for item in items
            if item.get("_id") or item.get("id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        body: Dict[str, Any] = {
            "parentId": kwargs.get("parentId"),
            "type": "dataset",
            "name": name,
            "intro": kwargs.get("description") or self.config.get("kb_description") or "",
        }
        vector_model = kwargs.get("vector_model") or self.config.get("vector_model")
        if vector_model:
            body["vectorModel"] = vector_model
        agent_model = kwargs.get("agent_model") or self.config.get("agent_model")
        if agent_model:
            body["agentModel"] = agent_model

        data = await self._core_request("POST", "/dataset/create", json_body=body)
        kb_id = data if isinstance(data, str) else dig(data, "id") or dig(data, "_id")
        if not kb_id:
            # 建库接口在部分版本只返回 success
            kbs = await self.list_knowledge_bases()
            matched = next((kb for kb in kbs if kb.name == name), None)
            if not matched:
                raise ConnectorError(f"FastGPT 建库未返回 ID：{data}")
            return matched
        return KnowledgeBase(id=str(kb_id), name=name, raw={"id": str(kb_id)})

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        import json

        data_field: Dict[str, Any] = {
            "datasetId": kb_id,
            "parentId": None,
            "trainingType": self.config.get("training_type") or "chunk",
        }
        for key in ("chunkSize", "chunkSplitter", "qaPrompt", "autoIndexes"):
            value = self.config.get(key)
            if value is not None:
                data_field[key] = value

        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        data = await self._core_request(
            "POST",
            "/dataset/collection/create/localFile",
            data={"data": json.dumps(data_field, ensure_ascii=False)},
            files=files,
            timeout=self.upload_timeout,
        )
        collection_id = dig(data, "collectionId") or dig(data, "_id") or dig(data, "id")
        if not collection_id:
            raise ConnectorError(f"FastGPT 上传 {file_name} 未返回 collectionId：{data}")
        return RemoteDocument(
            id=str(collection_id),
            name=file_name,
            status="pending",
            raw=data or {},
        )

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        documents: List[RemoteDocument] = []
        offset = 0
        page_size = 100
        while True:
            data = await self._core_request(
                "POST",
                "/dataset/collection/listV2",
                json_body={
                    "datasetId": kb_id,
                    "parentId": None,
                    "offset": offset,
                    "pageSize": page_size,
                    "searchText": "",
                },
            )
            items = dig(data, "list", []) or []
            documents.extend(self._map_collection(item) for item in items)
            total = int(dig(data, "total", 0) or 0)
            offset += len(items)
            if len(items) < page_size or offset >= total:
                break
        return documents

    def _map_collection(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(
            item.get("trainingStatus") or item.get("status") or ""
        ).lower()
        data_amount = int(item.get("dataAmount") or 0)
        training_amount = item.get("trainingAmount")

        if raw_status in ("complete", "completed", "success", "done"):
            status = "done"
        elif raw_status in ("error", "failed", "fail"):
            status = "failed"
        elif training_amount is not None and int(training_amount or 0) > 0:
            status = "done" if data_amount >= int(training_amount) else "running"
        elif data_amount > 0:
            # 没有显式状态时，已产出分片视为训练完成
            status = "done"
        else:
            status = "running"

        error = None
        if status == "failed":
            error = item.get("error") or item.get("trainingError") or raw_status or "训练失败"

        return RemoteDocument(
            id=str(item.get("_id") or item.get("id")),
            name=item.get("name") or str(item.get("_id") or item.get("id")),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        chunks: List[RemoteChunk] = []
        offset = 0
        page_size = 100
        while True:
            data = await self._core_request(
                "POST",
                "/dataset/data/v2/list",
                json_body={
                    "collectionId": document_id,
                    "offset": offset,
                    "pageSize": page_size,
                    "searchText": "",
                },
            )
            items = dig(data, "list", []) or []
            for position, item in enumerate(items):
                content = (
                    item.get("q")
                    or item.get("content")
                    or item.get("text")
                    or ""
                )
                chunks.append(
                    RemoteChunk(
                        id=str(item.get("_id") or item.get("id") or f"{document_id}-{len(chunks)}"),
                        content=content,
                        document_id=document_id,
                        index=int(item.get("index") or len(chunks)),
                        raw=item,
                    )
                )
            total = int(dig(data, "total", 0) or 0)
            offset += len(items)
            if len(items) < page_size or offset >= total:
                break
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
            "chatId": conversation_id or chat_id or self.config.get("chat_id") or "",
            "stream": False,
            "detail": True,
            "messages": [{"role": "user", "content": question}],
        }
        # appId 取自应用 URL 的查询参数，不是 API Key；部分部署不校验
        if self.config.get("app_id"):
            body["appId"] = self.config["app_id"]
        data = await self.request_json(
            "POST",
            f"{self.api_root}/v1/chat/completions",
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        choices = data.get("choices", []) if isinstance(data, dict) else []
        answer = ""
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        if choices:
            answer = dig(choices[0], "message.content", "") or ""
            # 新版引用在 responseData[].quoteList[]；旧版在 annotations.references[]
            quotes = dig(choices[0], "responseData.0.quoteList", []) or []
            for ref in quotes:
                content = ref.get("q") or ref.get("content") or ""
                if content:
                    contexts.append(content)
                if ref.get("id"):
                    retrieval_ids.append(str(ref["id"]))
            for ref in dig(choices[0], "annotations.references", []) or []:
                if ref.get("content"):
                    contexts.append(ref["content"])
                if ref.get("id"):
                    retrieval_ids.append(str(ref["id"]))
        return {
            "answer": answer,
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": data if isinstance(data, dict) else {},
        }
