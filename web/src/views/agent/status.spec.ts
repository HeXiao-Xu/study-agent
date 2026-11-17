import { describe, expect, it } from 'vitest'

import { statusLabel, statusType } from './status'

describe('agent status mapping', () => {
  it('maps every status to a Chinese label', () => {
    expect(statusLabel('pending')).toBe('排队中')
    expect(statusLabel('running')).toBe('生成中')
    expect(statusLabel('waiting_confirm')).toBe('等待确认')
    expect(statusLabel('succeeded')).toBe('已完成')
    expect(statusLabel('failed')).toBe('失败')
    expect(statusLabel('unknown')).toBe('unknown')
    expect(statusLabel(null)).toBe('未知')
  })

  it('maps tag types', () => {
    expect(statusType('succeeded')).toBe('success')
    expect(statusType('failed')).toBe('danger')
    expect(statusType('waiting_confirm')).toBe('warning')
    expect(statusType('running')).toBe('primary')
    expect(statusType('pending')).toBe('info')
    expect(statusType(undefined)).toBe('info')
  })
})