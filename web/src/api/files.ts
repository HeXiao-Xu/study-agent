import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { FileUploadOut } from '@/types/files'

export async function uploadImage(file: File): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'false' },
    timeout: 60_000,
  })
  return resp.data.data
}

export async function getImageBlob(id: number): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/files/${id}/image`, {
    responseType: 'blob',
    timeout: 30_000,
  })
  return resp.data
}