const PREFIX = 'study-agent:note-draft:v1'

export interface DraftState {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
  draftSavedAt: string
  baseUpdatedAt: string | null
}

export function draftKey(noteId: number | null): string {
  return `${PREFIX}:${noteId ?? 'new'}`
}

export function writeDraft(noteId: number | null, state: DraftState): void {
  try {
    localStorage.setItem(draftKey(noteId), JSON.stringify(state))
  } catch {
    // 隐私模式/配额满：草稿降级为仅内存，不阻断编辑
  }
}

export function readDraft(noteId: number | null): DraftState | null {
  try {
    const raw = localStorage.getItem(draftKey(noteId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<DraftState>
    if (
      typeof value.title !== 'string' ||
      typeof value.content_md !== 'string' ||
      (value.subject_id !== null && typeof value.subject_id !== 'number') ||
      !Array.isArray(value.tags) ||
      value.tags.some((tag) => typeof tag !== 'string') ||
      typeof value.draftSavedAt !== 'string' ||
      (value.baseUpdatedAt !== null && typeof value.baseUpdatedAt !== 'string')
    ) {
      throw new Error('invalid draft')
    }
    return value as DraftState
  } catch {
    try {
      localStorage.removeItem(draftKey(noteId))
    } catch {
      // ignore
    }
    return null
  }
}

export function clearDraft(noteId: number | null): void {
  try {
    localStorage.removeItem(draftKey(noteId))
  } catch {
    // ignore
  }
}

export function isDraftStale(draft: DraftState, serverUpdatedAt: string | null): boolean {
  if (draft.baseUpdatedAt === null) return false
  return draft.baseUpdatedAt !== serverUpdatedAt
}