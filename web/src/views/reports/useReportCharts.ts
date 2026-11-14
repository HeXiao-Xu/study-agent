/** S5-7 学习报告图表纯函数：页面只负责 setOption。 */
import type {
  ReportHeatmapNode,
  ReportModule,
  ReportSubject,
  ReportTrendPoint,
} from '@/types/reports'
import { COLOR_UNRATED, masteryColor } from '@/utils/masteryColor'

export interface HeatmapTreeNode {
  name: string
  kp_id: number
  level: number
  value: number
  mastery_t: number | null
  itemStyle: { color: string; borderColor: string; borderWidth: number }
  children: HeatmapTreeNode[]
}

type NumericTrendKey = Exclude<keyof ReportTrendPoint, 'date'>

export function pageSummary(
  trend: ReportTrendPoint[],
): Array<{ label: string; value: number }> {
  const sum = (key: NumericTrendKey): number =>
    trend.reduce((total, point) => total + Number(point[key]), 0)
  return [
    { label: '新增笔记', value: sum('new_notes') },
    { label: '完成复习', value: sum('reviews_done') },
    { label: '新增错题', value: sum('new_mistakes') },
    { label: '已掌握错题', value: sum('mastered_mistakes') },
    { label: '错题净变化', value: sum('mistakes_net') },
  ]
}

export function assessedModules(subject: ReportSubject): ReportModule[] {
  return subject.modules.filter((module) => module.mastery !== null)
}

export function hasAssessed(subject: ReportSubject): boolean {
  return assessedModules(subject).length > 0
}

export function radarOption(subject: ReportSubject): Record<string, unknown> {
  const modules = assessedModules(subject)
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: modules.map((module) => ({ name: module.kp_name, max: 1 })),
      radius: '62%',
      axisName: { color: '#667085', fontSize: 11 },
      splitArea: { areaStyle: { color: ['#fbfcfe', '#f4f7fb'] } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 5,
        areaStyle: { opacity: 0.18 },
        data: [
          {
            name: '模块掌握度',
            value: modules.map((module) => Number(module.mastery ?? 0)),
          },
        ],
      },
    ],
  }
}

/** 扁平热力节点组树；缺父节点的数据挂根，避免整块消失。 */
export function buildHeatmapTree(nodes: ReportHeatmapNode[]): HeatmapTreeNode[] {
  const sorted = [...nodes].sort(
    (left, right) => left.level - right.level || left.kp_id - right.kp_id,
  )
  const byId = new Map<number, HeatmapTreeNode>()
  const roots: HeatmapTreeNode[] = []
  for (const node of sorted) {
    byId.set(node.kp_id, {
      name: node.kp_name,
      kp_id: node.kp_id,
      level: node.level,
      value: 1,
      mastery_t: node.mastery_t,
      itemStyle: {
        color:
          node.assessed && node.mastery_t !== null
            ? masteryColor(node.mastery_t)
            : COLOR_UNRATED,
        borderColor: '#ffffff',
        borderWidth: 1,
      },
      children: [],
    })
  }
  for (const node of sorted) {
    const current = byId.get(node.kp_id)
    if (current === undefined) continue
    const parent =
      node.level > 2 && node.parent_id !== null ? byId.get(node.parent_id) : undefined
    if (parent === undefined) roots.push(current)
    else parent.children.push(current)
  }
  return roots
}

export function treemapOption(nodes: ReportHeatmapNode[]): Record<string, unknown> {
  return {
    tooltip: {
      formatter: (params: { name: string; data: HeatmapTreeNode }) => {
        const mastery = params.data.mastery_t
        return `${params.name}<br/>掌握度 ${mastery === null ? '未评估' : mastery.toFixed(2)}`
      },
    },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        upperLabel: { show: true, height: 20, color: '#344054' },
        itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
        label: { show: true, color: '#101828', fontSize: 11 },
        data: buildHeatmapTree(nodes),
      },
    ],
  }
}

export function trendOption(trend: ReportTrendPoint[]): Record<string, unknown> {
  const series = [
    { name: '新增笔记', key: 'new_notes', color: '#3b5bdb', dashed: false },
    { name: '完成复习', key: 'reviews_done', color: '#2f9e44', dashed: false },
    { name: '新增错题', key: 'new_mistakes', color: '#e8590c', dashed: false },
    { name: '已掌握错题', key: 'mastered_mistakes', color: '#7048e8', dashed: false },
    { name: '错题净变化', key: 'mistakes_net', color: '#c92a2a', dashed: true },
  ] as const
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll' },
    grid: { left: 36, right: 20, top: 24, bottom: 48 },
    xAxis: { type: 'category', data: trend.map((point) => point.date) },
    yAxis: { type: 'value' },
    series: series.map((row) => ({
      name: row.name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: row.dashed ? { type: 'dashed' } : undefined,
      itemStyle: { color: row.color },
      data: trend.map((point) => Number(point[row.key])),
    })),
  }
}