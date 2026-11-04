<script setup lang="ts">
/**
 * 图谱可视化页（S4-6）。
 *
 * 画布只负责渲染：可见集合与 option 全在 useGraphData 的纯函数里，
 * 页面这一层只管请求、抽屉与工具栏状态。
 */
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchGraphNode, fetchGraphSnapshot } from '@/api/graph'
import { listSubjects } from '@/api/kp'
import PageHeader from '@/components/common/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import type { GraphNodeDetail, GraphRelation, GraphSnapshot } from '@/types/graph'
import type { SubjectOut } from '@/types/kp'

import {
  DEGRADE_THRESHOLD,
  buildOption,
  chapterOf,
  chapterOptions,
  matchNodes,
  selectVisible,
} from './useGraphData'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const RELATION_LABELS: Array<{ value: GraphRelation; label: string }> = [
  { value: 'contains', label: '结构（章→节）' },
  { value: 'prerequisite', label: '前置' },
  { value: 'related', label: '相关' },
  { value: 'confusable', label: '易混' },
]

const auth = useAuthStore()
const router = useRouter()
const canReview = computed(() => ['admin', 'teacher'].includes(auth.user?.role ?? ''))

const canvas = ref<HTMLDivElement | null>(null)
const snapshotData = ref<GraphSnapshot | null>(null)
const subjects = ref<SubjectOut[]>([])
const subjectId = ref<number | null>(null)
const loading = ref(false)
const error = ref('')
const relations = ref<GraphRelation[]>(['prerequisite', 'related', 'confusable'])
const activeChapters = ref<number[] | null>(null)
const keyword = ref('')
const selectedId = ref<number | null>(null)
const showAllOverride = ref(false)
const drawerOpen = ref(false)
const detail = ref<GraphNodeDetail | null>(null)
const detailLoading = ref(false)

let chart: echarts.ECharts | null = null

const visible = computed(() => {
  if (snapshotData.value === null) {
    return { nodes: [], edges: [], degraded: false }
  }
  return selectVisible(snapshotData.value, {
    relations: relations.value,
    activeChapters: activeChapters.value === null ? null : new Set(activeChapters.value),
    focusId: selectedId.value,
    threshold: showAllOverride.value ? Number.MAX_SAFE_INTEGER : DEGRADE_THRESHOLD,
  })
})

const chapters = computed(() =>
  snapshotData.value === null ? [] : chapterOptions(snapshotData.value.nodes),
)
const searchResults = computed(() =>
  snapshotData.value === null ? [] : matchNodes(snapshotData.value.nodes, keyword.value),
)
const pendingEdges = computed(() => snapshotData.value?.stats.pending_edges ?? 0)

function render(): void {
  if (chart === null) return
  chart.setOption(buildOption(visible.value.nodes, visible.value.edges, selectedId.value), {
    notMerge: true,
  })
}

function findIndex(kpId: number): number {
  return visible.value.nodes.findIndex((node) => node.id === kpId)
}

function highlightById(kpId: number): void {
  const index = findIndex(kpId)
  if (chart === null || index < 0) return
  chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: index })
  chart.dispatchAction({ type: 'select', seriesIndex: 0, dataIndex: index })
}

async function loadSubjects(): Promise<void> {
  try {
    subjects.value = await listSubjects()
    if (subjectId.value === null) {
      subjectId.value = subjects.value[0]?.id ?? null
    }
  } catch {
    error.value = '学科加载失败，请重试'
  }
}

async function loadSnapshot(): Promise<void> {
  if (subjectId.value === null) return
  loading.value = true
  error.value = ''
  try {
    snapshotData.value = await fetchGraphSnapshot(subjectId.value)
    activeChapters.value = null
    showAllOverride.value = false
    render()
  } catch {
    error.value = '图谱加载失败，请重试'
  } finally {
    loading.value = false
  }
}

async function openDetail(kpId: number): Promise<void> {
  selectedId.value = kpId
  drawerOpen.value = true
  detailLoading.value = true
  detail.value = null
  // 等 visible 重算 + setOption 生效后再高亮，否则 dataIndex 是旧的
  await nextTick()
  highlightById(kpId)
  try {
    detail.value = await fetchGraphNode(kpId)
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function onPickSearch(kpId: number): void {
  const current = snapshotData.value
  if (current !== null && activeChapters.value !== null) {
    const nodesById = new Map(current.nodes.map((node) => [node.id, node]))
    const chapter = chapterOf(kpId, nodesById)
    if (!activeChapters.value.includes(chapter)) {
      activeChapters.value = [...activeChapters.value, chapter]
    }
  }
  void openDetail(kpId)
}

function onLegendChange(): void {
  render()
}

watch(visible, render)

onMounted(async () => {
  await loadSubjects()
  await loadSnapshot()
  if (canvas.value !== null) {
    chart = echarts.init(canvas.value)
    chart.on('click', (params) => {
      if (params.dataType !== 'node') return
      const kpId = (params.data as { id?: string } | undefined)?.id
      if (kpId === undefined) return
      void openDetail(Number(kpId))
    })
    render()
  }
})

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="graph-page">
    <PageHeader
      title="图谱"
      description="力导向知识图谱：节点大小=考纲权重，颜色=我的掌握度（灰=未评估，红<0.4，黄 0.4–0.7，绿≥0.7）。"
    />

    <div class="graph-toolbar">
      <el-select
        v-model="subjectId"
        placeholder="学科"
        style="width: 140px"
        @change="loadSnapshot"
      >
        <el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select
        v-model="activeChapters"
        multiple
        collapse-tags
        clearable
        placeholder="全部模块"
        style="min-width: 220px"
        @change="onLegendChange"
      >
        <el-option
          v-for="item in chapters"
          :key="item.id"
          :label="item.name"
          :value="item.id"
        />
      </el-select>
      <el-checkbox-group v-model="relations" @change="onLegendChange">
        <el-checkbox v-for="item in RELATION_LABELS" :key="item.value" :value="item.value">
          {{ item.label }}
        </el-checkbox>
      </el-checkbox-group>
      <el-select
        v-model="keyword"
        filterable
        remote
        clearable
        :remote-method="() => undefined"
        placeholder="搜索知识点"
        style="width: 200px"
      >
        <el-option
          v-for="item in searchResults"
          :key="item.id"
          :label="item.name"
          :value="item.name"
          @click="onPickSearch(item.id)"
        />
      </el-select>
      <el-button :loading="loading" @click="loadSnapshot">刷新</el-button>
      <el-link
        v-if="canReview && pendingEdges > 0"
        type="warning"
        data-testid="pending-hint"
        @click="router.push('/knowledge')"
      >
        还有 {{ pendingEdges }} 条待校验
      </el-link>
    </div>

    <el-alert
      v-if="visible.degraded"
      type="warning"
      :closable="false"
      show-icon
      data-testid="degrade-alert"
    >
      <template #title>节点过多，已降级为子图模式（只显示焦点与一跳邻居）</template>
      <el-button size="small" @click="showAllOverride = true">显示全部（可能卡顿）</el-button>
    </el-alert>

    <el-alert v-if="error" type="error" :closable="false" :title="error" />

    <div ref="canvas" class="graph-canvas" data-testid="graph-canvas" />

    <el-drawer v-model="drawerOpen" size="420px" :title="detail?.name ?? '知识点详情'">
      <div v-loading="detailLoading" class="graph-detail">
        <template v-if="detail !== null">
          <p class="graph-detail__path">{{ detail.path.join(' / ') }}</p>
          <p>
            考纲权重：{{ detail.exam_weight ?? '—' }} · 层级 L{{ detail.level }} · 我的错题：{{
              detail.mistake_count
            }}
            条
          </p>

          <h4>描述</h4>
          <p v-if="detail.description">{{ detail.description }}</p>
          <p v-else class="graph-detail__empty">暂无描述</p>

          <template
            v-for="group in [
              { title: '前置', items: detail.prerequisites },
              { title: '后继', items: detail.successors },
              { title: '相关', items: detail.related },
              { title: '易混', items: detail.confusable },
            ]"
            :key="group.title"
          >
            <h4>{{ group.title }}</h4>
            <p v-if="group.items.length === 0" class="graph-detail__empty">暂无</p>
            <ul v-else class="graph-detail__list">
              <li v-for="item in group.items" :key="item.kp_id">
                <el-link type="primary" @click="openDetail(item.kp_id)">
                  {{ item.name }}
                </el-link>
              </li>
            </ul>
          </template>

          <h4>关联笔记</h4>
          <p v-if="detail.notes.length === 0" class="graph-detail__empty">暂无关联笔记</p>
          <ul v-else class="graph-detail__list">
            <li v-for="note in detail.notes" :key="note.id">
              <el-link type="primary" @click="router.push(`/notes/${note.id}`)">
                {{ note.title }}
              </el-link>
            </li>
          </ul>

          <h4>我的错题</h4>
          <p v-if="detail.mistakes.length === 0" class="graph-detail__empty">暂无错题</p>
          <ul v-else class="graph-detail__list">
            <li v-for="mistake in detail.mistakes" :key="mistake.id">
              <el-link type="primary" @click="router.push(`/mistakes/${mistake.id}`)">
                #{{ mistake.id }} · {{ mistake.status }}
              </el-link>
              <span class="graph-detail__stem">{{ mistake.stem }}</span>
            </li>
          </ul>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.graph-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.graph-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.graph-canvas {
  height: calc(100vh - 260px);
  min-height: 480px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fbfcfe;
}
.graph-detail__path {
  color: #6b7280;
  font-size: 12px;
}
.graph-detail__empty {
  color: #9ca3af;
}
.graph-detail__list {
  padding-left: 18px;
}
.graph-detail__stem {
  margin-left: 8px;
  color: #6b7280;
  font-size: 12px;
}
</style>