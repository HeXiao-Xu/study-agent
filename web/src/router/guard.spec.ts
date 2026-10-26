import { describe, expect, it } from 'vitest'

import { resolveAccess } from './guard'
import type { UserOut } from '@/types/auth'

const user: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

describe('resolveAccess', () => {
  it('allows public routes', () => {
    expect(
      resolveAccess({
        isPublic: true,
        hasToken: false,
        user: null,
        redirectPath: '/login',
      }),
    ).toEqual({ type: 'allow' })
  })

  it('redirects to login when token is missing', () => {
    expect(
      resolveAccess({
        isPublic: false,
        hasToken: false,
        user: null,
        redirectPath: '/notes?x=1',
      }),
    ).toEqual({ type: 'login', redirect: '/notes?x=1' })
  })

  it('allows when role matches', () => {
    expect(
      resolveAccess({
        isPublic: false,
        hasToken: true,
        user,
        roles: ['student'],
        redirectPath: '/notes',
      }),
    ).toEqual({ type: 'allow' })
  })

  it('forbids when role does not match', () => {
    expect(
      resolveAccess({
        isPublic: false,
        hasToken: true,
        user,
        roles: ['teacher'],
        redirectPath: '/notes',
      }),
    ).toEqual({ type: 'forbidden' })
  })

  it('fails closed when roles required but user is missing', () => {
    expect(
      resolveAccess({
        isPublic: false,
        hasToken: true,
        user: null,
        roles: ['student'],
        redirectPath: '/notes',
      }),
    ).toEqual({ type: 'forbidden' })
  })
})