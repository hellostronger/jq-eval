# 标签管理路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Tag, EntityTag

router = APIRouter()

# 使用场景枚举
USAGE_SCENARIOS = ["qa_record", "dataset", "invocation_batch"]


# Pydantic Schemas
class TagCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    usage_scenario: str
    sort_order: int = 0


class TagUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class TagResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    color: Optional[str]
    icon: Optional[str]
    usage_scenario: str
    is_builtin: bool
    sort_order: int

    class Config:
        from_attributes = True


class EntityTagCreate(BaseModel):
    entity_type: str
    entity_id: UUID
    tag_id: UUID


class EntityTagResponse(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    tag_id: UUID
    tag: Optional[TagResponse] = None

    class Config:
        from_attributes = True


# ========== 标签管理 API ==========

@router.get("", response_model=List[TagResponse])
async def list_tags(
    usage_scenario: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取标签列表，可按使用场景筛选"""
    query = select(Tag).order_by(Tag.sort_order, Tag.created_at)
    if usage_scenario:
        query = query.where(Tag.usage_scenario == usage_scenario)
    result = await db.execute(query)
    tags = result.scalars().all()
    return [TagResponse.model_validate(t) for t in tags]


@router.get("/scenarios")
async def get_usage_scenarios():
    """获取所有使用场景"""
    return USAGE_SCENARIOS


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取标签详情"""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")
    return TagResponse.model_validate(tag)


@router.post("", response_model=TagResponse)
async def create_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建自定义标签"""
    # 验证使用场景
    if data.usage_scenario not in USAGE_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"无效的使用场景，可选值: {USAGE_SCENARIOS}")

    # 检查名称是否已存在（同一使用场景下）
    result = await db.execute(
        select(Tag).where(
            (Tag.name == data.name) &
            (Tag.usage_scenario == data.usage_scenario)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该使用场景下标签名称已存在")

    tag = Tag(
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        color=data.color,
        icon=data.icon,
        usage_scenario=data.usage_scenario,
        sort_order=data.sort_order,
        is_builtin=False
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: UUID,
    data: TagUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新标签"""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    if tag.is_builtin:
        raise HTTPException(status_code=400, detail="内置标签不可修改")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(tag, key, value)

    await db.commit()
    await db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除标签"""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    if tag.is_builtin:
        raise HTTPException(status_code=400, detail="内置标签不可删除")

    await db.delete(tag)
    await db.commit()
    return {"message": "标签已删除"}


# ========== 实体标签绑定 API ==========

@router.post("/bind", response_model=EntityTagResponse)
async def bind_tag_to_entity(
    data: EntityTagCreate,
    db: AsyncSession = Depends(get_db)
):
    """给实体打标签"""
    # 验证使用场景匹配
    tag_result = await db.execute(
        select(Tag).where(Tag.id == data.tag_id)
    )
    tag = tag_result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    if tag.usage_scenario != data.entity_type:
        raise HTTPException(
            status_code=400,
            detail=f"标签使用场景({tag.usage_scenario})与实体类型({data.entity_type})不匹配"
        )

    # 检查是否已绑定
    existing = await db.execute(
        select(EntityTag).where(
            and_(
                EntityTag.entity_type == data.entity_type,
                EntityTag.entity_id == data.entity_id,
                EntityTag.tag_id == data.tag_id
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该标签已绑定到此实体")

    entity_tag = EntityTag(
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        tag_id=data.tag_id
    )
    db.add(entity_tag)
    await db.commit()
    await db.refresh(entity_tag)

    return EntityTagResponse(
        id=entity_tag.id,
        entity_type=entity_tag.entity_type,
        entity_id=entity_tag.entity_id,
        tag_id=entity_tag.tag_id,
        tag=TagResponse.model_validate(tag)
    )


@router.delete("/unbind")
async def unbind_tag_from_entity(
    entity_type: str,
    entity_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """解除实体标签绑定"""
    result = await db.execute(
        select(EntityTag).where(
            and_(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
                EntityTag.tag_id == tag_id
            )
        )
    )
    entity_tag = result.scalar_one_or_none()
    if not entity_tag:
        raise HTTPException(status_code=404, detail="标签绑定不存在")

    await db.delete(entity_tag)
    await db.commit()
    return {"message": "标签绑定已解除"}


@router.get("/entity/{entity_type}/{entity_id}", response_model=List[TagResponse])
async def get_entity_tags(
    entity_type: str,
    entity_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取实体的所有标签"""
    result = await db.execute(
        select(Tag).join(EntityTag).where(
            and_(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id
            )
        )
    )
    tags = result.scalars().all()
    return [TagResponse.model_validate(t) for t in tags]


@router.post("/entity/{entity_type}/{entity_id}/set")
async def set_entity_tags(
    entity_type: str,
    entity_id: UUID,
    tag_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    """设置实体的标签（替换原有标签）"""
    # 删除原有标签绑定
    await db.execute(
        select(EntityTag).where(
            and_(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id
            )
        )
    )
    # 先查询再删除
    existing = await db.execute(
        select(EntityTag).where(
            and_(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id
            )
        )
    )
    for et in existing.scalars().all():
        await db.delete(et)

    # 添加新标签绑定
    for tag_id in tag_ids:
        tag_result = await db.execute(
            select(Tag).where(Tag.id == tag_id)
        )
        tag = tag_result.scalar_one_or_none()
        if not tag:
            raise HTTPException(status_code=404, detail=f"标签 {tag_id} 不存在")

        if tag.usage_scenario != entity_type:
            raise HTTPException(
                status_code=400,
                detail=f"标签使用场景({tag.usage_scenario})与实体类型({entity_type})不匹配"
            )

        entity_tag = EntityTag(
            entity_type=entity_type,
            entity_id=entity_id,
            tag_id=tag_id
        )
        db.add(entity_tag)

    await db.commit()
    return {"message": "标签已更新", "count": len(tag_ids)}