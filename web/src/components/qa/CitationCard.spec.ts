import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CitationCard from './CitationCard.vue'
import type { QaCitation } from '@/types/qa'

const citation: QaCitation = {
  index: 1,
  note_id: 55,
  chunk_id: 255,
  title: '数列笔记',
  heading_path: '数列/错位相减法',
  page_no: 2,
  snippet: '错位相减法正文',
  score: 0.91,
  note_available: true,
}

describe('CitationCard', () => {
  it('renders metadata and emits open', async () => {
    const wrapper = mount(CitationCard, { props: { citation } })
    expect(wrapper.text()).toContain('数列笔记')
    expect(wrapper.text()).toContain('数列/错位相减法')
    expect(wrapper.text()).toContain('第 2 页')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ note_id: 55 })
  })

  it('disables the button when the note is unavailable', () => {
    const wrapper = mount(CitationCard, {
      props: { citation: { ...citation, note_available: false } },
    })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('原笔记已删除')
  })
})