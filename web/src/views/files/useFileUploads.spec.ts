import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getFileStatus, uploadDocument } from '@/api/files'
import { useFileUploads } from '@/views/files/useFileUploads'

vi.mock('@/api/files', () => ({
  uploadDocument: vi.fn(),
  getFileStatus: vi.fn(),
}))

const record = {
  id: 11,
  filename: '试卷.pdf',
  mime: 'application/pdf',
  size: 100,
  sha256: 'x',
  parse_status: 'pending' as const,
  created_at: '2026-10-29T12:00:00+00:00',
  deduped: false,
}

const pending = {
  id: 11,
  filename: '试卷.pdf',
  parse_status: 'pending' as const,
  parse_progress: 0,
  error_msg: null,
  chunk_count: 0,
}

const done = {
  ...pending,
  parse_status: 'done' as const,
  parse_progress: 100,
  chunk_count: 3,
}

function pdf(name = '试卷.pdf'): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

describe('useFileUploads', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    })
    vi.mocked(uploadDocument).mockReset()
    vi.mocked(getFileStatus).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('rejects unsupported files before uploading', () => {
    const uploads = useFileUploads()
    const rejected = uploads.enqueue([new File(['png'], '图.png', { type: 'image/png' })])
    expect(rejected).toHaveLength(1)
    expect(uploadDocument).not.toHaveBeenCalled()
    uploads.dispose()
  })

  it('reports upload progress before status polling', async () => {
    let resolveUpload: (value: typeof record) => void = () => undefined
    vi.mocked(uploadDocument).mockImplementation((_file, onProgress) => {
      onProgress?.(42)
      return new Promise((resolve) => {
        resolveUpload = resolve
      })
    })
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    expect(uploads.tasks.value[0].progress).toBe(42)
    expect(uploads.tasks.value[0].phase).toBe('uploading')
    vi.mocked(getFileStatus).mockResolvedValue(pending)
    resolveUpload(record)
    await flushPromises()
    uploads.dispose()
  })

  it('polls until done and emits the finished task', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValueOnce(pending).mockResolvedValueOnce(done)
    const onFinished = vi.fn()
    const uploads = useFileUploads({ onFinished })
    uploads.enqueue([pdf()])
    await flushPromises()
    expect(getFileStatus).toHaveBeenCalledWith(11)
    expect(uploads.tasks.value[0].phase).toBe('pending')
    vi.advanceTimersByTime(3_000)
    await flushPromises()
    expect(uploads.tasks.value[0].phase).toBe('done')
    expect(uploads.tasks.value[0].chunkCount).toBe(3)
    expect(onFinished).toHaveBeenCalledTimes(1)
    uploads.dispose()
  })

  it('shows failed status and retries with the same file', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValue({
      ...pending,
      parse_status: 'failed',
      error_msg: 'RuntimeError: bad pdf',
    })
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    const task = uploads.tasks.value[0]
    expect(task.phase).toBe('failed')
    expect(task.error).toBe('RuntimeError: bad pdf')
    uploads.retry(task.uid)
    await flushPromises()
    expect(uploadDocument).toHaveBeenCalledTimes(2)
    uploads.dispose()
  })

  it('times out polling after five minutes', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValue(pending)
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    vi.setSystemTime(Date.now() + 300_001)
    vi.advanceTimersByTime(3_000)
    await flushPromises()
    expect(uploads.tasks.value[0].phase).toBe('timeout')
    uploads.dispose()
  })
})