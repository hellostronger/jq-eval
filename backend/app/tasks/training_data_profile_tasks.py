# 训练数据画像异步任务（大数据集路径）
import logging
from typing import Any, Dict
from uuid import UUID

from app.core.celery_app import celery_app
from app.tasks._common import run_async, mark_task_failed, format_error
from app.core.database import get_db_context
from app.models.training_data_profile import TrainingDataProfile
from app.services.training_data.profile_runner import run_profile

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="training_data_profile_task",
                 soft_time_limit=15 * 60, time_limit=20 * 60)
def training_data_profile_task(self, profile_id: str) -> Dict[str, Any]:
    """生成训练数据画像

    Args:
        profile_id: 画像任务ID (UUID字符串格式)
    """
    return run_async(_run_training_data_profile(self, UUID(profile_id)))


async def _run_training_data_profile(task, profile_id: UUID) -> Dict[str, Any]:
    async with get_db_context() as db:
        profile = await db.get(TrainingDataProfile, profile_id)
        if not profile:
            return {"error": f"画像 {profile_id} 不存在"}

        try:
            # 进度同时写 Celery 状态与 DB：前端 /status 轮询读的是 DB 字段
            def on_progress(value: int) -> None:
                task.update_state(state="PROGRESS", meta={"progress": value})

            await run_profile(db, profile, progress_cb=on_progress)
            return {
                "profile_id": str(profile_id),
                "status": profile.status,
                "total_samples": profile.total_samples,
                "format": profile.format,
                "level": profile.level,
            }
        except Exception as e:
            await mark_task_failed(db, TrainingDataProfile, profile_id, format_error(e), logger)
            return {"error": format_error(e)}
