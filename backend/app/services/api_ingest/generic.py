# 通用 HTTP 接入连接器（大厂云平台 / 自研 RAG 网关）
#
# 为什么需要它：
# BAT 及多数商业平台的 RAG 接口没有统一标准——有的用 Bearer，有的用 AK/SK 签名；
# 响应字段、分页方式、解析状态枚举也各不相同。与其为每家写一个半成品连接器，
# 不如提供一套 profile（JSON 描述请求/响应路径），既能覆盖大厂预设，也允许用户
# 按自己的私有化系统补充。
#
# profile 结构示例（字段都可省略，省略即不支持对应能力）：
# {
#   "list_kb":     {"method":"GET","path":"/v1/kbs","items_path":"data",
#                   "id_path":"id","name_path":"name"},
#   "create_kb":   {"method":"POST","path":"/v1/kbs","body":{"name":"{{name}}"},
#                   "id_path":"data.id","name_path":"data.name"},
#   "upload":      {"method":"POST","path":"/v1/kbs/{{kb_id}}/docs","multipart":true,
#                   "file_field":"file","form_fields":{"dataset_id":"{{kb_id}}"},
#                   "data_field":{"name":"{{file_name}}"},
#                   "id_path":"data.id"},
#   "parse":       {"method":"POST","path":"/v1/kbs/{{kb_id}}/parse",
#                   "body":{"document_ids":"{{document_ids}}"}},
#   "list_docs":   {"method":"GET","path":"/v1/kbs/{{kb_id}}/docs","items_path":"data",
#                   "id_path":"id","name_path":"name","status_path":"status",
#                   "progress_path":"progress",
#                   "done_values":["completed","done"],"fail_values":["failed","error"]},
#   "list_chunks": {"method":"GET","path":"/v1/kbs/{{kb_id}}/docs/{{document_id}}/chunks",
#                   "items_path":"data","content_path":"content","id_path":"id",
#                   "page_param":"page","page_start":1,"page_size_param":"page_size",
#                   "page_size":100},
#   "ask":         {"method":"POST","path":"/v1/chat/completions",
#                   "body":{"model":"{{model}}","messages":[{"role":"user","content":"{{question}}"}]},
#                   "answer_path":"choices.0.message.content",
#                   "contexts_path":"choices.0.message.contexts",
#                   "retrieval_ids_path":"choices.0.message.retrieval_ids"}
# }
#
# 认证：auth_type = bearer | api_key | none；api_key_header 可指定头名。
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


def render(template: Any, context: Dict[str, Any]) -> Any:
    """递归替换 {{key}}；整串就是一个占位符时保留原类型（列表/数字不被转成字符串）"""
    if isinstance(template, str):
        stripped = template.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            key = stripped[2:-2].strip()
            if key in context:
                return context[key]
        for key, value in context.items():
            if isinstance(value, (str, int, float)):
                template = template.replace(f"{{{{{key}}}}}", str(value))
        return template
    if isinstance(template, dict):
        return {key: render(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [render(item, context) for item in template]
    return template


class GenericHttpConnector(BaseApiIngestConnector):
    """按 profile 驱动的通用 API 连接器"""

    system_type = "generic"
    display_name = "通用 HTTP"
    api_doc_url = ""
    capabilities = IngestCapabilities(
        list_knowledge_bases=False,
        create_knowledge_base=False,
        upload_documents=False,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        notes="能力由 ingest_profile 决定；未配置的步骤请在对方系统完成。",
    )

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        profile: Optional[Dict[str, Any]] = None,
        capabilities: Optional[IngestCapabilities] = None,
        **kwargs: Any,
    ):
        super().__init__(config, **kwargs)
        # 用户配置优先于内置预设，便于修正版本差异而无需改代码
        merged = dict(profile or {})
        merged.update(self.config.get("ingest_profile") or {})
        self.profile = merged
        if capabilities is not None:
            self.capabilities = capabilities
        else:
            self.capabilities = IngestCapabilities(
                list_knowledge_bases="list_kb" in merged,
                create_knowledge_base="create_kb" in merged,
                upload_documents="upload" in merged,
                parse_documents="parse" in merged,
                list_chunks="list_chunks" in merged,
                create_chat=False,
                ask="ask" in merged,
                verified=bool(merged.get("_verified")),
                docs_url=str(merged.get("_docs_url") or self.config.get("api_doc_url") or ""),
                notes=str(merged.get("_notes") or ""),
            )

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> Dict[str, str]:
        auth_type = self.config.get("auth_type") or "bearer"
        if auth_type == "none":
            return {}
        if auth_type == "api_key":
            header = self.config.get("api_key_header") or "X-API-Key"
            return {header: self.api_key} if self.api_key else {}
        return self.auth_headers()

    async def _call(self, spec: Dict[str, Any], context: Dict[str, Any]) -> Any:
        method = str(spec.get("method") or "POST").upper()
        # 用户填写的 endpoint 优先于预设默认域名
        base = self.base_url or spec.get("base_url") or ""
        path = render(spec.get("path") or "", context)
        url = f"{str(base).rstrip('/')}/{str(path).lstrip('/')}" if path else base

        params = render(spec.get("params") or {}, context) or None
        json_body = render(spec.get("body"), context) if "body" in spec else None
        data = render(spec.get("form_fields"), context) if spec.get("form_fields") else None

        files = getattr(self, "_upload_files", None) if spec.get("multipart") else None
        if spec.get("multipart"):
            self._upload_files = None

        payload = await self.request_json(
            method,
            url,
            headers=self._headers(),
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=self.upload_timeout if files else None,
            auth=False,
        )
        return self._unwrap(payload, spec)

    def _unwrap(self, payload: Any, spec: Dict[str, Any]) -> Any:
        """处理 {code, data} 信封；不同厂商 code 成功值可能是 0 或 200"""
        if not isinstance(payload, dict):
            return payload
        envelope = spec.get("envelope")
        if not envelope:
            if "code" in payload and "data" in payload:
                code = payload.get("code")
                if code not in (None, 0, 200):
                    raise ConnectorError(
                        f"{self.display_name} 返回 code={code}："
                        f"{payload.get('message') or payload.get('msg') or payload}"
                    )
                return payload.get("data")
            return payload

        code_path = envelope.get("code_path") or "code"
        ok_values = envelope.get("ok_values") or [0, 200]
        code = dig(payload, code_path)
        if code not in (None, *ok_values):
            message = dig(payload, envelope.get("message_path") or "message", "")
            raise ConnectorError(f"{self.display_name} 返回 code={code}：{message or payload}")
        data_path = envelope.get("data_path")
        return dig(payload, data_path) if data_path else payload

    # -------------------------------------------------------------- 知识库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        self.ensure_supported("list_knowledge_bases")
        spec = self.profile["list_kb"]
        payload = await self._call(spec, {})
        items = dig(payload, spec.get("items_path") or "", payload)
        if isinstance(items, dict):
            items = items.get("list") or items.get("items") or []
        return [
            KnowledgeBase(
                id=str(dig(item, spec.get("id_path") or "id")),
                name=str(dig(item, spec.get("name_path") or "name") or ""),
                raw=item,
            )
            for item in (items or [])
            if dig(item, spec.get("id_path") or "id")
        ]

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        self.ensure_supported("create_knowledge_base")
        spec = self.profile["create_kb"]
        context = {"name": name, "description": kwargs.get("description", ""), **kwargs}
        payload = await self._call(spec, context)
        kb_id = dig(payload, spec.get("id_path") or "id")
        if not kb_id:
            raise ConnectorError(f"{self.display_name} 建库未返回 ID：{payload}")
        return KnowledgeBase(
            id=str(kb_id),
            name=str(dig(payload, spec.get("name_path") or "name") or name),
            raw=payload if isinstance(payload, dict) else {},
        )

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        self.ensure_supported("upload_documents")
        spec = self.profile["upload"]
        file_field = spec.get("file_field") or "file"
        self._upload_files = {
            file_field: (file_name, content, content_type or "application/octet-stream")
        }
        context = {"kb_id": kb_id, "file_name": file_name, "file_size": len(content)}
        payload = await self._call(spec, context)
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        doc_id = dig(payload, spec.get("id_path") or "id")
        if not doc_id:
            raise ConnectorError(f"{self.display_name} 上传 {file_name} 未返回文档 ID：{payload}")
        return RemoteDocument(
            id=str(doc_id),
            name=str(dig(payload, spec.get("name_path") or "name") or file_name),
            status="pending",
            raw=payload if isinstance(payload, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        spec = self.profile.get("parse")
        if not spec:
            return None
        await self._call(spec, {"kb_id": kb_id, "document_ids": document_ids})

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        spec = self.profile.get("list_docs")
        if not spec:
            raise ConnectorError(f"{self.display_name} 未配置 list_docs，无法轮询解析状态")
        payload = await self._call(spec, {"kb_id": kb_id})
        items = dig(payload, spec.get("items_path") or "", payload)
        if isinstance(items, dict):
            items = items.get("list") or items.get("items") or []
        return [self._map_document(item, spec) for item in (items or [])]

    def _map_document(self, item: Dict[str, Any], spec: Dict[str, Any]) -> RemoteDocument:
        raw = str(dig(item, spec.get("status_path") or "status") or "").lower()
        done_values = [str(v).lower() for v in (spec.get("done_values") or ["completed", "done", "success"])]
        fail_values = [str(v).lower() for v in (spec.get("fail_values") or ["failed", "error", "fail"])]
        if raw in done_values:
            status = "done"
        elif raw in fail_values:
            status = "failed"
        else:
            status = "running"

        try:
            progress = float(dig(item, spec.get("progress_path") or "progress", 0) or 0)
        except (TypeError, ValueError):
            progress = 0.0
        if progress > 1.0:
            progress = progress / 100.0
        if status == "done":
            progress = 1.0

        return RemoteDocument(
            id=str(dig(item, spec.get("id_path") or "id")),
            name=str(dig(item, spec.get("name_path") or "name") or ""),
            status=status,
            progress=progress,
            error=(
                str(dig(item, spec.get("error_path") or "error") or "") or None
                if status == "failed"
                else None
            ),
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        self.ensure_supported("list_chunks")
        spec = self.profile["list_chunks"]
        page_param = spec.get("page_param")
        page_size_param = spec.get("page_size_param")
        page_size = int(spec.get("page_size") or 100)
        page = int(spec.get("page_start") or 1)
        chunks: List[RemoteChunk] = []

        while True:
            context: Dict[str, Any] = {"kb_id": kb_id, "document_id": document_id}
            if page_param:
                context[page_param] = page
                context["page"] = page
            if page_size_param:
                context[page_size_param] = page_size
                context["page_size"] = page_size
            payload = await self._call(spec, context)
            items = dig(payload, spec.get("items_path") or "", payload)
            if isinstance(items, dict):
                items = items.get("list") or items.get("items") or []
            items = items or []
            for item in items:
                content = dig(item, spec.get("content_path") or "content", "") or ""
                chunks.append(
                    RemoteChunk(
                        id=str(dig(item, spec.get("id_path") or "id") or f"{document_id}-{len(chunks)}"),
                        content=content,
                        document_id=document_id,
                        index=int(dig(item, spec.get("index_path") or "index", len(chunks)) or len(chunks)),
                        raw=item,
                    )
                )
            if not page_param or len(items) < page_size:
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
        spec = self.profile.get("ask")
        if not spec:
            raise ConnectorError(f"{self.display_name} 未配置 ask")
        context = {
            # 先把连接配置铺开（app_id / pipeline_ids / bot_id 等），再用本次调用参数覆盖
            **{key: value for key, value in self.config.items() if isinstance(value, (str, int, float, list))},
            "question": question,
            "chat_id": chat_id or "",
            "conversation_id": conversation_id or "",
            "model": self.config.get("model") or "",
        }
        payload = await self._call(spec, context)
        answer = dig(payload, spec.get("answer_path") or "answer", "") or ""
        contexts = dig(payload, spec.get("contexts_path") or "contexts", []) or []
        ids = dig(payload, spec.get("retrieval_ids_path") or "retrieval_ids", []) or []
        if isinstance(contexts, str):
            contexts = [contexts]
        # 有的系统返回对象数组（如 Flowise sourceDocuments），用子路径抽正文
        content_path = spec.get("contexts_content_path")
        if content_path and isinstance(contexts, list):
            extracted = []
            for item in contexts:
                text = dig(item, content_path) if isinstance(item, dict) else item
                if text:
                    extracted.append(str(text))
            contexts = extracted
        return {
            "answer": answer,
            "contexts": contexts,
            "retrieval_ids": ids if isinstance(ids, list) else [],
            "metadata": payload if isinstance(payload, dict) else {},
        }

    async def check_connection(self) -> Dict[str, Any]:
        try:
            if self.capabilities.list_knowledge_bases:
                kbs = await self.list_knowledge_bases()
                return {"healthy": True, "knowledge_base_count": len(kbs)}
            if self.capabilities.ask:
                data = await self.ask("ping")
                return {"healthy": bool(data.get("answer")) or True, "probe": "ask"}
            return {"healthy": False, "error": "profile 未配置可用能力"}
        except ConnectorError as exc:
            return {"healthy": False, "error": format_error(exc)}
