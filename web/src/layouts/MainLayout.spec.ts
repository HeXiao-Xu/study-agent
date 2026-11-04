import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import type { UserOut } from '@/types/auth'
import MainLayout from './MainLayout.vue'

const user: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

const Dummy = { template: '<div class="dummy-page" />' }

async function mountLayout(path = '/notes') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        component: { template: '<router-view />' },
        children: [
          { path: 'notes', name: 'notes', component: Dummy },
          { path: 'files', name: 'files', component: Dummy },
          { path: 'knowledge', name: 'knowledge', component: Dummy },
          { path: 'questions', name: 'questions', component: Dummy },
          { path: 'qa', name: 'qa', component: Dummy },
          { path: 'mistakes', name: 'mistakes', component: Dummy },
          { path: 'plan', name: 'plan', component: Dummy },
        ],
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const auth = useAuthStore()
  auth.setSession('token-1', user)
  const wrapper = mount(MainLayout, {
    global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('MainLayout', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders seven nav items', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(8)
  })

  it('marks current route as aria-current', async () => {
    const { wrapper } = await mountLayout('/notes')
    const active = wrapper.find('[data-testid="nav-link"][aria-current="page"]')
    expect(active.text()).toContain('笔记')
  })

  it('renders nickname and role label', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.text()).toContain('测试用户_1')
    expect(wrapper.text()).toContain('学生')
  })
})