/**
 * 图谱关系审核的取数逻辑：列表 + 统计 + 单条/批量审核 + 重建轮询。
 * 组件只负责渲染，状态与请求集中在这里，便于单测。
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  buildGraph,
  getGraphStats,
  listGraphEdges,
  reviewGraphEdge,
  reviewGraphEdges,
} from '@/api/kp'
import { getTask } from '@/api/tasks'
import type { GraphEdge, GraphReviewStatus, GraphStats } from '@/types/kp'

export const RELATION_LABELS: Record<string, string> = {
  contains: '包含',
  prerequisite: '前置',
  related: '相关',
  confusable: '易混',
}

const POLL_INTERVAL_MS = 4000
const POLL_MAX_ATTEMPTS = 180

export function useGraphReview(subjectId: () => number) {
  const edges = ref<GraphEdge[]>([])
  const stats = ref<GraphStats | null>(null)
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const status = ref<GraphReviewStatus | 'all'>('pending')
  const relation = ref('')
  const keyword = ref('')
  const loading = ref(false)
  const building = ref(false)
  const selection = ref<GraphEdge[]>([])

  function pendingCount(): number {
    return stats.value?.by_status.pending ?? 0
  }

  async function load(): Promise<void> {
    loading.value = true
    try {
      const data = await listGraphEdges({
        subject_id: subjectId(),
        status: status.value,
        relation: relation.value || undefined,
        q: keyword.value || undefined,
        page: page.value,
        page_size: pageSize.value,
      })
      edges.value = data.items
      total.value = data.total
      stats.value = await getGraphStats(subjectId())
    } catch {
      edges.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  async function review(edge: GraphEdge, approve: boolean): Promise<void> {
    await reviewGraphEdge(edge.id, approve)
    ElMessage.success(approve ? '已通过' : '已驳回')
    await load()
  }

  async function reviewSelected(approve: boolean): Promise<void> {
    if (selection.value.length === 0) {
      ElMessage.warning('先勾选要处理的关系边')
      return
    }
    const result = await reviewGraphEdges(
      selection.value.map((edge) => edge.id),
      approve,
    )
    const tail = result.skipped ? `，跳过 ${result.skipped} 条` : ''
    ElMessage.success(`已处理 ${result.updated} 条${tail}`)
    selection.value = []
    await load()
  }

  async function poll(taskId: number): Promise<void> {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      const task = await getTask(taskId)
      if (task.status === 'succeeded') {
        return
      }
      if (task.status === 'failed') {
        ElMessage.error('图谱构建失败，请看任务详情')
        return
      }
    }
  }

  async function rebuild(): Promise<void> {
    building.value = true
    try {
      const task = await buildGraph({ subject_id: subjectId() })
      ElMessage.success(`构建任务已提交（#${task.id}），完成后自动刷新`)
      await poll(task.id)
      await load()
    } finally {
      building.value = false
    }
  }

  watch([status, relation, page], load)

  return {
    edges,
    stats,
    total,
    page,
    pageSize,
    status,
    relation,
    keyword,
    loading,
    building,
    selection,
    pendingCount,
    RELATION_LABELS,
    load,
    review,
    reviewSelected,
    rebuild,
  }
}