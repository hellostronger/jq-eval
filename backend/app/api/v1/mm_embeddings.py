# 多模态嵌入评测 API
#
# 独立于 /evaluations：嵌入模型评测没有 RAG 调用与 LLM 打分环节，
# 数据集是 (query, candidate) 对，结果按 Recall@k / MRR / nDCG 统计。
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import format_error
from ...core.utc_datetime import UTCDatetime
from ...models import MMDataset, MMEvalQueryResult, MMEvalRun, MMSample, Model
from ...services.mm_embedding.client import IMAGE_TRANSPORTS, REQUEST_FORMATS
from ...services.mm_embedding.media import (
    delete_dataset_images,
    presign_image,
    store_images,
)
from ...services.mm_embedding.parsing import parse_dataset_file
from ...tasks.mm_embedding_tasks import mm_embedding_eval_task
from ._common import get_or_404, start_task, validate_upload_size

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMPORT_MB = 200


class MMDatasetResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    status: str
    record_count: int
    query_count: int
    image_count: int
    subset_stats: Optional[Dict[str, Any]] = None
    source_meta: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class MMSamplePreview(BaseModel):
    qid: str
    subset: Optional[str] = None
    query_text: Optional[str] = None
    query_image_url: Optional[str] = None
    target_text: Optional[str] = None
    target_image_url: Optional[str] = None
    label: int


class MMDatasetDetail(MMDatasetResponse):
    samples: List[MMSamplePreview] = []


class MMRunCreate(BaseModel):
    name: Optional[str] = None
    dataset_id: UUID
    model_id: UUID
    params: Dict[str, Any] = {}


class MMRunResponse(BaseModel):
    id: UUID
    name: str
    dataset_id: UUID
    dataset_name: Optional[str] = None
    model_id: UUID
    model_name: Optional[str] = None
    status: str
    progress: int
    error: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    subset_metrics: Optional[Dict[str, Any]] = None
    query_count: int
    skipped_queries: int
    encoded_items: int
    started_at: Optional[UTCDatetime] = None
    completed_at: Optional[UTCDatetime] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class MMQueryResultResponse(BaseModel):
    id: UUID
    qid: str
    subset: Optional[str] = None
    rank: Optional[int] = None
    candidate_count: int
    positive_count: int
    metrics: Optional[Dict[str, Any]] = None
    retrieved_top: List[Dict[str, Any]] = []


class MMQueryResultPage(BaseModel):
    items: List[MMQueryResultResponse]
    total: int
    page: int
    page_size: int
    top_k: int


def _normalize_params(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params = dict(raw or {})
    transport = str(params.get("image_transport") or "data_url").lower()
    if transport not in IMAGE_TRANSPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"image_transport 仅支持 {', '.join(IMAGE_TRANSPORTS)}",
        )
    request_format = str(params.get("request_format") or "content_array").lower()
    if request_format not in REQUEST_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"request_format 仅支持 {', '.join(REQUEST_FORMATS)}",
        )

    def _int_param(key: str, default: int, low: int, high: int) -> int:
        value = params.get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} 必须是整数")
        if not low <= value <= high:
            raise HTTPException(status_code=400, detail=f"{key} 需在 {low}-{high} 之间")
        return value

    normalized = {
        "image_transport": transport,
        "request_format": request_format,
        "batch_size": _int_param("batch_size", 8, 1, 100),
        "top_k": _int_param("top_k", 10, 1, 100),
    }
    for key in ("timeout", "max_retries"):
        if key in params:
            normalized[key] = params[key]
    return normalized


async def _run_response(db: AsyncSession, run: MMEvalRun) -> MMRunResponse:
    dataset = await db.get(MMDataset, run.dataset_id)
    snapshot = run.model_snapshot or {}
    return MMRunResponse(
        id=run.id,
        name=run.name,
        dataset_id=run.dataset_id,
        dataset_name=dataset.name if dataset else None,
        model_id=run.model_id,
        model_name=snapshot.get("name"),
        status=run.status,
        progress=run.progress or 0,
        error=run.error,
        params=run.params,
        metrics=run.metrics,
        subset_metrics=run.subset_metrics,
        query_count=run.query_count or 0,
        skipped_queries=run.skipped_queries or 0,
        encoded_items=run.encoded_items or 0,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


# ---------------------------------------------------------------------------
# 数据集
# ---------------------------------------------------------------------------
@router.get("/datasets", response_model=List[MMDatasetResponse])
async def list_datasets(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(MMDataset).order_by(MMDataset.created_at.desc()))
    ).scalars().all()
    return rows


@router.post("/datasets", response_model=MMDatasetResponse)
async def import_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """导入 MMEB 官方 jsonl、通用 jsonl/json 或含图片的 zip（≤200MB）"""
    validate_upload_size(file, max_mb=MAX_IMPORT_MB)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        parsed = parse_dataset_file(file.filename or "", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=format_error(exc))

    dataset_id = uuid4()
    dataset = MMDataset(
        id=dataset_id,
        name=(name or "").strip() or (file.filename or "未命名评测集"),
        description=description or None,
        source_type="upload",
        status="importing",
        source_meta={
            "file": file.filename,
            "size_bytes": len(raw),
            **(parsed.source_meta or {}),
        },
    )
    db.add(dataset)
    # 先落 importing：图片上传可能需要几十秒，不能让长事务占着连接
    await db.commit()

    refs: List[str] = []
    for sample in parsed.samples:
        if sample.query_image_ref:
            refs.append(sample.query_image_ref)
        if sample.target_image_ref:
            refs.append(sample.target_image_ref)

    try:
        mapping, image_count = await store_images(
            dataset_id, refs, parsed.images, parsed.image_names
        )
    except ValueError as exc:
        dataset = await db.get(MMDataset, dataset_id)
        dataset.status = "failed"
        dataset.error = format_error(exc)
        await db.commit()
        raise HTTPException(status_code=400, detail=format_error(exc))
    except Exception as exc:
        logger.exception(f"评测集 {dataset_id} 图片入库失败")
        dataset = await db.get(MMDataset, dataset_id)
        dataset.status = "failed"
        dataset.error = f"图片入库失败：{format_error(exc)}"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"图片入库失败：{format_error(exc)}")

    subset_stats: Dict[str, Dict[str, Any]] = {}
    samples: List[MMSample] = []
    for seq, raw_sample in enumerate(parsed.samples):
        samples.append(
            MMSample(
                dataset_id=dataset_id,
                seq=seq,
                subset=raw_sample.subset,
                qid=raw_sample.qid,
                query_text=raw_sample.query_text,
                query_image=mapping.get(raw_sample.query_image_ref)
                if raw_sample.query_image_ref
                else None,
                target_text=raw_sample.target_text,
                target_image=mapping.get(raw_sample.target_image_ref)
                if raw_sample.target_image_ref
                else None,
                label=raw_sample.label,
                sample_metadata=raw_sample.metadata or {},
            )
        )
        entry = subset_stats.setdefault(
            raw_sample.subset or "未分组", {"queries": set(), "candidates": 0}
        )
        entry["queries"].add(raw_sample.qid)
        entry["candidates"] += 1

    db.add_all(samples)
    dataset = await db.get(MMDataset, dataset_id)
    dataset.status = "ready"
    dataset.record_count = len(samples)
    dataset.query_count = len({s.qid for s in parsed.samples})
    dataset.image_count = image_count
    dataset.subset_stats = {
        subset: {"queries": len(entry["queries"]), "candidates": entry["candidates"]}
        for subset, entry in sorted(subset_stats.items())
    }
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("/datasets/{dataset_id}", response_model=MMDatasetDetail)
async def get_dataset(
    dataset_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    dataset = await get_or_404(db, MMDataset, dataset_id, "评测集不存在")
    rows = (
        await db.execute(
            select(MMSample)
            .where(MMSample.dataset_id == dataset_id)
            .order_by(MMSample.seq)
            .limit(limit)
        )
    ).scalars().all()

    previews: List[MMSamplePreview] = []
    for sample in rows:
        previews.append(
            MMSamplePreview(
                qid=sample.qid,
                subset=sample.subset,
                query_text=sample.query_text,
                query_image_url=await presign_image(sample.query_image)
                if sample.query_image
                else None,
                target_text=sample.target_text,
                target_image_url=await presign_image(sample.target_image)
                if sample.target_image
                else None,
                label=sample.label or 0,
            )
        )
    detail = MMDatasetDetail.model_validate(dataset)
    detail.samples = previews
    return detail


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: UUID, db: AsyncSession = Depends(get_db)):
    dataset = await get_or_404(db, MMDataset, dataset_id, "评测集不存在")
    run_count = (
        await db.execute(
            select(func.count())
            .select_from(MMEvalRun)
            .where(MMEvalRun.dataset_id == dataset_id)
        )
    ).scalar_one()
    if run_count:
        raise HTTPException(
            status_code=400, detail=f"该评测集已被 {run_count} 个评测运行引用，不能删除"
        )

    await db.execute(delete(MMSample).where(MMSample.dataset_id == dataset_id))
    await db.delete(dataset)
    await db.commit()
    removed = await delete_dataset_images(dataset_id)
    return {"deleted": True, "images_removed": removed}


# ---------------------------------------------------------------------------
# 评测运行
# ---------------------------------------------------------------------------
@router.get("/runs", response_model=List[MMRunResponse])
async def list_runs(
    dataset_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MMEvalRun).order_by(MMEvalRun.created_at.desc()).limit(limit)
    if dataset_id:
        stmt = stmt.where(MMEvalRun.dataset_id == dataset_id)
    if status:
        stmt = stmt.where(MMEvalRun.status == status)
    runs = (await db.execute(stmt)).scalars().all()
    return [await _run_response(db, run) for run in runs]


@router.post("/runs", response_model=MMRunResponse)
async def create_run(payload: MMRunCreate, db: AsyncSession = Depends(get_db)):
    dataset = await get_or_404(db, MMDataset, payload.dataset_id, "评测集不存在")
    if dataset.status != "ready":
        raise HTTPException(
            status_code=400, detail=f"评测集状态为 {dataset.status}，导入完成后才能评测"
        )

    model = await get_or_404(db, Model, payload.model_id, "模型配置不存在")
    if model.model_type != "embedding":
        raise HTTPException(status_code=400, detail="只能选择 embedding 类型的模型")

    params = _normalize_params(payload.params)
    run = MMEvalRun(
        name=(payload.name or "").strip()
        or f"{dataset.name} · {model.name}",
        dataset_id=dataset.id,
        model_id=model.id,
        model_snapshot={
            "name": model.name,
            "model_name": model.model_name,
            "provider": model.provider,
            "endpoint": model.endpoint,
        },
        status="pending",
        params=params,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    await start_task(db, run, lambda: mm_embedding_eval_task.delay(str(run.id)))
    return await _run_response(db, run)


@router.get("/runs/{run_id}", response_model=MMRunResponse)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run = await get_or_404(db, MMEvalRun, run_id, "评测运行不存在")
    return await _run_response(db, run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID, force: bool = False, db: AsyncSession = Depends(get_db)
):
    run = await get_or_404(db, MMEvalRun, run_id, "评测运行不存在")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"当前状态 {run.status} 不可取消")

    if force:
        # worker 已丢失时协作式取消永远等不到检查点，只能库侧终结
        run.status = "cancelled"
        run.cancel_requested = False
        run.error = "强制取消：worker 可能已丢失，任务未再次执行"
        run.completed_at = datetime.utcnow()
        await db.commit()
        return {"cancelled": True, "forced": True, "message": "已强制取消"}

    run.cancel_requested = True
    await db.commit()
    return {"cancelled": True, "forced": False, "message": "已请求取消，任务将在批次边界停止"}


@router.post("/runs/{run_id}/rerun", response_model=MMRunResponse)
async def rerun(run_id: UUID, db: AsyncSession = Depends(get_db)):
    run = await get_or_404(db, MMEvalRun, run_id, "评测运行不存在")
    if run.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=400, detail="仅失败或已取消的运行可以重跑")

    await db.execute(delete(MMEvalQueryResult).where(MMEvalQueryResult.run_id == run_id))
    run.status = "pending"
    run.progress = 0
    run.error = None
    run.cancel_requested = False
    run.metrics = {}
    run.subset_metrics = {}
    run.query_count = 0
    run.skipped_queries = 0
    run.encoded_items = 0
    run.started_at = None
    run.completed_at = None
    await db.commit()

    await start_task(db, run, lambda: mm_embedding_eval_task.delay(str(run_id)))
    return await _run_response(db, run)


@router.get("/runs/{run_id}/queries", response_model=MMQueryResultPage)
async def list_query_results(
    run_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    subset: Optional[str] = None,
    only_missed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    run = await get_or_404(db, MMEvalRun, run_id, "评测运行不存在")
    top_k = int((run.params or {}).get("top_k") or 10)

    conditions = [MMEvalQueryResult.run_id == run_id]
    if subset:
        conditions.append(MMEvalQueryResult.subset == subset)
    if only_missed:
        conditions.append(
            (MMEvalQueryResult.rank.is_(None)) | (MMEvalQueryResult.rank > top_k)
        )

    total = (
        await db.execute(
            select(func.count())
            .select_from(MMEvalQueryResult)
            .where(*conditions)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(MMEvalQueryResult)
            .where(*conditions)
            .order_by(MMEvalQueryResult.rank.desc().nullslast(), MMEvalQueryResult.qid)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items: List[MMQueryResultResponse] = []
    for row in rows:
        retrieved = []
        for entry in row.retrieved_top or []:
            item = dict(entry)
            if item.get("image"):
                item["image_url"] = await presign_image(item["image"])
            retrieved.append(item)
        items.append(
            MMQueryResultResponse(
                id=row.id,
                qid=row.qid,
                subset=row.subset,
                rank=row.rank,
                candidate_count=row.candidate_count or 0,
                positive_count=row.positive_count or 0,
                metrics=row.metrics,
                retrieved_top=retrieved,
            )
        )

    return MMQueryResultPage(
        items=items, total=total, page=page, page_size=page_size, top_k=top_k
    )
