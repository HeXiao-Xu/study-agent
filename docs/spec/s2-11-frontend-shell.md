# S2-11 前端应用骨架与登录 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-11
- 日期：2026-10-27
- 状态：设计已逐节确认（桌面优先 / 克制研究工作台 / 全应用骨架 + 占位页 / 登录+学生注册 / 壳+基础组件层 / 允许新增前端测试依赖）
- 上游：S0-6 前端工程（Vue 3.5 + Vite 8 + Element Plus 2.14 + Pinia 4 + vue-router 5）、S2-2 认证接口、S2-10 对齐接口
- 下游：S2-12 笔记、S2-13 文件、S2-14 知识点树与待确认队列、S3 问答
- 产物：设计 token、`MainLayout`、`LoginView`、路由守卫、`api/auth.ts`、占位页与 Vitest 测试

## 1. 目标

1. 建立应用级视觉与布局底座：颜色/字号/间距/圆角 token，Element Plus 变量同步覆盖，后续页面不再各写一套样式。
2. 交付可用的登录/注册页：学生可自助注册，注册后自动登录；表单校验与 API.md 一致。
3. 交付全应用导航骨架：6 个一级模块 + 顶栏 + 用户区 + 统一占位页；当前不存在的功能明确标注计划任务号，不放假数据。
4. 路由守卫：未登录跳登录并保留 `redirect`；已登录访问登录页回首页；角色不符进 403；刷新后通过 `/auth/me` 恢复用户。
5. 统一请求层与错误处理：按模块薄封装 API，401 清理登录态并跳登录，不重复弹错。
6. 建立前端测试基线：Vitest + @vue/test-utils + jsdom，覆盖守卫、store、登录页、布局。

## 2. 范围

### 2.1 做

- `src/styles/tokens.css` + `src/styles/base.css`（reset/排版/焦点/过渡），在 `main.ts` 中于 Element Plus CSS 之后引入。
- `src/layouts/MainLayout.vue`、`src/components/layout/{SideNav,TopBar}.vue`。
- `src/components/common/{PageHeader,EmptyState}.vue`（ErrorState/StatusTag 等真正用到时再加，避免空组件）。
- `src/views/{LoginView,ComingSoonView,ForbiddenView,NotFoundView}.vue`；`DebugView` 保留为登录后可访问的诊断页。
- `src/router/index.ts` 重写；`src/router/guard.ts` 纯函数 + `beforeEach`；`src/router/meta.d.ts` 扩展 `RouteMeta`。
- `src/stores/auth.ts` 扩展；`src/api/auth.ts`、`src/types/auth.ts`、`src/utils/redirect.ts`。
- `src/api/http.ts` 的 401 处理补 `redirect`；避免登录页重复跳转。
- 测试：`src/router/guard.spec.ts`、`src/stores/auth.spec.ts`、`src/views/LoginView.spec.ts`、`src/layouts/MainLayout.spec.ts`。
- `package.json` 新增 devDependencies：`vitest`、`@vue/test-utils`、`jsdom`；`test` / `test:run` 脚本；`vitest.config.ts`。

### 2.2 不做

- 不做真实笔记/文件/知识点/问答/错题/复习计划页面（后续卡）。
- 不做首页仪表盘、图表、学习统计。
- 不做深色模式、手机适配、i18n、全局搜索（⌘K 等 S2-12 有真实数据后再上）。
- 不引入任何新运行时依赖；不引入 Tailwind、组件库二次封装框架、TanStack Query。
- 不改后端接口与数据库。
- 不做“记住我”开关、找回密码、邮箱验证、刷新 token（后端 S2-2 未提供）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 桌面优先：按 1440 设计；侧栏 248px、顶栏 56px、内容最大 1160px、页面留白 32px；1024–1279 侧栏 220px | 答辩投影与笔记本为主；不做手机版拖慢进度 |
| 2 | 视觉“克制研究工作台”：暖白底、深墨字、靛蓝主色、弱阴影、细分割线 | 长时间读写的学习工具，避免后台模板感与高饱和疲劳 |
| 3 | 壳 + 基础组件层，而不是逐页拼 Element Plus | 后续 4 张前端卡复用，风格不漂 |
| 4 | 导航用“两位序号 + 文字”，不引入图标库 | `@element-plus/icons-vue` 非直接依赖，避免为图标新增依赖；序号更贴合“研究工作台”气质 |
| 5 | 占位页统一 `ComingSoonView`，由 `route.meta` 注入模块名、说明、计划任务号 | 不放假表格/假统计；答辩时能明确区分已完成与未完成 |
| 6 | 登录/注册同页，注册成功自动用刚填账号登录 | 现场可完整演示注册 → 写笔记 → 对齐；少一次手动登录 |
| 7 | token 持久化 localStorage，user 只放内存、刷新后 `/auth/me` 回填 | 角色以服务端为权威；沿用 S0-6 已有持久化方式 |
| 8 | 守卫判定抽成纯函数 `resolveAccess`，`beforeEach` 只负责取数与跳转 | 可单测、后续加角色页不改判定逻辑 |
| 9 | 所有受保护路由默认只要登录；`meta.roles` 预留但本卡不启用 | 当前各业务接口权限不同，页面级角色限制等对应卡再加；守卫能力先测好 |
| 10 | 401 统一在 `http.ts` 处理，保留当前 `fullPath` 为 `redirect`，登录页不重复跳 | 避免刷新/并发请求多次弹错、丢回去路径 |
| 11 | Element Plus 继续全局注册 | S0-6 已定；按需引入的收益不值得在功能卡里重构 |
| 12 | 测试放 `src/**/*.spec.ts`，由 `vue-tsc -b` 一并类型检查 | 测试也纳入构建类型安全；Vitest 只跑不打包 |
| 13 | 不新增运行时依赖；测试依赖经用户确认（2026-10-27） | AGENTS §2.1 |

## 4. 设计系统

### 4.1 颜色

| Token | 值 | 用途 |
|---|---|---|
| `--app-bg` | `#F7F8FA` | 页面底色 |
| `--app-surface` | `#FFFFFF` | 卡片、弹层、输入区 |
| `--app-text` | `#1F2933` | 标题与正文 |
| `--app-text-secondary` | `#6B7280` | 说明、元信息 |
| `--app-text-tertiary` | `#9AA3AE` | 占位、禁用 |
| `--app-border` | `#E5E7EB` | 1px 分割线/边框 |
| `--app-primary` | `#3B5BDB` | 主按钮、选中态、链接 |
| `--app-primary-soft` | `#EEF2FF` | 选中底、标签底 |
| `--app-primary-strong` | `#2F49B8` | hover/active |
| `--app-success` | `#2F9E44` | 成功状态 |
| `--app-warning` | `#E8590C` | 待确认/警告 |
| `--app-danger` | `#C92A2A` | 错误/危险操作 |

Element Plus 变量同步覆盖：`--el-color-primary` 及 3/5/7/8/9 浅色阶、`--el-border-color`、`--el-border-radius-base`、`--el-font-size-base`、`--el-text-color-primary/regular/secondary`、`--el-bg-color-page`。

### 4.2 排版

- 字体：`system-ui, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif`；公式交给 KaTeX（S2-12 引入）。
- 正文 14px / 行高 1.65；辅助 13px / 1.5；页面标题 22px / 600；区块标题 16px / 600；品牌字标 18px / 600。
- 字重只用 400 / 500 / 600；数字与序号可用 `font-variant-numeric: tabular-nums`。
- 内容行长建议 70–80 字符（1160px 内容区 + 32px 留白）。

### 4.3 间距、圆角、阴影

- 间距：4 / 8 / 12 / 16 / 24 / 32 / 48。
- 圆角：输入与按钮 8px；卡片 10px；弹层 12px；标签 999px。
- 阴影：`0 1px 2px rgba(16,24,40,.06)`；仅弹层用 `0 12px 32px rgba(16,24,40,.12)`。
- 过渡：120ms ease-out；`prefers-reduced-motion: reduce` 时关闭。

### 4.4 焦点与可访问性

- 键盘焦点：`outline: 2px solid var(--app-primary); outline-offset: 2px`，禁止 `outline: none` 无替代。
- 正文对比度 ≥ 4.5:1；主色不用于大面积正文。
- 导航用 `<nav aria-label="主导航">`；当前项 `aria-current="page"`。
- 表单 `label` 与输入框 `for/id` 关联；错误文案与 `aria-describedby` 关联。
- 装饰性序号加 `aria-hidden="true"`。

## 5. 信息架构与路由

### 5.1 导航

| 序号 | 名称 | 路径 | 路由名 | 计划任务 |
|---|---|---|---|---|
| 01 | 笔记 | `/notes` | `notes` | S2-12 |
| 02 | 文件 | `/files` | `files` | S2-13 |
| 03 | 知识库 | `/knowledge` | `knowledge` | S2-14 |
| 04 | 智能问答 | `/qa` | `qa` | S3-1 |
| 05 | 错题本 | `/mistakes` | `mistakes` | S4-3 |
| 06 | 复习计划 | `/plan` | `plan` | S4-4 |

- 侧栏底部用户区：昵称、角色标签（学生/教师/家长/管理员）、退出登录。
- 顶栏左侧：面包屑「首页 / 当前页标题」；右侧暂只放用户菜单（全局搜索留待 S2-12）。
- 登录页不套 `MainLayout`。

### 5.2 路由表

```text
/login                     公开，LoginView
/                           MainLayout，受保护，redirect /notes
  /notes                    ComingSoonView（meta: title 笔记, task S2-12）
  /files                    ComingSoonView（S2-13）
  /knowledge                ComingSoonView（S2-14）
  /qa                       ComingSoonView（S3-1）
  /mistakes                 ComingSoonView（S4-3）
  /plan                     ComingSoonView（S4-4）
  /debug                    DebugView（登录后诊断，保留 S0-6 验收能力）
/403                       公开，ForbiddenView
/:pathMatch(.*)*           公开，NotFoundView
```

- 已登录访问 `/login` → `/notes`。
- 未登录访问任一受保护路由 → `/login?redirect=<fullPath>`；`redirect` 必须通过 `safeRedirect` 校验（以单个 `/` 开头、不以 `//` 开头、不含反斜杠的站内路径），否则回 `/notes`。
- 所有懒加载路由；`document.title` 统一写为 `知序 · <title>`；品牌名「知序」已在设计确认中拍板。
- 路由切换 `<router-view v-slot>` + `<Transition name="page">`，120ms 淡入。

## 6. 认证与守卫

### 6.1 类型（`src/types/auth.ts`）

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

### 6.2 API（`src/api/auth.ts`）

```ts
login(payload: { username: string; password: string }): Promise<TokenOut>
register(payload: { username: string; password: string; nickname: string; grade?: string }): Promise<UserOut>
getMe(): Promise<UserOut>
```

- 三者都通过 `http` 发请求并解包 `ApiEnvelope.data`；页面不直接写 URL。
- 注册固定不传 `role`（后端默认 student）；教师/家长账号由管理端或脚本创建。

### 6.3 auth store（`src/stores/auth.ts`）

- state：`token`（从 localStorage 恢复）、`user: UserOut | null`、`loading: boolean`。
- getters：`isLoggedIn`、`roleLabel`（student 学生 / teacher 教师 / parent 家长 / admin 管理员）。
- actions：
  - `setSession(token, user)`：写 state + localStorage；
  - `clearSession()`：清 state + localStorage；
  - `fetchMe()`：动态 `import('@/api/auth')` 调 `getMe`，避免 `http → store → api → http` 静态环；成功后写 `user`，失败向上抛由守卫处理。
- 注意：`user` 不持久化，防止角色过期后前端继续按旧角色渲染。

### 6.4 守卫（`src/router/guard.ts`）

```ts
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

export function resolveAccess(input: AccessInput): AccessDecision
```

判定顺序：
1. `isPublic` → allow；
2. 无 token → login（带 `redirectPath`）；
3. `roles` 非空且（`user` 为空或角色不在列表）→ forbidden（fail-closed，防止未回填时误放行）；
4. 否则 allow。

`beforeEach` 流程：
1. `meta.public` → 直接放行（已登录访问 `/login` 时改跳 `/notes`）。
2. 无 token → `/login?redirect=to.fullPath`。
3. 有 token 且无 user 且未在加载 → `await auth.fetchMe()`；失败则 `clearSession()` 并跳登录。
4. 以 `resolveAccess` 判定；forbidden → `/403`；否则放行。
5. 设置 `document.title = title ? \`知序 · ${title}\` : '知序'`。

### 6.5 登录页（`LoginView.vue`）

- 左右分栏：左侧品牌/定位/三条能力点（可溯源问答、知识点对齐、错题与复习计划）；右侧 380px 卡片。
- 顶部自定义两个文字 tab（`role="tablist"`）切换「登录 / 注册」，切换时保留用户名；不引入额外组件。
- 登录字段：用户名、密码；注册追加昵称、年级（可选）。
- 校验规则与 API.md §1 一致：用户名 3–50 且不含空白；密码 8–128；昵称 1–50；年级 ≤20。
- 交互：用户名自动聚焦；回车提交；提交中按钮 loading 且禁用；密码可切换可见。
- 登录成功：`setSession` → `safeRedirect(route.query.redirect)` → `router.replace` → `ElMessage.success('欢迎回来')`。
- 注册成功：立即用同一账号密码 `login`，成功后同上；若自动登录失败，切回登录 tab 并预填用户名。
- 错误：`http.ts` 已统一 toast，页面不重复弹；字段错误就地展示。

## 7. 布局与组件

### 7.1 MainLayout

```text
┌────────────┬──────────────────────────────────────┐
│ 品牌       │ TopBar: 面包屑 · 用户菜单             │
│ 01 笔记    ├──────────────────────────────────────┤
│ 02 文件    │                                      │
│ ...        │  <router-view> 内容区                 │
│            │                                      │
│ 用户区     │                                      │
└────────────┴──────────────────────────────────────┘
```

- 侧栏 `position: sticky; top: 0; height: 100vh`，内容区独立滚动。
- 菜单项高度 44px，左右 12px；active 时浅主色底 + 左侧 3px 主色条 + 文字主色。
- 顶栏 sticky，背景半透明 + 1px 下边框；面包屑首项「首页」链接 `/notes`。
- 用户菜单用 `el-dropdown`：角色标签 + 昵称；菜单项「退出登录」。

### 7.2 基础组件

| 组件 | Props | 说明 |
|---|---|---|
| `PageHeader` | `title`、`description?` | 右侧 `actions` 插槽；标题 22px，说明 13px 次文字 |
| `EmptyState` | `title`、`description?`、`icon?` | 居中，`actions` 插槽；不用于加载/错误 |
| `ComingSoonView` | 从 `route.meta` 读取 | 计划任务号 tag、模块说明、返回首页按钮 |

### 7.3 页面模式

- 页面结构统一：`PageHeader` → 内容；占位页为 `PageHeader` + `EmptyState` 组合。
- 403/404：居中大号状态码（48px、600）、一句说明、回首页按钮；403 不显示目标资源信息。
- 空状态文案必须给“下一步做什么”，例如「上传第一份资料，系统会自动切片并建立索引（S2-13）」。

## 8. 请求层与错误处理

- `http.ts` 保留现有拦截器结构，修改 401 分支：
  ```ts
  function redirectToLogin() {
    const current = router.currentRoute.value
    if (current.path === '/login') return
    void router.push({ path: '/login', query: { redirect: current.fullPath } })
  }
  ```
  业务码 `40100` 与 HTTP 401 都调用；先 `clearSession()` 再跳。
- 网络错误、4xx/5xx 继续统一 `ElMessage.error`；调用方 catch 后可做局部兜底。
- API 模块返回 `data` 本身，不把信封泄漏给页面；类型全部来自 `src/types/`。
- 不在 S2-11 做请求取消/重试/缓存；页面级 loading 用局部 `ref`。

## 9. 测试计划（17 条）

`src/router/guard.spec.ts`（5）
1. 公开路由 → allow
2. 无 token 的受保护路由 → login，redirect 为 fullPath
3. 有 token + 角色匹配 → allow
4. 有 token + 角色不匹配 → forbidden
5. 有 token、要求 roles 但 user 为空 → forbidden（fail-closed）

`src/utils/redirect.spec.ts`（3）
1. `/notes?x=1` → 原样
2. `//evil.com`、`/\evil.com` → `/notes`
3. 非字符串/空 → `/notes`

`src/stores/auth.spec.ts`（3）
1. `setSession` 写 token 到 localStorage
2. `clearSession` 清空 state 与 localStorage
3. `fetchMe` 成功后写入 user（mock `@/api/auth`）

`src/views/LoginView.spec.ts`（3）
1. 渲染登录/注册 tab 与字段
2. 空表单提交不调用 API，出现校验错误
3. 登录成功调用 `setSession` 并跳转 redirect

`src/layouts/MainLayout.spec.ts`（3）
1. 渲染 6 个导航项
2. 当前路由高亮 `aria-current="page"`
3. 顶栏渲染昵称与角色标签（退出登录放真实浏览器验收，避免依赖 Element Plus 下拉 teleport）

- 配置：`vitest.config.ts` 复用 Vite alias，`environment: 'jsdom'`，`globals: false`；Element Plus 在挂载测试中作为 plugin 注入；`ResizeObserver` 用最小 stub。
- 测试命令：`npm run test:run`；监听模式 `npm run test`。

## 10. 验收

### 10.1 自动化

```bash
cd web
npm run test:run
npm run build
```

预期：17 条测试全绿；`vue-tsc -b` 零错误，Vite 构建成功。

### 10.2 真实后端联调

启动 Postgres/Redis/MinIO + uvicorn（S2-2/S2-10 已具备）：

1. 打开 `http://localhost:5173/login`，注册 `s211_student`；注册成功自动登录并落到 `/notes` 占位页。
2. 刷新页面：仍保持登录，顶栏显示昵称与“学生”标签。
3. 退出登录 → 回 `/login`；直接访问 `/notes` → `/login?redirect=/notes`；登录后回到 `/notes`。
4. 用浏览器 devtools 把 localStorage token 改成非法值 → 刷新 → 401 自动清 token 回登录页。
5. 访问 `/not-exist` → 404；访问 `/403` → 403；两者“返回首页”均回 `/notes`。
6. 截图 1440×900：登录页、主布局 + 笔记占位页、404、403；目视检查无横向滚动、无默认蓝紫按钮。
7. 清理测试账号。

### 10.3 目视验收清单

- 侧栏 active 有左侧主色条 + 浅底；顶栏边框 1px；卡片圆角 10px。
- 登录页左右比例协调，表单宽 380px，输入框高 40px。
- 所有按钮/链接有可见焦点；Tab 可走完登录表单。
- 占位页明确写出计划任务号，不出现假数据。

## 11. 已知限制

- token 存 localStorage，存在 XSS 读取风险（S2-2 既有决策，未改）。
- 无刷新 token/登出吊销；token 过期只能重新登录。
- 无手机适配、深色模式、i18n、全局搜索。
- 页面级角色限制未启用；教师/家长登录后看到与学生相同的占位导航。
- 占位页较多，S2-12–S2-14 完成前系统“看起来空”，这是刻意避免假数据。
- 全局注册 Element Plus 导致首包偏大（S0-6 已知），本卡不优化。

## 12. 后续衔接

- S2-12：把 `/notes` 占位换成真实列表/编辑器；引入 KaTeX 与 Markdown 渲染；顶栏加 ⌘K。
- S2-13：`/files` 上传与解析进度；需要状态标签时再抽 `StatusTag`。
- S2-14：`/knowledge` 树 + 待确认队列；复用 `PageHeader` / `EmptyState` / 批量操作模式。
- S3：`/qa` 问答与引用回链；沿用同一布局。

## 13. 执行记录

- 实施 commits：`0bc7745`（token/测试基建）、`6f89bbd`（认证与守卫）、`5f4a809`（登录页/401）、`c394d4e`（布局与路由）、文档提交见 git log。
- 自动化：`npm run test:run` **17 passed / 5 files**；`npm run build` 成功、零 TS 错误。
- 真实联调（Chrome 155 headless，1440×900，CDP）：注册 `s211_e2e_*` → 自动登录 `/notes`；刷新后昵称「测试学生S211」/角色「学生」保持；退出后 token 清空；未登录 `/notes` → `/login?redirect=/notes`；重新登录回 `/notes`；伪造 token → 401 清 token 回登录（带 redirect）；`/not-exist` 404、`/403` 403；console error 0；验收账号已删除。
- 布局实测：侧栏 248px、顶栏 56px、内容 1160px、左边距 264px；主色 `rgb(59,91,219)`；登录卡片 380px。
- 偏差：① API 加 `/api/v1` 前缀（`VITE_API_BASE` 是 host）；② Vitest inline Element Plus 修复校验恒 true；③ Node 25 localStorage 用内存 stub；④ 登录页错误断言等 100ms 防抖；⑤ 403/404 共用 `StatusPage`；⑥ MainLayout 测试路由父级改 `<router-view />` 避免双挂载。
- 未完成：截图尚无人工目视评审，样式细节待用户确认。