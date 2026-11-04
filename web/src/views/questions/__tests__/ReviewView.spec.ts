/** S4-1 审题页：列表、详情、保存、拆分、公式渲染、越权只读。 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewView from '@/views/questions/ReviewView.vue'
import {
  deleteQuestion,
  getQuestion,
  listQuestions,
  mergeQuestions,
  splitQuestion,
  updateQuestion,
} from '@/api/questions'
import { getKpTree, listSubjects } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import type { QuestionDetail, QuestionSummary } from '@/types/questions'
import type { KpTree } from '@/types/kp'

vi.mock('@/api/questions', () => ({
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
  updateQuestion: vi.fn(),
  splitQuestion: vi.fn(),
  mergeQuestions: vi.fn(),
  deleteQuestion: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ getKpTree: vi.fn(), listSubjects: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

const SUMMARY: QuestionSummary = {
  id: 1,
  subject_id: 1,
  qtype: '解答',
  difficulty: 2,
  origin: 'upload',
  verified: true,
  stem_md: '已知函数 $f(x)=x^2$，求 $f(1)$。',
  source_file_id: 3,
  created_by: 1,
  created_at: '2026-11-02T00:00:00Z',
  kp_names: ['函数的单调性'],
}

const DETAIL: QuestionDetail = {
  ...SUMMARY,
  options_json: null,
  answer_md: '1',
  analysis_md: null,
  stem_latex: null,
  tags: null,
  kps: [{ kp_id: 3, kp_name: '函数的单调性', kp_code: 'kp.3', weight: 0.8 }],
}

const TREE: KpTree = {
  subject: { id: 1, name: '高中数学', code: 'math', stage: '高中' },
  nodes: [
    {
      id: 3,
      subject_id: 1,
      parent_id: null,
      name: '函数的单调性',
      code: 'kp.3',
      level: 1,
      description: null,
      exam_weight: null,
      order_no: 1,
      children: [],
    },
  ],
}

function makeWrapper(role: 'student' | 'teacher' = 'student') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = { id: 1, role } as never
  return mount(ReviewView, {
    global: {
      plugins: [ElementPlus, pinia],
      stubs: {
        MdPreview: { props: ['modelValue'], template: '<div class="md">{{ modelValue }}</div>' },
      },
    },
  })
}

describe('ReviewView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listQuestions).mockResolvedValue({
      items: [{ ...SUMMARY, created_by: 1 }],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(getQuestion).mockResolvedValue(DETAIL)
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    vi.mocked(getKpTree).mockResolvedValue(TREE)
    vi.mocked(updateQuestion).mockResolvedValue(DETAIL)
    vi.mocked(splitQuestion).mockResolvedValue([DETAIL, DETAIL])
    vi.mocked(mergeQuestions).mockResolvedValue({ ...DETAIL, id: 9 })
    vi.mocked(deleteQuestion).mockResolvedValue(undefined)
  })

  it('renders question list', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    expect(wrapper.text()).toContain('已知函数')
    expect(wrapper.text()).toContain('函数的单调性')
  })

  it('loads detail when a row is clicked', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(getQuestion).toHaveBeenCalledWith(1)
    // 知识点用学科 code 拉树，不是 subject_id
    expect(getKpTree).toHaveBeenCalledWith('math')
    expect(wrapper.text()).toContain('题目 #1')
  })

  it('列表题干把 $…$ 渲染成公式而不是裸露源码', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    const row = wrapper.find('[data-test="row-1"]')
    expect(row.find('.katex').exists()).toBe(true)
    expect(row.text()).not.toContain('$')
  })

  it('saves stem edits through PATCH', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    const stem = wrapper.find('[data-test="stem"]')
    await stem.setValue('已知函数 $f(x)=x^2$，求 $f(2)$。')
    await wrapper.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(updateQuestion).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ stem_md: '已知函数 $f(x)=x^2$，求 $f(2)$。' }),
    )
  })

  it('splits with the given marker', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="split-at"]').setValue('2.')
    await wrapper.find('[data-test="split"]').trigger('click')
    await flushPromises()
    expect(splitQuestion).toHaveBeenCalledWith(1, '2.')
  })

  it('renders formulas through the markdown preview', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.md').text()).toContain('$f(x)=x^2$')
  })

  it('列表不再显示 ID 列，题干前用徽标区分我的/他人', async () => {
    vi.mocked(listQuestions).mockResolvedValue({
      items: [
        { ...SUMMARY, id: 1, created_by: 1 },
        { ...SUMMARY, id: 2, created_by: 99, stem_md: '第二题 $g(x)=x+1$。' },
      ],
      total: 2,
      page: 1,
      page_size: 20,
    })
    const wrapper = makeWrapper()
    await flushPromises()
    expect(wrapper.text()).not.toContain('ID')
    expect(wrapper.get('[data-test="owner-1"]').text()).toBe('我的')
    expect(wrapper.get('[data-test="owner-2"]').text()).toBe('他人')
  })

  it('答案来源列名与取值', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    expect(wrapper.text()).toContain('答案来源')
    expect(wrapper.text()).toContain('卷面')
  })

  it('disables editing for other students questions', async () => {
    vi.mocked(listQuestions).mockResolvedValue({
      items: [{ ...SUMMARY, created_by: 99 }],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(getQuestion).mockResolvedValue({ ...DETAIL, created_by: 99 })
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="save"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="delete"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="split"]').attributes('disabled')).toBeDefined()
  })

  it('merges the selected questions', async () => {
    vi.mocked(listQuestions).mockResolvedValue({
      items: [
        { ...SUMMARY, id: 1, created_by: 1 },
        { ...SUMMARY, id: 2, stem_md: '第二题 $g(x)=x+1$。', created_by: 1 },
      ],
      total: 2,
      page: 1,
      page_size: 20,
    })
    const wrapper = makeWrapper()
    await flushPromises()
    const table = wrapper.findComponent({ name: 'ElTable' })
    table.vm.$emit('selection-change', [
      { ...SUMMARY, id: 1 },
      { ...SUMMARY, id: 2 },
    ])
    await flushPromises()
    const mergeButton = wrapper.find('[data-test="merge"]')
    expect(mergeButton.attributes('disabled')).toBeUndefined()
    await mergeButton.trigger('click')
    await flushPromises()
    expect(mergeQuestions).toHaveBeenCalledWith([1, 2])
  })

  it('confirms before deleting a question', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="delete"]').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect(deleteQuestion).toHaveBeenCalledWith(1)
    confirm.mockRestore()
  })

  it('omits kp_ids when only the difficulty changes', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'ElRate' }).vm.$emit('update:modelValue', 4)
    await flushPromises()
    await wrapper.find('[data-test="save"]').trigger('click')
    await flushPromises()
    const payload = vi.mocked(updateQuestion).mock.calls.at(-1)?.[1]
    expect(payload).not.toHaveProperty('kp_ids')
    expect(payload?.difficulty).toBe(4)
  })
})