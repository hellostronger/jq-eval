-- API 全链路入库任务表
-- 旧库升级用；开发环境由 Base.metadata.create_all 自动建表。
CREATE TABLE IF NOT EXISTS api_ingest_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rag_system_id UUID NOT NULL REFERENCES rag_systems(id),
    dataset_id UUID REFERENCES datasets(id),
    remote_kb_id VARCHAR(200),
    remote_kb_name VARCHAR(200),
    remote_chat_id VARCHAR(200),
    status VARCHAR(50) DEFAULT 'pending',
    stage VARCHAR(50),
    progress INTEGER DEFAULT 0,
    error TEXT,
    total_files INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    files JSONB DEFAULT '[]'::jsonb,
    config JSONB DEFAULT '{}'::jsonb,
    celery_task_id VARCHAR(100),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_ingest_tasks_rag_system_id ON api_ingest_tasks(rag_system_id);
CREATE INDEX IF NOT EXISTS idx_api_ingest_tasks_dataset_id ON api_ingest_tasks(dataset_id);
CREATE INDEX IF NOT EXISTS idx_api_ingest_tasks_status ON api_ingest_tasks(status);
