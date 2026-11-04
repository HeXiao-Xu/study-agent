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
import { COLOR_HIGH, COLOR_LOW, COLOR_MID, COLOR_UNRATED, masteryColor } from '@/utils/masteryColor'

export const UNKNOWN_CAUSE_COLOR = '#9aa4b2'

/**
 * 已知错因的固定配色：错因是**有限枚举**（S4-3 定义的 6 类 + unknown），
 * 直接一一对应，别再走哈希——哈希在 6 色上必然撞车（实测 6 类压成 3 色：
 * 概念不清/时间不足 同红、计算失误/审题偏差 同橙、知识遗忘/方法不当 同绿）。
 */
const CAUSE_COLORS: Record<string, string> = {
  概念不清: '#e5484d',
  计算失误: '#f0b429',
  知识遗忘: '#8b5cf6',
  方法不当: '#3b82f6',
  时间不足: '#14b8a6',
  审题偏差: '#f97316',
  unknown: UNKNOWN_CAUSE_COLOR,
}

/** 给「枚举之外的意外名字」备用：与上面 7 个都不撞。 */
const EXTRA_CAUSE_COLORS = ['#ec4899', '#0ea5e9', '#84cc16', '#a855f7', '#facc15', '#64748b']

export function causeColor(causeType: string, taken: string[] = []): string {
  const fixed = CAUSE_COLORS[causeType]
  if (fixed !== undefined) return fixed
  const free = EXTRA_CAUSE_COLORS.find((color) => !taken.includes(color))
  return free ?? UNKNOWN_CAUSE_COLOR
}

/** 整张饼一次性配色：保证同一张图里没有两个同色扇形。 */
export function causeColors(data: StatsCauseCount[]): string[] {
  const taken: string[] = []
  return data.map((item) => {
    const color = causeColor(item.cause_type, taken)
    taken.push(color)
    return color
  })
}

/**
 * TOP10 柱色的图例：柱色是掌握度四档，光看 tooltip 数字看不出颜色含义，页面上必须有固定图例。
 * 顺序按「从薄弱到熟练，最后未评估」，与 masteryColor 的分档口径一致（共用 utils/masteryColor）。
 */
export function masteryLegendItems(): Array<{ label: string; color: string }> {
  return [
    { label: '<0.4', color: COLOR_LOW },
    { label: '0.4–0.7', color: COLOR_MID },
    { label: '≥0.7', color: COLOR_HIGH },
    { label: '未评估', color: COLOR_UNRATED },
  ]
}

export function summaryCards(summary: StatsSummary): { label: string; value: number }[] {
  return [
    { label: '错题总数', value: summary.total },
    { label: '待订正', value: summary.pending },
    { label: '已订正', value: summary.corrected },
    { label: '已掌握', value: summary.mastered },
  ]
}

export function causeOption(data: StatsCauseCount[]): Record<string, unknown> {
  const colors = causeColors(data)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条（{d}%）' },
    // 图例的色块必须与扇形同色，否则图例会骗人：显式给 legend.data 带 itemStyle
    legend: {
      bottom: 0,
      type: 'scroll',
      data: data.map((item, index) => ({
        name: item.cause_type,
        itemStyle: { color: colors[index] },
      })),
    },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        data: data.map((item, index) => ({
          name: item.cause_type,
          value: item.count,
          itemStyle: { color: colors[index] },
        })),
      },
    ],
  }
}

export function topKpOption(data: StatsTopKp[]): Record<string, unknown> {
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

export function trendOption(data: StatsTrendPoint[]): Record<string, unknown> {
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