import type { LocationQuery } from 'vue-router'

import type { NoteListParams, NoteSort } from '@/types/notes'

export interface ListQueryState {
  q: string
  subjectId: number | null
  sort: NoteSort
  page: number
  pageSize: number
}

const SORTS: NoteSort[] = ['updated', 'created', 'title']
const PAGE_SIZES = [10, 20, 50]

export function normalizeListQuery(raw: LocationQuery): ListQueryState {
  const q = typeof raw.q === 'string' ? raw.q.trim().slice(0, 100) : ''
  const subjectRaw = typeof raw.subject_id === 'string' ? Number(raw.subject_id) : NaN
  const subjectId = Number.isInteger(subjectRaw) && subjectRaw > 0 ? subjectRaw : null
  const sortRaw = typeof raw.sort === 'string' ? raw.sort : ''
  const sort = SORTS.includes(sortRaw as NoteSort) ? (sortRaw as NoteSort) : 'updated'
  const pageRaw = typeof raw.page === 'string' ? Number(raw.page) : 1
  const page = Number.isInteger(pageRaw) && pageRaw > 0 ? pageRaw : 1
  const sizeRaw = typeof raw.page_size === 'string' ? Number(raw.page_size) : 10
  const pageSize = PAGE_SIZES.includes(sizeRaw) ? sizeRaw : 10
  return { q, subjectId, sort, page, pageSize }
}

export function toNoteListParams(state: ListQueryState): NoteListParams {
  const params: NoteListParams = {
    page: state.page,
    page_size: state.pageSize,
  }
  if (state.q) params.q = state.q
  if (state.subjectId !== null) params.subject_id = state.subjectId
  if (state.sort === 'updated') {
    params.sort_by = 'updated_at'
    params.order = 'desc'
  } else if (state.sort === 'created') {
    params.sort_by = 'created_at'
    params.order = 'desc'
  } else {
    params.sort_by = 'title'
    params.order = 'asc'
  }
  return params
}

export function toListQuery(state: ListQueryState): Record<string, string> {
  const query: Record<string, string> = {}
  if (state.q) query.q = state.q
  if (state.subjectId !== null) query.subject_id = String(state.subjectId)
  if (state.sort !== 'updated') query.sort = state.sort
  if (state.page !== 1) query.page = String(state.page)
  if (state.pageSize !== 10) query.page_size = String(state.pageSize)
  return query
}