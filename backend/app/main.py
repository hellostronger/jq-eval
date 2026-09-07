# FastAPI 主入口
import signal
import sys
import logging
from contextlib import asynccontextmanager
from dataclasses import is_dataclass, asdict
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder as _fastapi_jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .core import settings, init_db, close_db
from .core.database import AsyncSessionLocal
from .api.v1 import api_router
from .services.crawler.preset_sources import init_preset_sources
from .services.preset_tags import init_preset_tags

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------------------------------
# 时间序列化：数据库统一存 naive UTC，序列化时补 Z 后缀，
# 前端 new Date() 才能正确换算为本地时间（否则差 8 小时）
# ---------------------------------------------------------------------------

def _encode_utc(obj, **kwargs):
    """jsonable_encoder 的时区增强版：递归遍历结构，
    把 naive datetime 视为 UTC 补 tzinfo 后编码为 ISO 字符串"""
    if isinstance(obj, datetime):
        aware = obj.replace(tzinfo=timezone.utc) if obj.tzinfo is None else obj
        return _fastapi_jsonable_encoder(aware, **kwargs)
    if isinstance(obj, dict):
        return {k: _encode_utc(v, **kwargs) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_encode_utc(v, **kwargs) for v in obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return _encode_utc(asdict(obj), **kwargs)
    if isinstance(obj, BaseModel):
        # 先转 dict 再递归，保证模型字段里的 naive datetime 也补时区
        return _encode_utc(obj.model_dump(mode="python"), **kwargs)
    return _fastapi_jsonable_encoder(obj, **kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    await init_db()

    # 初始化预设RSS源
    async with AsyncSessionLocal() as db:
        await init_preset_sources(db)
        await init_preset_tags(db)

    print(f"[OK] {settings.APP_NAME} v{settings.APP_VERSION} 启动成功")
    print(f"[INFO] 环境: {settings.APP_ENV}")
    print(f"[INFO] 数据库: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    print(f"[INFO] 向量库: {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")

    yield

    # 关闭时
    await close_db()
    print(f"[OK] {settings.APP_NAME} 已关闭")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    app = FastAPI(
        title=settings.APP_NAME,
        description="RAG/LLM系统智能评估平台",
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan
    )

    # CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 响应编码：自定义响应类统一走 _encode_utc，保证 naive UTC 时间带时区输出
    class UTCJSONResponse(JSONResponse):
        def render(self, content) -> bytes:
            import json as _json
            encoded = _encode_utc(content)
            return _json.dumps(encoded, ensure_ascii=False, allow_nan=False,
                               indent=None, separators=(",", ":")).encode("utf-8")

    app.default_response_class = UTCJSONResponse

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")

    # 健康检查
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION
        }

    # 根路径
    @app.get("/")
    async def root():
        return {
            "message": f"Welcome to {settings.APP_NAME}",
            "docs": "/docs",
            "health": "/health"
        }

    return app


app = create_app()