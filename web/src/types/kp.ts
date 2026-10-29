export interface SubjectOut {
  id: number
  name: string
  code: string
  stage: string
}

export interface KpNode {
  id: number
  subject_id: number
  parent_id: number | null
  name: string
  code: string
  level: number
  description: string | null
  exam_weight: number | null
  order_no: number
  children: KpNode[]
}

export interface KpTree {
  subject: SubjectOut
  nodes: KpNode[]
}

export interface KpCreatePayload {
  subject: string
  parent_id: number | null
  code: string
  name: string
  description?: string | null
  exam_weight?: number | null
  order_no?: number
}

export interface KpUpdatePayload {
  name?: string
  description?: string | null
  exam_weight?: number | null
}

export interface KpOrderPayload {
  parent_id: number | null
  ordered_ids: number[]
  moved_id?: number
}

export interface KpDialogPayload {
  name: string
  code?: string
  description: string | null
  exam_weight: number | null
  parent_id: number | null
}

export interface PendingAlign {
  note_id: number
  kp_id: number
  confidence: number
  note_title: string
  note_excerpt: string
  kp_name: string
  kp_code: string
}

export interface AlignPair {
  note_id: number
  kp_id: number
}

export interface AlignBatchResult {
  confirmed: number
  deleted: number
  skipped: number
}
