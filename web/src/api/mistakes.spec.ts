import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createMistake,
  createMistakeFromPhoto,
  deleteMistake,
  getMistake,
  getMistakeStats,
  listMistakes,
  reviewMistake,
  updateMistake,
} from './mistakes'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/api/http', () => ({
  API_PREFIX: '/api/v1',
  default: http,
}))

function envelope<T>(data: T) {
  return { data: { code: 0, message: 'ok', trace_id: 'trace-1', data } }
}

const summary = {
  id: 7,
  question_id: 21,
  status: '待订正',
  correct_streak: 0,
  stem_excerpt: '题干摘要',
  subject_id: 3,
  qtype: '单选',
  difficulty: 3,
  kp_names: ['函数'],
  cause_type: null,
  has_image: false,
  created_at: '2026-11-01T08:00:00Z',
  last_review_at: null,
}

const detail = {
  ...summary,
  stem_md: '完整题干',
  options: [{ key: 'A', text: '选项 A' }],
  my_answer_md: null,
  correct_answer_md: 'A',
  image_url: null,
  analysis: null,
}

const stats = {
  total: 3,
  by_status: [{ status: '待订正', count: 3 }],
  by_cause: [{ cause_type: '计算失误', count: 1 }],
  top_kps: [{ kp_id: 4, kp_name: '函数', count: 2 }],
}

describe('mistakes api', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('maps camelCase list filters to snake_case query params', async () => {
    const page = { items: [summary], total: 1, page: 2, page_size: 20 }
    http.get.mockResolvedValue(envelope(page))

    const result = await listMistakes({
      status: '待订正',
      causeType: '计算失误',
      kpId: 12,
      createdFrom: '2026-10-01T00:00:00Z',
      createdTo: '2026-11-01T00:00:00Z',
      page: 2,
      pageSize: 20,
      sortBy: 'created_at',
      order: 'desc',
    })

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes', {
      params: {
        status: '待订正',
        cause_type: '计算失误',
        kp_id: 12,
        created_from: '2026-10-01T00:00:00Z',
        created_to: '2026-11-01T00:00:00Z',
        page: 2,
        page_size: 20,
        sort_by: 'created_at',
        order: 'desc',
      },
    })
    expect(result).toBe(page)
  })

  it('omits undefined list filters from the query', async () => {
    const page = { items: [], total: 0, page: 1, page_size: 10 }
    http.get.mockResolvedValue(envelope(page))

    await listMistakes({ page: 1, pageSize: 10 })

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes', {
      params: { page: 1, page_size: 10 },
    })
  })

  it('drops empty-string list filters instead of sending them', async () => {
    http.get.mockResolvedValue(envelope({ items: [], total: 0, page: 1, page_size: 10 }))

    await listMistakes({ status: '', causeType: '', kpId: undefined })

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes', { params: {} })
  })

  it('maps stats time bounds to snake_case query params', async () => {
    http.get.mockResolvedValue(envelope(stats))

    const result = await getMistakeStats({
      createdFrom: '2026-10-01T00:00:00Z',
      createdTo: '2026-11-01T00:00:00Z',
    })

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes/stats', {
      params: {
        created_from: '2026-10-01T00:00:00Z',
        created_to: '2026-11-01T00:00:00Z',
      },
    })
    expect(result).toBe(stats)
  })

  it('sends an empty stats query when no time bounds are given', async () => {
    http.get.mockResolvedValue(envelope(stats))

    await getMistakeStats()

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes/stats', { params: {} })
  })

  it('drops an empty-string stats bound instead of sending it', async () => {
    http.get.mockResolvedValue(envelope(stats))

    await getMistakeStats({ createdFrom: '' })

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes/stats', { params: {} })
  })

  it('creates a mistake from the question bank with snake_case body', async () => {
    const created = { ...detail, created: true }
    http.post.mockResolvedValue(envelope(created))

    const result = await createMistake({ questionId: 21, myAnswerMd: '我的答案' })

    expect(http.post).toHaveBeenCalledWith('/api/v1/mistakes', {
      question_id: 21,
      my_answer_md: '我的答案',
    })
    expect(result.created).toBe(true)
  })

  it('appends the optional my_answer_md form field for photo capture', async () => {
    const task = { id: 31, name: 'mistake.recognize', status: 'pending', created_at: '' }
    http.post.mockResolvedValue(envelope(task))
    const file = new File(['fake'], 'mistake.png', { type: 'image/png' })

    const result = await createMistakeFromPhoto(file, 3, '手写作答')

    const [url, form, config] = http.post.mock.calls.at(-1) ?? []
    const body = form as FormData
    expect(url).toBe('/api/v1/mistakes/photo')
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('file')).toBe(file)
    expect(body.get('my_answer_md')).toBe('手写作答')
    expect(config).toEqual({ params: { subject_id: 3 }, timeout: 120_000 })
    expect(result).toBe(task)
  })

  it('omits my_answer_md from the photo form when not provided', async () => {
    http.post.mockResolvedValue(envelope({}))
    const file = new File(['fake'], 'mistake.jpg', { type: 'image/jpeg' })

    await createMistakeFromPhoto(file, 3)

    const [, form] = http.post.mock.calls.at(-1) ?? []
    expect((form as FormData).has('my_answer_md')).toBe(false)
  })

  it('omits an empty my_answer_md from the photo form', async () => {
    http.post.mockResolvedValue(envelope({}))
    const file = new File(['fake'], 'mistake.jpg', { type: 'image/jpeg' })

    await createMistakeFromPhoto(file, 3, '')

    const [, form] = http.post.mock.calls.at(-1) ?? []
    expect((form as FormData).has('my_answer_md')).toBe(false)
  })

  it('fetches one mistake detail and unwraps the envelope', async () => {
    http.get.mockResolvedValue(envelope(detail))

    const result = await getMistake(7)

    expect(http.get).toHaveBeenCalledWith('/api/v1/mistakes/7')
    expect(result).toBe(detail)
  })

  it('patches a mistake and keeps explicit nulls for clearing fields', async () => {
    http.patch.mockResolvedValue(envelope(detail))

    await updateMistake(7, { status: '已掌握', myAnswerMd: null })

    expect(http.patch).toHaveBeenCalledWith('/api/v1/mistakes/7', {
      status: '已掌握',
      my_answer_md: null,
    })
  })

  it('records a review result with the correct flag', async () => {
    http.post.mockResolvedValue(envelope(detail))

    await reviewMistake(7, false)

    expect(http.post).toHaveBeenCalledWith('/api/v1/mistakes/7/review', { correct: false })
  })

  it('deletes a mistake', async () => {
    http.delete.mockResolvedValue({ data: { code: 0, message: 'ok', trace_id: 't', data: null } })

    await deleteMistake(7)

    expect(http.delete).toHaveBeenCalledWith('/api/v1/mistakes/7')
  })
})
