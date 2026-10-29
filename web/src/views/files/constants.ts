import type { ParseStatus } from '@/types/files'

export const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'md', 'txt'] as const
export const ACCEPT_ATTR = '.pdf,.docx,.md,.txt'
export const POLL_INTERVAL_MS = 3_000
export const POLL_TIMEOUT_MS = 5 * 60 * 1_000

export const STATUS_LABELS: Record<ParseStatus, string> = {
  pending: '待解析',
  parsing: '解析中',
  done: '已完成',
  failed: '失败',
}

export function extensionOf(filename: string): string {
  const index = filename.lastIndexOf('.')
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : ''
}

export function isAcceptedFile(filename: string): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(filename))
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`
}

export function formatFileType(filename: string, mime: string): string {
  const ext = extensionOf(filename)
  if (ext === 'pdf') return 'PDF'
  if (ext === 'docx') return 'Word'
  if (ext === 'md') return 'Markdown'
  if (ext === 'txt') return 'TXT'
  return mime || ext.toUpperCase() || '文件'
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}