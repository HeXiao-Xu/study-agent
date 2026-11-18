import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import { NAV_GROUPS } from './nav'
import type { UserOut } from '@/types/auth'
import MainLayout from './MainLayout.vue'

const student: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

const teacher: UserOut = {
  id: 2,
  username: 's211_teacher',
  nickname: '测试老师_1',
  grade: null,
  role: 'teacher',
  created_at: '2026-10-27T00:00:00Z',
}

const Dummy = { template: '<div class="dummy-page" />' }

async function mountLayout(
  path = '/notes',
  role: UserOut['role'] = 'student',
  options: { openAll?: boolean } = {},
) {
  const { openAll = true } = options
  if (openAll) {
    localStorage.setItem(
      'study-agent-nav-open-groups',
      JSON.stringify(NAV_GROUPS.map((group) => group.name)),
    )
  }
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
          { path: 'papers/generate', name: 'paper-generate', component: Dummy },
          { path: 'papers', name: 'paper-list', component: Dummy },
          { path: 'practice', name: 'practice', component: Dummy },
          {
            path: 'qa',
            name: 'qa',
            component: Dummy,
            meta: { title: '智能问答', nav: 'qa', roles: ['student'] },
          },
          { path: 'mistakes', name: 'mistakes', component: Dummy },
          {
            path: 'review',
            name: 'review',
            component: Dummy,
            meta: { title: '复习清单', nav: 'review', roles: ['student'] },
          },
          { path: 'reports', name: 'reports', component: Dummy },
          { path: 'graph', name: 'graph', component: Dummy },
          { path: 'stats', name: 'stats', component: Dummy },
        ],
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const auth = useAuthStore()
  auth.setSession('token-1', role === 'teacher' ? teacher : student)
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

  it('renders all nav items', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(14)
  })

  it('导航项不再显示 01/02 这类序号', async () => {
    const { wrapper } = await mountLayout()
    const links = wrapper.findAll('[data-testid="nav-link"]')
    expect(links[0]!.text()).toBe('笔记')
    expect(links[3]!.text()).toBe('图谱')
    expect(links[4]!.text()).toBe('题库')
    expect(links[5]!.text()).toBe('组卷')
    expect(links[0]!.find('.nav-index').exists()).toBe(false)
    expect(links.map((link) => link.text())).not.toContain('01')
  })

  it('marks current route as aria-current', async () => {
    const { wrapper } = await mountLayout('/notes')
    const active = wrapper.find('[data-testid="nav-link"][aria-current="page"]')
    expect(active.text()).toContain('笔记')
  })

  it('教师进入学生专属页时保留导航并在右侧显示无权限', async () => {
    const { wrapper } = await mountLayout('/qa', 'teacher')

    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(14)
    expect(wrapper.text()).toContain('暂不支持查看')
    expect(wrapper.text()).toContain('智能问答功能仅向学生开放')
    expect(wrapper.find('.dummy-page').exists()).toBe(false)
  })

  it('学生正常进入学生专属页', async () => {
    const { wrapper } = await mountLayout('/qa', 'student')

    expect(wrapper.find('.dummy-page').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('暂不支持查看')
  })

  it('renders nickname and role label', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.text()).toContain('测试用户_1')
    expect(wrapper.text()).toContain('学生')
  })

  it('groups navigation and only opens the active group by default', async () => {
    const { wrapper } = await mountLayout('/notes', 'student', { openAll: false })
    expect(wrapper.findAll('[data-testid^="nav-group-"]')).toHaveLength(4)
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(4)
    expect(wrapper.text()).toContain('知识中心')
    expect(wrapper.text()).toContain('试题训练')
    expect(wrapper.text()).toContain('复习总结')
    expect(wrapper.text()).toContain('智能助手')
    expect(wrapper.get('[data-testid="nav-group-knowledge"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[data-testid="nav-group-assessment"]').attributes('aria-expanded')).toBe('false')
  })

  it('expands and collapses a group by clicking its title', async () => {
    const { wrapper } = await mountLayout('/notes', 'student', { openAll: false })
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(4)
    await wrapper.get('[data-testid="nav-group-assessment"]').trigger('click')
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(8)
    expect(wrapper.get('[data-testid="nav-group-assessment"]').attributes('aria-expanded')).toBe('true')
    await wrapper.get('[data-testid="nav-group-assessment"]').trigger('click')
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(4)
    expect(wrapper.get('[data-testid="nav-group-assessment"]').attributes('aria-expanded')).toBe('false')
  })

  it('auto-opens the group of the current route', async () => {
    const { wrapper } = await mountLayout('/qa', 'student', { openAll: false })
    expect(wrapper.get('[data-testid="nav-group-assistant"]').attributes('aria-expanded')).toBe('true')
    const active = wrapper.find('[data-testid="nav-link"][aria-current="page"]')
    expect(active.text()).toContain('智能问答')
  })

})