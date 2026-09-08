# 路由层通用小工具
from typing import Optional, Type

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.base import BaseModel as DBBaseModel

# 上传文件大小上限（MB），防止超大文件耗尽内存/存储
MAX_UPLOAD_SIZE_MB = 50


def validate_upload_size(file: UploadFile, max_mb: int = MAX_UPLOAD_SIZE_MB) -> None:
    """校验上传文件大小，超限抛 413（Starlette 解析表单时已统计 size）"""
    size = getattr(file, "size", None)
    if size is not None and size > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{size / 1024 / 1024:.1f}MB），上限 {max_mb}MB",
        )


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """掩码 API key，显示前缀和后缀"""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}***{api_key[-4:]}"


async def get_or_404(db: AsyncSession, model: Type[DBBaseModel], obj_id, detail: str):
    """按主键取对象，不存在则抛 404"""
    obj = await db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=detail)
    return obj
