import type { UserOut, UserRole } from '@/types/auth'

export interface AccessInput {
  isPublic: boolean
  hasToken: boolean
  user: UserOut | null
  roles?: UserRole[]
  redirectPath: string
}

export type AccessDecision =
  | { type: 'allow' }
  | { type: 'login'; redirect: string }
  | { type: 'forbidden' }

export function resolveAccess(input: AccessInput): AccessDecision {
  if (input.isPublic) return { type: 'allow' }
  if (!input.hasToken) {
    return { type: 'login', redirect: input.redirectPath }
  }
  if (
    input.roles &&
    input.roles.length > 0 &&
    (!input.user || !input.roles.includes(input.user.role))
  ) {
    return { type: 'forbidden' }
  }
  return { type: 'allow' }
}