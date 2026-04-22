# 开源数据集管理路由
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import OpenSourceDataset

router = APIRouter()


# Pydantic Schemas
class OpenSourceDatasetCreate(BaseModel):
    """创建开源数据集请求"""
    name: str
    url: str
    description: Optional[str] = None
    dataset_type: Optional[str] = None
    size_info: Optional[str] = None
    language: Optional[str] = None
    is_public: bool = True
    tags: List[str] = []
    metadata: dict = {}


class OpenSourceDatasetUpdate(BaseModel):
    """更新开源数据集请求"""
    name: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    dataset_type: Optional[str] = None
    size_info: Optional[str] = None
    language: Optional[str] = None
    is_public: Optional[bool] = None
    tags: Optional[List[str]] = None
    metadata: Optional[dict] = None
    status: Optional[str] = None


class OpenSourceDatasetResponse(BaseModel):
    """开源数据集响应"""
    id: UUID
    name: str
    url: str
    description: Optional[str]
    dataset_type: Optional[str]
    size_info: Optional[str]
    language: Optional[str]
    is_public: bool
    tags: List[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OpenSourceDatasetListResponse(BaseModel):
    """开源数据集列表响应（分页）"""
    items: List[OpenSourceDatasetResponse]
    total: int


@router.post("", response_model=OpenSourceDatasetResponse)
async def create_open_source_dataset(
    data: OpenSourceDatasetCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建开源数据集"""
    dataset = OpenSourceDataset(
        name=data.name,
        url=data.url,
        description=data.description,
        dataset_type=data.dataset_type,
        size_info=data.size_info,
        language=data.language,
        is_public=data.is_public,
        tags=data.tags,
        osd_metadata=data.metadata
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("", response_model=OpenSourceDatasetListResponse)
async def list_open_source_datasets(
    page: int = 1,
    size: int = 10,
    dataset_type: Optional[str] = None,
    language: Optional[str] = None,
    status: Optional[str] = None,
    is_public: Optional[bool] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取开源数据集列表（分页）"""
    # 计算偏移量
    skip = (page - 1) * size

    # 构建查询
    query = select(OpenSourceDataset)

    # 过滤条件
    if dataset_type:
        query = query.where(OpenSourceDataset.dataset_type == dataset_type)
    if language:
        query = query.where(OpenSourceDataset.language == language)
    if status:
        query = query.where(OpenSourceDataset.status == status)
    if is_public is not None:
        query = query.where(OpenSourceDataset.is_public == is_public)
    if search:
        query = query.where(
            OpenSourceDataset.name.ilike(f"%{search}%") |
            OpenSourceDataset.description.ilike(f"%{search}%")
        )

    # 查询总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.offset(skip).limit(size).order_by(OpenSourceDataset.created_at.desc())
    result = await db.execute(query)
    items = result.scalars().all()

    return OpenSourceDatasetListResponse(items=items, total=total)


@router.get("/{dataset_id}", response_model=OpenSourceDatasetResponse)
async def get_open_source_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取开源数据集详情"""
    result = await db.execute(
        select(OpenSourceDataset).where(OpenSourceDataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="开源数据集不存在")
    return dataset


@router.put("/{dataset_id}", response_model=OpenSourceDatasetResponse)
async def update_open_source_dataset(
    dataset_id: UUID,
    data: OpenSourceDatasetUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新开源数据集"""
    result = await db.execute(
        select(OpenSourceDataset).where(OpenSourceDataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="开源数据集不存在")

    # 更新字段
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata":
            setattr(dataset, "osd_metadata", value)
        elif field == "tags" and value is not None:
            setattr(dataset, "tags", value)
        else:
            setattr(dataset, field, value)

    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.delete("/{dataset_id}")
async def delete_open_source_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除开源数据集"""
    result = await db.execute(
        select(OpenSourceDataset).where(OpenSourceDataset.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="开源数据集不存在")

    await db.delete(dataset)
    await db.commit()
    return {"message": "删除成功", "dataset_id": str(dataset_id)}