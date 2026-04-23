# Prompt 管理 API
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models.prompt import PromptVersion, PromptVersionHistory, PromptFramework

router = APIRouter(prefix="/prompts", tags=["Prompt 管理"])


# ========== Schema ==========
class PromptVersionCreate(BaseModel):
    name: str
    content: str
    description: Optional[str] = None
    framework: Optional[str] = None
    parameters: dict = {}
    original_prompt: Optional[str] = None
    optimization_notes: Optional[str] = None
    test_cases: list = []
    tags: list = []
    usage_scenario: Optional[str] = None


class PromptVersionUpdate(BaseModel):
    content: Optional[str] = None
    description: Optional[str] = None
    framework: Optional[str] = None
    parameters: Optional[dict] = None
    optimization_notes: Optional[str] = None
    test_cases: Optional[list] = None
    tags: Optional[list] = None
    usage_scenario: Optional[str] = None


class PromptVersionResponse(BaseModel):
    id: UUID
    name: str
    content: str
    version: int
    description: Optional[str]
    framework: Optional[str]
    parameters: dict
    is_active: bool
    original_prompt: Optional[str]
    optimization_notes: Optional[str]
    test_cases: list
    tags: list
    usage_scenario: Optional[str]
    usage_count: int
    version_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class PromptFrameworkResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    complexity: str
    domain: Optional[str]
    elements: list
    template: Optional[str]
    examples: list
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


# ========== Prompt 版本管理 API ==========
@router.get("", response_model=List[PromptVersionResponse])
async def list_prompts(
    usage_scenario: Optional[str] = None,
    framework: Optional[str] = None,
    tags: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """获取 Prompt 列表"""
    query = select(PromptVersion).where(PromptVersion.is_active == True)

    if usage_scenario:
        query = query.where(PromptVersion.usage_scenario == usage_scenario)
    if framework:
        query = query.where(PromptVersion.framework == framework)

    query = query.order_by(desc(PromptVersion.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{prompt_id}", response_model=PromptVersionResponse)
async def get_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取 Prompt 详情"""
    result = await db.execute(
        select(PromptVersion).where(PromptVersion.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    return prompt


@router.post("", response_model=PromptVersionResponse)
async def create_prompt(
    data: PromptVersionCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建 Prompt"""
    # 检查名称是否已存在
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.name == data.name,
            PromptVersion.is_active == True
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # 已有同名 prompt，创建新版本
        existing.is_active = False
        prompt = PromptVersion(
            name=data.name,
            content=data.content,
            version=existing.version + 1,
            description=data.description,
            framework=data.framework,
            parameters=data.parameters,
            original_prompt=data.original_prompt or data.content,
            optimization_notes=data.optimization_notes,
            test_cases=data.test_cases,
            tags=data.tags,
            usage_scenario=data.usage_scenario,
            version_count=existing.version_count + 1
        )
    else:
        prompt = PromptVersion(
            name=data.name,
            content=data.content,
            version=1,
            description=data.description,
            framework=data.framework,
            parameters=data.parameters,
            original_prompt=data.original_prompt or data.content,
            optimization_notes=data.optimization_notes,
            test_cases=data.test_cases,
            tags=data.tags,
            usage_scenario=data.usage_scenario
        )

    db.add(prompt)

    # 记录历史
    history = PromptVersionHistory(
        prompt_version_id=prompt.id,
        version=prompt.version,
        content=prompt.content,
        change_type="create",
        change_notes="初始版本"
    )
    db.add(history)

    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.put("/{prompt_id}", response_model=PromptVersionResponse)
async def update_prompt(
    prompt_id: UUID,
    data: PromptVersionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新 Prompt（创建新版本）"""
    result = await db.execute(
        select(PromptVersion).where(PromptVersion.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")

    # 创建新版本，旧版本设为非活跃
    prompt.is_active = False

    # 合并更新数据
    update_data = data.model_dump(exclude_unset=True)
    new_content = update_data.pop("content", prompt.content)

    new_prompt = PromptVersion(
        name=prompt.name,
        content=new_content,
        version=prompt.version + 1,
        description=update_data.get("description", prompt.description),
        framework=update_data.get("framework", prompt.framework),
        parameters=update_data.get("parameters", prompt.parameters),
        original_prompt=prompt.original_prompt,
        optimization_notes=update_data.get("optimization_notes", prompt.optimization_notes),
        test_cases=update_data.get("test_cases", prompt.test_cases),
        tags=update_data.get("tags", prompt.tags),
        usage_scenario=update_data.get("usage_scenario", prompt.usage_scenario),
        version_count=prompt.version_count + 1
    )

    db.add(new_prompt)

    # 记录历史
    history = PromptVersionHistory(
        prompt_version_id=new_prompt.id,
        version=new_prompt.version,
        content=new_prompt.content,
        change_type="update",
        change_notes=data.optimization_notes or "手动更新"
    )
    db.add(history)

    await db.commit()
    await db.refresh(new_prompt)
    return new_prompt


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除 Prompt"""
    result = await db.execute(
        select(PromptVersion).where(PromptVersion.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")

    prompt.is_active = False
    await db.commit()
    return {"message": "Prompt 已删除"}


@router.get("/{prompt_id}/history", response_model=List[PromptVersionResponse])
async def get_prompt_history(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取 Prompt 版本历史"""
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.name == (
            select(PromptVersion.name).where(PromptVersion.id == prompt_id)
        ).scalar_subquery())
        .order_by(desc(PromptVersion.version))
    )
    return result.scalars().all()


# ========== Prompt 框架 API ==========
@router.get("/frameworks", response_model=List[PromptFrameworkResponse])
async def list_frameworks(
    complexity: Optional[str] = None,
    domain: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取 Prompt 框架列表"""
    query = select(PromptFramework).where(PromptFramework.is_active == True)

    if complexity:
        query = query.where(PromptFramework.complexity == complexity)
    if domain:
        query = query.where(PromptFramework.domain == domain)

    query = query.order_by(PromptFramework.sort_order, PromptFramework.display_name)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/frameworks/{framework_id}", response_model=PromptFrameworkResponse)
async def get_framework(
    framework_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取框架详情"""
    result = await db.execute(
        select(PromptFramework).where(PromptFramework.id == framework_id)
    )
    framework = result.scalar_one_or_none()
    if not framework:
        raise HTTPException(status_code=404, detail="框架不存在")
    return framework