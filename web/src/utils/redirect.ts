export const DEFAULT_REDIRECT = '/notes'

/**
 * 登录后回跳只允许站内路径：拒绝 //host、反斜杠和非字符串，避免开放重定向。
 */
export function safeRedirect(raw: unknown): string {
  if (typeof raw !== 'string') return DEFAULT_REDIRECT
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) {
    return DEFAULT_REDIRECT
  }
  return raw
}