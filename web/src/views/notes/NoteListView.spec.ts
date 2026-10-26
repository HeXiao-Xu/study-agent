import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import NoteListView from './NoteListView.vue'

vi.mock('@/api/notes', () => ({
  listNotes: vi.fn(),
  deleteNote: vi.fn(),
}))
vi.mock('@/api/kp', () => ({
  listSubjects: vi.fn().mockResolvedValue([{ id: 7, name: '高中数学', code: 'math', stage: 'high' }]),
}))

import { deleteNote, listNotes } from '@/api/notes'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes', name: 'notes', component: NoteListView },
      { path: '/notes/new', name: 'note-new', component: { template: '<div />' } },
      { path: '/notes/:id/edit', name: 'note-edit', component: { template: '<div />' } },
    ],
  })
}

async function mountPage() {
  const router = makeRouter()
  await router.push('/notes')
  await router.isReady()
  const wrapper = mount(NoteListView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

describe('NoteListView', () => {
  beforeEach(() => {
    vi.mocked(listNotes).mockReset()
    vi.mocked(deleteNote).mockReset()
  })

  it('renders rows', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        {
          id: 1,
          title: '函数单调性',
          subject_id: 7,
          tags: ['函数'],
          folder: null,
          created_at: '2026-10-27T01:00:00+00:00',
          updated_at: '2026-10-27T02:00:00+00:00',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('函数单调性')
    expect(wrapper.text()).toContain('高中数学')
  })

  it('shows the empty state when there are no notes', async () => {
    vi.mocked(listNotes).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('还没有笔记')
  })

  it('shows filtered empty state', async () => {
    vi.mocked(listNotes).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const { wrapper } = await mountPage()
    await wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', '不存在')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()
    expect(wrapper.text()).toContain('没有匹配的笔记')
  })

  it('deletes after confirmation', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        {
          id: 1,
          title: '函数单调性',
          subject_id: 7,
          tags: [],
          folder: null,
          created_at: '2026-10-27T01:00:00+00:00',
          updated_at: '2026-10-27T02:00:00+00:00',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })
    vi.mocked(deleteNote).mockResolvedValue()
    const confirm = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as never)
    const { wrapper } = await mountPage()
    const danger = wrapper
      .findAll('.el-table__row button')
      .find((button) => button.text().includes('删除'))
    expect(danger).toBeTruthy()
    await danger!.trigger('click')
    await flushPromises()
    expect(deleteNote).toHaveBeenCalledWith(1)
    confirm.mockRestore()
  })

  it('navigates to the editor on row click', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        {
          id: 1,
          title: '函数单调性',
          subject_id: 7,
          tags: [],
          folder: null,
          created_at: '2026-10-27T01:00:00+00:00',
          updated_at: '2026-10-27T02:00:00+00:00',
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    })
    const { wrapper, router } = await mountPage()
    wrapper.findComponent({ name: 'ElTable' }).vm.$emit('row-click', { id: 1 })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('note-edit')
    expect(router.currentRoute.value.params.id).toBe('1')
  })
})