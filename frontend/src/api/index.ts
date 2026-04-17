import { request } from './request'
import type { RAGSystem, Dataset, QARecord, Evaluation, MetricDefinition, DataSource, SyncTask, ModelConfig, SystemStats } from '@/types'

// 模型API
export const getModels = (modelType: string) => {
  return request.get<ModelConfig[]>(`/models?type=${modelType}`)
}

export const createModel = (data: Partial<ModelConfig>) => {
  return request.post<ModelConfig>('/models', data)
}

export const updateModel = (id: number, data: Partial<ModelConfig>) => {
  return request.put<ModelConfig>(`/models/${id}`, data)
}

export const deleteModel = (id: number) => {
  return request.delete(`/models/${id}`)
}

export const testModel = (id: number) => {
  return request.post<{ success: boolean; error?: string }>(`/models/${id}/test`)
}

// RAG系统API
export const getRAGSystems = () => {
  return request.get<RAGSystem[]>('/rag-systems')
}

export const createRAGSystem = (data: Partial<RAGSystem>) => {
  return request.post<RAGSystem>('/rag-systems', data)
}

export const updateRAGSystem = (id: number, data: Partial<RAGSystem>) => {
  return request.put<RAGSystem>(`/rag-systems/${id}`, data)
}

export const deleteRAGSystem = (id: number) => {
  return request.delete(`/rag-systems/${id}`)
}

export const testRAGSystem = (id: number) => {
  return request.post(`/rag-systems/${id}/test`)
}

export const queryRAGSystem = (id: number, question: string) => {
  return request.post(`/rag-systems/${id}/query`, { question })
}

// 数据集API
export const getDatasets = () => {
  return request.get<Dataset[]>('/datasets')
}

export const getDataset = (id: number) => {
  return request.get<Dataset>(`/datasets/${id}`)
}

export const createDataset = (data: Partial<Dataset>) => {
  return request.post<Dataset>('/datasets', data)
}

export const deleteDataset = (id: number) => {
  return request.delete(`/datasets/${id}`)
}

export const getQARecords = (datasetId: number, params?: { page?: number; size?: number }) => {
  return request.get<{ items: QARecord[]; total: number }>(`/datasets/${datasetId}/qa-records`, { params })
}

export const uploadDatasetFile = (datasetId: number, file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`/datasets/${datasetId}/import`, formData)
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

export const generateDataset = (datasetId: number, data: GenerateRequest) => {
  return request.post<{ task_id: string; status: string; message: string }>(`/datasets/${datasetId}/generate`, data)
}

export const getGenerateStatus = (datasetId: number, taskId: string) => {
  return request.get(`/datasets/${datasetId}/generate/status/${taskId}`)
}

// 评估任务API
export const getEvaluations = () => {
  return request.get<Evaluation[]>('/evaluations')
}

export const getEvaluation = (id: number) => {
  return request.get<Evaluation>(`/evaluations/${id}`)
}

export const createEvaluation = (data: Partial<Evaluation>) => {
  return request.post<Evaluation>('/evaluations', data)
}

export const startEvaluation = (id: number) => {
  return request.post(`/evaluations/${id}/start`)
}

export const getEvaluationResults = (id: number) => {
  return request.get(`/evaluations/${id}/results`)
}

export const getEvaluationSummary = (id: number) => {
  return request.get(`/evaluations/${id}/summary`)
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

export const getMetric = (id: number) => {
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

export const deleteDataSource = (id: number) => {
  return request.delete(`/data-sources/${id}`)
}

export const testDataSourceConnection = (id: number) => {
  return request.post(`/data-sources/${id}/test-connection`)
}

export const getDataSourceSchema = (id: number) => {
  return request.get(`/data-sources/${id}/schema`)
}

export const createSyncTask = (dataSourceId: number, data: Partial<SyncTask>) => {
  return request.post<SyncTask>(`/data-sources/${dataSourceId}/sync`, data)
}

export const getSyncTasks = (dataSourceId: number) => {
  return request.get<SyncTask[]>(`/data-sources/${dataSourceId}/sync-tasks`)
}