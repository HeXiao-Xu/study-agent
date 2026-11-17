import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentTaskPage } from '@/types/agent'

const api = vi.hoisted(() => ({
  listAgentTasks: vi.fn(),
  getAgentTask: vi.fn(),
  createAgentTask: vi.fn(),
  confirmAgentTask: vi.fn(),
}))
vi.mock('@/api/agent', () => api)

const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  useRoute: () => ({ params: {} }),
}))

import TaskList from './TaskList.vue'

function page(overrides: Partial<AgentTaskPage> = {}): AgentTaskPage {
  return {
    items: [
      {
        id: 5,
        task_type: 'weekly_mindmap',
        status: 'succeeded',
        steps_count: 10,
        token_cost: 2296,
        error: null,
        created_at: '2026-11-17T07:50:52Z',
        started_at: null,
        finished_at: '2026-11-17T07:51:08Z',
      },
      {
        id: 6,
        task_type: 'demo',
        status: 'failed',
        steps_count: 6,
        token_cost: 0,
        error: '用户拒绝确认',
        created_at: '2026-11-17T07:55:31Z',
        started_at: null,
        finished_at: null,
      },
    ],
    total: 2,
    page: 1,
    page_size: 10,
    ...overrides,
  }
}

function mountPage() {
  return mount(TaskList, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  api.listAgentTasks.mockReset()
  api.listAgentTasks.mockResolvedValue(page())
  push.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('TaskList', () => {
  it('renders tasks with labels and status tags', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalled()
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('学习导图')
    expect(wrapper.text()).toContain('演示任务')
    expect(wrapper.get('[data-testid="task-row-5"]').text()).toBe('#5')
  })

  it('reloads on refresh', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="refresh"]').trigger('click')
    await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)
  })

  it('opens task detail on row id click', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="task-row-5"]').trigger('click')
    expect(push).toHaveBeenCalledWith('/agent/tasks/5')
  })

  it('shows an empty state', async () => {
    api.listAgentTasks.mockResolvedValue(page({ items: [], total: 0 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="empty"]').exists()).toBe(true)
  })

  it('polls every 2s while a running task exists, then stops', async () => {
    vi.useFakeTimers()
    api.listAgentTasks
      .mockResolvedValueOnce(
        page({
          items: [{ ...page().items[0]!, status: 'running', steps_count: 2 }],
          total: 1,
        }),
      )
      .mockResolvedValue(page())
    mountPage()
    await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(4000)
    await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)
  })
})