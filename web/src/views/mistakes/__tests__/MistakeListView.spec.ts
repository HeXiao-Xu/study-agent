/** S4-2 错题列表页：统计卡、筛选、复习/删除、空态与「从题库选题」弹窗。 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MistakeListView from '@/views/mistakes/MistakeListView.vue'
import { getKpTree, listSubjects } from '@/api/kp'
import {
  createMistake,
  deleteMistake,
  getMistakeStats,
  listMistakes,
  reviewMistake,
} from '@/api/mistakes'
import { listQuestions } from '@/api/questions'
import type { KpTree } from '@/types/kp'
import type {
  MistakeCreateResult,
  MistakeDetail,
  MistakeFilters,
  MistakeStats,
  MistakeSummary,
} from '@/types/mistakes'
import type { QuestionSummary } from '@/types/questions'

vi.mock('@/api/mistakes', () => ({
  listMistakes: vi.fn(),
  getMistakeStats: vi.fn(),
  reviewMistake: vi.fn(),
  deleteMistake: vi.fn(),
  createMistake: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn(), getKpTree: vi.fn() }))
vi.mock('@/api/questions', () => ({ listQuestions: vi.fn() }))

const pushMock = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

function summary(overrides: Partial<MistakeSummary> = {}): MistakeSummary {
  return {
    id: 1,
    question_id: 65,
    status: '待订正',
    correct_streak: 0,
    stem_excerpt: '已知函数 f(x)=x^2-4x+3',
    subject_id: 7,
    qtype: '解答',
    difficulty: 2,
    kp_names: ['函数的单调性'],
    cause_type: null,
    has_image: false,
    created_at: '2026-11-03T00:00:00Z',
    last_review_at: null,
    ...overrides,
  }
}

function detail(): MistakeDetail {
  return {
    ...summary(),
    stem_md: '已知函数 f(x)=x^2-4x+3',
    options: null,
    my_answer_md: null,
    correct_answer_md: null,
    image_url: null,
    analysis: null,
  }
}

function createResult(created: boolean): MistakeCreateResult {
  return { ...detail(), created }
}

function stats(overrides: Partial<MistakeStats> = {}): MistakeStats {
  return {
    total: 2,
    by_status: [
      { status: '待订正', count: 1 },
      { status: '已订正', count: 0 },
      { status: '已掌握', count: 1 },
    ],
    by_cause: [],
    top_kps: [{ kp_id: 137, kp_name: '函数的单调性', count: 1 }],
    ...overrides,
  }
}

function question(): QuestionSummary {
  return {
    id: 65,
    subject_id: 7,
    qtype: '解答',
    difficulty: 2,
    origin: 'upload',
    verified: true,
    stem_md: '已知函数 f(x)=x^2-4x+3，求最小值。',
    source_file_id: null,
    created_by: null,
    created_at: '2026-11-01T00:00:00Z',
    kp_names: [],
  }
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

type Reload = (next?: Partial<MistakeFilters>) => Promise<void>

function makeWrapper() {
  return mount(MistakeListView, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  pushMock.mockReset()
  vi.mocked(listMistakes).mockResolvedValue({
    items: [summary(), summary({ id: 2, status: '已掌握', correct_streak: 3 })],
    total: 2,
    page: 1,
    page_size: 20,
  })
  vi.mocked(getMistakeStats).mockResolvedValue(stats())
  vi.mocked(reviewMistake).mockResolvedValue(detail())
  vi.mocked(deleteMistake).mockResolvedValue(undefined)
  vi.mocked(createMistake).mockResolvedValue(createResult(false))
  vi.mocked(listSubjects).mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  vi.mocked(getKpTree).mockResolvedValue(TREE)
  vi.mocked(listQuestions).mockResolvedValue({
    items: [question()],
    total: 1,
    page: 1,
    page_size: 10,
  })
})

describe('MistakeListView', () => {
  it('首屏渲染统计卡与错题行', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('已知函数')
    expect(wrapper.text()).toContain('函数的单调性')
    expect(wrapper.get('[data-testid="stat-total"]').text()).toContain('2')
    expect(wrapper.get('[data-testid="stat-待订正"]').text()).toContain('1')
    expect(wrapper.get('[data-testid="stat-已掌握"]').text()).toContain('1')
    expect(getMistakeStats).toHaveBeenCalledTimes(1)
    expect(listMistakes).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
    )
  })

  it('状态筛选带正确参数并回到第 1 页', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    const vm = wrapper.vm as unknown as { reload: Reload }

    vi.mocked(listMistakes).mockClear()
    await vm.reload({ page: 2 })
    expect(vi.mocked(listMistakes).mock.calls.at(-1)?.[0]).toMatchObject({ page: 2 })

    // Element Plus 下拉的 DOM 交互成本高，直接驱动暴露的 reload 更稳。
    await wrapper.get('[data-testid="filter-status"]').trigger('change')
    await vm.reload({ status: '待订正' })
    expect(vi.mocked(listMistakes).mock.calls.at(-1)?.[0]).toMatchObject({
      status: '待订正',
      page: 1,
    })
  })

  it('复习答对调用 reviewMistake(id, true) 并刷新列表', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    vi.mocked(listMistakes).mockClear()
    await wrapper.get('[data-testid="row-1"] [data-testid="review-correct"]').trigger('click')
    await flushPromises()

    expect(reviewMistake).toHaveBeenCalledWith(1, true)
    expect(listMistakes).toHaveBeenCalledTimes(1)
  })

  it('删除需二次确认，确认后调用 deleteMistake 并刷新', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = makeWrapper()
    await flushPromises()

    vi.mocked(listMistakes).mockClear()
    await wrapper.get('[data-testid="row-1"] [data-testid="delete"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(deleteMistake).toHaveBeenCalledWith(1)
    expect(listMistakes).toHaveBeenCalledTimes(1)
    confirm.mockRestore()
  })

  it('取消二次确认则不调用删除接口', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue(new Error('cancel'))
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="row-1"] [data-testid="delete"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(deleteMistake).not.toHaveBeenCalled()
    confirm.mockRestore()
  })

  it('无错题时展示空态', async () => {
    vi.mocked(listMistakes).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    vi.mocked(getMistakeStats).mockResolvedValue(
      stats({ total: 0, by_status: [], by_cause: [], top_kps: [] }),
    )
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('还没有错题')
    expect(wrapper.get('[data-testid="stat-total"]').text()).toContain('0')
    expect(wrapper.findAll('[data-testid="row-1"]')).toHaveLength(0)
  })

  it('已掌握行不渲染「复习答对」', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="row-1"] [data-testid="review-correct"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="row-2"] [data-testid="review-correct"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid="row-2"] [data-testid="review-wrong"]')).toHaveLength(1)
  })

  it('错因为空时展示 S4-3 诊断占位', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="cause-hint"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('错因待 S4-3 诊断')
    // 行内 cause_type === null 时同样给出占位，不渲染错因标签。
    expect(wrapper.get('[data-testid="row-1"]').text()).not.toContain('概念不清')
    expect(wrapper.text()).toContain('待 S4-3 诊断')
  })

  it('学科下拉只驱动知识点树，不进入列表查询参数', async () => {
    makeWrapper()
    await flushPromises()

    expect(getKpTree).toHaveBeenCalledWith('math')
    const params = vi.mocked(listMistakes).mock.calls.at(-1)?.[0]
    expect(params).not.toHaveProperty('subject')
    expect(params).not.toHaveProperty('subjectId')
    expect(params).not.toHaveProperty('subject_id')
  })

  it('从题库选题弹窗选择后调用 createMistake，重复录入给出提示', async () => {
    const warning = vi.spyOn(ElMessage, 'warning').mockReturnValue({} as never)
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="open-pick"]').trigger('click')
    await flushPromises()
    expect(listQuestions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 10 }),
    )

    await wrapper.get('[data-testid="pick-row-65"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="pick-confirm"]').trigger('click')
    await flushPromises()

    expect(createMistake).toHaveBeenCalledWith({ questionId: 65 })
    expect(warning).toHaveBeenCalledWith('已存在，已重置为待订正')
    warning.mockRestore()
  })

  it('拍照录入跳转 /mistakes/new', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="photo-entry"]').trigger('click')
    expect(pushMock).toHaveBeenCalledWith('/mistakes/new')
  })
})