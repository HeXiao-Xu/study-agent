import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Chat from './Chat.vue'
import {
  askQuestion,
  deleteConversation,
  getConversationMessages,
  listConversations,
  renameConversation,
} from '@/api/qa'
import { listSubjects } from '@/api/kp'
import type { QaConversation } from '@/types/qa'

vi.mock('@/api/qa', () => ({
  askQuestion: vi.fn(),
  deleteConversation: vi.fn(),
  getConversationMessages: vi.fn(),
  listConversations: vi.fn(),
  renameConversation: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn() }))

const conversation: QaConversation = {
  id: '12',
  title: '错位相减法',
  scope: null,
  created_at: '2026-11-02T10:00:00+00:00',
  last_message_at: null,
  message_count: 2,
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/qa', name: 'qa', component: Chat },
      {
        path: '/notes/:id',
        name: 'note-read',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push('/qa')
  await router.isReady()
  return {
    wrapper: mount(Chat, { global: { plugins: [router, ElementPlus] } }),
    router,
  }
}

beforeEach(() => {
  vi.mocked(listConversations).mockReset()
  vi.mocked(getConversationMessages).mockReset()
  vi.mocked(listSubjects).mockReset()
  vi.mocked(askQuestion).mockReset()
  vi.mocked(renameConversation).mockReset()
  vi.mocked(deleteConversation).mockReset()
  vi.mocked(listSubjects).mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Chat', () => {
  it('loads conversations and messages', async () => {
    vi.mocked(listConversations).mockResolvedValue([conversation])
    vi.mocked(getConversationMessages).mockResolvedValue({
      conversation,
      messages: [
        {
          id: 30,
          role: 'user',
          content_md: '问题',
          created_at: '2026-11-02T10:00:00+00:00',
          refused: false,
          citations: [],
        },
      ],
    })
    const { wrapper } = await mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('错位相减法')
    expect(wrapper.text()).toContain('问题')
  })

  it('sends question and renders streamed answer', async () => {
    vi.mocked(listConversations).mockResolvedValue([conversation])
    vi.mocked(getConversationMessages).mockResolvedValue({
      conversation,
      messages: [],
    })
    vi.mocked(askQuestion).mockImplementation(async (_payload, handlers) => {
      handlers.onMeta({
        conversation_id: '12',
        user_message_id: 30,
        citations: [],
      })
      handlers.onDelta('你好')
      handlers.onDone({
        message_id: 31,
        conversation_id: '12',
        tokens: 1,
        latency_ms: 2,
        refused: false,
        refusal_reason: null,
        suggestions: [],
        cached: false,
      })
    })
    vi.useFakeTimers()
    const { wrapper } = await mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="question-input"]').setValue('你好')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    vi.advanceTimersByTime(100)
    await flushPromises()
    expect(wrapper.text()).toContain('你好')
    expect(askQuestion).toHaveBeenCalledWith(
      expect.objectContaining({ question: '你好', conversation_id: '12' }),
      expect.any(Object),
      expect.anything(),
    )
  })

  it('does not send blank questions', async () => {
    vi.mocked(listConversations).mockResolvedValue([])
    const { wrapper } = await mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="send-question"]').trigger('click')
    expect(askQuestion).not.toHaveBeenCalled()
  })
})