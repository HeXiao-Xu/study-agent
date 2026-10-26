import { computed, reactive, ref, type Ref } from 'vue'

import { getImageBlob } from '@/api/files'
import { createNote, getNote, updateNote } from '@/api/notes'
import type { NoteUpdatePayload } from '@/types/notes'
import {
  clearDraft,
  isDraftStale,
  readDraft,
  writeDraft,
  type DraftState,
} from '@/utils/noteDraft'
import { extractImageIds, replaceImageTokens, replaceImageUrls } from '@/utils/noteImages'

export interface EditorForm {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
}

export function emptyForm(): EditorForm {
  return { title: '', content_md: '', subject_id: null, tags: [] }
}

export function validateForm(form: EditorForm): string | null {
  const title = form.title.trim()
  const content = form.content_md.trim()
  if (!title) return '标题不能为空'
  if (title.length > 200) return '标题不能超过 200 字'
  if (!content) return '正文不能为空'
  if (content.length > 200_000) return '正文不能超过 200000 字'
  if (form.tags.length > 20) return '最多 20 个标签'
  if (form.tags.some((tag) => tag.length > 30)) return '单个标签不能超过 30 字'
  return null
}

function rawSnapshot(form: EditorForm): string {
  return JSON.stringify({
    title: form.title.trim(),
    content_md: form.content_md,
    subject_id: form.subject_id,
    tags: form.tags,
  })
}

export function useNoteEditor(
  noteId: Ref<number | null>,
  options: { onCreated?: (id: number) => void } = {},
) {
  const form = reactive<EditorForm>(emptyForm())
  const saved = ref<EditorForm>(emptyForm())
  const loading = ref(true)
  const saving = ref(false)
  const error = ref('')
  const pendingDraft = ref<DraftState | null>(null)
  const imageFailures = ref(0)
  const updatedAt = ref<string | null>(null)
  const tokenByUrl = new Map<string, string>()
  const objectUrls: string[] = []

  function revokeImages(): void {
    for (const url of objectUrls) URL.revokeObjectURL(url)
    objectUrls.length = 0
    tokenByUrl.clear()
  }

  async function hydrateImages(markdown: string): Promise<string> {
    const ids = extractImageIds(markdown)
    const urlById = new Map<number, string>()
    await Promise.all(
      ids.map(async (id) => {
        try {
          const blob = await getImageBlob(id)
          const url = URL.createObjectURL(blob)
          objectUrls.push(url)
          urlById.set(id, url)
          tokenByUrl.set(url, `note-file://${id}`)
        } catch {
          imageFailures.value += 1
        }
      }),
    )
    return replaceImageTokens(markdown, urlById)
  }

  function currentRaw(): EditorForm {
    return {
      title: form.title.trim(),
      content_md: replaceImageUrls(form.content_md, tokenByUrl).trim(),
      subject_id: form.subject_id,
      tags: [...form.tags],
    }
  }

  const dirty = computed(() => rawSnapshot(currentRaw()) !== rawSnapshot(saved.value))

  async function load(): Promise<void> {
    revokeImages()
    loading.value = true
    error.value = ''
    imageFailures.value = 0
    pendingDraft.value = null
    try {
      if (noteId.value === null) {
        Object.assign(form, emptyForm())
        saved.value = emptyForm()
        updatedAt.value = null
        const draft = readDraft(null)
        if (draft) pendingDraft.value = draft
        return
      }
      const note = await getNote(noteId.value)
      Object.assign(form, {
        title: note.title,
        content_md: note.content_md,
        subject_id: note.subject_id,
        tags: [...(note.tags ?? [])],
      })
      saved.value = {
        title: note.title,
        content_md: note.content_md,
        subject_id: note.subject_id,
        tags: [...(note.tags ?? [])],
      }
      updatedAt.value = note.updated_at
      const draft = readDraft(noteId.value)
      if (draft) {
        if (isDraftStale(draft, note.updated_at)) clearDraft(noteId.value)
        else pendingDraft.value = draft
      }
      form.content_md = await hydrateImages(note.content_md)
    } catch {
      error.value = '笔记加载失败，请返回列表重试'
    } finally {
      loading.value = false
    }
  }

  function registerImage(id: number, url: string): void {
    tokenByUrl.set(url, `note-file://${id}`)
  }

  async function applyDraft(): Promise<void> {
    const draft = pendingDraft.value
    if (!draft) return
    revokeImages()
    form.title = draft.title
    form.subject_id = draft.subject_id
    form.tags = [...draft.tags]
    form.content_md = await hydrateImages(draft.content_md)
    pendingDraft.value = null
  }

  function discardDraft(): void {
    clearDraft(noteId.value)
    pendingDraft.value = null
  }

  function writeCurrentDraft(): void {
    const raw = currentRaw()
    const empty =
      !raw.title && !raw.content_md && raw.subject_id === null && raw.tags.length === 0
    if (empty) {
      clearDraft(noteId.value)
      return
    }
    writeDraft(noteId.value, {
      ...raw,
      draftSavedAt: new Date().toISOString(),
      baseUpdatedAt: updatedAt.value,
    })
  }

  async function save(): Promise<boolean> {
    const raw = currentRaw()
    const validation = validateForm(raw)
    if (validation) {
      error.value = validation
      return false
    }
    if (!dirty.value) return true
    saving.value = true
    error.value = ''
    let createdId: number | null = null
    try {
      if (noteId.value === null) {
        const created = await createNote(raw)
        clearDraft(null)
        clearDraft(created.id)
        saved.value = {
          title: created.title,
          content_md: created.content_md,
          subject_id: created.subject_id,
          tags: [...(created.tags ?? [])],
        }
        updatedAt.value = created.updated_at
        form.title = created.title
        noteId.value = created.id
        createdId = created.id
        return true
      }
      const patch: NoteUpdatePayload = {}
      if (raw.title !== saved.value.title) patch.title = raw.title
      if (raw.content_md !== saved.value.content_md) patch.content_md = raw.content_md
      if (raw.subject_id !== saved.value.subject_id) patch.subject_id = raw.subject_id
      if (JSON.stringify(raw.tags) !== JSON.stringify(saved.value.tags)) patch.tags = raw.tags
      if (Object.keys(patch).length === 0) return true
      const updated = await updateNote(noteId.value, patch)
      saved.value = {
        title: updated.title,
        content_md: updated.content_md,
        subject_id: updated.subject_id,
        tags: [...(updated.tags ?? [])],
      }
      updatedAt.value = updated.updated_at
      form.title = updated.title
      clearDraft(noteId.value)
      return true
    } catch {
      error.value = '保存失败，请稍后重试'
      return false
    } finally {
      saving.value = false
      if (createdId !== null) options.onCreated?.(createdId)
    }
  }

  return {
    form,
    loading,
    saving,
    error,
    pendingDraft,
    imageFailures,
    dirty,
    load,
    save,
    applyDraft,
    discardDraft,
    writeCurrentDraft,
    registerImage,
    revokeImages,
  }
}