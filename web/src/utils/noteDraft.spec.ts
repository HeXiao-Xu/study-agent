import { beforeEach, describe, expect, it } from 'vitest'

import { clearDraft, draftKey, isDraftStale, readDraft, writeDraft } from './noteDraft'

const draft = {
  title: '函数单调性',
  content_md: '# 笔记',
  subject_id: 7,
  tags: ['函数'],
  draftSavedAt: '2026-10-27T02:00:00.000Z',
  baseUpdatedAt: '2026-10-27T01:50:00+00:00',
}

describe('noteDraft', () => {
  beforeEach(() => localStorage.clear())

  it('roundtrips and clears', () => {
    writeDraft(5, draft)
    expect(readDraft(5)).toEqual(draft)
    clearDraft(5)
    expect(readDraft(5)).toBeNull()
  })

  it('uses distinct keys for new and existing notes', () => {
    expect(draftKey(null)).toBe('study-agent:note-draft:v1:new')
    expect(draftKey(5)).toBe('study-agent:note-draft:v1:5')
  })

  it('detects stale drafts by baseUpdatedAt', () => {
    expect(isDraftStale(draft, draft.baseUpdatedAt)).toBe(false)
    expect(isDraftStale(draft, '2026-10-27T03:00:00+00:00')).toBe(true)
    expect(isDraftStale({ ...draft, baseUpdatedAt: null }, null)).toBe(false)
  })

  it('drops malformed drafts', () => {
    localStorage.setItem(draftKey(5), '{bad')
    expect(readDraft(5)).toBeNull()
    expect(localStorage.getItem(draftKey(5))).toBeNull()
  })
})