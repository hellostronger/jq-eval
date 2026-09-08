# 数据源与同步路由
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ._common import get_or_404
from ...models import DataSource, SyncTask, SchemaMapping, DataSourceType

router = APIRouter()

logger = logging.getLogger(__name__)


# Pydantic Schemas
class DataSourceCreate(BaseModel):
    name: str
    source_type: str  # database/api/file/huggingface/cloud
    system_type: Optional[str] = None  # dify/fastgpt/n8n/coze/custom
    connection_config: Dict[str, Any]
    sync_config: Optional[Dict[str, Any]] = None


class DataSourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: str
    system_type: Optional[str]
    status: str
    sync_status: Optional[str]
    total_synced: int

    class Config:
        from_attributes = True


class SyncRequest(BaseModel):
    dataset_id: UUID
    tables: List[str]
    mappings: Dict[str, List[Dict[str, Any]]]
    incremental: bool = False


class FieldMappingRequest(BaseModel):
    source_field: str
    target_field: str
    transform: Optional[str] = None


@router.get("/supported-systems")
async def get_supported_systems():
    """获取支持的数据源系统列表"""
    return [
        {
            "system_type": "dify",
            "display_name": "Dify",
            "db_type": "postgresql",
            "sync_targets": ["document_segments", "messages"],
            "description": "同步Dify知识库分片和对话消息"
        },
        {
            "system_type": "fastgpt",
            "display_name": "FastGPT",
            "db_type": "mongodb",
            "sync_targets": ["kb_data", "chat"],
            "description": "同步FastGPT知识库数据和对话记录"
        },
        {
            "system_type": "n8n",
            "display_name": "n8n",
            "db_type": "postgresql/sqlite/mysql",
            "sync_targets": ["execution_entity"],
            "description": "同步n8n工作流执行记录"
        },
        {
            "system_type": "custom",
            "display_name": "自定义数据库",
            "db_type": "postgresql/mongodb",
            "sync_targets": ["任意表"],
            "description": "自定义数据库同步，需配置字段映射"
        }
    ]


@router.post("", response_model=DataSourceResponse)
async def create_data_source(
    data: DataSourceCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建数据源"""
    data_source = DataSource(
        name=data.name,
        source_type=data.source_type,
        system_type=data.system_type,
        connection_config=data.connection_config,
        sync_config=data.sync_config or {}
    )
    db.add(data_source)
    await db.commit()
    await db.refresh(data_source)
    return data_source


@router.get("", response_model=List[DataSourceResponse])
async def list_data_sources(
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源列表"""
    query = select(DataSource)
    if source_type:
        query = query.where(DataSource.source_type == source_type)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{source_id}", response_model=DataSourceResponse)
async def get_data_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源详情"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")
    return data_source


@router.delete("/{source_id}")
async def delete_data_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除数据源"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    await db.delete(data_source)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{source_id}/test-connection")
async def test_connection(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """测试连接"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    # 用对应适配器真实探测连接
    try:
        from ...services.sync import SyncAdapterFactory
        adapter = SyncAdapterFactory.create(data_source.system_type or "custom", data_source.connection_config)
        probe = await adapter.test_connection()
        await adapter.disconnect()
        return {
            "success": bool(probe.get("success")),
            "message": probe.get("error") or "连接测试成功",
            "source_id": str(source_id),
            **{k: v for k, v in probe.items() if k not in ("success", "error")},
        }
    except Exception as e:
        return {"success": False, "message": f"连接测试失败: {e}", "source_id": str(source_id)}


@router.get("/{source_id}/tables")
async def get_tables(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源的表/集合列表"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    try:
        from ...services.sync import SyncAdapterFactory
        adapter = SyncAdapterFactory.create(data_source.system_type or "custom", data_source.connection_config)
        await adapter.connect()
        tables = await adapter.get_tables()
        await adapter.disconnect()
        return {"tables": tables, "source_id": str(source_id)}
    except Exception as e:
        logger.error(f"获取数据源表列表失败 source_id={source_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"获取表列表失败: {e}")


@router.get("/{source_id}/schema")
async def get_schema(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源Schema"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    try:
        from ...services.sync import SyncAdapterFactory
        adapter = SyncAdapterFactory.create(data_source.system_type or "custom", data_source.connection_config)
        await adapter.connect()
        schemas = await adapter.get_schema()
        await adapter.disconnect()
        return {
            "schemas": [s.model_dump() for s in schemas],
            "source_id": str(source_id)
        }
    except Exception as e:
        logger.error(f"获取数据源Schema失败 source_id={source_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"获取Schema失败: {e}")


@router.get("/{source_id}/preview/{table}")
async def preview_data(
    source_id: UUID,
    table: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """预览表数据"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    try:
        from ...services.sync import SyncAdapterFactory
        from ...services.sync.base import SyncConfig
        adapter = SyncAdapterFactory.create(data_source.system_type or "custom", data_source.connection_config)
        await adapter.connect()
        sync_config = SyncConfig(batch_size=limit)
        rows = []
        async for row in adapter.fetch_data(table, sync_config):
            rows.append(row)
            if len(rows) >= limit:
                break
        await adapter.disconnect()
        return {"data": rows, "table": table, "source_id": str(source_id)}
    except Exception as e:
        logger.error(f"预览数据失败 source_id={source_id} table={table}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"预览数据失败: {e}")


@router.get("/{source_id}/default-mappings")
async def get_default_mappings(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取系统默认字段映射"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    from ...services.sync import SyncAdapterFactory
    adapter = SyncAdapterFactory.create(data_source.system_type or "custom", data_source.connection_config)
    mappings = adapter.get_default_mappings()
    return {
        "system_type": data_source.system_type,
        "mappings": {table: [m.model_dump() for m in fields] for table, fields in mappings.items()}
    }


@router.post("/{source_id}/sync")
async def execute_sync(
    source_id: UUID,
    data: SyncRequest,
    db: AsyncSession = Depends(get_db)
):
    """执行数据同步"""
    data_source = await get_or_404(db, DataSource, source_id, "数据源不存在")

    # 验证数据集存在
    from ...models import Dataset
    dataset = await db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="目标数据集不存在")

    # 创建同步任务并触发 Celery 异步执行
    sync_task = SyncTask(
        source_id=source_id,
        task_type="incremental" if data.incremental else "full",
        target_type=json.dumps(data.tables) if data.tables else None,
        status="pending",
        log={
            "dataset_id": str(data.dataset_id),
            "tables": data.tables,
            "mappings": data.mappings,
        },
    )
    db.add(sync_task)
    await db.commit()

    from ...tasks.sync_tasks import data_sync_task
    data_sync_task.delay(sync_task.id)

    return {
        "task_id": str(sync_task.id),
        "status": "pending",
        "message": "同步任务已创建"
    }


@router.get("/{source_id}/sync-tasks")
async def list_sync_tasks(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取同步任务列表"""
    result = await db.execute(
        select(SyncTask)
        .where(SyncTask.source_id == source_id)
        .order_by(SyncTask.created_at.desc())
    )
    tasks = result.scalars().all()

    return [{
        "id": str(t.id),
        "task_type": t.task_type,
        "status": t.status,
        "synced_records": t.synced_records,
        "created_at": t.created_at
    } for t in tasks]


@router.get("/sync-tasks/{task_id}")
async def get_sync_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取同步任务详情"""
    result = await db.execute(select(SyncTask).where(SyncTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="同步任务不存在")

    return {
        "id": str(task.id),
        "source_id": str(task.source_id),
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "total_records": task.total_records,
        "synced_records": task.synced_records,
        "failed_records": task.failed_records,
        "log": task.log
    }