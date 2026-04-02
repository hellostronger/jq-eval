# FastAPI 主入口
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import settings, init_db, close_db
from .api.v1 import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    await init_db()
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