# LLM Wiki（nashsu/llm_wiki）接入连接器
#
# 参考文档（2026-10 核对 README 的 “Local HTTP API + MCP Server” 一节，并对照
# 仓库自带 mcp-server/src/api-client.ts 的请求形状）：
#   https://github.com/nashsu/llm_wiki#local-http-api--mcp-server--ai-agent-skill
#
# - 桌面应用内置本地 JSON API：http://127.0.0.1:19828/api/v1（默认只监听本机）
# - 鉴权：Authorization: Bearer <token>（Settings -> API + MCP 里生成；
#   若允许本机免鉴权则 token 可为空）
# - 本连接器用到的接口：
#   GET  /health                                         -> {ok/enabled/authRequired...}
#   GET  /projects                                       -> {projects:[{id,name,path,current}], currentProject}
#   GET  /projects/{id}/files?root=wiki&recursive=true   -> {files:[{name,path,isDir,children}]}
#   POST /projects/{id}/pages/write  {path,content,allowOverwrite}
#        -> {result:{path,bytes,verified,...}}           外部写入 wiki 页（agent 入口）
#   POST /projects/{id}/pages/embed  {path,force}         -> {result:{path,chunks,vectorsWritten,status}}
#   POST /projects/{id}/chat  {message,sessionId,mode,topK,tools:{wiki,web,anytxt}}
#        -> {message:{role,content}, references:[{title,path,kind,snippet,score}], sessionId}
#
# 限制（写进 capabilities.notes，前端会展示）：
# - Sources 导入（PDF/DOCX 解析）只在桌面端做，API 没有上传原始文件的接口；
#   这里用 pages/write 把文本写进 wiki/imports/*.md，再 pages/embed 建向量，
#   属于官方给外部 agent 的写入路径，不等价于桌面的 Sources 编译流程。
# - 没有分片列表接口（只有按 query 的 hybrid search），因此 list_chunks=False，
#   评测上下文只能取 chat 返回的 references/snippet。
# - 应用必须先在本机运行，否则 127.0.0.1:19828 直接连接失败。
from typing import Any, Dict, List, Optional

from app.core.exceptions import format_error

from .base import (
    BaseApiIngestConnector,
    ConnectorError,
    IngestCapabilities,
    KnowledgeBase,
    RemoteDocument,
    dig,
)


class LlmWikiConnector(BaseApiIngestConnector):
    """LLM Wiki 桌面应用（本地 HTTP API）"""

    system_type = "llm_wiki"
    display_name = "LLM Wiki"
    api_doc_url = (
        "https://github.com/nashsu/llm_wiki"
        "#local-http-api--mcp-server--ai-agent-skill"
    )
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,  # 项目（project）只能在桌面端创建
        upload_documents=True,  # 通过 pages/write 写入 wiki 页
        parse_documents=True,  # pages/embed 建向量
        list_chunks=False,  # 无分片列表接口，只有按查询的 hybrid search
        create_chat=False,  # 会话由 chat 接口自动创建
        ask=True,
        docs_url=api_doc_url,
        notes=(
            "接本机 LLM Wiki 桌面应用（127.0.0.1:19828，Bearer token 在 "
            "Settings → API + MCP 生成，应用需保持运行）。"
            "API 没有原始文件上传接口：文本会写到 wiki/imports/*.md 再 embed，"
            "PDF/DOCX 的解析仍应在桌面端 Sources 完成。没有分片列表，"
            "检索上下文取 chat 返回的 references。"
        ),
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        if not self.base_url:
            self.base_url = "http://127.0.0.1:19828"
        base = self.base_url.rstrip("/")
        self.api_root = base if base.endswith("/api/v1") else f"{base}/api/v1"

    # -------------------------------------------------------------- 项目
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        data = await self.request_json("GET", f"{self.api_root}/projects")
        projects = data.get("projects", []) if isinstance(data, dict) else []
        knowledge_bases = [
            KnowledgeBase(
                id=str(item.get("id")),
                name=item.get("name") or str(item.get("id")),
                raw=item,
            )
            for item in projects
            if isinstance(item, dict) and item.get("id")
        ]
        if not knowledge_bases:
            raise ConnectorError(
                "LLM Wiki 没有返回任何项目：请先在桌面应用里创建/打开一个知识库。"
            )
        return knowledge_bases

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConnectorError(
                f"LLM Wiki 的写入接口只接受 markdown/文本（{file_name} 不是 UTF-8 文本）。"
                "PDF/DOCX 请先在桌面端 Sources 导入编译，再用 jq-eval 选择该 wiki 评测。"
            ) from exc

        path = self._import_path(file_name)
        payload = await self.request_json(
            "POST",
            f"{self.api_root}/projects/{kb_id}/pages/write",
            json_body={"path": path, "content": text, "allowOverwrite": True},
            timeout=self.upload_timeout,
        )
        result = dig(payload, "result", {}) or {}
        if not result.get("verified"):
            raise ConnectorError(f"LLM Wiki 写入 {path} 未通过校验：{payload}")
        written_path = str(result.get("path") or path)

        status = "pending"
        progress = 0.0
        embed_result: Dict[str, Any] = {}
        try:
            embed_payload = await self.request_json(
                "POST",
                f"{self.api_root}/projects/{kb_id}/pages/embed",
                json_body={"path": written_path, "force": True},
                timeout=self.config.get("llm_timeout") or 300.0,
            )
            embed_result = dig(embed_payload, "result", {}) or {}
            status = "done" if str(embed_result.get("status") or "").lower() in (
                "ok",
                "done",
                "indexed",
                "embedded",
                "success",
            ) else "running"
            progress = 1.0 if status == "done" else 0.5
        except ConnectorError as exc:
            # 写入成功但向量化失败时，文档仍在 wiki 里，标记失败并带上原因
            return RemoteDocument(
                id=written_path,
                name=file_name,
                status="failed",
                error=f"向量化失败：{format_error(exc)}",
                raw={"write": result, "embed_error": format_error(exc)},
            )

        return RemoteDocument(
            id=written_path,
            name=file_name,
            status=status,
            progress=progress,
            raw={"write": result, "embed": embed_result},
        )

    @staticmethod
    def _import_path(file_name: str) -> str:
        """把文件名收敛成 wiki/imports 下的安全路径"""
        safe = (file_name or "document").replace("\\", "_").replace("/", "_").strip(". ")
        if not safe.lower().endswith((".md", ".markdown", ".txt")):
            safe = f"{safe}.md"
        return f"wiki/imports/{safe}"

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        # 上传时已经 embed；显式触发时再强制重建一次，便于改过文件后重跑
        for path in document_ids:
            await self.request_json(
                "POST",
                f"{self.api_root}/projects/{kb_id}/pages/embed",
                json_body={"path": path, "force": True},
                timeout=self.config.get("llm_timeout") or 300.0,
            )

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        data = await self.request_json(
            "GET",
            f"{self.api_root}/projects/{kb_id}/files",
            params={"root": "wiki", "recursive": "true", "maxFiles": 5000},
        )
        documents: List[RemoteDocument] = []
        self._walk_files(data.get("files", []) if isinstance(data, dict) else [], documents)
        return documents

    def _walk_files(self, nodes: Any, out: List[RemoteDocument]) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("isDir"):
                self._walk_files(node.get("children"), out)
                continue
            path = node.get("path")
            if not path:
                continue
            out.append(
                RemoteDocument(
                    id=str(path),
                    name=node.get("name") or str(path),
                    status="done",
                    progress=1.0,
                    raw=node,
                )
            )

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        kb_id = chat_id or self.config.get("kb_id") or "current"
        body: Dict[str, Any] = {
            "message": question,
            "topK": int(self.config.get("top_k") or 8),
            "tools": {
                "wiki": True,
                "web": bool(self.config.get("enable_web") or False),
                "anytxt": False,
            },
        }
        if conversation_id:
            body["sessionId"] = conversation_id
        mode = self.config.get("chat_mode")
        if mode:
            body["mode"] = mode

        data = await self.request_json(
            "POST",
            f"{self.api_root}/projects/{kb_id}/chat",
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        message = dig(data, "message", {}) or {}
        references = dig(data, "references", []) or []

        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for reference in references if isinstance(references, list) else []:
            if not isinstance(reference, dict):
                continue
            snippet = reference.get("snippet") or reference.get("text") or reference.get("content")
            if snippet:
                contexts.append(str(snippet))
            ref_path = reference.get("path") or reference.get("id")
            if ref_path:
                retrieval_ids.append(str(ref_path))

        return {
            "answer": message.get("content") or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "session_id": data.get("sessionId") if isinstance(data, dict) else None,
            "metadata": data,
        }

    # ------------------------------------------------------------ 连通性
    async def check_connection(self) -> Dict[str, Any]:
        try:
            data = await self.request_json(
                "GET", f"{self.api_root}/health", auth=False
            )
            return {
                "healthy": True,
                "knowledge_base_count": None,
                "health": data,
            }
        except ConnectorError as exc:
            return {
                "healthy": False,
                "error": (
                    f"{format_error(exc)}；请确认 LLM Wiki 桌面应用已启动，"
                    "并在 Settings → API + MCP 打开本地 API。"
                ),
            }
