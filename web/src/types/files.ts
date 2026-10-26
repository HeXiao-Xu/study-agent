export interface FileUploadOut {
  id: number
  filename: string
  mime: string
  size: number
  sha256: string
  parse_status: string
  created_at: string
  deduped: boolean
}