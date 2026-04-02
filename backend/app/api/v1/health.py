# 健康检查路由
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check():
    """就绪检查"""
    # TODO: 检查数据库、Redis、Milvus连接状态
    return {
        "status": "ready",
        "services": {
            "database": "connected",
            "redis": "connected",
            "milvus": "connected"
        }
    }