/** 掌握度配色（S4-7 起统一口径）：图谱与统计看板共用，避免两处硬编码。 */
export const COLOR_UNRATED = '#9aa4b2'
export const COLOR_LOW = '#e5484d'
export const COLOR_MID = '#f0b429'
export const COLOR_HIGH = '#22c55e'

/** <0.4 红、0.4–0.7 黄、≥0.7 绿；null = 未评估（灰）。 */
export function masteryColor(mastery: number | null): string {
  if (mastery === null) return COLOR_UNRATED
  if (mastery < 0.4) return COLOR_LOW
  if (mastery < 0.7) return COLOR_MID
  return COLOR_HIGH
}

export function masteryLabel(mastery: number | null): string {
  return mastery === null ? '未评估' : `掌握度 ${mastery.toFixed(2)}`
}