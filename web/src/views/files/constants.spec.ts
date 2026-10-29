import { describe, expect, it } from 'vitest'

import {
  extensionOf,
  formatFileSize,
  formatFileType,
  isAcceptedFile,
} from '@/views/files/constants'

describe('file constants', () => {
  it('extracts lower-case extension', () => {
    expect(extensionOf('试卷.PDF')).toBe('pdf')
    expect(extensionOf('noext')).toBe('')
  })

  it('accepts only parseable documents', () => {
    expect(isAcceptedFile('试卷.pdf')).toBe(true)
    expect(isAcceptedFile('笔记.MD')).toBe(true)
    expect(isAcceptedFile('图.png')).toBe(false)
  })

  it('formats byte sizes', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1024)).toBe('1.0 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1024 * 1024)).toBe('1.0 MB')
  })

  it('maps file type labels', () => {
    expect(formatFileType('试卷.pdf', 'application/pdf')).toBe('PDF')
    expect(formatFileType('笔记.md', 'text/markdown')).toBe('Markdown')
    expect(
      formatFileType(
        '试卷.docx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ),
    ).toBe('Word')
  })
})