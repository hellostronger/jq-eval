# RAG系统管理路由
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel
import logging

from ...core.database import get_db
from ...core.utc_datetime import UTCDatetime
from ...models import RAGSystem, RAGSystemType, Model, ApiIngestTask
from ._common import commit_delete, validate_upload_size
from app.core.exceptions import format_error

router = APIRouter()
logger = logging.getLogger(__name__)


async def _prepare_direct_llm_config(
    connection_config: Dict[str, Any],
    db: AsyncSession
) -> Dict[str, Any]:
    """为直连LLM类型准备完整的连接配置（从数据库获取API Key）"""
    llm_model_id = connection_config.get("llm_model_id")
    if not llm_model_id:
        return connection_config

    try:
        result = await db.execute(select(Model).where(Model.id == UUID(llm_model_id)))
        model = result.scalar_one_or_none()
        if not model:
            logger.warning(f"LLM模型 {llm_model_id} 不存在")
            return connection_config

        # 使用模型配置覆盖connection_config中的API信息
        config = connection_config.copy()
        config["api_endpoint"] = model.endpoint
        config["api_key"] = model.api_key_encrypted or ""
        config["model_name"] = model.model_name or model.name
        config["provider"] = connection_config.get("provider") or model.provider or "openai"

        # 合并参数
        if model.params:
            config["temperature"] = connection_config.get("temperature") or model.params.get("temperature", 0.7)
            config["max_tokens"] = connection_config.get("max_tokens") or model.params.get("max_tokens", 2048)
            # 额外请求参数：调用方配置可覆盖模型默认
            extra = dict(model.params.get("extra_params") or {})
            extra.update(connection_config.get("extra_params") or {})
            if extra:
                config["extra_params"] = extra

        return config
    except Exception as e:
        logger.error(f"获取LLM模型配置失败: {e}")
        return connection_config


# Pydantic Schemas
class RAGSystemCreate(BaseModel):
    name: str
    system_type: str
    description: Optional[str] = None
    connection_config: Dict[str, Any]
    llm_config: Optional[Dict[str, Any]] = None
    retrieval_config: Optional[Dict[str, Any]] = None


class RAGSystemResponse(BaseModel):
    id: UUID
    name: str
    system_type: str
    description: Optional[str]
    connection_config: Dict[str, Any] = {}
    llm_config: Optional[Dict[str, Any]] = None
    retrieval_config: Optional[Dict[str, Any]] = None
    status: str
    health_status: Optional[str]
    total_calls: int
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class QueryRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    contexts: Optional[List[str]] = None


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    space_id: Optional[str] = None


class ApiIngestTaskResponse(BaseModel):
    id: UUID
    rag_system_id: UUID
    dataset_id: Optional[UUID] = None
    remote_kb_id: Optional[str] = None
    remote_kb_name: Optional[str] = None
    remote_chat_id: Optional[str] = None
    status: str
    stage: Optional[str] = None
    progress: int = 0
    error: Optional[str] = None
    total_files: int = 0
    processed_files: int = 0
    files: List[Dict[str, Any]] = []
    config: Dict[str, Any] = {}
    created_at: Optional[UTCDatetime] = None
    started_at: Optional[UTCDatetime] = None
    completed_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


def _build_connector(rag_system: RAGSystem):
    from ...services.api_ingest import create_connector

    try:
        return create_connector(rag_system.system_type, rag_system.connection_config or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=format_error(exc))


@router.get("/types")
async def get_system_types(db: AsyncSession = Depends(get_db)):
    """获取支持的RAG系统类型"""
    result = await db.execute(
        select(RAGSystemType).where(RAGSystemType.is_active == True).order_by(RAGSystemType.sort_order)
    )
    types = result.scalars().all()
    return [{
        "type_code": t.type_code,
        "display_name": t.display_name,
        "description": t.description,
        "connection_schema": t.connection_schema,
        "capabilities": t.capabilities,
        "api_doc_url": t.api_doc_url
    } for t in types]


@router.get("/llm-models")
async def get_llm_models(db: AsyncSession = Depends(get_db)):
    """获取可用的LLM模型列表（用于直连LLM类型）"""
    result = await db.execute(
        select(Model).where(Model.model_type == "llm", Model.status == "active")
    )
    models = result.scalars().all()
    return [{
        "id": str(m.id),
        "name": m.name,
        "provider": m.provider,
        "model_name": m.model_name,
        "endpoint": m.endpoint,
        # 不返回完整的API Key，只返回确认存在
        "has_api_key": bool(m.api_key_encrypted),
        "params": m.params,
    } for m in models]


@router.post("", response_model=RAGSystemResponse)
async def create_rag_system(
    data: RAGSystemCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建RAG系统配置"""
    rag_system = RAGSystem(
        name=data.name,
        system_type=data.system_type,
        description=data.description,
        connection_config=data.connection_config,
        llm_config=data.llm_config or {},
        retrieval_config=data.retrieval_config or {}
    )
    db.add(rag_system)
    await db.commit()
    await db.refresh(rag_system)
    return rag_system


@router.get("", response_model=List[RAGSystemResponse])
async def list_rag_systems(
    system_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取RAG系统列表"""
    query = select(RAGSystem)
    if system_type:
        query = query.where(RAGSystem.system_type == system_type)
    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# API 全链路接入：能力查询 / 知识库 / 入库任务
# 注意：静态路径必须声明在 /{system_id} 之前，否则会被当成 UUID 解析
# ---------------------------------------------------------------------------
@router.get("/ingest-types")
async def get_ingest_types():
    """获取支持 API 全链路接入的系统类型及能力（含未实测标记）"""
    from ...services.api_ingest import list_connector_types

    return list_connector_types()


@router.get("/{system_id}/ingest/capabilities")
async def get_ingest_capabilities(
    system_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """查询某个 RAG 系统支持的入库/解析/分片能力"""
    rag_system = await db.get(RAGSystem, system_id)
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")
    connector = _build_connector(rag_system)
    return connector.get_info()


@router.get("/{system_id}/knowledge-bases")
async def list_remote_knowledge_bases(
    system_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """列出被测系统的远端知识库"""
    from ...services.api_ingest import ConnectorError

    rag_system = await db.get(RAGSystem, system_id)
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")
    connector = _build_connector(rag_system)
    try:
        items = await connector.list_knowledge_bases()
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=format_error(exc))
    return {
        "items": [{"id": kb.id, "name": kb.name} for kb in items],
        "capabilities": connector.capabilities.as_dict(),
    }


@router.post("/{system_id}/knowledge-bases")
async def create_remote_knowledge_base(
    system_id: UUID,
    data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db)
):
    """在被测系统创建知识库"""
    from ...services.api_ingest import ConnectorError

    rag_system = await db.get(RAGSystem, system_id)
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")
    connector = _build_connector(rag_system)
    try:
        kb = await connector.create_knowledge_base(
            data.name,
            description=data.description,
            space_id=data.space_id,
        )
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=format_error(exc))
    return {"id": kb.id, "name": kb.name}


@router.post("/{system_id}/ingest", response_model=ApiIngestTaskResponse)
async def start_api_ingest(
    system_id: UUID,
    files: List[UploadFile] = File(..., description="待入库的原始文档"),
    dataset_name: Optional[str] = Form(None),
    kb_id: Optional[str] = Form(None, description="已有知识库 ID；为空则新建"),
    new_kb_name: Optional[str] = Form(None),
    space_id: Optional[str] = Form(None, description="Coze 建库需要的空间 ID"),
    test_size: int = Form(10),
    llm_model_id: Optional[str] = Form(None),
    embedding_model_id: Optional[str] = Form(None),
    auto_generate: bool = Form(True, description="是否基于远端分片生成问答"),
    auto_invoke: bool = Form(False, description="入库完成后是否自动发起调用批次"),
    parse_timeout: float = Form(1800),
    db: AsyncSession = Depends(get_db),
):
    """上传原始文档到被测系统，解析后生成/导入评测数据集（异步任务）"""
    from ...services.api_ingest import ConnectorError
    from ...services.storage.minio_service import get_minio_service
    from ...tasks.api_ingest_tasks import api_ingest_task

    rag_system = await db.get(RAGSystem, system_id)
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    connector = _build_connector(rag_system)
    if not connector.capabilities.upload_documents:
        raise HTTPException(
            status_code=400,
            detail=f"{connector.display_name} 不支持通过 API 上传文档",
        )

    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        validate_upload_size(upload)

    # 先建任务拿到 ID，MinIO 对象按任务归档，便于排查和清理
    batch_key = uuid4().hex
    minio = get_minio_service()
    file_meta: List[Dict[str, Any]] = []
    for upload in files:
        result = await minio.upload_file(
            bucket="documents",
            file_data=upload.file,
            file_name=f"api-ingest/{batch_key}/{upload.filename}",
            content_type=upload.content_type,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=f"保存原始文件 {upload.filename} 失败：{result.get('error')}",
            )
        file_meta.append(
            {
                "name": upload.filename,
                "size": result.get("size"),
                "content_type": upload.content_type,
                "object_name": result.get("object_name"),
                "status": "pending",
            }
        )

    config: Dict[str, Any] = {
        "rag_system_type": rag_system.system_type,
        "dataset_name": dataset_name,
        "kb_id": kb_id,
        "new_kb_name": new_kb_name,
        "space_id": space_id,
        "test_size": test_size,
        "llm_model_id": llm_model_id,
        "embedding_model_id": embedding_model_id,
        "auto_generate": auto_generate,
        "auto_invoke": auto_invoke,
        "parse_timeout": parse_timeout,
    }

    task = ApiIngestTask(
        rag_system_id=rag_system.id,
        status="pending",
        stage="queued",
        total_files=len(file_meta),
        files=file_meta,
        config=config,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    try:
        celery_task = api_ingest_task.delay(str(task.id))
        task.celery_task_id = celery_task.id
        await db.commit()
        await db.refresh(task)
    except Exception as exc:
        task.status = "failed"
        task.error = f"任务队列不可用：{format_error(exc)}"
        await db.commit()
        raise HTTPException(status_code=503, detail=task.error)

    return task


@router.get("/{system_id}/ingest-tasks", response_model=List[ApiIngestTaskResponse])
async def list_api_ingest_tasks(
    system_id: UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """列出某个 RAG 系统的入库任务"""
    result = await db.execute(
        select(ApiIngestTask)
        .where(ApiIngestTask.rag_system_id == system_id)
        .order_by(ApiIngestTask.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    return result.scalars().all()


@router.get("/ingest-tasks/{task_id}", response_model=ApiIngestTaskResponse)
async def get_api_ingest_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取入库任务状态"""
    task = await db.get(ApiIngestTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="入库任务不存在")
    return task


@router.get("/{system_id}", response_model=RAGSystemResponse)
async def get_rag_system(
    system_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取RAG系统详情"""
    result = await db.execute(select(RAGSystem).where(RAGSystem.id == system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")
    return rag_system


@router.put("/{system_id}", response_model=RAGSystemResponse)
async def update_rag_system(
    system_id: UUID,
    data: RAGSystemCreate,
    db: AsyncSession = Depends(get_db)
):
    """更新RAG系统配置"""
    result = await db.execute(select(RAGSystem).where(RAGSystem.id == system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    rag_system.name = data.name
    rag_system.system_type = data.system_type
    rag_system.description = data.description
    rag_system.connection_config = data.connection_config
    rag_system.llm_config = data.llm_config or {}
    rag_system.retrieval_config = data.retrieval_config or {}

    await db.commit()
    await db.refresh(rag_system)
    return rag_system


@router.delete("/{system_id}")
async def delete_rag_system(
    system_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除RAG系统配置"""
    result = await db.execute(select(RAGSystem).where(RAGSystem.id == system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    await db.delete(rag_system)
    await commit_delete(db, "该 RAG 系统已被调用批次引用，无法删除")
    return {"message": "删除成功"}


@router.post("/{system_id}/query")
async def query_rag_system(
    system_id: UUID,
    data: QueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """查询RAG系统"""
    from ...services.adapters import AdapterFactory

    result = await db.execute(select(RAGSystem).where(RAGSystem.id == system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    try:
        # 为直连LLM类型准备完整配置
        config = rag_system.connection_config
        if rag_system.system_type == "direct_llm":
            config = await _prepare_direct_llm_config(config, db)

        adapter = AdapterFactory.create(
            rag_system.system_type,
            config
        )
        response = await adapter.query(
            question=data.question,
            conversation_id=data.conversation_id,
            contexts=data.contexts
        )
        return {
            "answer": response.answer,
            "contexts": response.contexts,
            "response_time": response.response_time,
            "success": response.success,
            "error": response.error
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询RAG系统 {system_id} 失败: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=format_error(e))


@router.post("/{system_id}/health")
async def health_check(
    system_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """健康检查"""
    from ...services.adapters import AdapterFactory

    result = await db.execute(select(RAGSystem).where(RAGSystem.id == system_id))
    rag_system = result.scalar_one_or_none()
    if not rag_system:
        raise HTTPException(status_code=404, detail="RAG系统不存在")

    try:
        # 为直连LLM类型准备完整配置
        config = rag_system.connection_config
        if rag_system.system_type == "direct_llm":
            config = await _prepare_direct_llm_config(config, db)

        adapter = AdapterFactory.create(
            rag_system.system_type,
            config
        )
        is_healthy = await adapter.health_check()

        rag_system.health_status = "healthy" if is_healthy else "unhealthy"
        rag_system.health_check_at = datetime.utcnow()
        await db.commit()

        return {
            "system_id": str(system_id),
            "health_status": rag_system.health_status,
            "checked_at": rag_system.health_check_at
        }
    except HTTPException:
        raise
    except Exception as e:
        rag_system.health_status = "unhealthy"
        await db.commit()
        logger.error(f"RAG系统 {system_id} 健康检查异常: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=format_error(e))