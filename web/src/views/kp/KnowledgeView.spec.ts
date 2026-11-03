import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  listSubjects: vi.fn(),
}))

import { listSubjects } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import KnowledgeView from './KnowledgeView.vue'

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(KnowledgeView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        Tree: { template: '<div data-testid="tree-stub">tree</div>' },
        PendingAlign: { template: '<div data-testid="pending-stub">pending</div>' },
        GraphReview: { template: '<div data-testid="graph-stub">graph</div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('KnowledgeView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads subjects and shows the tree tab by default', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    expect(listSubjects).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('知识点树')
    expect(wrapper.find('[data-testid="tree-stub"]').exists()).toBe(true)
  })

  it('switches to the pending tab', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    const tabs = wrapper.findAll('.el-tabs__item')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="pending-stub"]').exists()).toBe(true)
  })

  it('shows a load error with retry', async () => {
    vi.mocked(listSubjects).mockRejectedValueOnce(new Error('network'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('学科加载失败')
    vi.mocked(listSubjects).mockResolvedValueOnce([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    await wrapper.find('[data-testid="retry-subjects"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="tree-stub"]').exists()).toBe(true)
  })

  it('shows the graph review tab for teachers', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    const auth = useAuthStore()
    auth.user = {
      id: 9,
      username: 'teacher_1',
      nickname: '老师',
      grade: '高二',
      role: 'teacher',
    } as never
    await flushPromises()
    const labels = wrapper.findAll('.el-tabs__item').map((item) => item.text())
    expect(labels).toContain('图谱关系')
  })

  it('hides the graph review tab for students', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    const auth = useAuthStore()
    auth.user = {
      id: 50,
      username: 'student_1',
      nickname: '学生',
      grade: '高二',
      role: 'student',
    } as never
    await flushPromises()
    const labels = wrapper.findAll('.el-tabs__item').map((item) => item.text())
    expect(labels).not.toContain('图谱关系')
  })
})
