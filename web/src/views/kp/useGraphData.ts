/**
 * 图谱可视化的纯函数层（S4-6）。
 *
 * 拆出来的原因：ECharts 在 jsdom 里没有 canvas，页面级测试只能靠 mock；
 * 把「可见集合 → option」做成纯函数，颜色/降级/过滤这些易错逻辑才能被直接断言。
 */
import type {
  GraphRelation,
  GraphSnapshot,
  GraphSnapshotEdge,
  GraphSnapshotNode,
} from '@/types/graph'

import { masteryColor, masteryLabel } from '@/utils/masteryColor'

/** 节点数超过该值就只画焦点子图（卡片要求 >300 降级）。 */
export const DEGRADE_THRESHOLD = 300

// 掌握度四色与 hit 口径在 utils/masteryColor（S4-8 起与统计看板共用）
export {
  COLOR_HIGH,
  COLOR_LOW,
  COLOR_MID,
  COLOR_UNRATED,
  masteryLabel,
} from '@/utils/masteryColor'

export interface EdgeStyle {
  color: string
  type: 'solid' | 'dashed' | 'dotted'
  width: number
  arrow: boolean
}

export const EDGE_STYLES: Record<GraphRelation, EdgeStyle> = {
  contains: { color: '#cfd6e0', type: 'solid', width: 1, arrow: false },
  prerequisite: { color: '#3b82f6', type: 'solid', width: 1.4, arrow: true },
  related: { color: '#22c55e', type: 'dashed', width: 1.2, arrow: false },
  confusable: { color: '#f59e0b', type: 'dotted', width: 1.2, arrow: false },
}

export interface SelectOptions {
  relations: GraphRelation[]
  activeChapters: Set<number> | null
  focusId: number | null
  threshold?: number
}

/** 掌握度分档（S4-7）：<0.4 红、0.4–0.7 黄、≥0.7 绿；null = 未评估（灰）。 */
/** 掌握度分档（S4-7）：实现见 utils/masteryColor，图谱侧继续用旧名字。 */
export function nodeColor(mastery: number | null): string {
  return masteryColor(mastery)
}

export function nodeSize(examWeight: number | null): number {
  const weight = Math.min(1, Math.max(0, examWeight ?? 0))
  return Math.round(8 + 22 * weight)
}

export function chapterOf(
  nodeId: number,
  nodes: Map<number, GraphSnapshotNode>,
): number {
  let current = nodes.get(nodeId)
  let guard = 0
  let lastId = nodeId
  while (current !== undefined && guard < 10) {
    if (current.level <= 2) return current.id
    lastId = current.id
    current = current.parent_id === null ? undefined : nodes.get(current.parent_id)
    guard += 1
  }
  return lastId
}

export function chapterOptions(
  nodes: GraphSnapshotNode[],
): Array<{ id: number; name: string }> {
  return nodes
    .filter((node) => node.level === 2)
    .sort((left, right) => left.id - right.id)
    .map((node) => ({ id: node.id, name: node.name }))
}

export function pickFocusNode(nodes: GraphSnapshotNode[]): number | null {
  let best: GraphSnapshotNode | null = null
  for (const node of nodes) {
    if (
      best === null ||
      node.mistake_count > best.mistake_count ||
      (node.mistake_count === best.mistake_count && node.id < best.id)
    ) {
      best = node
    }
  }
  return best === null ? null : best.id
}

function subgraphAround(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
  focusId: number,
): { nodes: GraphSnapshotNode[]; edges: GraphSnapshotEdge[] } {
  const keep = new Set<number>([focusId])
  for (const edge of edges) {
    if (edge.src_kp_id === focusId) keep.add(edge.dst_kp_id)
    if (edge.dst_kp_id === focusId) keep.add(edge.src_kp_id)
  }
  return {
    nodes: nodes.filter((node) => keep.has(node.id)),
    edges: edges.filter((edge) => keep.has(edge.src_kp_id) && keep.has(edge.dst_kp_id)),
  }
}

export function selectVisible(
  snapshot: GraphSnapshot,
  options: SelectOptions,
): { nodes: GraphSnapshotNode[]; edges: GraphSnapshotEdge[]; degraded: boolean } {
  const threshold = options.threshold ?? DEGRADE_THRESHOLD
  const relationSet = new Set(options.relations)
  const nodesById = new Map(snapshot.nodes.map((node) => [node.id, node]))
  const edges = snapshot.edges.filter((edge) => relationSet.has(edge.relation))
  const chapterFilter = options.activeChapters
  const nodes =
    chapterFilter === null
      ? snapshot.nodes
      : snapshot.nodes.filter(
          (node) => node.level <= 1 || chapterFilter.has(chapterOf(node.id, nodesById)),
        )
  const kept = new Set(nodes.map((node) => node.id))
  const keptEdges = edges.filter(
    (edge) => kept.has(edge.src_kp_id) && kept.has(edge.dst_kp_id),
  )
  if (nodes.length <= threshold) {
    return { nodes, edges: keptEdges, degraded: false }
  }
  const focusId = options.focusId ?? pickFocusNode(nodes)
  if (focusId === null) {
    return { nodes, edges: keptEdges, degraded: false }
  }
  return { ...subgraphAround(nodes, keptEdges, focusId), degraded: true }
}

export function matchNodes(
  nodes: GraphSnapshotNode[],
  keyword: string,
  limit = 20,
): GraphSnapshotNode[] {
  const needle = keyword.trim().toLowerCase()
  if (!needle) return []
  return nodes
    .filter((node) => node.name.toLowerCase().includes(needle))
    .slice(0, limit)
}

export function buildOption(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
  selectedId: number | null,
): Record<string, unknown> {
  return {
    animationDuration: 200,
    tooltip: {
      confine: true,
      formatter: (params: {
        dataType?: string
        data?: { name?: string; mastery?: number | null }
      }) =>
        params.dataType === 'node'
          ? `${params.data?.name ?? ''}\n${masteryLabel(params.data?.mastery ?? null)}`
          : '',
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 220, gravity: 0.06, edgeLength: [40, 90] },
        label: { show: true, fontSize: 10, color: '#344054' },
        labelLayout: { hideOverlap: true },
        emphasis: { focus: 'adjacency', lineStyle: { width: 2 } },
        selectedMode: 'single',
        select: { itemStyle: { borderColor: '#111827', borderWidth: 2 } },
        data: nodes.map((node) => ({
          id: String(node.id),
          name: node.name,
          value: node.exam_weight ?? 0,
          symbolSize: nodeSize(node.exam_weight),
          itemStyle: { color: nodeColor(node.mastery) },
          mastery: node.mastery,
          selected: selectedId === node.id,
        })),
        links: edges.map((edge) => {
          const style = EDGE_STYLES[edge.relation] ?? EDGE_STYLES.related
          return {
            source: String(edge.src_kp_id),
            target: String(edge.dst_kp_id),
            lineStyle: {
              color: style.color,
              type: style.type,
              width: style.width,
              opacity: 0.7,
              curveness: 0.08,
            },
            ...(style.arrow ? { symbol: ['none', 'arrow'], symbolSize: [0, 6] } : {}),
          }
        }),
      },
    ],
  }
}