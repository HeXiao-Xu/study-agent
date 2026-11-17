import { describe, expect, it } from 'vitest'

import { downloadSvgAsPng, mindmapFileName, parseSvgSize } from './exportMindmap'

describe('parseSvgSize', () => {
  it('reads width and height attributes', () => {
    expect(parseSvgSize('<svg width="800" height="600"></svg>')).toEqual({
      width: 800,
      height: 600,
    })
  })

  it('falls back to viewBox', () => {
    expect(parseSvgSize('<svg viewBox="0 0 1200 900"></svg>')).toEqual({
      width: 1200,
      height: 900,
    })
  })

  it('rejects an svg without size', () => {
    expect(() => parseSvgSize('<svg></svg>')).toThrow('SVG 缺少尺寸')
  })

  it('rejects non-svg content', () => {
    expect(() => parseSvgSize('<html></html>')).toThrow('不是有效的 SVG')
  })
})

describe('mindmapFileName', () => {
  it('includes task id and date', () => {
    expect(mindmapFileName(4, '2026-11-17')).toBe('学习导图-4-2026-11-17.png')
  })
})

describe('downloadSvgAsPng', () => {
  it('rejects an empty svg instead of downloading a blank png', async () => {
    await expect(downloadSvgAsPng('', 'x.png')).rejects.toThrow('没有可导出的导图')
  })
})