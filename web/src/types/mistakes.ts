/**
 * S4-2 错题类型：字段与后端 `backend/app/schemas/mistake.py` 一一对应。
 * 查询参数与请求体用 camelCase（前端惯例），由 `api/mistakes.ts` 映射回 snake_case。
 */
export const MISTAKE_STATUSES = ['待订正', '已订正', '已掌握'] as const
export type MistakeStatus = (typeof MISTAKE_STATUSES)[number]

/** 与后端 `models/enums.py::CauseType` 一致；`unknown` 表示尚无诊断结论。 */
export const MISTAKE_CAUSE_TYPES = [
  '概念不清',
  '计算失误',
  '审题偏差',
  '方法不当',
  '知识遗忘',
  '时间不足',
  'unknown',
] as const
export type MistakeCauseType = (typeof MISTAKE_CAUSE_TYPES)[number]

/** 展示用文案：六类错因本身是中文，只有 unknown 需要换成人话。 */
export const MISTAKE_CAUSE_LABELS: Record<MistakeCauseType, string> = {
  概念不清: '概念不清',
  计算失误: '计算失误',
  审题偏差: '审题偏差',
  方法不当: '方法不当',
  知识遗忘: '知识遗忘',
  时间不足: '时间不足',
  unknown: '未诊断',
}

/** MistakeSummaryOut 的列表查询参数（camelCase，映射见 api/mistakes.ts）。 */
export type MistakeSort = 'created_at' | 'last_review_at' | 'status' | 'correct_streak'

export interface MistakeListParams {
  /** 筛选控件清空时会给空串，`api/mistakes.ts` 发请求前剔除。 */
  status?: MistakeStatus | ''
  causeType?: MistakeCauseType | ''
  kpId?: number | null
  createdFrom?: string
  createdTo?: string
  page?: number
  pageSize?: number
  sortBy?: MistakeSort
  order?: 'asc' | 'desc'
}

/** Task 11 brief 使用的名字，语义与 `MistakeListParams` 相同。 */
export type MistakeFilters = MistakeListParams

export interface MistakeStatsParams {
  createdFrom?: string
  createdTo?: string
}

export interface MistakeOption {
  key: string
  text: string
}

/** S4-4 变式题（MistakeVariantOut）：只有通过复算自检的题才会出现。 */
export interface MistakeVariant {
  variant_id: string
  stem_md: string
  options: MistakeOption[] | null
  answer_md: string
  analysis_md: string | null
  qtype: string
  difficulty: number
  self_check: string
  accepted_question_id: number | null
}

/** S4-4 本次生成的统计：rejected 只计数，被丢弃的题不下发给前端。 */
export interface VariantsStats {
  requested: number
  passed: number
  rejected: number
  rounds: number
  generated_at: string | null
}

/** VariantAcceptOut：created=false 表示已入库或题库已有同题。 */
export interface VariantAcceptResult {
  question_id: number
  created: boolean
}

/** MistakeAnalysisOut（S4-3 起含次因、置信度与模型溯源；S4-4 起含变式题） */
export interface MistakeAnalysis {
  cause_type: MistakeCauseType
  secondary_causes: MistakeCauseType[]
  error_step: string | null
  explanation_md: string | null
  review_advice_md: string | null
  kp_ids: number[] | null
  confidence: number | null
  model: string
  prompt_version: string
  created_at: string
  /** 未生成过是 null；已生成但 0 道通过时是空数组（配合 variants_stats 区分）。 */
  similar_questions: MistakeVariant[] | null
  variants_stats: VariantsStats | null
}

/** MistakeSummaryOut */
export interface MistakeSummary {
  id: number
  question_id: number
  status: MistakeStatus
  correct_streak: number
  stem_excerpt: string
  subject_id: number
  qtype: string
  difficulty: number
  kp_names: string[]
  cause_type: MistakeCauseType | null
  has_image: boolean
  created_at: string
  last_review_at: string | null
}

/** MistakeDetailOut */
export interface MistakeDetail extends MistakeSummary {
  stem_md: string
  options: MistakeOption[] | null
  my_answer_md: string | null
  correct_answer_md: string | null
  image_url: string | null
  analysis: MistakeAnalysis | null
}

/** MistakeCreateOut = MistakeDetailOut + created（同题复用时为 false）。 */
export interface MistakeCreateResult extends MistakeDetail {
  created: boolean
}

/** MistakeStatsOut */
export interface MistakeStats {
  total: number
  by_status: { status: MistakeStatus; count: number }[]
  by_cause: { cause_type: MistakeCauseType; count: number }[]
  top_kps: { kp_id: number; kp_name: string; count: number }[]
}

/** `mistake.recognize` 任务结果（backend/app/tasks/mistake_recognize.py 的 return）。 */
export interface MistakeRecognizeResult {
  mistake_id: number
  question_id: number
  created: boolean
  reused_question: boolean
  confidence: number
  low_confidence: boolean
  used_answer_source: 'student' | 'vision' | 'none'
  warnings: string[]
  elapsed_ms: number
  /** S4-3：识别成功后是否已入队诊断（best-effort，队列故障时为 false）。 */
  analysis_enqueued?: boolean
}

/**
 * `mistake.analyze` 任务结果（backend/app/tasks/analyze_mistake.py 的 return）。
 * `force=false` 且已有诊断时是 `{mistake_id, skipped: true}`，其余字段都可缺省。
 */
export interface MistakeAnalyzeResult {
  mistake_id: number
  cause_type?: MistakeCauseType
  secondary_causes?: MistakeCauseType[]
  confidence?: number | null
  retrieval_hits?: number
  skipped?: boolean
}

/** `mistake.variants` 任务结果（backend/app/services/question_gen_service.py 的 return）。 */
export interface MistakeVariantsResult {
  mistake_id: number
  requested: number
  passed: number
  rejected: number
  rounds: number
  elapsed_ms: number
}

/** MistakeCreateIn */
export interface MistakeCreatePayload {
  questionId: number
  myAnswerMd?: string | null
  correctAnswerMd?: string | null
}

/** MistakeUpdateIn；显式传 null 表示清空该列（与后端 PATCH 语义一致）。 */
export interface MistakeUpdatePayload {
  myAnswerMd?: string | null
  correctAnswerMd?: string | null
  status?: MistakeStatus
}
