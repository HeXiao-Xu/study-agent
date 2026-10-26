import { describe, expect, it } from 'vitest'

import { normalizeListQuery, toListQuery, toNoteListParams } from './listQuery'

describe('listQuery', () => {
  it('normalizes invalid values to defaults', () => {
    expect(normalizeListQuery({ q: '  函数 ', sort: 'bad', page: '0', page_size: '7' })).toEqual({
      q: '函数',
      subjectId: null,
      sort: 'updated',
      page: 1,
      pageSize: 10,
    })
  })

  it('maps sort to API params', () => {
    expect(
      toNoteListParams({ q: '导数', subjectId: 7, sort: 'title', page: 2, pageSize: 20 }),
    ).toMatchObject({
      q: '导数',
      subject_id: 7,
      sort_by: 'title',
      order: 'asc',
      page: 2,
      page_size: 20,
    })
  })

  it('omits defaults from the URL', () => {
    expect(
      toListQuery({ q: '', subjectId: null, sort: 'updated', page: 1, pageSize: 10 }),
    ).toEqual({})
    expect(
      toListQuery({ q: '函数', subjectId: 7, sort: 'created', page: 2, pageSize: 50 }),
    ).toEqual({ q: '函数', subject_id: '7', sort: 'created', page: '2', page_size: '50' })
  })
})