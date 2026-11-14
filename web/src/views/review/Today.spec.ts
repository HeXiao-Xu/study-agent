import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReviewItem, ReviewToday } from '@/types/review'

const api = vi.hoisted(() => ({
  refreshReview: vi.fn(),
  markReviewDone: vi.fn(),
  markReviewSkip: vi.fn(),
  markReviewLater: vi.fn(),
}))
vi.mock('@/api/review', () => api)
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
  }
})

import Today from './Today.vue'

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 1,
    kp_id: 197,
    kp_name: '同角三角函数基本关系',
    subject_id: 7,
    ref_type: 'mistake',
    ref_id: 31,
    ref_title: '测试错题',
    ref_available: true,
    due_at: '2026-11-14T00:00:00Z',
    interval_days: 2,
    priority: 0.72,
    estimated_minutes: 12,
    mastery: 0.2,
    mastery_t: 0.18,
    stability: 2.5,
    attempts: 3,
    overdue_days: 1.5,
    low_mastery: true,
    done_at: null,
    ...overrides,
  }
}

function today(overrides: Partial<ReviewToday> = {}): ReviewToday {
  return {
    date: '2026-11-14',
    timezone: 'Asia/Shanghai',
    items: [item(), item({ id: 2, ref_type: 'question', ref_id: 8, kp_name: '函数单调性' })],
    item_count: 2,
    total_minutes: 24,
    cap_minutes: 35,
    truncated_count: null,
    ...overrides,
  }
}

function mountPage() {
  return mount(Today, {
    global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.refreshReview.mockResolvedValue(today())
  api.markReviewDone.mockResolvedValue(item({ done_at: '2026-11-14T02:00:00Z' }))
  api.markReviewSkip.mockResolvedValue(item())
  api.markReviewLater.mockResolvedValue(item())
  vi.mocked(ElMessage.success).mockReset()
})

describe('Today 复习页', () => {
  it('进入页面先 refresh，并渲染日期、分钟与两项', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.refreshReview).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('2026-11-14')
    expect(wrapper.text()).toContain('24 分钟')
    expect(wrapper.findAll('[data-testid^="review-item-"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('同角三角函数基本关系')
  })

  it('完成一项后移除卡片并推进进度', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="done-1"]').trigger('click')
    await flushPromises()
    expect(api.markReviewDone).toHaveBeenCalledWith(1)
    expect(wrapper.find('[data-testid="review-item-1"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="review-progress"]').text()).toContain('已处理 1/2')
    expect(ElMessage.success).toHaveBeenCalledWith('已记录')
  })

  it('跳过和稍后分别调用对应接口并移除', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="skip-1"]').trigger('click')
    await flushPromises()
    expect(api.markReviewSkip).toHaveBeenCalledWith(1)
    await wrapper.get('[data-testid="later-2"]').trigger('click')
    await flushPromises()
    expect(api.markReviewLater).toHaveBeenCalledWith(2)
    expect(wrapper.findAll('[data-testid^="review-item-"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('今天的复习已完成')
  })

  it('显示顺延提示', async () => {
    api.refreshReview.mockResolvedValue(today({ truncated_count: 3 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('有 3 项顺延到明天')
  })

  it('空清单给空态和去组卷入口', async () => {
    api.refreshReview.mockResolvedValue(today({ items: [], item_count: 0, total_minutes: 0 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('今天没有待复习项')
    expect(wrapper.text()).toContain('去组卷')
  })

  it('操作失败保留卡片并提示可重试', async () => {
    api.markReviewDone.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="done-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="review-item-1"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('操作失败，请重试')
  })

  it('资源不可用时不显示跳转链接', async () => {
    api.refreshReview.mockResolvedValue(
      today({ items: [item({ ref_available: false })], item_count: 1 }),
    )
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('参考资源已删除')
    expect(wrapper.find('a').exists()).toBe(false)
  })
})