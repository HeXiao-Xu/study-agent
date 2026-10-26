export type UserRole = 'student' | 'teacher' | 'parent' | 'admin'

export interface UserOut {
  id: number
  username: string
  nickname: string
  grade: string | null
  role: UserRole
  created_at: string
}

export interface TokenOut {
  access_token: string
  token_type: string
  expires_in: number
  user: UserOut
}