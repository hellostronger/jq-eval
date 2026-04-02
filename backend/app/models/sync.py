# 数据同步相关模型
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime

from .base import BaseModel


class DataSource(BaseModel):
    """数据源配置表"""
    __tablename__ = "data_sources"

    name = Column(String(200), nullable=False)
    source_type = Column(String(50), nullable=False)  # database/api/file/huggingface/cloud
    system_type = Column(String(50), nullable=True)  # dify/fastgpt/n8n/coze/custom

    # 连接配置
    connection_config = Column(JSONB, nullable=False)

    # 同步配置
    sync_config = Column(JSONB, default=dict)

    # 同步目标
    target_tables = Column(JSONB, default=dict)

    # 状态
    status = Column(String(50), default="active")
    last_sync_at = Column(DateTime, nullable=True)
    sync_status = Column(String(50), nullable=True)  # success/failed/in_progress
    sync_error = Column(Text, nullable=True)

    # 统计
    total_synced = Column(Integer, default=0)

    # 所属用户
    owner_id = Column(UUID(as_uuid=True), nullable=True)


class SyncTask(BaseModel):
    """同步任务记录表"""
    __tablename__ = "sync_tasks"

    source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False, index=True)

    # 任务信息
    task_type = Column(String(50), nullable=True)  # full/incremental/schema_detect
    target_type = Column(String(50), nullable=True)  # documents/chunks/qa_records

    # 执行状态
    status = Column(String(50), default="pending")  # pending/running/completed/failed
    progress = Column(Integer, default=0)

    # 结果统计
    total_records = Column(Integer, default=0)
    synced_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)

    # 详细日志
    log = Column(JSONB, default=dict)

    # 时间
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class SchemaMapping(BaseModel):
    """Schema映射记录表"""
    __tablename__ = "schema_mappings"

    source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False, index=True)

    # 源表/集合名称
    source_table = Column(String(100), nullable=True)

    # 目标表类型
    target_type = Column(String(50), nullable=True)  # document/chunk/qa_record

    # 字段映射
    field_mappings = Column(JSONB, nullable=False)

    # 过滤条件
    filter_condition = Column(JSONB, default=dict)


class DataSourceType(BaseModel):
    """数据源类型定义表（系统内置）"""
    __tablename__ = "data_source_types"

    type_code = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # 连接配置Schema
    connection_schema = Column(JSONB, nullable=False)

    # 可同步的数据类型
    sync_targets = Column(JSONB, nullable=False)

    # Schema映射模板
    schema_mappings = Column(JSONB, default=dict)

    # 系统信息
    system_type = Column(String(50), nullable=True)
    db_type = Column(String(50), nullable=True)  # postgresql/mongodb/sqlite/mysql

    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)