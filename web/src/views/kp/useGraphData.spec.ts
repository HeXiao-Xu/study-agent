import { describe, expect, it } from 'vitest'

import type { GraphSnapshot, GraphSnapshotEdge, GraphSnapshotNode } from '@/types/graph'

import {
  DEGRADE_THRESHOLD,
  EDGE_STYLES,
  buildOption,
  chapterOf,
  chapterOptions,
  matchNodes,
  nodeColor,
  nodeSize,
  pickFocusNode,
  selectVisible,
} from './useGraphData'

function node(
  id: number,
  name: string,
  opts: Partial<GraphSnapshotNode> = {},
): GraphSnapshotNode {
  return {
    id,
    name,
    level: opts.level ?? 3,
    parent_id: opts.parent_id ?? 1,
    exam_weight: opts.exam_weight ?? 0.5,
    mistake_count: opts.mistake_count ?? 0,
  }
}

function edge(
  src: number,
  dst: number,
  relation: GraphSnapshotEdge['relation'] = 'prerequisite',
): GraphSnapshotEdge {
  return { src_kp_id: src, dst_kp_id: dst, relation, weight: 0.9 }
}

function snapshot(nodes: GraphSnapshotNode[], edges: GraphSnapshotEdge[]): GraphSnapshot {
  return {
    subject: { id: 7, name: '高中数学' },
    nodes,
    edges,
    stats: { nodes: nodes.length, edges: edges.length, pending_edges: 0, by_relation: {} },
  }
}

describe('nodeColor', () => {
  it('按错题数分三档', () => {
    expect(nodeColor(0)).toBe('#9aa4b2')
    expect(nodeColor(1)).toBe('#f0b429')
    expect(nodeColor(2)).toBe('#f0b429')
    expect(nodeColor(3)).toBe('#e5484d')
    expect(nodeColor(99)).toBe('#e5484d')
  })
})

describe('nodeSize', () => {
  it('考纲权重映射到 8–30，null 取下限', () => {
    expect(nodeSize(null)).toBe(8)
    expect(nodeSize(0)).toBe(8)
    expect(nodeSize(1)).toBe(30)
    expect(nodeSize(0.5)).toBe(19)
  })

  it('越界权重被 clamp', () => {
    expect(nodeSize(-1)).toBe(8)
    expect(nodeSize(2)).toBe(30)
  })
})

describe('EDGE_STYLES', () => {
  it('四类关系样式互不相同，前置带箭头', () => {
    expect(EDGE_STYLES.prerequisite.type).toBe('solid')
    expect(EDGE_STYLES.prerequisite.arrow).toBe(true)
    expect(EDGE_STYLES.related.type).toBe('dashed')
    expect(EDGE_STYLES.confusable.type).toBe('dotted')
    expect(EDGE_STYLES.contains.arrow).toBe(false)
  })
})

describe('chapterOf', () => {
  it('沿 parent 找到最近的 level<=2 祖先，level 1 返回自身', () => {
    const nodes = new Map([
      [1, node(1, '高中数学', { level: 1, parent_id: null })],
      [2, node(2, '导数及其应用', { level: 2, parent_id: 1 })],
      [3, node(3, '导数的概念与运算', { level: 3, parent_id: 2 })],
      [4, node(4, '基本求导公式', { level: 4, parent_id: 3 })],
    ])
    expect(chapterOf(4, nodes)).toBe(2)
    expect(chapterOf(2, nodes)).toBe(2)
    expect(chapterOf(1, nodes)).toBe(1)
  })
})

describe('chapterOptions', () => {
  it('只列 level=2 的章，按 id 升序', () => {
    const options = chapterOptions([
      node(5, '三角函数', { level: 2 }),
      node(1, '高中数学', { level: 1, parent_id: null }),
      node(3, '函数', { level: 2 }),
    ])
    expect(options).toEqual([
      { id: 3, name: '函数' },
      { id: 5, name: '三角函数' },
    ])
  })
})

describe('selectVisible', () => {
  const nodes = [
    node(1, '高中数学', { level: 1, parent_id: null }),
    node(2, '函数', { level: 2, parent_id: 1 }),
    node(3, '导数及其应用', { level: 2, parent_id: 1 }),
    node(4, '单调性', { level: 3, parent_id: 2 }),
    node(5, '导数应用', { level: 3, parent_id: 3 }),
  ]
  const edges = [edge(2, 4, 'contains'), edge(3, 5, 'contains'), edge(4, 5)]

  it('contains 不在 relations 里时被过滤掉', () => {
    const visible = selectVisible(snapshot(nodes, edges), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: null,
    })
    expect(visible.edges).toHaveLength(1)
    expect(visible.degraded).toBe(false)
  })

  it('折叠章时该章节点与其边一并消失，level 1 恒在', () => {
    const visible = selectVisible(snapshot(nodes, edges), {
      relations: ['contains', 'prerequisite'],
      activeChapters: new Set([3]),
      focusId: null,
    })
    expect(visible.nodes.map((item) => item.id)).toEqual([1, 3, 5])
    expect(visible.edges.map((item) => [item.src_kp_id, item.dst_kp_id])).toEqual([[3, 5]])
  })

  it('节点数超过阈值时只留焦点与一跳邻居', () => {
    const many = Array.from({ length: DEGRADE_THRESHOLD + 1 }, (_, index) =>
      node(100 + index, `节点${index}`),
    )
    const chain = [edge(100, 101), edge(101, 102), edge(103, 104)]
    const visible = selectVisible(snapshot(many, chain), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: 101,
    })
    expect(visible.degraded).toBe(true)
    expect(visible.nodes.map((item) => item.id).sort()).toEqual([100, 101, 102])
  })

  it('降级时没有焦点就用错题最多的节点', () => {
    const many = Array.from({ length: DEGRADE_THRESHOLD + 1 }, (_, index) =>
      node(100 + index, `节点${index}`, { mistake_count: index === 7 ? 5 : 0 }),
    )
    const visible = selectVisible(snapshot(many, [edge(107, 108)]), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: null,
    })
    expect(visible.degraded).toBe(true)
    expect(visible.nodes.map((item) => item.id).sort()).toEqual([107, 108])
  })
})

describe('pickFocusNode', () => {
  it('取错题最多者，同分取小 id，空数组返回 null', () => {
    expect(
      pickFocusNode([node(5, 'a', { mistake_count: 1 }), node(6, 'b', { mistake_count: 1 })]),
    ).toBe(5)
    expect(
      pickFocusNode([node(5, 'a', { mistake_count: 0 }), node(6, 'b', { mistake_count: 4 })]),
    ).toBe(6)
    expect(pickFocusNode([])).toBeNull()
  })
})

describe('matchNodes', () => {
  it('按名称中文子串匹配并限制条数', () => {
    const nodes = [node(1, '导数与函数的单调性'), node(2, '导数的实际应用'), node(3, '数列求和')]
    expect(matchNodes(nodes, '导数').map((item) => item.id)).toEqual([1, 2])
    expect(matchNodes(nodes, '  ')).toEqual([])
    expect(matchNodes(nodes, '导数', 1)).toHaveLength(1)
  })
})

describe('buildOption', () => {
  const nodes = [node(3, '单调性', { exam_weight: 1, mistake_count: 3 })]
  const edges = [edge(3, 5), edge(3, 5, 'confusable')]

  it('节点带 symbolSize/颜色，边带箭头与样式', () => {
    const option = buildOption(nodes, edges, null) as {
      series: Array<{ data: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }>
    }
    const series = option.series[0]
    expect(series.data[0]).toMatchObject({
      id: '3',
      name: '单调性',
      symbolSize: 30,
      itemStyle: { color: '#e5484d' },
    })
    const prerequisite = series.links[0] as { symbol: string[]; lineStyle: { color: string } }
    expect(prerequisite.symbol).toEqual(['none', 'arrow'])
    expect(prerequisite.lineStyle.color).toBe(EDGE_STYLES.prerequisite.color)
    const confusable = series.links[1] as { symbol?: string[]; lineStyle: { type: string } }
    expect(confusable.symbol).toBeUndefined()
    expect(confusable.lineStyle.type).toBe('dotted')
  })

  it('力导向参数固定，空集合也不报错', () => {
    const option = buildOption([], [], null) as {
      series: Array<{ layout: string; force: { repulsion: number }; data: unknown[] }>
    }
    expect(option.series[0].layout).toBe('force')
    expect(option.series[0].force.repulsion).toBe(220)
    expect(option.series[0].data).toEqual([])
  })
})