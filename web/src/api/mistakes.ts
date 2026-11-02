/**
 * S4-2 错题 API：8 个接口（docs/API.md §5.6）。
 * 对外参数用 camelCase，发请求前映射回后端 snake_case；Envelope 由 http.ts 统一拆。
 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  MistakeCreatePayload,
  MistakeCreateResult,
  MistakeDetail,
  MistakeListParams,
  MistakeStats,
  MistakeStatsParams,
  MistakeSummary,
  MistakeUpdatePayload,
} from '@/types/mistakes'
import type { TaskOut } from '@/types/tasks'

/** 请求体只剔除 undefined：PATCH 里显式 null 表示清空列，必须保留。 */
function compactBody(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined))
}

/**
 * 查询参数额外剔除 null 与空串：后端 `datetime | None` / `int | None` 收到 `''`
 * 会直接 ValidationError（422），而筛选控件清空时给的就是空串。
 */
function compactQuery(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== '',
    ),
  )
}

export async function listMistakes(
  params: MistakeListParams,
): Promise<PageData<MistakeSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<MistakeSummary>>>(`${API_PREFIX}/mistakes`, {
    params: compactQuery({
      status: params.status,
      cause_type: params.causeType,
      kp_id: params.kpId,
      created_from: params.createdFrom,
      created_to: params.createdTo,
      page: params.page,
      page_size: params.pageSize,
      sort_by: params.sortBy,
      order: params.order,
    }),
  })
  return resp.data.data
}

export async function getMistakeStats(
  params: MistakeStatsParams = {},
): Promise<MistakeStats> {
  const resp = await http.get<ApiEnvelope<MistakeStats>>(`${API_PREFIX}/mistakes/stats`, {
    params: compactQuery({
      created_from: params.createdFrom,
      created_to: params.createdTo,
    }),
  })
  return resp.data.data
}

export async function createMistake(
  payload: MistakeCreatePayload,
): Promise<MistakeCreateResult> {
  const resp = await http.post<ApiEnvelope<MistakeCreateResult>>(
    `${API_PREFIX}/mistakes`,
    compactBody({
      question_id: payload.questionId,
      my_answer_md: payload.myAnswerMd,
      correct_answer_md: payload.correctAnswerMd,
    }),
  )
  return resp.data.data
}

/**
 * 拍照录入（R1-c）：`my_answer_md` 是可选 Form 字段，空值不 append，
 * 避免把空串当成学生作答落库；`subject_id` 仍走 query。
 */
export async function createMistakeFromPhoto(
  file: File,
  subjectId: number,
  myAnswerMd?: string | null,
): Promise<TaskOut> {
  const form = new FormData()
  form.append('file', file)
  if (myAnswerMd !== undefined && myAnswerMd !== null && myAnswerMd !== '') {
    form.append('my_answer_md', myAnswerMd)
  }
  const resp = await http.post<ApiEnvelope<TaskOut>>(`${API_PREFIX}/mistakes/photo`, form, {
    params: { subject_id: subjectId },
    timeout: 120_000,
  })
  return resp.data.data
}

export async function getMistake(id: number): Promise<MistakeDetail> {
  const resp = await http.get<ApiEnvelope<MistakeDetail>>(`${API_PREFIX}/mistakes/${id}`)
  return resp.data.data
}

export async function updateMistake(
  id: number,
  payload: MistakeUpdatePayload,
): Promise<MistakeDetail> {
  const resp = await http.patch<ApiEnvelope<MistakeDetail>>(
    `${API_PREFIX}/mistakes/${id}`,
    compactBody({
      my_answer_md: payload.myAnswerMd,
      correct_answer_md: payload.correctAnswerMd,
      status: payload.status,
    }),
  )
  return resp.data.data
}

export async function reviewMistake(id: number, correct: boolean): Promise<MistakeDetail> {
  const resp = await http.post<ApiEnvelope<MistakeDetail>>(
    `${API_PREFIX}/mistakes/${id}/review`,
    { correct },
  )
  return resp.data.data
}

export async function deleteMistake(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/mistakes/${id}`)
}
