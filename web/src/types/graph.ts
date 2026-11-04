export type GraphRelation = 'contains' | 'prerequisite' | 'related' | 'confusable'

export interface GraphSnapshotNode {
  id: number
  name: string
  level: number
  parent_id: number | null
  exam_weight: number | null
  mistake_count: number
}

export interface GraphSnapshotEdge {
  src_kp_id: number
  dst_kp_id: number
  relation: GraphRelation
  weight: number | null
}

export interface GraphSnapshotStats {
  nodes: number
  edges: number
  pending_edges: number
  by_relation: Record<string, number>
}

export interface GraphSnapshot {
  subject: { id: number; name: string }
  nodes: GraphSnapshotNode[]
  edges: GraphSnapshotEdge[]
  stats: GraphSnapshotStats
}

export interface GraphNeighbor {
  kp_id: number
  name: string
  weight: number | null
}

export interface GraphNoteBrief {
  id: number
  title: string
  updated_at: string
}

export interface GraphMistakeBrief {
  id: number
  question_id: number
  status: string
  created_at: string
  stem: string
}

export interface GraphNodeDetail {
  id: number
  name: string
  level: number
  parent_id: number | null
  subject_id: number
  path: string[]
  description: string | null
  exam_weight: number | null
  mistake_count: number
  prerequisites: GraphNeighbor[]
  successors: GraphNeighbor[]
  related: GraphNeighbor[]
  confusable: GraphNeighbor[]
  notes: GraphNoteBrief[]
  mistakes: GraphMistakeBrief[]
}