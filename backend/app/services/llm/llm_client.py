# LLM/Embedding 客户端创建
from typing import Optional
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import logging

from app.models.model import Model

logger = logging.getLogger(__name__)


async def create_llm_from_config(model: Model) -> ChatOpenAI:
    """从数据库模型配置创建 LangChain LLM

    Args:
        model: Model 数据库模型实例

    Returns:
        ChatOpenAI 实例
    """
    params = model.params or {}

    return ChatOpenAI(
        model=params.get("model_name") or model.name,
        api_key=model.api_key_encrypted,
        base_url=model.endpoint,
        temperature=params.get("temperature", 0.7),
        max_tokens=params.get("max_tokens", 2048),
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
        model=params.get("model_name") or model.name,
        api_key=model.api_key_encrypted,
        base_url=model.endpoint,
    )


async def create_llm_from_model_id(db: AsyncSession, model_id: UUID) -> Optional[ChatOpenAI]:
    """从模型 ID 创建 LLM

    Args:
        db: 数据库会话
        model_id: 模型 UUID

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

    return await create_llm_from_config(model)


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