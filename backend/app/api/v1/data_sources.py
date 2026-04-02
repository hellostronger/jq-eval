# 数据源与同步路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import DataSource, SyncTask, SchemaMapping, DataSourceType

router = APIRouter()


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
    # TODO: 测试连接
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
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return data_source


@router.delete("/{source_id}")
async def delete_data_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除数据源"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    await db.delete(data_source)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{source_id}/test-connection")
async def test_connection(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """测试连接"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # TODO: 实现实际的连接测试
    return {
        "success": True,
        "message": "连接测试成功",
        "source_id": str(source_id)
    }


@router.get("/{source_id}/tables")
async def get_tables(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源的表/集合列表"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # TODO: 实现实际的表列表获取
    return {
        "tables": [],
        "source_id": str(source_id)
    }


@router.get("/{source_id}/schema")
async def get_schema(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取数据源Schema"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # TODO: 实现实际的Schema获取
    return {
        "schemas": [],
        "source_id": str(source_id)
    }


@router.get("/{source_id}/preview/{table}")
async def preview_data(
    source_id: UUID,
    table: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """预览表数据"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # TODO: 实现实际的数据预览
    return {
        "data": [],
        "table": table,
        "source_id": str(source_id)
    }


@router.get("/{source_id}/default-mappings")
async def get_default_mappings(
    source_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取系统默认字段映射"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # TODO: 根据系统类型返回默认映射
    return {
        "system_type": data_source.system_type,
        "mappings": {}
    }


@router.post("/{source_id}/sync")
async def execute_sync(
    source_id: UUID,
    data: SyncRequest,
    db: AsyncSession = Depends(get_db)
):
    """执行数据同步"""
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    data_source = result.scalar_one_or_none()
    if not data_source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 创建同步任务
    sync_task = SyncTask(
        source_id=source_id,
        task_type="incremental" if data.incremental else "full",
        status="pending"
    )
    db.add(sync_task)
    await db.commit()

    # TODO: 触发Celery异步任务执行同步

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