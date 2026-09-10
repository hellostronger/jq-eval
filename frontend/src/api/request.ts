import axios, { AxiosError, AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { message } from 'antd'

// 允许单个请求声明放弃全局错误弹窗：健康探测类接口在降级时按设计返回 503，
// UI 用状态标签呈现，而不是每次刷新页面都弹"请求失败"
declare module 'axios' {
  interface AxiosRequestConfig {
    silent?: boolean
  }
}

const service: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 请求拦截器
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error: AxiosError<{ detail?: string }>) => {
    const errorMessage = error.response?.data?.detail || error.message || '请求失败'
    if (!error.config?.silent) {
      message.error(errorMessage)
    }
    return Promise.reject(error)
  }
)

// API请求方法
export const request = {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return service.get(url, config)
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return service.post(url, data, config)
  },
  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return service.put(url, data, config)
  },
  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return service.delete(url, config)
  },
}

export default service