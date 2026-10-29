import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  listPendingAlign: vi.fn(),
  confirmAlign: vi.fn(),
  rejectAlign: vi.fn(),
}))

import { confirmAlign, listPendingAlign, rejectAlign } from '@/api/kp'
import type { PendingAlign as PendingItem } from '@/types/kp'
import PendingAlign from './PendingAlign.vue'

enableAutoUnmount(afterEach)

function item(id: number): PendingItem {
  return {
    note_id: id,
    kp_id: 100 + id,
    confidence: 0.68,
    note_title: `笔记${id}`,
    note_excerpt: `这是第 ${id} 条摘要`,
    kp_name: `知识点${id}`,
    kp_code: `MATH-${id}`,
  }
}

function page(items: PendingItem[], total = items.length) {
  return { items, total, page: 1, page_size: 20 }
}

async function mountPending() {
  const wrapper = mount(PendingAlign, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

describe('PendingAlign', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(confirmAlign).mockResolvedValue({ confirmed: 1, deleted: 0, skipped: 0 })
    vi.mocked(rejectAlign).mockResolvedValue({ confirmed: 0, deleted: 1, skipped: 0 })
  })

  it('renders excerpt and candidate knowledge point', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    const wrapper = await mountPending()
    expect(wrapper.text()).toContain('笔记1')
    expect(wrapper.text()).toContain('这是第 1 条摘要')
    expect(wrapper.text()).toContain('知识点1')
    expect(wrapper.text()).toContain('MATH-1')
  })

  it('confirms with Enter and shows the next card', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1), item(2)]))
    const wrapper = await mountPending()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(confirmAlign).toHaveBeenCalledWith([{ note_id: 1, kp_id: 101 }])
    expect(wrapper.text()).toContain('笔记2')
  })

  it('rejects with Backspace', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    await mountPending()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Backspace' }))
    await flushPromises()
    expect(rejectAlign).toHaveBeenCalledWith([{ note_id: 1, kp_id: 101 }])
  })

  it('does not act when focus is in an input', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    await mountPending()
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()
    expect(confirmAlign).not.toHaveBeenCalled()
    input.remove()
  })

  it('shows empty state when there is nothing pending', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([]))
    const wrapper = await mountPending()
    expect(wrapper.text()).toContain('暂无待确认')
  })

  it('handles 20 sequential confirmations without stale cards', async () => {
    const items = Array.from({ length: 20 }, (_, index) => item(index + 1))
    vi.mocked(listPendingAlign)
      .mockResolvedValueOnce(page(items, 20))
      .mockResolvedValueOnce(page([], 0))
    const wrapper = await mountPending()

    for (let index = 0; index < 20; index += 1) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
      await flushPromises()
    }

    expect(confirmAlign).toHaveBeenCalledTimes(20)
    expect(wrapper.text()).toContain('暂无待确认')
  })
})
