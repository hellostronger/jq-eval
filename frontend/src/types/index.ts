// 类型定义

export type ModelType = 'llm' | 'embedding' | 'reranker'

export interface ModelConfig {
  id: string
  name: string
  model_type: ModelType
  provider: string
  model_name: string
  endpoint: string
  api_key_masked?: string  // 掩码显示，如 "sk-***abc"
  params: {
    temperature: number
    max_tokens: number
  }
  api_key?: string  // 仅用于创建/更新时传递
  dimension?: number
  max_input_length?: number
  is_default: boolean
  status: string
}

export interface RAGSystem {
  id: string
  name: string
  system_type: string
  description?: string
  connection_config: Record<string, any>
  llm_config?: Record<string, any>
  retrieval_config?: Record<string, any>
  status: string
  health_status?: string
  total_calls: number
  created_at: string
}

export interface Dataset {
  id: string
  name: string
  description: string
  rag_system_id?: string
  total_records: number
  created_at: string
}

export interface QARecord {
  id: string
  snapshot_id: string
  question: string
  answer?: string
  contexts?: string[]
  ground_truth?: string
  metadata?: Record<string, any>
  created_at: string
}

export interface Evaluation {
  id: string
  name: string
  description?: string
  dataset_id: string
  rag_system_id?: string
  llm_model_id: string
  embedding_model_id?: string
  invocation_batch_id?: string  // 关联的调用批次
  reuse_invocation?: boolean  // 是否复用存量调用结果
  metrics: string[]
  batch_size: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  summary?: Record<string, any>
  created_at: string
}

// 调用批次类型
export interface InvocationBatch {
  id: string
  name: string
  dataset_id: string
  rag_system_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  total_count: number
  completed_count: number
  failed_count: number
  error?: string
  started_at?: string
  completed_at?: string
  created_at: string
}

// 调用结果类型
export interface InvocationResult {
  id: string
  batch_id: string
  qa_record_id: string
  rag_system_id: string
  question: string
  answer?: string
  contexts?: string[]
  latency?: number
  status: 'pending' | 'success' | 'failed'
  error?: string
  created_at: string
}

export interface EvalResult {
  id: string
  evaluation_id: string
  qa_record_id: string
  metric_scores: Record<string, { score: number; error?: string }>
  created_at: string
}

export interface MetricDefinition {
  id: string
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
  id: string
  name: string
  source_type?: string
  system_type: string
  connection_config: Record<string, any>
  rag_system_id?: string
  created_at: string
}

export interface SyncTask {
  id: string
  data_source_id: string
  target_types: string[]
  incremental: boolean
  batch_size: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  records_synced?: number
  dataset_id?: string
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface MetricCategory {
  name: string
  count: number
}

// 生成测试数据集请求
export interface GenerateRequest {
  sources: Array<{
    source_type: 'file_upload' | 'text_input' | 'existing_doc'
    file_paths?: string[]
    texts?: string[]
    document_ids?: string[]
  }>
  test_size: number
  distributions: Record<string, number>
  llm_model_id: string
  embedding_model_id: string
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

// 热点新闻相关类型
export interface NewsSource {
  id: string
  name: string
  domain: string
  source_url: string
  source_type: string
  crawl_config: Record<string, any>
  crawl_frequency: string
  is_active: boolean
  last_crawl_at?: string
  last_crawl_status?: string
  total_articles: number
}

export interface HotArticle {
  id: string
  source_id: string
  title: string
  content?: string
  author?: string
  published_at?: string
  crawled_at: string
  source_url?: string
  category?: string
  tags: string[]
  content_length?: number
  language?: string
}

export interface NewsStats {
  sources: {
    total: number
    active: number
  }
  articles: {
    total: number
    today: number
  }
  by_domain: Record<string, number>
}