/** S6-3 导图导出：Mermaid SVG → Canvas → PNG，不新增导出依赖。 */

export function parseSvgSize(svgText: string): { width: number; height: number } {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml')
  const svg = doc.documentElement
  if (!svg || svg.nodeName.toLowerCase() !== 'svg') throw new Error('不是有效的 SVG')
  const width = Number.parseFloat(svg.getAttribute('width') ?? '')
  const height = Number.parseFloat(svg.getAttribute('height') ?? '')
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    return { width, height }
  }
  const viewBox = (svg.getAttribute('viewBox') ?? '')
    .trim()
    .split(/[\s,]+/)
    .map(Number)
  if (viewBox.length === 4 && viewBox[2]! > 0 && viewBox[3]! > 0) {
    return { width: viewBox[2]!, height: viewBox[3]! }
  }
  throw new Error('SVG 缺少尺寸')
}

export function mindmapFileName(taskId: number, date: string): string {
  return `学习导图-${taskId}-${date}.png`
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('导图图片加载失败'))
    image.src = url
  })
}

export async function downloadSvgAsPng(
  svgText: string,
  filename: string,
  scale = 2,
): Promise<void> {
  if (!svgText.trim()) throw new Error('没有可导出的导图')
  const { width, height } = parseSvgSize(svgText)
  const sourceUrl = URL.createObjectURL(
    new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }),
  )
  try {
    const image = await loadImage(sourceUrl)
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(width * scale)
    canvas.height = Math.round(height * scale)
    const ctx = canvas.getContext('2d')
    if (ctx === null) throw new Error('浏览器不支持 Canvas')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/png')
    })
    if (blob === null) throw new Error('导出 PNG 失败')
    const pngUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = pngUrl
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    // 立即 revoke 会让部分浏览器来不及开始下载
    setTimeout(() => URL.revokeObjectURL(pngUrl), 1000)
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}