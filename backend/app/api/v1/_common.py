# 路由层通用小工具
from typing import Optional, Type

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.base import BaseModel as DBBaseModel


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
