/** S6-3/S6-5 Agent 任务与周导图结果类型（与 API.md §10 保持一致）。 */
export interface AgentStep {
  step_no: number
  thought: string | null
  tool_name: string | null
  tool_input: Record<string, unknown> | null
  tool_output: Record<string, unknown> | null
  latency_ms: number | null
  status: string
}

export interface AgentTaskSummary {
  id: number
  task_type: string
  status: string
  steps_count: number | null
  token_cost: number | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface WeeklyMindmapCitation {
  note_id: number
  note_title: string
}

export interface WeeklyMindmapResult {
  task_type: 'weekly_mindmap'
  days: number
  note_count: number
  kp_count: number
  summary_md: string
  mermaid: string
  fallback_text: string
  citations: WeeklyMindmapCitation[]
  degraded: boolean
  cluster_prompt_version: string
}

export interface DemoAgentResult {
  summary: string
  artifacts: Record<string, unknown>
  citations: unknown[]
}

export type AgentTaskResult =
  | WeeklyMindmapResult
  | DemoAgentResult
  | Record<string, unknown>
  | null

export interface AgentTaskDetail extends AgentTaskSummary {
  input: Record<string, unknown>
  result: AgentTaskResult
  steps: AgentStep[]
}

export interface AgentTaskPage {
  items: AgentTaskSummary[]
  total: number
  page: number
  page_size: number
}

export function asWeeklyMindmapResult(
  result: AgentTaskResult,
): WeeklyMindmapResult | null {
  if (!result || typeof result !== 'object') return null
  const candidate = result as { task_type?: unknown }
  return candidate.task_type === 'weekly_mindmap'
    ? (result as WeeklyMindmapResult)
    : null
}