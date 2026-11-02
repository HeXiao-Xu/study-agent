<script setup lang="ts">
/**
 * S4-2 错题列表页：统计卡 + 四维筛选 + 复习/删除 + 从题库选题。
 *
 * 学科下拉只用于驱动知识点树：`GET /mistakes` 没有 subject_id 筛选，
 * 而 `getKpTree(subject)` 需要学科 code，因此学科不进 filters，也不发给后端。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getKpTree, listSubjects } from '@/api/kp'
import {
  createMistake,
  deleteMistake,
  getMistakeStats,
  listMistakes,
  reviewMistake,
} from '@/api/mistakes'
import { listQuestions } from '@/api/questions'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { KpNode, SubjectOut } from '@/types/kp'
import {
  MISTAKE_CAUSE_LABELS,
  MISTAKE_CAUSE_TYPES,
  MISTAKE_STATUSES,
  type MistakeCauseType,
  type MistakeFilters,
  type MistakeStats,
  type MistakeStatus,
  type MistakeSummary,
} from '@/types/mistakes'
import type { QuestionSummary, QuestionType } from '@/types/questions'

const PAGE_SIZE = 20
const PICK_PAGE_SIZE = 10
const QUESTION_TYPES: QuestionType[] = ['单选', '多选', '填空', '解答']
/** 稳定引用，避免每轮渲染都新建 props 对象。 */
const TREE_PROPS = { label: 'name', children: 'children' }
const PAGER_SIZES = [10, 20, 50]
/** 触发列表回到第 1 页的筛选字段；翻页/改每页条数不算。 */
const FILTER_KEYS: (keyof MistakeFilters)[] = [
  'status',
  'causeType',
  'kpId',
  'createdFrom',
  'createdTo',
]

const router = useRouter()

const filters = reactive<MistakeFilters>({
  status: '',
  causeType: '',
  kpId: null,
  createdFrom: '',
  createdTo: '',
  page: 1,
  pageSize: PAGE_SIZE,
})

const rows = ref<MistakeSummary[]>([])
const total = ref(0)
const stats = ref<MistakeStats | null>(null)
const loading = ref(false)
const error = ref(false)

const subjects = ref<SubjectOut[]>([])
/** 仅驱动 KP 树的学科 code，不参与列表查询。 */
const subjectCode = ref('')
const kpNodes = ref<KpNode[]>([])
const dateRange = ref<[string, string] | null>(null)

const pickVisible = ref(false)
const pickLoading = ref(false)
const pickSubmitting = ref(false)
const pickRows = ref<QuestionSummary[]>([])
const pickTotal = ref(0)
const pickPage = ref(1)
const pickQtype = ref<QuestionType | ''>('')
const pickSelectedId = ref<number | null>(null)

const statusCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {}
  for (const item of stats.value?.by_status ?? []) counts[item.status] = item.count
  return counts
})

const causeOptions = computed(() => stats.value?.by_cause ?? [])

const hasFilter = computed(() =>
  Boolean(
    filters.status ||
      filters.causeType ||
      filters.kpId !== null ||
      filters.createdFrom ||
      filters.createdTo,
  ),
)

function isMistakeStatus(value: unknown): value is MistakeStatus {
  return typeof value === 'string' && (MISTAKE_STATUSES as readonly string[]).includes(value)
}

function isCauseType(value: unknown): value is MistakeCauseType {
  return typeof value === 'string' && (MISTAKE_CAUSE_TYPES as readonly string[]).includes(value)
}

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

/**
 * 统一取数入口：合并筛选 → 有筛选变化就回第 1 页 → 列表与统计并发。
 * brief 要求导出到组件实例，测试用 `reload()` 直接驱动筛选。
 */
async function reload(next: Partial<MistakeFilters> = {}): Promise<void> {
  Object.assign(filters, next)
  if (FILTER_KEYS.some((key) => key in next) && next.page === undefined) {
    filters.page = 1
  }
  loading.value = true
  error.value = false
  try {
    const [pageData, statsData] = await Promise.all([
      listMistakes({ ...filters }),
      getMistakeStats(),
    ])
    rows.value = pageData.items
    total.value = pageData.total
    stats.value = statsData
  } catch {
    // http.ts 已统一提示，这里只保留可重试的局部状态
    error.value = true
  } finally {
    loading.value = false
  }
}

async function loadSubjects(): Promise<void> {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
    return
  }
  if (!subjects.value.some((item) => item.code === subjectCode.value)) {
    subjectCode.value = subjects.value[0]?.code ?? ''
  }
  await loadKpTree()
}

async function loadKpTree(): Promise<void> {
  if (!subjectCode.value) {
    kpNodes.value = []
    return
  }
  try {
    const tree = await getKpTree(subjectCode.value)
    kpNodes.value = tree.nodes
  } catch {
    kpNodes.value = []
  }
}

/** 换学科会重建 KP 树，旧的 kp_id 不再可信，必须清掉并刷新列表。 */
async function onSubjectChange(value: unknown): Promise<void> {
  subjectCode.value = typeof value === 'string' ? value : ''
  await loadKpTree()
  await reload({ kpId: null })
}

async function onStatusChange(value: unknown): Promise<void> {
  await reload({ status: isMistakeStatus(value) ? value : '' })
}

async function onCauseChange(value: unknown): Promise<void> {
  await reload({ causeType: isCauseType(value) ? value : '' })
}

async function onKpChange(value: unknown): Promise<void> {
  await reload({ kpId: typeof value === 'number' ? value : null })
}

/** created_to 后端是 datetime；日期区间按「含当天」补到 23:59:59。 */
async function onDateChange(value: unknown): Promise<void> {
  const range = Array.isArray(value) && value.length === 2 ? value : null
  const from = typeof range?.[0] === 'string' ? range[0] : ''
  const to = typeof range?.[1] === 'string' ? range[1] : ''
  await reload({ createdFrom: from, createdTo: to ? `${to}T23:59:59` : '' })
}

async function resetFilters(): Promise<void> {
  dateRange.value = null
  await reload({ status: '', causeType: '', kpId: null, createdFrom: '', createdTo: '' })
}

async function onPageChange(page: number): Promise<void> {
  await reload({ page })
}

async function onSizeChange(size: number): Promise<void> {
  await reload({ pageSize: size, page: 1 })
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
    if (rows.value.length === 1 && currentPage > 1) {
      await reload({ page: currentPage - 1 })
    } else {
      await reload()
    }
  } catch {
    // http.ts 已统一提示
  }
}

async function openPickDialog(): Promise<void> {
  pickVisible.value = true
  pickPage.value = 1
  pickSelectedId.value = null
  await loadPickRows()
}

async function loadPickRows(): Promise<void> {
  pickLoading.value = true
  try {
    const data = await listQuestions({
      page: pickPage.value,
      page_size: PICK_PAGE_SIZE,
      qtype: pickQtype.value || undefined,
    })
    pickRows.value = data.items
    pickTotal.value = data.total
  } catch {
    pickRows.value = []
    pickTotal.value = 0
  } finally {
    pickLoading.value = false
  }
}

async function onPickQtypeChange(): Promise<void> {
  pickPage.value = 1
  await loadPickRows()
}

async function onPickPageChange(page: number): Promise<void> {
  pickPage.value = page
  await loadPickRows()
}

function selectPick(id: number): void {
  pickSelectedId.value = id
}

function onPickRowClick(row: QuestionSummary): void {
  selectPick(row.id)
}

async function confirmPick(): Promise<void> {
  const questionId = pickSelectedId.value
  if (questionId === null) return
  pickSubmitting.value = true
  try {
    const result = await createMistake({ questionId })
    if (result.created) {
      ElMessage.success('已加入错题本')
    } else {
      ElMessage.warning('已存在，已重置为待订正')
    }
    pickVisible.value = false
    await reload({ page: 1 })
  } catch {
    // http.ts 已统一提示
  } finally {
    pickSubmitting.value = false
  }
}

defineExpose({ reload })

onMounted(async () => {
  await loadSubjects()
  await reload()
})
</script>

<template>
  <div class="mistake-list" data-testid="mistake-list">
    <PageHeader title="错题本" description="记录错题、推进订正，答对后连续记录进入已掌握。">
      <template #actions>
        <el-button data-testid="open-pick" @click="openPickDialog">从题库选题</el-button>
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
        @change="onStatusChange"
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
        @change="onCauseChange"
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
        @change="onKpChange"
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
        @change="onDateChange"
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
          <span v-if="row.cause_type">{{ causeLabel(row.cause_type) }}</span>
          <span v-else class="muted">待 S4-3 诊断</span>
        </template>
      </el-table-column>
      <el-table-column prop="correct_streak" label="连续答对" width="94" />
      <el-table-column label="录入时间" width="150">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="230" align="right">
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
          <el-button @click="openPickDialog">从题库选题</el-button>
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
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-dialog v-model="pickVisible" title="从题库选题" width="720px" class="pick-dialog">
      <div class="pick-toolbar">
        <el-radio-group
          v-model="pickQtype"
          data-testid="pick-qtype"
          @change="onPickQtypeChange"
        >
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button
            v-for="qtype in QUESTION_TYPES"
            :key="qtype"
            :value="qtype"
          >
            {{ qtype }}
          </el-radio-button>
        </el-radio-group>
        <span class="pick-hint">选中题目后点「录入错题」；重复录入会重置为待订正。</span>
      </div>

      <el-table
        v-loading="pickLoading"
        :data="pickRows"
        row-key="id"
        max-height="320"
        class="pick-table"
        @row-click="onPickRowClick"
      >
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="题干" min-width="320">
          <template #default="{ row }">
            <span class="pick-stem">
              {{ row.stem_md.slice(0, 60) }}<span v-if="row.stem_md.length > 60">…</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="qtype" label="题型" width="72" />
        <el-table-column label="选择" width="88">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :data-testid="`pick-row-${row.id}`"
              @click.stop="selectPick(row.id)"
            >
              {{ pickSelectedId === row.id ? '已选' : '选择' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pick-pager">
        <el-pagination
          :current-page="pickPage"
          :page-size="PICK_PAGE_SIZE"
          :total="pickTotal"
          layout="total, prev, pager, next"
          @current-change="onPickPageChange"
        />
      </div>

      <template #footer>
        <el-button @click="pickVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-testid="pick-confirm"
          :disabled="pickSelectedId === null"
          :loading="pickSubmitting"
          @click="confirmPick"
        >
          录入错题
        </el-button>
      </template>
    </el-dialog>
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

.pick-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.pick-hint {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.pick-stem {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pick-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>