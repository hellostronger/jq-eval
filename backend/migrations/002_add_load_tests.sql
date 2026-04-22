-- 创建压测任务表
CREATE TABLE IF NOT EXISTS load_tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    rag_system_id UUID NOT NULL REFERENCES rag_systems(id),
    test_type VARCHAR(50) NOT NULL DEFAULT 'full_response',
    latency_threshold FLOAT NOT NULL,
    concurrency INTEGER NOT NULL DEFAULT 1,
    dataset_id UUID REFERENCES datasets(id),
    questions JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    error TEXT,
    result JSONB,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_load_tests_rag_system_id ON load_tests(rag_system_id);
CREATE INDEX IF NOT EXISTS idx_load_tests_dataset_id ON load_tests(dataset_id);
CREATE INDEX IF NOT EXISTS idx_load_tests_status ON load_tests(status);