# RAG系统调用相关异步任务
from typing import Dict, List, Any
from datetime import datetime
import logging
import time
from uuid import UUID

from app.core.celery_app import celery_app
from app.tasks._common import run_async
from app.core.database import get_db_context
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.dataset import Dataset, QARecord
from app.models.rag_system import RAGSystem
from app.models.model import Model
from app.services.adapters import AdapterFactory
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


async def _prepare_direct_llm_config(connection_config: Dict[str, Any], db) -> Dict[str, Any]:
    """为直连LLM类型准备完整配置"""
    llm_model_id = connection_config.get("llm_model_id")
    if not llm_model_id:
        return connection_config

    try:
        result = await db.execute(select(Model).where(Model.id == UUID(llm_model_id)))
        model = result.scalar_one_or_none()
        if not model:
            return connection_config

        config = connection_config.copy()
        config["api_endpoint"] = model.endpoint
        config["api_key"] = model.api_key_encrypted or ""
        config["model_name"] = model.model_name or model.name
        config["provider"] = connection_config.get("provider") or model.provider or "openai"

        if model.params:
            config["temperature"] = connection_config.get("temperature") or model.params.get("temperature", 0.7)
            config["max_tokens"] = connection_config.get("max_tokens") or model.params.get("max_tokens", 2048)
            # 额外请求参数：调用方配置可覆盖模型默认
            extra = dict(model.params.get("extra_params") or {})
            extra.update(connection_config.get("extra_params") or {})
            if extra:
                config["extra_params"] = extra

        return config
    except Exception as e:
        logger.error(f"获取LLM模型配置失败: {e}")
        return connection_config


@celery_app.task(bind=True, name="invocation_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def invocation_task(self, batch_id: str) -> Dict[str, Any]:
    """执行RAG系统调用批次

    Args:
        batch_id: 调用批次ID (UUID字符串格式)
    """
    return run_async(_run_invocation(self, UUID(batch_id)))


@celery_app.task(bind=True, name="retry_invocation_task")
def retry_invocation_task(self, batch_id: str, result_ids: List[str]) -> Dict[str, Any]:
    """重试调用批次中指定的结果

    Args:
        batch_id: 调用批次ID
        result_ids: 要重试的结果ID列表
    """
    return run_async(_run_retry(self, UUID(batch_id), [UUID(rid) for rid in result_ids]))


async def _run_retry(task, batch_id: UUID, result_ids: List[UUID]) -> Dict[str, Any]:
    """异步执行重试"""
    async with get_db_context() as db:
        batch = await db.get(InvocationBatch, batch_id)
        if not batch:
            return {"error": f"调用批次 {batch_id} 不存在"}

        rag_system = await db.get(RAGSystem, batch.rag_system_id)
        if not rag_system:
            return {"error": f"RAG系统 {batch.rag_system_id} 不存在"}

        # 获取要重试的结果
        from sqlalchemy import select
        results = await db.execute(
            select(InvocationResult).where(InvocationResult.id.in_(result_ids))
        )
        retry_results = results.scalars().all()

        if not retry_results:
            return {"error": "没有找到要重试的结果"}

        # 创建RAG适配器
        config = rag_system.connection_config
        if rag_system.system_type == "direct_llm":
            config = await _prepare_direct_llm_config(config, db)
        adapter = AdapterFactory.create(
            rag_system.system_type,
            config
        )

        batch.status = "running"
        await db.commit()

        # 批量预取要重试的问题，避免循环内逐条 db.get
        qa_ids = {r.qa_record_id for r in retry_results}
        qa_result = await db.execute(select(QARecord).where(QARecord.id.in_(qa_ids)))
        qa_map = {qa.id: qa for qa in qa_result.scalars().all()}

        success_count = 0
        fail_count = 0

        try:
            for inv_result in retry_results:
                try:
                    # 删除旧结果
                    await db.delete(inv_result)
                    await db.flush()

                    # 获取原始问题
                    qa_record = qa_map.get(inv_result.qa_record_id)
                    if not qa_record:
                        fail_count += 1
                        continue

                    start_time = time.time()
                    response = await adapter.query(qa_record.question)
                    latency = time.time() - start_time

                    # 从 RAGResponse 对象获取数据
                    answer = response.answer or ""
                    contexts = response.contexts or []
                    retrieval_ids = response.retrieval_ids or []

                    # 创建新结果
                    new_result = InvocationResult(
                        batch_id=batch_id,
                        qa_record_id=qa_record.id,
                        rag_system_id=rag_system.id,
                        question=qa_record.question,
                        answer=answer,
                        contexts=contexts,
                        retrieval_ids=retrieval_ids,
                        latency=latency,
                        status="success"
                    )
                    db.add(new_result)
                    success_count += 1

                except Exception as e:
                    logger.error(f"重试调用 {inv_result.id} 失败: {e}")
                    # 创建失败结果
                    new_result = InvocationResult(
                        batch_id=batch_id,
                        qa_record_id=inv_result.qa_record_id,
                        rag_system_id=rag_system.id,
                        question=inv_result.question,
                        status="failed",
                        error=str(e)
                    )
                    db.add(new_result)
                    fail_count += 1

                await db.commit()

            # 计数不再做增量加减（重试成功项会造成重复计数），直接按结果表重算
            counts = await db.execute(
                select(InvocationResult.status, func.count(InvocationResult.id)).where(
                    InvocationResult.batch_id == batch_id
                ).group_by(InvocationResult.status)
            )
            by_status = dict(counts.all())
            batch.completed_count = by_status.get("success", 0)
            batch.failed_count = by_status.get("failed", 0)
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()

            await db.commit()

            return {
                "batch_id": str(batch_id),
                "retried": len(retry_results),
                "success": success_count,
                "failed": fail_count
            }

        except Exception as e:
            # 与 _run_invocation 对齐：任何未预期异常都必须把批次标记为失败，
            # 否则批次永久停留在 running
            logger.error(f"重试任务异常 batch_id={batch_id}: {e}")
            await db.rollback()
            batch = await db.get(InvocationBatch, batch_id)
            if batch:
                batch.status = "failed"
                await db.commit()
            raise


async def _run_invocation(task, batch_id: UUID) -> Dict[str, Any]:
    """异步执行RAG调用"""
    async with get_db_context() as db:
        # 获取调用批次
        batch = await db.get(InvocationBatch, batch_id)
        if not batch:
            return {"error": f"调用批次 {batch_id} 不存在"}

        # 更新状态
        batch.status = "running"
        batch.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取数据集
            dataset = await db.get(Dataset, batch.dataset_id)
            if not dataset:
                raise ValueError(f"数据集 {batch.dataset_id} 不存在")

            # 获取RAG系统
            rag_system = await db.get(RAGSystem, batch.rag_system_id)
            if not rag_system:
                raise ValueError(f"RAG系统 {batch.rag_system_id} 不存在")

            # 获取QA记录
            from sqlalchemy import text
            qa_records = await db.execute(
                text("""
                SELECT id, question FROM qa_records
                WHERE dataset_id = :dataset_id
                ORDER BY created_at
                """),
                {"dataset_id": dataset.id}
            )
            qa_list = [dict(r._mapping) for r in qa_records.fetchall()]
            batch.total_count = len(qa_list)
            await db.commit()

            # 创建RAG适配器
            config = rag_system.connection_config
            if rag_system.system_type == "direct_llm":
                config = await _prepare_direct_llm_config(config, db)
            adapter = AdapterFactory.create(
                rag_system.system_type,
                config
            )

            # 执行调用
            completed = 0
            failed = 0
            for qa in qa_list:
                try:
                    start_time = time.time()
                    # 调用RAG系统
                    response = await adapter.query(qa["question"])
                    latency = time.time() - start_time

                    # 从 RAGResponse 对象获取数据
                    answer = response.answer or ""
                    contexts = response.contexts or []
                    retrieval_ids = response.retrieval_ids or []

                    # 存储结果
                    result = InvocationResult(
                        batch_id=batch_id,
                        qa_record_id=qa["id"],
                        rag_system_id=rag_system.id,
                        question=qa["question"],
                        answer=answer,
                        contexts=contexts,
                        retrieval_ids=retrieval_ids,
                        latency=latency,
                        status="success"
                    )
                    db.add(result)
                    completed += 1

                except Exception as e:
                    logger.error(f"调用 QA {qa['id']} 失败: {e}")
                    # 存储失败结果
                    result = InvocationResult(
                        batch_id=batch_id,
                        qa_record_id=qa["id"],
                        rag_system_id=rag_system.id,
                        question=qa["question"],
                        status="failed",
                        error=str(e)
                    )
                    db.add(result)
                    failed += 1

                batch.completed_count = completed
                batch.failed_count = failed
                await db.commit()

                # 更新进度
                progress = (completed + failed) / len(qa_list) * 100
                task.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "completed": completed, "failed": failed, "total": len(qa_list)}
                )

            # 完成批次
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
            await db.commit()

            return {
                "batch_id": str(batch_id),
                "status": "completed",
                "total": len(qa_list),
                "completed": completed,
                "failed": failed
            }

        except Exception as e:
            logger.error(f"调用批次 {batch_id} 失败: {e}")
            await db.rollback()
            batch = await db.get(InvocationBatch, batch_id)
            if batch:
                batch.status = "failed"
                batch.error = str(e)
                batch.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": str(e)}