# API 全链路接入连接器基类
#
# 与 sync（数据库直连同步，已废弃）不同，这里走被测系统的官方 HTTP API：
#   建库 -> 上传原始文档 -> 触发解析 -> 轮询解析状态 -> 拉取远端分片 -> 生成/导入 QA
# 目标是把「jq-eval 的评测数据集」和「被测系统实际检索到的分片」对齐，
# 这样 Recall@K / MRR / 引用命中才有真实的对照物。
#
# 设计约束：
# 1. 只做 API，不依赖对方数据库/表结构（RAGFlow MySQL+ES、Dify PG、FastGPT Mongo 各不相同）。
# 2. 各家能力不一致（有的不能建库、有的不暴露分片），用 IngestCapabilities 显式声明，
#    前端据此隐藏入口，而不是让用户点到最后一步才报错。
# 3. 所有实现都接受 transport 注入，测试用 httpx.MockTransport 离线跑契约。
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.core.exceptions import format_error


class ConnectorError(Exception):
    """连接器可读错误：把上游状态码/响应片段带出来，避免只报一个类名"""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass
class KnowledgeBase:
    """远端知识库（RAGFlow dataset / Dify dataset / FastGPT dataset）"""

    id: str
    name: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteDocument:
    """远端文档及其解析状态"""

    id: str
    name: str
    status: str = "unknown"  # pending | running | done | failed
    progress: float = 0.0
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status == "done"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass
class RemoteChunk:
    """远端分片：入库后保存为本地 Chunk，QA 的 target_chunk_ids 指向它"""

    id: str
    content: str
    document_id: str = ""
    document_name: str = ""
    index: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestCapabilities:
    """接入能力声明（前端据此决定展示哪些操作）"""

    list_knowledge_bases: bool = False
    create_knowledge_base: bool = False
    upload_documents: bool = False
    parse_documents: bool = False
    list_chunks: bool = False
    create_chat: bool = False
    ask: bool = True

    # verified: 是否已在本地私有化部署上实测通过（False 表示按官方文档实现、待验证）
    verified: bool = False
    docs_url: str = ""
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "list_knowledge_bases": self.list_knowledge_bases,
            "create_knowledge_base": self.create_knowledge_base,
            "upload_documents": self.upload_documents,
            "parse_documents": self.parse_documents,
            "list_chunks": self.list_chunks,
            "create_chat": self.create_chat,
            "ask": self.ask,
            "verified": self.verified,
            "docs_url": self.docs_url,
            "notes": self.notes,
        }


def dig(data: Any, path: str, default: Any = None) -> Any:
    """按 "data.docs.0.name" 取值；纯数字段按列表下标处理

    各家响应嵌套层级不同，用路径而不是层层 if，连接器里能少一半噪音。
    """
    if not path:
        return data
    value = data
    for key in path.split("."):
        if isinstance(value, dict):
            if key not in value:
                return default
            value = value[key]
        elif isinstance(value, (list, tuple)):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return value


class BaseApiIngestConnector(ABC):
    """API 全链路接入连接器基类"""

    system_type: str = ""
    display_name: str = ""
    api_doc_url: str = ""
    capabilities: IngestCapabilities = IngestCapabilities()

    request_timeout: float = 30.0
    upload_timeout: float = 300.0

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.config = config or {}
        raw_base = (
            self.config.get("api_endpoint")
            or self.config.get("api_url")
            or ""
        )
        self.base_url = str(raw_base).rstrip("/")
        self.api_key = (
            self.config.get("api_key")
            or self.config.get("access_token")
            or ""
        )
        # 仅测试注入；生产为 None，走 httpx 默认 transport
        self._transport = transport

    # ------------------------------------------------------------------ HTTP
    def client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout if timeout is not None else self.request_timeout,
            transport=self._transport,
            follow_redirects=True,
        )

    def auth_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
        timeout: Optional[float] = None,
        auth: bool = True,
    ) -> Any:
        """发起请求并解析 JSON；HTTP 错误统一转 ConnectorError"""
        merged_headers = dict(headers or {})
        if auth:
            for key, value in self.auth_headers().items():
                merged_headers.setdefault(key, value)

        try:
            async with self.client(timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=merged_headers,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                )
        except httpx.TimeoutException as exc:
            raise ConnectorError(
                f"请求 {self.display_name} 超时"
                f"（{timeout if timeout is not None else self.request_timeout:.0f}s）：{url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(f"无法连接 {self.display_name}：{exc}") from exc

        if response.status_code >= 400:
            body = response.text[:800]
            raise ConnectorError(
                f"{self.display_name} 返回 HTTP {response.status_code}：{body}",
                status_code=response.status_code,
                response_body=body,
            )

        try:
            return response.json()
        except ValueError:
            # 某些网关成功时也返回空体/纯文本；保留原文供上层判断
            return {"_raw_text": response.text}

    def ensure_supported(self, capability: str) -> None:
        if not getattr(self.capabilities, capability, False):
            raise ConnectorError(
                f"{self.display_name} 不支持「{capability}」。"
                "请改在对方系统页面完成该步骤，或在 jq-eval 中选择其它接入类型。"
            )

    # ------------------------------------------------------------- 能力接口
    async def check_connection(self) -> Dict[str, Any]:
        """轻量连通性检查；失败返回 healthy=False 而不是抛异常（供 /health 使用）"""
        try:
            knowledge_bases = await self.list_knowledge_bases()
            return {"healthy": True, "knowledge_base_count": len(knowledge_bases)}
        except ConnectorError as exc:
            return {"healthy": False, "error": format_error(exc)}

    async def list_knowledge_bases(self) -> List[KnowledgeBase]:
        self.ensure_supported("list_knowledge_bases")
        return []

    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        self.ensure_supported("create_knowledge_base")
        raise ConnectorError(f"{self.display_name} 未实现建库")

    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        self.ensure_supported("upload_documents")
        raise ConnectorError(f"{self.display_name} 未实现上传")

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        """触发解析；不支持显式触发的系统可重写为空操作"""
        self.ensure_supported("parse_documents")

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        """列出知识库内文档及解析状态（轮询的公共依赖）"""
        raise ConnectorError(f"{self.display_name} 未实现文档列表")

    async def wait_documents_ready(
        self,
        kb_id: str,
        document_ids: List[str],
        *,
        timeout: float = 900.0,
        interval: float = 3.0,
        on_progress: Optional[Callable[[int, int, List[RemoteDocument]], None]] = None,
    ) -> List[RemoteDocument]:
        """轮询直到目标文档全部完成/失败/超时

        未在远端列表中出现的 id 视为"尚未开始"，继续等；这是 RAGFlow
        上传后短暂查不到、FastGPT 异步建 collection 的常见窗口。
        """
        import asyncio
        import time

        wanted = set(document_ids)
        deadline = time.monotonic() + timeout
        last: Dict[str, RemoteDocument] = {}

        while True:
            documents = await self.list_documents(kb_id)
            current = {doc.id: doc for doc in documents if doc.id in wanted}
            last.update(current)

            done = [d for d in last.values() if d.ready]
            failed = [d for d in last.values() if d.failed]
            if on_progress:
                on_progress(len(done) + len(failed), len(wanted), list(last.values()))
            if len(done) + len(failed) >= len(wanted):
                return list(last.values())

            if time.monotonic() >= deadline:
                pending = [doc_id for doc_id in wanted if doc_id not in last or not last[doc_id].ready]
                raise ConnectorError(
                    f"{self.display_name} 解析超时（{timeout:.0f}s），仍有 {len(pending)} 个文档未完成："
                    + ", ".join(pending[:5])
                )

            await asyncio.sleep(interval)

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        self.ensure_supported("list_chunks")
        return []

    async def ensure_chat(self, name: str, kb_ids: List[str]) -> str:
        """确保存在可问答的会话/助手，返回 chat_id；不支持创建的返回配置值或空串"""
        return str(self.config.get("chat_id") or "")

    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise ConnectorError(f"{self.display_name} 未实现问答")

    def get_info(self) -> Dict[str, Any]:
        return {
            "system_type": self.system_type,
            "display_name": self.display_name,
            "api_doc_url": self.api_doc_url,
            "capabilities": self.capabilities.as_dict(),
        }
