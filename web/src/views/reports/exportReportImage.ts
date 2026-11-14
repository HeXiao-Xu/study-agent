/** S5-7 报告图表导出：ECharts dataURL + 原生 Canvas，不新增依赖。 */
export interface ReportImageBlock {
  dataUrl: string
  width: number
  height: number
}

export interface ReportImageLayout {
  width: number
  headerHeight: number
  margin: number
  gap: number
  blocks: Array<{ x: number; y: number; width: number; height: number }>
  totalHeight: number
}

export const REPORT_IMAGE_WIDTH = 1200
export const REPORT_IMAGE_HEADER = 110
export const REPORT_IMAGE_MARGIN = 32
export const REPORT_IMAGE_GAP = 24

export function layoutReportImage(
  blocks: Array<Pick<ReportImageBlock, 'width' | 'height'>>,
  width = REPORT_IMAGE_WIDTH,
): ReportImageLayout {
  const innerWidth = width - REPORT_IMAGE_MARGIN * 2
  let y = REPORT_IMAGE_HEADER
  const placed = blocks.map((block) => {
    const ratio = block.width > 0 ? innerWidth / block.width : 1
    const height = Math.max(1, Math.round(block.height * ratio))
    const row = { x: REPORT_IMAGE_MARGIN, y, width: innerWidth, height }
    y += height + REPORT_IMAGE_GAP
    return row
  })
  const totalHeight =
    placed.length === 0
      ? REPORT_IMAGE_HEADER + REPORT_IMAGE_MARGIN
      : y - REPORT_IMAGE_GAP + REPORT_IMAGE_MARGIN
  return {
    width,
    headerHeight: REPORT_IMAGE_HEADER,
    margin: REPORT_IMAGE_MARGIN,
    gap: REPORT_IMAGE_GAP,
    blocks: placed,
    totalHeight,
  }
}

export function reportFileName(range: string, date: string): string {
  return `report-${range}-${date}.png`
}

function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片加载失败'))
    image.src = dataUrl
  })
}

export async function downloadReportImage(options: {
  range: string
  subjectName: string
  from: string
  to: string
  blocks: ReportImageBlock[]
}): Promise<void> {
  if (options.blocks.length === 0) throw new Error('没有可导出的图表')
  const layout = layoutReportImage(options.blocks)
  const canvas = document.createElement('canvas')
  canvas.width = layout.width
  canvas.height = layout.totalHeight
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error('浏览器不支持 Canvas')

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#101828'
  ctx.font = '600 30px system-ui, "PingFang SC", "Microsoft YaHei", sans-serif'
  ctx.fillText(`学习报告 · ${options.range}`, layout.margin, 52)
  ctx.fillStyle = '#667085'
  ctx.font = '14px system-ui, "PingFang SC", "Microsoft YaHei", sans-serif'
  ctx.fillText(
    `${options.subjectName} · ${options.from} ~ ${options.to}（UTC）`,
    layout.margin,
    82,
  )

  for (let index = 0; index < options.blocks.length; index += 1) {
    const image = await loadImage(options.blocks[index]!.dataUrl)
    const box = layout.blocks[index]!
    ctx.drawImage(image, box.x, box.y, box.width, box.height)
  }

  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob(resolve, 'image/png')
  })
  if (blob === null) throw new Error('导出 PNG 失败')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = reportFileName(options.range, options.to)
  link.click()
  URL.revokeObjectURL(url)
}