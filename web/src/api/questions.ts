import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  QuestionCreatePayload,
  QuestionDetail,
  QuestionListParams,
  QuestionSummary,
  QuestionUpdatePayload,
} from '@/types/questions'
import type { TaskOut } from '@/types/tasks'

export async function importQuestions(
  file: File,
  subjectId: number,
  origin = 'upload',
): Promise<TaskOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<TaskOut>>(`${API_PREFIX}/questions/import`, form, {
    params: { subject_id: subjectId, origin },
    timeout: 120_000,
  })
  return resp.data.data
}

export async function listQuestions(
  params: QuestionListParams,
): Promise<PageData<QuestionSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<QuestionSummary>>>(`${API_PREFIX}/questions`, {
    params,
  })
  return resp.data.data
}

export async function getQuestion(id: number): Promise<QuestionDetail> {
  const resp = await http.get<ApiEnvelope<QuestionDetail>>(`${API_PREFIX}/questions/${id}`)
  return resp.data.data
}

export async function createQuestion(payload: QuestionCreatePayload): Promise<QuestionDetail> {
  const resp = await http.post<ApiEnvelope<QuestionDetail>>(`${API_PREFIX}/questions`, payload)
  return resp.data.data
}

export async function updateQuestion(
  id: number,
  payload: QuestionUpdatePayload,
): Promise<QuestionDetail> {
  const resp = await http.patch<ApiEnvelope<QuestionDetail>>(
    `${API_PREFIX}/questions/${id}`,
    payload,
  )
  return resp.data.data
}

export async function splitQuestion(id: number, splitAt: string): Promise<QuestionDetail[]> {
  const resp = await http.post<ApiEnvelope<QuestionDetail[]>>(
    `${API_PREFIX}/questions/${id}/split`,
    { split_at: splitAt },
  )
  return resp.data.data
}

export async function mergeQuestions(ids: number[]): Promise<QuestionDetail> {
  const resp = await http.post<ApiEnvelope<QuestionDetail>>(`${API_PREFIX}/questions/merge`, {
    ids,
  })
  return resp.data.data
}

export async function deleteQuestion(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/questions/${id}`)
}