import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 注意：这里刻意不配 server.proxy —— 跨域走后端 CORS（S0-5 已放行
// http://localhost:5173）。CORS 与 proxy 二选一（S0-6 任务卡的坑），
// 两个都配会出现难以排查的 404。
// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
