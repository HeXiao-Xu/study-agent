/** S5-6 学习报告与周报前端类型（docs/API.md §9）。 */
export type ReportRange = '7d' | '30d' | '90d'

export interface ReportRangeInfo {
  key: ReportRange
  from: string
  to: string
}

export interface ReportModule {
  kp_id: number
  kp_name: string
  exam_weight: number | null
  kp_count: number
  assessed_count: number
  mastery: number | null
}

export interface ReportHeatmapNode {
  kp_id: number
  kp_name: string
  parent_id: number | null
  level: number
  exam_weight: number | null
  mastery: number | null
  mastery_t: number | null
  color_value: number | null
  assessed: boolean
}

export interface ReportSubject {
  subject_id: number
  subject_name: string
  modules: ReportModule[]
  heatmap: ReportHeatmapNode[]
}

export interface ReportTrendPoint {
  date: string
  new_notes: number
  reviews_done: number
  new_mistakes: number
  mastered_mistakes: number
  mistakes_net: number
}

export interface ReportOverview {
  range: ReportRangeInfo
  subjects: ReportSubject[]
  trend: ReportTrendPoint[]
}

export interface WeeklyPeriod {
  from: string
  to: string
  days: number
}

export interface WeeklyTotals {
  new_notes: number
  reviews_done: number
  new_mistakes: number
  mastered_mistakes: number
  mistakes_net: number
}

export interface WeeklyWeakModule {
  subject_id: number
  kp_id: number
  kp_name: string
  mastery: number
}

export interface WeeklyWeakKp {
  subject_id: number
  kp_id: number
  kp_name: string
  level: number
  mastery: number
}

export interface WeeklyMastery {
  assessed_kp_count: number
  avg_mastery: number | null
  weak_modules: WeeklyWeakModule[]
  weak_kps: WeeklyWeakKp[]
}

export interface WeeklyStats {
  totals: WeeklyTotals
  active_days: number
  mastery: WeeklyMastery
  trend: ReportTrendPoint[]
}

export interface WeeklyValidation {
  ok: boolean
  attempts: number
  checked_numbers: string[]
  invalid_numbers: string[]
}

export interface WeeklyReport {
  period: WeeklyPeriod
  generated_by: 'llm' | 'empty'
  report_md: string
  stats: WeeklyStats
  validation: WeeklyValidation
}