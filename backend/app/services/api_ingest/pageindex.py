# PageIndex（VectifyAI）接入连接器
#
# 参考文档（2026-10 逐条核对）：
# - API Reference：https://docs.pageindex.ai/api-reference
#   - POST https://api.pageindex.ai/doc/            multipart `file` -> {"doc_id": "pi-..."}
#     上传即自动建树索引，没有单独的“触发解析”接口。
#   - GET  https://api.pageindex.ai/doc/{doc_id}/   ?type=tree
#     -> {"doc_id","status":"processing"|"completed","result":[{title,node_id,page_index,text,nodes:[...]}]}
#   - GET  https://api.pageindex.ai/doc/{doc_id}/metadata -> {id,name,status,pageNum,...}
#   - GET  https://api.pageindex.ai/docs?limit=&offset= -> {documents:[{id,name,status,...}],total,...}
#   - POST https://api.pageindex.ai/chat/completions
#     body {"messages":[{"role":"user","content":...}],"doc_id":可选,"stream":false}
#     -> OpenAI 形状：choices.0.message.content
# - 鉴权：请求头 `api_key: <key>`（注意不是 Authorization: Bearer）。
# - 本地模式（pip install pageindex）只有 Python SDK，没有 HTTP 服务；
#   这里按 API 接的是 PageIndex Cloud。要接本机，需要自己包一层薄 HTTP 服务。
# - PageIndex 没有“知识库”概念，文档之间是独立的树。本连接器把账号下全部文档
#   视为一个虚拟库（id=pageindex:account）；分片取树的节点文本（node_id/page_index/text），
#   这样评测的 target chunk 能和问答引用里的 node 对齐。
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


class PageIndexConnector(BaseApiIngestConnector):
    """PageIndex Cloud：文档树索引 + 推理式检索问答"""

    system_type = "pageindex"
    display_name = "PageIndex"
    api_doc_url = "https://docs.pageindex.ai/api-reference"
    capabilities = IngestCapabilities(
        list_knowledge_bases=True,
        create_knowledge_base=False,
        upload_documents=True,
        parse_documents=True,  # 上传即自动建树；trigger_parse 为空操作
        list_chunks=True,  # 分片 = 树节点（node_id + text）
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes=(
            "PageIndex Cloud（api_key 请求头鉴权，上传后自动建树）。"
            "本地 SDK 模式没有 HTTP 服务，需要自建薄服务后才能接。"
            "没有知识库概念：账号下所有文档视为一个库，分片取树节点文本。"
            "尚未实机验证（本地未部署，也没有云端 key）。"
        ),
    )

    # 虚拟库 ID：承载账号下的全部文档
    ACCOUNT_KB = "pageindex:account"

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        if not self.base_url:
            self.base_url = "https://api.pageindex.ai"
        self.api_root = self.base_url.rstrip("/")

    def auth_headers(self) -> Dict[str, str]:
        # PageIndex 用 `api_key:` 头，不是 Bearer
        key = self.api_key or self.config.get("pageindex_api_key") or ""
        return {"api_key": str(key)} if key else {}

    # -------------------------------------------------------------- 文档库
    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        documents = await self._fetch_documents(limit=100)
        return [
            KnowledgeBase(
                id=self.ACCOUNT_KB,
                name="PageIndex 账号文档库",
                raw={"documents": documents},
            )
        ]

    async def _fetch_documents(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        data = await self.request_json(
            "GET", f"{self.api_root}/docs", params={"limit": limit, "offset": offset}
        )
        items = data.get("documents", []) if isinstance(data, dict) else []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        # PageIndex 只收 PDF；kb_id 是本地虚拟库，不参与上传
        files = {"file": (file_name, content, content_type or "application/pdf")}
        data = await self.request_json(
            "POST",
            f"{self.api_root}/doc/",
            files=files,
            timeout=self.upload_timeout,
        )
        doc_id = dig(data, "doc_id") or dig(data, "id")
        if not doc_id:
            raise ConnectorError(f"PageIndex 上传 {file_name} 未返回 doc_id：{data}")
        return RemoteDocument(
            id=str(doc_id),
            name=file_name,
            status="pending",
            raw=data if isinstance(data, dict) else {},
        )

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        # 上传即排队建树，无需显式触发；保留空实现让流水线无感
        return None

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        documents: List[RemoteDocument] = []
        offset = 0
        while True:
            batch = await self._fetch_documents(limit=100, offset=offset)
            documents.extend(self._map_document(item) for item in batch)
            if len(batch) < 100:
                break
            offset += len(batch)
        return documents

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = str(item.get("status") or "").lower()
        if raw_status in ("completed", "success", "done"):
            status = "done"
        elif raw_status in ("failed", "error"):
            status = "failed"
        elif raw_status in ("processing", "running", "indexing", "queued"):
            status = "running"
        else:
            status = "pending"
        return RemoteDocument(
            id=str(item.get("id") or item.get("doc_id")),
            name=item.get("name") or str(item.get("id") or ""),
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=(item.get("error") or item.get("message")) if status == "failed" else None,
            raw=item,
        )

    # ---------------------------------------------------------------- 分片
    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        data = await self.request_json(
            "GET", f"{self.api_root}/doc/{document_id}/", params={"type": "tree"}
        )
        tree = data.get("result") if isinstance(data, dict) else None
        if not isinstance(tree, list):
            return []
        chunks: List[RemoteChunk] = []
        self._flatten_nodes(tree, document_id, chunks)
        return chunks

    def _flatten_nodes(
        self, nodes: Any, document_id: str, out: List[RemoteChunk]
    ) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            text = node.get("text") or node.get("summary") or ""
            node_id = node.get("node_id") or node.get("id")
            if text and node_id:
                out.append(
                    RemoteChunk(
                        id=f"{document_id}:{node_id}",
                        content=text,
                        document_id=document_id,
                        document_name=node.get("title") or "",
                        index=int(node.get("page_index") or 0),
                        raw=node,
                    )
                )
            self._flatten_nodes(node.get("nodes") or node.get("children"), document_id, out)

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "messages": [{"role": "user", "content": question}],
            "stream": False,
            "enable_citations": True,
        }
        doc_id = self.config.get("doc_id") or self.config.get("pageindex_doc_id")
        if doc_id:
            body["doc_id"] = doc_id

        data = await self.request_json(
            "POST",
            f"{self.api_root}/chat/completions",
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
        )
        message = dig(data, "choices.0.message", {}) or {}
        answer = message.get("content") or data.get("answer") if isinstance(data, dict) else ""
        citations = (
            message.get("citations")
            or message.get("references")
            or (data.get("citations") if isinstance(data, dict) else None)
            or []
        )

        contexts: List[str] = []
        retrieval_ids: List[str] = []
        for citation in citations if isinstance(citations, list) else []:
            if isinstance(citation, str):
                contexts.append(citation)
                continue
            if not isinstance(citation, dict):
                continue
            text = citation.get("text") or citation.get("content") or citation.get("snippet")
            if text:
                contexts.append(str(text))
            cite_id = citation.get("node_id") or citation.get("block_id") or citation.get("id")
            if cite_id:
                retrieval_ids.append(str(cite_id))

        return {
            "answer": answer or "",
            "contexts": contexts,
            "retrieval_ids": retrieval_ids,
            "metadata": data,
        }
