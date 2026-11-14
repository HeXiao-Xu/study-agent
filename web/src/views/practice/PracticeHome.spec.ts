import { mount, RouterLinkStub } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import PracticeHome from './PracticeHome.vue'

describe('PracticeHome', () => {
  it('renders three entries with correct targets', () => {
    const wrapper = mount(PracticeHome, {
      global: { plugins: [ElementPlus], stubs: { RouterLink: RouterLinkStub } },
    })
    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links.map((link) => link.props('to'))).toEqual([
      '/review',
      '/papers/generate',
      '/mistakes',
    ])
    expect(wrapper.text()).toContain('今日复习')
    expect(wrapper.text()).toContain('智能组卷')
    expect(wrapper.text()).toContain('错题回顾')
  })
})