import { describe, expect, it } from 'vitest'

import {
  downloadReportImage,
  layoutReportImage,
  reportFileName,
} from './exportReportImage'

describe('layoutReportImage', () => {
  it('keeps equal inner width and vertical gaps', () => {
    const layout = layoutReportImage(
      [
        { width: 600, height: 300 },
        { width: 1200, height: 600 },
      ],
      1200,
    )
    expect(layout.width).toBe(1200)
    expect(layout.blocks[0]).toEqual({ x: 32, y: 110, width: 1136, height: 568 })
    expect(layout.blocks[1]!.width).toBe(1136)
    expect(layout.blocks[1]!.y).toBe(110 + 568 + 24)
    expect(layout.totalHeight).toBe(110 + 568 + 24 + 568 + 32)
  })

  it('handles no blocks without negative height', () => {
    const layout = layoutReportImage([], 1200)
    expect(layout.blocks).toEqual([])
    expect(layout.totalHeight).toBe(142)
  })
})

describe('reportFileName', () => {
  it('includes range and date', () => {
    expect(reportFileName('7d', '2026-11-14')).toBe('report-7d-2026-11-14.png')
  })
})

describe('downloadReportImage', () => {
  it('rejects an empty export instead of writing a blank image', async () => {
    await expect(
      downloadReportImage({
        range: '7d',
        subjectName: '高中数学',
        from: '2026-11-08',
        to: '2026-11-14',
        blocks: [],
      }),
    ).rejects.toThrow('没有可导出的图表')
  })
})