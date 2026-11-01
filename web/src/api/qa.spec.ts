import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { askQuestion } from './qa'

describe('askQuestion', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('throws a readable error for a JSON HTTP error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: 40400, message: '会话不存在' }), {
          status: 404,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(
      askQuestion(
        { question: '问题' },
        { onMeta: vi.fn(), onDelta: vi.fn(), onDone: vi.fn() },
      ),
    ).rejects.toMatchObject({ message: '会话不存在', status: 404 })
  })

  it('dispatches meta/delta/done in order', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          'event: meta\ndata: {"conversation_id":"12","user_message_id":30,"citations":[]}\n\n' +
            'event: delta\ndata: {"text":"你好"}\n\n' +
            'event: done\ndata: {"message_id":31,"conversation_id":"12","tokens":1,"latency_ms":2,"refused":false,"suggestions":[],"cached":false}\n\n',
          { status: 200, headers: { 'content-type': 'text/event-stream' } },
        ),
      ),
    )
    const calls: string[] = []
    await askQuestion(
      { question: '你好' },
      {
        onMeta: () => calls.push('meta'),
        onDelta: () => calls.push('delta'),
        onDone: () => calls.push('done'),
      },
    )
    expect(calls).toEqual(['meta', 'delta', 'done'])
  })
})