/** S4-2 错题详情页：题干/选项渲染、复习状态刷新、诊断占位、图片鉴权与作答保存。 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MistakeDetailView from '@/views/mistakes/MistakeDetailView.vue'
import { getImageBlob } from '@/api/files'
import { listSubjects } from '@/api/kp'
import { deleteMistake, getMistake, reviewMistake, updateMistake } from '@/api/mistakes'
import type { MistakeDetail } from '@/types/mistakes'

vi.mock('@/api/mistakes', () => ({
  getMistake: vi.fn(),
  updateMistake: vi.fn(),
  reviewMistake: vi.fn(),
  deleteMistake: vi.fn(),
}))
vi.mock('@/api/files', () => ({ getImageBlob: vi.fn() }))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn() }))

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  route: { params: { id: '12' } },
}))
vi.mock('vue-router', () => ({
  useRoute: () => routerMocks.route,
  useRouter: () => ({ push: routerMocks.push }),
}))

const createObjectURL = vi.fn(() => 'blob:mock-image')
const revokeObjectURL = vi.fn()

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => {}
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function detail(overrides: Partial<MistakeDetail> = {}): MistakeDetail {
  return {
    id: 12,
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
    stem_md: '已知函数 $f(x)=x^2-4x+3$，求最小值。',
    options: [
      { key: 'A', text: '1' },
      { key: 'B', text: '2' },
    ],
    my_answer_md: '我的原答案',
    correct_answer_md: '最小值为 1',
    image_url: null,
    analysis: null,
    ...overrides,
  }
}

const MdPreviewStub = {
  props: ['modelValue'],
  template: '<div class="md">{{ modelValue }}</div>',
}

function makeWrapper() {
  return mount(MistakeDetailView, {
    global: {
      plugins: [ElementPlus],
      stubs: { MdPreview: MdPreviewStub },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  routerMocks.push.mockReset()
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: createObjectURL,
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: revokeObjectURL,
  })
  vi.mocked(listSubjects).mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  vi.mocked(getMistake).mockResolvedValue(detail())
  vi.mocked(getImageBlob).mockReset()
  vi.mocked(updateMistake).mockResolvedValue(detail())
  vi.mocked(reviewMistake).mockResolvedValue(detail({ status: '已订正', correct_streak: 1 }))
  vi.mocked(deleteMistake).mockResolvedValue(undefined)
})

describe('MistakeDetailView', () => {
  it('用 Markdown 预览渲染题干，并列出选项与元信息', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    expect(getMistake).toHaveBeenCalledWith(12)
    expect(wrapper.get('[data-testid="stem"]').text()).toContain('$f(x)=x^2-4x+3$')
    expect(wrapper.get('[data-testid="option-A"]').text()).toContain('A.')
    expect(wrapper.get('[data-testid="option-B"]').text()).toContain('B.')
    expect(wrapper.get('[data-testid="subject-name"]').text()).toContain('高中数学')
    expect(wrapper.text()).toContain('题型 解答')
  })

  it('analysis 为空时显示 S4-3 占位文案', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.get('[data-testid="analysis-placeholder"]').text()).toContain(
      'AI 错因诊断将在 S4-3 上线',
    )
  })

  it('点「答对了」调用 reviewMistake(12, true) 并用返回值刷新状态', async () => {
    const success = vi.spyOn(ElMessage, 'success').mockReturnValue({} as never)
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="review-correct"]').trigger('click')
    await flushPromises()

    expect(reviewMistake).toHaveBeenCalledWith(12, true)
    expect(getMistake).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="status-tag"]').text()).toBe('已订正')
    expect(wrapper.get('[data-testid="correct-streak"]').text()).toContain('1')
    expect(success).toHaveBeenCalled()
    success.mockRestore()
  })

  it('有 image_url 时用 getImageBlob 取图并渲染 objectURL', async () => {
    vi.mocked(getMistake).mockResolvedValue(
      detail({ image_url: '/api/v1/files/88/image', has_image: true }),
    )
    vi.mocked(getImageBlob).mockResolvedValue(new Blob(['png'], { type: 'image/png' }))
    const wrapper = makeWrapper()
    await flushPromises()

    expect(getImageBlob).toHaveBeenCalledWith(88)
    const image = wrapper.get('[data-testid="image-preview"]')
    expect(image.attributes('src')).toBe('blob:mock-image')
  })

  it('图片请求挂起时不阻塞题干与复习按钮', async () => {
    vi.mocked(getMistake).mockResolvedValue(
      detail({ image_url: '/api/v1/files/88/image', has_image: true }),
    )
    vi.mocked(getImageBlob).mockReturnValue(new Promise<Blob>(() => {}))
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.find('[data-testid="detail-loading"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="stem"]').text()).toContain('$f(x)=x^2-4x+3$')
    expect(wrapper.find('[data-testid="review-correct"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="image-loading"]').exists()).toBe(true)
  })

  it('卸载后迟到的图片响应会立即回收 blob URL', async () => {
    const pending = deferred<Blob>()
    vi.mocked(getMistake).mockResolvedValue(
      detail({ image_url: '/api/v1/files/88/image', has_image: true }),
    )
    vi.mocked(getImageBlob).mockReturnValue(pending.promise)
    const wrapper = makeWrapper()
    await flushPromises()
    expect(createObjectURL).not.toHaveBeenCalled()

    wrapper.unmount()
    pending.resolve(new Blob(['png'], { type: 'image/png' }))
    await flushPromises()

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-image')
  })

  it('保存作答传 myAnswerMd，清空时传 null', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('textarea').setValue('新写的作答')
    await wrapper.get('[data-testid="save-answer"]').trigger('click')
    await flushPromises()
    expect(updateMistake).toHaveBeenCalledWith(12, { myAnswerMd: '新写的作答' })

    await wrapper.get('textarea').setValue('')
    await wrapper.get('[data-testid="save-answer"]').trigger('click')
    await flushPromises()
    expect(updateMistake).toHaveBeenLastCalledWith(12, { myAnswerMd: null })
  })

  it('删除需二次确认，确认后回到列表页', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.get('[data-testid="delete-mistake"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(deleteMistake).toHaveBeenCalledWith(12)
    expect(routerMocks.push).toHaveBeenCalledWith('/mistakes')
    confirm.mockRestore()
  })

  it('加载失败时显示无权访问与返回列表', async () => {
    vi.mocked(getMistake).mockRejectedValue(new Error('404'))
    const wrapper = makeWrapper()
    await flushPromises()

    expect(wrapper.get('[data-testid="detail-error"]').text()).toContain('错题不存在或无权访问')
    await wrapper.get('[data-testid="detail-back"]').trigger('click')
    expect(routerMocks.push).toHaveBeenCalledWith('/mistakes')
  })
})