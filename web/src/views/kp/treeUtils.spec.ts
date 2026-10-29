import { describe, expect, it } from 'vitest'

import type { KpNode } from '@/types/kp'
import {
  canDropNode,
  collectSiblingIds,
  dropParentId,
  findKpNode,
  flattenKpNodes,
  subtreeHeight,
} from './treeUtils'

function node(
  id: number,
  parent_id: number | null,
  level: number,
  children: KpNode[] = [],
): KpNode {
  return {
    id,
    subject_id: 1,
    parent_id,
    name: `节点${id}`,
    code: `KP-${id}`,
    level,
    description: null,
    exam_weight: null,
    order_no: 0,
    children,
  }
}

const leaf = node(3, 2, 3)
const child = node(2, 1, 2, [leaf])
const root = node(1, null, 1, [child])

describe('treeUtils', () => {
  it('finds a node recursively and flattens the tree', () => {
    expect(findKpNode([root], 3)?.code).toBe('KP-3')
    expect(findKpNode([root], 99)).toBeNull()
    expect(flattenKpNodes([root]).map((item) => item.id)).toEqual([1, 2, 3])
  })

  it('collects direct sibling ids', () => {
    expect(collectSiblingIds([root], 1)).toEqual([2])
    expect(collectSiblingIds([root], null)).toEqual([1])
    expect(collectSiblingIds([root], 2)).toEqual([3])
  })

  it('computes subtree height', () => {
    expect(subtreeHeight(root)).toBe(3)
    expect(subtreeHeight(child)).toBe(2)
    expect(subtreeHeight(leaf)).toBe(1)
  })

  it('resolves the target parent for a drop', () => {
    expect(dropParentId(child, 'inner')).toBe(2)
    expect(dropParentId(child, 'before')).toBe(1)
    expect(dropParentId(child, 'after')).toBe(1)
  })

  it('rejects invalid drop levels and locked roots', () => {
    const level4 = node(4, 3, 4)
    expect(canDropNode(root, child, 'inner')).toBe(false)
    expect(canDropNode(child, level4, 'inner')).toBe(false)
    expect(canDropNode(child, root, 'before')).toBe(false)
    expect(canDropNode(child, child, 'inner')).toBe(true)
  })
})
