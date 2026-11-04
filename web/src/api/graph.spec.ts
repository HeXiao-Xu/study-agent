import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchGraphNode, fetchGraphSnapshot } from './graph'

const http = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/api/http', () => ({
  API_PREFIX: '/api/v1',
  default: http,
}))

function envelope<T>(data: T) {
  return { data: { code: 0, message: 'ok', trace_id: 'trace-1', data } }
}

const snapshot = {
  subject: { id: 7, name: '高中数学' },
  nodes: [
    { id: 2, name: '导数', level: 3, parent_id: 1, exam_weight: 0.8, mistake_count: 1 },
  ],
  edges: [{ src_kp_id: 1, dst_kp_id: 2, relation: 'prerequisite', weight: 0.9 }],
  stats: { nodes: 2, edges: 1, pending_edges: 50, by_relation: { prerequisite: 1 } },
}

const detail = {
  id: 3,
  name: '导数与函数的单调性',
  level: 3,
  parent_id: 2,
  subject_id: 7,
  path: ['高中数学', '导数及其应用'],
  description: null,
  exam_weight: 0.8,
  mistake_count: 0,
  prerequisites: [],
  successors: [],
  related: [],
  confusable: [],
  notes: [],
  mistakes: [],
}

beforeEach(() => {
  http.get.mockReset()
})

describe('graph api', () => {
  it('fetchGraphSnapshot 带 subject_id 查询参数并解包', async () => {
    http.get.mockResolvedValueOnce(envelope(snapshot))
    const result = await fetchGraphSnapshot(7)
    expect(http.get).toHaveBeenCalledWith('/api/v1/kp/graph/snapshot', {
      params: { subject_id: 7 },
    })
    expect(result.stats.pending_edges).toBe(50)
  })

  it('fetchGraphNode 按 kp_id 请求详情', async () => {
    http.get.mockResolvedValueOnce(envelope(detail))
    const result = await fetchGraphNode(3)
    expect(http.get).toHaveBeenCalledWith('/api/v1/kp/graph/nodes/3')
    expect(result.path).toEqual(['高中数学', '导数及其应用'])
    expect(result.description).toBeNull()
  })
})