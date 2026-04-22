# RAG系统管理路由
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
import logging

from ...core.database import get_db
from ...models import RAGSystem, RAGSystemType, Model

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
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QueryRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    contexts: Optional[List[str]] = None


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
    await db.commit()
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        rag_system.health_status = "unhealthy"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))