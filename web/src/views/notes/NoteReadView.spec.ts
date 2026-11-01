import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent, h, onMounted } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NoteReadView from './NoteReadView.vue'
import { getNote } from '@/api/notes'

vi.mock('@/api/notes', () => ({ getNote: vi.fn() }))

const PreviewStub = defineComponent({
  props: {
    modelValue: { type: String, default: '' },
    onHtmlChanged: { type: Function, default: undefined },
  },
  setup(props) {
    onMounted(() => props.onHtmlChanged?.(props.modelValue))
    return () => h('div', { class: 'md-preview' }, props.modelValue)
  },
})

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes/:id(\\d+)', name: 'note-read', component: NoteReadView },
      {
        path: '/notes/:id(\\d+)/edit',
        name: 'note-edit',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(NoteReadView, {
    global: {
      plugins: [router, ElementPlus],
      stubs: { MdPreview: PreviewStub },
    },
  })
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 120))
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.mocked(getNote).mockReset()
})

describe('NoteReadView', () => {
  it('renders note and highlights query snippet', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 55,
      title: '数列笔记',
      subject_id: 1,
      tags: [],
      folder: null,
      created_at: '2026-11-01T00:00:00+00:00',
      updated_at: '2026-11-01T00:00:00+00:00',
      content_md: '错位相减法很好用',
      source_file_id: null,
    })
    const { wrapper } = await mountAt('/notes/55?snippet=错位相减')
    await flushPromises()
    expect(wrapper.text()).toContain('数列笔记')
    expect(wrapper.find('mark.citation-hit').text()).toBe('错位相减')
  })

  it('shows a fallback notice when snippet cannot be located', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 55,
      title: '数列笔记',
      subject_id: null,
      tags: [],
      folder: null,
      created_at: '2026-11-01T00:00:00+00:00',
      updated_at: '2026-11-01T00:00:00+00:00',
      content_md: '正文',
      source_file_id: null,
    })
    const { wrapper } = await mountAt('/notes/55?snippet=不存在&heading=数列/公式')
    await flushPromises()
    expect(wrapper.text()).toContain('未能精确定位')
  })
})