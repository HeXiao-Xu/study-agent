<template>
  <div class="mindmap-page">
    <header class="page-head">
      <div>
        <h1>学习导图</h1>
        <p>把最近几天的笔记按知识点整理成思维导图，并附上可追溯的学习摘要。</p>
      </div>
      <div class="actions">
        <el-input-number v-model="days" :min="1" :max="30" size="default" />
        <el-button
          type="primary"
          :loading="creating"
          data-testid="generate"
          @click="start"
        >
          生成导图
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="error"
      class="status-alert"
      type="error"
      :closable="false"
      :title="error"
      data-testid="error"
    />

    <el-card v-if="task" class="status-card" shadow="never">
      <div class="status-line">
        <el-tag :type="statusType" data-testid="status">{{ statusLabel }}</el-tag>
        <span v-if="task.steps_count">已完成 {{ task.steps_count }} 步</span>
        <span v-if="task.token_cost">token：{{ task.token_cost }}</span>
      </div>

      <el-alert
        v-if="task.status === 'failed'"
        type="error"
        :closable="false"
        :title="task.error || '任务失败'"
        data-testid="failed"
      />
      <p v-if="task.status === 'pending' || task.status === 'running'" class="running">
        正在整理笔记并生成导图，请稍候…
      </p>
      <p v-else-if="task.status === 'waiting_confirm'" class="running">
        任务等待人工确认，请在任务详情中处理。
      </p>
    </el-card>

    <template v-if="result && task?.status === 'succeeded'">
      <el-card v-if="result.note_count === 0" shadow="never" data-testid="empty">
        <el-empty :description="result.summary_md" />
      </el-card>

      <template v-else>
        <el-alert
          v-if="result.degraded"
          class="status-alert"
          type="warning"
          :closable="false"
          title="LLM 聚类失败，已按知识点降级为结构树"
          data-testid="degraded"
        />

        <el-card class="summary-card" shadow="never">
          <template #header>
            <div class="card-head">
              <span>学习摘要</span>
              <span class="meta">
                {{ result.note_count }} 篇笔记 · {{ result.kp_count }} 个知识点
              </span>
            </div>
          </template>
          <pre class="summary" data-testid="summary">{{ result.summary_md }}</pre>
          <div v-if="result.citations.length" class="citations">
            <span class="citations-label">引用：</span>
            <el-tag
              v-for="citation in result.citations"
              :key="citation.note_id"
              class="citation"
              type="info"
              effect="plain"
            >
              笔记 #{{ citation.note_id }} {{ citation.note_title }}
            </el-tag>
          </div>
        </el-card>

        <el-card class="mindmap-card" shadow="never">
          <template #header>
            <div class="card-head">
              <span>思维导图</span>
              <el-button
                type="primary"
                plain
                :disabled="!svg"
                data-testid="export-png"
                @click="exportPng"
              >
                导出 PNG
              </el-button>
            </div>
          </template>
          <div
            v-if="svg"
            class="mermaid"
            data-testid="mindmap-svg"
            v-html="svg"
          />
          <div v-else-if="renderFailed" class="fallback" data-testid="fallback">
            <el-alert
              type="warning"
              :closable="false"
              title="导图渲染失败，已降级为结构树"
            />
            <pre>{{ result.fallback_text }}</pre>
          </div>
          <p v-else class="running">正在渲染导图…</p>
        </el-card>
      </template>
    </template>

    <el-empty
      v-else-if="!task && !creating"
      description="还没有导图任务：选好天数后点「生成导图」"
      data-testid="idle"
    />
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { createAgentTask, getAgentTask } from '@/api/agent'
import { asWeeklyMindmapResult, type AgentTaskDetail } from '@/types/agent'

import { downloadSvgAsPng, mindmapFileName } from './exportMindmap'
import { renderMermaid } from './mermaid'

const route = useRoute()
const router = useRouter()

const days = ref(7)
const task = ref<AgentTaskDetail | null>(null)
const svg = ref('')
const renderFailed = ref(false)
const creating = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

const taskId = computed<number | null>(() => {
  const raw = route.params.taskId
  const value = Array.isArray(raw) ? raw[0] : raw
  if (!value) return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const result = computed(() => asWeeklyMindmapResult(task.value?.result ?? null))

const statusLabel = computed(() => {
  const status = task.value?.status
  if (status === 'pending') return '排队中'
  if (status === 'running') return '生成中'
  if (status === 'succeeded') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'waiting_confirm') return '等待确认'
  return status || '未知'
})

const statusType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  if (task.value?.status === 'succeeded') return 'success'
  if (task.value?.status === 'failed') return 'danger'
  if (task.value?.status === 'waiting_confirm') return 'warning'
  return 'info'
})

function stopPolling(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

async function renderIfNeeded(): Promise<void> {
  svg.value = ''
  renderFailed.value = false
  const code = result.value?.mermaid
  if (!code) return
  try {
    svg.value = await renderMermaid(code)
  } catch {
    renderFailed.value = true
  }
}

async function load(id: number): Promise<void> {
  try {
    const data = await getAgentTask(id)
    task.value = data
    error.value = ''
    if (data.status === 'succeeded') {
      stopPolling()
      await renderIfNeeded()
      return
    }
    if (data.status === 'failed' || data.status === 'waiting_confirm') {
      stopPolling()
      return
    }
    stopPolling()
    timer = setTimeout(() => {
      void load(id)
    }, 1000)
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '加载任务失败'
    stopPolling()
  }
}

async function start(): Promise<void> {
  creating.value = true
  error.value = ''
  try {
    const created = await createAgentTask({
      task_type: 'weekly_mindmap',
      input: { days: days.value },
    })
    await router.replace({
      name: 'agent-mindmap',
      params: { taskId: String(created.id) },
    })
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '创建任务失败'
  } finally {
    creating.value = false
  }
}

async function exportPng(): Promise<void> {
  const id = taskId.value
  if (id === null || !svg.value) return
  const date = new Date().toISOString().slice(0, 10)
  try {
    await downloadSvgAsPng(svg.value, mindmapFileName(id, date))
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '导出失败')
  }
}

watch(
  taskId,
  (id) => {
    stopPolling()
    if (id === null) {
      task.value = null
      svg.value = ''
      renderFailed.value = false
      return
    }
    void load(id)
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.mindmap-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 4px 32px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.page-head h1 {
  margin: 0 0 6px;
  font-size: 22px;
}
.page-head p {
  margin: 0;
  color: #667085;
  font-size: 13px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.status-card,
.summary-card,
.mindmap-card {
  border: 1px solid #eaecf0;
}
.status-line {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #667085;
  font-size: 13px;
}
.status-alert {
  margin-bottom: 4px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}
.meta {
  color: #667085;
  font-size: 12px;
  font-weight: 400;
}
.summary {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.8;
  color: #344054;
}
.citations {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.citations-label {
  color: #667085;
  font-size: 12px;
}
.mermaid {
  overflow-x: auto;
  text-align: center;
}
.mermaid :deep(svg) {
  max-width: 100%;
  height: auto;
}
.fallback pre {
  margin: 12px 0 0;
  white-space: pre-wrap;
  font-family: inherit;
  color: #344054;
}
.running {
  color: #667085;
  font-size: 13px;
}
</style>