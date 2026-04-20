# API v1 Module
from fastapi import APIRouter

from . import health, models, rag_systems, datasets, evaluations, metrics, data_sources, files, graph, hot_news, invocations

api_router = APIRouter()

# 注册各模块路由
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(rag_systems.router, prefix="/rag-systems", tags=["RAG Systems"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["Metrics"])
api_router.include_router(data_sources.router, prefix="/data-sources", tags=["Data Sources"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
api_router.include_router(graph.router, tags=["Graph Building"])
api_router.include_router(hot_news.router, prefix="/hot-news", tags=["Hot News"])
api_router.include_router(invocations.router, prefix="/invocations", tags=["Invocations"])

__all__ = ["api_router"]