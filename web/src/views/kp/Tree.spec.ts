import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  getKpTree: vi.fn(),
  createKp: vi.fn(),
  updateKp: vi.fn(),
  deleteKp: vi.fn(),
  reorderKp: vi.fn(),
}))

import { createKp, deleteKp, getKpTree, reorderKp } from '@/api/kp'
import KpNodeDialog from '@/components/kp/KpNodeDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { KpNode, KpTree } from '@/types/kp'
import Tree from './Tree.vue'

const root: KpNode = {
  id: 1,
  subject_id: 1,
  parent_id: null,
  name: '高中数学',
  code: 'MATH',
  level: 1,
  description: null,
  exam_weight: null,
  order_no: 0,
  children: [
    {
      id: 2,
      subject_id: 1,
      parent_id: 1,
      name: '函数',
      code: 'MATH-FUNC',
      level: 2,
      description: null,
      exam_weight: null,
      order_no: 0,
      children: [],
    },
  ],
}

const treeData: KpTree = {
  subject: { id: 1, name: '高中数学', code: 'math', stage: '高中' },
  nodes: [root],
}

async function mountTree(role: 'student' | 'teacher' = 'teacher') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.setSession('token', {
    id: 1,
    username: '测试用户_1',
    nickname: '测试用户_1',
    grade: '高一',
    role,
    created_at: '2026-10-30T00:00:00Z',
  })
  vi.mocked(getKpTree).mockResolvedValue(treeData)
  const wrapper = mount(Tree, {
    props: { subject: 'math' },
    global: { plugins: [pinia, ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('Tree', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows management controls for a teacher', async () => {
    const wrapper = await mountTree('teacher')
    expect(wrapper.text()).toContain('新增根节点')
    expect(wrapper.text()).toContain('函数')
  })

  it('hides management controls for a student', async () => {
    const wrapper = await mountTree('student')
    expect(wrapper.text()).not.toContain('新增根节点')
    expect(wrapper.text()).toContain('只读')
  })

  it('submits a create payload from the dialog', async () => {
    vi.mocked(createKp).mockResolvedValue(root)
    const wrapper = await mountTree('teacher')
    await wrapper.find('[data-testid="add-root"]').trigger('click')
    const dialog = wrapper.findComponent(KpNodeDialog)
    dialog.vm.$emit('submit', {
      name: '新节点',
      code: 'MATH-NEW',
      description: null,
      exam_weight: null,
      parent_id: null,
    })
    await flushPromises()
    expect(createKp).toHaveBeenCalledWith(
      expect.objectContaining({
        subject: 'math',
        parent_id: null,
        name: '新节点',
        code: 'MATH-NEW',
      }),
    )
  })

  it('calls reorderKp with the post-drop sibling order', async () => {
    vi.mocked(reorderKp).mockResolvedValue()
    const wrapper = await mountTree('teacher')
    const elTree = wrapper.findComponent({ name: 'ElTree' })
    elTree.vm.$emit(
      'node-drop',
      {
        data: { ...treeData.nodes[0].children[0] },
        parent: {
          childNodes: [
            { data: treeData.nodes[0].children[0] },
            { data: { ...root, id: 3, name: '新节点', code: 'MATH-NEW' } },
          ],
        },
      },
      {
        data: treeData.nodes[0],
        childNodes: [
          { data: treeData.nodes[0].children[0] },
          { data: { ...root, id: 3, name: '新节点', code: 'MATH-NEW' } },
        ],
      },
      'inner',
      new Event('drop'),
    )
    await flushPromises()
    expect(reorderKp).toHaveBeenCalledWith({
      parent_id: 1,
      ordered_ids: [2, 3],
      moved_id: 2,
    })
  })

  it('deletes a child after confirmation', async () => {
    vi.mocked(deleteKp).mockResolvedValue()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = await mountTree('teacher')
    const deleteButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('删除'))
    expect(deleteButton).toBeTruthy()
    await deleteButton!.trigger('click')
    await flushPromises()
    expect(deleteKp).toHaveBeenCalledWith(2)
  })
})
