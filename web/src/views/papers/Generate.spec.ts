import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PaperItem, PaperPreview } from '@/types/papers'

import Generate from './Generate.vue'

const papers = vi.hoisted(() => ({
  generatePaper: vi.fn(),
  replacePaperItem: vi.fn(),
  savePaper: vi.fn(),
  exportPaperPdf: vi.fn(),
}))
vi.mock('@/api/papers', () => papers)

const kpApi = vi.hoisted(() => ({ listSubjects: vi.fn(), getKpTree: vi.fn() }))
vi.mock('@/api/kp', () => kpApi)

const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => router }))

vi.mock('@/components/common/MathText.vue', () => ({
  default: { props: ['text'], template: '<span class="math-text">{{ text }}</span>' },
}))

function item(overrides: Partial<PaperItem> = {}): PaperItem {
  return {
    question_id: 501,
    qtype: '单选',
    difficulty: 2,
    score: 3,
    kp_ids: [101],
    parts: { difficulty_match: 1, mastery_match: 0.8, novelty: 1, quality: 1, total: 0.95 },
    subject_id: 7,
    stem_md: '题干一',
    options: [{ key: 'A', text: '选项 A' }],
    answer_md: '答案一',
    analysis_md: null,
    verified: true,
    origin: 'exam',
    ...overrides,
  }
}

function preview(overrides: Partial<PaperPreview> = {}): PaperPreview {
  return {
    constraint: {
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
      duration_min: 60,
      exclude_recent_days: 14,
      seed: 7,
      kp_weights: { 101: 1 },
      score_by_qtype: { 单选: 3, 多选: 4, 填空: 4, 解答: 8 },
    },
    seed: 7,
    ok: true,
    items: [item(), item({ question_id: 502, stem_md: '题干二' })],
    total_score: 6,
    target_score: 60,
    quota_by_qtype: { 单选: 2 },
    quota_by_difficulty: { 2: 2 },
    quota_by_kp: { 101: 2 },
    counts_by_qtype: { 单选: 2 },
    counts_by_difficulty: { 2: 2 },
    counts_by_kp: { 101: 2 },
    violations: [],
    warnings: [],
    ...overrides,
  }
}

async function mountView() {
  const wrapper = mount(Generate, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

async function selectKp(wrapper: Awaited<ReturnType<typeof mountView>>) {
  const tree = wrapper.findComponent({ name: 'ElTree' })
  tree.vm.$emit('check', { id: 101 }, { checkedKeys: [101] })
  await flushPromises()
}

async function generate(wrapper: Awaited<ReturnType<typeof mountView>>) {
  await selectKp(wrapper)
  await wrapper.find('[data-testid="generate-button"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  papers.generatePaper.mockReset()
  papers.replacePaperItem.mockReset()
  papers.savePaper.mockReset()
  router.push.mockReset()
  papers.exportPaperPdf.mockReset()
  kpApi.listSubjects.mockReset()
  kpApi.getKpTree.mockReset()
  kpApi.listSubjects.mockResolvedValue([{ id: 7, name: '高中数学', code: 'math', stage: '高中' }])
  kpApi.getKpTree.mockResolvedValue({
    subject: { id: 7, name: '高中数学', code: 'math', stage: '高中' },
    nodes: [
      {
        id: 101,
        subject_id: 7,
        parent_id: null,
        name: '导数',
        code: 'MATH-D',
        level: 1,
        description: null,
        exam_weight: null,
        order_no: 1,
        children: [],
      },
    ],
  })
})

describe('Generate', () => {
  it('renders default form values', async () => {
    const wrapper = await mountView()
    const questions = wrapper.find('[data-testid="total-questions"] input')
    const score = wrapper.find('[data-testid="total-score"] input')
    expect((questions.element as HTMLInputElement).value).toBe('10')
    expect((score.element as HTMLInputElement).value).toBe('60')
  })

  it('explains ratios with plain labels and estimated counts', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('[data-testid="qtype-count-单选"]').text()).toContain('40%')
    expect(wrapper.get('[data-testid="qtype-count-单选"]').text()).toContain('4 题')
    expect(wrapper.get('[data-testid="qtype-count-多选"]').text()).toBe('不出')
    expect(wrapper.get('[data-testid="difficulty-label-2"]').text()).toBe('简单')
    expect(wrapper.get('[data-testid="difficulty-count-2"]').text()).toBe('约 5 题')
    expect(wrapper.text()).toContain('合计不需要等于 1')
    expect(wrapper.text()).toContain('1 最简单，5 最难')
  })

  it('warns and does not call the API without kp selection', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = await mountView()
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(papers.generatePaper).not.toHaveBeenCalled()
    expect(warning).toHaveBeenCalledWith('请至少选择 1 个知识点')
  })

  it('renders the preview and total after generating', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await generate(wrapper)
    expect(papers.generatePaper).toHaveBeenCalledWith(
      expect.objectContaining({
        kp_ids: [101],
        total_questions: 10,
        total_score: 60,
        qtype_ratio: { 单选: 0.4, 填空: 0.2, 解答: 0.4 },
      }),
    )
    expect(wrapper.text()).toContain('题干一')
    expect(wrapper.find('[data-testid="preview-total"]').text()).toBe('总分 6 / 60')
  })

  it('shows shortage status and violation messages', async () => {
    papers.generatePaper.mockResolvedValue(
      preview({
        ok: false,
        items: [item()],
        violations: [{ code: 'QTYPE_SHORTAGE', message: '题型「解答」题量不足', detail: {} }],
      }),
    )
    const wrapper = await mountView()
    await generate(wrapper)
    expect(wrapper.find('[data-testid="preview-status"]').text()).toBe('题库不足')
    expect(wrapper.find('[data-testid="violation"]').text()).toContain('题量不足')
  })

  it('replaces a single row', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.replacePaperItem.mockResolvedValue({
      replaced: true,
      item: item({ question_id: 999, stem_md: '换来的题' }),
      reason: null,
    })
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.findAll('[data-testid="replace-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(papers.replacePaperItem).toHaveBeenCalledWith(
      expect.objectContaining({
        selected_question_ids: [501, 502],
        replace_question_id: 501,
        seed: 7,
      }),
    )
    expect(wrapper.text()).toContain('换来的题')
    expect(wrapper.text()).not.toContain('题干一')
  })

  it('warns when replacement has no candidate', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    papers.generatePaper.mockResolvedValue(preview())
    papers.replacePaperItem.mockResolvedValue({
      replaced: false,
      item: null,
      reason: '没有可替换的候选题',
    })
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.findAll('[data-testid="replace-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(warning).toHaveBeenCalledWith('没有可替换的候选题')
  })

  it('removes a row and recomputes total', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.findAll('[data-testid="remove-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('题干一')
    expect(wrapper.find('[data-testid="preview-total"]').text()).toBe('总分 3 / 60')
  })

  it('moves rows and disables boundary buttons', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await generate(wrapper)
    expect(wrapper.findAll('[data-testid="move-up"]')[0]!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('[data-testid="move-down"]')[1]!.attributes('disabled')).toBeDefined()
    await wrapper.findAll('[data-testid="move-up"]')[1]!.trigger('click')
    await flushPromises()
    const firstRow = wrapper.findAll('.el-table__row')[0]!
    expect(firstRow.text()).toContain('题干二')
  })

  it('saves with the prompted title and current question order', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()
    expect(papers.savePaper).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '我的卷',
        question_ids: [501, 502],
        constraint: expect.objectContaining({ seed: 7 }),
      }),
    )
  })

  it('navigates to the take page after saving', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="take-button"]').trigger('click')
    expect(router.push).toHaveBeenCalledWith('/papers/7/take')
  })

  it('shows export buttons only after the paper is saved', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const wrapper = await mountView()
    await generate(wrapper)
    expect(wrapper.find('[data-testid="export-questions"]').exists()).toBe(false)

    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="export-questions"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="export-answers"]').exists()).toBe(true)
  })

  it('downloads the saved paper as an answer PDF', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    papers.exportPaperPdf.mockResolvedValue(new Blob(['%PDF-1.4']))
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const createObjectURL = vi.fn(() => 'blob:paper')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="export-answers"]').trigger('click')
    await flushPromises()

    expect(papers.exportPaperPdf).toHaveBeenCalledWith(7, 'answers')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:paper')
  })

  it('disables save when the paper is empty', async () => {
    papers.generatePaper.mockResolvedValue(preview({ ok: false, items: [], total_score: 0 }))
    const wrapper = await mountView()
    await generate(wrapper)
    expect(wrapper.find('[data-testid="save-button"]').attributes('disabled')).toBeDefined()
  })

  it('hides answers until the toggle is on', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await generate(wrapper)
    expect(wrapper.text()).not.toContain('答案一')
    const toggle = wrapper.findComponent({ name: 'ElSwitch' })
    toggle.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(wrapper.text()).toContain('答案一')
  })
})