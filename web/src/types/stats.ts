/** S4-8 统计看板出参（docs/API.md §4.7）。 */
export type StatsRange = '7d' | '30d' | '90d'

export interface StatsRangeInfo {
  key: StatsRange
  from: string
  to: string
}

export interface StatsSummary {
  total: number
  pending: number
  corrected: number
  mastered: number
  analyzed: number
  with_kp: number
  mastery_rows: number
}

export interface StatsStatusCount {
  status: string
  count: number
}

export interface StatsCauseCount {
  cause_type: string
  count: number
}

export interface StatsTopKp {
  kp_id: number
  kp_name: string
  count: number
  mastery: number | null
}

export interface StatsTrendPoint {
  date: string
  new_mistakes: number
  mastered: number
}

export interface StatsOverview {
  range: StatsRangeInfo
  summary: StatsSummary
  by_status: StatsStatusCount[]
  by_cause: StatsCauseCount[]
  top_kps: StatsTopKp[]
  trend: StatsTrendPoint[]
}