import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { TaskDetail } from '@/types/tasks'

export async function getTask(id: number): Promise<TaskDetail> {
  const resp = await http.get<ApiEnvelope<TaskDetail>>(`${API_PREFIX}/tasks/${id}`)
  return resp.data.data
}