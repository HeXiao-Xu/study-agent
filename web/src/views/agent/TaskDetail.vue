<template>
  <div class="task-detail-page">
    <header class="page-head">
      <div class="head-left">
        <el-button link type="primary" data-testid="back" @click="back">← 返回任务列表</el-button>
        <h1>任务 #{{ taskId }}</h1>
        <el-tag v-if="task" :type="statusType(task.status)" data-testid="status">
          {{ statusLabel(task.status) }}
        </el-tag>
        <el-tag v-if="task" type="info" effect="plain">{{ typeLabel(task.task_type) }}</el-tag>
      </div>
      <div v-if="task" class="meta">
        <span>{{ task.steps_count ?? 0 }} 步</span>
        <span>token {{ task.token_cost ?? 0 }}</span>
        <span v-if="task.started_at">开始 {{ formatTime(task.started_at) }}</span>
        <span v-if="task.finished_at">结束 {{ formatTime(task.finished_at) }}</span>
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

    <el-card v-if="task?.status === 'waiting_confirm'" class="confirm-card" shadow="never">
      <div class="confirm-line">
        <div>
          <strong>等待人工确认</strong>
          <p>任务已生成中间产物；确认后继续，拒绝则任务失败。</p>
        </div>
        <div class="actions">
          <el-button type="success" data-testid="confirm-approve" @click="openConfirm(true)">
            通过
          </el-button>
          <el-button type="danger" plain data-testid="confirm-reject" @click="openConfirm(false)">
            拒绝
          </el-button>
        </div>
      </div>
    </el-card>

    <el-alert
      v-if="task?.status === 'failed'"
      class="status-alert"
      type="error"
      :closable="false"
      :title="task.error || '任务失败'"
      data-testid="failed"
    >
      <p class="suggestion">
        建议：展开下方红色错误步骤，查看工具入参与出参；修复后返回列表重新创建任务。
      </p>
      <p class="suggestion">重跑会清空旧步骤并从头执行。</p>
      <div class="actions">
        <el-button
          type="warning"
          :loading="retrying"
          data-testid="retry"
          @click="retryTask"
        >
          重跑任务
        </el-button>
        <el-button type="primary" @click="newMindmap">重新创建学习导图</el-button>
        <el-button @click="back">返回列表</el-button>
      </div>
    </el-alert>

    <el-card v-if="weekly" class="result-card" shadow="never" data-testid="weekly-result">
      <template #header>
        <div class="card-head">
          <span>学习摘要</span>
          <a class="link" :href="`/agent/mindmap/${taskId}`" data-testid="mindmap-link">
            查看学习导图 →
          </a>
        </div>
      </template>
      <el-alert
        v-if="weekly.degraded"
        type="warning"
        :closable="false"
        title="LLM 聚类失败，已按知识点降级为结构树"
        data-testid="degraded"
      />
      <pre class="summary" data-testid="summary">{{ weekly.summary_md }}</pre>
      <div class="citations">
        <span class="muted">引用：</span>
        <el-tag
          v-for="citation in weekly.citations"
          :key="citation.note_id"
          type="info"
          effect="plain"
        >
          笔记 #{{ citation.note_id }} {{ citation.note_title }}
        </el-tag>
        <span v-if="weekly.citations.length === 0" class="muted">无</span>
      </div>
    </el-card>

    <el-card v-else-if="task?.result" class="result-card" shadow="never">
      <template #header><span>任务结果</span></template>
      <pre class="summary" data-testid="result-json">{{ pretty(task.result) }}</pre>
    </el-card>

    <el-card class="timeline-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span>执行步骤</span>
          <span class="muted">{{ steps.length }} 条</span>
        </div>
      </template>
      <div ref="timelineRef">
        <transition-group v-if="steps.length" name="step" tag="ol" class="timeline">
          <li
            v-for="step in steps"
            :key="step.step_no"
            :data-testid="'step-row'"
            :class="['step', step.status === 'error' ? 'step-error' : '']"
          >
            <div class="step-head">
              <span class="step-no">#{{ step.step_no }}</span>
              <el-tag size="small" :type="stepTag(step.status)">{{ step.status }}</el-tag>
              <el-tag v-if="step.tool_name" size="small" effect="plain">
                {{ step.tool_name }}
              </el-tag>
              <span v-if="step.latency_ms !== null" class="muted">
                {{ step.latency_ms }} ms
              </span>
            </div>
            <p class="thought">{{ step.thought || '—' }}</p>
            <details
              v-if="step.tool_input || step.tool_output"
              :open="step.status === 'error'"
              data-testid="step-io"
            >
              <summary>工具入参 / 出参</summary>
              <pre v-if="step.tool_input">入参：{{ pretty(step.tool_input) }}</pre>
              <pre v-if="step.tool_output">出参：{{ pretty(step.tool_output) }}</pre>
            </details>
          </li>
        </transition-group>
        <el-empty v-else description="任务尚未开始" data-testid="steps-empty" />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="人工确认" width="420px">
      <p>{{ approved ? '确认通过后任务将继续执行。' : '拒绝后任务会结束并标记失败。' }}</p>
      <el-input
        v-model="comment"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        placeholder="备注（可选）"
        data-testid="confirm-comment"
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          :type="approved ? 'success' : 'danger'"
          :loading="submitting"
          data-testid="confirm-submit"
          @click="submitConfirm"
        >
          {{ approved ? '确认通过' : '确认拒绝' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { confirmAgentTask, getAgentTask, retryAgentTask } from '@/api/agent'
import {
  asWeeklyMindmapResult,
  type AgentStep,
  type AgentTaskDetail,
} from '@/types/agent'

import { statusLabel, statusType } from './status'

const route = useRoute()
const router = useRouter()

const task = ref<AgentTaskDetail | null>(null)
const loading = ref(false)
const error = ref('')
const dialogVisible = ref(false)
const approved = ref(true)
const comment = ref('')
const submitting = ref(false)
const retrying = ref(false)
const timelineRef = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const taskId = computed<number>(() => Number(route.params.id))
const steps = computed<AgentStep[]>(() => task.value?.steps ?? [])
const weekly = computed(() => asWeeklyMindmapResult(task.value?.result ?? null))

const TYPE_LABELS: Record<string, string> = {
  demo: '演示任务',
  weekly_mindmap: '学习导图',
}

function typeLabel(value: string): string {
  return TYPE_LABELS[value] ?? value
}

function stepTag(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ok') return 'success'
  if (status === 'waiting_confirm') return 'warning'
  if (status === 'error') return 'danger'
  return 'info'
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function pretty(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? String(value)
  return text.length > 4000 ? `${text.slice(0, 4000)}\n…（已截断）` : text
}

function stopPolling(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function isNearBottom(): boolean {
  const doc = document.documentElement
  return window.innerHeight + window.scrollY >= doc.scrollHeight - 120
}

async function scrollLatest(): Promise<void> {
  if (!task.value) return
  if (task.value.status !== 'running' || !isNearBottom()) return
  await nextTick()
  const last = timelineRef.value?.lastElementChild as HTMLElement | null
  last?.scrollIntoView?.({ block: 'nearest' })
}

async function load(): Promise<void> {
  stopPolling()
  const id = taskId.value
  if (!Number.isInteger(id) || id <= 0) {
    error.value = '任务 ID 不合法'
    return
  }
  loading.value = true
  try {
    const data = await getAgentTask(id)
    task.value = data
    error.value = ''
    if (data.status === 'pending' || data.status === 'running') {
      await scrollLatest()
      timer = setTimeout(() => {
        void load()
      }, 1000)
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '加载任务失败'
  } finally {
    loading.value = false
  }
}

function openConfirm(value: boolean): void {
  approved.value = value
  comment.value = ''
  dialogVisible.value = true
}

async function submitConfirm(): Promise<void> {
  submitting.value = true
  try {
    await confirmAgentTask(taskId.value, {
      approved: approved.value,
      comment: comment.value || null,
    })
    dialogVisible.value = false
    await load()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '确认失败'
  } finally {
    submitting.value = false
  }
}

async function retryTask(): Promise<void> {
  retrying.value = true
  try {
    await retryAgentTask(taskId.value)
    await load()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '重跑失败'
  } finally {
    retrying.value = false
  }
}

function back(): void {
  void router.push('/agent/tasks')
}

function newMindmap(): void {
  void router.push('/agent/mindmap')
}

watch(
  taskId,
  () => {
    task.value = null
    void load()
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.task-detail-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 8px 4px 24px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-left h1 {
  margin: 0;
  font-size: 22px;
}
.meta {
  display: flex;
  gap: 14px;
  color: #667085;
  font-size: 12px;
}
.confirm-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.confirm-line p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 13px;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
.status-alert {
  margin-bottom: 2px;
}
.suggestion {
  margin: 6px 0 0;
  font-size: 13px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}
.summary {
  margin: 12px 0 0;
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
  gap: 8px;
  align-items: center;
}
.muted {
  color: #667085;
  font-size: 12px;
}
.link {
  color: #175cd3;
  font-size: 13px;
  text-decoration: none;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0 0 0 8px;
  border-left: 2px solid #eaecf0;
}
.step {
  position: relative;
  padding: 0 0 18px 18px;
  transition:
    opacity 0.25s ease,
    transform 0.25s ease;
}
.step::before {
  content: '';
  position: absolute;
  left: -7px;
  top: 4px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #12b76a;
  border: 2px solid #fff;
}
.step-error::before {
  background: #f04438;
}
.step-error {
  background: #fef3f2;
  border-radius: 8px;
  padding: 8px 12px 12px 18px;
  margin-left: -2px;
}
.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-no {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  color: #667085;
  font-size: 12px;
}
.thought {
  margin: 6px 0;
  color: #344054;
  white-space: pre-wrap;
  word-break: break-word;
}
details {
  margin-top: 4px;
}
details summary {
  cursor: pointer;
  color: #175cd3;
  font-size: 13px;
}
details pre {
  margin: 8px 0 0;
  padding: 10px;
  background: #f9fafb;
  border: 1px solid #eaecf0;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  color: #475467;
}
.step-enter-from,
.step-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>