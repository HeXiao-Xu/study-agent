import http, { type ApiEnvelope } from '@/api/http'
import type { TokenOut, UserOut } from '@/types/auth'

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload {
  username: string
  password: string
  nickname: string
  grade?: string
}

export async function login(payload: LoginPayload): Promise<TokenOut> {
  const resp = await http.post<ApiEnvelope<TokenOut>>('/auth/login', payload)
  return resp.data.data
}

export async function register(payload: RegisterPayload): Promise<UserOut> {
  const resp = await http.post<ApiEnvelope<UserOut>>('/auth/register', payload)
  return resp.data.data
}

export async function getMe(): Promise<UserOut> {
  const resp = await http.get<ApiEnvelope<UserOut>>('/auth/me')
  return resp.data.data
}