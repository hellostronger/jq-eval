# 评测集画像执行器：API 同步路径与 Celery 任务共用同一套逻辑
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Dataset, EvalSetProfile, EvalSetRecord
from .normalize import MODEL_LLM, normalize_record
from .profiling import build_profile

logger = logging.getLogger(__name__)

# 超过该条数走异步任务，避免请求线程被大画像占住
SYNC_PROFILE_LIMIT = 20000
# 单个画像最多统计的样本数
MAX_PROFILE_ROWS = 200000


async def count_records(db: AsyncSession, dataset_id) -> int:
    result = await db.execute(
        select(func.count(EvalSetRecord.id)).where(EvalSetRecord.dataset_id == dataset_id)
    )
    return int(result.scalar() or 0)


async def load_records(
    db: AsyncSession, dataset_id, limit: int
) -> List[Dict[str, Any]]:
    """读取归一化列（画像统计用）。payload 单独按需取，避免一次性拉全量 JSON。"""
    result = await db.execute(
        select(
            EvalSetRecord.model_type,
            EvalSetRecord.task_format,
            EvalSetRecord.answer_type,
            EvalSetRecord.question,
            EvalSetRecord.choices,
            EvalSetRecord.answer_labels,
            EvalSetRecord.answer_text,
            EvalSetRecord.subject,
            EvalSetRecord.category,
            EvalSetRecord.difficulty,
            EvalSetRecord.language,
            EvalSetRecord.pos_count,
            EvalSetRecord.neg_count,
            EvalSetRecord.question_length,
            EvalSetRecord.context_length,
            EvalSetRecord.est_tokens,
            EvalSetRecord.question_hash,
            EvalSetRecord.qa_hash,
            EvalSetRecord.payload,
        )
        .where(EvalSetRecord.dataset_id == dataset_id)
        .order_by(EvalSetRecord.seq)
        .limit(limit)
    )
    return [dict(r._mapping) for r in result.all()]


async def import_records(
    db: AsyncSession,
    dataset_id,
    records: List[Dict[str, Any]],
    model_type: str = MODEL_LLM,
    replace: bool = True,
) -> int:
    """把原始记录归一化后落库。导入幂等：replace=True 时先清空该数据集旧样本。"""
    if replace:
        await db.execute(delete(EvalSetRecord).where(EvalSetRecord.dataset_id == dataset_id))
        await db.commit()

    saved = 0
    for seq, raw in enumerate(records):
        if not isinstance(raw, dict):
            continue
        db.add(EvalSetRecord(dataset_id=dataset_id, **normalize_record(raw, seq=seq, model_type=model_type)))
        saved += 1
        # 分批提交，避免上万行时事务过大
        if saved % 2000 == 0:
            await db.commit()
    await db.commit()
    return saved


async def run_profile(
    db: AsyncSession,
    profile: EvalSetProfile,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """执行画像并写回 profile。内部按阶段 commit，保证长任务中断也能看到进度。"""

    async def _progress(value: int) -> None:
        profile.progress = max(profile.progress or 0, value)
        await db.commit()
        if progress_cb:
            try:
                progress_cb(value)
            except Exception as exc:
                logger.warning(f"评测集画像进度回调失败: {exc}")

    dataset = await db.get(Dataset, profile.dataset_id)
    if not dataset:
        raise ValueError(f"数据集 {profile.dataset_id} 不存在")

    profile.status = "running"
    profile.error = None
    await db.commit()
    await _progress(10)

    rows = await load_records(db, profile.dataset_id, MAX_PROFILE_ROWS)
    if not rows:
        raise ValueError(f"评测集「{dataset.name}」中没有样本，请先导入数据")

    total_in_db = await count_records(db, profile.dataset_id)
    sampled = total_in_db > len(rows)
    await _progress(50)

    result = build_profile(rows, model_type=profile.model_type or MODEL_LLM)
    await _progress(80)

    profile.name = profile.name or dataset.name
    profile.model_type = result["model_type"]
    profile.total_samples = result["overview"]["total"]
    profile.unique_samples = result["overview"]["unique"]
    profile.duplicate_rate = result["overview"]["duplicate_rate"]
    profile.sampled = sampled
    profile.tags = result["tags"]
    profile.overview = result["overview"]
    profile.task_profile = result["task_profile"]
    profile.answer_profile = result["answer_profile"]
    profile.capability = result["capability"]
    profile.quality = result["quality"]
    profile.schema_profile = result["schema_profile"]
    profile.samples = result["samples"]
    profile.summary = result["summary"]
    profile.status = "completed"
    profile.completed_at = datetime.utcnow()
    await db.commit()
    await _progress(100)
    return result