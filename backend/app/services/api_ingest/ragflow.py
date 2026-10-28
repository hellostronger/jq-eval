# RAGFlow（InfiniFlow）API 全链路连接器
#
# 参考文档：
# - v1.0（Go 重写后的 HTTP API，字段以源码为准）：
#   https://github.com/infiniflow/ragflow/tree/v1.0.0-rc2/internal/handler
#   - 建库 POST /api/v1/datasets
#     allowed fields: name / embedding_model / parser_config / language /
#     permission / parser_id / pipeline_id / parse_type
#     **parse_type 是整数**：1=内置解析器，2=数据流；不接受 description。
#   - 触发解析 POST /api/v1/documents/ingest
#     body {"doc_ids": [...], "run": "1"}；run 是 TaskStatus 枚举字符串
#     （1=Running，3=Cancel）。传 "RUNNING" 会返回 success 但什么都不做。
#   - 文档状态字段为 ingestion_status：UNSTART/CREATED/SCHEDULED/RUNNING/
#     STOPPING/COMPLETED/FAILED/STOPPED
#   - 问答 POST /api/v1/chat/completions，chat_id 放在 body
#     （/chats/{id}/completions 已移除）；回答 data.answer，召回 data.reference.chunks
# - 0.x（Python API）：
#   https://ragflow.io/docs/dev/http_api_reference
#   建库用 chunk_method；触发解析 POST /datasets/{id}/chunks；
#   文档状态字段为 run（UNSTART/RUNNING/DONE/FAIL/CANCEL）；
#   问答 POST /chats/{id}/completions。
#
# 因此这里对「建库 / 触发解析 / 问答 / 状态映射」做了双版本兼容：
# 先按 v1.0 调，遇到 404 或字段校验错误再回退 0.x 形状。
# 以上均已在本地 v1.0.0-rc2 实机跑通，问答用真实 embedding + LLM 验证。
from typing import Any, Dict, List, Optional

from app.core.exceptions import format_error

from .base import (
    BaseApiIngestConnector,
    ConnectorError,
    IngestCapabilities,
    KnowledgeBase,
    RemoteChunk,
    RemoteDocument,
    dig,
)


class RAGFlowConnector(BaseApiIngestConnector):
    """RAGFlow：建库、上传、解析、拉分片、问答全链路"""

    system_type = "ragflow"
    display_name = "RAGFlow"
    api_doc_url = "https://ragflow.io/docs/dev/http_api_reference"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=True,
        list_chunks=True,
        create_chat=True,
        ask=True,
        docs_url=api_doc_url,
        notes=(
            "已按 v1.0.0-rc2 Go API 源码核对并在本地实例跑通全链路；"
            "0.x 自动回退旧形状。建库需可用 embedding 模型（控制台配置或 OpenAI 兼容实例）。"
        ),
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        # 允许 endpoint 直接带 /api/v1 或 /v1，避免拼成 /api/v1/api/v1
        base = self.base_url
        if base.endswith("/api/v1"):
            self.api_root = base
        elif base.endswith("/v1"):
            self.api_root = base
        else:
            self.api_root = f"{base}/api/v1"

    # ------------------------------------------------------------------ 工具
    def _check_envelope(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        code = data.get("code")
        if code not in (None, 0):
            raise ConnectorError(
                f"RAGFlow API 返回错误 code={code}：{data.get('message') or data}"
            )
        return data.get("data", data)

    async def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        data = await self.request_json("GET", f"{self.api_root}{path}", params=params)
        return self._check_envelope(data)

    async def _post_json(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        data = await self.request_json(
            "POST", f"{self.api_root}{path}", json_body=body or {}
        )
        return self._check_envelope(data)

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        data = await self._get_json(
            "/datasets",
            params={"page": 1, "page_size": 1000, "orderby": "create_time", "desc": True},
        )
        # v1.0 直接返回 list；个别版本返回 {"datasets": [...]}
        items = data if isinstance(data, list) else (dig(data, "datasets", []) or [])
        return [
            KnowledgeBase(id=str(item.get("id")), name=item.get("name") or str(item.get("id")), raw=item)
            for item in items
            if item.get("id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        # v1.0 的 CreateDatasetRequest：parse_type 是整数（1=BuiltIn），
        # 且 allowed fields 不含 description，传了会被 "Extra inputs are not permitted" 拒绝。
        body: Dict[str, Any] = {
            "name": name,
            "parse_type": 1,
            "parser_id": kwargs.get("parser_id") or self.config.get("parser_id") or "naive",
            "permission": "me",
            "language": kwargs.get("language") or self.config.get("language") or "Chinese",
        }
        embedding_model = kwargs.get("embedding_model") or self.config.get("embedding_model")
        if embedding_model:
            body["embedding_model"] = embedding_model
        parser_config = kwargs.get("parser_config") or self.config.get("parser_config")
        if parser_config:
            body["parser_config"] = parser_config

        try:
            data = await self._post_json("/datasets", body)
        except ConnectorError as exc:
            # 0.x：parse_type 是字符串、用 chunk_method；description 反而是合法字段。
            if not self._looks_like_v1_field_error(exc):
                raise
            legacy_body: Dict[str, Any] = {
                "name": name,
                "description": kwargs.get("description") or self.config.get("kb_description") or "",
                "chunk_method": kwargs.get("parser_id") or self.config.get("parser_id") or "naive",
                "permission": "me",
                "language": kwargs.get("language") or self.config.get("language") or "Chinese",
            }
            if embedding_model:
                legacy_body["embedding_model"] = embedding_model
            if parser_config:
                legacy_body["parser_config"] = parser_config
            data = await self._post_json("/datasets", legacy_body)

        if isinstance(data, list) and data:
            data = data[0]
        kb_id = dig(data, "id")
        if not kb_id:
            # 少数版本建库只返回 success，不回 id：用名字回查
            kbs = await self.list_knowledge_bases()
            matched = next((kb for kb in kbs if kb.name == name), None)
            if not matched:
                raise ConnectorError("RAGFlow 建库成功但未返回知识库 ID，且按名称回查失败")
            return matched
        return KnowledgeBase(id=str(kb_id), name=dig(data, "name", name), raw=data or {})

    def _looks_like_v1_field_error(self, exc: ConnectorError) -> bool:
        """判断建库失败是否因为传了 0.x 字段（而不是鉴权/网络问题）"""
        text = format_error(exc).lower()
        return (
            "extra inputs are not permitted" in text
            or "cannot unmarshal" in text
            or "parse_type" in text
            or "chunk_method" in text
        )

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        files = {"file": (file_name, content, content_type or "application/octet-stream")}
        data = await self.request_json(
            "POST",
            f"{self.api_root}/datasets/{kb_id}/documents",
            files=files,
            timeout=self.upload_timeout,
        )
        data = self._check_envelope(data)
        if isinstance(data, list):
            data = data[0] if data else {}
        doc_id = dig(data, "id")
        if not doc_id:
            raise ConnectorError(f"RAGFlow 上传 {file_name} 未返回文档 ID：{data}")
        return RemoteDocument(
            id=str(doc_id),
            name=dig(data, "name", file_name),
            status="pending",
            raw=data or {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        if not document_ids:
            return
        # v1.0：POST /documents/ingest，body {doc_ids, run:"1"}
        # run 是实体枚举（TaskStatusRunning = "1"，Cancel = "3"），传 "RUNNING"
        # 不会报错，但会落进 cancel 分支，任务永远 pending——实机踩过。
        try:
            await self._post_json(
                "/documents/ingest",
                {"doc_ids": document_ids, "run": "1"},
            )
            return
        except ConnectorError as exc:
            # 0.x 没有该接口（404）；其余错误直接抛出，避免把鉴权失败当成版本差异
            if exc.status_code != 404:
                raise
        # 0.x：POST /datasets/{id}/chunks，body {document_ids}
        await self._post_json(f"/datasets/{kb_id}/chunks", {"document_ids": document_ids})

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        data = await self._get_json(
            f"/datasets/{kb_id}/documents",
            params={"page": 1, "page_size": 1000, "orderby": "create_time", "desc": True},
        )
        items = data.get("docs", []) if isinstance(data, dict) else (data or [])
        documents: List[RemoteDocument] = []
        for item in items:
            documents.append(self._map_document(item))
        return documents

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        # v1.0：ingestion_status（UNSTART/CREATED/SCHEDULED/RUNNING/STOPPING/
        # COMPLETED/FAILED/STOPPED）；0.x：run（UNSTART/RUNNING/DONE/FAIL/CANCEL）
        raw = str(item.get("ingestion_status") or item.get("run") or "").upper()
        if raw in ("DONE", "COMPLETED"):
            status = "done"
        elif raw in ("FAIL", "FAILED", "CANCEL", "STOPPED"):
            status = "failed"
        elif raw in ("CREATED", "SCHEDULED", "UNSTART", "PENDING", ""):
            status = "pending"
        elif raw in ("RUNNING", "STOPPING"):
            status = "running"
        else:
            status = "running"

        try:
            progress = float(item.get("progress") or 0)
        except (TypeError, ValueError):
            progress = 0.0
        # progress 可能是 0~1，也可能是 0~100
        if progress > 1.0:
            progress = progress / 100.0
        if status == "done":
            progress = 1.0

        error = None
        if status == "failed":
            error = item.get("progress_msg") or item.get("status") or item.get("ingestion_status") or "解析失败"
        latest = item.get("latest_ingestion_event") or {}
        if status == "failed" and isinstance(latest, dict) and latest.get("message"):
            error = latest["message"]

        return RemoteDocument(
            id=str(item.get("id")),
            name=item.get("name") or str(item.get("id")),
            status=status,
            progress=progress,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        chunks: List[RemoteChunk] = []
        page = 1
        page_size = 100
        while True:
            data = await self._get_json(
                f"/datasets/{kb_id}/documents/{document_id}/chunks",
                params={"page": page, "page_size": page_size},
            )
            items = data.get("chunks", []) if isinstance(data, dict) else (data or [])
            for index, item in enumerate(items):
                chunks.append(
                    RemoteChunk(
                        id=str(item.get("id") or f"{document_id}-{len(chunks)}"),
                        content=item.get("content") or item.get("content_with_weight") or "",
                        document_id=str(item.get("document_id") or document_id),
                        document_name=item.get("document_name") or "",
                        index=len(chunks),
                        raw=item,
                    )
                )
            total = dig(data, "total")
            if len(items) < page_size or (total is not None and len(chunks) >= int(total)):
                break
            page += 1
        return [chunk for chunk in chunks if chunk.content]

    # ------------------------------------------------------------ 会话/问答
    async def ensure_chat(self, name: str, kb_ids: List[str]) -> str:
        configured = str(self.config.get("chat_id") or "").strip()
        if configured:
            return configured

        data = await self._post_json(
            "/chats",
            {
                "name": name,
                "dataset_ids": kb_ids,
                # 未显式指定 llm 时使用租户默认模型
                "llm": self.config.get("chat_llm") or {},
            },
        )
        chat_id = dig(data, "id")
        if not chat_id:
            raise ConnectorError(f"RAGFlow 创建会话助手失败：{data}")
        return str(chat_id)

    async def create_session(self, chat_id: str, name: str = "jq-eval") -> str:
        data = await self._post_json(f"/chats/{chat_id}/sessions", {"name": name})
        session_id = dig(data, "id")
        if not session_id:
            raise ConnectorError(f"RAGFlow 创建会话失败：{data}")
        return str(session_id)

    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        chat_id = chat_id or str(self.config.get("chat_id") or "")
        if not chat_id:
            raise ConnectorError("RAGFlow 问答缺少 chat_id：请先创建会话助手或在连接配置中填写 chat_id")

        body: Dict[str, Any] = {"question": question, "stream": False}
        # 不传 session_id 时 RAGFlow 会新建会话，适合逐题独立评测；
        # 传了则沿用上下文（多轮场景）。
        if conversation_id:
            body["session_id"] = conversation_id

        # v1.0：POST /chat/completions，chat_id 在 body；0.x：POST /chats/{id}/completions
        llm_id = (self.config.get("chat_llm") or {}).get("model_name")
        try:
            data = await self._post_json(
                "/chat/completions",
                {**body, "chat_id": chat_id, **({"llm_id": llm_id} if llm_id else {})},
            )
        except ConnectorError as exc:
            if exc.status_code != 404:
                raise
            data = await self._post_json(f"/chats/{chat_id}/completions", body)
        answer = dig(data, "answer", "") or ""
        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for ref in dig(data, "reference.chunks", []) or []:
            content = ref.get("content") or ref.get("content_with_weight") or ""
            if content:
                contexts.append(content)
            if ref.get("id"):
                retrieval_ids.append(str(ref["id"]))
        return {
            "answer": answer,
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": data,
        }

    # -------------------------------------------------------------- 连通性
    async def check_connection(self) -> Dict[str, Any]:
        try:
            kbs = await self.list_knowledge_bases()
            return {"healthy": True, "knowledge_base_count": len(kbs)}
        except ConnectorError as exc:
            return {"healthy": False, "error": format_error(exc)}
