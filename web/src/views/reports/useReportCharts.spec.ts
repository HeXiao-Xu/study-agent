import { describe, expect, it } from 'vitest'

import type {
  ReportHeatmapNode,
  ReportModule,
  ReportSubject,
  ReportTrendPoint,
} from '@/types/reports'

import {
  assessedModules,
  buildHeatmapTree,
  hasAssessed,
  pageSummary,
  radarOption,
  treemapOption,
  trendOption,
} from './useReportCharts'

function module(kp_id: number, name: string, mastery: number | null): ReportModule {
  return {
    kp_id,
    kp_name: name,
    exam_weight: 0.5,
    kp_count: 2,
    assessed_count: mastery === null ? 0 : 1,
    mastery,
  }
}

function node(
  kp_id: number,
  name: string,
  level: number,
  parent_id: number | null,
  mastery_t: number | null,
): ReportHeatmapNode {
  return {
    kp_id,
    kp_name: name,
    parent_id,
    level,
    exam_weight: 0.5,
    mastery: mastery_t,
    mastery_t,
    color_value: mastery_t === null ? null : 1 - mastery_t,
    assessed: mastery_t !== null,
  }
}

function subject(modules: ReportModule[], heatmap: ReportHeatmapNode[]): ReportSubject {
  return { subject_id: 7, subject_name: '高中数学', modules, heatmap }
}

const TREND: ReportTrendPoint[] = [
  { date: '2026-11-13', new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
  { date: '2026-11-14', new_notes: 0, reviews_done: 1, new_mistakes: 2, mastered_mistakes: 2, mistakes_net: 0 },
]

describe('pageSummary', () => {
  it('sums trend fields and keeps labels explicit', () => {
    expect(pageSummary(TREND)).toEqual([
      { label: '新增笔记', value: 1 },
      { label: '完成复习', value: 3 },
      { label: '新增错题', value: 5 },
      { label: '已掌握错题', value: 3 },
      { label: '错题净变化', value: 2 },
    ])
  })
})

describe('radar', () => {
  it('only assesses modules with non-null mastery', () => {
    const s = subject(
      [module(1, '函数', 0.3), module(2, '数列', null), module(3, '三角', 0.8)],
      [],
    )
    expect(assessedModules(s).map((m) => m.kp_id)).toEqual([1, 3])
    expect(hasAssessed(s)).toBe(true)
    const option = radarOption(s) as { radar: { indicator: Array<{ name: string }> }; series: Array<{ data: Array<{ value: number[] }> }> }
    expect(option.radar.indicator.map((row) => row.name)).toEqual(['函数', '三角'])
    expect(option.series[0]!.data[0]!.value).toEqual([0.3, 0.8])
  })

  it('reports no assessed modules', () => {
    expect(hasAssessed(subject([module(1, '函数', null)], []))).toBe(false)
  })
})

describe('heatmap tree', () => {
  it('builds level 2→3→4 and attaches orphan to root', () => {
    const nodes = [
      node(10, '函数', 2, null, 0.5),
      node(11, '单调性', 3, 10, 0.3),
      node(12, '基本公式', 4, 11, null),
      node(20, '孤儿', 3, 999, 0.6),
    ]
    const tree = buildHeatmapTree(nodes)
    expect(tree.map((row) => row.kp_id)).toEqual([10, 20])
    expect(tree[0]!.children.map((row) => row.kp_id)).toEqual([11])
    expect(tree[0]!.children[0]!.children[0]!.itemStyle.color).toBe('#9aa4b2')
    expect(tree[1]!.itemStyle.color).not.toBe('#9aa4b2')
  })
})

describe('treemapOption', () => {
  it('wraps the tree in a treemap series', () => {
    const option = treemapOption([node(10, '函数', 2, null, 0.5)]) as {
      series: Array<{ type: string; data: Array<{ kp_id: number }> }>
    }
    expect(option.series[0]!.type).toBe('treemap')
    expect(option.series[0]!.data[0]!.kp_id).toBe(10)
  })
})

describe('trendOption', () => {
  it('has five series and a dashed net series', () => {
    const option = trendOption(TREND) as {
      xAxis: { data: string[] }
      series: Array<{ name: string; data: number[]; lineStyle?: { type?: string } }>
    }
    expect(option.xAxis.data).toEqual(['2026-11-13', '2026-11-14'])
    expect(option.series).toHaveLength(5)
    expect(option.series[4]!.name).toBe('错题净变化')
    expect(option.series[4]!.lineStyle?.type).toBe('dashed')
    expect(option.series[2]!.data).toEqual([3, 2])
  })
})