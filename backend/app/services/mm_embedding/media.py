# 多模态评测：图片落地与读取
#
# 评测时模型 API 需要的是图片字节（base64）或可公网访问的 URL。源站 URL 可能
# 失效、zip 里的图片也不能让评测进程反复读压缩包，所以导入时统一转存 MinIO，
# 样本表只保存 object key。对象名由内容哈希决定，重复导入天然去重。
import asyncio
import base64
import hashlib
import io
import logging
import re
from typing import Dict, Optional, Tuple

import httpx

from app.services.storage.minio_service import get_minio_service

logger = logging.getLogger(__name__)

MM_BUCKET = "mm-eval"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGES = 20_000
DOWNLOAD_TIMEOUT = 20.0
UPLOAD_CONCURRENCY = 8

_DATA_URI_RE = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.DOTALL)


def _sniff_image(data: bytes) -> Optional[Tuple[str, str]]:
    """按魔数识别图片类型，返回 (mime, ext)；非图片返回 None"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if data.startswith(b"BM"):
        return "image/bmp", ".bmp"
    return None


async def store_images(
    dataset_id,
    refs: list[str],
    zip_images: Dict[str, bytes],
    image_names: Dict[str, str],
) -> Tuple[Dict[str, str], int]:
    """把样本里出现的图片引用统一转存 MinIO。

    Returns:
        (ref -> object_key, 唯一图片数)
    """
    unique_refs = list(dict.fromkeys(r for r in refs if r))
    if not unique_refs:
        return {}, 0

    semaphore = asyncio.Semaphore(UPLOAD_CONCURRENCY)
    resolved: Dict[str, Tuple[bytes, str, str]] = {}

    async def resolve(ref: str) -> None:
        async with semaphore:
            try:
                data, mime, ext = await _resolve_ref(ref, zip_images, image_names)
            except Exception as exc:
                raise ValueError(f"图片 {ref} 加载失败：{exc}") from exc
            resolved[ref] = (data, mime, ext)

    await asyncio.gather(*(resolve(ref) for ref in unique_refs))

    # 按内容哈希去重：重复引用只上传一次
    digest_to_key: Dict[str, str] = {}
    by_digest: Dict[str, Tuple[bytes, str, str]] = {}
    for data, mime, ext in resolved.values():
        digest = hashlib.sha256(data).hexdigest()
        by_digest.setdefault(digest, (data, mime, ext))

    async def upload(digest: str, payload: Tuple[bytes, str, str]) -> None:
        data, mime, ext = payload
        async with semaphore:
            key = await asyncio.to_thread(_put_object, dataset_id, digest, data, mime, ext)
            digest_to_key[digest] = key

    await asyncio.gather(*(upload(d, p) for d, p in by_digest.items()))

    mapping: Dict[str, str] = {}
    for ref, (data, mime, ext) in resolved.items():
        digest = hashlib.sha256(data).hexdigest()
        mapping[ref] = digest_to_key[digest]
    return mapping, len(by_digest)


async def _resolve_ref(
    ref: str, zip_images: Dict[str, bytes], image_names: Dict[str, str]
) -> Tuple[bytes, str, str]:
    ref = ref.strip()
    if ref.lower().startswith("data:image/"):
        match = _DATA_URI_RE.match(ref)
        if not match:
            raise ValueError("data URI 格式不支持（需 base64）")
        mime = match.group(1)
        try:
            data = base64.b64decode(match.group(2), validate=True)
        except Exception as exc:
            raise ValueError(f"base64 解码失败：{exc}") from exc
        return _validate_image(data, mime, ref)

    if ref.lower().startswith(("http://", "https://")):
        data = await _download(ref)
        return _validate_image(data, None, ref)

    normalized = ref.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    data = zip_images.get(normalized)
    if data is None:
        fallback = image_names.get(normalized.rsplit("/", 1)[-1].lower())
        if fallback:
            data = zip_images.get(fallback)
    if data is None:
        raise ValueError("zip 内未找到该图片（路径需与 jsonl 引用一致）")
    return _validate_image(data, None, ref)


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=DOWNLOAD_TIMEOUT
    ) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            content_type = (resp.headers.get("content-type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                raise ValueError(f"响应不是图片（content-type={content_type}）")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError(f"图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB 上限")
                chunks.append(chunk)
    return b"".join(chunks)


def _validate_image(data: bytes, declared_mime: Optional[str], ref: str) -> Tuple[bytes, str, str]:
    if not data:
        raise ValueError("图片内容为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB 上限")
    sniffed = _sniff_image(data)
    if sniffed is None:
        raise ValueError(f"无法识别的图片格式（{ref}），支持 jpg/png/webp/gif/bmp")
    mime, ext = sniffed
    if declared_mime and declared_mime != mime:
        # 声明与实际不符时以实际为准（源站经常把 png 标成 jpg）
        logger.warning(f"图片 {ref} 声明 {declared_mime} 实际 {mime}，按实际类型处理")
    return data, mime, ext


def _put_object(dataset_id, digest: str, data: bytes, mime: str, ext: str) -> str:
    service = get_minio_service()
    service.ensure_buckets()
    key = f"mm-eval/{dataset_id}/{digest[:2]}/{digest}{ext}"
    service.client.put_object(
        MM_BUCKET, key, io.BytesIO(data), len(data), content_type=mime
    )
    return key


async def load_image(object_key: str) -> bytes:
    """评测时读取图片字节"""

    def _read() -> bytes:
        service = get_minio_service()
        response = service.client.get_object(MM_BUCKET, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(_read)


async def presign_image(object_key: str, expires: int = 3600) -> str:
    def _sign() -> str:
        return get_minio_service().get_presigned_url(MM_BUCKET, object_key, expires)

    return await asyncio.to_thread(_sign)


def mime_from_key(object_key: str) -> str:
    lowered = object_key.lower()
    for ext, mime in (
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".bmp", "image/bmp"),
    ):
        if lowered.endswith(ext):
            return mime
    return "application/octet-stream"


async def delete_dataset_images(dataset_id) -> int:
    """删除某评测集在 MinIO 下的图片（best-effort，失败只记日志）"""

    def _delete() -> int:
        service = get_minio_service()
        prefix = f"mm-eval/{dataset_id}/"
        removed = 0
        try:
            for obj in service.client.list_objects(MM_BUCKET, prefix=prefix, recursive=True):
                service.client.remove_object(MM_BUCKET, obj.object_name)
                removed += 1
        except Exception as exc:
            logger.warning(f"清理评测集 {dataset_id} 图片失败: {exc}")
        return removed

    return await asyncio.to_thread(_delete)
