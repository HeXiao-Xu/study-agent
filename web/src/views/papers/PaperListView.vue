<script setup lang="ts">
/** S5-2 我的试卷：找回已保存草稿与已提交试卷。 */
import { onMounted, ref } from 'vue'

import { exportPaperPdf, listPapers } from '@/api/papers'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { PaperStatus, PaperSummary } from '@/types/papers'

const PAGE_SIZES = [10, 20, 50]

const items = ref<PaperSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')
const exporting = ref('')

function statusType(status: PaperStatus): 'warning' | 'success' | 'info' {
  if (status === '草稿') return 'warning'
  if (status === '已提交') return 'success'
  return 'info'
}

function actionLabel(status: PaperStatus): string {
  return status === '草稿' ? '继续作答' : '查看试卷'
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listPapers({ page: page.value, page_size: pageSize.value })
    items.value = result.items
    total.value = result.total
  } catch {
    error.value = '试卷列表加载失败，请重试'
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

async function onExport(id: number, variant: 'questions' | 'answers'): Promise<void> {
  const key = `${id}-${variant}`
  exporting.value = key
  try {
    const blob = await exportPaperPdf(id, variant)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `试卷-${id}-${variant === 'answers' ? '答案卷' : '题干卷'}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="papers-list">
    <PageHeader title="我的试卷" description="查看已保存的草稿和已提交的试卷，继续作答或导出 PDF。">
      <template #actions>
        <router-link to="/papers/generate">
          <el-button type="primary">继续组卷</el-button>
        </router-link>
      </template>
    </PageHeader>

    <div v-if="error" class="error-bar" role="alert">
      {{ error }}
      <el-button data-testid="retry-list" link type="primary" @click="load">重试</el-button>
    </div>

    <el-table v-if="items.length || loading" v-loading="loading" :data="items" class="papers-table">
      <el-table-column label="试卷" min-width="260">
        <template #default="{ row }">
          <div class="paper-title">{{ row.title }}</div>
          <div class="paper-id">#{{ row.id }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="题量" width="90">
        <template #default="{ row }">{{ row.question_count }} 题</template>
      </el-table-column>
      <el-table-column label="总分" width="90">
        <template #default="{ row }">{{ row.total_score }} 分</template>
      </el-table-column>
      <el-table-column label="保存时间" width="180">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" align="right">
        <template #default="{ row }">
          <router-link
            :to="`/papers/${row.id}/take`"
            :data-testid="`open-paper-${row.id}`"
          >
            <el-button link type="primary">{{ actionLabel(row.status) }}</el-button>
          </router-link>
          <el-button
            :data-testid="`export-questions-${row.id}`"
            link
            :loading="exporting === `${row.id}-questions`"
            @click="onExport(row.id, 'questions')"
          >
            导出题干
          </el-button>
          <el-button
            :data-testid="`export-answers-${row.id}`"
            link
            :loading="exporting === `${row.id}-answers`"
            @click="onExport(row.id, 'answers')"
          >
            导出答案
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState
      v-else-if="!loading && !error"
      title="还没有保存过试卷"
      description="在组卷页生成试卷并保存后，草稿会出现在这里。"
    >
      <template #actions>
        <router-link to="/papers/generate" data-testid="empty-generate">
          <el-button type="primary">去组卷</el-button>
        </router-link>
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
  </section>
</template>

<style scoped>
.papers-list {
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

.papers-table {
  width: 100%;
}

.paper-title {
  font-weight: 500;
}

.paper-id {
  margin-top: 2px;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>