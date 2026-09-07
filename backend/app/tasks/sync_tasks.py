# 数据同步相关异步任务
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import logging
import json
from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.sync import SyncTask, SyncTaskStatus, DataSource
from app.models.dataset import Dataset, DatasetSnapshot, QARecord
from app.models.document import Document, Chunk
from app.services.sync import SyncAdapterFactory
from app.services.sync.base import SyncConfig

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="data_sync_task")
def data_sync_task(self, sync_task_id: str) -> Dict[str, Any]:
    """执行数据同步任务

    Args:
        sync_task_id: 同步任务ID (UUID字符串格式)
    """
    from uuid import UUID
    return run_async(_run_data_sync(self, UUID(str(sync_task_id))))


async def _run_data_sync(task, sync_task_id: int) -> Dict[str, Any]:
    """异步执行数据同步"""
    async with get_db_context() as db:
        # 获取同步任务配置
        sync_task = await db.get(SyncTask, sync_task_id)
        if not sync_task:
            return {"error": f"同步任务 {sync_task_id} 不存在"}

        # 更新状态
        sync_task.status = SyncTaskStatus.RUNNING
        sync_task.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取数据源配置
            data_source = await db.get(DataSource, sync_task.source_id)
            if not data_source:
                raise ValueError(f"数据源 {sync_task.source_id} 不存在")

            # 创建适配器
            adapter = SyncAdapterFactory.create(
                data_source.system_type,
                data_source.connection_config
            )

            # 连接数据源
            await adapter.connect()

            # 创建数据集（若同步请求带 dataset_id 则复用，否则新建）
            task_log = sync_task.log or {}
            if task_log.get("dataset_id"):
                dataset = await db.get(Dataset, task_log["dataset_id"])
                if not dataset:
                    raise ValueError(f"目标数据集 {task_log['dataset_id']} 不存在")
            else:
                dataset = Dataset(
                    name=f"{data_source.name}_sync_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    description=f"从 {data_source.name} 同步的数据",
                    source_type="sync",
                )
                db.add(dataset)
                await db.commit()
                await db.refresh(dataset)

            # 创建快照
            snapshot = DatasetSnapshot(
                dataset_id=dataset.id,
                version=1,
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(snapshot)

            # 同步配置
            sync_config = SyncConfig(
                batch_size=100,
                incremental=sync_task.task_type == "incremental",
                target_types=json.loads(sync_task.target_type) if sync_task.target_type else ["chunks", "qa_records"],
            )

            # 同步数据
            total_synced = 0
            target_types = sync_config.target_types or ["chunks", "qa_records"]
            sync_errors = []

            # 获取字段映射
            mappings = adapter.get_default_mappings()

            # 同步chunks（Chunk 挂在 Document 下：每个来源分片建一个同步 Document）
            if "chunks" in target_types:
                chunk_mapping = mappings.get("chunks", [])
                table_name = _get_source_table(data_source.system_type, "chunks")

                count = 0
                document = Document(
                    title=f"{data_source.name}_chunks",
                    source_type="sync",
                    doc_metadata={"source_id": str(data_source.id), "system_type": data_source.system_type},
                )
                db.add(document)
                await db.flush()

                for raw_data in await adapter.fetch_data(table_name, sync_config):
                    # 转换数据
                    transformed = adapter.transform_data(raw_data, chunk_mapping, "chunks")

                    content = transformed.get("content")
                    if not content:
                        continue

                    chunk = Chunk(
                        doc_id=document.id,
                        content=content,
                        chunk_index=transformed.get("chunk_index") or count,
                        chunk_metadata=transformed.get("metadata") or {},
                    )
                    db.add(chunk)

                    count += 1
                    if count % sync_config.batch_size == 0:
                        await db.commit()
                        task.update_state(
                            state="PROGRESS",
                            meta={"type": "chunks", "synced": count}
                        )

                await db.commit()
                total_synced += count

            # 同步QA记录
            if "qa_records" in target_types:
                qa_mapping = mappings.get("qa_records", [])
                table_name = _get_source_table(data_source.system_type, "qa_records")

                count = 0
                for raw_data in await adapter.fetch_data(table_name, sync_config):
                    # 转换数据
                    transformed = adapter.transform_data(raw_data, qa_mapping, "qa_records")

                    question = transformed.get("question")
                    if not question:
                        continue

                    qa_record = QARecord(
                        dataset_id=dataset.id,
                        question=question,
                        answer=transformed.get("answer"),
                        ground_truth=transformed.get("ground_truth"),
                        snapshot={"contexts": transformed.get("contexts") or []},
                        qa_metadata={"raw": raw_data},  # 保存原始数据
                    )
                    db.add(qa_record)

                    count += 1
                    if count % sync_config.batch_size == 0:
                        await db.commit()
                        task.update_state(
                            state="PROGRESS",
                            meta={"type": "qa_records", "synced": count}
                        )

                await db.commit()
                total_synced += count

            # 更新数据集记录数
            dataset.record_count = total_synced
            if total_synced:
                dataset.status = "ready"

            # 断开连接
            await adapter.disconnect()

            # 更新任务状态
            sync_task.status = SyncTaskStatus.COMPLETED
            sync_task.synced_records = total_synced
            sync_task.progress = 100
            sync_task.completed_at = datetime.utcnow()
            data_source.last_sync_at = datetime.utcnow()
            data_source.sync_status = "success"
            data_source.total_synced = (data_source.total_synced or 0) + total_synced
            await db.commit()

            return {
                "sync_task_id": str(sync_task_id),
                "status": "completed",
                "dataset_id": str(dataset.id),
                "total_synced": total_synced,
            }

        except Exception as e:
            logger.error(f"同步任务 {sync_task_id} 失败: {e}")
            sync_task.status = SyncTaskStatus.FAILED
            sync_task.log = {"error": str(e), **(sync_task.log or {})}
            sync_task.completed_at = datetime.utcnow()
            await db.commit()
            return {"error": str(e)}


@celery_app.task(bind=True, name="data_import_task")
def data_import_task(self, dataset_id: int, file_path: str, import_type: str = "qa") -> Dict[str, Any]:
    """数据导入任务"""
    return run_async(_run_data_import(self, dataset_id, file_path, import_type))


async def _run_data_import(task, dataset_id: int, file_path: str, import_type: str) -> Dict[str, Any]:
    """异步执行数据导入"""
    async with get_db_context() as db:
        dataset = await db.get(Dataset, dataset_id)
        if not dataset:
            return {"error": f"数据集 {dataset_id} 不存在"}

        try:
            # 创建新快照
            latest_snapshot = await db.execute(
                text("""
                SELECT MAX(version) as max_version
                FROM dataset_snapshots WHERE dataset_id = :dataset_id
                """),
                {"dataset_id": dataset_id}
            )
            max_version = latest_snapshot.fetchone()["max_version"] or 0

            snapshot = DatasetSnapshot(
                dataset_id=dataset_id,
                version=max_version + 1,
                snapshot_data={"import_type": import_type, "file_path": file_path},
            )
            db.add(snapshot)
            await db.commit()

            # 读取文件
            import pandas as pd
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path)
            elif file_path.endswith(".json"):
                df = pd.read_json(file_path)
            elif file_path.endswith(".xlsx"):
                df = pd.read_excel(file_path)
            else:
                raise ValueError(f"不支持的文件格式: {file_path}")

            # 导入数据
            count = 0
            batch_size = 100

            if import_type == "qa":
                for _, row in df.iterrows():
                    row_dict = row.to_dict()
                    qa_record = QARecord(
                        dataset_id=dataset_id,
                        question=row.get("question") or row.get("query"),
                        answer=row.get("answer"),
                        ground_truth=row.get("ground_truth"),
                        snapshot={"contexts": row.get("contexts") or []},
                        qa_metadata=row_dict,
                    )
                    db.add(qa_record)
                    count += 1

                    if count % batch_size == 0:
                        await db.commit()
                        task.update_state(
                            state="PROGRESS",
                            meta={"imported": count, "total": len(df)}
                        )

            await db.commit()

            # 更新数据集记录数
            dataset.record_count = (dataset.record_count or 0) + count
            if count:
                dataset.status = "ready"
                dataset.has_contexts = bool(df.columns.str.contains("contexts").any())
                dataset.has_ground_truth = bool(df.columns.str.contains("ground_truth").any())
            await db.commit()

            return {
                "dataset_id": str(dataset_id),
                "imported": count,
                "status": "completed"
            }

        except Exception as e:
            logger.error(f"数据导入失败: {e}")
            return {"error": str(e)}


def _get_source_table(system_type: str, data_type: str) -> str:
    """获取源表名"""
    table_mapping = {
        "dify": {"chunks": "document_segments", "qa_records": "messages"},
        "fastgpt": {"chunks": "kb_data", "qa_records": "chat"},
        "n8n": {"chunks": "documents", "qa_records": "execution_entity"},
        "custom": {"chunks": "chunks", "qa_records": "qa_records"},
    }
    return table_mapping.get(system_type, {}).get(data_type, data_type)