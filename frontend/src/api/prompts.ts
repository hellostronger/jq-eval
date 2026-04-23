// Prompt 管理 API
import type { AxiosRequestConfig } from 'axios'

export interface PromptVersion {
  id: string
  name: string
  content: string
  version: number
  description?: string
  framework?: string
  parameters: Record<string, any>
  is_active: boolean
  original_prompt?: string
  optimization_notes?: string
  test_cases: any[]
  tags: string[]
  usage_scenario?: string
  usage_count: number
  version_count: number
  created_at: string
}

export interface PromptFramework {
  id: string
  name: string
  display_name: string
  description?: string
  complexity: string
  domain?: string
  elements: any[]
  template?: string
  examples: any[]
  is_active: boolean
  sort_order: number
}

const API_BASE = '/api/v1'

async function fetchApi<T>(url: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string> || {}),
  }

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(error.detail || '请求失败')
  }

  return response.json()
}

export const promptApi = {
  // Prompt 版本管理
  listPrompts: (params?: { usage_scenario?: string; framework?: string; skip?: number; limit?: number }) => {
    const query = params ? '?' + new URLSearchParams(params as any).toString() : ''
    return fetchApi<PromptVersion[]>(`/prompts${query}`, { method: 'GET' })
  },

  getPrompt: (id: string) => {
    return fetchApi<PromptVersion>(`/prompts/${id}`, { method: 'GET' })
  },

  createPrompt: (data: {
    name: string
    content: string
    description?: string
    framework?: string
    parameters?: Record<string, any>
    original_prompt?: string
    optimization_notes?: string
    test_cases?: any[]
    tags?: string[]
    usage_scenario?: string
  }) => {
    return fetchApi<PromptVersion>('/prompts', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updatePrompt: (id: string, data: {
    content?: string
    description?: string
    framework?: string
    parameters?: Record<string, any>
    optimization_notes?: string
    test_cases?: any[]
    tags?: string[]
    usage_scenario?: string
  }) => {
    return fetchApi<PromptVersion>(`/prompts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  deletePrompt: (id: string) => {
    return fetchApi<any>(`/prompts/${id}`, { method: 'DELETE' })
  },

  getPromptHistory: (id: string) => {
    return fetchApi<PromptVersion[]>(`/prompts/${id}/history`, { method: 'GET' })
  },

  // Prompt 框架管理
  listFrameworks: (params?: { complexity?: string; domain?: string }) => {
    const query = params ? '?' + new URLSearchParams(params as any).toString() : ''
    return fetchApi<PromptFramework[]>(`/prompts/frameworks${query}`, { method: 'GET' })
  },

  getFramework: (id: string) => {
    return fetchApi<PromptFramework>(`/prompts/frameworks/${id}`, { method: 'GET' })
  },
}