import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  listGraphEdges: vi.fn(),
  getGraphStats: vi.fn(),
  reviewGraphEdge: vi.fn(),
  reviewGraphEdges: vi.fn(),
  buildGraph: vi.fn(),
}))
vi.mock('@/api/tasks', () => ({ getTask: vi.fn() }))

import {
  buildGraph,
  getGraphStats,
  listGraphEdges,
  reviewGraphEdge,
  reviewGraphEdges,
} from '@/api/kp'
import { getTask } from '@/api/tasks'
import GraphReview from './GraphReview.vue'

const EDGE = {
  id: 1,
  src_kp_id: 2,
  src_name: '函数单调性',
  dst_kp_id: 8,
  dst_name: '导数应用',
  relation: 'prerequisite' as const,
  weight: 0.82,
  source: 'ai' as const,
  review_status: 'pending' as const,
  reviewed_at: null,
  created_at: '2026-11-04T01:00:00Z',
}

const STATS = {
  subject_id: 7,
  nodes: 108,
  edges: 120,
  by_relation: { prerequisite: 20 },
  by_status: { pending: 20, approved: 100 },
  last_built_at: null,
}

async function mountView() {
  const wrapper = mount(GraphReview, {
    props: { subjectId: 7 },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getGraphStats).mockResolvedValue(STATS)
  vi.mocked(listGraphEdges).mockResolvedValue({
    items: [EDGE],
    total: 1,
    page: 1,
    page_size: 20,
  })
})

describe('GraphReview', () => {
  it('渲染统计与边的两端名称', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('[data-testid="graph-stats"]').text()).toContain('待校验 20')
    expect(wrapper.text()).toContain('函数单调性')
    expect(wrapper.text()).toContain('导数应用')
  })

  it('默认只查待校验且带学科', async () => {
    await mountView()
    expect(listGraphEdges).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending', subject_id: 7, page: 1 }),
    )
  })

  it('单条通过调用审核接口并刷新', async () => {
    vi.mocked(reviewGraphEdge).mockResolvedValue({ ...EDGE, review_status: 'approved' })
    const wrapper = await mountView()
    await wrapper.findAll('button').find((btn) => btn.text() === '通过')!.trigger('click')
    await flushPromises()
    expect(reviewGraphEdge).toHaveBeenCalledWith(1, true)
    expect(listGraphEdges).toHaveBeenCalledTimes(2)
  })

  it('单条驳回调用审核接口', async () => {
    vi.mocked(reviewGraphEdge).mockResolvedValue({ ...EDGE, review_status: 'rejected' })
    const wrapper = await mountView()
    await wrapper.findAll('button').find((btn) => btn.text() === '驳回')!.trigger('click')
    await flushPromises()
    expect(reviewGraphEdge).toHaveBeenCalledWith(1, false)
  })

  it('批量驳回把已选 id 一起提交', async () => {
    vi.mocked(reviewGraphEdges).mockResolvedValue({ updated: 1, skipped: 0 })
    const wrapper = await mountView()
    wrapper.vm.$.exposed
    const table = wrapper.findComponent({ name: 'ElTable' })
    table.vm.$emit('selection-change', [EDGE])
    await flushPromises()
    await wrapper.get('[data-testid="graph-batch-reject"]').trigger('click')
    await flushPromises()
    expect(reviewGraphEdges).toHaveBeenCalledWith([1], false)
  })

  it('空列表显示空态文案', async () => {
    vi.mocked(listGraphEdges).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    })
    const wrapper = await mountView()
    expect(wrapper.get('[data-testid="graph-empty"]').text()).toContain('还没有 AI 推断的关系')
  })

  it('重建触发生成任务并轮询到 succeeded', async () => {
    vi.useFakeTimers()
    vi.mocked(buildGraph).mockResolvedValue({
      id: 77,
      name: 'graph.build',
      status: 'pending',
      created_at: '2026-11-04T01:00:00Z',
    })
    vi.mocked(getTask).mockResolvedValue({
      id: 77,
      name: 'graph.build',
      status: 'succeeded',
      created_at: '2026-11-04T01:00:00Z',
      payload: { subject_id: 7 },
      attempts: 1,
      result: null,
      error: null,
      started_at: '2026-11-04T01:00:05Z',
      finished_at: '2026-11-04T01:01:00Z',
    })
    const wrapper = await mountView()
    await wrapper.get('[data-testid="graph-rebuild"]').trigger('click')
    await vi.advanceTimersByTimeAsync(4000)
    await flushPromises()
    vi.useRealTimers()
    expect(buildGraph).toHaveBeenCalledWith({ subject_id: 7 })
    expect(getTask).toHaveBeenCalledWith(77)
  })

  it('加载失败时列表为空但不抛错', async () => {
    vi.mocked(listGraphEdges).mockRejectedValue(new Error('boom'))
    const wrapper = await mountView()
    expect(wrapper.findAll('[data-testid="graph-table"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('还没有 AI 推断的关系')
  })
})