# 模型管理路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Model

router = APIRouter()


# Pydantic Schemas
class ModelCreate(BaseModel):
    name: str
    model_type: str  # llm/embedding/reranker
    provider: Optional[str] = None
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    params: dict = {}
    is_default: bool = False
    dimension: Optional[int] = None
    max_input_length: Optional[int] = None


class ModelResponse(BaseModel):
    id: UUID
    name: str
    model_type: str
    provider: Optional[str]
    endpoint: Optional[str]
    params: dict
    is_default: bool
    status: str
    dimension: Optional[int]
    max_input_length: Optional[int]

    class Config:
        from_attributes = True


class ModelTestRequest(BaseModel):
    test_prompt: Optional[str] = "Hello, this is a test."


@router.post("", response_model=ModelResponse)
async def create_model(
    data: ModelCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建模型配置"""
    model = Model(
        name=data.name,
        model_type=data.model_type,
        provider=data.provider,
        endpoint=data.endpoint,
        # TODO: 加密存储API Key
        api_key_encrypted=data.api_key,
        params=data.params,
        is_default=data.is_default,
        dimension=data.dimension,
        max_input_length=data.max_input_length
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.get("", response_model=List[ModelResponse])
async def list_models(
    model_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取模型列表"""
    query = select(Model)
    if model_type:
        query = query.where(Model.model_type == model_type)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取模型详情"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model


@router.put("/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: UUID,
    data: ModelCreate,
    db: AsyncSession = Depends(get_db)
):
    """更新模型配置"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    model.name = data.name
    model.model_type = data.model_type
    model.provider = data.provider
    model.endpoint = data.endpoint
    model.params = data.params
    model.is_default = data.is_default
    model.dimension = data.dimension
    model.max_input_length = data.max_input_length

    await db.commit()
    await db.refresh(model)
    return model


@router.delete("/{model_id}")
async def delete_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除模型配置"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    await db.delete(model)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{model_id}/test")
async def test_model(
    model_id: UUID,
    data: ModelTestRequest,
    db: AsyncSession = Depends(get_db)
):
    """测试模型连接"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    # TODO: 实现实际的模型测试逻辑
    return {
        "success": True,
        "message": "模型连接测试成功",
        "model_id": str(model_id)
    }