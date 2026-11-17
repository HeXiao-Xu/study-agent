<template>
  <div class="task-list-page">
    <header class="page-head">
      <div>
        <h1>Agent 任务</h1>
        <p>查看多步任务的执行状态与步骤日志；学习导图任务会展示导图与摘要。</p>
      </div>
      <div class="head-actions">
        <el-button data-testid="refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" data-testid="new-mindmap" @click="newMindmap">
          生成学习导图
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

    <div class="filters">
      <el-select v-model="status" placeholder="全部状态" clearable data-testid="status-filter">
        <el-option label="排队中" value="pending" />
        <el-option label="生成中" value="running" />
        <el-option label="等待确认" value="waiting_confirm" />
        <el-option label="已完成" value="succeeded" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="taskType" placeholder="全部类型" clearable data-testid="type-filter">
        <el-option label="学习导图" value="weekly_mindmap" />
        <el-option label="演示任务" value="demo" />
      </el-select>
      <el-button type="primary" plain data-testid="search" @click="search">查询</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="items"
      class="task-table"
      data-testid="task-table"
      @row-click="open"
    >
      <el-table-column label="ID" width="90">
        <template #default="{ row }">
          <span
            class="mono task-id"
            :data-testid="`task-row-${row.id}`"
            @click.stop="open(row)"
          >
            #{{ row.id }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">{{ typeLabel(row.task_type) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="步骤" width="80">
        <template #default="{ row }">{{ row.steps_count ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="token" width="90">
        <template #default="{ row }">{{ row.token_cost ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="150">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="结束时间" min-width="150">
        <template #default="{ row }">{{ formatTime(row.finished_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="open(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty
      v-if="!loading && items.length === 0"
      description="还没有 Agent 任务，先生成一份学习导图试试"
      data-testid="empty"
    >
      <el-button type="primary" @click="newMindmap">生成学习导图</el-button>
    </el-empty>

    <div v-if="total > 0" class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="load"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listAgentTasks } from '@/api/agent'
import type { AgentTaskSummary } from '@/types/agent'

import { statusLabel, statusType } from './status'

const router = useRouter()

const items = ref<AgentTaskSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const status = ref('')
const taskType = ref('')
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | null = null

const hasRunning = computed(() =>
  items.value.some((item) => item.status === 'pending' || item.status === 'running'),
)

const TYPE_LABELS: Record<string, string> = {
  demo: '演示任务',
  weekly_mindmap: '学习导图',
}

function typeLabel(value: string): string {
  return TYPE_LABELS[value] ?? value
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function stopPolling(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function schedule(): void {
  stopPolling()
  if (!hasRunning.value) return
  timer = setTimeout(() => {
    void load()
  }, 2000)
}

async function load(): Promise<void> {
  stopPolling()
  loading.value = true
  try {
    const data = await listAgentTasks({
      page: page.value,
      page_size: pageSize.value,
      status: status.value || undefined,
      task_type: taskType.value || undefined,
    })
    items.value = data.items
    total.value = data.total
    error.value = ''
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '加载任务失败'
  } finally {
    loading.value = false
    schedule()
  }
}

function search(): void {
  page.value = 1
  void load()
}

function onSizeChange(): void {
  page.value = 1
  void load()
}

function open(row: AgentTaskSummary): void {
  void router.push(`/agent/tasks/${row.id}`)
}

function newMindmap(): void {
  void router.push('/agent/mindmap')
}

onMounted(() => {
  void load()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.task-list-page {
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
.page-head h1 {
  margin: 0 0 6px;
  font-size: 22px;
}
.page-head p {
  margin: 0;
  color: #667085;
  font-size: 13px;
}
.head-actions {
  display: flex;
  gap: 10px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.filters :deep(.el-select) {
  width: 150px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.task-id {
  cursor: pointer;
  color: #175cd3;
}
.task-table :deep(.el-table__row) {
  cursor: pointer;
}
.status-alert {
  margin-bottom: 2px;
}
.pager {
  display: flex;
  justify-content: flex-end;
}
</style>