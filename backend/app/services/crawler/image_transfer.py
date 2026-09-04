# 文章图片转存服务：下载原文图片上传到 MinIO，替换正文中的图片URL
import io
import hashlib
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from minio import Minio

from app.core.config import settings

logger = logging.getLogger(__name__)

# 图片URL提取：匹配 markdown 图片 ![alt](url) 和裸 URL
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
IMG_TAG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)

# 跳过的资源：base64 内联、data URI、过小的占位图
SKIP_URL_PREFIXES = ("data:", "blob:")

# 独立MinIO服务实例（不复用minio_service全局实例，bucket策略不同）
_client: Optional[Minio] = None

BUCKET = "hot-news"
# 公开访问的基础URL（bucket已设置匿名只读策略）
PUBLIC_BASE = f"http://{settings.MINIO_HOST}:{settings.MINIO_PORT}/{BUCKET}"

# 图片最大 20MB，防止异常大文件
MAX_IMAGE_SIZE = 20 * 1024 * 1024


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


def ensure_bucket() -> bool:
    """确保 hot-news bucket 存在且匿名可读"""
    try:
        client = _get_client()
        if not client.bucket_exists(BUCKET):
            client.make_bucket(BUCKET)
            logger.info(f"Created bucket: {BUCKET}")
        return True
    except Exception as e:
        logger.warning(f"确保 bucket 失败: {e}")
        return False


def _ext_from_content_type(content_type: str) -> str:
    """根据 Content-Type 推断扩展名"""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "image/avif": ".avif",
    }
    ct = (content_type or "").split(";")[0].strip().lower()
    return mapping.get(ct, ".jpg")


def _object_name(url: str, content_type: str) -> str:
    """根据图片URL生成稳定的对象路径：同URL同对象名，避免重复存储"""
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    ext = _ext_from_content_type(content_type)
    # 保留原文件名最后一段便于辨识（去掉query）
    path = urlparse(url).path
    original = path.rsplit("/", 1)[-1][:40] if path else ""
    original = re.sub(r"[^A-Za-z0-9._-]", "", original)
    # 原文件名已带图片扩展名则直接用，否则补上推断的扩展名
    if original and re.search(r"\.(jpe?g|png|gif|webp|svg|bmp|avif)$", original, re.I):
        return f"{digest}/{original}"
    return f"{digest}/{original or 'image'}{ext}"


async def _download_image(client: httpx.AsyncClient, url: str) -> Optional[Tuple[bytes, str]]:
    """下载图片，返回 (内容, content_type)；失败返回 None"""
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        # 只处理真正的图片
        if content_type and not content_type.startswith("image/"):
            return None
        if len(resp.content) == 0 or len(resp.content) > MAX_IMAGE_SIZE:
            return None
        return resp.content, content_type
    except Exception as e:
        logger.debug(f"图片下载失败: {url}, {e}")
        return None


def _upload_image(content: bytes, object_name: str, content_type: str) -> bool:
    """上传图片到 MinIO"""
    try:
        client = _get_client()
        client.put_object(
            bucket_name=BUCKET,
            object_name=object_name,
            data=io.BytesIO(content),
            length=len(content),
            content_type=content_type or "image/jpeg",
        )
        return True
    except Exception as e:
        logger.warning(f"图片上传MinIO失败: {object_name}, {e}")
        return False


async def transfer_article_images(content: str) -> Tuple[str, int]:
    """转存正文中的图片到 MinIO，替换为 MinIO URL

    处理 markdown 图片语法 ![alt](url)；裸URL不处理（无法区分是否为图片链接）

    Returns:
        (新内容, 成功转存的图片数)
    """
    if not content:
        return content, 0

    matches = MARKDOWN_IMAGE_RE.findall(content)
    if not matches:
        return content, 0

    # 去重，保持顺序
    seen = set()
    urls = []
    for _, url in matches:
        if url not in seen and not url.startswith(SKIP_URL_PREFIXES):
            if url.startswith("http"):
                seen.add(url)
                urls.append(url)

    if not urls:
        return content, 0

    transferred = 0
    url_map = {}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }) as client:
        for url in urls:
            result = await _download_image(client, url)
            if result is None:
                continue
            data, content_type = result
            object_name = _object_name(url, content_type)
            if _upload_image(data, object_name, content_type):
                url_map[url] = f"{PUBLIC_BASE}/{object_name}"
                transferred += 1

    if url_map:
        for old, new in url_map.items():
            content = content.replace(old, new)

    return content, transferred
