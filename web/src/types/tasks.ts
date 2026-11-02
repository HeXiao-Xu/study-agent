/** S2-7 任务类型 + S4-1 切题任务结果 + S4-2 错题识别任务结果。 */
import type { MistakeRecognizeResult } from '@/types/mistakes'

export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface TaskOut {
  id: number
  name: string
  status: TaskStatus
  created_at: string
}

export interface ExtractFailedItem {
  index: number
  reason: string
}

export interface ExtractTaskResult {
  file_id: number
  subject_id: number
  detected_count: number
  expected_count: number | null
  created: number
  duplicated: number
  failed_items: ExtractFailedItem[]
  degraded: boolean
  warnings: string[]
  elapsed_ms: number
}

export interface TaskDetail extends TaskOut {
  attempts: number
  payload: Record<string, unknown>
  result: ExtractTaskResult | MistakeRecognizeResult | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}