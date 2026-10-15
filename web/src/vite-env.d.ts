/// <reference types="vite/client" />

// 本项目实际使用的环境变量（新增时同步 .env.example 与本文件）
// 注意：VITE_ 前缀变量会打进前端构建产物，禁止放机密
interface ImportMetaEnv {
  /** 后端 API 基地址（开发指向本地 FastAPI；生产留空 = 同源） */
  readonly VITE_API_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
