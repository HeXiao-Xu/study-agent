/**
 * S4-2 错题列表取数/筛选 composable。
 *
 * 这里直接驱动视图绑定的处理器（setStatus/setCauseType/setKpId/setCreatedRange/
 * resetFilters/changePage/changePageSize），断言 listMistakes 的实收参数；
 * 不再对 Element Plus 下拉根节点 trigger('change')（那不会触发组件事件，是假绿）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useMistakeList } from '@/views/mistakes/useMistakeList'
import { getKpTree, listSubjects } from '@/api/kp'
import { getMistakeStats, listMistakes } from '@/api/mistakes'
import type { KpTree } from '@/types/kp'
import type { MistakeListParams, MistakeStats, MistakeSummary } from '@/types/mistakes'

vi.mock('@/api/mistakes', () => ({ listMistakes: vi.fn(), getMistakeStats: vi.fn() }))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn(), getKpTree: vi.fn() }))

function summary(overrides: Partial<MistakeSummary> = {}): MistakeSummary {
  return {
    id: 1,
    question_id: 65,
    status: '待订正',
    correct_streak: 0,
    stem_excerpt: '已知函数',
    subject_id: 7,
    qtype: '解答',
    difficulty: 2,
    kp_names: [],
    cause_type: null,
    has_image: false,
    created_at: '2026-11-03T00:00:00Z',
    last_review_at: null,
    ...overrides,
  }
}

const STATS: MistakeStats = {
  total: 2,
  by_status: [
    { status: '待订正', count: 1 },
    { status: '已订正', count: 0 },
    { status: '已掌握', count: 1 },
  ],
  by_cause: [],
  top_kps: [],
}

const TREE: KpTree = {
  subject: { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  nodes: [
    {
      id: 137,
      subject_id: 7,
      parent_id: null,
      name: '函数的单调性',
      code: 'kp.137',
      level: 1,
      description: null,
      exam_weight: null,
      order_no: 1,
      children: [],
    },
  ],
}

/** 最近一次 listMistakes 的实收参数。 */
function lastListParams(): MistakeListParams {
  return vi.mocked(listMistakes).mock.calls.at(-1)?.[0] ?? {}
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listMistakes).mockResolvedValue({
    items: [summary(), summary({ id: 2, status: '已掌握' })],
    total: 2,
    page: 1,
    page_size: 20,
  })
  vi.mocked(getMistakeStats).mockResolvedValue(STATS)
  vi.mocked(listSubjects).mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  vi.mocked(getKpTree).mockResolvedValue(TREE)
})

describe('useMistakeList', () => {
  it('reload 并发取列表与统计并写入状态', async () => {
    const state = useMistakeList()
    await state.reload()

    expect(listMistakes).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
    )
    expect(getMistakeStats).toHaveBeenCalledTimes(1)
    expect(state.rows.value).toHaveLength(2)
    expect(state.total.value).toBe(2)
    expect(state.stats.value?.total).toBe(2)
    expect(state.error.value).toBe(false)
  })

  it('状态筛选带正确参数并回到第 1 页', async () => {
    const state = useMistakeList()
    await state.reload()

    await state.changePage(2)
    expect(lastListParams()).toMatchObject({ page: 2, pageSize: 20 })

    await state.setStatus('待订正')
    expect(lastListParams()).toMatchObject({ status: '待订正', page: 1, pageSize: 20 })
  })

  it('错因筛选带正确参数并回到第 1 页', async () => {
    const state = useMistakeList()
    await state.reload()
    await state.changePage(3)

    await state.setCauseType('概念不清')
    expect(lastListParams()).toMatchObject({ causeType: '概念不清', page: 1 })
  })

  it('知识点筛选带正确参数并回到第 1 页', async () => {
    const state = useMistakeList()
    await state.reload()
    await state.changePage(3)

    await state.setKpId(137)
    expect(lastListParams()).toMatchObject({ kpId: 137, page: 1 })
  })

  it('日期区间补到当天 23:59:59，清空后发空串', async () => {
    const state = useMistakeList()
    await state.reload()

    await state.setCreatedRange(['2026-11-01', '2026-11-03'])
    expect(lastListParams()).toMatchObject({
      createdFrom: '2026-11-01',
      createdTo: '2026-11-03T23:59:59',
      page: 1,
    })

    await state.setCreatedRange(null)
    expect(lastListParams()).toMatchObject({ createdFrom: '', createdTo: '', page: 1 })
  })

  it('重置清空四维筛选并回第 1 页', async () => {
    const state = useMistakeList()
    await state.reload()
    await state.setStatus('已掌握')
    await state.setCauseType('概念不清')
    await state.setKpId(137)
    await state.setCreatedRange(['2026-11-01', '2026-11-03'])

    await state.resetFilters()
    expect(state.dateRange.value).toBeNull()
    expect(lastListParams()).toMatchObject({
      status: '',
      causeType: '',
      kpId: null,
      createdFrom: '',
      createdTo: '',
      page: 1,
    })
  })

  it('切页只改 page 且保留 pageSize，改 pageSize 回第 1 页', async () => {
    const state = useMistakeList()
    await state.reload()

    await state.changePage(3)
    expect(lastListParams()).toMatchObject({ page: 3, pageSize: 20 })

    await state.changePageSize(50)
    expect(lastListParams()).toMatchObject({ page: 1, pageSize: 50 })
  })

  it('统计失败不拖垮列表：列表照常渲染、错误标记不置位', async () => {
    vi.mocked(getMistakeStats).mockRejectedValueOnce(new Error('stats down'))
    const state = useMistakeList()
    await state.reload()

    expect(state.error.value).toBe(false)
    expect(state.rows.value).toHaveLength(2)
    expect(state.total.value).toBe(2)
    expect(state.stats.value).toBeNull()
    expect(state.statusCounts.value['待订正'] ?? 0).toBe(0)
  })

  it('列表失败才标记加载失败', async () => {
    vi.mocked(listMistakes).mockRejectedValueOnce(new Error('list down'))
    const state = useMistakeList()
    await state.reload()

    expect(state.error.value).toBe(true)
    expect(state.rows.value).toHaveLength(0)
  })

  it('loadSubjects 默认选中第一学科并按 code 取树', async () => {
    const state = useMistakeList()
    await state.loadSubjects()

    expect(state.subjects.value).toHaveLength(1)
    expect(state.subjectCode.value).toBe('math')
    expect(getKpTree).toHaveBeenCalledWith('math')
    expect(state.kpNodes.value).toHaveLength(1)
  })

  it('换学科重建 KP 树并清掉 kpId（kp 筛选回第 1 页）', async () => {
    const state = useMistakeList()
    await state.loadSubjects()

    await state.setKpId(137)
    await state.onSubjectChange('physics')

    expect(state.subjectCode.value).toBe('physics')
    expect(getKpTree).toHaveBeenLastCalledWith('physics')
    expect(lastListParams()).toMatchObject({ kpId: null, page: 1 })
  })
})