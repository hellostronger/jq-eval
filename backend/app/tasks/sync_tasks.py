# 数据同步相关异步任务
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import logging
import json

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.sync import SyncTask, SyncTaskStatus, DataSource
from app.models.dataset import Dataset, DatasetSnapshot, QARecord
from app.models.document import Document, Chunk
from app.services.sync import SyncAdapterFactory
from app.services.sync.base import SyncConfig
from app.services.milvus.client import MilvusClient

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
def data_sync_task(self, sync_task_id: int) -> Dict[str, Any]:
    """执行数据同步任务"""
    return run_async(_run_data_sync(self, sync_task_id))


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
            data_source = await db.get(DataSource, sync_task.data_source_id)
            if not data_source:
                raise ValueError(f"数据源 {sync_task.data_source_id} 不存在")

            # 创建适配器
            adapter = SyncAdapterFactory.create(
                data_source.system_type,
                data_source.connection_config
            )

            # 连接数据源
            await adapter.connect()

            # 创建数据集
            dataset = Dataset(
                name=f"{data_source.name}_sync_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                description=f"从 {data_source.name} 同步的数据",
                rag_system_id=data_source.rag_system_id,
                created_at=datetime.utcnow()
            )
            db.add(dataset)
            await db.commit()
            await db.refresh(dataset)

            # 创建快照
            snapshot = DatasetSnapshot(
                dataset_id=dataset.id,
                snapshot_version=1,
                description="初始同步数据",
                created_at=datetime.utcnow()
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(snapshot)

            # 同步配置
            sync_config = SyncConfig(
                batch_size=sync_task.batch_size or 100,
                incremental=sync_task.incremental,
                since=sync_task.last_sync_at
            )

            # 同步数据
            total_synced = 0
            target_types = sync_task.target_types or ["chunks", "qa_records"]
            milvus_client = MilvusClient()

            # 获取字段映射
            mappings = adapter.get_default_mappings()

            # 同步chunks
            if "chunks" in target_types:
                chunk_mapping = mappings.get("chunks", [])
                table_name = _get_source_table(data_source.system_type, "chunks")

                count = 0
                for raw_data in await adapter.fetch_data(table_name, sync_config):
                    # 转换数据
                    transformed = adapter.transform_data(raw_data, chunk_mapping, "chunks")

                    # 创建Chunk记录
                    chunk = Chunk(
                        id=transformed.get("id"),
                        document_id=transformed.get("doc_id"),
                        content=transformed.get("content"),
                        chunk_index=transformed.get("chunk_index"),
                        metadata=transformed.get("metadata", {}),
                        created_at=transformed.get("created_at", datetime.utcnow())
                    )
                    db.add(chunk)

                    # 插入向量（如果有embedding）
                    if data_source.rag_system_id:
                        rag_system = await db.execute(
                            "SELECT * FROM rag_systems WHERE id = :id",
                            {"id": data_source.rag_system_id}
                        )
                        rag = rag_system.fetchone()
                        if rag and rag.get("embedding_model_id"):
                            # 使用RAG系统的embedding模型生成向量
                            # 这里简化处理，实际需要调用embedding服务
                            pass

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

                    # 创建QARecord
                    qa_record = QARecord(
                        id=transformed.get("id"),
                        snapshot_id=snapshot.id,
                        question=transformed.get("question"),
                        answer=transformed.get("answer"),
                        contexts=transformed.get("contexts", []),
                        ground_truth=transformed.get("ground_truth"),
                        metadata=raw_data,  # 保存原始数据
                        created_at=transformed.get("created_at", datetime.utcnow())
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

            # 断开连接
            await adapter.disconnect()

            # 更新任务状态
            sync_task.status = SyncTaskStatus.COMPLETED
            sync_task.completed_at = datetime.utcnow()
            sync_task.records_synced = total_synced
            sync_task.dataset_id = dataset.id
            sync_task.last_sync_at = datetime.utcnow()
            await db.commit()

            return {
                "sync_task_id": sync_task_id,
                "status": "completed",
                "dataset_id": dataset.id,
                "total_synced": total_synced
            }

        except Exception as e:
            logger.error(f"同步任务 {sync_task_id} 失败: {e}")
            sync_task.status = SyncTaskStatus.FAILED
            sync_task.error_message = str(e)
            sync_task.completed_at = datetime.utcnow()
            await db.commit()
            return {"error": str(e)}}


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
                """
                SELECT MAX(snapshot_version) as max_version
                FROM dataset_snapshots WHERE dataset_id = :dataset_id
                """,
                {"dataset_id": dataset_id}
            )
            max_version = latest_snapshot.fetchone()["max_version"] or 0

            snapshot = DatasetSnapshot(
                dataset_id=dataset_id,
                snapshot_version=max_version + 1,
                description=f"导入 {import_type} 数据",
                created_at=datetime.utcnow()
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(snapshot)

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
                    qa_record = QARecord(
                        snapshot_id=snapshot.id,
                        question=row.get("question") or row.get("query"),
                        answer=row.get("answer"),
                        contexts=row.get("contexts", []),
                        ground_truth=row.get("ground_truth"),
                        metadata=row.to_dict(),
                        created_at=datetime.utcnow()
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

            return {
                "dataset_id": dataset_id,
                "snapshot_id": snapshot.id,
                "imported": count,
                "status": "completed"
            }

        except Exception as e:
            logger.error(f"数据导入失败: {e}")
            return {"error": str(e)}}


def _get_source_table(system_type: str, data_type: str) -> str:
    """获取源表名"""
    table_mapping = {
        "dify": {"chunks": "document_segments", "qa_records": "messages"},
        "fastgpt": {"chunks": "kb_data", "qa_records": "chat"},
        "n8n": {"chunks": "documents", "qa_records": "execution_entity"},
        "custom": {"chunks": "chunks", "qa_records": "qa_records"},
    }
    return table_mapping.get(system_type, {}).get(data_type, data_type)