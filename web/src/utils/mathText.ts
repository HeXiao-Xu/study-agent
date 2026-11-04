/**
 * 题干/答案里的 `$…$` 渲染（题库列表、错题列表共用）。
 *
 * 为什么不在列表里直接塞 `MdPreview`：md-editor-v3 是整块编辑器预览，20 行列表各挂一个
 * 太重；这里只处理行内公式，纯函数可脱离 DOM 断言，列表里用 CSS 折行截断。
 */
import katex from 'katex'

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => ESCAPES[char] ?? char)
}

/** 渲染单条公式；写坏（未闭合、非法命令）就退化成转义后的原文，绝不抛到页面。 */
function renderFormula(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      trust: false,
      output: 'html',
    })
  } catch {
    return escapeHtml(displayMode ? `$$${tex}$$` : `$${tex}$`)
  }
}

/**
 * 把 Markdown 片段里的公式渲染成 HTML，非公式部分一律转义。
 *
 * 只认成对的 `$$…$$` / `$…$`；未闭合的 `$` 留在文本里（当作普通字符），
 * 避免把「价格 $5 和 $6」这类内容误判成公式。
 */
export function renderMathToHtml(text: string): string {
  if (!text) return ''
  let html = ''
  let cursor = 0
  while (cursor < text.length) {
    const displayStart = text.indexOf('$$', cursor)
    const inlineStart = text.indexOf('$', cursor)
    if (inlineStart === -1) {
      html += escapeHtml(text.slice(cursor))
      break
    }
    if (displayStart !== -1 && displayStart === inlineStart) {
      const end = text.indexOf('$$', displayStart + 2)
      if (end === -1) {
        html += escapeHtml(text.slice(cursor))
        break
      }
      html += escapeHtml(text.slice(cursor, displayStart))
      html += renderFormula(text.slice(displayStart + 2, end), true)
      cursor = end + 2
      continue
    }
    const end = text.indexOf('$', inlineStart + 1)
    if (end === -1) {
      html += escapeHtml(text.slice(cursor))
      break
    }
    html += escapeHtml(text.slice(cursor, inlineStart))
    html += renderFormula(text.slice(inlineStart + 1, end), false)
    cursor = end + 1
  }
  return html
}