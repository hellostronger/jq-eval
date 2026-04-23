# API v1 Module
from fastapi import APIRouter

from . import health, models, rag_systems, datasets, evaluations, metrics, tags, data_sources, files, graph, hot_news, invocations, load_tests, open_source_datasets, doc_explanations, doc_explanation_evaluations, annotation_corrections, prompts

api_router = APIRouter()

# 注册各模块路由
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(rag_systems.router, prefix="/rag-systems", tags=["RAG Systems"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["Metrics"])
api_router.include_router(tags.router, prefix="/tags", tags=["Tags"])
api_router.include_router(data_sources.router, prefix="/data-sources", tags=["Data Sources"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
api_router.include_router(graph.router, tags=["Graph Building"])
api_router.include_router(hot_news.router, prefix="/hot-news", tags=["Hot News"])
api_router.include_router(invocations.router, prefix="/invocations", tags=["Invocations"])
api_router.include_router(load_tests.router, prefix="/load-tests", tags=["Load Tests"])
api_router.include_router(open_source_datasets.router, prefix="/open-source-datasets", tags=["Open Source Datasets"])
api_router.include_router(doc_explanations.router, prefix="/doc-explanations", tags=["Doc Explanations"])
api_router.include_router(doc_explanation_evaluations.router, prefix="/doc-explanation-evaluations", tags=["Doc Explanation Evaluations"])
api_router.include_router(annotation_corrections.router, prefix="/annotation-corrections", tags=["Annotation Corrections"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])

__all__ = ["api_router"]