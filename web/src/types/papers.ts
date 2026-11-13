/** S5-2 组卷：接口契约镜像（API.md §8）。 */
export type PaperQuestionType = '单选' | '多选' | '填空' | '解答'
export type PaperStatus = '草稿' | '已生成' | '已提交'

export interface ScoreParts {
  difficulty_match: number
  mastery_match: number
  novelty: number
  quality: number
  total: number
}

export interface OptionOut {
  key: string
  text: string
}

/** 题目与知识点：groups 里的 kp_ids 顺序不保证。 */
export interface PaperItem {
  question_id: number
  qtype: string
  difficulty: number
  score: number
  kp_ids: number[]
  parts: ScoreParts | null
  subject_id: number
  stem_md: string
  options: OptionOut[]
  answer_md: string | null
  analysis_md: string | null
  verified: boolean
  origin: string
}

export interface PaperConstraintOut {
  kp_ids: number[]
  total_questions: number
  qtype_ratio: Record<string, number>
  difficulty_dist: Record<string, number>
  total_score: number
  duration_min: number | null
  exclude_recent_days: number
  seed: number
  kp_weights: Record<string, number>
  score_by_qtype: Record<string, number>
}

export interface PaperViolation {
  code: string
  message: string
  detail: Record<string, unknown>
}

export interface PaperPreview {
  constraint: PaperConstraintOut
  seed: number
  ok: boolean
  items: PaperItem[]
  total_score: number
  target_score: number
  quota_by_qtype: Record<string, number>
  quota_by_difficulty: Record<string, number>
  quota_by_kp: Record<string, number>
  counts_by_qtype: Record<string, number>
  counts_by_difficulty: Record<string, number>
  counts_by_kp: Record<string, number>
  violations: PaperViolation[]
  warnings: string[]
}

export interface Paper {
  id: number
  title: string
  status: PaperStatus
  total_score: number
  duration_min: number | null
  question_ids: number[]
  created_at: string
}

export interface PaperDetail extends Paper {
  constraint_json: Record<string, unknown>
  items: PaperItem[]
  missing_question_ids: number[]
}

export interface PaperConstraintPayload {
  kp_ids: number[]
  total_questions: number
  qtype_ratio: Record<string, number>
  difficulty_dist: Record<string, number>
  total_score: number
  duration_min?: number | null
  exclude_recent_days?: number
  seed?: number
  kp_weights?: Record<string, number>
}

export type PaperGeneratePayload = PaperConstraintPayload

export interface PaperReplacePayload extends PaperConstraintPayload {
  selected_question_ids: number[]
  replace_question_id: number
}

export interface PaperSavePayload {
  title: string
  constraint: PaperConstraintPayload
  question_ids: number[]
  duration_min?: number | null
}

export interface PaperReplaceResult {
  replaced: boolean
  item: PaperItem | null
  reason: string | null
}