# 指标市场路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import MetricDefinition, MetricTag

router = APIRouter()


# Pydantic Schemas
class MetricCreate(BaseModel):
    name: str
    display_name: str
    display_name_en: Optional[str] = None
    description: Optional[str] = None
    category: str  # retrieval/generation/quality/performance/custom
    framework: Optional[str] = None
    eval_stage: str = "result"  # process/result
    params_schema: Optional[Dict[str, Any]] = None
    default_params: Dict[str, Any] = {}
    requires_llm: bool = True
    requires_embedding: bool = False
    requires_ground_truth: bool = False
    requires_contexts: bool = False
    range_min: float = 0.0
    range_max: float = 1.0
    higher_is_better: bool = True
    tags: List[str] = []


class MetricResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    display_name_en: Optional[str]
    description: Optional[str]
    category: str
    framework: Optional[str]
    eval_stage: str
    requires_llm: bool
    requires_embedding: bool
    requires_ground_truth: bool
    requires_contexts: bool
    usage_count: int
    is_builtin: bool
    tags: List[str]

    class Config:
        from_attributes = True


@router.get("", response_model=List[MetricResponse])
async def list_metrics(
    category: Optional[str] = None,
    framework: Optional[str] = None,
    eval_stage: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """浏览指标市场"""
    query = select(MetricDefinition).where(
        MetricDefinition.is_active == True,
        MetricDefinition.is_public == True
    )

    if category:
        query = query.where(MetricDefinition.category == category)
    if framework:
        query = query.where(MetricDefinition.framework == framework)
    if eval_stage:
        query = query.where(MetricDefinition.eval_stage == eval_stage)
    if search:
        query = query.where(
            MetricDefinition.name.ilike(f"%{search}%") |
            MetricDefinition.display_name.ilike(f"%{search}%")
        )

    query = query.order_by(MetricDefinition.sort_order, MetricDefinition.usage_count.desc())
    result = await db.execute(query)
    metrics = result.scalars().all()

    # 获取每个指标的标签
    response = []
    for m in metrics:
        tags_result = await db.execute(
            select(MetricTag.tag).where(MetricTag.metric_id == m.id)
        )
        tags = [t[0] for t in tags_result.fetchall()]

        response.append(MetricResponse(
            id=m.id,
            name=m.name,
            display_name=m.display_name,
            display_name_en=m.display_name_en,
            description=m.description,
            category=m.category,
            framework=m.framework,
            eval_stage=m.eval_stage,
            requires_llm=m.requires_llm,
            requires_embedding=m.requires_embedding,
            requires_ground_truth=m.requires_ground_truth,
            requires_contexts=m.requires_contexts,
            usage_count=m.usage_count,
            is_builtin=m.is_builtin,
            tags=tags
        ))

    return response


@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """获取指标分类列表"""
    return ["retrieval", "generation", "quality", "performance", "custom"]


@router.get("/eval-stages")
async def get_eval_stages(db: AsyncSession = Depends(get_db)):
    """获取评估阶段列表"""
    return ["process", "result"]


@router.get("/{metric_id}", response_model=MetricResponse)
async def get_metric(
    metric_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """查看指标详情"""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="指标不存在")

    tags_result = await db.execute(
        select(MetricTag.tag).where(MetricTag.metric_id == metric.id)
    )
    tags = [t[0] for t in tags_result.fetchall()]

    return MetricResponse(
        id=metric.id,
        name=metric.name,
        display_name=metric.display_name,
        display_name_en=metric.display_name_en,
        description=metric.description,
        category=metric.category,
        framework=metric.framework,
        requires_llm=metric.requires_llm,
        requires_embedding=metric.requires_embedding,
        requires_ground_truth=metric.requires_ground_truth,
        requires_contexts=metric.requires_contexts,
        usage_count=metric.usage_count,
        is_builtin=metric.is_builtin,
        tags=tags
    )


@router.post("", response_model=MetricResponse)
async def create_metric(
    data: MetricCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建自定义指标"""
    # 检查名称是否已存在
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.name == data.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="指标名称已存在")

    metric = MetricDefinition(
        name=data.name,
        display_name=data.display_name,
        display_name_en=data.display_name_en,
        description=data.description,
        category=data.category,
        framework=data.framework,
        eval_stage=data.eval_stage,
        params_schema=data.params_schema,
        default_params=data.default_params,
        requires_llm=data.requires_llm,
        requires_embedding=data.requires_embedding,
        requires_ground_truth=data.requires_ground_truth,
        requires_contexts=data.requires_contexts,
        range_min=data.range_min,
        range_max=data.range_max,
        higher_is_better=data.higher_is_better,
        is_builtin=False,
        is_public=True
    )
    db.add(metric)
    await db.flush()

    # 添加标签
    for tag in data.tags:
        metric_tag = MetricTag(metric_id=metric.id, tag=tag)
        db.add(metric_tag)

    await db.commit()
    await db.refresh(metric)

    return MetricResponse(
        id=metric.id,
        name=metric.name,
        display_name=metric.display_name,
        display_name_en=metric.display_name_en,
        description=metric.description,
        category=metric.category,
        framework=metric.framework,
        requires_llm=metric.requires_llm,
        requires_embedding=metric.requires_embedding,
        requires_ground_truth=metric.requires_ground_truth,
        requires_contexts=metric.requires_contexts,
        usage_count=metric.usage_count,
        is_builtin=metric.is_builtin,
        tags=data.tags
    )


@router.post("/{metric_id}/rate")
async def rate_metric(
    metric_id: UUID,
    rating: int,
    db: AsyncSession = Depends(get_db)
):
    """对指标评分"""
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="评分必须在1-5之间")

    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="指标不存在")

    # TODO: 实现评分逻辑（需要用户系统）
    return {"message": "评分成功", "metric_id": str(metric_id), "rating": rating}