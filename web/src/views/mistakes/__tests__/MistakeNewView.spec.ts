/** S4-2 拍照录入页：提交参数、轮询成功跳转、低置信提示、失败重试与兜底。 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MistakeNewView from '@/views/mistakes/MistakeNewView.vue'
import { listSubjects } from '@/api/kp'
import { createMistakeFromPhoto } from '@/api/mistakes'
import { getTask } from '@/api/tasks'
import type { MistakeRecognizeResult } from '@/types/mistakes'
import type { TaskDetail, TaskOut } from '@/types/tasks'

vi.mock('@/api/mistakes', () => ({ createMistakeFromPhoto: vi.fn() }))
vi.mock('@/api/tasks', () => ({ getTask: vi.fn() }))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn() }))

const pushMock = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

const createObjectURL = vi.fn(() => 'blob:mock-preview')
const revokeObjectURL = vi.fn()

function taskOut(id = 33): TaskOut {
  return {
    id,
    name: 'mistake.recognize',
    status: 'pending',
    created_at: '2026-11-03T00:00:00Z',
  }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => {}
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function recognize(overrides: Partial<MistakeRecognizeResult> = {}): MistakeRecognizeResult {
  return {
    mistake_id: 12,
    question_id: 65,
    created: true,
    reused_question: false,
    confidence: 0.93,
    low_confidence: false,
    used_answer_source: 'student',
    warnings: [],
    elapsed_ms: 1500,
    ...overrides,
  }
}

function taskDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    ...taskOut(),
    status: 'succeeded',
    attempts: 1,
    payload: {},
    result: recognize(),
    error: null,
    started_at: '2026-11-03T00:00:01Z',
    finished_at: '2026-11-03T00:00:02Z',
    ...overrides,
  }
}

function makeWrapper() {
  return mount(MistakeNewView, { global: { plugins: [ElementPlus] } })
}

async function pickFile(wrapper: ReturnType<typeof makeWrapper>, file: File): Promise<void> {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
  await flushPromises()
}

async function fillAndSubmit(
  wrapper: ReturnType<typeof makeWrapper>,
  file: File,
  myAnswer = '',
): Promise<void> {
  await pickFile(wrapper, file)
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', 7)
  await flushPromises()
  if (myAnswer) await wrapper.get('textarea').setValue(myAnswer)
  await wrapper.get('[data-testid="submit"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  pushMock.mockReset()
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
  vi.mocked(createMistakeFromPhoto).mockResolvedValue(taskOut())
  vi.mocked(getTask).mockResolvedValue(taskDetail())
})

afterEach(() => {
  vi.useRealTimers()
})

describe('MistakeNewView', () => {
  it('未选文件时不提交', async () => {
    const wrapper = makeWrapper()
    await flushPromises()

    const submit = wrapper.get('[data-testid="submit"]')
    expect(submit.attributes('disabled')).toBeDefined()
    await submit.trigger('click')
    await flushPromises()

    expect(createMistakeFromPhoto).not.toHaveBeenCalled()
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('提交图片与学科后轮询任务并跳转详情', async () => {
    vi.mocked(getTask).mockResolvedValue(taskDetail())
    const wrapper = makeWrapper()
    await flushPromises()

    const file = new File(['fake-image'], 'shot.png', { type: 'image/png' })
    await fillAndSubmit(wrapper, file, '解：先配方再求最小值')

    expect(createMistakeFromPhoto).toHaveBeenCalledWith(file, 7, '解：先配方再求最小值')
    expect(getTask).toHaveBeenCalledWith(33)
    expect(pushMock).toHaveBeenCalledWith('/mistakes/12')
  })

  it('low_confidence 时先警告再跳转', async () => {
    const warning = vi.spyOn(ElMessage, 'warning').mockReturnValue({} as never)
    vi.mocked(getTask).mockResolvedValue(
      taskDetail({ result: recognize({ low_confidence: true, confidence: 0.41 }) }),
    )
    const wrapper = makeWrapper()
    await flushPromises()

    await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))

    expect(warning).toHaveBeenCalledWith('识别置信度偏低，请在详情页核对题干')
    expect(pushMock).toHaveBeenCalledWith('/mistakes/12')
    warning.mockRestore()
  })

  it('重复题目（created=false）提示已重置为待订正', async () => {
    const warning = vi.spyOn(ElMessage, 'warning').mockReturnValue({} as never)
    vi.mocked(getTask).mockResolvedValue(
      taskDetail({ result: recognize({ created: false, reused_question: true }) }),
    )
    const wrapper = makeWrapper()
    await flushPromises()

    await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))

    expect(warning).toHaveBeenCalledWith('该题已在错题本，已重置为待订正')
    warning.mockRestore()
  })

  it('任务失败时显示重试与兜底入口，重试复用同一文件', async () => {
    vi.mocked(getTask).mockResolvedValue(
      taskDetail({ status: 'failed', result: null, error: '未识别到题干' }),
    )
    const wrapper = makeWrapper()
    await flushPromises()

    const file = new File(['fake-image'], 'shot.png', { type: 'image/png' })
    await fillAndSubmit(wrapper, file)

    expect(wrapper.text()).toContain('未识别到题干')
    expect(wrapper.get('[data-testid="retry"]').text()).toContain('重试')
    expect(wrapper.get('[data-testid="fallback-pick"]').text()).toContain('改用题库选题')

    await wrapper.get('[data-testid="retry"]').trigger('click')
    await flushPromises()

    expect(createMistakeFromPhoto).toHaveBeenCalledTimes(2)
    expect(vi.mocked(createMistakeFromPhoto).mock.calls[1]?.[0]).toBe(file)
  })

  it('卸载后迟到的识别结果不再导航或弹提示', async () => {
    const pending = deferred<TaskDetail>()
    vi.mocked(getTask).mockReturnValue(pending.promise)
    const warning = vi.spyOn(ElMessage, 'warning').mockReturnValue({} as never)
    const wrapper = makeWrapper()
    await flushPromises()

    await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))
    wrapper.unmount()
    pending.resolve(taskDetail({ result: recognize({ low_confidence: true }) }))
    await flushPromises()

    expect(pushMock).not.toHaveBeenCalled()
    expect(warning).not.toHaveBeenCalled()
    warning.mockRestore()
  })

  it('轮询 404 立即失败，不空转到 60 秒超时', async () => {
    vi.mocked(getTask).mockRejectedValue({ response: { status: 404 } })
    const wrapper = makeWrapper()
    await flushPromises()

    await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))

    expect(wrapper.get('[data-testid="submit-error"]').text()).toContain('任务不存在或已过期')
    expect(wrapper.find('[data-testid="retry"]').exists()).toBe(true)
  })

  it('轮询每 4 秒查询一次，且轮询中不可换图', async () => {
    vi.mocked(getTask).mockResolvedValue(taskDetail({ status: 'running', result: null }))
    const wrapper = makeWrapper()
    await flushPromises()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))
      expect(getTask).toHaveBeenCalledTimes(1)
      expect(wrapper.get('input[type="file"]').attributes('disabled')).toBeDefined()

      await vi.advanceTimersByTimeAsync(4000)
      expect(getTask).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(4000)
      expect(getTask).toHaveBeenCalledTimes(3)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('约 60 秒仍无终态时转「识别超时」并停止轮询', async () => {
    vi.mocked(getTask).mockResolvedValue(taskDetail({ status: 'running', result: null }))
    const wrapper = makeWrapper()
    await flushPromises()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))
      await vi.advanceTimersByTimeAsync(60_000)

      expect(wrapper.get('[data-testid="submit-error"]').text()).toContain('识别超时')
      expect(wrapper.find('[data-testid="retry"]').exists()).toBe(true)

      const calls = vi.mocked(getTask).mock.calls.length
      await vi.advanceTimersByTimeAsync(8000)
      expect(vi.mocked(getTask).mock.calls.length).toBe(calls)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('重试后旧任务迟到的成功响应不会导航', async () => {
    const stale = deferred<TaskDetail>()
    let staleCalls = 0
    vi.mocked(createMistakeFromPhoto)
      .mockResolvedValueOnce(taskOut(33))
      .mockResolvedValueOnce(taskOut(44))
    vi.mocked(getTask).mockImplementation((id) => {
      if (id === 44) return new Promise<TaskDetail>(() => {})
      staleCalls += 1
      return staleCalls === 1
        ? stale.promise
        : Promise.resolve(
            taskDetail({ status: 'failed', result: null, error: '第一次识别失败' }),
          )
    })
    const wrapper = makeWrapper()
    await flushPromises()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      await fillAndSubmit(wrapper, new File(['fake-image'], 'shot.png', { type: 'image/png' }))
      await vi.advanceTimersByTimeAsync(4000)
      expect(wrapper.get('[data-testid="submit-error"]').text()).toContain('第一次识别失败')

      await wrapper.get('[data-testid="retry"]').trigger('click')
      await flushPromises()
      expect(createMistakeFromPhoto).toHaveBeenCalledTimes(2)

      stale.resolve(taskDetail())
      await flushPromises()
      expect(pushMock).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })
})