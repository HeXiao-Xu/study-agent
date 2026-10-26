# S2-11 前端应用骨架与登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付「知序」前端的视觉底座、应用布局、登录/注册页与路由守卫，让 S2-12–S2-14 能直接往骨架里填页面。

**Architecture:** 先立 CSS token 与基础组件，再实现 auth store/守卫纯函数，接着做登录页与布局壳，最后接真实后端走完整登录流程。页面只组合组件与 store，不直接写 URL/样式魔法值。

**Tech Stack:** Vue 3.5 + TypeScript 6 + Vite 8 + Pinia 4 + vue-router 5 + Element Plus 2.14；测试 Vitest + @vue/test-utils + jsdom。

**Spec:** `docs/spec/s2-11-frontend-shell.md`

## Global Constraints

- 桌面优先：1440 设计，侧栏 248px、顶栏 56px、内容最大 1160px、页面留白 32px。
- 视觉：暖白 `#F7F8FA`、深墨 `#1F2933`、主色 `#3B5BDB`、卡片圆角 10px、弱阴影。
- 品牌名「知序」；`document.title` 格式 `知序 · <title>`。
- 不新增运行时依赖；仅新增 devDependencies `vitest`、`@vue/test-utils`、`jsdom`（用户 2026-10-27 确认）。
- 受保护路由不写 `meta.public`；登录/403/404 为公开路由。
- token 存 localStorage；user 只放内存，刷新后 `/auth/me` 回填。
- 守卫判定 fail-closed：要求 roles 但 user 为空 → 403。
- 占位页明确标计划任务号，不放假数据。
- 前端校验规则与 `docs/API.md` §1 一致。
- Commit 使用 Conventional Commits，含 `(s2-11)`。

---

### Task 1: 测试基建、设计 token 与安全跳转

**Files:**
- Modify: `web/package.json`
- Create: `web/vitest.config.ts`
- Create: `web/src/test/setup.ts`
- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/base.css`
- Delete: `web/src/style.css`
- Modify: `web/src/main.ts`
- Create: `web/src/utils/redirect.ts`
- Test: `web/src/utils/redirect.spec.ts`

**Interfaces:**
- Consumes: 无
- Produces: `safeRedirect(raw: unknown): string`；CSS 变量 `--app-*`；`npm run test:run`

- [ ] **Step 1: 安装测试依赖与脚本**

```bash
cd web
npm install -D vitest @vue/test-utils jsdom
```

修改 `web/package.json` 的 `scripts`：

```json
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:run": "vitest run"
  },
```

- [ ] **Step 2: 写 safeRedirect 失败测试**

`web/src/utils/redirect.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { safeRedirect } from './redirect'

describe('safeRedirect', () => {
  it('keeps same-site path with query', () => {
    expect(safeRedirect('/notes?x=1')).toBe('/notes?x=1')
  })

  it('rejects protocol-relative and backslash paths', () => {
    expect(safeRedirect('//evil.com')).toBe('/notes')
    expect(safeRedirect('/\\evil.com')).toBe('/notes')
  })

  it('rejects non-string and empty values', () => {
    expect(safeRedirect(undefined)).toBe('/notes')
    expect(safeRedirect('')).toBe('/notes')
  })
})
```

- [ ] **Step 3: 运行确认失败**

Run: `cd web && npm run test:run -- src/utils/redirect.spec.ts`
Expected: FAIL，无法解析 `./redirect`

- [ ] **Step 4: 写 vitest 配置与 setup**

`web/vitest.config.ts`：

```ts
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

`web/src/test/setup.ts`：

```ts
import { vi } from 'vitest'

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)

vi.stubGlobal('matchMedia', (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
}))
```

- [ ] **Step 5: 实现 safeRedirect**

`web/src/utils/redirect.ts`：

```ts
export const DEFAULT_REDIRECT = '/notes'

/**
 * 登录后回跳只允许站内路径：拒绝 //host、反斜杠和非字符串，避免开放重定向。
 */
export function safeRedirect(raw: unknown): string {
  if (typeof raw !== 'string') return DEFAULT_REDIRECT
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) {
    return DEFAULT_REDIRECT
  }
  return raw
}
```

- [ ] **Step 6: 写设计 token 与基础样式**

`web/src/styles/tokens.css`：

```css
:root {
  --app-bg: #f7f8fa;
  --app-surface: #ffffff;
  --app-text: #1f2933;
  --app-text-secondary: #6b7280;
  --app-text-tertiary: #9aa3ae;
  --app-border: #e5e7eb;
  --app-primary: #3b5bdb;
  --app-primary-soft: #eef2ff;
  --app-primary-strong: #2f49b8;
  --app-success: #2f9e44;
  --app-warning: #e8590c;
  --app-danger: #c92a2a;

  --app-radius-sm: 8px;
  --app-radius-md: 10px;
  --app-radius-lg: 12px;
  --app-shadow-sm: 0 1px 2px rgba(16, 24, 40, 0.06);
  --app-shadow-lg: 0 12px 32px rgba(16, 24, 40, 0.12);

  --app-sidebar-width: 248px;
  --app-topbar-height: 56px;
  --app-content-max: 1160px;

  --el-color-primary: var(--app-primary);
  --el-color-primary-light-3: #6b82e5;
  --el-color-primary-light-5: #a9b6f0;
  --el-color-primary-light-7: #c7d0f5;
  --el-color-primary-light-8: #dce2f9;
  --el-color-primary-light-9: var(--app-primary-soft);
  --el-color-primary-dark-2: var(--app-primary-strong);
  --el-border-color: var(--app-border);
  --el-border-color-light: var(--app-border);
  --el-border-color-lighter: #eef0f3;
  --el-border-radius-base: var(--app-radius-sm);
  --el-font-size-base: 14px;
  --el-text-color-primary: var(--app-text);
  --el-text-color-regular: #4b5563;
  --el-text-color-secondary: var(--app-text-secondary);
  --el-bg-color-page: var(--app-bg);
  --el-bg-color: var(--app-surface);
  --el-box-shadow-light: var(--app-shadow-sm);
}
```

`web/src/styles/base.css`：

```css
* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
}

body {
  min-width: 1024px;
  background: var(--app-bg);
  color: var(--app-text);
  font-family:
    system-ui,
    'Segoe UI',
    'PingFang SC',
    'Microsoft YaHei',
    sans-serif;
  font-size: 14px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#app {
  min-height: 100vh;
}

a {
  color: inherit;
  text-decoration: none;
}

:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}

.page-enter-active,
.page-leave-active {
  transition: opacity 120ms ease-out;
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .page-enter-active,
  .page-leave-active {
    transition: none;
  }
}
```

删除 `web/src/style.css`，并改 `web/src/main.ts`：

```ts
/**
 * 前端入口：装配顺序固定 —— Pinia → Router → Element Plus（全局注册）。
 * Element Plus 按任务卡 S0-6 全局注册（体积换简单，需要时再改按需引入）。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

- [ ] **Step 7: 运行测试与构建**

Run: `cd web && npm run test:run -- src/utils/redirect.spec.ts`
Expected: `3 passed`

Run: `cd web && npm run build`
Expected: 构建成功，无 TS 错误

- [ ] **Step 8: 提交**

```bash
git add web/package.json web/package-lock.json web/vitest.config.ts web/src/test/setup.ts web/src/styles web/src/main.ts web/src/utils/redirect.ts web/src/utils/redirect.spec.ts
git rm web/src/style.css
git commit -m "feat(s2-11): 设计 token、基础样式与前端测试基建"
```

---

### Task 2: 认证类型、API、store 与守卫纯函数

**Files:**
- Create: `web/src/types/auth.ts`
- Create: `web/src/api/auth.ts`
- Modify: `web/src/stores/auth.ts`
- Create: `web/src/router/guard.ts`
- Test: `web/src/stores/auth.spec.ts`
- Test: `web/src/router/guard.spec.ts`

**Interfaces:**
- Consumes: `http`（`@/api/http`）、`ApiEnvelope`
- Produces:
  - `UserRole`、`UserOut`、`TokenOut`
  - `login/register/getMe`
  - `useAuthStore()`：`token/user/loading/isLoggedIn/roleLabel/setSession/clearSession/fetchMe`
  - `resolveAccess(input): AccessDecision`

- [ ] **Step 1: 写 store 与守卫失败测试**

`web/src/stores/auth.spec.ts`：

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserOut } from '@/types/auth'

vi.mock('@/api/auth', () => ({
  getMe: vi.fn(),
}))

import { getMe } from '@/api/auth'
import { useAuthStore } from './auth'

const user: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('setSession stores token in localStorage', () => {
    const store = useAuthStore()
    store.setSession('token-1', user)
    expect(store.token).toBe('token-1')
    expect(store.user?.nickname).toBe('测试用户_1')
    expect(localStorage.getItem('study-agent-token')).toBe('token-1')
  })

  it('clearSession clears state and localStorage', () => {
    const store = useAuthStore()
    store.setSession('token-1', user)
    store.clearSession()
    expect(store.token).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('study-agent-token')).toBeNull()
  })

  it('fetchMe writes user on success', async () => {
    vi.mocked(getMe).mockResolvedValue(user)
    const store = useAuthStore()
    store.setSession('token-1', null)
    await store.fetchMe()
    expect(store.user).toEqual(user)
  })
})
```

`web/src/router/guard.spec.ts`：

```ts
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/stores/auth.spec.ts src/router/guard.spec.ts`
Expected: FAIL，模块不存在且 store 无 `setSession`

- [ ] **Step 3: 写类型与 API**

`web/src/types/auth.ts`：

```ts
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
```

`web/src/api/auth.ts`：

```ts
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
```

- [ ] **Step 4: 写 store**

`web/src/stores/auth.ts`：

```ts
/**
 * 登录态唯一持有处：token 持久化，user 只存内存并在刷新后由 /auth/me 回填。
 */
import { defineStore } from 'pinia'

import type { UserOut } from '@/types/auth'

const TOKEN_KEY = 'study-agent-token'

const ROLE_LABELS: Record<UserOut['role'], string> = {
  student: '学生',
  teacher: '教师',
  parent: '家长',
  admin: '管理员',
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) ?? '',
    user: null as UserOut | null,
    loading: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    roleLabel: (state) => (state.user ? ROLE_LABELS[state.user.role] : ''),
  },
  actions: {
    setSession(token: string, user: UserOut | null) {
      this.token = token
      this.user = user
      localStorage.setItem(TOKEN_KEY, token)
    },
    clearSession() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
    async fetchMe() {
      // 动态导入避免 http → store → api → http 的静态模块环
      const { getMe } = await import('@/api/auth')
      this.user = await getMe()
    },
  },
})
```

- [ ] **Step 5: 写守卫纯函数**

`web/src/router/guard.ts`：

```ts
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
```

- [ ] **Step 6: 运行测试**

Run: `cd web && npm run test:run -- src/stores/auth.spec.ts src/router/guard.spec.ts`
Expected: `8 passed`

- [ ] **Step 7: 提交**

```bash
git add web/src/types/auth.ts web/src/api/auth.ts web/src/stores/auth.ts web/src/router/guard.ts web/src/stores/auth.spec.ts web/src/router/guard.spec.ts
git commit -m "feat(s2-11): 认证类型、store 与路由守卫判定"
```

---

### Task 3: 登录/注册页与 401 回跳

**Files:**
- Create: `web/src/views/LoginView.vue`
- Modify: `web/src/api/http.ts`
- Test: `web/src/views/LoginView.spec.ts`

**Interfaces:**
- Consumes: `login/register`、`useAuthStore`、`safeRedirect`
- Produces: 路由组件 `LoginView`；401 时 `/login?redirect=<当前路径>`

- [ ] **Step 1: 写登录页失败测试**

`web/src/views/LoginView.spec.ts`：

```ts
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/views/LoginView.spec.ts`
Expected: FAIL，`LoginView.vue` 不存在

- [ ] **Step 3: 实现 LoginView**

`web/src/views/LoginView.vue`：

```vue
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { login, register } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { safeRedirect } from '@/utils/redirect'

type Mode = 'login' | 'register'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mode = ref<Mode>('login')
const loading = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  nickname: '',
  grade: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^\S{3,50}$/,
      message: '用户名 3–50 个字符，不能含空格',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码 8–128 个字符', trigger: 'blur' },
  ],
  nickname: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { max: 50, message: '昵称不超过 50 字', trigger: 'blur' },
  ],
  grade: [{ max: 20, message: '年级不超过 20 字', trigger: 'blur' }],
}

const submitLabel = computed(() => (mode.value === 'login' ? '登录' : '注册并登录'))

function switchMode(next: Mode): void {
  if (mode.value === next) return
  mode.value = next
  formRef.value?.clearValidate()
}

async function onSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    if (mode.value === 'register') {
      await register({
        username: form.username.trim(),
        password: form.password,
        nickname: form.nickname.trim(),
        grade: form.grade.trim() || undefined,
      })
      ElMessage.success('注册成功，正在登录')
    }
    const session = await login({
      username: form.username.trim(),
      password: form.password,
    })
    auth.setSession(session.access_token, session.user)
    ElMessage.success('欢迎回来')
    await router.replace(safeRedirect(route.query.redirect))
  } catch {
    if (mode.value === 'register') mode.value = 'login'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="brand-panel">
      <div class="brand-mark">知序</div>
      <h1>把笔记、错题和知识点<br />连成一张可复习的网</h1>
      <p class="brand-lead">面向高中生的个性化学习工作台</p>
      <ul class="brand-points">
        <li><span>01</span>可溯源问答，每个结论都能点回原文</li>
        <li><span>02</span>笔记自动对齐已有知识点，不生造节点</li>
        <li><span>03</span>错题诊断与复习计划，按掌握度推进</li>
      </ul>
      <p class="brand-foot">Study Agent · 毕业设计演示版</p>
    </section>

    <section class="form-panel">
      <div class="form-card">
        <div class="tabs" role="tablist" aria-label="登录或注册">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'login'"
            :class="{ active: mode === 'login' }"
            @click="switchMode('login')"
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'register'"
            :class="{ active: mode === 'register' }"
            @click="switchMode('register')"
          >
            注册
          </button>
        </div>

        <h2>{{ mode === 'login' ? '欢迎回来' : '创建学生账号' }}</h2>
        <p class="form-hint">
          {{ mode === 'login' ? '继续你的学习记录' : '注册后自动登录，进入学习工作台' }}
        </p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="onSubmit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              name="username"
              autocomplete="username"
              placeholder="3–50 个字符，不能含空格"
              autofocus
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              name="password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="至少 8 个字符"
            />
          </el-form-item>
          <template v-if="mode === 'register'">
            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="form.nickname" name="nickname" placeholder="展示用昵称" />
            </el-form-item>
            <el-form-item label="年级（可选）" prop="grade">
              <el-input v-model="form.grade" name="grade" placeholder="如：高一" />
            </el-form-item>
          </template>

          <el-button
            class="login-submit"
            type="primary"
            native-type="submit"
            :loading="loading"
          >
            {{ submitLabel }}
          </el-button>
        </el-form>

        <p class="form-switch">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '注册学生账号' : '去登录' }}
          </button>
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(420px, 46%) 1fr;
  min-height: 100vh;
  background: var(--app-bg);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px 72px;
  background:
    radial-gradient(circle at 18% 12%, rgba(59, 91, 219, 0.12), transparent 42%),
    linear-gradient(160deg, #f2f4ff 0%, #f7f8fa 60%);
  border-right: 1px solid var(--app-border);
}

.brand-mark {
  width: fit-content;
  margin-bottom: 48px;
  padding: 6px 14px;
  border: 1px solid var(--app-primary);
  border-radius: 999px;
  color: var(--app-primary);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.brand-panel h1 {
  margin: 0 0 16px;
  font-size: 34px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.01em;
}

.brand-lead {
  margin: 0 0 40px;
  color: var(--app-text-secondary);
  font-size: 15px;
}

.brand-points {
  display: grid;
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--app-text-secondary);
}

.brand-points li {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.brand-points span {
  color: var(--app-primary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.08em;
}

.brand-foot {
  margin: 64px 0 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
}

.form-card {
  width: 380px;
  padding: 32px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
}

.tabs {
  display: flex;
  gap: 24px;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--app-border);
}

.tabs button {
  position: relative;
  padding: 0 0 10px;
  background: none;
  border: none;
  color: var(--app-text-secondary);
  font: inherit;
  cursor: pointer;
}

.tabs button.active {
  color: var(--app-primary);
  font-weight: 600;
}

.tabs button.active::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: var(--app-primary);
  content: '';
}

.form-card h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
}

.form-hint {
  margin: 0 0 24px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.login-submit {
  width: 100%;
  margin-top: 8px;
}

.form-switch {
  margin: 20px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  text-align: center;
}

.form-switch button {
  padding: 0;
  background: none;
  border: none;
  color: var(--app-primary);
  font: inherit;
  cursor: pointer;
}
</style>
```

- [ ] **Step 4: 改 401 回跳**

`web/src/api/http.ts` 在 `const http` 之后加入：

```ts
function redirectToLogin(): void {
  const current = router.currentRoute.value
  useAuthStore().clearSession()
  if (current.path === '/login') return
  void router.push({ path: '/login', query: { redirect: current.fullPath } })
}
```

响应拦截器两个分支都改为调用它：

```ts
    if (body && typeof body.code === 'number' && body.code !== 0) {
      if (body.code === 40100) {
        redirectToLogin()
      }
      ElMessage.error(body.message)
      return Promise.reject(new Error(body.message))
    }
```

```ts
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    const message = error.response?.data?.message ?? '网络异常，请稍后重试'
    if (error.response?.status === 401) {
      redirectToLogin()
    }
    ElMessage.error(message)
    return Promise.reject(error)
  },
```

- [ ] **Step 5: 运行测试**

Run: `cd web && npm run test:run -- src/views/LoginView.spec.ts`
Expected: `3 passed`

- [ ] **Step 6: 提交**

```bash
git add web/src/views/LoginView.vue web/src/views/LoginView.spec.ts web/src/api/http.ts
git commit -m "feat(s2-11): 登录注册页与 401 回跳"
```

---

### Task 4: 布局壳、占位页与路由守卫接线

**Files:**
- Create: `web/src/layouts/nav.ts`
- Create: `web/src/layouts/MainLayout.vue`
- Create: `web/src/components/layout/SideNav.vue`
- Create: `web/src/components/layout/TopBar.vue`
- Create: `web/src/components/common/PageHeader.vue`
- Create: `web/src/components/common/EmptyState.vue`
- Create: `web/src/views/ComingSoonView.vue`
- Create: `web/src/views/ForbiddenView.vue`
- Create: `web/src/views/NotFoundView.vue`
- Create: `web/src/router/meta.d.ts`
- Modify: `web/src/router/index.ts`
- Test: `web/src/layouts/MainLayout.spec.ts`

**Interfaces:**
- Consumes: `resolveAccess`、`useAuthStore`、`safeRedirect`
- Produces: `MainLayout`、`NAV_ITEMS`、完整路由表、`PageHeader`、`EmptyState`

- [ ] **Step 1: 写布局失败测试**

`web/src/layouts/MainLayout.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import type { UserOut } from '@/types/auth'
import MainLayout from './MainLayout.vue'

const user: UserOut = {
  id: 1,
  username: 's211_student',
  nickname: '测试用户_1',
  grade: '高一',
  role: 'student',
  created_at: '2026-10-27T00:00:00Z',
}

const Dummy = { template: '<div class="dummy-page" />' }

async function mountLayout(path = '/notes') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        component: MainLayout,
        children: [
          { path: 'notes', name: 'notes', component: Dummy },
          { path: 'files', name: 'files', component: Dummy },
          { path: 'knowledge', name: 'knowledge', component: Dummy },
          { path: 'qa', name: 'qa', component: Dummy },
          { path: 'mistakes', name: 'mistakes', component: Dummy },
          { path: 'plan', name: 'plan', component: Dummy },
        ],
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const auth = useAuthStore()
  auth.setSession('token-1', user)
  const wrapper = mount(MainLayout, {
    global: { plugins: [pinia, router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('MainLayout', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders six nav items', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(6)
  })

  it('marks current route as aria-current', async () => {
    const { wrapper } = await mountLayout('/notes')
    const active = wrapper.find('[data-testid="nav-link"][aria-current="page"]')
    expect(active.text()).toContain('笔记')
  })

  it('renders nickname and role label', async () => {
    const { wrapper } = await mountLayout()
    expect(wrapper.text()).toContain('测试用户_1')
    expect(wrapper.text()).toContain('学生')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/layouts/MainLayout.spec.ts`
Expected: FAIL，`MainLayout.vue` 不存在

- [ ] **Step 3: 写导航数据与基础组件**

`web/src/layouts/nav.ts`：

```ts
export interface NavItem {
  index: string
  label: string
  name: string
  path: string
}

export const NAV_ITEMS: NavItem[] = [
  { index: '01', label: '笔记', name: 'notes', path: '/notes' },
  { index: '02', label: '文件', name: 'files', path: '/files' },
  { index: '03', label: '知识库', name: 'knowledge', path: '/knowledge' },
  { index: '04', label: '智能问答', name: 'qa', path: '/qa' },
  { index: '05', label: '错题本', name: 'mistakes', path: '/mistakes' },
  { index: '06', label: '复习计划', name: 'plan', path: '/plan' },
]
```

`web/src/components/common/PageHeader.vue`：

```vue
<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <header class="page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="page-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  line-height: 1.4;
}

.page-header p {
  margin: 6px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.page-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
</style>
```

`web/src/components/common/EmptyState.vue`：

```vue
<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <div class="empty-mark" aria-hidden="true">·</div>
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
    <div class="empty-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 72px 24px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  text-align: center;
}

.empty-mark {
  display: grid;
  width: 40px;
  height: 40px;
  margin-bottom: 16px;
  place-items: center;
  color: var(--app-primary);
  font-size: 28px;
  line-height: 1;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.empty-state h2 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
}

.empty-state p {
  max-width: 460px;
  margin: 0;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.empty-actions {
  margin-top: 20px;
}
</style>
```

- [ ] **Step 4: 写占位页与错误页**

`web/src/views/ComingSoonView.vue`：

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'

const route = useRoute()
const router = useRouter()

const title = computed(() => String(route.meta.title ?? '功能'))
const description = computed(() => String(route.meta.description ?? ''))
const task = computed(() => String(route.meta.task ?? '后续任务'))
</script>

<template>
  <div>
    <PageHeader :title="title" :description="description" />
    <EmptyState
      title="功能建设中"
      :description="`计划在 ${task} 交付。当前只完成应用骨架，避免用假数据让你误判进度。`"
    >
      <el-button type="primary" @click="router.push('/notes')">返回笔记</el-button>
    </EmptyState>
  </div>
</template>
```

`web/src/views/ForbiddenView.vue`：

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="status-page">
    <p class="status-code">403</p>
    <h1>没有访问权限</h1>
    <p>当前账号不能访问这个页面。如果刚切换过账号，请重新登录。</p>
    <el-button type="primary" @click="router.replace('/notes')">返回首页</el-button>
  </div>
</template>

<style scoped>
.status-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  text-align: center;
}

.status-code {
  margin: 0;
  color: var(--app-primary);
  font-size: 48px;
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.status-page h1 {
  margin: 20px 0 8px;
  font-size: 20px;
}

.status-page p {
  margin: 0 0 24px;
  color: var(--app-text-secondary);
  font-size: 13px;
}
</style>
```

`web/src/views/NotFoundView.vue`：

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="status-page">
    <p class="status-code">404</p>
    <h1>页面不存在</h1>
    <p>链接可能已失效，或者地址输错了。</p>
    <el-button type="primary" @click="router.replace('/notes')">返回首页</el-button>
  </div>
</template>

<style scoped>
.status-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  text-align: center;
}

.status-code {
  margin: 0;
  color: var(--app-primary);
  font-size: 48px;
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.status-page h1 {
  margin: 20px 0 8px;
  font-size: 20px;
}

.status-page p {
  margin: 0 0 24px;
  color: var(--app-text-secondary);
  font-size: 13px;
}
</style>
```

- [ ] **Step 5: 写 SideNav、TopBar、MainLayout**

`web/src/components/layout/SideNav.vue`：

```vue
<script setup lang="ts">
import { useRoute } from 'vue-router'

import { NAV_ITEMS } from '@/layouts/nav'

const route = useRoute()
</script>

<template>
  <aside class="sidebar">
    <router-link class="brand" to="/notes">
      <span class="brand-name">知序</span>
      <span class="brand-sub">学习工作台</span>
    </router-link>

    <nav aria-label="主导航">
      <ul class="nav-list">
        <li v-for="item in NAV_ITEMS" :key="item.name">
          <router-link
            class="nav-link"
            :class="{ active: route.name === item.name }"
            :to="item.path"
            :aria-current="route.name === item.name ? 'page' : undefined"
            data-testid="nav-link"
          >
            <span class="nav-index" aria-hidden="true">{{ item.index }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </li>
      </ul>
    </nav>

    <div class="sidebar-foot">
      <slot name="user" />
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  width: var(--app-sidebar-width);
  height: 100vh;
  padding: 24px 16px 16px;
  background: var(--app-surface);
  border-right: 1px solid var(--app-border);
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 12px 24px;
}

.brand-name {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.brand-sub {
  color: var(--app-text-tertiary);
  font-size: 11px;
  letter-spacing: 0.16em;
}

.nav-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.nav-link {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  color: var(--app-text-secondary);
  font-size: 14px;
  border-left: 3px solid transparent;
  border-radius: var(--app-radius-sm);
  transition: background 120ms ease-out, color 120ms ease-out;
}

.nav-link:hover {
  color: var(--app-text);
  background: #f3f4f6;
}

.nav-link.active {
  color: var(--app-primary);
  font-weight: 500;
  background: var(--app-primary-soft);
  border-left-color: var(--app-primary);
}

.nav-index {
  color: var(--app-text-tertiary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.08em;
}

.nav-link.active .nav-index {
  color: var(--app-primary);
}

.sidebar-foot {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--app-border);
}
</style>
```

`web/src/components/layout/TopBar.vue`：

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const title = computed(() => String(route.meta.title ?? ''))
const initials = computed(() => auth.user?.nickname.slice(0, 1) ?? '知')

function onCommand(command: string): void {
  if (command !== 'logout') return
  auth.clearSession()
  ElMessage.success('已退出登录')
  void router.replace('/login')
}
</script>

<template>
  <header class="topbar">
    <nav class="crumbs" aria-label="面包屑">
      <router-link to="/notes">首页</router-link>
      <span class="separator" aria-hidden="true">/</span>
      <span class="current">{{ title }}</span>
    </nav>

    <el-dropdown trigger="click" @command="onCommand">
      <button class="user-trigger" type="button">
        <span class="avatar" aria-hidden="true">{{ initials }}</span>
        <span class="user-text">
          <span class="user-name">{{ auth.user?.nickname }}</span>
          <span class="user-role">{{ auth.roleLabel }}</span>
        </span>
        <span class="caret" aria-hidden="true">⌄</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item disabled>{{ auth.user?.username }}</el-dropdown-item>
          <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--app-topbar-height);
  padding: 0 32px;
  background: rgba(247, 248, 250, 0.88);
  border-bottom: 1px solid var(--app-border);
  backdrop-filter: blur(8px);
}

.crumbs {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.crumbs a:hover {
  color: var(--app-primary);
}

.separator {
  color: var(--app-text-tertiary);
}

.current {
  color: var(--app-text);
}

.user-trigger {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 4px 8px;
  background: none;
  border: none;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.user-trigger:hover {
  background: #eef0f3;
}

.avatar {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: var(--app-primary);
  font-size: 13px;
  font-weight: 600;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.user-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.3;
}

.user-name {
  color: var(--app-text);
  font-size: 13px;
}

.user-role {
  color: var(--app-text-tertiary);
  font-size: 11px;
}

.caret {
  color: var(--app-text-tertiary);
  font-size: 12px;
}
</style>
```

`web/src/layouts/MainLayout.vue`：

```vue
<script setup lang="ts">
import { storeToRefs } from 'pinia'

import SideNav from '@/components/layout/SideNav.vue'
import TopBar from '@/components/layout/TopBar.vue'
import { useAuthStore } from '@/stores/auth'

const { roleLabel } = storeToRefs(useAuthStore())
</script>

<template>
  <div class="app-shell">
    <SideNav>
      <template #user>
        <div class="user-card">
          <el-tag size="small" effect="plain">{{ roleLabel }}</el-tag>
        </div>
      </template>
    </SideNav>

    <div class="app-main">
      <TopBar />
      <main class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--app-bg);
}

.app-main {
  flex: 1;
  min-width: 0;
}

.app-content {
  max-width: var(--app-content-max);
  padding: 32px;
  margin: 0 auto;
}

.user-card {
  padding: 0 12px;
}
</style>
```

- [ ] **Step 6: 写路由与 meta 类型**

`web/src/router/meta.d.ts`：

```ts
import 'vue-router'

import type { UserRole } from '@/types/auth'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    title?: string
    task?: string
    description?: string
    roles?: UserRole[]
  }
}
```

`web/src/router/index.ts`：

```ts
/**
 * 路由与守卫（S2-11）：登录页公开，其余业务路由需登录；403/404 公开。
 */
import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '@/layouts/MainLayout.vue'
import { resolveAccess } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: MainLayout,
      redirect: '/notes',
      children: [
        {
          path: 'notes',
          name: 'notes',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '笔记',
            task: 'S2-12',
            description: '记录学习内容，系统会自动对齐已有知识点。',
          },
        },
        {
          path: 'files',
          name: 'files',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '文件',
            task: 'S2-13',
            description: '上传 PDF / Word / 图片，解析成可检索的笔记与切片。',
          },
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '知识库',
            task: 'S2-14',
            description: '浏览知识点树，处理待确认的笔记对齐。',
          },
        },
        {
          path: 'qa',
          name: 'qa',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '智能问答',
            task: 'S3-1',
            description: '基于个人知识库回答问题，并给出可点击的原文引用。',
          },
        },
        {
          path: 'mistakes',
          name: 'mistakes',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '错题本',
            task: 'S4-3',
            description: '按知识点归集错题，定位薄弱环节。',
          },
        },
        {
          path: 'plan',
          name: 'plan',
          component: () => import('@/views/ComingSoonView.vue'),
          meta: {
            title: '复习计划',
            task: 'S4-4',
            description: '按掌握度生成每日复习任务。',
          },
        },
        {
          path: 'debug',
          name: 'debug',
          component: () => import('@/views/DebugView.vue'),
          meta: { title: '诊断' },
        },
      ],
    },
    {
      path: '/403',
      name: 'forbidden',
      component: () => import('@/views/ForbiddenView.vue'),
      meta: { public: true, title: '无权限' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { public: true, title: '页面不存在' },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (to.name === 'login' && auth.token) return { path: '/notes' }
    return true
  }

  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!auth.user) {
    auth.loading = true
    try {
      await auth.fetchMe()
    } catch {
      auth.clearSession()
      return { path: '/login', query: { redirect: to.fullPath } }
    } finally {
      auth.loading = false
    }
  }

  const decision = resolveAccess({
    isPublic: false,
    hasToken: true,
    user: auth.user,
    roles: to.meta.roles,
    redirectPath: to.fullPath,
  })

  if (decision.type === 'forbidden') return { path: '/403' }
  if (decision.type === 'login') {
    return { path: '/login', query: { redirect: decision.redirect } }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `知序 · ${to.meta.title}` : '知序'
})

export default router
```

- [ ] **Step 7: 运行测试与构建**

Run: `cd web && npm run test:run -- src/layouts/MainLayout.spec.ts`
Expected: `3 passed`

Run: `cd web && npm run build`
Expected: 构建成功，无 TS 错误

- [ ] **Step 8: 提交**

```bash
git add web/src/layouts web/src/components web/src/views/ComingSoonView.vue web/src/views/ForbiddenView.vue web/src/views/NotFoundView.vue web/src/router
git commit -m "feat(s2-11): 应用布局、占位页与路由守卫接线"
```

---

### Task 5: 全量测试、真实联调与文档同步

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s2-11-frontend-shell.md`（§13 执行记录）
- Modify: `docs/plan/s2-11-frontend-shell.md`（执行记录）

- [ ] **Step 1: 全量自动化**

```bash
cd web
npm run test:run
npm run build
```

Expected：`17 passed`；构建成功。

- [ ] **Step 2: 起后端与前端**

```bash
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
cd web && npm run dev
```

- [ ] **Step 3: 真实流程手测（浏览器）**

访问 `http://localhost:5173/login`，按 spec §10.2 逐条执行：

1. 注册 `s211_student` → 自动登录 → `/notes` 占位页。
2. 刷新仍登录；顶栏昵称 + “学生”。
3. 退出 → 登录；访问 `/notes` → `?redirect=/notes`；登录后回 `/notes`。
4. DevTools 改坏 localStorage token → 刷新 → 401 清理并回登录。
5. `/not-exist` → 404；`/403` → 403；返回首页均回 `/notes`。
6. 1440×900 截图 4 张（登录、主布局、404、403），检查无横向滚动、无默认蓝紫按钮。
7. 清理测试账号。

把结果写进执行记录；若无法截图，让用户目视确认后记录“用户已确认”。

- [ ] **Step 4: 更新文档**

- `docs/PROGRESS.md`：当前状态“最近完成 S2-11 / 下一步 S2-12”；任务清单勾选 S2-11；新增/更新前端遗留（占位页多、无手机/深色模式、Element Plus 首包、无刷新 token）；变更日志新增 2026-10-27（S2-11）。
- `docs/DECISIONS.md`：新增 D-031，记录桌面优先、视觉方向、壳+基础组件、登录/注册自动登录、守卫 fail-closed、测试依赖与 17 条测试、真实联调结果、已知限制。
- `docs/AI协作开发实施计划.md`：`[ ] S2-11` → `[x] S2-11`（如总表有该行）。
- `docs/spec/s2-11-frontend-shell.md` §13：commit、测试数、实测结果、偏差。
- 本 plan 末尾追加“执行记录”。

- [ ] **Step 5: 提交**

```bash
git add docs
git commit -m "docs(s2-11): 前端骨架决策、进度与验收记录"
```

## Self-Review

**1. Spec coverage**

| Spec 章节 | 对应任务 |
|---|---|
| §4 设计系统（token/排版/间距/焦点） | Task 1 + Task 3/4 样式 |
| §5 信息架构与路由 | Task 4 |
| §6 认证、API、store、守卫、登录页 | Task 2 + Task 3 |
| §7 布局与基础组件 | Task 4 |
| §8 请求层与 401 | Task 3 |
| §9 17 条测试 | Task 1（3）+ Task 2（8）+ Task 3（3）+ Task 4（3） |
| §10 自动化与真实联调 | Task 5 |
| §11 已知限制 | Task 5 文档 |

无缺口。

**2. Placeholder scan**

- 无 TBD/TODO；所有代码步骤给出完整内容。
- 提示词/文案均为最终值，不需要执行者自行发挥。
- 真实联调需要浏览器操作，Step 3 给了逐条动作与记录要求，不是“自行验证”。

**3. Type consistency**

- `UserOut` / `UserRole` / `TokenOut` 在 Task 2 定义，Task 3/4 引用一致。
- `resolveAccess` 输入字段 `isPublic/hasToken/user/roles/redirectPath` 在 Task 2 定义，Task 4 调用一致。
- store 方法统一 `setSession/clearSession/fetchMe`；Task 3 的 `http.ts` 使用 `clearSession`（已在步骤中标注旧名风险）。
- 路由名 `notes/files/knowledge/qa/mistakes/plan` 在 `NAV_ITEMS`、路由表、测试三处一致。

**4. 已知执行风险与处理**

- Vitest 与 Vite 8 的版本兼容：若 `npm install` 出现 peer 冲突，先 `npm install -D vitest@latest @vue/test-utils@latest jsdom@latest`，仍冲突则记录版本并选兼容组合；不得跳过测试。
- Element Plus 表单校验在 jsdom 中异步：测试统一 `await flushPromises()` 两次；若仍不稳定，改为直接调用 `formRef.validate()` 的组件暴露方法（需 `defineExpose`），在 plan 执行记录中说明。
- `MainLayout` 的 `<transition mode="out-in">` 在测试中可能产生空档：测试挂载后 `await flushPromises()`，必要时 stub `transition`。
- 真实浏览器截图若环境无浏览器自动化，由用户目视确认并写记录，不伪造截图。

## 执行记录

- 任务 1–4 均按计划完成，commits：`0bc7745`、`6f89bbd`、`5f4a809`、`c394d4e`；文档同步提交单独一条。
- 自动化：17/17 tests、build 通过。
- 真实联调：注册→自动登录→刷新→退出→redirect→401→404/403 全通；布局 248/56/1160；console error 0；测试账号已删。
- 偏差：
  1. `api/auth.ts` 路径加 `/api/v1` 前缀（`API_PREFIX`），因为 `VITE_API_BASE` 是 host；plan 里写的是 `/auth/login`。
  2. `vitest.config.ts` 增 `server.deps.inline: ['element-plus']`；否则 Element Plus 的 async-validator 默认导入在 Vitest 下失效，校验恒 true（已用临时独立 spec 定位）。
  3. `src/test/setup.ts` 增内存 localStorage stub；Node 25 自带实现覆盖 jsdom 且无 `clear()`。
  4. 登录页空表单测试等待 150ms，绕开 Element Plus 100ms 错误态防抖。
  5. 新增 `components/common/StatusPage.vue` 供 403/404 复用，替代 plan 中的两份重复样式。
  6. MainLayout 测试的路由父级改为 `<router-view />`，避免直接挂载 + 路由再渲染导致 12 个导航项。
- 截图：登录、主布局、404、403 已生成在临时目录，未纳入仓库；待用户目视确认。
