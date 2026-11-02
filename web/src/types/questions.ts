/** S4-1 题库类型：字段与后端 schemas/question.py 一一对应。 */
export type QuestionType = '单选' | '多选' | '填空' | '解答'
export type QuestionOrigin = 'textbook' | 'exam' | 'mock' | 'upload' | 'ai'

export interface QuestionOption {
  key: string
  text: string
}

export interface KpRef {
  kp_id: number
  kp_name: string
  kp_code: string
  weight: number | null
}

export interface QuestionSummary {
  id: number
  subject_id: number
  qtype: QuestionType
  difficulty: number
  origin: QuestionOrigin
  verified: boolean
  stem_md: string
  source_file_id: number | null
  created_by: number | null
  created_at: string
  kp_names: string[]
}

export interface QuestionDetail extends QuestionSummary {
  options_json: QuestionOption[] | null
  answer_md: string | null
  analysis_md: string | null
  stem_latex: string | null
  tags: string[] | null
  kps: KpRef[]
}

export interface QuestionListParams {
  page?: number
  page_size?: number
  subject_id?: number
  qtype?: QuestionType
  kp_id?: number
  origin?: QuestionOrigin
  mine?: boolean
  verified?: boolean
  keyword?: string
  source_file_id?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}

export interface QuestionCreatePayload {
  subject_id: number
  stem_md: string
  options?: QuestionOption[] | null
  answer_md?: string | null
  analysis_md?: string | null
  qtype: QuestionType
  difficulty: number
  kp_ids?: number[]
  origin?: QuestionOrigin
  tags?: string[] | null
}

export type QuestionUpdatePayload = Partial<Omit<QuestionCreatePayload, 'subject_id'>> & {
  verified?: boolean
}