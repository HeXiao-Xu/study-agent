export function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

interface CharRef {
  node: Text
  offset: number
}

function isBlockElement(element: HTMLElement): boolean {
  return /^(ADDRESS|ARTICLE|ASIDE|BLOCKQUOTE|DIV|DL|FIELDSET|FIGCAPTION|FIGURE|FOOTER|FORM|H[1-6]|HEADER|HR|LI|MAIN|NAV|OL|P|PRE|SECTION|TABLE|UL)$/.test(
    element.tagName,
  )
}

function collectChars(root: HTMLElement): { text: string; refs: CharRef[] } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const refs: CharRef[] = []
  let text = ''
  let previousSpace = true
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    const parent = node.parentElement
    if (!parent || ['SCRIPT', 'STYLE'].includes(parent.tagName)) continue
    if (isBlockElement(parent) && parent.firstChild === node && text.length > 0 && !previousSpace) {
      text += ' '
      refs.push({ node, offset: 0 })
      previousSpace = true
    }
    const raw = node.data
    for (let offset = 0; offset < raw.length; offset += 1) {
      const char = raw[offset]
      if (/\s/.test(char)) {
        if (!previousSpace && text.length > 0) {
          text += ' '
          refs.push({ node, offset })
          previousSpace = true
        }
        continue
      }
      text += char
      refs.push({ node, offset })
      previousSpace = false
    }
  }
  const trimmed = text.replace(/\s+$/, '')
  return { text: trimmed, refs: refs.slice(0, trimmed.length) }
}

function markNode(node: Text, start: number, end: number): HTMLElement | null {
  if (start >= end) return null
  const range = document.createRange()
  range.setStart(node, start)
  range.setEnd(node, end)
  const mark = document.createElement('mark')
  mark.className = 'citation-hit'
  try {
    range.surroundContents(mark)
    return mark
  } catch {
    return null
  }
}

function candidateNeedles(snippet: string): string[] {
  const full = normalizeText(snippet)
  if (!full) return []
  const withoutMath = normalizeText(
    snippet.replace(/\$\$[\s\S]*?\$\$/g, ' ').replace(/\$[^$\n]*\$/g, ' '),
  )
  const proseOnly = normalizeText(
    snippet
      .split(/\r?\n/)
      .filter((line) => !line.includes('$'))
      .join(' '),
  )
  return [...new Set([full, withoutMath, proseOnly].filter(Boolean))]
}

export function highlightSnippet(
  root: HTMLElement,
  snippet: string,
): HTMLElement | null {
  const { text, refs } = collectChars(root)
  for (const needle of candidateNeedles(snippet)) {
    const start = text.indexOf(needle)
    if (start === -1) continue
    const end = start + needle.length
    const selected = refs.slice(start, end)
    const byNode = new Map<Text, { start: number; end: number }>()
    for (const ref of selected) {
      const current = byNode.get(ref.node)
      if (current === undefined) {
        byNode.set(ref.node, { start: ref.offset, end: ref.offset + 1 })
      } else {
        current.start = Math.min(current.start, ref.offset)
        current.end = Math.max(current.end, ref.offset + 1)
      }
    }
    const entries = [...byNode.entries()].sort((a, b) => {
      if (a[0] === b[0]) return 0
      return a[0].compareDocumentPosition(b[0]) & Node.DOCUMENT_POSITION_FOLLOWING
        ? -1
        : 1
    })
    let first: HTMLElement | null = null
    for (const [node, range] of entries.reverse()) {
      const mark = markNode(node, range.start, range.end)
      if (mark) first = mark
    }
    first?.scrollIntoView?.({ block: 'center' })
    return first
  }
  return null
}

export function scrollToHeading(
  root: HTMLElement,
  headingPath: string | null,
): HTMLElement | null {
  const last = headingPath?.split('/').filter(Boolean).pop()
  if (!last) return null
  const headings = [...root.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')]
  const target = headings.find((item) => item.textContent?.includes(last))
  target?.scrollIntoView?.({ block: 'center' })
  return target ?? null
}