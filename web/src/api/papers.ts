/** S5-2 组卷接口：生成预览 / 换题 / 保存草稿 / 读回。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type {
  Paper,
  PaperAnswerPayload,
  PaperAnswerRow,
  PaperAnswers,
  PaperDetail,
  PaperGeneratePayload,
  PaperPreview,
  PaperReplacePayload,
  PaperReplaceResult,
  PaperSavePayload,
  PaperSubmitPayload,
  PaperSubmitResult,
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
export async function exportPaperPdf(
  id: number,
  variant: 'questions' | 'answers',
): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/papers/${id}/export.pdf`, {
    params: { variant },
    responseType: 'blob',
    timeout: 60_000,
  })
  return resp.data
}

export async function getPaperAnswers(id: number): Promise<PaperAnswers> {
  const resp = await http.get<ApiEnvelope<PaperAnswers>>(`${API_PREFIX}/papers/${id}/answers`)
  return resp.data.data
}

export async function savePaperAnswer(
  id: number,
  questionId: number,
  payload: PaperAnswerPayload,
): Promise<PaperAnswerRow> {
  const resp = await http.put<ApiEnvelope<PaperAnswerRow>>(
    `${API_PREFIX}/papers/${id}/answers/${questionId}`,
    payload,
  )
  return resp.data.data
}

export async function submitPaper(
  id: number,
  payload: PaperSubmitPayload,
): Promise<PaperSubmitResult> {
  const resp = await http.post<ApiEnvelope<PaperSubmitResult>>(
    `${API_PREFIX}/papers/${id}/submit`,
    payload,
  )
  return resp.data.data
}
