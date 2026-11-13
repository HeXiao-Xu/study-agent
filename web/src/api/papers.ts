/** S5-2 组卷接口：生成预览 / 换题 / 保存草稿 / 读回。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type {
  Paper,
  PaperDetail,
  PaperGeneratePayload,
  PaperPreview,
  PaperReplacePayload,
  PaperReplaceResult,
  PaperSavePayload,
} from '@/types/papers'

export async function generatePaper(payload: PaperGeneratePayload): Promise<PaperPreview> {
  const resp = await http.post<ApiEnvelope<PaperPreview>>(`${API_PREFIX}/papers/generate`, payload)
  return resp.data.data
}

export async function replacePaperItem(
  payload: PaperReplacePayload,
): Promise<PaperReplaceResult> {
  const resp = await http.post<ApiEnvelope<PaperReplaceResult>>(
    `${API_PREFIX}/papers/replace-item`,
    payload,
  )
  return resp.data.data
}

export async function savePaper(payload: PaperSavePayload): Promise<Paper> {
  const resp = await http.post<ApiEnvelope<Paper>>(`${API_PREFIX}/papers`, payload)
  return resp.data.data
}

export async function getPaper(id: number): Promise<PaperDetail> {
  const resp = await http.get<ApiEnvelope<PaperDetail>>(`${API_PREFIX}/papers/${id}`)
  return resp.data.data
}