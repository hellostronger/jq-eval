# AnythingLLM 全链路连接器
#
# 参考文档 / 源码（2026-10 快照）：
# - API 文档：https://docs.anythingllm.com/
# - workspace 路由：server/endpoints/api/workspace/index.js
#   GET  /api/v1/workspaces                       列 workspace（= 知识库）
#   POST /api/v1/workspace/new                    {name}
#   GET  /api/v1/workspace/:slug                  含 documents
#   POST /api/v1/workspace/:slug/chat             {message, mode:"query", sessionId}
#   POST /api/v1/workspace/:slug/vector-search    {query, topN}
# - document 路由：server/endpoints/api/document/index.js
#   POST /api/v1/document/upload                  multipart file + addToWorkspaces
#
# 认证：Authorization: Bearer <API Key>（Settings → API Keys 生成）。
# 注意：AnythingLLM 的“文档”先进入全局文档库，再用 addToWorkspaces 嵌入 workspace；
# 上传接口的 addToWorkspaces 字段会同步完成嵌入，因此不需要单独的解析步骤。
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


class AnythingLLMConnector(BaseApiIngestConnector):
    system_type = "anythingllm"
    display_name = "AnythingLLM"
    api_doc_url = "https://docs.anythingllm.com/"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,          # 上传时即完成解析与嵌入
        list_chunks=False,              # 只有 vector-search TopN，不能枚举全部分片
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="workspace 即知识库；上传可带 addToWorkspaces 直接入库。无分片枚举接口。",
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

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        payload = await self._api("GET", "/v1/workspaces")
        items = dig(payload, "workspaces", []) or []
        return [
            KnowledgeBase(
                id=str(item.get("slug") or item.get("id")),
                name=str(item.get("name") or item.get("slug")),
                raw=item,
            )
            for item in items
            if item.get("slug") or item.get("id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        payload = await self._api("POST", "/v1/workspace/new", json_body={"name": name})
        workspace = dig(payload, "workspace", {}) or {}
        slug = workspace.get("slug") or workspace.get("id")
        if not slug:
            raise ConnectorError(f"AnythingLLM 建 workspace 未返回 slug：{payload}")
        return KnowledgeBase(
            id=str(slug),
            name=str(workspace.get("name") or name),
            raw=workspace,
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
        payload = await self._api(
            "POST",
            "/v1/document/upload",
            data={"addToWorkspaces": kb_id},
            files=files,
            timeout=self.upload_timeout,
        )
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ConnectorError(f"AnythingLLM 上传 {file_name} 失败：{payload.get('error')}")
        documents = dig(payload, "documents", []) or []
        document = documents[0] if documents else {}
        location = document.get("location") or document.get("name")
        if not location:
            raise ConnectorError(f"AnythingLLM 上传 {file_name} 未返回文档位置：{payload}")
        return RemoteDocument(
            id=str(location),
            name=str(document.get("title") or file_name),
            status="done",  # addToWorkspaces 同步嵌入；失败会走 success=false
            progress=1.0,
            raw=document,
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        # 上传即解析/嵌入，没有单独的解析接口
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        payload = await self._api("GET", f"/v1/workspace/{kb_id}")
        workspace = dig(payload, "workspace", {}) or {}
        documents = workspace.get("documents") or []
        result: List[RemoteDocument] = []
        for item in documents:
            # docpath 是嵌入时使用的相对路径，和上传返回的 location 对得上
            doc_id = item.get("docpath") or item.get("location") or item.get("id")
            if not doc_id:
                continue
            result.append(
                RemoteDocument(
                    id=str(doc_id),
                    name=str(item.get("title") or item.get("filename") or doc_id),
                    status="done",
                    progress=1.0,
                    raw=item,
                )
            )
        return result

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        # AnythingLLM 没有“列出全部分片”的 API；vector-search 只给查询相关的 TopN，
        # 用它当全量分片会把评测的 target 变成“当前问题的召回”，产生循环论证。
        return []

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        workspace = (
            chat_id
            or self.config.get("chat_id")
            or self.config.get("kb_id")
            or self.config.get("workspace_slug")
        )
        if not workspace:
            raise ConnectorError("AnythingLLM 问答需要 workspace slug（chat_id）")
        payload = await self._api(
            "POST",
            f"/v1/workspace/{workspace}/chat",
            json_body={
                "message": question,
                "mode": self.config.get("chat_mode") or "query",
                "sessionId": conversation_id or self.config.get("session_id") or "jq-eval",
                "reset": False,
            },
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        if isinstance(payload, dict) and payload.get("error"):
            raise ConnectorError(f"AnythingLLM 问答失败：{payload['error']}")

        contexts: List[str] = []
        retrieval_ids: List[str] = []
        sources = payload.get("sources") if isinstance(payload, dict) else []
        for source in sources or []:
            chunk = source.get("chunk") or source.get("text") or source.get("content")
            if chunk:
                contexts.append(str(chunk))
            if source.get("id") or source.get("title"):
                retrieval_ids.append(str(source.get("id") or source.get("title")))

        return {
            "answer": (payload.get("textResponse") if isinstance(payload, dict) else "") or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": payload if isinstance(payload, dict) else {},
        }
