/**
 * 最小 auth store（S0-6）：token 的唯一前端持有处。
 * 登录/刷新/登出逻辑 S2-2 交付；本阶段只负责持久化与清理，供 http.ts 注入。
 */
import { defineStore } from 'pinia'

const TOKEN_KEY = 'study-agent-token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    // 从 localStorage 恢复，页面刷新不掉登录态
    token: localStorage.getItem(TOKEN_KEY) ?? '',
  }),
  actions: {
    setToken(token: string) {
      this.token = token
      localStorage.setItem(TOKEN_KEY, token)
    },
    clearToken() {
      this.token = ''
      localStorage.removeItem(TOKEN_KEY)
    },
  },
})
