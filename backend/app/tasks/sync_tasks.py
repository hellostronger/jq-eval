# 数据同步相关异步任务
from typing import Dict, Any
from datetime import datetime
from uuid import UUID
import logging
import json
from sqlalchemy import text

from app.core.celery_app import celery_app
from app.tasks._common import run_async, mark_task_failed, format_error
from app.core.database import get_db_context
from app.models.sync import SyncTask, SyncTaskStatus, DataSource
from app.models.dataset import Dataset, DatasetSnapshot, QARecord
from app.models.document import Document, Chunk
from app.services.sync import SyncAdapterFactory
from app.services.sync.base import SyncConfig

logger = logging.getLogger(__name__)


# 数据同步/导入可能超过全局 30 分钟硬超时；task_acks_late 下超时 SIGKILL 会触发
# 消息重投递、任务从头重跑（无幂等键会重复插入）。与 evaluation_task 同样覆写时限。
@celery_app.task(bind=True, name="data_sync_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def data_sync_task(self, sync_task_id: str) -> Dict[str, Any]:
    """执行数据同步任务

    Args:
        sync_task_id: 同步任务ID (UUID字符串格式)
    """
    from uuid import UUID
    return run_async(_run_data_sync(self, UUID(str(sync_task_id))))


async def _run_data_sync(task, sync_task_id: UUID) -> Dict[str, Any]:
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

        adapter = None
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
                since=data_source.last_sync_at,  # 增量同步的过滤起点，缺失会导致每次全量重拉
                target_types=json.loads(sync_task.target_type) if sync_task.target_type else ["chunks", "qa_records"],
            )

            # 同步数据
            total_synced = 0
            target_types = sync_config.target_types or ["chunks", "qa_records"]

            # 获取字段映射（目标类型缺映射时立即报错——否则循环内逐条
            # transformed.get(...) 全为空、静默导入 0 条却上报 completed）
            mappings = adapter.get_default_mappings()
            for tt in target_types:
                if not mappings.get(tt):
                    raise ValueError(
                        f"{data_source.system_type} 数据源未配置 {tt} 的字段映射，无法同步该类型"
                    )

            # 同步chunks
            if "chunks" in target_types:
                chunk_mapping = mappings.get("chunks", [])
                table_name = _get_source_table(data_source.system_type, "chunks")

                count = 0
                fetched = 0
                document = Document(
                    title=f"{data_source.name}_chunks",
                    source_type="sync",
                    doc_metadata={"source_id": str(data_source.id), "system_type": data_source.system_type},
                )
                db.add(document)
                await db.flush()

                # fetch_data 是 async generator，必须 async for（await 会 TypeError）
                async for raw_data in adapter.fetch_data(table_name, sync_config):
                    fetched += 1
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
                # 拉到了源数据却一条都没转换成功：映射字段与源数据结构不符，
                # 必须以失败结束——静默 0 条 completed 会掩盖配置错误
                if fetched and not count:
                    raise ValueError(
                        f"从 {table_name} 读取了 {fetched} 行，但没有一行解析出有效 content，"
                        f"请检查 {data_source.system_type} 的 chunks 字段映射"
                    )
                total_synced += count

            # 同步QA记录
            if "qa_records" in target_types:
                qa_mapping = mappings.get("qa_records", [])
                table_name = _get_source_table(data_source.system_type, "qa_records")

                count = 0
                fetched = 0
                async for raw_data in adapter.fetch_data(table_name, sync_config):
                    fetched += 1
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
                if fetched and not count:
                    raise ValueError(
                        f"从 {table_name} 读取了 {fetched} 行，但没有一行解析出有效 question，"
                        f"请检查 {data_source.system_type} 的 qa_records 字段映射"
                    )
                total_synced += count

            # 更新数据集记录数
            dataset.record_count = total_synced
            if total_synced:
                dataset.status = "ready"

            # 断开连接
            await adapter.disconnect()
            adapter = None

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
            # 确保数据源连接被释放，避免连接泄漏
            if adapter is not None:
                try:
                    await adapter.disconnect()
                except Exception:
                    logger.warning(f"同步任务 {sync_task_id} 断开数据源连接失败")
            # 异常可能源自 flush/commit，session 处于 needs-rollback 状态；
            # 不回滚则下面的 commit 抛 PendingRollbackError，任务永远停留在 RUNNING
            await db.rollback()
            sync_task = await db.get(SyncTask, sync_task_id)
            if sync_task:
                sync_task.status = SyncTaskStatus.FAILED
                sync_task.log = {"error": format_error(e), **(sync_task.log or {})}
                sync_task.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": format_error(e)}


@celery_app.task(bind=True, name="data_import_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def data_import_task(self, dataset_id: int, file_path: str, import_type: str = "qa") -> Dict[str, Any]:
    """数据导入任务"""
    return run_async(_run_data_import(self, dataset_id, file_path, import_type))


async def _run_data_import(task, dataset_id: int, file_path: str, import_type: str) -> Dict[str, Any]:
    """异步执行数据导入"""
    async with get_db_context() as db:
        dataset = await db.get(Dataset, dataset_id)
        if not dataset:
            return {"error": f"数据集 {dataset_id} 不存在"}

        dataset.status = "importing"
        await db.commit()

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
            await mark_task_failed(db, Dataset, dataset_id, format_error(e), logger)
            return {"error": format_error(e)}


def _get_source_table(system_type: str, data_type: str) -> str:
    """获取源表名"""
    table_mapping = {
        "dify": {"chunks": "document_segments", "qa_records": "messages"},
        "fastgpt": {"chunks": "kb_data", "qa_records": "chat"},
        "n8n": {"chunks": "documents", "qa_records": "execution_entity"},
        "custom": {"chunks": "chunks", "qa_records": "qa_records"},
    }
    return table_mapping.get(system_type, {}).get(data_type, data_type)