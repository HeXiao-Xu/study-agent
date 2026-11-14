import { describe, expect, it } from 'vitest'

import type { ReviewItem } from '@/types/review'

import {
  minutesLabel,
  progressOf,
  reviewRefPath,
  truncatedLabel,
} from './useReviewProgress'

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 1,
    kp_id: 1,
    kp_name: '函数',
    subject_id: 7,
    ref_type: 'mistake',
    ref_id: 31,
    ref_title: '错题',
    ref_available: true,
    due_at: '2026-11-14T00:00:00Z',
    interval_days: 1,
    priority: 0.5,
    estimated_minutes: 10,
    mastery: 0.2,
    mastery_t: 0.2,
    stability: 1,
    attempts: 1,
    overdue_days: 0,
    low_mastery: true,
    done_at: null,
    ...overrides,
  }
}

describe('progressOf', () => {
  it('clamps processed and computes rounded percent', () => {
    expect(progressOf(3, 1)).toEqual({
      processed: 1,
      total: 3,
      percent: 33,
      label: '已处理 1/3',
    })
  })

  it('handles zero and overflow without NaN', () => {
    expect(progressOf(0, 2)).toEqual({ processed: 0, total: 0, percent: 0, label: '已处理 0/0' })
    expect(progressOf(2, 9).processed).toBe(2)
  })
})

describe('labels', () => {
  it('formats minutes and truncated count', () => {
    expect(minutesLabel(12)).toBe('12 分钟')
    expect(truncatedLabel(null)).toBe('')
    expect(truncatedLabel(0)).toBe('')
    expect(truncatedLabel(2)).toBe('有 2 项顺延到明天')
  })
})

describe('reviewRefPath', () => {
  it('routes mistakes and questions, and hides unavailable refs', () => {
    expect(reviewRefPath(item())).toBe('/mistakes/31')
    expect(reviewRefPath(item({ ref_type: 'question', ref_id: 8 }))).toBe('/questions')
    expect(reviewRefPath(item({ ref_available: false }))).toBeNull()
  })
})