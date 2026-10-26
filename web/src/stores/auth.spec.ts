import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserOut } from '@/types/auth'

vi.mock('@/api/auth', () => ({
  getMe: vi.fn(),
}))

import { getMe } from '@/api/auth'
import { useAuthStore } from './auth'

const user: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('setSession stores token in localStorage', () => {
    const store = useAuthStore()
    store.setSession('token-1', user)
    expect(store.token).toBe('token-1')
    expect(store.user?.nickname).toBe('测试用户_1')
    expect(localStorage.getItem('study-agent-token')).toBe('token-1')
  })

  it('clearSession clears state and localStorage', () => {
    const store = useAuthStore()
    store.setSession('token-1', user)
    store.clearSession()
    expect(store.token).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('study-agent-token')).toBeNull()
  })

  it('fetchMe writes user on success', async () => {
    vi.mocked(getMe).mockResolvedValue(user)
    const store = useAuthStore()
    store.setSession('token-1', null)
    await store.fetchMe()
    expect(store.user).toEqual(user)
  })
})