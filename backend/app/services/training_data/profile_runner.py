# 画像计算执行器：API 同步路径与 Celery 任务共用同一套逻辑
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Dataset, TrainingDataProfile, TrainingDataRecord
from ...models.dataset import QARecord
from .normalize import normalize_record
from .profiling import PAYLOAD_PROFILE_LIMIT, build_profile

logger = logging.getLogger(__name__)

# 超过该条数走异步任务，避免请求线程被大画像占住
SYNC_PROFILE_LIMIT = 20000
# 单个画像最多统计的样本数（超出部分只计数不参与分布）
MAX_PROFILE_ROWS = 200000
# LLM 抽样模式默认送样条数（均匀抽样）
LLM_SAMPLE_DEFAULT = 40


async def count_records(db: AsyncSession, dataset_id) -> int:
    result = await db.execute(
        select(func.count(TrainingDataRecord.id)).where(TrainingDataRecord.dataset_id == dataset_id)
    )
    return int(result.scalar() or 0)


async def _load_rows(
    db: AsyncSession, dataset_id, limit: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """读取归一化样本行 + 字段画像用 payload 抽样"""
    total = await count_records(db, dataset_id)
    sampled = total > limit

    rows_result = await db.execute(
        select(
            TrainingDataRecord.format,
            TrainingDataRecord.language,
            TrainingDataRecord.labels,
            TrainingDataRecord.char_length,
            TrainingDataRecord.est_tokens,
            TrainingDataRecord.content_hash,
            TrainingDataRecord.turn_count,
            TrainingDataRecord.has_tools,
            TrainingDataRecord.score,
        )
        .where(TrainingDataRecord.dataset_id == dataset_id)
        .order_by(TrainingDataRecord.seq)
        .limit(limit)
    )
    rows = [dict(r._mapping) for r in rows_result.all()]

    payload_result = await db.execute(
        select(TrainingDataRecord.payload)
        .where(TrainingDataRecord.dataset_id == dataset_id)
        .order_by(TrainingDataRecord.seq)
        .limit(PAYLOAD_PROFILE_LIMIT)
    )
    payloads = [r for (r,) in payload_result.all() if r]

    if rows:
        return rows, payloads, sampled

    # 兼容历史数据集：该数据集是在画像功能上线前导入的，没有训练样本行，
    # 直接用 QARecord 现场归一化，保证老数据也能生成画像
    qa_result = await db.execute(
        select(
            QARecord.question, QARecord.answer, QARecord.ground_truth,
            QARecord.snapshot, QARecord.qa_metadata,
        )
        .where(QARecord.dataset_id == dataset_id)
        .order_by(QARecord.created_at)
        .limit(limit)
    )
    rows = []
    payloads = []
    for idx, rec in enumerate(qa_result.all()):
        raw = {
            "question": rec.question,
            "answer": rec.answer,
            "ground_truth": rec.ground_truth,
            "contexts": (rec.snapshot or {}).get("contexts"),
            **{k: v for k, v in ((rec.qa_metadata or {}).get("extra") or {}).items()},
        }
        normalized = normalize_record(raw, seq=idx)
        rows.append(normalized)
        if len(payloads) < PAYLOAD_PROFILE_LIMIT:
            payloads.append(raw)
    return rows, payloads, bool(rows)


async def _load_payloads(
    db: AsyncSession, dataset_id: Optional[Any], limit: int
) -> List[Dict[str, Any]]:
    """读取原始 payload（LLM 深度分析用；老数据集回退 QARecord 现场构造）"""
    if dataset_id is not None:
        result = await db.execute(
            select(TrainingDataRecord.payload)
            .where(TrainingDataRecord.dataset_id == dataset_id)
            .order_by(TrainingDataRecord.seq)
            .limit(limit)
        )
        payloads = [r for (r,) in result.all() if r]
        if payloads:
            return payloads

    qa_result = await db.execute(
        select(
            QARecord.question, QARecord.answer, QARecord.ground_truth,
            QARecord.snapshot, QARecord.qa_metadata,
        )
        .where(QARecord.dataset_id == dataset_id)
        .order_by(QARecord.created_at)
        .limit(limit)
    )
    return [
        {
            "question": rec.question,
            "answer": rec.answer,
            "ground_truth": rec.ground_truth,
            "contexts": (rec.snapshot or {}).get("contexts"),
            **{k: v for k, v in ((rec.qa_metadata or {}).get("extra") or {}).items()},
        }
        for rec in qa_result.all()
    ]


async def _run_llm_analysis(
    db: AsyncSession,
    profile: TrainingDataProfile,
    payloads: List[Dict[str, Any]],
    progress_cb: Optional[Any] = None,
) -> None:
    """按 llm_mode 调用 LLM 深度分析，结果写入 profile.llm_analysis

    没有可用模型且未显式指定 model_id 时降级：llm_analysis 记录原因，不失败。
    """
    from . import llm_analysis as la

    mode = (profile.llm_mode or "off").lower()
    if mode not in ("sample", "full"):
        return

    try:
        complete = await la.resolve_completer(db, profile.llm_model_id)
    except ValueError as exc:
        # 显式指定了模型但不可用：如实失败，让用户能感知
        raise
    if complete is None:
        profile.llm_analysis = {
            "mode": mode, "status": "skipped",
            "reason": "没有可用的 LLM 模型，请先在模型管理中配置并启用一个 LLM",
        }
        return

    dataset = await db.get(Dataset, profile.dataset_id)
    context = {
        "total": profile.total_samples,
        "format": profile.format,
        "name": (dataset.name if dataset else None) or profile.name,
        "stats": {
            "total": profile.total_samples,
            "unique": profile.unique_samples,
            "duplicate_rate": profile.duplicate_rate,
            "level": profile.level,
            "quality": (profile.quality or {}).get("score"),
        },
    }

    if mode == "sample":
        n = max(1, min(profile.llm_sample_size or LLM_SAMPLE_DEFAULT, len(payloads)))
        # 均匀抽样而非头部切片，避免只看到同质前缀
        step = max(1, len(payloads) // n)
        sampled = payloads[::step][:n]
        result = await la.analyze_sample(sampled, context, complete)
        result["status"] = "completed"
        profile.llm_analysis = result
        return

    # full：分批逐条过 LLM（进度 85 -> 95）
    def _batch_progress(done: int, total_batches: int) -> None:
        if progress_cb:
            try:
                progress_cb(85 + int(10 * done / max(total_batches, 1)))
            except Exception:
                pass

    llm_limit = min(len(payloads), la.FULL_BATCH_SIZE * la.FULL_MAX_BATCHES)
    result = await la.analyze_full(
        payloads[:llm_limit], context, complete, batch_progress=_batch_progress
    )
    result["status"] = "completed"
    result["truncated"] = llm_limit < len(payloads)
    profile.llm_analysis = result


async def run_profile(
    db: AsyncSession,
    profile: TrainingDataProfile,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """执行画像计算并把结果写回 profile（调用方负责最终 commit 的时机约定：
    本函数内部按阶段 commit，保证长任务中断也能看到进度）"""

    async def _progress(value: int) -> None:
        profile.progress = max(profile.progress or 0, value)
        await db.commit()
        if progress_cb:
            try:
                progress_cb(value)
            except Exception as exc:  # 进度回调失败不影响画像本身
                logger.warning(f"画像进度回调失败: {exc}")

    dataset = await db.get(Dataset, profile.dataset_id)
    if not dataset:
        raise ValueError(f"数据集 {profile.dataset_id} 不存在")

    profile.status = "running"
    profile.error = None
    await db.commit()
    await _progress(10)

    rows, payloads, sampled = await _load_rows(db, profile.dataset_id, MAX_PROFILE_ROWS)
    if not rows:
        raise ValueError(f"数据集「{dataset.name}」中没有可分析的样本，请先导入数据")
    await _progress(50)

    result = build_profile(
        rows,
        payloads=payloads,
        source=profile.source or "dataset",
    )
    await _progress(80)

    profile.name = profile.name or dataset.name
    profile.total_samples = result["total"]
    profile.unique_samples = result["unique"]
    profile.duplicate_rate = result["duplicate_rate"]
    profile.sampled = sampled
    profile.format = result["format"]
    profile.level = result["level"]
    profile.tags = result["tags"]
    profile.overview = result["overview"]
    profile.schema_profile = result["schema_profile"]
    profile.classification = result["classification"]
    profile.quality = result["quality"]
    profile.samples = result["samples"]
    profile.summary = result["summary"]
    profile.status = "completed"
    profile.completed_at = datetime.utcnow()
    await db.commit()
    await _progress(85)

    if (profile.llm_mode or "off") != "off":
        try:
            # LLM 分析用全量 payload（full 模式内部有批次上限）
            llm_payloads = await _load_payloads(db, profile.dataset_id, MAX_PROFILE_ROWS)
            await _run_llm_analysis(db, profile, llm_payloads, progress_cb=progress_cb)
        except Exception as exc:
            from ...core.exceptions import format_error
            profile.llm_analysis = {
                "mode": profile.llm_mode, "status": "failed",
                "error": format_error(exc),
            }
            logger.warning(f"LLM 深度分析失败（规则画像不受影响）: {exc}")
        await db.commit()

    await _progress(100)

    return result
