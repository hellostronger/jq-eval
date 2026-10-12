# 训练数据画像 API 路由
#
# 流程：数据走既有数据集上传（POST /datasets/{id}/import）落库 → 本模块对
# 数据集生成画像（概览/字段/分类/质量/样本预览）；另内置 UltraData 目录与
# 真实样例的一键导入，作为开箱即用的示例数据源。
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import format_error
from ...core.utc_datetime import UTCDatetime
from ...models import Dataset, TrainingDataProfile, TrainingDataRecord
from ...models.dataset import QARecord
from ...services.training_data.normalize import normalize_record
from ...services.training_data.profile_runner import (
    SYNC_PROFILE_LIMIT,
    count_records,
    run_profile,
)
from ...services.training_data import ultradata as ultradata_service
from ._common import get_or_404, start_task

logger = logging.getLogger(__name__)
router = APIRouter()


class ProfileCreate(BaseModel):
    dataset_id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    # LLM 深度分析：off=仅规则画像 / sample=抽样过一遍 / full=逐条过一遍（分批）
    llm_mode: str = "off"
    llm_model_id: Optional[UUID] = None
    llm_sample_size: int = 40


class ProfileResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    dataset_id: UUID
    source: str
    format: Optional[str]
    level: Optional[str]
    tags: List[str]
    status: str
    progress: int
    error: Optional[str]
    total_samples: int
    unique_samples: int
    duplicate_rate: float
    sampled: bool
    overview: Optional[Dict[str, Any]]
    schema_profile: Optional[List[Dict[str, Any]]]
    classification: Optional[Dict[str, Any]]
    quality: Optional[Dict[str, Any]]
    samples: Optional[List[Dict[str, Any]]]
    summary: Optional[str]
    llm_mode: str
    llm_model_id: Optional[UUID]
    llm_sample_size: int
    llm_analysis: Optional[Dict[str, Any]]
    source_meta: Optional[Dict[str, Any]]
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class ProfileRerunRequest(BaseModel):
    llm_mode: Optional[str] = None       # 不传则沿用画像上的设置
    llm_model_id: Optional[UUID] = None
    llm_sample_size: Optional[int] = None


class UltradataImportRequest(BaseModel):
    sample: str
    name: Optional[str] = None
    llm_mode: str = "off"
    llm_model_id: Optional[UUID] = None
    llm_sample_size: int = 40


# ---------------------------------------------------------------------------
# UltraData（静态路由必须在 /{profile_id} 之前，否则被 UUID 动态路由遮蔽）
# ---------------------------------------------------------------------------
@router.get("/ultradata/catalog")
async def get_ultradata_catalog(language: str = "zh"):
    """拉取 UltraData 数据集目录（在线失败时报 502，由前端提示重试）"""
    try:
        items = await ultradata_service.fetch_catalog(language=language)
    except Exception as exc:
        logger.warning(f"UltraData 目录拉取失败: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail=f"UltraData 目录拉取失败：{exc}")
    return {"items": items, "total": len(items)}


@router.get("/ultradata/samples")
async def list_ultradata_samples():
    """本地内置的 UltraData 真实样例（离线可导入）"""
    samples = ultradata_service.list_samples()
    return {"items": samples, "total": len(samples)}


@router.post("/ultradata/import")
async def import_ultradata_sample(
    data: UltradataImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """把内置 UltraData 样例导入为数据集并生成画像（离线闭环示例）"""
    try:
        records = ultradata_service.load_sample(data.sample)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"未知样例：{data.sample}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=format_error(exc))
    if not records:
        raise HTTPException(status_code=400, detail="样例文件为空")

    meta = ultradata_service.SAMPLE_FILES[data.sample]
    name = data.name or f"UltraData/{meta['title']}"

    # 幂等：同名样例数据集重复导入时复用，先清掉旧样本再灌新数据
    dataset = (await db.execute(
        select(Dataset).where(Dataset.name == name, Dataset.source_type == "ultradata")
    )).scalars().first()
    if dataset:
        # 复用同名数据集：先清掉旧样本再灌新数据，保证重复导入幂等
        await db.execute(
            TrainingDataRecord.__table__.delete().where(
                TrainingDataRecord.dataset_id == dataset.id
            )
        )
    else:
        dataset = Dataset(
            name=name,
            description=f"来自 {meta['repo']} 的真实样例（{meta['title']}，层级 {meta['level']}）",
            source_type="ultradata",
            source_url=f"https://huggingface.co/datasets/{meta['repo']}",
            status="ready",
        )
        db.add(dataset)
        await db.flush()

    for seq, raw in enumerate(records):
        db.add(TrainingDataRecord(dataset_id=dataset.id, **normalize_record(raw, seq=seq)))

    dataset.record_count = len(records)
    dataset.status = "ready"

    profile = TrainingDataProfile(
        name=f"{name} 画像",
        description=f"UltraData 样例画像（{meta['title']}）",
        dataset_id=dataset.id,
        source="ultradata",
        source_meta={k: v for k, v in meta.items() if k != "file"},
        status="pending",
        progress=0,
        llm_mode=data.llm_mode,
        llm_model_id=data.llm_model_id,
        llm_sample_size=data.llm_sample_size,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    try:
        result = await run_profile(db, profile)
    except Exception as exc:
        profile.status = "failed"
        profile.error = format_error(exc)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"画像生成失败：{profile.error}")

    return {
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "imported": len(records),
        "profile": result and {
            "id": str(profile.id),
            "format": profile.format,
            "level": profile.level,
            "status": profile.status,
            "total_samples": profile.total_samples,
        },
    }


# ---------------------------------------------------------------------------
# 画像 CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=List[ProfileResponse])
async def list_profiles(
    dataset_id: Optional[UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(TrainingDataProfile)
    if dataset_id:
        query = query.where(TrainingDataProfile.dataset_id == dataset_id)
    if status:
        query = query.where(TrainingDataProfile.status == status)
    result = await db.execute(query.order_by(TrainingDataProfile.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ProfileResponse)
async def create_profile(
    data: ProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """为数据集生成画像：样本量小则同步算完返回，大则派异步任务"""
    dataset = await get_or_404(db, Dataset, data.dataset_id, "数据集不存在")
    if data.llm_mode not in ("off", "sample", "full"):
        raise HTTPException(status_code=400, detail="llm_mode 只能是 off / sample / full")

    total = await count_records(db, dataset.id)
    if total == 0:
        # 历史数据集可能只有 qa_records，交由画像执行器现场归一化
        qa_total = (await db.execute(
            select(func.count(QARecord.id)).where(QARecord.dataset_id == dataset.id)
        )).scalar()
        if not qa_total:
            raise HTTPException(status_code=400, detail="数据集中没有样本，请先上传数据")

    profile = TrainingDataProfile(
        name=data.name or f"{dataset.name} 画像",
        description=data.description,
        dataset_id=dataset.id,
        source="dataset",
        status="pending",
        progress=0,
        llm_mode=data.llm_mode,
        llm_model_id=data.llm_model_id,
        llm_sample_size=data.llm_sample_size,
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

    # 大数据集走 Celery，避免请求线程被占住
    from ...tasks.training_data_profile_tasks import training_data_profile_task
    await start_task(
        db, profile,
        lambda: training_data_profile_task.delay(str(profile.id)),
        fallback_value="pending",
    )
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, TrainingDataProfile, profile_id, "画像不存在")


@router.get("/{profile_id}/status")
async def get_profile_status(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    profile = await get_or_404(db, TrainingDataProfile, profile_id, "画像不存在")
    return {
        "profile_id": str(profile.id),
        "status": profile.status,
        "progress": profile.progress,
        "total_samples": profile.total_samples,
        "error": profile.error,
    }


@router.post("/{profile_id}/run")
async def rerun_profile(
    profile_id: UUID,
    body: Optional[ProfileRerunRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """重新计算画像（数据更新后刷新）；可顺带改 LLM 分析设置"""
    profile = await get_or_404(db, TrainingDataProfile, profile_id, "画像不存在")
    if profile.status == "running":
        raise HTTPException(status_code=400, detail="画像正在生成中")
    if body is not None:
        if body.llm_mode is not None:
            if body.llm_mode not in ("off", "sample", "full"):
                raise HTTPException(status_code=400, detail="llm_mode 只能是 off / sample / full")
            profile.llm_mode = body.llm_mode
        if body.llm_model_id is not None:
            profile.llm_model_id = body.llm_model_id
        if body.llm_sample_size is not None:
            profile.llm_sample_size = body.llm_sample_size
    try:
        await run_profile(db, profile)
    except Exception as exc:
        profile.status = "failed"
        profile.error = format_error(exc)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"画像生成失败：{profile.error}")
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}/records")
async def get_profile_records(
    profile_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    format: Optional[str] = None,
    label: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """画像样本明细（分页 + 按格式/标签过滤）"""
    profile = await get_or_404(db, TrainingDataProfile, profile_id, "画像不存在")

    query = select(TrainingDataRecord).where(TrainingDataRecord.dataset_id == profile.dataset_id)
    count_query = select(func.count(TrainingDataRecord.id)).where(
        TrainingDataRecord.dataset_id == profile.dataset_id
    )
    if format:
        query = query.where(TrainingDataRecord.format == format)
        count_query = count_query.where(TrainingDataRecord.format == format)
    if label:
        query = query.where(TrainingDataRecord.labels.contains([label]))
        count_query = count_query.where(TrainingDataRecord.labels.contains([label]))

    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.order_by(TrainingDataRecord.seq).offset(skip).limit(limit))

    def _preview(value: Any, length: int = 400) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value).replace("\n", " ")
        return text[:length]

    return {
        "profile_id": str(profile.id),
        "total": total,
        "records": [
            {
                "id": str(r.id),
                "seq": r.seq,
                "format": r.format,
                "language": r.language,
                "labels": r.labels or [],
                "char_length": r.char_length,
                "est_tokens": r.est_tokens,
                "score": r.score,
                "turn_count": r.turn_count,
                "has_tools": r.has_tools,
                "instruction": _preview(r.instruction),
                "response": _preview(r.response),
                "text": _preview(r.text),
                "messages": [
                    {"role": m.get("role"), "content": _preview(m.get("content"), 200)}
                    for m in (r.messages or [])[:6]
                ] if r.messages else None,
            }
            for r in result.scalars().all()
        ],
    }


@router.delete("/{profile_id}")
async def delete_profile(profile_id: UUID, db: AsyncSession = Depends(get_db)):
    profile = await get_or_404(db, TrainingDataProfile, profile_id, "画像不存在")
    await db.delete(profile)
    await db.commit()
    return {"message": "删除成功"}
