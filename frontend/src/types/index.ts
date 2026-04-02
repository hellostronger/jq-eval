// 类型定义

export type ModelType = 'llm' | 'embedding' | 'reranker'

export interface ModelConfig {
  id: number
  name: string
  model_type: ModelType
  provider: string
  model_name: string
  api_base: string
  api_key: string
  temperature?: number
  max_tokens?: number
  dimension?: number
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface RAGSystem {
  id: number
  name: string
  system_type: string
  display_name: string
  api_endpoint: string
  api_key: string
  llm_model_id?: number
  embedding_model_id?: number
  reranker_model_id?: number
  config: Record<string, any>
  is_active: boolean
  created_at: string
}

export interface Dataset {
  id: number
  name: string
  description: string
  rag_system_id?: number
  total_records: number
  created_at: string
}

export interface QARecord {
  id: number
  snapshot_id: number
  question: string
  answer?: string
  contexts?: string[]
  ground_truth?: string
  metadata?: Record<string, any>
  created_at: string
}

export interface Evaluation {
  id: number
  name: string
  description?: string
  dataset_id: number
  rag_system_id?: number
  llm_model_id: number
  embedding_model_id?: number
  metrics: string[]
  batch_size: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  summary?: Record<string, any>
  created_at: string
}

export interface EvalResult {
  id: number
  evaluation_id: number
  qa_record_id: number
  metric_scores: Record<string, { score: number; error?: string }>
  created_at: string
}

export interface MetricDefinition {
  id: number
  name: string
  display_name: string
  category: string
  framework: string
  description: string
  requires_llm: boolean
  requires_embedding: boolean
  requires_ground_truth: boolean
  requires_contexts: boolean
  params_schema?: Record<string, any>
}

export interface DataSource {
  id: number
  name: string
  system_type: string
  connection_config: Record<string, any>
  rag_system_id?: number
  created_at: string
}

export interface SyncTask {
  id: number
  data_source_id: number
  target_types: string[]
  incremental: boolean
  batch_size: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  records_synced?: number
  dataset_id?: number
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface MetricCategory {
  name: string
  count: number
}

export interface SystemStats {
  total_datasets: number
  total_qa_records: number
  evaluations: {
    total: number
    completed: number
    running: number
    pending: number
    failed: number
  }
  total_rag_systems: number
  models: {
    llm: number
    embedding: number
    reranker: number
  }
}