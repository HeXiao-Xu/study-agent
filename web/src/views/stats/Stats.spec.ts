import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { StatsOverview } from '@/types/stats'

import Stats from './Stats.vue'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
  }
  return {
    chart,
    init: vi.fn((element: unknown) => ({ ...chart, getDom: () => element })),
    use: vi.fn(),
  }
})

vi.mock('echarts/core', () => ({ use: charts.use, init: charts.init }))
vi.mock('echarts/charts', () => ({ PieChart: {}, BarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({ fetchStatsOverview: vi.fn() }))
vi.mock('@/api/stats', () => ({ fetchStatsOverview: api.fetchStatsOverview }))

function overview(overrides: Partial<StatsOverview> = {}): StatsOverview {
  return {
    range: { key: '30d', from: '2026-10-06', to: '2026-11-04' },
    summary: {
      total: 34,
      pending: 33,
      corrected: 1,
      mastered: 0,
      analyzed: 34,
      with_kp: 3,
      mastery_rows: 5,
    },
    by_status: [
      { status: '待订正', count: 33 },
      { status: '已订正', count: 1 },
      { status: '已掌握', count: 0 },
    ],
    by_cause: [
      { cause_type: '概念不清', count: 11 },
      { cause_type: 'unknown', count: 1 },
    ],
    top_kps: [{ kp_id: 197, kp_name: '同角三角函数基本关系', count: 1, mastery: 0.144 }],
    trend: [{ date: '2026-11-03', new_mistakes: 34, mastered: 0 }],
    ...overrides,
  }
}

function mountPage() {
  return mount(Stats, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchStatsOverview.mockResolvedValue(overview())
})

describe('Stats 页面', () => {
  it('首屏渲染四张摘要卡与解释性提示', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('错题总数')
    expect(text).toContain('34 条错题中 34 条已诊断')
    expect(text).toContain('3 条挂知识点')
    expect(text).toContain('其余 31 条错题没有关联知识点')
    expect(api.fetchStatsOverview).toHaveBeenCalledWith('30d')
  })

  it('TOP10 卡片给掌握度四档颜色图例', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const legend = wrapper.get('[data-testid="top-kp-legend"]')
    expect(legend.text()).toContain('<0.4')
    expect(legend.text()).toContain('0.4–0.7')
    expect(legend.text()).toContain('≥0.7')
    expect(legend.text()).toContain('未评估')
    expect(legend.findAll('li')).toHaveLength(4)
  })

  it('三块画布都初始化并渲染', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(charts.init).toHaveBeenCalledTimes(3)
    expect(charts.chart.setOption).toHaveBeenCalledTimes(3)
    expect(wrapper.find('[data-testid="cause-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="top-kp-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="trend-chart"]').exists()).toBe(true)
  })

  it('切换窗口后把图表重新绑到新画布（骨架屏重建过 DOM）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(charts.init).toHaveBeenCalledTimes(3)
    const input = wrapper.find('[data-testid="range-7d"] input')
    await input.setValue(true)
    await flushPromises()
    // 三块容器在 loading 分支被销毁重建，必须重新 init，否则画布永远是空的
    expect(charts.init).toHaveBeenCalledTimes(6)
    expect(charts.chart.setOption).toHaveBeenCalledTimes(6)
  })

  it('切换窗口会重新请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    // Element Plus 的 radio-button 把值绑在内部 input 上，点 label 在 jsdom 里不触发 change
    const input = wrapper.find('[data-testid="range-7d"] input')
    await input.setValue(true)
    await flushPromises()
    expect(api.fetchStatsOverview).toHaveBeenLastCalledWith('7d')
  })

  it('没有错题时给空态，不画假数据', async () => {
    api.fetchStatsOverview.mockResolvedValue(
      overview({
        summary: {
          total: 0,
          pending: 0,
          corrected: 0,
          mastered: 0,
          analyzed: 0,
          with_kp: 0,
          mastery_rows: 0,
        },
        by_status: [],
        by_cause: [],
        top_kps: [],
        trend: [],
      }),
    )
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('窗口内没有错题')
  })

  it('没有诊断时提示而不是空图', async () => {
    api.fetchStatsOverview.mockResolvedValue(overview({ by_cause: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有错因诊断')
  })

  it('没有挂知识点的错题时提示', async () => {
    api.fetchStatsOverview.mockResolvedValue(overview({ top_kps: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有错题挂上知识点')
  })

  it('请求失败给错误提示', async () => {
    api.fetchStatsOverview.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('统计数据加载失败')
  })
})