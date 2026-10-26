export type NoteSort = 'updated' | 'created' | 'title'

export interface NoteSummary {
  id: number
  title: string
  subject_id: number | null
  tags: string[] | null
  folder: string | null
  created_at: string
  updated_at: string
}

export interface NoteOut extends NoteSummary {
  content_md: string
  source_file_id: number | null
}

export interface NoteCreatePayload {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
}

export type NoteUpdatePayload = Partial<NoteCreatePayload>

export interface NoteListParams {
  q?: string
  subject_id?: number
  sort_by?: 'created_at' | 'updated_at' | 'title'
  order?: 'asc' | 'desc'
  page: number
  page_size: number
}