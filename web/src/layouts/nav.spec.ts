import { describe, expect, it } from 'vitest'

import { NAV_ITEMS } from './nav'

describe('NAV_ITEMS', () => {
  it('has review, practice and reports entries', () => {
    const byName = Object.fromEntries(NAV_ITEMS.map((item) => [item.name, item.path]))
    expect(byName.review).toBe('/review')
    expect(byName.practice).toBe('/practice')
    expect(byName.reports).toBe('/reports')
    expect(byName['papers-list']).toBe('/papers')
    expect(byName.plan).toBeUndefined()
  })
})