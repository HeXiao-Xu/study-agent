<script setup lang="ts">
/**
 * 错题统计看板（S4-8）。
 *
 * 页面只负责请求、range 切换与三块画布的 setOption；数据到 option 的映射全在
 * useStatsCharts 的纯函数里（jsdom 测不到 canvas，但能测 option）。
 */
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchStatsOverview } from '@/api/stats'
import PageHeader from '@/components/common/PageHeader.vue'
import type { StatsOverview, StatsRange } from '@/types/stats'

import {
  causeOption,
  hasMastered,
  summaryCards,
  topKpOption,
  trendOption,
} from './useStatsCharts'

echarts.use([
  PieChart,
  BarChart,
  LineChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  CanvasRenderer,
])

const RANGE_OPTIONS: { value: StatsRange; label: string }[] = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
]

const range = ref<StatsRange>('30d')
const data = ref<StatsOverview | null>(null)
const loading = ref(false)
const error = ref('')

const causeCanvas = ref<HTMLDivElement | null>(null)
const topKpCanvas = ref<HTMLDivElement | null>(null)
const trendCanvas = ref<HTMLDivElement | null>(null)
let causeChart: echarts.ECharts | null = null
let topKpChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const cards = computed(() => (data.value === null ? [] : summaryCards(data.value.summary)))
const missingKp = computed(() => {
  const current = data.value
  if (current === null) return 0
  return Math.max(0, current.summary.total - current.summary.with_kp)
})
const causeEmpty = computed(() => data.value !== null && data.value.by_cause.length === 0)
const topKpEmpty = computed(() => data.value !== null && data.value.top_kps.length === 0)
const totallyEmpty = computed(() => data.value !== null && data.value.summary.total === 0)
const masteredAllZero = computed(() => data.value !== null && !hasMastered(data.value.trend))

/**
 * 把实例绑到"当前"画布节点上。
 *
 * range 切换时 loading 分支会把图表容器整棵重建（骨架屏），旧实例指向的 DOM 已被丢弃；
 * 只 setOption 不重绑，画布会一直是空的——这是真机验收时才暴露的问题。
 */
function bind(
  canvas: HTMLDivElement | null,
  instance: echarts.ECharts | null,
): echarts.ECharts | null {
  if (canvas === null) {
    instance?.dispose()
    return null
  }
  if (instance !== null && instance.getDom() === canvas) return instance
  instance?.dispose()
  return echarts.init(canvas)
}

function syncCharts(): void {
  causeChart = bind(causeCanvas.value, causeChart)
  topKpChart = bind(topKpCanvas.value, topKpChart)
  trendChart = bind(trendCanvas.value, trendChart)
}

function render(): void {
  const current = data.value
  if (current === null) return
  causeChart?.setOption(causeOption(current.by_cause), true)
  topKpChart?.setOption(topKpOption(current.top_kps), true)
  trendChart?.setOption(trendOption(current.trend), true)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchStatsOverview(range.value)
  } catch {
    error.value = '统计数据加载失败，请重试'
    data.value = null
  } finally {
    loading.value = false
  }
  // 骨架屏撤掉之后图表容器才存在，此时再绑实例
  await nextTick()
  syncCharts()
  render()
}

watch(range, load)

onMounted(async () => {
  await load()
})

onBeforeUnmount(() => {
  causeChart?.dispose()
  topKpChart?.dispose()
  trendChart?.dispose()
  causeChart = null
  topKpChart = null
  trendChart = null
})
</script>

<template>
  <div class="stats-page">
    <PageHeader
      title="统计"
      description="本人错题的窗口汇总：错因分布、知识点 TOP10（颜色=掌握度）与每日新增/累计已掌握。"
    />

    <div class="stats-toolbar">
      <el-radio-group v-model="range" size="small">
        <el-radio-button
          v-for="item in RANGE_OPTIONS"
          :key="item.value"
          :value="item.value"
          :data-testid="`range-${item.value}`"
        >
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>
      <span v-if="data !== null" class="stats-toolbar__range">
        {{ data.range.from }} ~ {{ data.range.to }}（UTC）
      </span>
    </div>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      data-testid="stats-error"
    />
    <el-skeleton v-if="loading" :rows="4" animated data-testid="stats-loading" />

    <template v-else-if="data !== null">
      <el-empty v-if="totallyEmpty" description="窗口内没有错题" data-testid="stats-empty" />

      <template v-else>
        <div class="stats-cards">
          <div v-for="card in cards" :key="card.label" class="stats-card">
            <div class="stats-card__value">{{ card.value }}</div>
            <div class="stats-card__label">{{ card.label }}</div>
          </div>
        </div>
        <p class="stats-note">
          {{ data.summary.total }} 条错题中 {{ data.summary.analyzed }} 条已诊断 ·
          {{ data.summary.with_kp }} 条挂知识点 · 掌握度
          {{ data.summary.mastery_rows }} 个知识点有记录
        </p>

        <div class="stats-grid">
          <section class="stats-panel">
            <h3>错因分布</h3>
            <p v-if="causeEmpty" class="stats-panel__empty">还没有错因诊断</p>
            <div ref="causeCanvas" class="stats-canvas" data-testid="cause-chart" />
          </section>

          <section class="stats-panel">
            <h3>知识点 TOP10</h3>
            <p v-if="topKpEmpty" class="stats-panel__empty">还没有错题挂上知识点</p>
            <div ref="topKpCanvas" class="stats-canvas" data-testid="top-kp-chart" />
            <p v-if="missingKp > 0" class="stats-panel__empty">
              其余 {{ missingKp }} 条错题没有关联知识点，所以不出现在图上
            </p>
          </section>

          <section class="stats-panel stats-panel--wide">
            <h3>每日新增错题与累计已掌握</h3>
            <div ref="trendCanvas" class="stats-canvas" data-testid="trend-chart" />
            <p v-if="masteredAllZero" class="stats-panel__empty">窗口内暂无已掌握错题</p>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.stats-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stats-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}
.stats-toolbar__range {
  font-size: 12px;
  color: #667085;
}
.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.stats-card {
  padding: 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.stats-card__value {
  font-size: 26px;
  font-weight: 600;
  color: #101828;
}
.stats-card__label {
  margin-top: 4px;
  font-size: 12px;
  color: #667085;
}
.stats-note {
  margin: 0;
  font-size: 12px;
  color: #667085;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.stats-panel {
  padding: 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.stats-panel--wide {
  grid-column: 1 / -1;
}
.stats-panel h3 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #344054;
}
.stats-panel__empty {
  margin: 8px 0 0;
  font-size: 12px;
  color: #98a2b3;
}
.stats-canvas {
  width: 100%;
  height: 260px;
}
</style>