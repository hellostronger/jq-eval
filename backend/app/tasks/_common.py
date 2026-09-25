# Celery 任务公共工具
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


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


async def mark_task_failed(db, model, obj_id, error: str, task_logger=None) -> None:
    """任务失败收尾：回滚事务，重取对象并标记 FAILED

    状态按 str 枚举值 "failed" 写入（各任务的 FAILED 枚举成员均为 str 子类）。

    长任务跑了几分钟后连接可能已被服务端掐断（云端 PG 跨公网），
    用旧 session 落库会二次失败、状态卡 running。失败时换全新会话重试一次。
    """
    if task_logger:
        task_logger.error(f"任务失败: {error}")
    try:
        await db.rollback()
        obj = await db.get(model, obj_id)
        if obj:
            obj.status = "failed"
            obj.error = error
            if hasattr(obj, "completed_at"):
                obj.completed_at = datetime.utcnow()
            await db.commit()
    except Exception as e:
        (task_logger or logger).error(f"失败状态落库异常，换新会话重试: {e}")
        # 旧会话大概率已失效：用全新 engine/session 直接落库
        from app.core.database import get_db_context
        try:
            async with get_db_context() as fresh_db:
                obj = await fresh_db.get(model, obj_id)
                if obj:
                    obj.status = "failed"
                    obj.error = error
                    if hasattr(obj, "completed_at"):
                        obj.completed_at = datetime.utcnow()
                    await fresh_db.commit()
        except Exception as e2:
            (task_logger or logger).error(f"失败状态二次落库仍异常: {e2}")
