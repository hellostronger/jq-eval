# Coze（扣子）API 全链路连接器
#
# 参考文档：
# - 创建知识库:   https://docs.coze.cn/developer_guides_create_dataset
# - 创建知识库文件: https://docs.coze.cn/developer_guides_create_knowledge_files
# - 上传进度:     https://docs.coze.cn/developer_guides_get_dataset_progress
# - 对话 API (v3): https://docs.coze.cn/developer_guides_chat_v3
#
# Coze 的能力边界（决定了为什么这里只能做"半链路"）：
# - 可以建库（POST /v1/datasets，需 space_id），但没有公开的列库接口。
# - 文档上传支持 file_base64；解析状态在 document/list 的 status 字段
#   （0 处理中 / 1 完成 / 9 失败）。
# - 不暴露分片列表接口，因此无法把远端 chunk 落到本地 Chunk；
#   评测时只能依赖对话返回的 knowledge 消息作为上下文。
# - 非流式 chat 只返回 chat 元数据，必须再 retrieve + message/list 才能拿回答；
#   结构化引用不保证存在，流式才有 knowledge 事件。
import base64
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


class CozeConnector(BaseApiIngestConnector):
    """Coze：建库 + 文档上传 + Bot 问答（无分片查询）"""

    system_type = "coze"
    display_name = "Coze"
    api_doc_url = "https://docs.coze.cn/developer_guides_create_knowledge_files"
    capabilities = IngestCapabilities(
        list_knowledge_bases=False,  # Coze 无公开列库接口
        create_knowledge_base=True,
        upload_documents=True,
        parse_documents=False,
        list_chunks=False,
        create_chat=False,
        ask=True,
        docs_url=api_doc_url,
        notes="建库需 space_id；文档上传需 dataset_id；Coze 不开放分片查询，引用依赖流式 knowledge 事件。",
    )

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        super().__init__(config, **kwargs)
        base = self.base_url
        if base.endswith("/v3"):
            base = base[: -len("/v3")]
        self.host = base
        self.open_api_root = f"{base}/open_api"
        self.chat_root = f"{base}/v3"

    def _headers(self) -> Dict[str, str]:
        # Agw-Js-Conv 是 Coze 网关要求：强制按字符串解析大整数，避免 document_id 精度丢失
        headers = {"Agw-Js-Conv": "str"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _document_kb_id(self, kb_id: Optional[str]) -> str:
        resolved = kb_id or str(self.config.get("dataset_id") or "").strip()
        if not resolved:
            raise ConnectorError(
                "Coze 未配置知识库 ID：请在连接配置里填写 dataset_id"
                "（可用本页的「新建知识库」自动创建，或从 Coze 控制台知识库详情页获取）。"
            )
        return resolved

    async def _doc_request(self, path: str, body: Dict[str, Any]) -> Any:
        data = await self.request_json(
            "POST",
            f"{self.open_api_root}{path}",
            headers=self._headers(),
            json_body=body,
            auth=False,
        )
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise ConnectorError(
                f"Coze API 返回错误 code={data.get('code')}：{data.get('msg') or data}"
            )
        return data.get("data", data) if isinstance(data, dict) else data

    # -------------------------------------------------------------- 知识库
    async def create_knowledge_base(self, name: str, **kwargs: Any) -> KnowledgeBase:
        space_id = str(
            kwargs.get("space_id") or self.config.get("space_id") or ""
        ).strip()
        if not space_id:
            raise ConnectorError(
                "Coze 建库需要 space_id：请在连接配置里填写空间 ID（空间 URL /w/{space_id}）"
            )
        body = {
            "name": name,
            "space_id": space_id,
            "format_type": int(kwargs.get("format_type") or self.config.get("format_type") or 0),
            "description": kwargs.get("description") or self.config.get("kb_description") or "",
        }
        payload = await self.request_json(
            "POST",
            f"{self.host}/v1/datasets",
            headers=self._headers(),
            json_body=body,
            auth=False,
        )
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise ConnectorError(
                f"Coze 建库返回错误 code={payload.get('code')}：{payload.get('msg') or payload}"
            )
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        kb_id = dig(data, "dataset_id") or dig(data, "id")
        if not kb_id:
            raise ConnectorError(f"Coze 建库未返回 dataset_id：{payload}")
        return KnowledgeBase(id=str(kb_id), name=name, raw=data if isinstance(data, dict) else {})

    # ---------------------------------------------------------------- 文档
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> RemoteDocument:
        dataset_id = self._document_kb_id(kb_id)
        body = {
            "dataset_id": dataset_id,
            "document_bases": [
                {
                    "name": file_name,
                    "source_info": {
                        "file_base64": base64.b64encode(content).decode("ascii"),
                        "file_type": content_type or "text/plain",
                    },
                }
            ],
            "format_type": 0,  # 0=文本
            "chunk_strategy": self.config.get("chunk_strategy")
            or {
                "chunk_type": 0,
                "separator": "\n\n",
                "max_tokens": 800,
                "remove_extra_spaces": False,
                "remove_urls_emails": False,
            },
        }
        data = await self._doc_request("/knowledge/document/create", body)
        document_infos = dig(data, "document_infos", []) or []
        if not document_infos:
            raise ConnectorError(f"Coze 上传 {file_name} 未返回文档信息：{data}")
        doc = document_infos[0]
        doc_id = doc.get("document_id") or doc.get("id")
        if not doc_id:
            raise ConnectorError(f"Coze 上传 {file_name} 未返回文档 ID：{doc}")
        return RemoteDocument(
            id=str(doc_id),
            name=doc.get("name") or file_name,
            status="pending",
            raw=doc,
        )

    async def list_documents(self, kb_id: str) -> List[RemoteDocument]:
        dataset_id = self._document_kb_id(kb_id)
        documents: List[RemoteDocument] = []
        page = 1
        while True:
            data = await self._doc_request(
                "/knowledge/document/list",
                {"dataset_id": dataset_id, "page": page, "size": 100},
            )
            items = dig(data, "document_infos", []) or []
            documents.extend(self._map_document(item) for item in items)
            total = int(dig(data, "total", 0) or 0)
            if len(items) < 100 or page * 100 >= total:
                break
            page += 1
        return documents

    def _map_document(self, item: Dict[str, Any]) -> RemoteDocument:
        raw_status = item.get("status")
        if str(raw_status).lower() in ("1", "completed", "success", "done"):
            status = "done"
        elif str(raw_status).lower() in ("2", "9", "failed", "error"):
            status = "failed"
        else:
            status = "running"

        error = None
        if status == "failed":
            error = item.get("error") or item.get("status_msg") or "解析失败"

        return RemoteDocument(
            id=str(item.get("document_id") or item.get("id")),
            name=item.get("name") or "",
            status=status,
            progress=1.0 if status == "done" else 0.0,
            error=error,
            raw=item,
        )

    async def list_chunks(self, kb_id: str, document_id: str) -> List[RemoteChunk]:
        # 显式不支持：Coze 未开放分片查询。调用方应跳过本地 Chunk 落库。
        return []

    async def trigger_parse(self, kb_id: str, document_ids: List[str]) -> None:
        # 上传后自动解析，无需触发
        return None

    # ---------------------------------------------------------------- 问答
    async def ask(
        self,
        question: str,
        *,
        chat_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        import asyncio
        import time

        bot_id = str(self.config.get("bot_id") or chat_id or "").strip()
        if not bot_id:
            raise ConnectorError("Coze 问答缺少 bot_id：请在连接配置里填写 Bot ID")

        body: Dict[str, Any] = {
            "bot_id": bot_id,
            "user_id": self.config.get("user_id") or "jq-eval",
            "stream": False,
            "auto_save_history": True,
            "additional_messages": [
                {"role": "user", "content": question, "content_type": "text"}
            ],
        }
        if conversation_id:
            body["conversation_id"] = conversation_id

        params = {"conversation_id": conversation_id} if conversation_id else None
        started = await self.request_json(
            "POST",
            f"{self.chat_root}/chat",
            headers=self._headers(),
            params=params,
            json_body=body,
            timeout=self.config.get("llm_timeout") or 300.0,
            auth=False,
        )
        if isinstance(started, dict) and started.get("code") not in (None, 0):
            raise ConnectorError(
                f"Coze 对话返回错误 code={started.get('code')}：{started.get('msg') or started}"
            )

        chat_data = started.get("data", {}) if isinstance(started, dict) else {}
        remote_chat_id = chat_data.get("id")
        remote_conversation_id = chat_data.get("conversation_id") or conversation_id

        # 非流式 chat 只返回元数据：必须轮询 retrieve，再取 message/list
        deadline = time.monotonic() + float(self.config.get("poll_timeout") or 180.0)
        status = str(chat_data.get("status") or "").lower()
        while remote_chat_id and status not in ("completed", "failed", "canceled", "required_action"):
            if time.monotonic() >= deadline:
                raise ConnectorError(
                    f"Coze 对话轮询超时（{self.config.get('poll_timeout') or 180}s），最后状态：{status}"
                )
            await asyncio.sleep(float(self.config.get("poll_interval") or 1.0))
            retrieved = await self.request_json(
                "GET",
                f"{self.chat_root}/chat/retrieve",
                headers=self._headers(),
                params={
                    "conversation_id": remote_conversation_id,
                    "chat_id": remote_chat_id,
                },
                auth=False,
            )
            status = str(dig(retrieved, "data.status", status) or status).lower()

        messages: List[Dict[str, Any]] = []
        if remote_chat_id:
            listed = await self.request_json(
                "GET",
                f"{self.chat_root}/chat/message/list",
                headers=self._headers(),
                params={
                    "conversation_id": remote_conversation_id,
                    "chat_id": remote_chat_id,
                },
                auth=False,
            )
            messages = dig(listed, "data", []) or []

        answer = ""
        contexts: List[str] = []
        for message in messages:
            if message.get("type") == "answer" and message.get("content"):
                answer = message["content"]
            elif message.get("type") == "knowledge" and message.get("content"):
                contexts.append(message["content"])

        return {
            "answer": answer,
            "contexts": contexts,
            "retrieval_ids": [],
            "metadata": {"start": started, "messages": messages, "status": status},
        }

    async def check_connection(self) -> Dict[str, Any]:
        bot_id = str(self.config.get("bot_id") or "").strip()
        if not bot_id:
            return {"healthy": False, "error": "未填写 bot_id"}
        try:
            data = await self.request_json(
                "GET",
                f"{self.chat_root}/bots/{bot_id}",
                headers=self._headers(),
                auth=False,
            )
            code = data.get("code") if isinstance(data, dict) else None
            if code not in (None, 0):
                return {"healthy": False, "error": f"Coze 返回 code={code}: {data.get('msg')}"}
            return {"healthy": True, "bot_id": bot_id}
        except ConnectorError as exc:
            return {"healthy": False, "error": format_error(exc)}
