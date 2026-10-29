import type { KpNode } from '@/types/kp'

export type DropType = 'before' | 'after' | 'inner'

export function findKpNode(nodes: KpNode[], id: number | null): KpNode | null {
  if (id === null) return null
  for (const node of nodes) {
    if (node.id === id) return node
    const match = findKpNode(node.children, id)
    if (match) return match
  }
  return null
}

export function flattenKpNodes(nodes: KpNode[]): KpNode[] {
  return nodes.flatMap((node) => [node, ...flattenKpNodes(node.children)])
}

export function collectSiblingIds(nodes: KpNode[], parentId: number | null): number[] {
  return flattenKpNodes(nodes)
    .filter((node) => node.parent_id === parentId)
    .map((node) => node.id)
}

export function subtreeHeight(node: KpNode): number {
  if (!node.children.length) return 1
  return 1 + Math.max(...node.children.map(subtreeHeight))
}

export function dropParentId(dropNode: KpNode, type: DropType): number | null {
  return type === 'inner' ? dropNode.id : dropNode.parent_id
}

export function canDropNode(
  dragNode: KpNode,
  dropNode: KpNode,
  type: DropType,
): boolean {
  if (dragNode.parent_id === null) return false
  if (type !== 'inner' && dropNode.parent_id === null) return false
  const newLevel = type === 'inner' ? dropNode.level + 1 : dropNode.level
  return newLevel + subtreeHeight(dragNode) - 1 <= 4
}
