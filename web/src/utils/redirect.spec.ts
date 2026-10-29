import { describe, expect, it } from 'vitest'

import { defaultRedirectForRole, safeRedirect } from './redirect'

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

  it('uses the supplied fallback for missing or unsafe redirects', () => {
    expect(safeRedirect(undefined, '/knowledge')).toBe('/knowledge')
    expect(safeRedirect('//evil.com', '/knowledge')).toBe('/knowledge')
  })
})

describe('defaultRedirectForRole', () => {
  it('sends teachers and admins to knowledge', () => {
    expect(defaultRedirectForRole('teacher')).toBe('/knowledge')
    expect(defaultRedirectForRole('admin')).toBe('/knowledge')
  })

  it('keeps students and parents on notes', () => {
    expect(defaultRedirectForRole('student')).toBe('/notes')
    expect(defaultRedirectForRole('parent')).toBe('/notes')
  })
})