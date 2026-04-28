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
  description?: string
  source_type?: string
  record_count: number
  has_ground_truth: boolean
  has_contexts: boolean
  status: string
  created_at?: string
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
  dataset_id?: string  // 可选，如果选择调用批次可从中获取
  rag_system_id?: string
  llm_model_id?: string
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
  ground_truth?: string  // 标准答案
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

// 文档类型
export interface DocumentInfo {
  id: string
  title?: string
  content?: string
  file_type?: string
  source_type?: string
  chunk_count?: number
}

// 分片类型
export interface ChunkInfo {
  id: string
  doc_id: string
  content: string
  chunk_index: number
  start_char?: number
  end_char?: number
  milvus_id?: string
  document_title?: string
}

// 压测任务类型
export interface LoadTest {
  id: string
  name: string
  description?: string
  rag_system_id: string
  test_mode: 'qps_limit' | 'latency_dist'
  test_type: 'first_token' | 'full_response'
  latency_threshold?: number  // latency_dist模式下可选
  initial_concurrency?: number  // qps_limit模式
  step?: number  // qps_limit模式
  max_concurrency?: number  // qps_limit模式
  concurrency_levels?: number[]  // latency_dist模式
  dataset_id?: string
  questions?: string[]
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  error?: string
  result?: LoadTestResult
  started_at?: string
  completed_at?: string
  created_at: string
}

// 压测结果类型
export type LoadTestResult = LoadTestQpsLimitResult | LoadTestLatencyDistResult

// QPS上限测试结果
export interface LoadTestQpsLimitResult {
  test_mode: 'qps_limit'
  max_qps: number
  max_concurrency: number
  latency_threshold: number
  test_type: string
  step_results: Array<{
    concurrency: number
    qps: number
    success_rate: number
    latency_stats: LatencyStats
    meets_threshold: boolean
  }>
}

// 响应时间分布测试结果
export interface LoadTestLatencyDistResult {
  test_mode: 'latency_dist'
  test_type: string
  latency_threshold?: number
  levels: Array<{
    concurrency: number
    qps: number
    success_rate: number
    latency_stats: LatencyStats
    meets_threshold?: boolean
  }>
}

// 延迟统计
export interface LatencyStats {
  mean: number
  median: number
  min: number
  max: number
  p50: number
  p90: number
  p99: number
}

// 文档解释类型
export interface DocExplanation {
  id: string
  doc_id: string
  explanation: string
  source: string
  status: string
  document_title?: string
  document_content?: string
  created_at?: string
}

// 文档解释评估任务类型
export interface DocExplanationEvaluation {
  id: string
  name: string
  description?: string
  llm_model_id: string
  dataset_id?: string
  doc_ids?: string[]
  metrics: string[]
  batch_size: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  error?: string
  summary?: Record<string, any>
  started_at?: string
  completed_at?: string
  created_at?: string
}

// 文档解释评估结果类型
export interface DocExplanationEvalResult {
  id: string
  eval_id: string
  doc_id: string
  explanation_id: string
  document_title?: string
  document_content?: string
  explanation?: string
  scores: Record<string, number | string>
  details?: Record<string, any>
  created_at?: string
}

// 开源数据集类型
export interface OpenSourceDataset {
  id: string
  name: string
  url: string
  description?: string
  dataset_type?: string
  size_info?: string
  language?: string
  is_public: boolean
  tags: string[]
  status: string
  created_at: string
  updated_at: string
}

// 标注矫正类型
export interface AnnotationCorrection {
  id: string
  invocation_result_id?: string
  qa_record_id?: string
  batch_id?: string
  status: 'pending' | 'analyzing' | 'completed' | 'failed'
  different_statements: Array<{
    statement: string
    source: 'system' | 'ground_truth'
    type: 'unique' | 'conflicting'
    verification_question?: string
    supported?: boolean
    conflict_with?: string
    conflict_description?: string
  }>
  evidence_results: Array<{
    statement: string
    question: string
    supported: boolean
    supporting_chunks: Array<{
      chunk_id?: string
      content: string
      relevance_score?: number
    }>
    reason?: string
  }>
  is_doubtful: boolean
  doubt_reason?: string
  is_confirmed: boolean
  confirmed_at?: string
  summary?: string
  analysis_duration?: string
  error?: string
  created_at?: string
}

// 训练数据评估相关类型
export type TrainingDataType = 'llm' | 'embedding' | 'reranker' | 'reward_model' | 'dpo' | 'vlm' | 'vla'

export interface TrainingDataEval {
  id: string
  name: string
  description?: string
  dataset_id: string
  data_type: TrainingDataType
  config: Record<string, any>
  metrics: string[]
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  total_samples: number
  passed_samples: number
  failed_samples: number
  pass_rate: number
  summary?: Record<string, any>
  quality_distribution?: Record<string, number>
  started_at?: string
  completed_at?: string
  created_at?: string
}

export interface TrainingDataMetricConfig {
  metric_name: string
  metric_type: string
  params: Record<string, any>
  weight: number
  enabled: boolean
  threshold?: number
  threshold_type?: string
}

export interface TrainingDataEvalResult {
  id: string
  eval_id: string
  qa_record_id: string
  question: string
  answer?: string
  scores: Record<string, { score: number; passed: boolean }>
  details?: Record<string, any>
  quality_tags: string[]
  issues: string[]
  suggestions: string[]
  status: 'passed' | 'failed' | 'warning'
  overall_score: number
  created_at?: string
}

export interface TrainingDataMetricDefinition {
  name: string
  display_name: string
  description: string
  category: string
  data_types: string[]
  requires_llm: boolean
  requires_embedding: boolean
  requires_ground_truth: boolean
  range_min: number
  range_max: number
  higher_is_better: boolean
  default_threshold: number
  threshold_type: string
}

export interface TrainingDataTemplate {
  id: string
  name: string
  display_name: string
  data_type: TrainingDataType
  description?: string
  metric_configs: TrainingDataMetricConfig[]
  default_thresholds: Record<string, number>
  is_builtin: boolean
}

export interface TrainingQualityRule {
  id: string
  name: string
  description?: string
  data_types: string[]
  rule_type: string
  config: Record<string, any>
  threshold_min?: number
  threshold_max?: number
  severity: 'error' | 'warning' | 'info'
  auto_fixable: boolean
  is_enabled: boolean
  is_builtin: boolean
}