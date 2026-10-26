import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    setupFiles: ['./src/test/setup.ts'],
    // Element Plus 默认被 externalize 后，其 CJS 依赖 async-validator 的默认导入
    // 在 Vitest 下会退化成非构造函数，导致表单校验恒为 true；inline 后走 Vite 转换。
    server: {
      deps: {
        inline: ['element-plus'],
      },
    },
  },
})