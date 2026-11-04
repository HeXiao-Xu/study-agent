import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphNodeDetail, GraphSnapshot } from '@/types/graph'

import Graph from './Graph.vue'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
    dispatchAction: vi.fn(),
  }
  return { chart, init: vi.fn(() => chart), use: vi.fn() }
})

vi.mock('echarts/core', () => ({ use: charts.use, init: charts.init }))
vi.mock('echarts/charts', () => ({ GraphChart: {} }))
vi.mock('echarts/components', () => ({ TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({
  fetchGraphSnapshot: vi.fn(),
  fetchGraphNode: vi.fn(),
  listSubjects: vi.fn(),
}))

vi.mock('@/api/graph', () => ({
  fetchGraphSnapshot: api.fetchGraphSnapshot,
  fetchGraphNode: api.fetchGraphNode,
}))
vi.mock('@/api/kp', () => ({ listSubjects: api.listSubjects }))

const store = vi.hoisted(() => ({ role: 'student' }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role: store.role } }),
}))

const routerPush = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))

function node(id: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    name,
    level: 3,
    parent_id: 2,
    exam_weight: 0.5,
    mistake_count: 0,
    mastery: 0.5,
    ...extra,
  }
}

function snapshot(overrides: Partial<GraphSnapshot> = {}): GraphSnapshot {
  return {
    subject: { id: 7, name: '高中数学' },
    nodes: [
      { id: 1, name: '高中数学', level: 1, parent_id: null, exam_weight: 1, mistake_count: 0, mastery: null },
      { id: 2, name: '函数', level: 2, parent_id: 1, exam_weight: 1, mistake_count: 0, mastery: 0.42 },
      node(3, '单调性'),
      node(4, '导数与函数的单调性'),
    ],
    edges: [{ src_kp_id: 3, dst_kp_id: 4, relation: 'prerequisite', weight: 0.9 }],
    stats: {
      nodes: 4,
      edges: 1,
      pending_edges: 0,
      by_relation: { contains: 0, prerequisite: 1, related: 0, confusable: 0 },
    },
    ...overrides,
  }
}

const detail: GraphNodeDetail = {
  id: 4,
  name: '导数与函数的单调性',
  level: 3,
  parent_id: 2,
  subject_id: 7,
  path: ['高中数学', '导数及其应用', '导数与函数的单调性'],
  description: null,
  exam_weight: 0.8,
  mistake_count: 0,
  prerequisites: [{ kp_id: 3, name: '单调性', weight: 0.9 }],
  successors: [],
  related: [],
  confusable: [],
  notes: [],
  mistakes: [],
}

function mountPage() {
  return mount(Graph, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        'el-drawer': {
          template: '<div data-testid="drawer"><slot /></div>',
          props: ['modelValue'],
        },
      },
    },
  })
}

beforeEach(() => {
  api.fetchGraphSnapshot.mockReset()
  api.fetchGraphNode.mockReset()
  api.listSubjects.mockReset()
  charts.init.mockClear()
  charts.chart.setOption.mockClear()
  charts.chart.on.mockClear()
  charts.chart.dispatchAction.mockClear()
  routerPush.mockReset()
  store.role = 'student'
  api.listSubjects.mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  api.fetchGraphSnapshot.mockResolvedValue(snapshot())
  api.fetchGraphNode.mockResolvedValue(detail)
})

describe('Graph 页面', () => {
  it('首屏拉快照并渲染画布', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.fetchGraphSnapshot).toHaveBeenCalledWith(7)
    expect(charts.init).toHaveBeenCalled()
    expect(charts.chart.setOption).toHaveBeenCalled()
    const first = charts.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data: Array<{ id: string }> }>
    }
    // contains 默认关闭 → 只画前置边，节点仍是全部 4 个
    expect(first.series[0].data).toHaveLength(4)
    wrapper.unmount()
  })

  it('点节点打开抽屉并展示前置与空态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const clickHandler = charts.chart.on.mock.calls.find(([name]) => name === 'click')?.[1] as (
      params: { dataType: string; data: { id: string } },
    ) => void
    clickHandler({ dataType: 'node', data: { id: '4' } })
    await flushPromises()
    expect(api.fetchGraphNode).toHaveBeenCalledWith(4)
    const text = wrapper.text()
    expect(text).toContain('导数与函数的单调性')
    expect(text).toContain('单调性')
    expect(text).toContain('暂无描述')
    expect(text).toContain('暂无关联笔记')
    wrapper.unmount()
  })

  it('节点超过阈值时显示降级横幅', async () => {
    const many = Array.from({ length: 301 }, (_, index) => node(100 + index, `节点${index}`))
    api.fetchGraphSnapshot.mockResolvedValue(snapshot({ nodes: many, edges: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('降级为子图模式')
    wrapper.unmount()
  })

  it('老师看到待校验提示，学生看不到', async () => {
    api.fetchGraphSnapshot.mockResolvedValue(
      snapshot({
        stats: {
          nodes: 4,
          edges: 1,
          pending_edges: 50,
          by_relation: { contains: 0, prerequisite: 1, related: 0, confusable: 0 },
        },
      }),
    )
    const student = mountPage()
    await flushPromises()
    expect(student.text()).not.toContain('50 条待校验')
    student.unmount()

    store.role = 'teacher'
    const teacher = mountPage()
    await flushPromises()
    expect(teacher.text()).toContain('50 条待校验')
    teacher.unmount()
  })

  it('搜索选中节点后高亮并打开抽屉', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      keyword: string
      onPickSearch: (id: number) => void
    }
    vm.keyword = '导数'
    vm.onPickSearch(4)
    await flushPromises()
    expect(api.fetchGraphNode).toHaveBeenCalledWith(4)
    expect(charts.chart.dispatchAction).toHaveBeenCalled()
    wrapper.unmount()
  })
})