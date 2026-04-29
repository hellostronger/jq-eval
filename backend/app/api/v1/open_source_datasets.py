# 开源数据集管理路由
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
import httpx
import re

from ...core.database import get_db
from ...models import OpenSourceDataset

router = APIRouter()

# HuggingFace API
HF_API = "https://huggingface.co/api"

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


# ============================================================================
# HuggingFace Dataset Search (放在 /{dataset_id} 之前，避免路由冲突)
# ============================================================================


class HFDatasetSearchResult(BaseModel):
    """HuggingFace 数据集搜索结果"""
    id: str
    name: str
    url: str
    description: Optional[str]
    downloads: int
    likes: int
    tags: List[str]
    language: Optional[str]
    task_categories: List[str]
    size_info: Optional[str]


class HFDatasetSearchResponse(BaseModel):
    """HuggingFace 数据集搜索响应"""
    items: List[HFDatasetSearchResult]
    total: int


class HFDatasetImportRequest(BaseModel):
    """导入 HuggingFace 数据集请求"""
    hf_dataset_id: str


@router.get("/hf-search", response_model=HFDatasetSearchResponse)
async def search_hf_datasets(
    query: str,
    limit: int = 10,
    author: Optional[str] = None,
    tags: Optional[str] = None,
    language: Optional[str] = None,
):
    """
    搜索 HuggingFace Hub 上的数据集

    参考 ml-intern 的 dataset_search 实现
    """
    params = {
        "search": query,
        "limit": min(limit, 50),
        "sort": "downloads",
        "direction": -1,
    }

    if author:
        params["author"] = author
    if tags:
        params["filter"] = tags
    if language:
        params["language"] = language

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{HF_API}/datasets", params=params)
            resp.raise_for_status()
            datasets = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"HuggingFace API 错误: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"请求 HuggingFace API 失败: {str(e)}")

    results = []
    for ds in datasets:
        ds_id = ds.get("id", "")
        downloads = ds.get("downloads", 0)
        likes = ds.get("likes", 0)

        # 提取描述
        desc = ds.get("description") or ""
        if desc:
            desc = re.sub(r"<[^>]+>", "", desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            if len(desc) > 200:
                desc = desc[:200] + "..."

        # 提取标签信息
        tags_list = ds.get("tags", [])
        languages = [t.replace("language:", "") for t in tags_list if t.startswith("language:")]
        task_cats = [t.replace("task_categories:", "") for t in tags_list if t.startswith("task_categories:")]
        sizes = [t.replace("size_categories:", "") for t in tags_list if t.startswith("size_categories:")]

        size_info = sizes[0] if sizes else None

        results.append(HFDatasetSearchResult(
            id=ds_id,
            name=ds.get("title") or ds_id.split("/")[-1],
            url=f"https://huggingface.co/datasets/{ds_id}",
            description=desc,
            downloads=downloads,
            likes=likes,
            tags=[t for t in tags_list if not t.startswith(("language:", "task_categories:", "size_categories:", "arxiv:", "region:"))][:5],
            language=languages[0] if languages else None,
            task_categories=task_cats[:3],
            size_info=size_info,
        ))

    return HFDatasetSearchResponse(items=results, total=len(results))


@router.post("/hf-import", response_model=OpenSourceDatasetResponse)
async def import_hf_dataset(
    data: HFDatasetImportRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    从 HuggingFace Hub 导入数据集到本地数据库
    """
    hf_dataset_id = data.hf_dataset_id

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{HF_API}/datasets/{hf_dataset_id}")
            resp.raise_for_status()
            ds = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"HuggingFace 数据集 '{hf_dataset_id}' 不存在")
        raise HTTPException(status_code=500, detail=f"HuggingFace API 错误: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"请求 HuggingFace API 失败: {str(e)}")

    ds_id = ds.get("id", hf_dataset_id)
    description = ds.get("description") or ""
    if description:
        description = re.sub(r"<[^>]+>", "", description)
        description = re.sub(r"\s+", " ", description).strip()

    tags_list = ds.get("tags", [])
    languages = [t.replace("language:", "") for t in tags_list if t.startswith("language:")]
    task_cats = [t.replace("task_categories:", "") for t in tags_list if t.startswith("task_categories:")]
    sizes = [t.replace("size_categories:", "") for t in tags_list if t.startswith("size_categories:")]

    # 检查是否已存在
    existing = await db.execute(
        select(OpenSourceDataset).where(OpenSourceDataset.url == f"https://huggingface.co/datasets/{ds_id}")
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"数据集 '{ds_id}' 已存在于本地数据库")

    dataset = OpenSourceDataset(
        name=ds.get("title") or ds_id.split("/")[-1],
        url=f"https://huggingface.co/datasets/{ds_id}",
        description=description[:500] if description else None,
        dataset_type=task_cats[0] if task_cats else None,
        size_info=sizes[0] if sizes else f"{ds.get('downloads', 0)} downloads",
        language=languages[0] if languages else "multi",
        is_public=True,
        tags=[t for t in tags_list if not t.startswith(("language:", "task_categories:", "size_categories:", "arxiv:", "region:"))][:10],
        osd_metadata={
            "hf_id": ds_id,
            "downloads": ds.get("downloads", 0),
            "likes": ds.get("likes", 0),
            "task_categories": task_cats,
            "languages": languages,
        },
    )

    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return dataset


# ============================================================================
# 本地数据集 CRUD
# ============================================================================


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
    skip = (page - 1) * size

    query = select(OpenSourceDataset)

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

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

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