# 健康检查路由
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from redis import asyncio as aioredis

from ...core.database import async_engine
from ...core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# 单个依赖探针的最长等待（秒）。端口"拒绝连接"毫秒级返回，但被防火墙 DROP 的
# 主机会让 TCP 连接挂到系统超时（分钟级）——就绪探针绝不能比被探测的服务更慢。
PROBE_TIMEOUT = 10


@router.get("/health")
async def health_check():
    """存活检查（liveness）：仅表明进程可响应，不探测依赖——
    中间件抖动时应让容器存活、由 /ready 决定摘流，避免误杀重启"""
    return {"status": "healthy"}


def _probe_milvus():
    """pymilvus 是同步 SDK，必须放线程池执行（见 _ready 注释）。
    失败路径也必须 disconnect：alias 泄漏后，下次 connect 会因 alias 已存在报错，
    一次瞬时故障会被固化成永久 unhealthy"""
    from pymilvus import connections, utility
    connections.connect(
        alias="health_check",
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
    )
    try:
        utility.list_collections(using="health_check")
    finally:
        connections.disconnect("health_check")


def _probe_minio():
    from minio import Minio
    client = Minio(
        f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )
    client.list_buckets()


@router.get("/ready")
async def readiness_check():
    """就绪检查 - 检查所有中间件连接状态

    任一依赖降级时返回 HTTP 503：就绪探针若恒 200，负载均衡/编排会照常放流，
    /ready 语义失效。响应体在两种状态下结构一致（前端从 503 的 body 渲染分项状态）。
    """
    services = {}

    # 检查PostgreSQL
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        services["database"] = {"status": "healthy", "type": "PostgreSQL"}
    except Exception as e:
        services["database"] = {"status": "unhealthy", "error": str(e)}

    # 检查Redis（短超时防止探针拖慢整个检查；finally 保证失败路径也关闭连接）
    redis = None
    try:
        redis = aioredis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
        )
        await redis.ping()
        services["redis"] = {"status": "healthy"}
    except Exception as e:
        services["redis"] = {"status": "unhealthy", "error": str(e)}
    finally:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:
                pass

    # Milvus/MinIO 为同步 SDK：中间件失联时的 TCP 连接会挂起数十秒，
    # 直接在 async 端点里调用会阻塞整个事件循环（健康检查反而拖垮正常服务），
    # 必须 run_in_threadpool 卸载；wait_for 再兜底防止线程被防火墙黑洞永久挂起。
    # （超时后线程本身无法强杀，可能短暂滞留——对探针接口是两害相权的取舍）
    for name, probe in (("milvus", _probe_milvus), ("minio", _probe_minio)):
        try:
            await asyncio.wait_for(run_in_threadpool(probe), timeout=PROBE_TIMEOUT)
            services[name] = {"status": "healthy"}
        except asyncio.TimeoutError:
            services[name] = {"status": "unhealthy", "error": f"探针超时（>{PROBE_TIMEOUT}s）"}
        except Exception as e:
            services[name] = {"status": "unhealthy", "error": str(e)}

    all_healthy = all(s.get("status") == "healthy" for s in services.values())
    body = {"status": "ready" if all_healthy else "degraded", "services": services}
    if not all_healthy:
        return JSONResponse(status_code=503, content=body)
    return body
