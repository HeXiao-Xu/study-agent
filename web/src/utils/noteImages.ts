const TOKEN_PATTERN = /!\[([^\]]*)\]\(note-file:\/\/(\d+)\)/g

export function extractImageIds(markdown: string): number[] {
  const ids = new Set<number>()
  for (const match of markdown.matchAll(TOKEN_PATTERN)) {
    ids.add(Number(match[2]))
  }
  return [...ids]
}

export function replaceImageTokens(
  markdown: string,
  urlById: ReadonlyMap<number, string>,
): string {
  return markdown.replace(TOKEN_PATTERN, (whole, alt: string, rawId: string) => {
    const url = urlById.get(Number(rawId))
    return url ? `![${alt}](${url})` : whole
  })
}

export function replaceImageUrls(
  markdown: string,
  tokenByUrl: ReadonlyMap<string, string>,
): string {
  let result = markdown
  for (const [url, token] of tokenByUrl) {
    result = result.split(url).join(token)
  }
  return result
}