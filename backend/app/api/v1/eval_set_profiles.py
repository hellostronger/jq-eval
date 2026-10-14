# 评测集画像 API 路由
#
# 流程：内置样例一键导入（离线）或 HF 拉取 → 落为 Dataset(dataset_kind=evaluation)
# + EvalSetRecord → 生成 EvalSetProfile；/compare 做集间差异对比。
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import format_error
from ...core.utc_datetime import UTCDatetime
from ...models import Dataset, EvalSetProfile, EvalSetRecord
from ...services.evalset import samples as samples_service
from ...services.evalset.compare import compare_profiles
from ...services.evalset.normalize import MODEL_TYPES
from ...services.evalset.profile_runner import (
    SYNC_PROFILE_LIMIT,
    count_records,
    import_records,
    load_records,
    run_profile,
)
from ._common import commit_delete, get_or_404

logger = logging.getLogger(__name__)
router = APIRouter()


class SampleImportRequest(BaseModel):
    sample: str
    name: Optional[str] = None
    description: Optional[str] = None


class ProfileCreate(BaseModel):
    dataset_id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    model_type: str = "llm"
    benchmark_key: Optional[str] = None


class ProfileResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    dataset_id: UUID
    source: str
    benchmark_key: Optional[str]
    model_type: str
    status: str
    progress: int
    error: Optional[str]
    total_samples: int
    unique_samples: int
    duplicate_rate: float
    sampled: bool
    tags: List[str]
    overview: Optional[Dict[str, Any]]
    task_profile: Optional[Dict[str, Any]]
    answer_profile: Optional[Dict[str, Any]]
    capability: Optional[Dict[str, Any]]
    quality: Optional[Dict[str, Any]]
    schema_profile: Optional[List[Dict[str, Any]]]
    samples: Optional[List[Dict[str, Any]]]
    summary: Optional[str]
    source_meta: Optional[Dict[str, Any]]
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class CompareRequest(BaseModel):
    profile_ids: List[UUID]
    include_contamination: bool = True


# ---------------------------------------------------------------------------
# ⚠️ 静态路由必须全部声明在 /{profile_id} 之前
#    Starlette 按首个匹配的路径正则分发且无类型兜底，
#    /samples、/compare 若声明在动态路由后会���被永久遮蔽、恒返回 422。
#    回归由 backend/tests/test_route_order.py 把关。
# ---------------------------------------------------------------------------
@router.get("/samples")
async def list_samples():
    """内置评测集样例目录（离线可导入）"""
    items = samples_service.list_samples()
    return {"items": items, "total": len(items)}


@router.post("/samples/import")
async def import_sample(
    data: SampleImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """导入内置样例为评测集并立即生成画像（离线闭环）"""
    try:
        meta = samples_service.get_meta(data.sample)
    except KeyError:
        raise HTTPException(status_code=404, detail="样例不存在")

    try:
        records = samples_service.load_sample(data.sample)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=format_error(exc))
    if not records:
        raise HTTPException(status_code=400, detail="样例文件为空")

    model_type = meta["model_type"]
    name = data.name or meta["title"]

    # 幂等：同名 + 同来源的评测集复用，避免重复导入堆积
    existing = await db.execute(
        select(Dataset).where(
            Dataset.name == name, Dataset.source_type == "evalset-sample"
        )
    )
    dataset = existing.scalars().first()
    if not dataset:
        dataset = Dataset(
            name=name,
            description=data.description or meta["title"],
            source_type="evalset-sample",
            source_url=f"https://huggingface.co/datasets/{meta['repo']}",
            dataset_kind="evaluation",
        )
        db.add(dataset)
        await db.commit()
        await db.refresh(dataset)

    saved = await import_records(db, dataset.id, records, model_type=model_type, replace=True)
    dataset.record_count = saved
    await db.commit()

    profile = EvalSetProfile(
        name=f"{name} 画像",
        dataset_id=dataset.id,
        source="sample",
        benchmark_key=data.sample,
        model_type=model_type,
        status="pending",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    try:
        await run_profile(db, profile)
    except Exception as exc:
        profile.status = "failed"
        profile.error = format_error(exc)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"画像生成失败：{profile.error}")
    await db.refresh(profile)

    return {"dataset_id": str(dataset.id), "dataset_name": dataset.name,
            "imported": saved, "profile": ProfileResponse.model_validate(profile)}


@router.post("/compare")
async def compare(
    data: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    """★ 评测集之间差异对比（本功能主入口）"""
    ids = list(dict.fromkeys(data.profile_ids))
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择两个评测集才能对比")
    if len(ids) > 8:
        raise HTTPException(status_code=400, detail="一次最多对比 8 个评测集")

    result = await db.execute(select(EvalSetProfile).where(EvalSetProfile.id.in_(ids)))
    profiles = list(result.scalars().all())
    if len(profiles) < 2:
        raise HTTPException(status_code=404, detail="部分评测集不存在")

    payload: List[Dict[str, Any]] = []
    rows_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for p in profiles:
        item = {
            "id": str(p.id),
            "name": p.name,
            "model_type": p.model_type,
            "benchmark_key": p.benchmark_key,
            "overview": p.overview or {},
            "task_profile": p.task_profile or {},
            "answer_profile": p.answer_profile or {},
            "capability": p.capability or {},
            "quality": p.quality or {},
        }
        payload.append(item)
        if data.include_contamination:
            rows = await load_records(db, p.dataset_id, 200000)
            # 污染检测只需指纹与答案，裁剪掉大字段降低内存占用
            rows_by_id[str(p.id)] = [
                {
                    "question_hash": r.get("question_hash"),
                    "qa_hash": r.get("qa_hash"),
                    "question": r.get("question"),
                    "answer_labels": r.get("answer_labels"),
                    "answer_text": r.get("answer_text"),
                    "subject": r.get("subject"),
                }
                for r in rows
            ]

    return compare_profiles(payload, rows_by_id if data.include_contamination else None)


# ---------------------------------------------------------------------------
# 画像 CRUD（静态路由之后）
# ---------------------------------------------------------------------------
@router.get("")
async def list_profiles(
    dataset_id: Optional[UUID] = None,
    status: Optional[str] = None,
    model_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(EvalSetProfile)
    if dataset_id:
        query = query.where(EvalSetProfile.dataset_id == dataset_id)
    if status:
        query = query.where(EvalSetProfile.status == status)
    if model_type:
        query = query.where(EvalSetProfile.model_type == model_type)
    query = query.order_by(EvalSetProfile.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=ProfileResponse)
async def create_profile(
    data: ProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """为已存在的数据集生成评测集画像"""
    if data.model_type not in MODEL_TYPES:
        raise HTTPException(status_code=400, detail=f"model_type 只能是 {'/'.join(MODEL_TYPES)}")

    dataset = await get_or_404(db, Dataset, data.dataset_id, "数据集不存在")
    total = await count_records(db, dataset.id)
    if total == 0:
        raise HTTPException(
            status_code=400,
            detail="该数据集没有评测样本，请先通过 /samples/import 导入评测集",
        )

    profile = EvalSetProfile(
        name=data.name or f"{dataset.name} 画像",
        description=data.description,
        dataset_id=dataset.id,
        source="dataset",
        benchmark_key=data.benchmark_key,
        model_type=data.model_type,
        status="pending",
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    if total <= SYNC_PROFILE_LIMIT:
        try:
            await run_profile(db, profile)
        except Exception as exc:
            profile.status = "failed"
            profile.error = format_error(exc)
            await db.commit()
            raise HTTPException(status_code=500, detail=f"画像生成失败：{profile.error}")
        await db.refresh(profile)
        return profile

    raise HTTPException(
        status_code=400,
        detail=f"数据集有 {total} 条样本，超过同步画像上限 {SYNC_PROFILE_LIMIT}，请缩小导入量",
    )


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, EvalSetProfile, profile_id, "评测集画像不存在")


@router.get("/{profile_id}/status")
async def get_profile_status(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    profile = await get_or_404(db, EvalSetProfile, profile_id, "评测集画像不存在")
    return {
        "profile_id": str(profile.id),
        "status": profile.status,
        "progress": profile.progress,
        "total_samples": profile.total_samples,
        "error": profile.error,
    }


@router.post("/{profile_id}/run", response_model=ProfileResponse)
async def rerun_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    profile = await get_or_404(db, EvalSetProfile, profile_id, "评测集画像不存在")
    try:
        await run_profile(db, profile)
    except Exception as exc:
        profile.status = "failed"
        profile.error = format_error(exc)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"画像重跑失败：{profile.error}")
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}/records")
async def list_records(
    profile_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    task_format: Optional[str] = None,
    model_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    profile = await get_or_404(db, EvalSetProfile, profile_id, "评测集画像不存在")
    query = select(EvalSetRecord).where(EvalSetRecord.dataset_id == profile.dataset_id)
    if task_format:
        query = query.where(EvalSetRecord.task_format == task_format)
    if model_type:
        query = query.where(EvalSetRecord.model_type == model_type)

    total = await db.execute(
        select(func.count(EvalSetRecord.id)).where(EvalSetRecord.dataset_id == profile.dataset_id)
    )
    result = await db.execute(query.order_by(EvalSetRecord.seq).offset(skip).limit(limit))
    rows = [
        {
            "id": str(r.id),
            "seq": r.seq,
            "question": r.question,
            "task_format": r.task_format,
            "answer_type": r.answer_type,
            "choices": r.choices,
            "answer_labels": r.answer_labels,
            "answer_text": r.answer_text,
            "subject": r.subject,
            "difficulty": r.difficulty,
            "language": r.language,
            "payload": r.payload,
        }
        for r in result.scalars().all()
    ]
    return {"total": int(total.scalar() or 0), "records": rows}


@router.delete("/{profile_id}")
async def delete_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    profile = await get_or_404(db, EvalSetProfile, profile_id, "评测集画像不存在")
    await db.delete(profile)
    await commit_delete(db, "评测集画像已被其他记录引用，无法删除")
    return {"success": True}