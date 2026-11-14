import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PaperSummary } from '@/types/papers'

import PaperListView from './PaperListView.vue'

const papers = vi.hoisted(() => ({
  listPapers: vi.fn(),
  exportPaperPdf: vi.fn(),
}))
vi.mock('@/api/papers', () => papers)

const summary: PaperSummary = {
  id: 13,
  title: '2026-11-14 组卷（8 题）',
  status: '草稿',
  total_score: 51,
  question_count: 8,
  created_at: '2026-11-14T13:43:16Z',
}

function mountPage() {
  return mount(PaperListView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :data-to="to"><slot /></a>',
        },
      },
    },
  })
}

beforeEach(() => {
  papers.listPapers.mockReset()
  papers.exportPaperPdf.mockReset()
})

describe('PaperListView', () => {
  it('renders saved papers and the continue action', async () => {
    papers.listPapers.mockResolvedValue({ items: [summary], total: 1, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('2026-11-14 组卷（8 题）')
    expect(wrapper.text()).toContain('草稿')
    expect(wrapper.text()).toContain('51 分')
    expect(wrapper.text()).toContain('8 题')
    expect(wrapper.find('[data-testid="open-paper-13"]').attributes('data-to')).toBe(
      '/papers/13/take',
    )
  })

  it('shows an empty state with a link to generate', async () => {
    papers.listPapers.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('还没有保存过试卷')
    expect(wrapper.find('[data-testid="empty-generate"]').attributes('data-to')).toBe(
      '/papers/generate',
    )
  })

  it('requests the next page', async () => {
    papers.listPapers.mockResolvedValue({ items: [summary], total: 20, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()

    wrapper.findComponent({ name: 'ElPagination' }).vm.$emit('current-change', 2)
    await flushPromises()

    expect(papers.listPapers).toHaveBeenLastCalledWith({ page: 2, page_size: 10 })
  })

  it('exports the saved paper as a questions PDF', async () => {
    papers.listPapers.mockResolvedValue({ items: [summary], total: 1, page: 1, page_size: 10 })
    papers.exportPaperPdf.mockResolvedValue(new Blob(['%PDF-1.4']))
    const createObjectURL = vi.fn(() => 'blob:paper')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('[data-testid="export-questions-13"]').trigger('click')
    await flushPromises()

    expect(papers.exportPaperPdf).toHaveBeenCalledWith(13, 'questions')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:paper')
  })
})