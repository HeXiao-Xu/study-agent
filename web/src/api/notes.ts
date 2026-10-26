import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  NoteCreatePayload,
  NoteListParams,
  NoteOut,
  NoteSummary,
  NoteUpdatePayload,
} from '@/types/notes'

export async function listNotes(params: NoteListParams): Promise<PageData<NoteSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<NoteSummary>>>(`${API_PREFIX}/notes`, {
    params,
  })
  return resp.data.data
}

export async function getNote(id: number): Promise<NoteOut> {
  const resp = await http.get<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes/${id}`)
  return resp.data.data
}

export async function createNote(payload: NoteCreatePayload): Promise<NoteOut> {
  const resp = await http.post<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes`, payload)
  return resp.data.data
}

export async function updateNote(id: number, payload: NoteUpdatePayload): Promise<NoteOut> {
  const resp = await http.patch<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes/${id}`, payload)
  return resp.data.data
}

export async function deleteNote(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/notes/${id}`)
}