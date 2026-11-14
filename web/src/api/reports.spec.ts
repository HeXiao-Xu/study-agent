import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { ReportOverview, WeeklyReport } from '@/types/reports'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import { fetchReportOverview, generateWeeklyReport } from './reports'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('reports api', () => {
  it('requests mastery overview with the range param', async () => {
    http.get.mockResolvedValue(envelope<ReportOverview>({ range: {} } as ReportOverview))
    await fetchReportOverview('7d')
    expect(http.get).toHaveBeenCalledWith('/api/v1/reports/mastery', {
      params: { range: '7d' },
    })
  })

  it('defaults to 30d', async () => {
    http.get.mockResolvedValue(envelope<ReportOverview>({ range: {} } as ReportOverview))
    await fetchReportOverview()
    expect(http.get).toHaveBeenCalledWith('/api/v1/reports/mastery', {
      params: { range: '30d' },
    })
  })

  it('posts weekly generation without a body', async () => {
    http.post.mockResolvedValue(envelope<WeeklyReport>({ generated_by: 'empty' } as WeeklyReport))
    const data = await generateWeeklyReport()
    expect(http.post).toHaveBeenCalledWith('/api/v1/reports/weekly')
    expect(data.generated_by).toBe('empty')
  })
})