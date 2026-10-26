<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listSubjects } from '@/api/kp'
import { deleteNote } from '@/api/notes'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { SubjectOut } from '@/types/kp'
import { useNoteList } from '@/views/notes/useNoteList'

const route = useRoute()
const router = useRouter()
const { items, total, loading, error, query, fetchList, updateQuery, syncFromRoute } =
  useNoteList()
const subjects = ref<SubjectOut[]>([])
const subjectNames = computed(() => new Map(subjects.value.map((item) => [item.id, item.name])))
const keyword = ref(query.q)
let timer: ReturnType<typeof setTimeout> | undefined

const hasFilter = computed(() => Boolean(query.q) || query.subjectId !== null)

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function subjectName(id: number | null): string {
  return id === null ? '未分类' : (subjectNames.value.get(id) ?? '未分类')
}

function onKeywordInput(value: string): void {
  keyword.value = value
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    void updateQuery({ q: value.trim() }, true)
  }, 300)
}

async function onSubjectChange(value: number | null | undefined): Promise<void> {
  await updateQuery({ subjectId: typeof value === 'number' ? value : null }, true)
}

async function onSortChange(value: string): Promise<void> {
  await updateQuery({ sort: value as 'updated' | 'created' | 'title' }, true)
}

async function onPageChange(page: number): Promise<void> {
  await updateQuery({ page })
}

async function onSizeChange(size: number): Promise<void> {
  await updateQuery({ pageSize: size }, true)
}

async function clearFilters(): Promise<void> {
  if (timer) clearTimeout(timer)
  keyword.value = ''
  await updateQuery({ q: '', subjectId: null }, true)
}

async function removeNote(id: number, title: string): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除「${title}」？删除后不可在列表恢复。`, '删除笔记', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteNote(id)
    ElMessage.success('已删除')
    if (items.value.length === 1 && query.page > 1) {
      await updateQuery({ page: query.page - 1 })
    } else {
      await fetchList()
    }
  } catch {
    // 全局拦截器已提示
  }
}

function editNote(id: number): void {
  void router.push({ name: 'note-edit', params: { id } })
}

function onRowClick(row: { id: number }): void {
  editNote(row.id)
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})

watch(
  () => route.query,
  async () => {
    syncFromRoute()
    keyword.value = query.q
    await fetchList()
  },
  { immediate: true },
)
</script>

<template>
  <div class="notes-page">
    <PageHeader title="笔记" description="按主题整理，保存后自动对齐知识点。">
      <template #actions>
        <el-button type="primary" @click="router.push({ name: 'note-new' })">新建笔记</el-button>
      </template>
    </PageHeader>

    <section class="filter-bar" aria-label="笔记筛选">
      <el-input
        :model-value="keyword"
        class="keyword"
        placeholder="搜索标题或正文"
        clearable
        @update:model-value="onKeywordInput"
      />
      <el-select
        :model-value="query.subjectId"
        class="subject"
        placeholder="全部学科"
        clearable
        @update:model-value="onSubjectChange"
      >
        <el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select :model-value="query.sort" class="sort" @update:model-value="onSortChange">
        <el-option label="最近更新" value="updated" />
        <el-option label="最近创建" value="created" />
        <el-option label="标题 A–Z" value="title" />
      </el-select>
    </section>

    <div v-if="error" class="error-bar" role="alert">
      {{ error }}
      <el-button link type="primary" @click="fetchList">重试</el-button>
    </div>

    <el-table
      v-if="items.length || loading"
      v-loading="loading"
      :data="items"
      class="notes-table"
      row-key="id"
      @row-click="onRowClick"
    >
      <el-table-column prop="title" label="标题" min-width="320">
        <template #default="{ row }">
          <span class="row-title" :title="row.title">{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column label="学科" width="140">
        <template #default="{ row }">{{ subjectName(row.subject_id) }}</template>
      </el-table-column>
      <el-table-column label="标签" min-width="200">
        <template #default="{ row }">
          <el-tag
            v-for="tag in (row.tags ?? []).slice(0, 3)"
            :key="tag"
            size="small"
            effect="plain"
            class="tag"
          >{{ tag }}</el-tag>
          <span v-if="(row.tags ?? []).length > 3" class="tag-more">
            +{{ row.tags.length - 3 }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="editNote(row.id)">编辑</el-button>
          <el-button link type="danger" @click.stop="removeNote(row.id, row.title)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState
      v-else-if="!loading && hasFilter"
      title="没有匹配的笔记"
      description="换个关键词或学科试试。"
    >
      <template #actions>
        <el-button @click="clearFilters">清空筛选</el-button>
      </template>
    </EmptyState>
    <EmptyState v-else-if="!loading" title="还没有笔记" description="把今天学到的东西写下来。">
      <template #actions>
        <el-button type="primary" @click="router.push({ name: 'note-new' })">
          写第一篇笔记
        </el-button>
      </template>
    </EmptyState>

    <div v-if="total > 0" class="pager">
      <el-pagination
        :current-page="query.page"
        :page-size="query.pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
.notes-page {
  display: grid;
  gap: 16px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.keyword {
  width: 320px;
}

.subject {
  width: 180px;
}

.sort {
  width: 160px;
}

.error-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  color: var(--app-danger);
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.notes-table {
  background: var(--app-surface);
  border-radius: var(--app-radius-md);
}

.row-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag {
  margin-right: 4px;
}

.tag-more {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
</style>