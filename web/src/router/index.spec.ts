import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import type { UserOut } from '@/types/auth'
import router from './index'

const teacher: UserOut = {
  id: 2,
  username: 's211_teacher',
  nickname: '测试老师_1',
  grade: null,
  role: 'teacher',
  created_at: '2026-10-27T00:00:00Z',
}

describe('S5-7 routes', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('registers review, reports and practice', () => {
    const paths = router.getRoutes().map((route) => route.path)
    expect(paths).toContain('/review')
    expect(paths).toContain('/reports')
    expect(paths).toContain('/practice')
  })

  it('keeps /plan as a redirect to /review', () => {
    const plan = router.getRoutes().find((route) => route.path === '/plan')
    expect(plan?.redirect).toBe('/review')
  })

  it('让教师留在角色受限页，由布局显示右侧无权限', async () => {
    useAuthStore().setSession('token-1', teacher)

    await router.push('/review')

    expect(router.currentRoute.value.path).toBe('/review')
  })
})