import { request } from './request'
import type { ModelConfig, ModelType } from '@/types'

// 获取模型列表
export const getModels = (modelType?: ModelType) => {
  return request.get<ModelConfig[]>('/models', { params: { model_type: modelType } })
}

// 创建模型配置
export const createModel = (data: Partial<ModelConfig>) => {
  return request.post<ModelConfig>('/models', data)
}

// 更新模型配置
export const updateModel = (id: number, data: Partial<ModelConfig>) => {
  return request.put<ModelConfig>(`/models/${id}`, data)
}

// 删除模型配置
export const deleteModel = (id: number) => {
  return request.delete(`/models/${id}`)
}

// 测试模型连接
export const testModel = (id: number) => {
  return request.post(`/models/${id}/test`)
}

// 获取支持的模型列表
export const getSupportedModels = () => {
  return request.get('/models/supported')
}