import { describe, expect, it } from 'vitest'

import { toScopePayload } from './scope'

describe('toScopePayload', () => {
  it('drops empty fields and trims folder', () => {
    expect(
      toScopePayload({
        subjectId: null,
        folder: '  数列  ',
        dateRange: null,
      }),
    ).toEqual({ folder: '数列' })
  })

  it('maps date range to ISO dates', () => {
    expect(
      toScopePayload({
        subjectId: 7,
        folder: '',
        dateRange: ['2026-01-01', '2026-02-01'],
      }),
    ).toEqual({
      subject_id: 7,
      start_date: '2026-01-01',
      end_date: '2026-02-01',
    })
  })

  it('returns null when nothing is selected', () => {
    expect(
      toScopePayload({ subjectId: null, folder: '  ', dateRange: null }),
    ).toBeNull()
  })

  it('rejects an inverted date range', () => {
    expect(() =>
      toScopePayload({
        subjectId: null,
        folder: '',
        dateRange: ['2026-02-01', '2026-01-01'],
      }),
    ).toThrow('结束日期不能早于开始日期')
  })
})