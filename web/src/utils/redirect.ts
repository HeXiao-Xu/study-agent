import type { UserRole } from '@/types/auth'

export const DEFAULT_REDIRECT = '/notes'

export function defaultRedirectForRole(role: UserRole): string {
  return role === 'teacher' || role === 'admin' ? '/knowledge' : DEFAULT_REDIRECT
}

/**
 * 登录后回跳只允许站内路径：拒绝 //host、反斜杠和非字符串，避免开放重定向。
 */
export function safeRedirect(raw: unknown, fallback: string = DEFAULT_REDIRECT): string {
  if (typeof raw !== 'string') return fallback
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) {
    return fallback
  }
  return raw
}
