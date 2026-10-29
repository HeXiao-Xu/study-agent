import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  AlignBatchResult,
  AlignPair,
  KpCreatePayload,
  KpNode,
  KpOrderPayload,
  KpTree,
  KpUpdatePayload,
  PendingAlign,
  SubjectOut,
} from '@/types/kp'

export async function listSubjects(): Promise<SubjectOut[]> {
  const resp = await http.get<ApiEnvelope<SubjectOut[]>>(`${API_PREFIX}/kp/subjects`)
  return resp.data.data
}

export async function getKpTree(subject: string): Promise<KpTree> {
  const resp = await http.get<ApiEnvelope<KpTree>>(`${API_PREFIX}/kp/tree`, {
    params: { subject },
  })
  return resp.data.data
}

export async function createKp(payload: KpCreatePayload): Promise<KpNode> {
  const resp = await http.post<ApiEnvelope<KpNode>>(`${API_PREFIX}/kp`, payload)
  return resp.data.data
}

export async function updateKp(id: number, payload: KpUpdatePayload): Promise<KpNode> {
  const resp = await http.patch<ApiEnvelope<KpNode>>(`${API_PREFIX}/kp/${id}`, payload)
  return resp.data.data
}

export async function deleteKp(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/kp/${id}`)
}

export async function reorderKp(payload: KpOrderPayload): Promise<void> {
  await http.put(`${API_PREFIX}/kp/order`, payload)
}

export async function listPendingAlign(
  params: { page?: number; page_size?: number } = {},
): Promise<PageData<PendingAlign>> {
  const resp = await http.get<ApiEnvelope<PageData<PendingAlign>>>(
    `${API_PREFIX}/kp/align/pending`,
    { params: { page: 1, page_size: 20, ...params } },
  )
  return resp.data.data
}

export async function confirmAlign(items: AlignPair[]): Promise<AlignBatchResult> {
  const resp = await http.post<ApiEnvelope<AlignBatchResult>>(
    `${API_PREFIX}/kp/align/confirm`,
    { items },
  )
  return resp.data.data
}

export async function rejectAlign(items: AlignPair[]): Promise<AlignBatchResult> {
  const resp = await http.post<ApiEnvelope<AlignBatchResult>>(
    `${API_PREFIX}/kp/align/reject`,
    { items },
  )
  return resp.data.data
}
