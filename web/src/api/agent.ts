import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { AgentTaskDetail, AgentTaskSummary } from '@/types/agent'

export interface CreateAgentTaskPayload {
  task_type: string
  input: Record<string, unknown>
}

export async function createAgentTask(
  payload: CreateAgentTaskPayload,
): Promise<AgentTaskSummary> {
  const resp = await http.post<ApiEnvelope<AgentTaskSummary>>(
    `${API_PREFIX}/agent/tasks`,
    payload,
  )
  return resp.data.data
}

export async function getAgentTask(id: number): Promise<AgentTaskDetail> {
  const resp = await http.get<ApiEnvelope<AgentTaskDetail>>(
    `${API_PREFIX}/agent/tasks/${id}`,
  )
  return resp.data.data
}