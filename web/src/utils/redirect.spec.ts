import { describe, expect, it } from 'vitest'

import { safeRedirect } from './redirect'

describe('safeRedirect', () => {
  it('keeps same-site path with query', () => {
    expect(safeRedirect('/notes?x=1')).toBe('/notes?x=1')
  })

  it('rejects protocol-relative and backslash paths', () => {
    expect(safeRedirect('//evil.com')).toBe('/notes')
    expect(safeRedirect('/\\evil.com')).toBe('/notes')
  })

  it('rejects non-string and empty values', () => {
    expect(safeRedirect(undefined)).toBe('/notes')
    expect(safeRedirect('')).toBe('/notes')
  })
})