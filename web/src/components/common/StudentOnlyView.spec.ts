import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import type { UserOut } from '@/types/auth'
import StudentOnlyView from './StudentOnlyView.vue'

function user(role: UserOut['role']): UserOut {
  return {
    id: 1,
    username: `test_${role}`,
    nickname: `测试${role}`,
    grade: '高一',
    role,
    created_at: '2026-10-30T00:00:00Z',
  }
}

async function mountGate(role: UserOut['role']) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setSession('token', user(role))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/knowledge', component: { template: '<div>knowledge</div>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(StudentOnlyView, {
    props: { feature: '笔记' },
    slots: { default: '<div data-testid="student-content">学生内容</div>' },
    global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('StudentOnlyView', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('shows the unsupported state for a teacher', async () => {
    const { wrapper } = await mountGate('teacher')
    expect(wrapper.text()).toContain('暂不支持查看')
    expect(wrapper.text()).toContain('笔记功能仅向学生开放')
    expect(wrapper.find('[data-testid="student-content"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('前往知识库')
  })

  it('renders the student content for a student', async () => {
    const { wrapper } = await mountGate('student')
    expect(wrapper.text()).not.toContain('暂不支持查看')
    expect(wrapper.find('[data-testid="student-content"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('学生个人学习空间')
  })

  it('navigates a teacher to the knowledge page', async () => {
    const { wrapper, router } = await mountGate('teacher')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/knowledge')
  })
})
