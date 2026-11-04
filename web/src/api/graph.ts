import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { GraphNodeDetail, GraphSnapshot } from '@/types/graph'

export async function fetchGraphSnapshot(subjectId: number): Promise<GraphSnapshot> {
  const resp = await http.get<ApiEnvelope<GraphSnapshot>>(
    `${API_PREFIX}/kp/graph/snapshot`,
    { params: { subject_id: subjectId } },
  )
  return resp.data.data
}

export async function fetchGraphNode(kpId: number): Promise<GraphNodeDetail> {
  const resp = await http.get<ApiEnvelope<GraphNodeDetail>>(
    `${API_PREFIX}/kp/graph/nodes/${kpId}`,
  )
  return resp.data.data
}