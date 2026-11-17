# 多模态 Embedding 客户端
#
# 两条协议：
#   * OpenAI 兼容 /embeddings —— 图片以 content 数组（image_url/data URL）传入。
#     vLLM 等网关的多模态 embedding 走 messages 字段，可用 request_format=messages 切换。
#   * Gemini batchEmbedContents —— EmbeddingGemma 2 / Gemini Embedding 的官方协议，
#     图片走 inline_data(base64)。
# 所有请求串行发送（大 batch 在单个请求内完成），不做并发压测式调用。
import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

import httpx

logger = logging.getLogger(__name__)

GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_FORMATS = ("content_array", "messages", "text_only")
IMAGE_TRANSPORTS = ("data_url", "url")


@dataclass
class MediaItem:
    """一次待编码的输入：文本、图片或图文对"""

    text: Optional[str] = None
    image_bytes: Optional[bytes] = None
    image_mime: Optional[str] = None
    image_url: Optional[str] = None  # image_transport=url 时使用预签名地址

    def is_empty(self) -> bool:
        return not self.text and not self.image_bytes and not self.image_url


class MMEmbeddingError(RuntimeError):
    pass


class MMEmbeddingClient:
    def __init__(self, model, params: Optional[dict] = None):
        self.model = model
        model_params = model.params or {}
        merged = {**model_params, **(params or {})}

        self.model_name = (
            merged.get("model_name") or model.model_name or model.name
        )
        self.endpoint = (model.endpoint or "").rstrip("/")
        self.api_key = model.api_key_encrypted or ""
        self.provider = (model.provider or "").lower()

        self.request_format = str(merged.get("request_format") or "content_array").lower()
        if self.request_format not in REQUEST_FORMATS:
            raise ValueError(
                f"不支持的 request_format={self.request_format}，可选：{', '.join(REQUEST_FORMATS)}"
            )
        self.image_transport = str(merged.get("image_transport") or "data_url").lower()
        if self.image_transport not in IMAGE_TRANSPORTS:
            raise ValueError(
                f"不支持的 image_transport={self.image_transport}，可选：{', '.join(IMAGE_TRANSPORTS)}"
            )

        self.timeout = float(merged.get("timeout") or 180)
        self.max_retries = int(merged.get("max_retries") or 2)
        self.dimension = model.dimension

        self.is_gemini = self.provider == "gemini" or "generativelanguage.googleapis.com" in self.endpoint
        default_batch = 100 if self.is_gemini else 8
        self.batch_size = max(1, min(int(merged.get("batch_size") or default_batch), 100))
        if self.request_format == "messages" and not self.is_gemini:
            # messages 形态一次只能表达一个输入，批量会导致返回条数对不上
            self.batch_size = 1

    async def embed(
        self,
        items: List[MediaItem],
        progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
        cancel_cb: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> List[List[float]]:
        if not items:
            return []

        vectors: List[List[float]] = []
        total = len(items)
        for start in range(0, total, self.batch_size):
            if cancel_cb:
                await cancel_cb()
            batch = items[start : start + self.batch_size]
            batch_vectors = (
                await self._embed_gemini(batch)
                if self.is_gemini
                else await self._embed_openai(batch)
            )
            if len(batch_vectors) != len(batch):
                raise MMEmbeddingError(
                    f"嵌入返回条数不匹配：请求 {len(batch)} 条，返回 {len(batch_vectors)} 条"
                )
            vectors.extend(batch_vectors)
            if progress_cb:
                await progress_cb(len(vectors), total)
        return vectors

    # ------------------------------------------------------------------ OpenAI
    async def _embed_openai(self, batch: List[MediaItem]) -> List[List[float]]:
        if not self.endpoint:
            raise MMEmbeddingError("模型未配置 API 地址（endpoint）")

        url = (
            self.endpoint
            if self.endpoint.endswith("/embeddings")
            else f"{self.endpoint}/embeddings"
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self.request_format == "messages":
            body = {
                "model": self.model_name,
                "messages": [
                    {"role": "user", "content": self._content_blocks(batch[0])}
                ],
            }
        elif self.request_format == "text_only":
            body = {
                "model": self.model_name,
                "input": [item.text or "" for item in batch],
            }
        else:
            body = {
                "model": self.model_name,
                "input": [{"content": self._content_blocks(item)} for item in batch],
            }

        payload = await self._post(url, headers, body)
        return self._extract_vectors(payload, expected=len(batch))

    def _content_blocks(self, item: MediaItem) -> List[dict]:
        blocks: List[dict] = []
        if item.text:
            blocks.append({"type": "text", "text": item.text})
        if item.image_bytes or item.image_url:
            blocks.append(
                {"type": "image_url", "image_url": {"url": self._image_ref(item)}}
            )
        if not blocks:
            raise MMEmbeddingError("输入为空（既无文本也无图片）")
        return blocks

    def _image_ref(self, item: MediaItem) -> str:
        if self.image_transport == "url":
            if not item.image_url:
                raise MMEmbeddingError("image_transport=url 但图片没有可访问的 URL")
            return item.image_url
        if not item.image_bytes:
            raise MMEmbeddingError("image_transport=data_url 但图片字节缺失")
        mime = item.image_mime or "image/jpeg"
        encoded = base64.b64encode(item.image_bytes).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    # ------------------------------------------------------------------ Gemini
    async def _embed_gemini(self, batch: List[MediaItem]) -> List[List[float]]:
        base = self.endpoint or GEMINI_DEFAULT_BASE
        if base.endswith("/embeddings"):
            base = base.rsplit("/embeddings", 1)[0]
        model_path = self.model_name if self.model_name.startswith("models/") else f"models/{self.model_name}"
        url = f"{base}/{model_path}:batchEmbedContents"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key

        requests = []
        for item in batch:
            parts: List[dict] = []
            if item.text:
                parts.append({"text": item.text})
            if item.image_bytes:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": item.image_mime or "image/jpeg",
                            "data": base64.b64encode(item.image_bytes).decode("ascii"),
                        }
                    }
                )
            if not parts:
                raise MMEmbeddingError("输入为空（既无文本也无图片）")
            requests.append({"model": model_path, "content": {"parts": parts}})

        payload = await self._post(url, headers, {"requests": requests})
        return self._extract_vectors(payload, expected=len(batch))

    # ------------------------------------------------------------------ 公共
    async def _post(self, url: str, headers: dict, body: dict) -> dict:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2 ** attempt, 10))
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    return resp.json()
                detail = resp.text[:300]
                if resp.status_code in (408, 429) or resp.status_code >= 500:
                    raise MMEmbeddingError(f"HTTP {resp.status_code}: {detail}")
                raise MMEmbeddingError(
                    f"嵌入请求失败 HTTP {resp.status_code}: {detail}"
                )
            except (httpx.HTTPError, MMEmbeddingError) as exc:
                last_error = exc
                logger.warning(
                    f"多模态嵌入请求失败（第 {attempt + 1}/{self.max_retries + 1} 次）: {exc}"
                )
        raise MMEmbeddingError(f"嵌入请求重试后仍失败：{last_error}")

    @staticmethod
    def _extract_vectors(payload: dict, expected: int) -> List[List[float]]:
        """兼容 OpenAI / Gemini / 常见网关的返回形状"""
        entries = payload.get("data") or payload.get("embeddings") or payload.get("results")
        if entries is None and "vectors" in payload:
            entries = payload["vectors"]
        if not isinstance(entries, list):
            raise MMEmbeddingError(f"无法识别的嵌入响应：{str(payload)[:200]}")

        vectors: List[List[float]] = []
        for entry in entries:
            value = entry
            if isinstance(entry, dict):
                value = (
                    entry.get("embedding")
                    or entry.get("values")
                    or entry.get("vector")
                )
                if isinstance(value, dict):
                    value = value.get("values") or value.get("embedding")
            if not isinstance(value, list) or not value:
                raise MMEmbeddingError(f"嵌入响应缺少向量：{str(entry)[:200]}")
            vectors.append([float(x) for x in value])

        if expected and len(vectors) != expected:
            raise MMEmbeddingError(
                f"嵌入返回条数不匹配：请求 {expected} 条，返回 {len(vectors)} 条"
            )
        return vectors
