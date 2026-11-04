import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MathText from './MathText.vue'

describe('MathText', () => {
  it('行内公式渲染成 KaTeX，而不是裸露的 $…$', () => {
    const wrapper = mount(MathText, { props: { text: '已知 $f(x)=x^2$，求 $f(1)$。' } })
    const html = wrapper.html()
    expect(html).toContain('katex')
    expect(wrapper.text()).not.toContain('$')
    expect(wrapper.text()).toContain('已知')
  })

  it('块级公式用 display mode', () => {
    const wrapper = mount(MathText, { props: { text: '$$x^2+y^2=1$$' } })
    expect(wrapper.html()).toContain('katex-display')
  })

  it('HTML 被转义，不会执行注入的标签', () => {
    const wrapper = mount(MathText, { props: { text: '<script>alert(1)</script> 已知 $x$' } })
    expect(wrapper.html()).not.toContain('<script>')
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
  })

  it('公式写错不抛错，退化成原文', () => {
    const wrapper = mount(MathText, { props: { text: '求 $\\frac{1}{$ 的值' } })
    expect(wrapper.text()).toContain('frac')
  })

  it('没有公式时原样显示，不产生空 katex 节点', () => {
    const wrapper = mount(MathText, { props: { text: '解方程，求取值范围。' } })
    expect(wrapper.html()).not.toContain('katex')
    expect(wrapper.text()).toBe('解方程，求取值范围。')
  })

  it('空串不崩', () => {
    const wrapper = mount(MathText, { props: { text: '' } })
    expect(wrapper.text()).toBe('')
  })
})