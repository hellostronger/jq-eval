# LLM/Embedding 客户端创建
from typing import Optional
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import logging

from app.models.model import Model

logger = logging.getLogger(__name__)


async def create_llm_from_config(model: Model, param_overrides: Optional[dict] = None) -> ChatOpenAI:
    """从数据库模型配置创建 LangChain LLM

    Args:
        model: Model 数据库模型实例
        param_overrides: 调用时覆盖参数（如 extra_params），优先级高于模型配置

    Returns:
        ChatOpenAI 实例
    """
    params = model.params or {}

    # 额外请求参数：模型配置为默认值，调用方可覆盖；顶层透传给 LLM API
    extra_params = dict(params.get("extra_params") or {})
    if param_overrides and param_overrides.get("extra_params"):
        extra_params.update(param_overrides["extra_params"])

    return ChatOpenAI(
        # 真实上游模型名：params.model_name > model.model_name > model.name
        # （model.name 是展示名，可能带 openai/ 等供应商前缀，直接传上游会 404/503）
        model=params.get("model_name") or model.model_name or model.name,
        api_key=model.api_key_encrypted,
        base_url=model.endpoint,
        temperature=params.get("temperature", 0.7),
        max_tokens=params.get("max_tokens", 2048),
        model_kwargs=extra_params,
    )


async def create_embeddings_from_config(model: Model) -> OpenAIEmbeddings:
    """从数据库模型配置创建 Embeddings

    Args:
        model: Model 数据库模型实例

    Returns:
        OpenAIEmbeddings 实例
    """
    params = model.params or {}

    return OpenAIEmbeddings(
        model=params.get("model_name") or model.model_name or model.name,
        api_key=model.api_key_encrypted,
        base_url=model.endpoint,
    )


async def create_llm_from_model_id(db: AsyncSession, model_id: UUID,
                                   param_overrides: Optional[dict] = None) -> Optional[ChatOpenAI]:
    """从模型 ID 创建 LLM

    Args:
        db: 数据库会话
        model_id: 模型 UUID
        param_overrides: 调用时覆盖参数（如 extra_params），优先级高于模型配置

    Returns:
        ChatOpenAI 实例，如果模型不存在则返回 None
    """
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        logger.warning(f"LLM 模型 {model_id} 不存在")
        return None

    if model.model_type != "llm":
        logger.warning(f"模型 {model_id} 不是 LLM 类型")
        return None

    return await create_llm_from_config(model, param_overrides)


async def create_embeddings_from_model_id(db: AsyncSession, model_id: UUID) -> Optional[OpenAIEmbeddings]:
    """从模型 ID 创建 Embeddings

    Args:
        db: 数据库会话
        model_id: 模型 UUID

    Returns:
        OpenAIEmbeddings 实例，如果模型不存在则返回 None
    """
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        logger.warning(f"Embedding 模型 {model_id} 不存在")
        return None

    if model.model_type != "embedding":
        logger.warning(f"模型 {model_id} 不是 Embedding 类型")
        return None

    return await create_embeddings_from_config(model)