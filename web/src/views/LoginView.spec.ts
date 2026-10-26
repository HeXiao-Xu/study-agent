import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  register: vi.fn(),
}))

import { login } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { TokenOut } from '@/types/auth'
import LoginView from './LoginView.vue'

const session: TokenOut = {
  access_token: 'token-1',
  token_type: 'bearer',
  expires_in: 86400,
  user: {
    id: 1,
    username: 's211_student',
    nickname: '测试用户_1',
    grade: '高一',
    role: 'student',
    created_at: '2026-10-27T00:00:00Z',
  },
}

async function mountLogin(path = '/login') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginView },
      { path: '/notes', component: { template: '<div>notes</div>' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(LoginView, {
    global: { plugins: [pinia, router, ElementPlus] },
  })
  return { wrapper, router, auth: useAuthStore() }
}

describe('LoginView', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('renders login and register tabs with fields', async () => {
    const { wrapper } = await mountLogin()
    expect(wrapper.text()).toContain('登录')
    expect(wrapper.text()).toContain('注册')
    expect(wrapper.find('input[name="username"]').exists()).toBe(true)
    expect(wrapper.find('input[name="password"]').exists()).toBe(true)
  })

  it('does not call api when form is empty', async () => {
    const { wrapper } = await mountLogin()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    // Element Plus 的错误态有 100ms 防抖，等它落到 DOM 再断言
    await new Promise((resolve) => setTimeout(resolve, 150))
    await flushPromises()
    expect(login).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入用户名')
  })

  it('stores session and redirects after login', async () => {
    vi.mocked(login).mockResolvedValue(session)
    const { wrapper, router, auth } = await mountLogin('/login?redirect=%2Fnotes')
    await wrapper.find('input[name="username"]').setValue('s211_student')
    await wrapper.find('input[name="password"]').setValue('Password123!')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await flushPromises()
    expect(login).toHaveBeenCalledWith({
      username: 's211_student',
      password: 'Password123!',
    })
    expect(auth.token).toBe('token-1')
    expect(router.currentRoute.value.path).toBe('/notes')
  })
})