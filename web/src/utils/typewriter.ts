export interface TypewriterOptions {
  onUpdate: (text: string) => void
  onDrained?: () => void
  charsPerTick?: number
  intervalMs?: number
}

export interface Typewriter {
  push: (text: string) => void
  flush: () => void
  cancel: () => void
  isIdle: () => boolean
}

export function createTypewriter(options: TypewriterOptions): Typewriter {
  const charsPerTick = options.charsPerTick ?? 12
  const intervalMs = options.intervalMs ?? 16
  let visible = ''
  let pending = ''
  let timer: ReturnType<typeof setInterval> | null = null
  let drained = false

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function tick(): void {
    if (!pending) {
      stop()
      if (!drained) {
        drained = true
        options.onDrained?.()
      }
      return
    }
    visible += pending.slice(0, charsPerTick)
    pending = pending.slice(charsPerTick)
    options.onUpdate(visible)
  }

  function start(): void {
    if (timer !== null) return
    drained = false
    timer = setInterval(tick, intervalMs)
  }

  return {
    push(text: string) {
      if (!text) return
      pending += text
      start()
    },
    flush() {
      stop()
      if (pending) {
        visible += pending
        pending = ''
        options.onUpdate(visible)
      }
      if (!drained) {
        drained = true
        options.onDrained?.()
      }
    },
    cancel() {
      stop()
      pending = ''
      visible = ''
      drained = true
    },
    isIdle() {
      return pending.length === 0
    },
  }
}