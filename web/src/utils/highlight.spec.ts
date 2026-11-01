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

  it('falls back to prose when the snippet contains latex', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<h2>单调性</h2><p>定义：区间内自变量增大时函数值也增大。</p>'
    const mark = highlightSnippet(
      root,
      '单调性\n定义：区间内自变量增大时函数值也增大。\n$$\\int_0^1 x^2 dx$$',
    )
    expect(mark).not.toBeNull()
    expect(root.querySelector('mark.citation-hit')).not.toBeNull()
  })

  it('does not drop block content when the snippet crosses blocks', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<h1>单调性</h1><p>定义：区间内自变量增大时函数值也增大。</p>' +
      '<p class="katex">∫</p>'
    highlightSnippet(
      root,
      '单调性\n定义：区间内自变量增大时函数值也增大。\n$$\\int_0^1 x^2 dx$$',
    )
    expect(root.textContent).toContain('定义：区间内自变量增大时函数值也增大。')
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