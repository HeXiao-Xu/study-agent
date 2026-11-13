import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  PaperAnswerRow,
  PaperAnswers,
  PaperDetail,
  PaperItem,
  PaperSubmitResult,
} from '@/types/papers'

const papers = vi.hoisted(() => ({
  getPaper: vi.fn(),
  getPaperAnswers: vi.fn(),
  savePaperAnswer: vi.fn(),
  submitPaper: vi.fn(),
}))
vi.mock('@/api/papers', () => papers)

const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '8' } }),
  useRouter: () => router,
}))

vi.mock('@/components/common/MathText.vue', () => ({
  default: { props: ['text'], template: '<span class="math-text">{{ text }}</span>' },
}))

import Take from './Take.vue'

function item(overrides: Partial<PaperItem> = {}): PaperItem {
  return {
    question_id: 501,
    qtype: '解答',
    difficulty: 3,
    score: 8,
    kp_ids: [117],
    parts: null,
    subject_id: 7,
    stem_md: '解方程 $x+1=2$',
    options: [],
    answer_md: 'x=1',
    analysis_md: '移项即可',
    verified: true,
    origin: 'exam',
    ...overrides,
  }
}

function detail(items: PaperItem[] = [item()]): PaperDetail {
  return {
    id: 8,
    title: '验收卷',
    status: '草稿',
    total_score: 8,
    duration_min: 60,
    question_ids: items.map((row) => row.question_id),
    created_at: '2026-11-13T08:00:00+00:00',
    constraint_json: {},
    items,
    missing_question_ids: [],
  }
}

function row(overrides: Partial<PaperAnswerRow> = {}): PaperAnswerRow {
  return {
    question_id: 501,
    user_answer_md: null,
    self_rated: null,
    is_correct: null,
    score: null,
    time_spent_sec: null,
    saved: false,
    ...overrides,
  }
}

function answers(overrides: Partial<PaperAnswers> = {}): PaperAnswers {
  return {
    paper: { id: 8, title: '验收卷', status: '草稿', total_score: 8 },
    items: [row()],
    submitted: false,
    earned_score: null,
    ...overrides,
  }
}

function submitResult(overrides: Partial<PaperSubmitResult> = {}): PaperSubmitResult {
  return {
    paper_id: 8,
    score: 8,
    total_score: 8,
    correct_count: 1,
    question_count: 1,
    elapsed_sec: 30,
    items: [
      {
        question_id: 501,
        qtype: '解答',
        is_correct: true,
        score: 8,
        self_rated: 1,
        user_answer_md: 'x=1',
      },
    ],
    mastery: [
      {
        kp_id: 117,
        kp_name: '函数',
        mastery_before: null,
        mastery_after: 0.117,
        attempts_delta: 1,
      },
    ],
    mistake_question_ids: [],
    missing_question_ids: [],
    ...overrides,
  }
}

async function mountTake() {
  const wrapper = mount(Take, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

async function waitAutosave() {
  await new Promise((resolve) => setTimeout(resolve, 900))
  await flushPromises()
}

beforeEach(() => {
  papers.getPaper.mockReset()
  papers.getPaperAnswers.mockReset()
  papers.savePaperAnswer.mockReset()
  papers.submitPaper.mockReset()
  router.push.mockReset()
  papers.getPaper.mockResolvedValue(detail())
  papers.getPaperAnswers.mockResolvedValue(answers())
  papers.savePaperAnswer.mockResolvedValue(row({ saved: true, user_answer_md: 'x=1' }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
})

describe('Take', () => {
  it('renders the paper and first question', async () => {
    const wrapper = await mountTake()
    expect(wrapper.text()).toContain('验收卷')
    expect(wrapper.find('[data-testid="current-stem"]').text()).toContain('解方程')
    expect(wrapper.find('[data-testid="take-progress"]').text()).toContain('0 / 1')
  })

  it('auto-saves a draft answer after typing', async () => {
    const wrapper = await mountTake()
    await wrapper.find('[data-testid="answer-input"]').setValue('x=1')
    await waitAutosave()
    expect(papers.savePaperAnswer).toHaveBeenCalledWith(8, 501, {
      user_answer_md: 'x=1',
      time_spent_sec: expect.any(Number),
    })
  })

  it('blocks submit until every self-rated question is rated', async () => {
    const wrapper = await mountTake()
    const button = wrapper.find('[data-testid="submit-button"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('还有 1 道题未自评')
    expect(papers.submitPaper).not.toHaveBeenCalled()
  })

  it('submits and shows score plus mastery delta', async () => {
    papers.submitPaper.mockResolvedValue(submitResult())
    const wrapper = await mountTake()
    await wrapper.find('[data-testid="self-rated-1"] input').setValue(true)
    await flushPromises()
    await wrapper.find('[data-testid="submit-button"]').trigger('click')
    await flushPromises()

    expect(papers.submitPaper).toHaveBeenCalledWith(8, {
      items: [
        {
          question_id: 501,
          user_answer_md: null,
          self_rated: 1,
          time_spent_sec: expect.any(Number),
        },
      ],
    })
    expect(wrapper.find('[data-testid="submit-summary"]').text()).toContain('8 / 8')
    expect(wrapper.find('[data-testid="mastery-delta"]').text()).toContain('未评估')
    expect(wrapper.find('[data-testid="mastery-delta"]').text()).toContain('0.117')
  })

  it('waits for an in-flight autosave before submitting', async () => {
    const single = item({
      qtype: '单选',
      score: 3,
      answer_md: 'A',
      options: [
        { key: 'A', text: '选项 A' },
        { key: 'B', text: '选项 B' },
      ],
    })
    papers.getPaper.mockResolvedValue(detail([single]))
    papers.getPaperAnswers.mockResolvedValue(
      answers({
        paper: { id: 8, title: '验收卷', status: '草稿', total_score: 3 },
        items: [row({ question_id: 501 })],
      }),
    )
    papers.submitPaper.mockResolvedValue(
      submitResult({
        score: 3,
        total_score: 3,
        items: [
          {
            question_id: 501,
            qtype: '单选',
            is_correct: true,
            score: 3,
            self_rated: 1,
            user_answer_md: 'A',
          },
        ],
        mastery: [],
      }),
    )
    let resolveSave!: (value: PaperAnswerRow) => void
    papers.savePaperAnswer.mockReturnValue(
      new Promise<PaperAnswerRow>((resolve) => {
        resolveSave = resolve
      }),
    )

    const wrapper = await mountTake()
    await wrapper.find('[data-testid="option-A"] input').setValue(true)
    await waitAutosave()
    expect(papers.savePaperAnswer).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-testid="submit-button"]').trigger('click')
    await flushPromises()
    expect(papers.submitPaper).not.toHaveBeenCalled()

    resolveSave(row({ saved: true, user_answer_md: 'A' }))
    await flushPromises()
    expect(papers.submitPaper).toHaveBeenCalledTimes(1)
  })

  it('restores a saved draft on resume', async () => {
    papers.getPaperAnswers.mockResolvedValue(
      answers({ items: [row({ user_answer_md: 'x=1', time_spent_sec: 12, saved: true })] }),
    )
    const wrapper = await mountTake()
    expect(
      (wrapper.find('[data-testid="answer-input"]').element as HTMLTextAreaElement).value,
    ).toBe('x=1')
    expect(wrapper.find('[data-testid="save-status"]').exists()).toBe(false)
  })

  it('shows a read-only review after submission', async () => {
    papers.getPaperAnswers.mockResolvedValue(
      answers({
        submitted: true,
        earned_score: 8,
        items: [
          row({
            user_answer_md: 'x=1',
            self_rated: 1,
            is_correct: true,
            score: 8,
            time_spent_sec: 30,
            saved: true,
          }),
        ],
      }),
    )
    const wrapper = await mountTake()
    expect(wrapper.find('[data-testid="submitted-banner"]').text()).toContain('已提交')
    expect(wrapper.find('[data-testid="submit-button"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="graded-result"]').text()).toContain('得分 8 / 8')
    expect(
      (wrapper.find('[data-testid="answer-input"]').element as HTMLTextAreaElement)
        .disabled,
    ).toBe(true)
  })
})