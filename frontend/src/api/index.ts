import { request } from './request'
import type { RAGSystem, Dataset, QARecord, Evaluation, MetricDefinition, DataSource, SyncTask, ModelConfig, SystemStats, NewsSource, HotArticle, NewsStats, InvocationBatch, InvocationResult, LoadTest, DocExplanation, DocExplanationEvaluation, DocExplanationEvalResult, OpenSourceDataset, AnnotationCorrection } from '@/types'

// 文档和分片API
export interface DocumentInfo {
  id: string
  title?: string
  content?: string
  file_type?: string
  source_type?: string
  chunk_count?: number
}

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

// 模型API
export const getModels = (modelType: string) => {
  return request.get<ModelConfig[]>(`/models?type=${modelType}`)
}

export const createModel = (data: Partial<ModelConfig>) => {
  return request.post<ModelConfig>('/models', data)
}

export const updateModel = (id: string, data: Partial<ModelConfig>) => {
  return request.put<ModelConfig>(`/models/${id}`, data)
}

export const deleteModel = (id: string) => {
  return request.delete(`/models/${id}`)
}

export const testModel = (id: string) => {
  return request.post<{ success: boolean; error?: string }>(`/models/${id}/test`)
}

// RAG系统API
export const getRAGSystems = () => {
  return request.get<RAGSystem[]>('/rag-systems')
}

export const createRAGSystem = (data: Partial<RAGSystem>) => {
  return request.post<RAGSystem>('/rag-systems', data)
}

export const updateRAGSystem = (id: string, data: Partial<RAGSystem>) => {
  return request.put<RAGSystem>(`/rag-systems/${id}`, data)
}

export const deleteRAGSystem = (id: string) => {
  return request.delete(`/rag-systems/${id}`)
}

export const testRAGSystem = (id: string) => {
  return request.post(`/rag-systems/${id}/health`)
}

export const queryRAGSystem = (id: string, question: string) => {
  return request.post<{ answer?: string; response?: string; content?: string }>(`/rag-systems/${id}/query`, { question })
}

export const getRAGSystemTypes = () => {
  return request.get<{ type_code: string; display_name: string; description?: string }[]>('/rag-systems/types')
}

export const getLLMModels = () => {
  return request.get<{ id: string; name: string; provider?: string; model_name?: string; endpoint?: string; has_api_key: boolean }[]>('/rag-systems/llm-models')
}

// 数据集API
export const getDatasets = () => {
  return request.get<Dataset[]>('/datasets')
}

export const getDataset = (id: string) => {
  return request.get<Dataset>(`/datasets/${id}`)
}

export const createDataset = (data: Partial<Dataset>) => {
  return request.post<Dataset>('/datasets', data)
}

export const deleteDataset = (id: string) => {
  return request.delete(`/datasets/${id}`)
}

export const getQARecords = (datasetId: string, params?: { page?: number; size?: number }) => {
  return request.get<{ items: QARecord[]; total: number }>(`/datasets/${datasetId}/qa-records`, { params })
}

export const uploadDatasetFile = (datasetId: string, file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<{ object_name?: string; file_path?: string }>(`/datasets/${datasetId}/import`, formData)
}

// 删除QA记录
export const deleteQARecord = (datasetId: string, recordId: string) => {
  return request.delete(`/datasets/${datasetId}/qa-records/${recordId}`)
}

// 批量删除QA记录
export const batchDeleteQARecords = (datasetId: string, recordIds: string[]) => {
  return request.post(`/datasets/${datasetId}/qa-records/batch-delete`, recordIds)
}

// 下载导入数据模板
export const downloadTemplate = (format: 'json' | 'jsonl' | 'csv') => {
  // 直接使用 fetch下载，避免 axios 拦截器处理
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
  const url = `${baseUrl}/datasets/templates/${format}`
  return fetch(url).then(async response => {
    if (!response.ok) {
      throw new Error('下载失败')
    }
    const blob = await response.blob()
    // 创建下载链接
    const downloadUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `dataset_template.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(downloadUrl)
  })
}

// 生成测试数据集
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

export const generateDataset = (datasetId: string, data: GenerateRequest) => {
  return request.post<{ task_id: string; status: string; message: string }>(`/datasets/${datasetId}/generate`, data)
}

export const getGenerateStatus = (datasetId: string, taskId: string) => {
  return request.get<{
    status: string
    progress?: { progress: number }
    result?: { generated_count?: number; error?: string }
  }>(`/datasets/${datasetId}/generate/status/${taskId}`)
}

export const getCurrentGenerateTask = (datasetId: string) => {
  return request.get<{ task_id: string | null; status: string | null; has_active_task: boolean }>(`/datasets/${datasetId}/generate/current`)
}

// 评估任务API
export const getEvaluations = () => {
  return request.get<Evaluation[]>('/evaluations')
}

export const getEvaluation = (id: string) => {
  return request.get<Evaluation>(`/evaluations/${id}`)
}

export const createEvaluation = (data: Partial<Evaluation>) => {
  return request.post<Evaluation>('/evaluations', data)
}

export const startEvaluation = (id: string) => {
  return request.post(`/evaluations/${id}/run`)
}

export const retryEvaluation = (id: string) => {
  return request.post(`/evaluations/${id}/retry`)
}

interface EvaluationResultsResponse {
  results: Array<{
    id: string
    qa_record_id: string
    question: string
    answer?: string
    ground_truth?: string
    metric_scores: Record<string, { score: number; error?: string }>
    details?: Record<string, any>
    created_at?: string
  }>
  summary?: {
    overall_score: number
    metrics: Record<string, { mean: number; std: number; min: number; max: number }>
  }
}

export const getEvaluationResults = (id: string) => {
  return request.get<EvaluationResultsResponse>(`/evaluations/${id}/results`)
}

export const getEvaluationSummary = (id: string) => {
  return request.get(`/evaluations/${id}/summary`)
}

export const compareEvaluations = (evalIds: string[]) => {
  return request.post<{
    evaluations: Array<{ id: string; name: string; metrics: string[]; summary: Record<string, any> }>
    comparison: Array<{
      qa_record_id: string
      question: string
      ground_truth?: string
      scores: Record<string, Record<string, { score: number; error?: string }>>
    }>
    summary: Record<string, Record<string, any>>
  }>('/evaluations/compare', { eval_ids: evalIds })
}

export const retryEvaluationWithOption = (id: string, reuseInvocation: boolean = true) => {
  return request.post<{ message: string; eval_id: string; task_id: string; reuse_invocation: boolean }>(
    `/evaluations/${id}/retry?reuse_invocation=${reuseInvocation}`
  )
}

// 调用批次API
export const getInvocationBatches = (params?: { dataset_id?: string; rag_system_id?: string; status?: string }) => {
  return request.get<InvocationBatch[]>('/invocations', { params })
}

export const getInvocationBatch = (id: string) => {
  return request.get<InvocationBatch>(`/invocations/${id}`)
}

export const createInvocationBatch = (data: { name: string; dataset_id: string; rag_system_id: string }) => {
  return request.post<InvocationBatch>('/invocations', data)
}

export const runInvocationBatch = (id: string) => {
  return request.post<{ message: string; batch_id: string; task_id: string }>(`/invocations/${id}/run`)
}

export const getInvocationResults = (batchId: string, params?: { skip?: number; limit?: number; status?: string }) => {
  return request.get<InvocationResult[]>(`/invocations/${batchId}/results`, { params })
}

export const deleteInvocationBatch = (id: string) => {
  return request.delete(`/invocations/${id}`)
}

export const retryInvocationBatch = (batchId: string, resultIds?: string[]) => {
  return request.post<{ message: string; batch_id: string; task_id: string; retry_count?: number }>(
    `/invocations/${batchId}/retry`,
    resultIds ? { result_ids: resultIds } : {}
  )
}

export const retrySingleResult = (batchId: string, resultId: string) => {
  return request.post<{ message: string; batch_id: string; result_id: string; task_id: string }>(
    `/invocations/${batchId}/results/${resultId}/retry`
  )
}

export const getInvocationStats = (batchId: string) => {
  return request.get<{
    batch_id: string
    total: number
    completed: number
    failed: number
    status_counts: Record<string, number>
  }>(`/invocations/${batchId}/stats`)
}

// 统计API
export const getSystemStats = () => {
  return request.get<SystemStats>('/evaluations/daily-stats')
}

export const getHealth = () => {
  return request.get<{ components: Record<string, { status: string }> }>('/health')
}

// 指标市场API
export const getMetrics = () => {
  return request.get<MetricDefinition[]>('/metrics')
}

export const getMetric = (id: string) => {
  return request.get<MetricDefinition>(`/metrics/${id}`)
}

export const getMetricCategories = () => {
  return request.get<string[]>('/metrics/categories')
}

export const getMetricsByCategory = (category: string) => {
  return request.get<MetricDefinition[]>('/metrics', { params: { category } })
}

// 数据源API
export const getDataSources = () => {
  return request.get<DataSource[]>('/data-sources')
}

export const createDataSource = (data: Partial<DataSource>) => {
  return request.post<DataSource>('/data-sources', data)
}

export const deleteDataSource = (id: string) => {
  return request.delete(`/data-sources/${id}`)
}

export const testDataSourceConnection = (id: string) => {
  return request.post<{ success: boolean; message?: string }>(`/data-sources/${id}/test-connection`)
}

export const getDataSourceSchema = (id: string) => {
  return request.get(`/data-sources/${id}/schema`)
}

export const createSyncTask = (dataSourceId: string, data: Partial<SyncTask>) => {
  return request.post<SyncTask>(`/data-sources/${dataSourceId}/sync`, data)
}

export const executeSync = (dataSourceId: string, data: { dataset_id: string; tables: string[]; mappings: Record<string, any> }) => {
  return request.post(`/data-sources/${dataSourceId}/sync`, data)
}

export const getSyncTasks = (dataSourceId: string) => {
  return request.get<SyncTask[]>(`/data-sources/${dataSourceId}/sync-tasks`)
}

// 热点新闻API
export const getNewsSources = (params?: { domain?: string; is_active?: boolean }) => {
  return request.get<NewsSource[]>('/hot-news/sources', { params })
}

export const createNewsSource = (data: Partial<NewsSource>) => {
  return request.post<NewsSource>('/hot-news/sources', data)
}

export const updateNewsSource = (id: string, data: Partial<NewsSource>) => {
  return request.put<NewsSource>(`/hot-news/sources/${id}`, data)
}

export const deleteNewsSource = (id: string) => {
  return request.delete(`/hot-news/sources/${id}`)
}

export const testNewsSource = (id: string) => {
  return request.post<{ success: boolean; error?: string; feed_title?: string }>(`/hot-news/sources/${id}/test`)
}

export const triggerCrawl = (id: string, forceFull: boolean = false) => {
  return request.post<{ total_found: number; new_articles: number; status: string }>(
    `/hot-news/sources/${id}/crawl`,
    null,
    { params: { force_full: forceFull } }
  )
}

export const getHotArticles = (params?: { source_id?: string; domain?: string; limit?: number; offset?: number }) => {
  return request.get<HotArticle[]>('/hot-news/articles', { params })
}

export const getNewsStats = () => {
  return request.get<NewsStats>('/hot-news/stats')
}

export const getDomains = () => {
  return request.get<{ code: string; name: string }[]>('/hot-news/domains')
}

export const getSupportedTypes = () => {
  return request.get<{ type: string; display_name: string }[]>('/hot-news/supported-types')
}

export const deleteArticle = (id: string) => {
  return request.delete(`/hot-news/articles/${id}`)
}

export const batchDeleteArticles = (ids: string[]) => {
  return request.post<{ deleted_count: number }>('/hot-news/articles/batch-delete', { article_ids: ids })
}

// 文档和分片API（定义已移到文件顶部）

export const getDatasetDocuments = (datasetId: string, params?: { page?: number; size?: number }) => {
  return request.get<{ items: DocumentInfo[]; total: number }>(`/datasets/${datasetId}/documents`, { params })
}

export const getDatasetDocument = (datasetId: string, docId: string) => {
  return request.get<DocumentInfo>(`/datasets/${datasetId}/documents/${docId}`)
}

export const getDatasetChunks = (datasetId: string, params?: { page?: number; size?: number; doc_id?: string }) => {
  return request.get<{ items: ChunkInfo[]; total: number }>(`/datasets/${datasetId}/chunks`, { params })
}

export const getDatasetChunk = (datasetId: string, chunkId: string) => {
  return request.get<ChunkInfo>(`/datasets/${datasetId}/chunks/${chunkId}`)
}

// 上传文档并自动分片
export const uploadDocument = (datasetId: string, file: File, chunkSize?: number, chunkOverlap?: number) => {
  const formData = new FormData()
  formData.append('file', file)
  const params = new URLSearchParams()
  if (chunkSize) params.append('chunk_size', chunkSize.toString())
  if (chunkOverlap) params.append('chunk_overlap', chunkOverlap.toString())
  return request.post<{
    document_id: string
    title: string
    content_length: number
    chunk_count: number
  }>(`/datasets/${datasetId}/documents/upload?${params.toString()}`, formData)
}

// 从文本创建文档
export const createDocumentFromText = (datasetId: string, data: {
  title?: string
  content: string
  source_type?: string
  file_type?: string
}, chunkData?: { chunk_size?: number; chunk_overlap?: number }) => {
  return request.post<{
    document_id: string
    title: string
    content_length: number
    chunk_count: number
  }>(`/datasets/${datasetId}/documents/text`, data, { params: chunkData })
}

// 从热点新闻创建文档
export const createDocumentsFromNews = (datasetId: string, articleIds: string[], chunkSize?: number, chunkOverlap?: number) => {
  const params = new URLSearchParams()
  if (chunkSize) params.append('chunk_size', chunkSize.toString())
  if (chunkOverlap) params.append('chunk_overlap', chunkOverlap.toString())
  return request.post<{
    created_count: number
    documents: Array<{
      document_id: string
      title: string
      content_length: number
      chunk_count: number
      article_id: string
    }>
  }>(`/datasets/${datasetId}/documents/from-news?${params.toString()}`, { article_ids: articleIds })
}

// 获取文档的所有分片
export const getDocumentChunks = (datasetId: string, docId: string, params?: { page?: number; size?: number }) => {
  return request.get<{ items: ChunkInfo[]; total: number }>(`/datasets/${datasetId}/documents/${docId}/chunks`, { params })
}

// 压测任务API
export interface LoadTestCreateParams {
  name: string
  description?: string
  rag_system_id: string
  test_mode: 'qps_limit' | 'latency_dist'
  test_type: 'first_token' | 'full_response'
  latency_threshold?: number
  initial_concurrency?: number
  step?: number
  max_concurrency?: number
  concurrency_levels?: number[]
  dataset_id?: string
  questions?: string[]
}

export const getLoadTests = (params?: { rag_system_id?: string; status?: string }) => {
  return request.get<LoadTest[]>('/load-tests', { params })
}

export const getLoadTest = (id: string) => {
  return request.get<LoadTest>(`/load-tests/${id}`)
}

export const createLoadTest = (data: LoadTestCreateParams) => {
  return request.post<LoadTest>('/load-tests', data)
}

export const updateLoadTest = (id: string, data: Partial<LoadTestCreateParams>) => {
  return request.put<LoadTest>(`/load-tests/${id}`, data)
}

export const deleteLoadTest = (id: string) => {
  return request.delete(`/load-tests/${id}`)
}

export const runLoadTest = (id: string) => {
  return request.post<{ message: string; load_test_id: string; task_id: string }>(`/load-tests/${id}/run`)
}

// 文档解释API
export const getDocExplanations = (params?: { doc_id?: string; status?: string }) => {
  return request.get<DocExplanation[]>('/doc-explanations', { params })
}

export const getDocExplanation = (id: string) => {
  return request.get<DocExplanation>(`/doc-explanations/${id}`)
}

export const createDocExplanation = (data: { doc_id: string; explanation: string; source?: string }) => {
  return request.post<DocExplanation>('/doc-explanations', data)
}

export const updateDocExplanation = (id: string, data: { explanation?: string; source?: string; status?: string }) => {
  return request.put<DocExplanation>(`/doc-explanations/${id}`, data)
}

export const deleteDocExplanation = (id: string) => {
  return request.delete(`/doc-explanations/${id}`)
}

// 文档解释评估API
export const getDocExplanationEvaluations = (params?: { status?: string }) => {
  return request.get<DocExplanationEvaluation[]>('/doc-explanation-evaluations', { params })
}

export const getDocExplanationEvaluation = (id: string) => {
  return request.get<DocExplanationEvaluation>(`/doc-explanation-evaluations/${id}`)
}

export const createDocExplanationEvaluation = (data: {
  name: string
  description?: string
  llm_model_id: string
  dataset_id?: string
  doc_ids?: string[]
  metrics?: string[]
  batch_size?: number
}) => {
  return request.post<DocExplanationEvaluation>('/doc-explanation-evaluations', data)
}

export const runDocExplanationEvaluation = (id: string) => {
  return request.post<{ message: string; eval_id: string; task_id: string }>(`/doc-explanation-evaluations/${id}/run`)
}

export const getDocExplanationEvalResults = (id: string) => {
  return request.get<DocExplanationEvalResult[]>(`/doc-explanation-evaluations/${id}/results`)
}

export const deleteDocExplanationEvaluation = (id: string) => {
  return request.delete(`/doc-explanation-evaluations/${id}`)
}

// 获取所有文档（用于选择）
export const getDocuments = () => {
  return request.get<{ items: DocumentInfo[]; total: number }>('/datasets/documents')
}

// 开源数据集API
export const getOpenSourceDatasets = (params?: { page?: number; size?: number; dataset_type?: string; language?: string; status?: string; is_public?: boolean; search?: string }) => {
  return request.get<{ items: OpenSourceDataset[]; total: number }>('/open-source-datasets', { params })
}

export const getOpenSourceDataset = (id: string) => {
  return request.get<OpenSourceDataset>(`/open-source-datasets/${id}`)
}

export const createOpenSourceDataset = (data: Partial<OpenSourceDataset>) => {
  return request.post<OpenSourceDataset>('/open-source-datasets', data)
}

export const updateOpenSourceDataset = (id: string, data: Partial<OpenSourceDataset>) => {
  return request.put<OpenSourceDataset>(`/open-source-datasets/${id}`, data)
}

export const deleteOpenSourceDataset = (id: string) => {
  return request.delete(`/open-source-datasets/${id}`)
}

// HuggingFace 数据集搜索 API
export interface HFDatasetSearchResult {
  id: string
  name: string
  url: string
  description: string
  downloads: number
  likes: number
  tags: string[]
  language: string
  task_categories: string[]
  size_info: string
}

export const searchHFDatasets = (params: { query: string; limit?: number; author?: string; tags?: string; language?: string }) => {
  return request.get<{ items: HFDatasetSearchResult[]; total: number }>('/open-source-datasets/hf-search', { params })
}

export const importHFDataset = (hfDatasetId: string) => {
  return request.post<OpenSourceDataset>('/open-source-datasets/hf-import', { hf_dataset_id: hfDatasetId })
}

// 标注矫正API
export interface SingleCorrectionRequest {
  invocation_result_id: string
  qa_record_id: string
  batch_id?: string
  llm_model_id: string
}

export interface BatchCorrectionRequest {
  llm_model_id: string
}

export const analyzeSingleCorrection = (data: SingleCorrectionRequest) => {
  return request.post<AnnotationCorrection>('/annotation-corrections/single', data)
}

export const analyzeBatchCorrection = (batchId: string, data: BatchCorrectionRequest) => {
  return request.post<{ items: AnnotationCorrection[]; total: number; doubtful_count: number }>(
    `/annotation-corrections/batch/${batchId}`,
    data
  )
}

export const getAnnotationCorrection = (correctionId: string) => {
  return request.get<AnnotationCorrection>(`/annotation-corrections/${correctionId}`)
}

export const getBatchCorrections = (
  batchId: string,
  params?: { status?: string; is_doubtful?: boolean; page?: number; size?: number }
) => {
  return request.get<{ items: AnnotationCorrection[]; total: number; doubtful_count: number }>(
    `/annotation-corrections/batch/${batchId}`,
    { params }
  )
}

export const getCorrectionByInvocation = (invocationResultId: string) => {
  return request.get<AnnotationCorrection>(`/annotation-corrections/invocation/${invocationResultId}`)
}

export const confirmCorrection = (
  correctionId: string,
  data: { is_doubtful: boolean; doubt_reason?: string }
) => {
  return request.put<{ message: string; correction_id: string }>(
    `/annotation-corrections/${correctionId}/confirm`,
    data
  )
}

// 训练数据评估API
export interface TrainingDataEvalCreateParams {
  name: string
  description?: string
  dataset_id: string
  data_type: 'llm' | 'embedding' | 'reranker' | 'reward_model' | 'dpo' | 'vlm' | 'vla'
  config?: Record<string, any>
  metrics: string[]
  metric_configs?: Array<{
    metric_name: string
    metric_type: string
    params?: Record<string, any>
    weight?: number
    enabled?: boolean
    threshold?: number
    threshold_type?: string
  }>
}

export const getTrainingDataEvals = (params?: { status?: string; dataset_id?: string; data_type?: string }) => {
  return request.get<import('@/types').TrainingDataEval[]>('/training-data-evals', { params })
}

export const getTrainingDataEval = (id: string) => {
  return request.get<import('@/types').TrainingDataEval>(`/training-data-evals/${id}`)
}

export const createTrainingDataEval = (data: TrainingDataEvalCreateParams) => {
  return request.post<import('@/types').TrainingDataEval>('/training-data-evals', data)
}

export const deleteTrainingDataEval = (id: string) => {
  return request.delete(`/training-data-evals/${id}`)
}

export const runTrainingDataEval = (id: string) => {
  return request.post<{ message: string; eval_id: string; task_id: string }>(`/training-data-evals/${id}/run`)
}

export const getTrainingDataEvalStatus = (id: string) => {
  return request.get<{
    eval_id: string
    status: string
    progress: number
    total_samples: number
    passed_samples: number
    failed_samples: number
    pass_rate: number
    error?: string
  }>(`/training-data-evals/${id}/status`)
}

export const getTrainingDataEvalResults = (id: string, params?: { status?: string; skip?: number; limit?: number }) => {
  return request.get<{
    eval_id: string
    summary?: Record<string, any>
    results: import('@/types').TrainingDataEvalResult[]
  }>(`/training-data-evals/${id}/results`, { params })
}

export const getAvailableTrainingDataMetrics = (dataType?: string) => {
  return request.get<{ metrics: import('@/types').TrainingDataMetricDefinition[] }>('/training-data-evals/metrics/available', {
    params: dataType ? { data_type: dataType } : undefined
  })
}

export const getTrainingDataTemplates = (dataType?: string) => {
  return request.get<{ templates: import('@/types').TrainingDataTemplate[] }>('/training-data-evals/templates', {
    params: dataType ? { data_type: dataType } : undefined
  })
}

export const getTrainingQualityRules = (params?: { data_type?: string; rule_type?: string }) => {
  return request.get<{ rules: import('@/types').TrainingQualityRule[] }>('/training-data-evals/quality-rules', { params })
}

export const exportTrainingDataEvalReport = (id: string, format: 'json' | 'csv' = 'json') => {
  return request.get(`/training-data-evals/${id}/export`, { params: { format } })
}