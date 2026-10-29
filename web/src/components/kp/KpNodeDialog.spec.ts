import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import KpNodeDialog from './KpNodeDialog.vue'

function mountDialog(mode: 'create' | 'edit' = 'create') {
  return mount(KpNodeDialog, {
    props: {
      modelValue: true,
      mode,
      parentId: 1,
      parentName: '高中数学',
      node:
        mode === 'edit'
          ? {
              id: 2,
              subject_id: 1,
              parent_id: 1,
              name: '函数',
              code: 'MATH-FUNC',
              level: 2,
              description: '原描述',
              exam_weight: 0.5,
              order_no: 0,
              children: [],
            }
          : null,
    },
    global: {
      plugins: [ElementPlus],
      stubs: {
        ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
      },
    },
  })
}

describe('KpNodeDialog', () => {
  it('submits name and code on create', async () => {
    const wrapper = mountDialog()
    await wrapper.find('input[name="kp-name"]').setValue('函数的单调性')
    await wrapper.find('input[name="kp-code"]').setValue('MATH-FUNC-01')
    await wrapper.find('[data-testid="kp-save"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
      name: '函数的单调性',
      code: 'MATH-FUNC-01',
      parent_id: 1,
    })
  })

  it('does not submit an empty create form', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="kp-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('keeps code read-only when editing', async () => {
    const wrapper = mountDialog('edit')
    expect(wrapper.find('input[name="kp-code"]').attributes('disabled')).toBeDefined()
    expect((wrapper.find('input[name="kp-code"]').element as HTMLInputElement).value).toBe(
      'MATH-FUNC',
    )
  })
})
