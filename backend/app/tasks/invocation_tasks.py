# RAG系统调用相关异步任务
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import logging
import time
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.dataset import Dataset, QARecord
from app.models.rag_system import RAGSystem
from app.services.adapters import AdapterFactory

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="invocation_task")
def invocation_task(self, batch_id: str) -> Dict[str, Any]:
    """执行RAG系统调用批次

    Args:
        batch_id: 调用批次ID (UUID字符串格式)
    """
    return run_async(_run_invocation(self, UUID(batch_id)))


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
            adapter = AdapterFactory.create_adapter(
                rag_system.system_type,
                rag_system.connection_config
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

                    # 解析响应
                    answer = response.get("answer") or response.get("response") or response.get("content", "")
                    contexts = response.get("contexts") or response.get("retrieved_chunks", [])

                    # 存储结果
                    result = InvocationResult(
                        batch_id=batch_id,
                        qa_record_id=qa["id"],
                        rag_system_id=rag_system.id,
                        question=qa["question"],
                        answer=answer,
                        contexts=contexts,
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
                "batch_id": batch_id,
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