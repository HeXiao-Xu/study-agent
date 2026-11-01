import type { QaScope } from '@/types/qa'

export interface ScopeForm {
  subjectId: number | null
  folder: string
  dateRange: [string, string] | null
}

export function toScopePayload(form: ScopeForm): QaScope | null {
  const folder = form.folder.trim()
  const start = form.dateRange?.[0] ?? null
  const end = form.dateRange?.[1] ?? null
  if (start && end && end < start) {
    throw new Error('结束日期不能早于开始日期')
  }
  const scope: QaScope = {}
  if (form.subjectId !== null) scope.subject_id = form.subjectId
  if (folder) scope.folder = folder
  if (start) scope.start_date = start
  if (end) scope.end_date = end
  return Object.keys(scope).length ? scope : null
}