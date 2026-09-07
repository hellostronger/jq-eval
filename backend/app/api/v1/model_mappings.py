# 模型调用映射管理路由
import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...core.utc_datetime import UTCDatetime
from ...models import Model, ModelMapping

router = APIRouter()
logger = logging.getLogger(__name__)


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """掩码 API key，显示前缀和后缀"""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}***{api_key[-4:]}"


def generate_mapping_api_key() -> str:
    """生成映射服务密钥（sk-mx- 前缀 + 48位hex）"""
    return f"sk-mx-{secrets.token_hex(24)}"


# Pydantic Schemas
class MappingCreate(BaseModel):
    name: str
    target_model_id: UUID
    auth_required: bool = True
    log_enabled: bool = False
    status: str = "active"
    description: Optional[str] = None


class MappingUpdate(BaseModel):
    name: Optional[str] = None
    target_model_id: Optional[UUID] = None
    auth_required: Optional[bool] = None
    log_enabled: Optional[bool] = None
    status: Optional[str] = None
    description: Optional[str] = None


class MappingResponse(BaseModel):
    id: UUID
    name: str
    target_model_id: UUID
    target_model_name: Optional[str] = None
    auth_required: bool
    log_enabled: bool
    status: str
    description: Optional[str] = None
    api_key_masked: Optional[str] = None
    api_key: Optional[str] = None  # 仅创建/重置时返回明文
    openai_base_url: Optional[str] = None  # [OI] 客户端 SDK base_url
    anthropic_base_url: Optional[str] = None  # Anthropic 客户端 SDK base_url
    last_called_at: Optional[UTCDatetime] = None
    created_at: UTCDatetime

    class Config:
        from_attributes = True


def mapping_to_response(mapping: ModelMapping, target_model_name: Optional[str] = None,
                        plain_key: Optional[str] = None) -> dict:
    """转换为响应字典"""
    return {
        "id": mapping.id,
        "name": mapping.name,
        "target_model_id": mapping.target_model_id,
        "target_model_name": target_model_name,
        "auth_required": mapping.auth_required,
        "log_enabled": mapping.log_enabled,
        "status": mapping.status,
        "description": mapping.description,
        "api_key_masked": mask_api_key(mapping.api_key),
        "api_key": plain_key,
        "openai_base_url": f"/api/v1/model-mappings/{mapping.id}/v1",
        "anthropic_base_url": f"/api/v1/model-mappings/{mapping.id}",
        "last_called_at": mapping.last_called_at,
        "created_at": mapping.created_at,
    }


async def _get_target_names(db: AsyncSession, target_model_ids: List[UUID]) -> dict:
    """批量查目标模型名称"""
    if not target_model_ids:
        return {}
    result = await db.execute(select(Model.id, Model.name).where(Model.id.in_(target_model_ids)))
    return {row[0]: row[1] for row in result}


async def _validate_target(db: AsyncSession, target_model_id: UUID) -> Model:
    """校验目标模型存在且为 LLM 类型"""
    result = await db.execute(select(Model).where(Model.id == target_model_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="目标模型不存在")
    if target.model_type != "llm":
        raise HTTPException(status_code=400, detail="目标模型必须是 LLM 类型")
    return target


@router.post("", response_model=MappingResponse)
async def create_mapping(data: MappingCreate, db: AsyncSession = Depends(get_db)):
    """创建映射服务（响应中一次性返回明文密钥）"""
    await _validate_target(db, data.target_model_id)

    mapping = ModelMapping(
        name=data.name,
        target_model_id=data.target_model_id,
        api_key=generate_mapping_api_key(),
        auth_required=data.auth_required,
        log_enabled=data.log_enabled,
        status=data.status,
        description=data.description,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)

    names = await _get_target_names(db, [mapping.target_model_id])
    return mapping_to_response(mapping, names.get(mapping.target_model_id), plain_key=mapping.api_key)


@router.get("", response_model=List[MappingResponse])
async def list_mappings(db: AsyncSession = Depends(get_db)):
    """获取映射服务列表"""
    result = await db.execute(select(ModelMapping).order_by(ModelMapping.created_at.desc()))
    mappings = result.scalars().all()

    names = await _get_target_names(db, [m.target_model_id for m in mappings])
    return [mapping_to_response(m, names.get(m.target_model_id)) for m in mappings]


@router.get("/{mapping_id}", response_model=MappingResponse)
async def get_mapping(mapping_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取映射服务详情"""
    result = await db.execute(select(ModelMapping).where(ModelMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射服务不存在")

    names = await _get_target_names(db, [mapping.target_model_id])
    return mapping_to_response(mapping, names.get(mapping.target_model_id))


@router.put("/{mapping_id}", response_model=MappingResponse)
async def update_mapping(mapping_id: UUID, data: MappingUpdate, db: AsyncSession = Depends(get_db)):
    """更新映射服务（不修改密钥）"""
    result = await db.execute(select(ModelMapping).where(ModelMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射服务不存在")

    if data.target_model_id is not None:
        await _validate_target(db, data.target_model_id)
        mapping.target_model_id = data.target_model_id
    if data.name is not None:
        mapping.name = data.name
    if data.auth_required is not None:
        mapping.auth_required = data.auth_required
    if data.log_enabled is not None:
        mapping.log_enabled = data.log_enabled
    if data.status is not None:
        if data.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status 只能是 active/disabled")
        mapping.status = data.status
    if data.description is not None:
        mapping.description = data.description

    await db.commit()
    await db.refresh(mapping)

    names = await _get_target_names(db, [mapping.target_model_id])
    return mapping_to_response(mapping, names.get(mapping.target_model_id))


@router.post("/{mapping_id}/reset-key")
async def reset_mapping_key(mapping_id: UUID, db: AsyncSession = Depends(get_db)):
    """重置映射服务密钥（返回新明文密钥）"""
    result = await db.execute(select(ModelMapping).where(ModelMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射服务不存在")

    mapping.api_key = generate_mapping_api_key()
    await db.commit()
    return {"api_key": mapping.api_key}


@router.delete("/{mapping_id}")
async def delete_mapping(mapping_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除映射服务"""
    result = await db.execute(select(ModelMapping).where(ModelMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射服务不存在")

    await db.delete(mapping)
    await db.commit()
    return {"message": "删除成功"}
