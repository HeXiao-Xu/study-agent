import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import FileListView from './FileListView.vue'
import { getFileStatus, listFileChunks, listFiles } from '@/api/files'

vi.mock('@/api/files', () => ({
  listFiles: vi.fn(),
  getFileStatus: vi.fn(),
  listFileChunks: vi.fn(),
}))

const row = {
  id: 11,
  filename: '试卷.pdf',
  mime: 'application/pdf',
  size: 2048,
  parse_status: 'done' as const,
  parse_progress: 100,
  error_msg: null,
  chunk_count: 3,
  created_at: '2026-10-29T12:00:00+00:00',
  parse_finished_at: '2026-10-29T12:01:00+00:00',
}

function mountPage() {
  return mount(FileListView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        FileUploader: true,
      },
    },
  })
}

describe('FileListView', () => {
  beforeEach(() => {
    vi.mocked(listFiles).mockReset()
    vi.mocked(listFileChunks).mockReset()
    vi.mocked(getFileStatus).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders files with size, status and chunk count', async () => {
    vi.mocked(listFiles).mockResolvedValue({
      items: [row],
      total: 1,
      page: 1,
      page_size: 10,
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('试卷.pdf')
    expect(wrapper.text()).toContain('PDF · 2.0 KB')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('3 块')
  })

  it('shows the empty state when there are no files', async () => {
    vi.mocked(listFiles).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有文件')
  })

  it('shows an error and retries loading', async () => {
    vi.mocked(listFiles)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('文件列表加载失败')
    await wrapper.find('[data-testid="retry-list"]').trigger('click')
    await flushPromises()
    expect(listFiles).toHaveBeenCalledTimes(2)
  })

  it('requests the next page', async () => {
    vi.mocked(listFiles).mockResolvedValue({
      items: [row],
      total: 20,
      page: 1,
      page_size: 10,
    })
    const wrapper = mountPage()
    await flushPromises()
    wrapper.findComponent({ name: 'ElPagination' }).vm.$emit('current-change', 2)
    await flushPromises()
    expect(listFiles).toHaveBeenLastCalledWith({ page: 2, page_size: 10 })
  })

  it('polls historical active files until they finish', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    })
    vi.mocked(listFiles).mockResolvedValue({
      items: [{ ...row, parse_status: 'parsing', parse_progress: 50, chunk_count: 0 }],
      total: 1,
      page: 1,
      page_size: 10,
    })
    vi.mocked(getFileStatus).mockResolvedValue({
      ...row,
      parse_status: 'done',
      parse_progress: 100,
      chunk_count: 3,
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('解析中 50%')
    vi.advanceTimersByTime(3_000)
    await flushPromises()
    expect(getFileStatus).toHaveBeenCalledWith(11)
    expect(wrapper.text()).toContain('已完成')
    wrapper.unmount()
  })

  it('opens the chunk drawer with the first three chunks', async () => {
    vi.mocked(listFiles).mockResolvedValue({
      items: [row],
      total: 1,
      page: 1,
      page_size: 10,
    })
    vi.mocked(listFileChunks).mockResolvedValue([
      { chunk_index: 0, content: '第一块', token_count: 10 },
      { chunk_index: 1, content: '第二块', token_count: 11 },
      { chunk_index: 2, content: '第三块', token_count: 12 },
    ])
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="preview-chunks"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 80))
    await flushPromises()
    expect(listFileChunks).toHaveBeenCalledWith(11, 3)
    expect(wrapper.text()).toContain('第一块')
    expect(wrapper.text()).toContain('第三块')
  })
})