export type ParseStatus = 'pending' | 'parsing' | 'done' | 'failed'

export interface FileUploadOut {
  id: number
  filename: string
  mime: string
  size: number
  sha256: string
  parse_status: ParseStatus
  created_at: string
  deduped: boolean
}

export interface FileSummary {
  id: number
  filename: string
  mime: string
  size: number
  parse_status: ParseStatus
  parse_progress: number
  error_msg: string | null
  chunk_count: number
  created_at: string
  parse_finished_at: string | null
}

export interface FileStatus {
  id: number
  filename: string
  parse_status: ParseStatus
  parse_progress: number
  error_msg: string | null
  chunk_count: number
}

export interface ChunkPreview {
  chunk_index: number
  content: string
  token_count: number
}

export interface FileListParams {
  page: number
  page_size: number
}