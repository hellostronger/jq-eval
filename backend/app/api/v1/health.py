# 健康检查路由
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from redis import asyncio as aioredis
import httpx

from ...core.database import async_engine
from ...core.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check():
    """就绪检查 - 检查所有中间件连接状态"""
    services = {}

    # 检查PostgreSQL
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        services["database"] = {"status": "healthy", "type": "PostgreSQL"}
    except Exception as e:
        services["database"] = {"status": "unhealthy", "error": str(e)}

    # 检查Redis
    try:
        redis = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
        await redis.close()
        services["redis"] = {"status": "healthy"}
    except Exception as e:
        services["redis"] = {"status": "unhealthy", "error": str(e)}

    # 检查Milvus (通过pymilvus)
    try:
        from pymilvus import connections, utility
        connections.connect(
            alias="health_check",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT
        )
        utility.list_collections(using="health_check")
        connections.disconnect("health_check")
        services["milvus"] = {"status": "healthy"}
    except Exception as e:
        services["milvus"] = {"status": "unhealthy", "error": str(e)}

    # 检查MinIO
    try:
        from minio import Minio
        minio_client = Minio(
            f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        minio_client.list_buckets()
        services["minio"] = {"status": "healthy"}
    except Exception as e:
        services["minio"] = {"status": "unhealthy", "error": str(e)}

    # 判断整体状态
    all_healthy = all(s.get("status") == "healthy" for s in services.values())

    return {
        "status": "ready" if all_healthy else "degraded",
        "services": services
    }