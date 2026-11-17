import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentStep, AgentTaskDetail } from '@/types/agent'

const api = vi.hoisted(() => ({
  getAgentTask: vi.fn(),
  confirmAgentTask: vi.fn(),
}))
vi.mock('@/api/agent', () => api)

const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '5' } }),
  useRouter: () => ({ push }),
}))

import TaskDetail from './TaskDetail.vue'

function step(overrides: Partial<AgentStep> = {}): AgentStep {
  return {
    step_no: 1,
    thought: '计划 1 步',
    tool_name: null,
    tool_input: null,
    tool_output: null,
    latency_ms: null,
    status: 'ok',
    ...overrides,
  }
}

function detail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 5,
    task_type: 'weekly_mindmap',
    status: 'succeeded',
    steps_count: 2,
    token_cost: 2296,
    error: null,
    created_at: '2026-11-17T07:50:52Z',
    started_at: '2026-11-17T07:50:53Z',
    finished_at: '2026-11-17T07:51:08Z',
    input: { days: 30 },
    result: {
      task_type: 'weekly_mindmap',
      days: 30,
      note_count: 4,
      kp_count: 2,
      summary_md: '## 过去 30 天学习摘要\n- 单调性：复习了定义法（引用：笔记 #54）',
      mermaid: 'mindmap\n  root((学习导图))',
      fallback_text: '- 学习导图',
      citations: [{ note_id: 54, note_title: '函数与导数' }],
      degraded: false,
      cluster_prompt_version: 'weekly_mindmap_v1',
    },
    steps: [
      step(),
      step({ step_no: 2, thought: '计算 2 的 10 次方', tool_name: 'calculator', latency_ms: 3 }),
    ],
    ...overrides,
  }
}

function mountPage() {
  return mount(TaskDetail, {
    attachTo: document.body,
    global: {
      plugins: [ElementPlus],
      stubs: { transition: false, 'transition-group': false },
    },
  })
}

beforeEach(() => {
  api.getAgentTask.mockReset()
  api.getAgentTask.mockResolvedValue(detail())
  api.confirmAgentTask.mockReset()
  api.confirmAgentTask.mockResolvedValue({ id: 5, status: 'pending' })
  push.mockClear()
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('TaskDetail', () => {
  it('renders step timeline and weekly result link', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="step-row"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('计划 1 步')
    expect(wrapper.text()).toContain('calculator')
    expect(wrapper.get('[data-testid="mindmap-link"]').attributes('href')).toBe(
      '/agent/mindmap/5',
    )
    expect(wrapper.text()).toContain('复习了定义法')
    expect(wrapper.text()).toContain('笔记 #54')
  })

  it('highlights and expands the error step with suggestions', async () => {
    const failed = detail({
      status: 'failed',
      error: '工具连续失败已达重试上限',
      result: null,
      steps: [
        step(),
        step({
          step_no: 2,
          thought: '工具 calculator 失败',
          tool_name: 'calculator',
          tool_input: { expression: '1/0' },
          tool_output: { error: '不能除以 0', code: 42200 },
          status: 'error',
        }),
      ],
    })
    api.getAgentTask.mockResolvedValue(failed)
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.step-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('不能除以 0')
    expect(wrapper.get('[data-testid="step-io"]').attributes('open')).toBeDefined()
    expect(wrapper.text()).toContain('重新创建学习导图')
    expect(wrapper.text()).toContain('工具连续失败已达重试上限')
  })

  it('opens the confirm dialog and submits approval', async () => {
    api.getAgentTask
      .mockResolvedValueOnce(detail({ status: 'waiting_confirm', result: null }))
      .mockResolvedValue(detail({ status: 'succeeded' }))
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="confirm-approve"]').trigger('click')
    await flushPromises()
    const submit = document.querySelector<HTMLElement>('[data-testid="confirm-submit"]')
    expect(submit).not.toBeNull()
    submit!.click()
    await flushPromises()
    expect(api.confirmAgentTask).toHaveBeenCalledWith(5, {
      approved: true,
      comment: null,
    })
  })

  it('polls while pending and stops after a terminal state', async () => {
    vi.useFakeTimers()
    api.getAgentTask
      .mockResolvedValueOnce(detail({ status: 'running', steps: [step()] }))
      .mockResolvedValue(detail())
    mountPage()
    await flushPromises()
    expect(api.getAgentTask).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(api.getAgentTask).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(api.getAgentTask).toHaveBeenCalledTimes(2)
  })
})