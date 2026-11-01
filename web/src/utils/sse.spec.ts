import { describe, expect, it } from 'vitest'

import { parseSseFrame, readSseStream } from './sse'

function bodyOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe('sse', () => {
  it('parses event and multi-line data', () => {
    const event = parseSseFrame('event: meta\ndata: {"a":1}\ndata: {"b":2}')
    expect(event).toEqual({ event: 'meta', data: '{"a":1}\n{"b":2}' })
  })

  it('parses CRLF and ignores comments', () => {
    const event = parseSseFrame(': keepalive\r\nevent: delta\r\ndata: {"text":"hi"}')
    expect(event?.event).toBe('delta')
    expect(event?.data).toBe('{"text":"hi"}')
  })

  it('reads frames across chunks and decodes UTF-8', async () => {
    const events = []
    for await (const event of readSseStream(
      bodyOf(['event: delta\ndata: {"text":"错', '位相减"}\n\n']),
    )) {
      events.push(event)
    }
    expect(events).toHaveLength(1)
    expect(events[0].data).toContain('错位相减')
  })

  it('returns null for a comment-only frame', () => {
    expect(parseSseFrame(': ping')).toBeNull()
  })
})