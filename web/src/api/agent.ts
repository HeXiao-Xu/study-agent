import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type {
  AgentTaskDetail,
  AgentTaskPage,
  AgentTaskSummary,
} from '@/types/agent'

export interface CreateAgentTaskPayload {
  task_type: string
  input: Record<string, unknown>
}

export interface ListAgentTasksParams {
  page?: number
  page_size?: number
  status?: string
  task_type?: string
  sort_by?: string
  order?: 'asc' | 'desc'
}

export interface AgentConfirmDecision {
  approved: boolean
  comment?: string | null
  edits?: Record<string, unknown> | null
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

export async function listAgentTasks(
  params: ListAgentTasksParams = {},
): Promise<AgentTaskPage> {
  const resp = await http.get<ApiEnvelope<AgentTaskPage>>(
    `${API_PREFIX}/agent/tasks`,
    { params },
  )
  return resp.data.data
}

export async function getAgentTask(id: number): Promise<AgentTaskDetail> {
  const resp = await http.get<ApiEnvelope<AgentTaskDetail>>(
    `${API_PREFIX}/agent/tasks/${id}`,
  )
  return resp.data.data
}

export async function retryAgentTask(id: number): Promise<AgentTaskSummary> {
  const resp = await http.post<ApiEnvelope<AgentTaskSummary>>(
    `${API_PREFIX}/agent/tasks/${id}/retry`,
  )
  return resp.data.data
}

export async function confirmAgentTask(
  id: number,
  decision: AgentConfirmDecision,
): Promise<AgentTaskSummary> {
  const resp = await http.post<ApiEnvelope<AgentTaskSummary>>(
    `${API_PREFIX}/agent/tasks/${id}/confirm`,
    decision,
  )
  return resp.data.data
}