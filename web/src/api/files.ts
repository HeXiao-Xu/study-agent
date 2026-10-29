import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  ChunkPreview,
  FileListParams,
  FileStatus,
  FileSummary,
  FileUploadOut,
} from '@/types/files'

export async function uploadImage(file: File): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'false' },
    timeout: 60_000,
  })
  return resp.data.data
}

export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'true' },
    timeout: 300_000,
    onUploadProgress: (event) => {
      if (event.total && event.total > 0) {
        onProgress?.(Math.round((event.loaded * 100) / event.total))
      }
    },
  })
  return resp.data.data
}

export async function listFiles(params: FileListParams): Promise<PageData<FileSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<FileSummary>>>(`${API_PREFIX}/files`, {
    params,
  })
  return resp.data.data
}

export async function getFileStatus(id: number): Promise<FileStatus> {
  const resp = await http.get<ApiEnvelope<FileStatus>>(
    `${API_PREFIX}/files/${id}/parse-status`,
  )
  return resp.data.data
}

export async function listFileChunks(id: number, limit = 3): Promise<ChunkPreview[]> {
  const resp = await http.get<ApiEnvelope<ChunkPreview[]>>(
    `${API_PREFIX}/files/${id}/chunks`,
    { params: { limit } },
  )
  return resp.data.data
}

export async function getImageBlob(id: number): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/files/${id}/image`, {
    responseType: 'blob',
    timeout: 30_000,
  })
  return resp.data
}