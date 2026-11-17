# 多模态嵌入评测任务
#
# 与 RAG 评估任务一样走协作式取消：cancel 端点只置标志，worker 在批次边界
# 检查后落库 cancelled；终态守卫保证 redelivery 不会把 completed 改回 running。
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import delete, select

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.core.exceptions import TaskCancelled
from app.models import MMEvalQueryResult, MMEvalRun, MMDataset, MMSample, Model
from app.services.mm_embedding.client import MMEmbeddingClient
from app.services.mm_embedding.media import load_image, presign_image
from app.services.mm_embedding.runner import (
    bind_items,
    build_groups,
    encode_groups,
    materialize_images,
    score_groups,
    summarize,
)
from app.tasks._common import format_error, mark_task_failed, run_async
from app.tasks.persistence import commit_with_retry

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


@celery_app.task(
    bind=True,
    name="mm_embedding_eval_task",
    soft_time_limit=55 * 60,
    time_limit=60 * 60,
)
def mm_embedding_eval_task(self, run_id: str) -> Dict[str, Any]:
    return run_async(_run_mm_embedding_eval(self, UUID(run_id)))


async def _run_mm_embedding_eval(task, run_id: UUID) -> Dict[str, Any]:
    async with get_db_context() as db:
        run = await db.get(MMEvalRun, run_id)
        if not run:
            return {"error": f"评测运行 {run_id} 不存在"}
        if run.status in TERMINAL_STATUSES:
            logger.info(f"多模态评测 {run_id} 已是终态 {run.status}，跳过重复执行")
            return {"run_id": str(run_id), "status": run.status, "skipped": True}

        if run.cancel_requested:
            # pending 阶段就被用户取消：start_task 已置 running，这里直接收敛
            run.status = "cancelled"
            run.cancel_requested = False
            run.completed_at = datetime.utcnow()
            await db.commit()
            return {"run_id": str(run_id), "status": "cancelled"}

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.progress = 1
        run.error = None
        await db.commit()

        dataset = await db.get(MMDataset, run.dataset_id)
        model = await db.get(Model, run.model_id)
        if not dataset:
            await mark_task_failed(db, MMEvalRun, run_id, "评测集不存在", logger)
            return {"error": "评测集不存在"}
        if not model:
            await mark_task_failed(db, MMEvalRun, run_id, "模型配置不存在", logger)
            return {"error": "模型配置不存在"}

        samples = (
            await db.execute(
                select(MMSample)
                .where(MMSample.dataset_id == dataset.id)
                .order_by(MMSample.seq, MMSample.created_at)
            )
        ).scalars().all()
        params = dict(run.params or {})
        # rollback/commit 会让 ORM 实例过期，编码阶段不能再访问它们；
        # 先把分组需要的字段与模型配置复制出来，再结束读事务
        sample_rows = [
            SimpleNamespace(
                qid=sample.qid,
                subset=sample.subset,
                query_text=sample.query_text,
                query_image=sample.query_image,
                target_text=sample.target_text,
                target_image=sample.target_image,
                label=sample.label,
            )
            for sample in samples
        ]
        model_snapshot = SimpleNamespace(
            name=model.name,
            model_name=model.model_name,
            provider=model.provider,
            endpoint=model.endpoint,
            api_key_encrypted=model.api_key_encrypted,
            params=dict(model.params or {}),
            dimension=model.dimension,
        )
        await db.rollback()  # 结束读事务，避免长编码期间占着连接

    last_progress = {"value": 0}

    async def update_progress(percent: int, encoded: int | None = None) -> None:
        if percent <= last_progress["value"]:
            return
        last_progress["value"] = percent

        def apply(db):
            from sqlalchemy import update

            values = {"progress": percent}
            if encoded is not None:
                values["encoded_items"] = encoded
            return db.execute(update(MMEvalRun).where(MMEvalRun.id == run_id).values(**values))

        await commit_with_retry(
            apply, get_session=get_db_context, label="更新评测进度", context=str(run_id)
        )
        task.update_state(state="PROGRESS", meta={"progress": percent, "encoded": encoded})

    async def cancel_check() -> None:
        async with get_db_context() as db:
            flag = (
                await db.execute(
                    select(MMEvalRun.cancel_requested).where(MMEvalRun.id == run_id)
                )
            ).scalar()
        if flag:
            raise TaskCancelled()

    try:
        groups, skipped, _stats = build_groups(sample_rows)
        if not groups:
            raise ValueError("没有可用查询：每个查询至少需要 2 个候选（1 正 + 1 负）")

        await update_progress(3)
        client = MMEmbeddingClient(model_snapshot, params)
        image_url_builder = (
            presign_image if client.image_transport == "url" else None
        )
        images = await materialize_images(
            groups,
            load_image,
            image_url_builder=image_url_builder,
            load_bytes=client.image_transport == "data_url",
        )
        bind_items(groups, images)
        await update_progress(5)

        async def on_encode(encoded: int, total: int) -> None:
            percent = 5 + int(65 * encoded / max(total, 1))
            await update_progress(min(percent, 70), encoded=encoded)

        vectors = await encode_groups(
            client, groups, progress_cb=on_encode, cancel_cb=cancel_check
        )
        await update_progress(72, encoded=len(vectors))

        outcomes = score_groups(
            groups, vectors, top_k=int(params.get("top_k") or 10)
        )
        overall, subset_metrics = summarize(outcomes)
        await update_progress(80)

        await _persist_outcomes(run_id, outcomes)
        await update_progress(95)

        def finalize(db):
            from sqlalchemy import update

            return db.execute(
                update(MMEvalRun)
                .where(MMEvalRun.id == run_id)
                .values(
                    status="completed",
                    progress=100,
                    error=None,
                    metrics=overall,
                    subset_metrics=subset_metrics,
                    query_count=len(outcomes),
                    skipped_queries=skipped,
                    encoded_items=len(vectors),
                    completed_at=datetime.utcnow(),
                )
            )

        await commit_with_retry(
            finalize, get_session=get_db_context, label="更新评测终态", context=str(run_id)
        )
        return {
            "run_id": str(run_id),
            "status": "completed",
            "query_count": len(outcomes),
            "metrics": overall,
        }
    except TaskCancelled:
        await _finalize_cancelled(run_id)
        return {"run_id": str(run_id), "status": "cancelled"}
    except Exception as exc:
        error = format_error(exc)
        logger.exception(f"多模态评测 {run_id} 失败: {error}")
        async with get_db_context() as db:
            await mark_task_failed(db, MMEvalRun, run_id, error, logger)
        return {"run_id": str(run_id), "status": "failed", "error": error}


async def _persist_outcomes(run_id: UUID, outcomes) -> None:
    """分批写明细，单批失败只重试该批"""
    for start in range(0, len(outcomes), 1000):
        chunk = outcomes[start : start + 1000]

        async def apply(db, chunk=chunk, start=start):
            # 重跑时首批判删旧明细，保证 apply 幂等；后续批只插入
            if start == 0:
                await db.execute(
                    delete(MMEvalQueryResult).where(MMEvalQueryResult.run_id == run_id)
                )
            db.add_all(
                [
                    MMEvalQueryResult(
                        run_id=run_id,
                        subset=outcome.subset,
                        qid=outcome.qid,
                        rank=outcome.rank,
                        candidate_count=outcome.candidate_count,
                        positive_count=outcome.positive_count,
                        metrics=outcome.metrics,
                        retrieved_top=outcome.retrieved_top,
                    )
                    for outcome in chunk
                ]
            )

        await commit_with_retry(
            apply,
            get_session=get_db_context,
            label=f"写入评测明细({start + 1}-{start + len(chunk)})",
            context=str(run_id),
        )


async def _finalize_cancelled(run_id: UUID) -> None:
    def apply(db):
        from sqlalchemy import update

        return db.execute(
            update(MMEvalRun)
            .where(MMEvalRun.id == run_id)
            .values(
                status="cancelled",
                cancel_requested=False,
                completed_at=datetime.utcnow(),
            )
        )

    await commit_with_retry(
        apply, get_session=get_db_context, label="写入取消终态", context=str(run_id)
    )
