<script setup lang="ts">
/**
 * S5-7 学习报告：雷达/热力是当前快照，趋势随 range 重算。
 * 周报必须手动触发；导出只合成三张图，不含周报正文。
 */
import { LineChart, RadarChart, TreemapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { MdPreview } from 'md-editor-v3'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  fetchReportOverview,
  fetchWeeklyReport,
  generateWeeklyReport,
} from '@/api/reports'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { ReportOverview, ReportRange, WeeklyReport } from '@/types/reports'

import {
  downloadReportImage,
  type ReportImageBlock,
} from './exportReportImage'
import {
  hasAssessed,
  pageSummary,
  radarOption,
  treemapOption,
  trendOption,
} from './useReportCharts'

import 'katex/dist/katex.min.css'
import 'md-editor-v3/lib/preview.css'

echarts.use([
  RadarChart,
  TreemapChart,
  LineChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  CanvasRenderer,
])

const RANGE_OPTIONS: Array<{ value: ReportRange; label: string }> = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
]

const range = ref<ReportRange>('30d')
const data = ref<ReportOverview | null>(null)
const loading = ref(true)
const error = ref('')
const subjectIndex = ref(0)
const weekly = ref<WeeklyReport | null>(null)
const weeklyLoading = ref(false)
const weeklyError = ref('')
const weeklyButtonLabel = computed(() =>
  weekly.value === null ? '生成周报' : '重新生成周报',
)
const exporting = ref(false)
const chartsReady = ref(false)

const radarCanvas = ref<HTMLDivElement | null>(null)
const treemapCanvas = ref<HTMLDivElement | null>(null)
const trendCanvas = ref<HTMLDivElement | null>(null)
let radarChart: echarts.ECharts | null = null
let treemapChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const subjects = computed(() => data.value?.subjects ?? [])
const activeSubject = computed(() => subjects.value[subjectIndex.value] ?? null)
const cards = computed(() => (data.value === null ? [] : pageSummary(data.value.trend)))
const noSubjects = computed(() => data.value !== null && subjects.value.length === 0)
const radarEmpty = computed(
  () => activeSubject.value !== null && !hasAssessed(activeSubject.value),
)
const treemapEmpty = computed(() => (activeSubject.value?.heatmap.length ?? 0) === 0)
const exportDisabled = computed(
  () =>
    data.value === null ||
    activeSubject.value === null ||
    radarEmpty.value ||
    treemapEmpty.value ||
    loading.value ||
    !chartsReady.value,
)

function bind(
  element: HTMLDivElement | null,
  chart: echarts.ECharts | null,
): echarts.ECharts | null {
  if (element === null) {
    chart?.dispose()
    return null
  }
  if (chart !== null && chart.getDom() === element) return chart
  chart?.dispose()
  return echarts.init(element)
}

function syncCharts(): void {
  radarChart = bind(radarCanvas.value, radarChart)
  treemapChart = bind(treemapCanvas.value, treemapChart)
  trendChart = bind(trendCanvas.value, trendChart)
  chartsReady.value =
    radarChart !== null && treemapChart !== null && trendChart !== null
}

function render(): void {
  const subject = activeSubject.value
  const current = data.value
  if (subject !== null && hasAssessed(subject)) {
    radarChart?.setOption(radarOption(subject), true)
  }
  if (subject !== null && subject.heatmap.length > 0) {
    treemapChart?.setOption(treemapOption(subject.heatmap), true)
  }
  if (current !== null) {
    trendChart?.setOption(trendOption(current.trend), true)
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchReportOverview(range.value)
    subjectIndex.value = 0
  } catch {
    data.value = null
    error.value = '报告加载失败，请重试'
  } finally {
    loading.value = false
  }
  await nextTick()
  syncCharts()
  render()
}

watch(range, load)
watch(subjectIndex, async () => {
  await nextTick()
  render()
})

async function loadWeeklyCache(): Promise<void> {
  weeklyLoading.value = true
  try {
    weekly.value = await fetchWeeklyReport()
  } catch {
    weekly.value = null
  } finally {
    weeklyLoading.value = false
  }
}

async function onWeekly(): Promise<void> {
  if (weeklyLoading.value) return
  weeklyLoading.value = true
  weeklyError.value = ''
  try {
    weekly.value = await generateWeeklyReport()
  } catch {
    weeklyError.value = '周报生成失败，请稍后重试'
  } finally {
    weeklyLoading.value = false
  }
}

function chartSource(
  chart: echarts.ECharts | null,
  element: HTMLDivElement | null,
): ReportImageBlock | null {
  if (chart === null || element === null || element.clientWidth <= 0 || element.clientHeight <= 0) {
    return null
  }
  return {
    dataUrl: chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }),
    width: element.clientWidth,
    height: element.clientHeight,
  }
}

async function onExport(): Promise<void> {
  const subject = activeSubject.value
  const current = data.value
  if (subject === null || current === null || exportDisabled.value) return
  const radar = chartSource(radarChart, radarCanvas.value)
  const treemap = chartSource(treemapChart, treemapCanvas.value)
  const trend = chartSource(trendChart, trendCanvas.value)
  if (radar === null || treemap === null || trend === null) {
    ElMessage.warning('图表尚未准备好，请稍后再试')
    return
  }
  exporting.value = true
  try {
    await downloadReportImage({
      range: current.range.key,
      subjectName: subject.subject_name,
      from: current.range.from,
      to: current.range.to,
      blocks: [radar, treemap, trend],
    })
  } catch {
    ElMessage.error('导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  void load()
  void loadWeeklyCache()
})

onBeforeUnmount(() => {
  radarChart?.dispose()
  treemapChart?.dispose()
  trendChart?.dispose()
  radarChart = null
  treemapChart = null
  trendChart = null
  chartsReady.value = false
})
</script>

<template>
  <div class="reports-page">
    <PageHeader
      title="学习报告"
      description="模块雷达、知识点热力与趋势；range 只影响趋势，掌握度是当前快照。"
    >
      <template #actions>
        <el-button
          :disabled="exportDisabled || exporting"
          :loading="exporting"
          data-testid="report-export"
          @click="onExport"
        >
          导出图表 PNG
        </el-button>
      </template>
    </PageHeader>

    <div class="reports-toolbar">
      <el-radio-group v-model="range" size="small">
        <el-radio-button
          v-for="item in RANGE_OPTIONS"
          :key="item.value"
          :value="item.value"
          :data-testid="`report-range-${item.value}`"
        >
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>
      <span v-if="data">{{ data.range.from }} ~ {{ data.range.to }}（UTC）</span>
    </div>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      data-testid="report-error"
    />
    <el-skeleton v-if="loading" :rows="5" animated data-testid="report-loading" />

    <EmptyState
      v-else-if="noSubjects"
      title="暂无知识库数据"
      description="先导入知识点与笔记，再来看学习报告。"
    />

    <template v-else-if="data">
      <section class="report-cards">
        <div v-for="card in cards" :key="card.label" class="report-card">
          <strong>{{ card.value }}</strong><span>{{ card.label }}</span>
        </div>
      </section>

      <el-radio-group
        v-if="subjects.length > 1"
        v-model="subjectIndex"
        size="small"
        class="subject-tabs"
      >
        <el-radio-button
          v-for="(subject, index) in subjects"
          :key="subject.subject_id"
          :value="index"
        >
          {{ subject.subject_name }}
        </el-radio-button>
      </el-radio-group>

      <div class="report-grid">
        <section class="report-panel">
          <h3>模块雷达</h3>
          <p v-if="radarEmpty" class="report-empty">
            暂无已评估模块；未评估模块不纳入雷达。
          </p>
          <div ref="radarCanvas" class="report-canvas" data-testid="report-radar" />
        </section>
        <section class="report-panel">
          <h3>知识点热力</h3>
          <p v-if="treemapEmpty" class="report-empty">暂无知识点。</p>
          <div ref="treemapCanvas" class="report-canvas" data-testid="report-treemap" />
        </section>
        <section class="report-panel report-panel--wide">
          <h3>近期趋势</h3>
          <p class="report-empty">日界为 UTC；复习完成数只反映当前 done_at 快照。</p>
          <div ref="trendCanvas" class="report-canvas" data-testid="report-trend" />
        </section>
      </div>

      <section class="weekly-panel">
        <div class="weekly-head">
          <h3>本周周报</h3>
          <el-button
            type="primary"
            :loading="weeklyLoading"
            data-testid="weekly-generate"
            @click="onWeekly"
          >
            {{ weeklyButtonLabel }}
          </el-button>
        </div>
        <p class="weekly-hint">
          页面会读取当天已生成的周报；只有生成/重新生成才调用真实 LLM，约需数秒。
        </p>
        <el-alert
          v-if="weeklyError"
          type="error"
          :closable="false"
          :title="weeklyError"
          data-testid="weekly-error"
        />
        <div v-if="weekly" data-testid="weekly-report">
          <p>
            {{ weekly.period.from }} ~ {{ weekly.period.to }} ·
            {{ weekly.generated_by === 'empty' ? '空数据' : 'LLM 生成' }} ·
            校验 {{ weekly.validation.attempts }} 次
          </p>
          <MdPreview :model-value="weekly.report_md" :no-mermaid="true" preview-theme="github" />
          <p>
            检查数字 {{ weekly.validation.checked_numbers.length }} 个，非法
            {{ weekly.validation.invalid_numbers.length }} 个。
          </p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.reports-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.reports-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.report-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}
.report-card {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
.report-card strong {
  color: var(--app-text);
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}
.report-card span {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.report-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.report-panel {
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
.report-panel--wide {
  grid-column: 1 / -1;
}
.report-panel h3 {
  margin: 0 0 8px;
  font-size: 14px;
}
.report-empty {
  margin: 0 0 8px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
.report-canvas {
  width: 100%;
  height: 280px;
}
.weekly-panel {
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
.weekly-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.weekly-head h3 {
  margin: 0;
  font-size: 14px;
}
.weekly-hint {
  margin: 6px 0 12px;
  color: var(--app-text-secondary);
  font-size: 12px;
}
</style>