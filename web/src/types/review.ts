/** S5-5 复习清单前端类型（docs/API.md §9）。 */
export type ReviewRefType = 'question' | 'mistake'

export interface ReviewItem {
  id: number
  kp_id: number
  kp_name: string
  subject_id: number
  ref_type: ReviewRefType
  ref_id: number
  ref_title: string | null
  ref_available: boolean
  due_at: string
  interval_days: number
  priority: number
  estimated_minutes: number
  mastery: number
  mastery_t: number
  stability: number
  attempts: number
  overdue_days: number
  low_mastery: boolean
  done_at: string | null
}

export interface ReviewToday {
  date: string
  timezone: string
  items: ReviewItem[]
  item_count: number
  total_minutes: number
  cap_minutes: number
  truncated_count: number | null
}