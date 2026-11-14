export const DIFFICULTY_LABELS = ['很简单', '简单', '中等', '较难', '最难'] as const

export interface WeightedItem {
  key: string
  weight: number
}

/**
 * 与后端 largest_remainder 同口径：先按整数部分分配，再按小数部分补足；
 * 并列时保持传入顺序，保证同样输入得到同样预览。
 */
export function allocateCounts(items: WeightedItem[], total: number): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const item of items) {
    counts[item.key] = 0
  }
  const positive = items
    .map((item, index) => ({ ...item, index, weight: Math.max(0, Number(item.weight) || 0) }))
    .filter((item) => item.weight > 0)
  const weightSum = positive.reduce((sum, item) => sum + item.weight, 0)
  const target = Math.max(0, Math.trunc(total))
  if (weightSum <= 0 || target === 0) return counts

  const raw = positive.map((item) => ({
    ...item,
    exact: (item.weight / weightSum) * target,
  }))
  let allocated = 0
  for (const item of raw) {
    const floor = Math.floor(item.exact)
    counts[item.key] = floor
    allocated += floor
  }
  const remainderOrder = [...raw].sort(
    (a, b) => b.exact - Math.floor(b.exact) - (a.exact - Math.floor(a.exact)) || a.index - b.index,
  )
  for (let i = 0; i < target - allocated; i += 1) {
    counts[remainderOrder[i % remainderOrder.length]!.key] += 1
  }
  return counts
}

export function qtypeCounts(
  ratios: Record<string, number>,
  total: number,
): Record<string, number> {
  return allocateCounts(
    ['单选', '多选', '填空', '解答'].map((key) => ({
      key,
      weight: ratios[key] ?? 0,
    })),
    total,
  )
}

export function difficultyCounts(weights: number[], total: number): Record<number, number> {
  const counts = allocateCounts(
    weights.map((weight, index) => ({ key: String(index + 1), weight })),
    total,
  )
  return Object.fromEntries(
    Object.entries(counts).map(([key, value]) => [Number(key), value]),
  ) as Record<number, number>
}