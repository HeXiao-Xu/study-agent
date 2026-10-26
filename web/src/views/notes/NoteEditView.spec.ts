import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import NoteEditView from './NoteEditView.vue'

vi.mock('@/api/notes', () => ({
  getNote: vi.fn(),
  createNote: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/files', () => ({
  getImageBlob: vi.fn(),
  uploadImage: vi.fn(),
}))

import { createNote, getNote, updateNote } from '@/api/notes'

const EditorStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue', 'save', 'upload-error', 'image-uploaded'],
  setup(props, { emit }) {
    return () =>
      h('textarea', {
        'data-testid': 'note-body',
        value: props.modelValue,
        onInput: (event: Event) =>
          emit('update:modelValue', (event.target as HTMLTextAreaElement).value),
      })
  },
})

function note(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    title: '函数单调性',
    content_md: '# 正文',
    subject_id: 7,
    tags: ['函数'],
    folder: null,
    source_file_id: null,
    created_at: '2026-10-27T01:00:00+00:00',
    updated_at: '2026-10-27T02:00:00+00:00',
    ...overrides,
  }
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes', name: 'notes', component: { template: '<div />' } },
      { path: '/notes/new', name: 'note-new', component: NoteEditView },
      { path: '/notes/:id/edit', name: 'note-edit', component: NoteEditView },
    ],
  })
}

async function mountAt(path: string) {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const Root = defineComponent({ template: '<router-view />' })
  const wrapper = mount(Root, {
    global: {
      plugins: [router, ElementPlus],
      stubs: { MarkdownEditor: EditorStub },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('NoteEditView', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.mocked(getNote).mockReset()
    vi.mocked(createNote).mockReset()
    vi.mocked(updateNote).mockReset()
  })

  it('loads an existing note', async () => {
    vi.mocked(getNote).mockResolvedValue(note())
    const { wrapper } = await mountAt('/notes/5/edit')
    expect((wrapper.find('[data-testid="note-title"]').element as HTMLInputElement).value).toBe(
      '函数单调性',
    )
    expect(wrapper.text()).toContain('已保存')
  })

  it('creates a note from the new page', async () => {
    vi.mocked(createNote).mockResolvedValue(
      note({ id: 9, title: '新笔记', content_md: '正文', subject_id: null, tags: [] }),
    )
    const { wrapper, router } = await mountAt('/notes/new')
    await wrapper.find('[data-testid="note-title"]').setValue('新笔记')
    await wrapper.find('[data-testid="note-body"]').setValue('正文')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(createNote).toHaveBeenCalledWith({
      title: '新笔记',
      content_md: '正文',
      subject_id: null,
      tags: [],
    })
    expect(router.currentRoute.value.name).toBe('note-edit')
    expect(router.currentRoute.value.params.id).toBe('9')
  })

  it('patches only the changed title', async () => {
    vi.mocked(getNote).mockResolvedValue(note())
    vi.mocked(updateNote).mockResolvedValue(note({ title: '新标题' }))
    const { wrapper } = await mountAt('/notes/5/edit')
    await wrapper.find('[data-testid="note-title"]').setValue('新标题')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(updateNote).toHaveBeenCalledWith(5, { title: '新标题' })
  })

  it('does not send an invalid new note', async () => {
    const { wrapper } = await mountAt('/notes/new')
    await wrapper.find('[data-testid="note-body"]').setValue('只有正文')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(createNote).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('标题不能为空')
  })

  it('restores a pending draft when confirmed', async () => {
    localStorage.setItem(
      'study-agent:note-draft:v1:new',
      JSON.stringify({
        title: '草稿标题',
        content_md: '草稿正文',
        subject_id: null,
        tags: [],
        draftSavedAt: '2026-10-27T02:00:00.000Z',
        baseUpdatedAt: null,
      }),
    )
    const confirm = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as never)
    const { wrapper } = await mountAt('/notes/new')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect((wrapper.find('[data-testid="note-title"]').element as HTMLInputElement).value).toBe(
      '草稿标题',
    )
    confirm.mockRestore()
  })
})