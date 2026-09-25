# 健康检查和清理任务
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
import logging
from sqlalchemy import text

from app.core.celery_app import celery_app
from app.tasks._common import run_async
from app.core.database import get_db_context
from app.core.config import settings
from app.models.evaluation import EvaluationStatus
from app.models.sync import SyncTaskStatus
from app.core.exceptions import format_error

logger = logging.getLogger(__name__)


@celery_app.task(name="health_check_task")
def health_check_task() -> Dict[str, Any]:
    """系统健康检查（Beat 每 15 分钟调度；组件降级时输出 WARNING 到 worker 日志做预警）"""
    result = run_async(_run_health_check())
    if result.get("overall_status") != "healthy":
        degraded = [k for k, v in result["components"].items()
                    if v.get("status") != "healthy"]
        logger.warning(f"定时健康检查发现降级组件: {degraded}")
    return result


async def _run_health_check() -> Dict[str, Any]:
    """异步健康检查"""
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }

    # 检查数据库
    try:
        async with get_db_context() as db:
            await db.execute(text("SELECT 1"))
            results["components"]["database"] = {"status": "healthy", "type": "postgresql"}
    except Exception as e:
        results["components"]["database"] = {"status": "unhealthy", "error": format_error(e)}

    # 检查Redis
    try:
        import redis.asyncio as redis
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True
        )
        await client.ping()
        await client.close()
        results["components"]["redis"] = {"status": "healthy"}
    except Exception as e:
        results["components"]["redis"] = {"status": "unhealthy", "error": format_error(e)}

    # 检查Milvus
    try:
        from app.services.milvus.client import MilvusClient
        client = MilvusClient()
        # 尝试列出collections
        collections = client.list_collections()
        results["components"]["milvus"] = {"status": "healthy", "collections": len(collections)}
    except Exception as e:
        results["components"]["milvus"] = {"status": "unhealthy", "error": format_error(e)}

    # 检查MinIO
    try:
        from minio import Minio
        client = Minio(
            f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False
        )
        buckets = client.list_buckets()
        results["components"]["minio"] = {"status": "healthy", "buckets": len(buckets)}
    except Exception as e:
        results["components"]["minio"] = {"status": "unhealthy", "error": format_error(e)}

    # 统计运行中的任务
    async with get_db_context() as db:
        running_evals = await db.execute(
            text("""
            SELECT COUNT(*) as count FROM evaluations
            WHERE status = :status
            """),
            {"status": EvaluationStatus.RUNNING}
        )
        results["running_evaluations"] = running_evals.fetchone()["count"]

        running_syncs = await db.execute(
            text("""
            SELECT COUNT(*) as count FROM sync_tasks
            WHERE status = :status
            """),
            {"status": SyncTaskStatus.RUNNING}
        )
        results["running_sync_tasks"] = running_syncs.fetchone()["count"]

    # 综合状态
    all_healthy = all(
        c.get("status") == "healthy"
        for c in results["components"].values()
    )
    results["overall_status"] = "healthy" if all_healthy else "degraded"

    return results


@celery_app.task(name="cleanup_task")
def cleanup_task(days: int = 30) -> Dict[str, Any]:
    """清理过期数据"""
    return run_async(_run_cleanup(days))


async def _run_cleanup(days: int) -> Dict[str, Any]:
    """异步清理"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    cleanup_stats = {}

    async with get_db_context() as db:
        # 清理失败的评估任务（超过指定天数）
        failed_evals = await db.execute(
            text("""
            DELETE FROM evaluations
            WHERE status = :status AND created_at < :cutoff
            RETURNING id
            """),
            {"status": EvaluationStatus.FAILED, "cutoff": cutoff_date}
        )
        cleanup_stats["deleted_failed_evaluations"] = len(failed_evals.fetchall())

        # 清理失败的同步任务
        failed_syncs = await db.execute(
            text("""
            DELETE FROM sync_tasks
            WHERE status = :status AND created_at < :cutoff
            RETURNING id
            """),
            {"status": SyncTaskStatus.FAILED, "cutoff": cutoff_date}
        )
        cleanup_stats["deleted_failed_syncs"] = len(failed_syncs.fetchall())

        # 清理旧的临时文件（MinIO）
        try:
            from minio import Minio
            from minio.deleteobjects import DeleteObject

            client = Minio(
                f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=False
            )

            # 删除temp桶中超过指定天数的对象
            # MinIO SDK 返回的 last_modified 是 tz-aware，需与 aware 截止点比较
            cutoff_aware = cutoff_date.replace(tzinfo=timezone.utc)
            objects_to_delete = []
            for obj in client.list_objects("temp", recursive=True):
                if obj.last_modified and obj.last_modified < cutoff_aware:
                    objects_to_delete.append(DeleteObject(obj.object_name))

            if objects_to_delete:
                errors = client.remove_objects("temp", objects_to_delete)
                deleted_count = len(objects_to_delete) - len(list(errors))
                cleanup_stats["deleted_temp_files"] = deleted_count
            else:
                cleanup_stats["deleted_temp_files"] = 0

        except Exception as e:
            cleanup_stats["minio_cleanup_error"] = format_error(e)

        await db.commit()

    cleanup_stats["cutoff_date"] = cutoff_date.isoformat()
    cleanup_stats["timestamp"] = datetime.utcnow().isoformat()

    return cleanup_stats

# 注：曾有 daily_stats_task（无 Beat 调度、无调用方、返回值无人消费的纯死代码），
# 每日统计由 /api/v1/evaluations/daily-stats 在线聚合提供，已删除