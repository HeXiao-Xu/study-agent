import { describe, expect, it } from 'vitest'

import { extractImageIds, replaceImageTokens, replaceImageUrls } from './noteImages'

const md = '文字\n![图1](note-file://3)\n![图2](note-file://4)'

describe('noteImages', () => {
  it('extracts unique ids', () => {
    expect(extractImageIds(`${md}\n![重复](note-file://3)`)).toEqual([3, 4])
    expect(extractImageIds('没有图片')).toEqual([])
  })

  it('replaces tokens with blob urls', () => {
    const out = replaceImageTokens(
      md,
      new Map([
        [3, 'blob:a'],
        [4, 'blob:b'],
      ]),
    )
    expect(out).toBe('文字\n![图1](blob:a)\n![图2](blob:b)')
  })

  it('leaves unknown ids untouched', () => {
    expect(replaceImageTokens(md, new Map([[3, 'blob:a']]))).toBe(
      '文字\n![图1](blob:a)\n![图2](note-file://4)',
    )
  })

  it('replaces blob urls back to tokens', () => {
    const urls = new Map([
      ['blob:a', 'note-file://3'],
      ['blob:b', 'note-file://4'],
    ])
    expect(replaceImageUrls('![图1](blob:a) ![图2](blob:b)', urls)).toBe(
      '![图1](note-file://3) ![图2](note-file://4)',
    )
  })

  it('does not touch external image urls', () => {
    const input = '![外链](https://example.com/a.png)'
    expect(replaceImageUrls(input, new Map([['blob:a', 'note-file://3']]))).toBe(input)
  })
})