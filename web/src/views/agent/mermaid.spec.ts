import { describe, expect, it, vi } from 'vitest'

const fake = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(),
}))
vi.mock('mermaid', () => ({ default: fake }))

import { renderMermaid } from './mermaid'

describe('renderMermaid', () => {
  it('initializes once and returns svg', async () => {
    fake.render.mockResolvedValue({ svg: '<svg width="10" height="10"></svg>' })
    const first = await renderMermaid('mindmap\n  root((x))')
    const second = await renderMermaid('mindmap\n  root((y))')
    expect(first).toContain('<svg')
    expect(second).toContain('<svg')
    expect(fake.initialize).toHaveBeenCalledTimes(1)
    expect(fake.initialize).toHaveBeenCalledWith(
      expect.objectContaining({ startOnLoad: false, securityLevel: 'strict' }),
    )
  })

  it('rejects when mermaid returns no svg', async () => {
    fake.render.mockResolvedValue({ svg: 'not-svg' })
    await expect(renderMermaid('bad')).rejects.toThrow('Mermaid 未返回 SVG')
  })
})