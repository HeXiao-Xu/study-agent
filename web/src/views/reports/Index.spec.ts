import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReportOverview, WeeklyReport } from '@/types/reports'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    getDataURL: vi.fn(() => 'data:image/png;base64,abc'),
    dispose: vi.fn(),
  }
  return {
    chart,
    init: vi.fn((element: unknown) => ({ ...chart, getDom: () => element })),
    use: vi.fn(),
  }
})
vi.mock('echarts/core', () => ({ use: charts.use, init: charts.init }))
vi.mock('echarts/charts', () => ({ RadarChart: {}, TreemapChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({
  fetchReportOverview: vi.fn(),
  fetchWeeklyReport: vi.fn(),
  generateWeeklyReport: vi.fn(),
}))
vi.mock('@/api/reports', () => api)

vi.mock('md-editor-v3', () => ({
  MdPreview: {
    props: ['modelValue'],
    template: '<div data-testid="weekly-md">{{ modelValue }}</div>',
  },
}))

const image = vi.hoisted(() => ({ downloadReportImage: vi.fn() }))
vi.mock('./exportReportImage', () => image)

import Reports from './Index.vue'

function overview(overrides: Partial<ReportOverview> = {}): ReportOverview {
  return {
    range: { key: '30d', from: '2026-10-16', to: '2026-11-14' },
    subjects: [
      {
        subject_id: 7,
        subject_name: '高中数学',
        modules: [
          { kp_id: 115, kp_name: '函数', exam_weight: 0.8, kp_count: 3, assessed_count: 2, mastery: 0.52 },
          { kp_id: 120, kp_name: '数列', exam_weight: 0.4, kp_count: 2, assessed_count: 0, mastery: null },
        ],
        heatmap: [
          { kp_id: 115, kp_name: '函数', parent_id: null, level: 2, exam_weight: 0.8, mastery: 0.5, mastery_t: 0.48, color_value: 0.52, assessed: true },
          { kp_id: 120, kp_name: '数列', parent_id: null, level: 2, exam_weight: 0.4, mastery: null, mastery_t: null, color_value: null, assessed: false },
        ],
      },
    ],
    trend: [
      { date: '2026-11-13', new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
    ],
    ...overrides,
  }
}

function weekly(overrides: Partial<WeeklyReport> = {}): WeeklyReport {
  return {
    period: { from: '2026-11-08', to: '2026-11-14', days: 7 },
    generated_by: 'llm',
    report_md: '## 本周概览\n本周新增 1 条。',
    stats: {
      totals: { new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
      active_days: 2,
      mastery: { assessed_kp_count: 2, avg_mastery: 0.5, weak_modules: [], weak_kps: [] },
      trend: [],
    },
    validation: { ok: true, attempts: 1, checked_numbers: ['1', '2', '3'], invalid_numbers: [] },
    ...overrides,
  }
}

function mountPage() {
  return mount(Reports, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchReportOverview.mockResolvedValue(overview())
  api.fetchWeeklyReport.mockResolvedValue(null)
  api.generateWeeklyReport.mockResolvedValue(weekly())
})

describe('Reports 页面', () => {
  it('默认加载 30d，初始化三张图并渲染摘要', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.fetchReportOverview).toHaveBeenCalledWith('30d')
    expect(charts.init).toHaveBeenCalledTimes(3)
    expect(charts.chart.setOption).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('新增笔记')
    expect(wrapper.text()).toContain('模块雷达')
  })

  it('切换 range 会重新请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="report-range-7d"] input').setValue(true)
    await flushPromises()
    expect(api.fetchReportOverview).toHaveBeenLastCalledWith('7d')
  })

  it('进入页面不生成周报，点击后才调用', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.fetchWeeklyReport).toHaveBeenCalledTimes(1)
    expect(api.generateWeeklyReport).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="weekly-generate"]').text()).toContain('生成周报')
    await wrapper.get('[data-testid="weekly-generate"]').trigger('click')
    await flushPromises()
    expect(api.generateWeeklyReport).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="weekly-report"]').text()).toContain('本周新增 1 条')
  })

  it('进入页面读取当天缓存的周报', async () => {
    api.fetchWeeklyReport.mockResolvedValue(weekly())
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.get('[data-testid="weekly-report"]').text()).toContain('本周新增 1 条')
    expect(wrapper.get('[data-testid="weekly-generate"]').text()).toContain('重新生成周报')
  })

  it('重新生成失败时保留已缓存的周报', async () => {
    api.fetchWeeklyReport.mockResolvedValue(weekly({ report_md: '缓存的旧周报' }))
    api.generateWeeklyReport.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="weekly-generate"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="weekly-error"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="weekly-report"]').text()).toContain('缓存的旧周报')
  })

  it('空数据给空态，不画假图', async () => {
    api.fetchReportOverview.mockResolvedValue(overview({ subjects: [], trend: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无知识库数据')
    expect(wrapper.find('[data-testid="report-radar"]').exists()).toBe(false)
  })

  it('加载失败给错误与重试', async () => {
    api.fetchReportOverview.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('报告加载失败')
  })

  it('导出按钮在图表就绪时可点击，并调用导出', async () => {
    const wrapper = mountPage()
    await flushPromises()
    for (const id of ['report-radar', 'report-treemap', 'report-trend']) {
      const element = wrapper.get(`[data-testid="${id}"]`).element as HTMLElement
      Object.defineProperty(element, 'clientWidth', { configurable: true, value: 600 })
      Object.defineProperty(element, 'clientHeight', { configurable: true, value: 280 })
    }
    const button = wrapper.get('[data-testid="report-export"]')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await flushPromises()
    expect(image.downloadReportImage).toHaveBeenCalled()
  })
})