import { afterEach, describe, expect, it, vi } from 'vitest'

import { createTypewriter } from './typewriter'

describe('createTypewriter', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reveals buffered text in chunks', () => {
    vi.useFakeTimers()
    let text = ''
    const writer = createTypewriter({
      onUpdate: (value) => {
        text = value
      },
      charsPerTick: 2,
      intervalMs: 10,
    })
    writer.push('abcdef')
    vi.advanceTimersByTime(10)
    expect(text).toBe('ab')
    vi.advanceTimersByTime(20)
    expect(text).toBe('abcdef')
  })

  it('calls onDrained once after the queue empties', () => {
    vi.useFakeTimers()
    const drained = vi.fn()
    const writer = createTypewriter({
      onUpdate: vi.fn(),
      onDrained: drained,
      charsPerTick: 5,
      intervalMs: 10,
    })
    writer.push('abc')
    vi.advanceTimersByTime(20)
    expect(drained).toHaveBeenCalledTimes(1)
  })

  it('flush reveals everything and cancel drops pending text', () => {
    vi.useFakeTimers()
    let text = ''
    const writer = createTypewriter({
      onUpdate: (value) => {
        text = value
      },
      charsPerTick: 1,
      intervalMs: 10,
    })
    writer.push('abc')
    writer.flush()
    expect(text).toBe('abc')
    expect(writer.isIdle()).toBe(true)

    writer.push('def')
    writer.cancel()
    expect(writer.isIdle()).toBe(true)
    vi.advanceTimersByTime(50)
    expect(text).toBe('abc')
  })
})