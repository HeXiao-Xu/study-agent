/**
 * S4-2 错题列表的筛选状态与取数。
 *
 * 筛选处理器（setStatus/setCauseType/setKpId/setCreatedRange/resetFilters、
 * changePage/changePageSize）单独成函数：视图只把控件事件转进来，测试可以直接
 * 驱动处理器并断言 `listMistakes` 的实收参数，不依赖 Element Plus 下拉的 DOM 事件。
 */
import { computed, reactive, ref } from 'vue'

import { getKpTree, listSubjects } from '@/api/kp'
import { getMistakeStats, listMistakes } from '@/api/mistakes'
import type { KpNode, SubjectOut } from '@/types/kp'
import {
  MISTAKE_CAUSE_TYPES,
  MISTAKE_STATUSES,
  type MistakeCauseType,
  type MistakeFilters,
  type MistakeStats,
  type MistakeStatus,
  type MistakeSummary,
} from '@/types/mistakes'

const PAGE_SIZE = 20
/** 触发列表回到第 1 页的筛选字段；翻页/改每页条数不算。 */
const FILTER_KEYS: (keyof MistakeFilters)[] = [
  'status',
  'causeType',
  'kpId',
  'createdFrom',
  'createdTo',
]

function isMistakeStatus(value: unknown): value is MistakeStatus {
  return typeof value === 'string' && (MISTAKE_STATUSES as readonly string[]).includes(value)
}

function isCauseType(value: unknown): value is MistakeCauseType {
  return typeof value === 'string' && (MISTAKE_CAUSE_TYPES as readonly string[]).includes(value)
}

export function useMistakeList() {
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

  /**
   * 统一取数入口：合并筛选 → 有筛选变化就回第 1 页 → 列表与统计并发。
   * 统计失败只影响统计卡（置空显示 0），不把列表整体标成加载失败。
   */
  async function reload(next: Partial<MistakeFilters> = {}): Promise<void> {
    Object.assign(filters, next)
    if (FILTER_KEYS.some((key) => key in next) && next.page === undefined) {
      filters.page = 1
    }
    loading.value = true
    error.value = false
    try {
      const [listResult, statsResult] = await Promise.allSettled([
        listMistakes({ ...filters }),
        getMistakeStats(),
      ])
      if (listResult.status === 'fulfilled') {
        rows.value = listResult.value.items
        total.value = listResult.value.total
      } else {
        error.value = true
      }
      stats.value = statsResult.status === 'fulfilled' ? statsResult.value : null
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

  async function setStatus(value: unknown): Promise<void> {
    await reload({ status: isMistakeStatus(value) ? value : '' })
  }

  async function setCauseType(value: unknown): Promise<void> {
    await reload({ causeType: isCauseType(value) ? value : '' })
  }

  async function setKpId(value: unknown): Promise<void> {
    await reload({ kpId: typeof value === 'number' ? value : null })
  }

  /** created_to 后端是 datetime；日期区间按「含当天」补到 23:59:59。 */
  async function setCreatedRange(value: unknown): Promise<void> {
    const range = Array.isArray(value) && value.length === 2 ? value : null
    const from = typeof range?.[0] === 'string' ? range[0] : ''
    const to = typeof range?.[1] === 'string' ? range[1] : ''
    await reload({ createdFrom: from, createdTo: to ? `${to}T23:59:59` : '' })
  }

  async function resetFilters(): Promise<void> {
    dateRange.value = null
    await reload({ status: '', causeType: '', kpId: null, createdFrom: '', createdTo: '' })
  }

  async function changePage(page: number): Promise<void> {
    await reload({ page })
  }

  async function changePageSize(size: number): Promise<void> {
    await reload({ pageSize: size, page: 1 })
  }

  return {
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
  }
}