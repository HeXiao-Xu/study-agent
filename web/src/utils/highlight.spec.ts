import { describe, expect, it } from 'vitest'

import { highlightSnippet, scrollToHeading } from './highlight'

describe('highlightSnippet', () => {
  it('marks a plain substring and returns the mark', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>错位相减法很好用</p>'
    const mark = highlightSnippet(root, '错位相减')
    expect(mark?.textContent).toBe('错位相减')
    expect(root.querySelector('mark.citation-hit')).not.toBeNull()
  })

  it('matches across nested text nodes', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>先看<strong>错位</strong>相减法</p>'
    const mark = highlightSnippet(root, '错位相减法')
    expect(mark).not.toBeNull()
    expect(root.textContent).toContain('错位相减法')
  })

  it('normalizes whitespace and returns null when missing', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>第一段   第二段</p>'
    expect(highlightSnippet(root, '第一段 第二段')).not.toBeNull()
    expect(highlightSnippet(root, '不存在')).toBeNull()
  })
})

describe('scrollToHeading', () => {
  it('finds the last heading segment', () => {
    const root = document.createElement('div')
    root.innerHTML = '<h2>数列/错位相减法</h2>'
    expect(scrollToHeading(root, '数列/错位相减法')?.textContent).toBe(
      '数列/错位相减法',
    )
    expect(scrollToHeading(root, null)).toBeNull()
  })
})