export interface SseEvent {
  event: string
  data: string
}

export function parseSseFrame(frame: string): SseEvent | null {
  const lines = frame.split(/\r?\n/)
  let event = 'message'
  const data: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const raw = colon === -1 ? '' : line.slice(colon + 1)
    const value = raw.startsWith(' ') ? raw.slice(1) : raw
    if (field === 'event') event = value || 'message'
    if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  return { event, data: data.join('\n') }
}

export async function* readSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n?/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseSseFrame(frame)
        if (event) yield event
      }
    }
    buffer += decoder.decode()
    buffer = buffer.replace(/\r\n?/g, '\n')
    if (buffer.trim()) {
      const event = parseSseFrame(buffer)
      if (event) yield event
    }
  } finally {
    reader.releaseLock()
  }
}