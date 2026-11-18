import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentTaskDetail } from '@/types/agent'
vi.mock('md-editor-v3', () => ({
  MdPreview: {
    props: ['modelValue'],
    template: '<div class="md-preview-mock">{{ modelValue }}</div>',
  },
}))


const routeState = vi.hoisted(() => ({ params: {} as Record<string, string | undefined> }))
const replace = vi.hoisted(() => vi.fn(async () => undefined))
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace }),
}))

const api = vi.hoisted(() => ({ createAgentTask: vi.fn(), getAgentTask: vi.fn() }))
vi.mock('@/api/agent', () => api)

const mermaid = vi.hoisted(() => ({ renderMermaid: vi.fn() }))
vi.mock('./mermaid', () => mermaid)

const exporter = vi.hoisted(() => ({ downloadSvgAsPng: vi.fn(async () => undefined) }))
vi.mock('./exportMindmap', async () => ({
  ...(await vi.importActual<typeof import('./exportMindmap')>('./exportMindmap')),
  ...exporter,
}))

import WeeklyMindmap from './WeeklyMindmap.vue'

function detail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail {
  return {
    id: 4,
    task_type: 'weekly_mindmap',
    status: 'succeeded',
    steps_count: 8,
    token_cost: 50,
    error: null,
    created_at: '2026-11-17T07:00:00Z',
    started_at: '2026-11-17T07:00:01Z',
    finished_at: '2026-11-17T07:00:08Z',
    input: { days: 30 },
    result: {
      task_type: 'weekly_mindmap',
      days: 30,
      note_count: 4,
      kp_count: 2,
      summary_md: '## 过去 30 天学习摘要\n- 单调性：复习了定义法（引用：笔记 #54）',
      mermaid: 'mindmap\n  root((学习导图))\n    单调性',
      fallback_text: '- 学习导图\n  - 单调性',
      citations: [{ note_id: 54, note_title: '函数与导数' }],
      degraded: false,
      cluster_prompt_version: 'weekly_mindmap_v1',
    },
    steps: [],
    ...overrides,
  }
}

function mountPage() {
  return mount(WeeklyMindmap, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  routeState.params = {}
  api.createAgentTask.mockReset()
  api.getAgentTask.mockReset()
  mermaid.renderMermaid.mockReset()
  mermaid.renderMermaid.mockResolvedValue('<svg width="800" height="600"></svg>')
  exporter.downloadSvgAsPng.mockClear()
  replace.mockClear()
})

describe('WeeklyMindmap', () => {
  it('loads a task and renders summary and mermaid svg', async () => {
    routeState.params = { taskId: '4' }
    api.getAgentTask.mockResolvedValue(detail())
    const wrapper = mountPage()
    await flushPromises()
    expect(api.getAgentTask).toHaveBeenCalledWith(4)
    expect(wrapper.find('.md-preview-mock').exists()).toBe(true)
    expect(wrapper.get('[data-testid="summary"]').text()).toContain('复习了定义法')
    expect(mermaid.renderMermaid).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="mindmap-svg"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('笔记 #54')
  })

  it('shows fallback text when mermaid render fails', async () => {
    routeState.params = { taskId: '4' }
    api.getAgentTask.mockResolvedValue(detail())
    mermaid.renderMermaid.mockRejectedValue(new Error('bad mermaid'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.get('[data-testid="fallback"]').text()).toContain('降级为结构树')
    expect(wrapper.text()).toContain('- 学习导图')
  })

  it('shows an empty state when there are no notes', async () => {
    routeState.params = { taskId: '4' }
    const base = detail()
    api.getAgentTask.mockResolvedValue(
      detail({
        result: {
          ...base.result!,
          note_count: 0,
          kp_count: 0,
          mermaid: '',
          fallback_text: '',
          citations: [],
          summary_md: '过去 30 天没有笔记，先记录一些学习内容再来生成导图。',
        },
      }),
    )
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('没有笔记')
    expect(mermaid.renderMermaid).not.toHaveBeenCalled()
  })

  it('creates a weekly task from the form', async () => {
    api.createAgentTask.mockResolvedValue({ id: 9, status: 'pending' })
    const wrapper = mountPage()
    await wrapper.get('[data-testid="generate"]').trigger('click')
    await flushPromises()
    expect(api.createAgentTask).toHaveBeenCalledWith({
      task_type: 'weekly_mindmap',
      input: { days: 7 },
    })
    expect(replace).toHaveBeenCalledWith({
      name: 'agent-mindmap',
      params: { taskId: '9' },
    })
  })

  it('exports the rendered svg as png', async () => {
    routeState.params = { taskId: '4' }
    api.getAgentTask.mockResolvedValue(detail())
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="export-png"]').trigger('click')
    await flushPromises()
    expect(exporter.downloadSvgAsPng).toHaveBeenCalledWith(
      '<svg width="800" height="600"></svg>',
      expect.stringContaining('学习导图-4-'),
    )
  })
})