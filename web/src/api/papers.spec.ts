import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { PaperDetail, PaperPreview } from '@/types/papers'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import { exportPaperPdf, generatePaper, getPaper, replacePaperItem, savePaper } from './papers'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('papers api', () => {
  it('posts the generate payload and unwraps the envelope', async () => {
    http.post.mockResolvedValue(envelope<PaperPreview>({ ok: true } as PaperPreview))
    const payload = {
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
    }
    const preview = await generatePaper(payload)
    expect(http.post).toHaveBeenCalledWith('/api/v1/papers/generate', payload)
    expect(preview.ok).toBe(true)
  })

  it('posts the replace payload', async () => {
    http.post.mockResolvedValue(envelope({ replaced: true, item: null, reason: null }))
    await replacePaperItem({
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
      selected_question_ids: [1],
      replace_question_id: 1,
    })
    expect(http.post.mock.calls[0]![0]).toBe('/api/v1/papers/replace-item')
  })

  it('posts save payload to /papers', async () => {
    http.post.mockResolvedValue(envelope({ id: 7, title: 't', status: '草稿' }))
    const payload = {
      title: 't',
      constraint: {
        kp_ids: [101],
        total_questions: 2,
        qtype_ratio: { 单选: 1 },
        difficulty_dist: { 2: 1 },
        total_score: 6,
      },
      question_ids: [1],
    }
    const paper = await savePaper(payload)
    expect(http.post).toHaveBeenCalledWith('/api/v1/papers', payload)
    expect(paper.id).toBe(7)
  })

  it('requests the export as a blob with the chosen variant', async () => {
    const blob = new Blob(['%PDF-1.4'], { type: 'application/pdf' })
    http.get.mockResolvedValue({ data: blob })

    const result = await exportPaperPdf(7, 'answers')

    expect(http.get).toHaveBeenCalledWith('/api/v1/papers/7/export.pdf', {
      params: { variant: 'answers' },
      responseType: 'blob',
      timeout: 60_000,
    })
    expect(result).toBe(blob)
  })

  it('gets a paper by id', async () => {
    http.get.mockResolvedValue(envelope<PaperDetail>({ id: 7 } as PaperDetail))
    const detail = await getPaper(7)
    expect(http.get).toHaveBeenCalledWith('/api/v1/papers/7')
    expect(detail.id).toBe(7)
  })
})