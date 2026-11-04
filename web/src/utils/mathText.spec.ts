import { describe, expect, it } from 'vitest'

import { escapeHtml, renderMathToHtml } from './mathText'

describe('escapeHtml', () => {
  it('转义五个危险字符', () => {
    expect(escapeHtml(`<img src=x onerror="alert('1')"> &`)).toBe(
      '&lt;img src=x onerror=&quot;alert(&#39;1&#39;)&quot;&gt; &amp;',
    )
  })
})

describe('renderMathToHtml', () => {
  it('把行内公式渲染成 katex，其余文本转义', () => {
    const html = renderMathToHtml('已知 $f(x)=x^2$ <b>不是标签</b>')
    expect(html).toContain('katex')
    expect(html).toContain('&lt;b&gt;不是标签&lt;/b&gt;')
    expect(html).not.toContain('<b>')
  })

  it('块级公式用 displayMode', () => {
    expect(renderMathToHtml('$$\\frac{1}{2}$$')).toContain('katex-display')
  })

  it('公式之前的文本不会被吞', () => {
    const html = renderMathToHtml('求 $a$ 的范围')
    expect(html.startsWith('求 ')).toBe(true)
    expect(html).toContain('katex')
    expect(html.endsWith(' 的范围')).toBe(true)
  })

  it('未闭合的 $ 当普通文本，不抛错', () => {
    const html = renderMathToHtml('求 $x 的值')
    expect(html).not.toContain('katex')
    expect(html).toContain('求 $x 的值')
  })

  it('多行公式与列表也能渲染', () => {
    const html = renderMathToHtml('$a_1$\n$b_2$')
    expect(html.match(/katex/g)?.length ?? 0).toBeGreaterThanOrEqual(4)
  })

  it('空串与纯文本返回转义文本', () => {
    expect(renderMathToHtml('')).toBe('')
    expect(renderMathToHtml('没有公式')).toBe('没有公式')
  })
})