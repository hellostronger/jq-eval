# Celery 任务公共工具
import asyncio
from datetime import datetime


def run_async(coro):
    """在同步环境（Celery worker）中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_progress_callback(task):
    """构造批量评估用的进度回调：向 Celery 上报 PROGRESS 状态"""
    def progress_callback(progress, current, total):
        task.update_state(
            state="PROGRESS",
            meta={"progress": progress, "current": current, "total": total}
        )
    return progress_callback


async def mark_task_failed(db, model, obj_id, error: str, logger=None) -> None:
    """任务失败收尾：回滚事务，重取对象并标记 FAILED

    状态按 str 枚举值 "failed" 写入（各任务的 FAILED 枚举成员均为 str 子类）。
    """
    if logger:
        logger.error(f"任务失败: {error}")
    await db.rollback()
    obj = await db.get(model, obj_id)
    if obj:
        obj.status = "failed"
        obj.error = error
        if hasattr(obj, "completed_at"):
            obj.completed_at = datetime.utcnow()
        await db.commit()
