<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { getFileStatus, listFileChunks, listFiles } from '@/api/files'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import FileUploader from '@/components/files/FileUploader.vue'
import type { ChunkPreview, FileSummary, ParseStatus } from '@/types/files'
import {
  PAGE_SIZES,
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  STATUS_LABELS,
  formatDateTime,
  formatFileSize,
  formatFileType,
} from '@/views/files/constants'

const items = ref<FileSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')

const previewOpen = ref(false)
const previewFile = ref<FileSummary | null>(null)
const chunks = ref<ChunkPreview[]>([])
const chunksLoading = ref(false)
const chunksError = ref('')

let rowTimer: ReturnType<typeof setInterval> | undefined
let rowPollStartedAt = 0

function isActive(status: ParseStatus): boolean {
  return status === 'pending' || status === 'parsing'
}

function stopRowPolling(): void {
  if (rowTimer) clearInterval(rowTimer)
  rowTimer = undefined
}

function startRowPolling(): void {
  stopRowPolling()
  if (!items.value.some((item) => isActive(item.parse_status))) return
  rowPollStartedAt = Date.now()
  rowTimer = setInterval(() => {
    void pollActiveRows()
  }, POLL_INTERVAL_MS)
}

async function pollActiveRows(): Promise<void> {
  const active = items.value.filter((item) => isActive(item.parse_status))
  if (!active.length) {
    stopRowPolling()
    return
  }
  if (Date.now() - rowPollStartedAt >= POLL_TIMEOUT_MS) {
    stopRowPolling()
    return
  }
  const statuses = await Promise.all(
    active.map(async (item) => {
      try {
        return await getFileStatus(item.id)
      } catch {
        return null
      }
    }),
  )
  for (const status of statuses) {
    if (!status) continue
    const item = items.value.find((entry) => entry.id === status.id)
    if (!item) continue
    item.parse_status = status.parse_status
    item.parse_progress = status.parse_progress
    item.error_msg = status.error_msg
    item.chunk_count = status.chunk_count
  }
  if (!items.value.some((item) => isActive(item.parse_status))) stopRowPolling()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listFiles({ page: page.value, page_size: pageSize.value })
    items.value = result.items
    total.value = result.total
    startRowPolling()
  } catch {
    error.value = '文件列表加载失败，请重试'
    stopRowPolling()
  } finally {
    loading.value = false
  }
}

async function onPageChange(next: number): Promise<void> {
  page.value = next
  await load()
}

async function onSizeChange(size: number): Promise<void> {
  pageSize.value = size
  page.value = 1
  await load()
}

async function onUploadFinished(): Promise<void> {
  await load()
}

function statusType(status: ParseStatus): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'done') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'parsing') return 'warning'
  return 'info'
}

function statusText(row: FileSummary): string {
  if (row.parse_status === 'parsing') {
    return `${STATUS_LABELS.parsing} ${row.parse_progress}%`
  }
  return STATUS_LABELS[row.parse_status]
}

async function loadChunks(): Promise<void> {
  if (!previewFile.value) return
  chunksLoading.value = true
  chunksError.value = ''
  try {
    chunks.value = await listFileChunks(previewFile.value.id, 3)
  } catch {
    chunksError.value = '切片加载失败，请重试'
  } finally {
    chunksLoading.value = false
  }
}

async function openPreview(row: FileSummary): Promise<void> {
  if (row.parse_status !== 'done') return
  previewFile.value = row
  previewOpen.value = true
  chunks.value = []
  await loadChunks()
}

function resetPreview(): void {
  previewFile.value = null
  chunks.value = []
  chunksError.value = ''
}

function scrollToUploader(): void {
  document
    .querySelector('.file-uploader')
    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const previewTitle = computed(() => previewFile.value?.filename ?? '切片预览')

onMounted(load)
onUnmounted(stopRowPolling)
</script>

<template>
  <div class="files-page">
    <PageHeader
      title="文件"
      description="上传 PDF、Word、Markdown、TXT，系统自动解析并切片。"
    />

    <FileUploader @finished="onUploadFinished" />

    <div v-if="error" class="error-bar" role="alert">
      {{ error }}
      <el-button data-testid="retry-list" link type="primary" @click="load">重试</el-button>
    </div>

    <el-table v-if="items.length || loading" v-loading="loading" :data="items" class="files-table">
      <el-table-column label="文件名" min-width="280">
        <template #default="{ row }">
          <span class="row-name" :title="row.filename">{{ row.filename }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型 / 大小" width="180">
        <template #default="{ row }">
          {{ formatFileType(row.filename, row.mime) }} · {{ formatFileSize(row.size) }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="190">
        <template #default="{ row }">
          <el-tag :type="statusType(row.parse_status)" size="small" effect="plain">
            {{ statusText(row) }}
          </el-tag>
          <el-progress
            v-if="row.parse_status === 'parsing'"
            class="row-progress"
            :percentage="row.parse_progress"
            :stroke-width="4"
            :show-text="false"
          />
        </template>
      </el-table-column>
      <el-table-column label="切片数" width="110">
        <template #default="{ row }">
          {{ row.parse_status === 'done' ? `${row.chunk_count} 块` : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130" align="right">
        <template #default="{ row }">
          <el-button
            v-if="row.parse_status === 'done'"
            data-testid="preview-chunks"
            link
            type="primary"
            @click="openPreview(row)"
          >
            切片预览
          </el-button>
          <el-tooltip
            v-else-if="row.parse_status === 'failed'"
            :content="row.error_msg ?? '解析失败'"
          >
            <span class="failed-hint">查看错误</span>
          </el-tooltip>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState
      v-else-if="!loading && !error"
      title="还没有文件"
      description="上传第一份资料，系统会自动切片并建立索引。"
    >
      <template #actions>
        <el-button type="primary" @click="scrollToUploader">上传第一份资料</el-button>
      </template>
    </EmptyState>

    <div v-if="total > 0" class="pager">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="PAGE_SIZES"
        :total="total"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-drawer v-model="previewOpen" :title="previewTitle" size="520px" @closed="resetPreview">
      <div v-if="chunksLoading" v-loading="true" class="chunk-loading" />
      <div v-else-if="chunksError" class="chunk-error">
        {{ chunksError }}
        <el-button link type="primary" @click="loadChunks">重试</el-button>
      </div>
      <EmptyState
        v-else-if="!chunks.length"
        title="没有可预览的切片"
        description="该文件尚未产生切片，或解析结果为空。"
      />
      <div v-else class="chunk-list">
        <article v-for="chunk in chunks" :key="chunk.chunk_index" class="chunk-item">
          <header class="chunk-head">
            <span>#{{ chunk.chunk_index + 1 }}</span>
            <span>{{ chunk.token_count }} tokens</span>
          </header>
          <pre class="chunk-content">{{ chunk.content }}</pre>
        </article>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.files-page {
  min-width: 0;
}

.error-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 16px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.files-table {
  width: 100%;
}

.row-name {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-progress {
  width: 120px;
  margin-top: 6px;
}

.failed-hint {
  color: var(--app-danger);
  font-size: 12px;
  cursor: help;
}

.muted {
  color: var(--app-text-tertiary);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.chunk-loading {
  min-height: 160px;
}

.chunk-error {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-danger);
  font-size: 13px;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chunk-item {
  padding: 12px;
  background: #f8f9fb;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.chunk-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.chunk-content {
  max-height: 220px;
  margin: 0;
  overflow: auto;
  color: var(--app-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>