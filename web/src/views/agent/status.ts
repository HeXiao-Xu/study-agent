/** S6-5 Agent 状态 → 中文标签 / Element Plus tag 类型。 */
export type AgentStatusTag = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const LABELS: Record<string, string> = {
  pending: '排队中',
  running: '生成中',
  waiting_confirm: '等待确认',
  succeeded: '已完成',
  failed: '失败',
}

export function statusLabel(status?: string | null): string {
  if (!status) return '未知'
  return LABELS[status] ?? status
}

export function statusType(status?: string | null): AgentStatusTag {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'waiting_confirm') return 'warning'
  if (status === 'running') return 'primary'
  return 'info'
}