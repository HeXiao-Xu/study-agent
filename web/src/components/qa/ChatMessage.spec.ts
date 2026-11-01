import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatMessage from './ChatMessage.vue'
import type { QaUiMessage } from '@/types/qa'

const PreviewStub = {
  props: ['modelValue'],
  template: '<div class="preview">{{ modelValue }}</div>',
}

function baseMessage(overrides: Partial<QaUiMessage> = {}): QaUiMessage {
  return {
    id: 31,
    role: 'assistant',
    content_md: '回答 [1]',
    created_at: '2026-11-02T10:00:00+00:00',
    refused: false,
    citations: [],
    localId: 'server-31',
    error: '',
    streaming: false,
    done: null,
    ...overrides,
  }
}

function mountMessage(overrides: Partial<QaUiMessage> = {}) {
  return mount(ChatMessage, {
    props: { message: baseMessage(overrides) },
    global: { stubs: { MdPreview: PreviewStub } },
  })
}

describe('ChatMessage', () => {
  it('renders assistant markdown through MdPreview', () => {
    const wrapper = mountMessage()
    expect(wrapper.find('.preview').text()).toContain('回答')
  })

  it('styles refusals and shows suggestions', async () => {
    const wrapper = mountMessage({
      refused: true,
      content_md: '暂时无法回答',
      done: {
        tokens: 0,
        latency_ms: 0,
        cached: false,
        suggestions: [{ type: 'rephrase', text: '换个问法', note_id: null }],
      },
    })
    expect(wrapper.classes()).toContain('refused')
    expect(wrapper.text()).toContain('换个问法')
    await wrapper.get('.suggestion').trigger('click')
    expect(wrapper.emitted('suggestion')?.[0]).toEqual(['换个问法'])
  })

  it('shows an error state', () => {
    const wrapper = mountMessage({ error: '生成失败' })
    expect(wrapper.text()).toContain('生成失败')
  })
})