/**
 * axios 封装：统一 baseURL、token 注入、错误提示与 401 跳登录。
 * 契约：后端统一响应壳 {code, message, trace_id, data}（docs/API.md §0/§13）。
 */
import axios, { type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE,
  timeout: 15_000,
})

/** 后端统一响应壳（与 docs/API.md §0 保持一致） */
export interface ApiEnvelope<T> {
  code: number
  message: string
  trace_id: string
  data: T
}

// 请求拦截：带 token（无 token 照常放行，公开接口如 /health 不需要）
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 响应拦截：统一处理业务错误码与 401
http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiEnvelope<unknown>
    // HTTP 200 但业务失败：统一弹提示；调用方拿 reject 自行决定是否细粒度处理
    if (body && typeof body.code === 'number' && body.code !== 0) {
      if (body.code === 40100) {
        useAuthStore().clearToken()
        // 登录页 S2-2 交付；先占位跳转，避免死循环停留在需登录页面
        void router.push('/login')
      }
      ElMessage.error(body.message)
      return Promise.reject(new Error(body.message))
    }
    return response
  },
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    // 网络/HTTP 层错误：后端 4xx/5xx 同样是统一壳，优先读壳里的 message
    const message = error.response?.data?.message ?? '网络异常，请稍后重试'
    if (error.response?.status === 401) {
      useAuthStore().clearToken()
      void router.push('/login')
    }
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export default http
