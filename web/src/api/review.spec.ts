import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { ReviewItem, ReviewToday } from '@/types/review'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import {
  getTodayReview,
  markReviewDone,
  markReviewLater,
  markReviewSkip,
  refreshReview,
} from './review'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

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
    items: [item()],
    item_count: 1,
    total_minutes: 12,
    cap_minutes: 35,
    truncated_count: null,
    ...overrides,
  }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('review api', () => {
  it('refreshes the today list with POST', async () => {
    http.post.mockResolvedValue(envelope(today()))
    const data = await refreshReview()
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/refresh')
    expect(data.item_count).toBe(1)
  })

  it('gets the read-only today list', async () => {
    http.get.mockResolvedValue(envelope(today()))
    await getTodayReview()
    expect(http.get).toHaveBeenCalledWith('/api/v1/review/today')
  })

  it('marks an item done', async () => {
    http.post.mockResolvedValue(envelope(item({ done_at: '2026-11-14T02:00:00Z' })))
    const row = await markReviewDone(1)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/1/done')
    expect(row.done_at).not.toBeNull()
  })

  it('marks an item skipped', async () => {
    http.post.mockResolvedValue(envelope(item()))
    await markReviewSkip(2)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/2/skip')
  })

  it('marks an item later', async () => {
    http.post.mockResolvedValue(envelope(item()))
    await markReviewLater(3)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/3/later')
  })
})