# API 全链路入库任务模型
from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from ..core.db_types import JSONType, UUIDType
from .base import BaseModel


class ApiIngestTask(BaseModel):
    """把本地文档通过被测系统 API 入库，并生成评测数据集的任务"""

    __tablename__ = "api_ingest_tasks"

    rag_system_id = Column(
        UUIDType(as_uuid=True), ForeignKey("rag_systems.id"), nullable=False, index=True
    )
    dataset_id = Column(
        UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=True, index=True
    )

    # 远端资源
    remote_kb_id = Column(String(200), nullable=True)
    remote_kb_name = Column(String(200), nullable=True)
    remote_chat_id = Column(String(200), nullable=True)

    # 任务状态：pending/running/completed/failed
    status = Column(String(50), default="pending", index=True)
    stage = Column(String(50), nullable=True)  # ensuring_kb/uploading/parsing/chunking/generating/saving
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)

    # [{name, size, remote_doc_id, status, error}]
    files = Column(JSONType, default=list)
    # 入库配置（test_size/llm_model_id/embedding_model_id/auto_generate 等）
    config = Column(JSONType, default=dict)

    celery_task_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
