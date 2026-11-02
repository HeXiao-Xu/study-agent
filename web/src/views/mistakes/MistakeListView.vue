<script setup lang="ts">
/**
 * S4-2 错题列表页：统计卡 + 四维筛选 + 复习/删除/详情 + 从题库选题。
 *
 * 学科下拉只用于驱动知识点树：`GET /mistakes` 没有 subject_id 筛选，
 * 而 `getKpTree(subject)` 需要学科 code，因此学科不进 filters，也不发给后端。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { deleteMistake, reviewMistake } from '@/api/mistakes'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import {
  MISTAKE_CAUSE_LABELS,
  MISTAKE_STATUSES,
  type MistakeCauseType,
  type MistakeStatus,
  type MistakeSummary,
} from '@/types/mistakes'
import MistakePickDialog from './MistakePickDialog.vue'
import { useMistakeList } from './useMistakeList'

/** 稳定引用，避免每轮渲染都新建 props 对象/数组。 */
const TREE_PROPS = { label: 'name', children: 'children' }
const PAGER_SIZES = [10, 20, 50]

const router = useRouter()
const {
  filters,
  rows,
  total,
  stats,
  loading,
  error,
  subjects,
  subjectCode,
  kpNodes,
  dateRange,
  statusCounts,
  causeOptions,
  hasFilter,
  reload,
  loadSubjects,
  onSubjectChange,
  setStatus,
  setCauseType,
  setKpId,
  setCreatedRange,
  resetFilters,
  changePage,
  changePageSize,
} = useMistakeList()

const pickVisible = ref(false)

function statusTagType(status: MistakeStatus): 'warning' | 'primary' | 'success' {
  if (status === '已掌握') return 'success'
  if (status === '已订正') return 'primary'
  return 'warning'
}

function causeLabel(cause: MistakeCauseType | null): string {
  return cause ? MISTAKE_CAUSE_LABELS[cause] : '待 S4-3 诊断'
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function goDetail(id: number): void {
  void router.push(`/mistakes/${id}`)
}

async function handleReview(row: MistakeSummary, correct: boolean): Promise<void> {
  try {
    await reviewMistake(row.id, correct)
    ElMessage.success(correct ? '已记为答对' : '已记为答错')
    await reload()
  } catch {
    // http.ts 已统一提示
  }
}

async function removeRow(row: MistakeSummary): Promise<void> {
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除这道错题？', '删除错题', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const currentPage = filters.page ?? 1
  try {
    await deleteMistake(row.id)
    ElMessage.success('已删除')
    await reload(currentPage > 1 ? { page: currentPage - 1 } : {})
  } catch {
    // http.ts 已统一提示
  }
}

async function onPicked(): Promise<void> {
  await reload({ page: 1 })
}

defineExpose({ reload })

onMounted(() => {
  // 列表先发，学科与 KP 树并行加载；KP 慢不影响首屏错题。
  void loadSubjects()
  void reload()
})
</script>

<template>
  <div class="mistake-list" data-testid="mistake-list">
    <PageHeader title="错题本" description="记录错题、推进订正，答对后连续记录进入已掌握。">
      <template #actions>
        <el-button data-testid="open-pick" @click="pickVisible = true">从题库选题</el-button>
        <el-button
          type="primary"
          data-testid="photo-entry"
          @click="router.push('/mistakes/new')"
        >
          拍照录入
        </el-button>
      </template>
    </PageHeader>

    <section class="stat-grid" aria-label="错题统计">
      <div class="stat-card" data-testid="stat-total">
        <span class="stat-label">错题总数</span>
        <strong class="stat-value">{{ stats?.total ?? 0 }}</strong>
      </div>
      <div
        v-for="status in MISTAKE_STATUSES"
        :key="status"
        class="stat-card"
        :data-testid="`stat-${status}`"
      >
        <span class="stat-label">{{ status }}</span>
        <strong class="stat-value">{{ statusCounts[status] ?? 0 }}</strong>
      </div>
    </section>

    <section class="filter-bar" aria-label="错题筛选">
      <el-select
        v-model="subjectCode"
        data-testid="filter-subject"
        class="filter filter--subject"
        placeholder="选择学科"
        @change="onSubjectChange"
      >
        <el-option
          v-for="subject in subjects"
          :key="subject.code"
          :label="subject.name"
          :value="subject.code"
        />
      </el-select>

      <el-select
        v-model="filters.status"
        data-testid="filter-status"
        class="filter filter--status"
        placeholder="全部状态"
        clearable
        @change="setStatus"
      >
        <el-option
          v-for="status in MISTAKE_STATUSES"
          :key="status"
          :label="status"
          :value="status"
        />
      </el-select>

      <el-select
        v-model="filters.causeType"
        data-testid="filter-cause"
        class="filter filter--cause"
        placeholder="全部错因"
        clearable
        :disabled="!causeOptions.length"
        @change="setCauseType"
      >
        <el-option
          v-for="item in causeOptions"
          :key="item.cause_type"
          :label="MISTAKE_CAUSE_LABELS[item.cause_type]"
          :value="item.cause_type"
        />
      </el-select>
      <span v-if="!causeOptions.length" class="cause-hint" data-testid="cause-hint">
        错因待 S4-3 诊断
      </span>

      <el-tree-select
        v-model="filters.kpId"
        data-testid="filter-kp"
        class="filter filter--kp"
        :data="kpNodes"
        node-key="id"
        :props="TREE_PROPS"
        check-strictly
        filterable
        clearable
        placeholder="全部知识点"
        @change="setKpId"
      />

      <el-date-picker
        v-model="dateRange"
        data-testid="filter-date"
        class="filter filter--date"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="录入起始日"
        end-placeholder="录入截止日"
        @change="setCreatedRange"
      />

      <el-button data-testid="filter-reset" @click="resetFilters">重置</el-button>
    </section>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      show-icon
      title="错题加载失败"
      data-testid="list-error"
      class="list-error"
    >
      <el-button size="small" @click="reload()">重试</el-button>
    </el-alert>

    <el-table
      v-if="rows.length || loading"
      v-loading="loading"
      :data="rows"
      row-key="id"
      class="mistake-table"
      data-testid="mistake-table"
    >
      <el-table-column label="题干摘录" min-width="280">
        <template #default="{ row }">
          <el-tooltip :content="row.stem_excerpt" placement="top" :show-after="300">
            <span class="stem-excerpt">{{ row.stem_excerpt }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="qtype" label="题型" width="80" />
      <el-table-column label="知识点" min-width="170">
        <template #default="{ row }">
          <template v-if="row.kp_names.length">
            <el-tag
              v-for="name in row.kp_names"
              :key="name"
              size="small"
              effect="plain"
              class="kp-tag"
            >
              {{ name }}
            </el-tag>
          </template>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="96">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="错因" width="130">
        <template #default="{ row }">
          <span
            :data-testid="`row-${row.id}-cause`"
            :class="{ muted: !row.cause_type }"
          >{{ causeLabel(row.cause_type) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="correct_streak" label="连续答对" width="94" />
      <el-table-column label="录入时间" width="150">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" align="right">
        <template #default="{ row }">
          <div class="row-actions" :data-testid="`row-${row.id}`">
            <el-button
              v-if="row.status !== '已掌握'"
              link
              type="success"
              data-testid="review-correct"
              @click="handleReview(row, true)"
            >
              复习答对
            </el-button>
            <el-button
              link
              type="warning"
              data-testid="review-wrong"
              @click="handleReview(row, false)"
            >
              复习答错
            </el-button>
            <el-button link type="primary" data-testid="detail" @click="goDetail(row.id)">
              详情
            </el-button>
            <el-button link type="danger" data-testid="delete" @click="removeRow(row)">
              删除
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState
      v-if="!rows.length && !loading && !error"
      :title="hasFilter ? '没有匹配的错题' : '还没有错题'"
      :description="
        hasFilter ? '换个筛选条件再试试。' : '从题库选一道题，或者拍照录入第一道错题。'
      "
    >
      <template #actions>
        <el-button v-if="hasFilter" @click="resetFilters">清空筛选</el-button>
        <template v-else>
          <el-button @click="pickVisible = true">从题库选题</el-button>
          <el-button type="primary" @click="router.push('/mistakes/new')">拍照录入</el-button>
        </template>
      </template>
    </EmptyState>

    <div v-if="total > 0" class="pager">
      <el-pagination
        :current-page="filters.page"
        :page-size="filters.pageSize"
        :page-sizes="PAGER_SIZES"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="changePage"
        @size-change="changePageSize"
      />
    </div>

    <MistakePickDialog v-model="pickVisible" @created="onPicked" />
  </div>
</template>

<style scoped>
.mistake-list {
  display: grid;
  gap: 16px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.stat-label {
  color: var(--app-text-secondary);
  font-size: 13px;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  line-height: 1.2;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.filter--subject {
  width: 150px;
}

.filter--status,
.filter--cause {
  width: 130px;
}

.filter--kp {
  width: 200px;
}

.filter--date {
  width: 280px;
}

.cause-hint {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.list-error {
  margin: 0;
}

.mistake-table {
  background: var(--app-surface);
  border-radius: var(--app-radius-md);
}

.stem-excerpt {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kp-tag {
  margin-right: 4px;
  margin-bottom: 2px;
}

.muted {
  color: var(--app-text-tertiary);
}

.row-actions {
  display: flex;
  gap: 2px;
  justify-content: flex-end;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
</style>