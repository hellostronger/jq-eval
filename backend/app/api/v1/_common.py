# 路由层通用小工具
import logging
from typing import Any, Callable, Optional, Type

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.base import BaseModel as DBBaseModel

logger = logging.getLogger(__name__)

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


async def delete_or_404(db: AsyncSession, model: Type[DBBaseModel], obj_id, detail: str):
    """按主键删除对象，不存在则抛 404（删除后由调用方或 get_db 依赖统一 commit）"""
    obj = await get_or_404(db, model, obj_id, detail)
    await db.delete(obj)
    return obj


async def commit_delete(db: AsyncSession, referenced_detail: str):
    """提交当前事务；若删除触发外键引用违例，回滚并把 IntegrityError 转 400。

    FK 违例在 flush（commit 时）才暴露，直接抛会是 500；这里回滚 session
    （否则残留 needs-rollback 会污染 get_db 依赖的收尾 commit）并返回可读 400。
    调用方需已完成 db.delete(...)。
    """
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=referenced_detail)


async def start_task(
    db: AsyncSession,
    obj,
    dispatch: Callable[[], Any],
    *,
    status_attr: str = "status",
    running_value: Any = "running",
    fallback_value: Optional[Any] = None,
):
    """统一的"置运行中 → 派发 Celery 任务"封装。

    先提交 running，再派发；若派发失败（broker 不可达等）把状态回滚并抛 503，
    避免任务对象永久停留在 running。返回 Celery AsyncResult。

    注意：running 必须在 dispatch 之前落库——若先 dispatch 再置 running，
    秒级完成的 worker 写入的 completed 会被随后的 running 覆盖，状态永久卡死。
    fallback_value 缺省时恢复为进入前的原状态。
    """
    original_value = getattr(obj, status_attr)
    setattr(obj, status_attr, running_value)
    await db.commit()
    try:
        return dispatch()
    except Exception as e:
        rollback_value = fallback_value if fallback_value is not None else original_value
        logger.error(f"任务派发失败，状态回滚为 {rollback_value}: {type(e).__name__}: {e}")
        setattr(obj, status_attr, rollback_value)
        await db.commit()
        raise HTTPException(status_code=503, detail=f"任务队列不可用，启动失败：{e}")
