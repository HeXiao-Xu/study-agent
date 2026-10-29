import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import FileUploader from './FileUploader.vue'
import { uploadDocument } from '@/api/files'

vi.mock('@/api/files', () => ({
  uploadDocument: vi.fn(),
  getFileStatus: vi.fn(),
}))

function makeFile(name = '试卷.pdf'): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

async function selectFiles(wrapper: ReturnType<typeof mount>, files: File[]) {
  const input = wrapper.find('[data-testid="file-input"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  await input.trigger('change')
  await flushPromises()
}

describe('FileUploader', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    })
    vi.mocked(uploadDocument).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('enqueues selected documents and shows the file name', async () => {
    vi.mocked(uploadDocument).mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(FileUploader, { global: { plugins: [ElementPlus] } })
    await selectFiles(wrapper, [makeFile()])
    expect(wrapper.text()).toContain('试卷.pdf')
    expect(uploadDocument).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('renders a queue item and clears finished items', async () => {
    vi.mocked(uploadDocument).mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(FileUploader, { global: { plugins: [ElementPlus] } })
    await selectFiles(wrapper, [makeFile('讲义.md')])
    expect(wrapper.find('[data-testid^="upload-task-"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('讲义.md')
    wrapper.unmount()
  })
})