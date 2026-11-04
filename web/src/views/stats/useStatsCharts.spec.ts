import { describe, expect, it } from 'vitest'

import { masteryColor } from '@/utils/masteryColor'
import type { StatsCauseCount, StatsSummary, StatsTopKp, StatsTrendPoint } from '@/types/stats'

import {
  UNKNOWN_CAUSE_COLOR,
  causeOption,
  hasMastered,
  masteryLegendItems,
  summaryCards,
  topKpOption,
  trendOption,
} from './useStatsCharts'

const summary: StatsSummary = {
  total: 34,
  pending: 33,
  corrected: 1,
  mastered: 0,
  analyzed: 34,
  with_kp: 3,
  mastery_rows: 5,
}

describe('summaryCards', () => {
  it('四张卡按固定顺序', () => {
    expect(summaryCards(summary)).toEqual([
      { label: '错题总数', value: 34 },
      { label: '待订正', value: 33 },
      { label: '已订正', value: 1 },
      { label: '已掌握', value: 0 },
    ])
  })
})

describe('causeOption', () => {
  const data: StatsCauseCount[] = [
    { cause_type: '概念不清', count: 11 },
    { cause_type: 'unknown', count: 1 },
  ]

  it('把错因映射成饼图数据，unknown 用灰', () => {
    const option = causeOption(data) as {
      series: Array<{
        data: Array<{ name: string; value: number; itemStyle: { color: string } }>
      }>
    }
    expect(option.series[0].data.map((item) => [item.name, item.value])).toEqual([
      ['概念不清', 11],
      ['unknown', 1],
    ])
    expect(option.series[0].data[1].itemStyle.color).toBe(UNKNOWN_CAUSE_COLOR)
    expect(option.series[0].data[0].itemStyle.color).not.toBe(UNKNOWN_CAUSE_COLOR)
  })

  it('同名错因换顺序也拿到同一个颜色', () => {
    const first = causeOption(data) as {
      series: Array<{ data: Array<{ itemStyle: { color: string } }> }>
    }
    const reordered = causeOption([...data].reverse()) as {
      series: Array<{ data: Array<{ itemStyle: { color: string } }> }>
    }
    expect(reordered.series[0].data[1].itemStyle.color).toBe(
      first.series[0].data[0].itemStyle.color,
    )
  })

  it('六种已知错因两两不同色（哈希撞色是一次真实缺陷）', () => {
    const real: StatsCauseCount[] = [
      { cause_type: '概念不清', count: 11 },
      { cause_type: '计算失误', count: 6 },
      { cause_type: '知识遗忘', count: 5 },
      { cause_type: '方法不当', count: 4 },
      { cause_type: '时间不足', count: 4 },
      { cause_type: '审题偏差', count: 3 },
      { cause_type: 'unknown', count: 1 },
    ]
    const option = causeOption(real) as {
      series: Array<{ data: Array<{ name: string; itemStyle: { color: string } }> }>
    }
    const colors = option.series[0].data.map((item) => item.itemStyle.color)
    expect(new Set(colors).size).toBe(colors.length)
    expect(colors).toHaveLength(7)
  })

  it('图例色块与扇形同色（否则图例会骗人）', () => {
    const option = causeOption(data) as {
      legend: { data: Array<{ name: string; itemStyle: { color: string } }> }
      series: Array<{ data: Array<{ name: string; itemStyle: { color: string } }> }>
    }
    const slices = new Map(option.series[0].data.map((item) => [item.name, item.itemStyle.color]))
    expect(option.legend.data).toHaveLength(2)
    for (const entry of option.legend.data) {
      expect(entry.itemStyle.color).toBe(slices.get(entry.name))
    }
  })

  it('没见过的错因也拿到不撞色的颜色', () => {
    const weird: StatsCauseCount[] = [
      { cause_type: '概念不清', count: 2 },
      { cause_type: '新错因甲', count: 1 },
      { cause_type: '新错因乙', count: 1 },
    ]
    const option = causeOption(weird) as {
      series: Array<{ data: Array<{ itemStyle: { color: string } }> }>
    }
    const colors = option.series[0].data.map((item) => item.itemStyle.color)
    expect(new Set(colors).size).toBe(3)
  })

  it('空数组给出空数据而不是占位假数据', () => {
    const option = causeOption([]) as { series: Array<{ data: unknown[] }> }
    expect(option.series[0].data).toEqual([])
  })
})

describe('topKpOption', () => {
  it('按掌握度四档着色，null 走未评估灰', () => {
    const data: StatsTopKp[] = [
      { kp_id: 1, kp_name: '低', count: 2, mastery: 0.2 },
      { kp_id: 2, kp_name: '中', count: 1, mastery: 0.5 },
      { kp_id: 3, kp_name: '高', count: 1, mastery: 0.9 },
      { kp_id: 4, kp_name: '无', count: 1, mastery: null },
    ]
    const option = topKpOption(data) as {
      yAxis: { data: string[] }
      series: Array<{ data: Array<{ value: number; itemStyle: { color: string } }> }>
    }
    expect(option.yAxis.data).toEqual(['低', '中', '高', '无'])
    expect(option.series[0].data.map((item) => item.value)).toEqual([2, 1, 1, 1])
    expect(option.series[0].data.map((item) => item.itemStyle.color)).toEqual([
      '#e5484d',
      '#f0b429',
      '#22c55e',
      '#9aa4b2',
    ])
  })

  it('空数组不崩', () => {
    const option = topKpOption([]) as { yAxis: { data: string[] } }
    expect(option.yAxis.data).toEqual([])
  })
})

describe('trendOption', () => {
  const data: StatsTrendPoint[] = [
    { date: '2026-11-02', new_mistakes: 34, mastered: 0 },
    { date: '2026-11-03', new_mistakes: 0, mastered: 0 },
  ]

  it('补零后的数据直接成折线，日期只显示 MM-DD', () => {
    const option = trendOption(data) as {
      xAxis: { data: string[] }
      series: Array<{ name: string; data: number[] }>
    }
    expect(option.xAxis.data).toEqual(['11-02', '11-03'])
    expect(option.series[0]).toMatchObject({ data: [34, 0] })
  })

  it('已掌握全 0 时不画第二条线', () => {
    expect(hasMastered(data)).toBe(false)
    const option = trendOption(data) as { series: Array<{ name: string }> }
    expect(option.series).toHaveLength(1)
  })

  it('有已掌握时画累计线', () => {
    const withMastered: StatsTrendPoint[] = [
      { date: '2026-11-02', new_mistakes: 1, mastered: 2 },
    ]
    expect(hasMastered(withMastered)).toBe(true)
    const option = trendOption(withMastered) as { series: Array<{ name: string }> }
    expect(option.series).toHaveLength(2)
  })

  it('空数组不崩', () => {
    const option = trendOption([]) as { xAxis: { data: string[] } }
    expect(option.xAxis.data).toEqual([])
  })
})

describe('masteryLegendItems', () => {
  it('四档颜色图例：薄弱/一般/熟练/未评估', () => {
    expect(masteryLegendItems()).toEqual([
      { label: '<0.4', color: '#e5484d' },
      { label: '0.4–0.7', color: '#f0b429' },
      { label: '≥0.7', color: '#22c55e' },
      { label: '未评估', color: '#9aa4b2' },
    ])
  })

  it('颜色与 masteryColor 的分档一致', () => {
    const byLabel = new Map(masteryLegendItems().map((item) => [item.label, item.color]))
    expect(byLabel.get('<0.4')).toBe(masteryColor(0.39))
    expect(byLabel.get('0.4–0.7')).toBe(masteryColor(0.4))
    expect(byLabel.get('≥0.7')).toBe(masteryColor(0.7))
    expect(byLabel.get('未评估')).toBe(masteryColor(null))
  })
})
