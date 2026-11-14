/** S5-7 复习清单的纯计算，页面只消费结果。 */
import type { ReviewItem } from '@/types/review'

export interface ReviewProgress {
  processed: number
  total: number
  percent: number
  label: string
}

export function progressOf(total: number, processed: number): ReviewProgress {
  const safeTotal = Number.isFinite(total) ? Math.max(0, Math.trunc(total)) : 0
  const safeProcessed = Number.isFinite(processed)
    ? Math.min(Math.max(0, Math.trunc(processed)), safeTotal)
    : 0
  const percent = safeTotal === 0 ? 0 : Math.round((safeProcessed / safeTotal) * 100)
  return {
    processed: safeProcessed,
    total: safeTotal,
    percent,
    label: `已处理 ${safeProcessed}/${safeTotal}`,
  }
}

export function minutesLabel(minutes: number): string {
  return `${Math.max(0, Math.trunc(minutes))} 分钟`
}

export function truncatedLabel(count: number | null): string {
  return count !== null && count > 0 ? `有 ${count} 项顺延到明天` : ''
}

export function reviewRefPath(
  item: Pick<ReviewItem, 'ref_type' | 'ref_id' | 'ref_available'>,
): string | null {
  if (!item.ref_available) return null
  return item.ref_type === 'mistake' ? `/mistakes/${item.ref_id}` : '/questions'
}