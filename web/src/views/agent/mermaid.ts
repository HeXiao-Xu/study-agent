/** S6-3 Mermaid 渲染：只在这里初始化，页面/测试都走 renderMermaid。 */
import mermaid from 'mermaid'

let initialized = false

export async function renderMermaid(code: string): Promise<string> {
  if (!initialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'default',
      // 关掉 HTML 标签：foreignObject 会让 canvas 被标记为 tainted，导出 PNG 失败
      htmlLabels: false,
      fontFamily: 'system-ui, "PingFang SC", "Microsoft YaHei", sans-serif',
    })
    initialized = true
  }
  const { svg } = await mermaid.render(`weekly-mindmap-${Date.now()}`, code)
  if (!svg.includes('<svg')) throw new Error('Mermaid 未返回 SVG')
  return svg
}