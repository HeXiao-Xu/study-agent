import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { SubjectOut } from '@/types/kp'

export async function listSubjects(): Promise<SubjectOut[]> {
  const resp = await http.get<ApiEnvelope<SubjectOut[]>>(`${API_PREFIX}/kp/subjects`)
  return resp.data.data
}