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

/** S4-5 知识图谱关系 */
export type GraphRelation = 'contains' | 'prerequisite' | 'related' | 'confusable'
export type GraphReviewStatus = 'pending' | 'approved' | 'rejected'

export interface GraphEdge {
  id: number
  src_kp_id: number
  src_name: string
  dst_kp_id: number
  dst_name: string
  relation: GraphRelation
  weight: number | null
  source: 'ai' | 'manual'
  review_status: GraphReviewStatus
  reviewed_at: string | null
  created_at: string
}

export interface GraphStats {
  subject_id: number | null
  nodes: number
  edges: number
  by_relation: Record<string, number>
  by_status: Record<string, number>
  last_built_at: string | null
}

export interface GraphEdgeQuery {
  status?: GraphReviewStatus | 'all'
  relation?: string
  subject_id?: number
  q?: string
  page?: number
  page_size?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}

export interface GraphBuildPayload {
  subject_id: number
  relations?: GraphRelation[]
  limit?: number
}

export interface GraphReviewResult {
  updated: number
  skipped: number
}
