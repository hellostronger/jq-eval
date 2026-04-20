import { request } from './request'
import type { RAGSystem, Dataset, QARecord, Evaluation, MetricDefinition, DataSource, SyncTask, ModelConfig, SystemStats, NewsSource, HotArticle, NewsStats, InvocationBatch, InvocationResult } from '@/types'

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

export const getInvocationResults = (batchId: string, params?: { skip?: number; limit?: number }) => {
  return request.get<InvocationResult[]>(`/invocations/${batchId}/results`, { params })
}

export const deleteInvocationBatch = (id: string) => {
  return request.delete(`/invocations/${id}`)
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