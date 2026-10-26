/**
 * 登录态唯一持有处：token 持久化，user 只存内存并在刷新后由 /auth/me 回填。
 */
import { defineStore } from 'pinia'

import type { UserOut } from '@/types/auth'

const TOKEN_KEY = 'study-agent-token'

const ROLE_LABELS: Record<UserOut['role'], string> = {
  student: '学生',
  teacher: '教师',
  parent: '家长',
  admin: '管理员',
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) ?? '',
    user: null as UserOut | null,
    loading: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    roleLabel: (state) => (state.user ? ROLE_LABELS[state.user.role] : ''),
  },
  actions: {
    setSession(token: string, user: UserOut | null) {
      this.token = token
      this.user = user
      localStorage.setItem(TOKEN_KEY, token)
    },
    clearSession() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
    async fetchMe() {
      // 动态导入避免 http → store → api → http 的静态模块环
      const { getMe } = await import('@/api/auth')
      this.user = await getMe()
    },
  },
})