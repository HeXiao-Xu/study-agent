/**
 * 统计看板的纯函数层（S4-8）。
 *
 * 和 S4-6 的 useGraphData 同样的理由：jsdom 没有 canvas，页面级只能 mock ECharts；
 * 把「数据 → option」抽出来，补零、分档、空数组这些易错点才能被直接断言。
 */
import type {
  StatsCauseCount,
  StatsSummary,
  StatsTopKp,
  StatsTrendPoint,
} from '@/types/stats'
import { masteryColor } from '@/utils/masteryColor'

export const UNKNOWN_CAUSE_COLOR = '#9aa4b2'

const CAUSE_PALETTE = ['#e5484d', '#f0b429', '#3b82f6', '#8b5cf6', '#22c55e', '#f97316']

/**
 * unknown 单独灰；其余按名字哈希取固定调色板——
 * 错因类型是有限的几个中文串，用哈希而不是下标，换顺序也不会改色。
 */
export function causeColor(causeType: string): string {
  if (causeType === 'unknown') return UNKNOWN_CAUSE_COLOR
  let hash = 0
  for (const char of causeType) hash = (hash * 31 + char.codePointAt(0)!) % 997
  return CAUSE_PALETTE[hash % CAUSE_PALETTE.length]!
}

export function summaryCards(summary: StatsSummary): { label: string; value: number }[] {
  return [
    { label: '错题总数', value: summary.total },
    { label: '待订正', value: summary.pending },
    { label: '已订正', value: summary.corrected },
    { label: '已掌握', value: summary.mastered },
  ]
}

export function causeOption(data: StatsCauseCount[]): unknown {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条（{d}%）' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        data: data.map((item) => ({
          name: item.cause_type,
          value: item.count,
          itemStyle: { color: causeColor(item.cause_type) },
        })),
      },
    ],
  }
}

export function topKpOption(data: StatsTopKp[]): unknown {
  return {
    grid: { left: 8, right: 72, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: Array<{ dataIndex: number }>) => {
        const row = data[params[0]?.dataIndex ?? -1]
        if (row === undefined) return ''
        const mastery = row.mastery === null ? '未评估' : row.mastery.toFixed(2)
        return `${row.kp_name}<br/>错题 ${row.count} 条 · 掌握度 ${mastery}`
      },
    },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: data.map((item) => item.kp_name), inverse: true },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        label: {
          show: true,
          position: 'right',
          formatter: (params: { dataIndex: number }) => {
            const row = data[params.dataIndex]
            if (row === undefined) return ''
            return row.mastery === null ? `${row.count}` : `${row.count} · ${row.mastery.toFixed(2)}`
          },
        },
        data: data.map((item) => ({
          value: item.count,
          itemStyle: { color: masteryColor(item.mastery) },
        })),
      },
    ],
  }
}

/** 累计已掌握全 0 时没必要画一条贴底的虚线。 */
export function hasMastered(data: StatsTrendPoint[]): boolean {
  return data.some((point) => point.mastered > 0)
}

export function trendOption(data: StatsTrendPoint[]): unknown {
  const series: Array<Record<string, unknown>> = [
    {
      name: '新增错题',
      type: 'line',
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.12 },
      data: data.map((point) => point.new_mistakes),
    },
  ]
  if (hasMastered(data)) {
    series.push({
      name: '累计已掌握',
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { type: 'dashed' },
      data: data.map((point) => point.mastered),
    })
  }
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map((point) => point.date.slice(5)),
    },
    yAxis: { type: 'value', minInterval: 1 },
    series,
  }
}