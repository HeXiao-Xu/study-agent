import { describe, expect, it } from 'vitest'

import { NAV_GROUPS, NAV_ITEMS } from './nav'

describe('NAV_ITEMS', () => {
  it('has review, practice and reports entries', () => {
    const byName = Object.fromEntries(NAV_ITEMS.map((item) => [item.name, item.path]))
    expect(byName.review).toBe('/review')
    expect(byName.practice).toBe('/practice')
    expect(byName.reports).toBe('/reports')
    expect(byName['papers-list']).toBe('/papers')
    expect(byName.plan).toBeUndefined()
  })

  it('groups every item once, in order', () => {
    expect(NAV_GROUPS.map((group) => group.title)).toEqual([
      '知识中心',
      '试题训练',
      '复习总结',
      '智能助手',
    ])
    expect(NAV_GROUPS.map((group) => group.items.length)).toEqual([4, 4, 4, 2])
    expect(NAV_GROUPS.flatMap((group) => group.items)).toEqual(NAV_ITEMS)
    expect(NAV_ITEMS).toHaveLength(14)
  })

  it('keeps titles different from child labels to avoid redundancy', () => {
    for (const group of NAV_GROUPS) {
      expect(group.items.map((item) => item.label)).not.toContain(group.title)
    }
  })
})