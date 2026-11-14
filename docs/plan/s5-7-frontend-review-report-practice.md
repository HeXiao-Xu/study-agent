# S5-7 前端复习 / 报告 / 练习页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 S5-5 复习调度与 S5-6 学习报告接成学生可用的 `/review`、`/reports`、`/practice` 三个页面，并保持前端测试与构建全绿。

**Architecture:** 沿用现有「页面薄、纯函数厚」结构：API 客户端与类型镜像契约；复习进度、图表 option、图片布局放纯函数模块；页面只负责请求、状态、图表实例与交互。不新增依赖、不改后端。

**Tech Stack:** Vue 3 + TypeScript + Vue Router + Pinia + Element Plus + ECharts + md-editor-v3 + Vitest + jsdom。

**Spec:** `docs/spec/s5-7-frontend-review-report-practice.md`

## Global Constraints

- 只做前端；**禁止**新增后端接口、数据库迁移、前端依赖。
- **禁止**改 `body { min-width: 1024px }`、侧栏或 `MainLayout` 做手机适配；本轮不做 H5，任务卡手机验收项明确不满足。
- 所有 API 调用经 `web/src/api/` 封装；组件不得直接 import axios。
- 所有业务数据请求 mock 在测试中；测试套件禁止真实网络/LLM 调用。
- 不用假数据填图；空数据一律空态。
- 明确禁止伪造掌握度变化：复习 done/skip/later 只做进度动画与“已记录”提示。
- 路由页面 `meta.roles: ['student']`；沿用 `router/guard.ts`，不另写权限判断。
- 提交信息含任务号，例如 `feat(s5-7): ...`；用户负责 `git push`。
- 每个任务结束必须跑该任务的测试并提交；全量验证在 Task 9。

---

### Task 1: 复习 / 报告类型与 API 客户端

**Files:**
- Create: `web/src/types/review.ts`
- Create: `web/src/types/reports.ts`
- Create: `web/src/api/review.ts`
- Create: `web/src/api/reports.ts`
- Test: `web/src/api/review.spec.ts`
- Test: `web/src/api/reports.spec.ts`

**Interfaces:**
- Consumes: `@/api/http` 的 `http`、`API_PREFIX`、`ApiEnvelope`。
- Produces:
  - `ReviewItem`、`ReviewToday`
  - `ReportRange`、`ReportOverview`、`WeeklyReport` 及子类型
  - `refreshReview(): Promise<ReviewToday>`
  - `getTodayReview(): Promise<ReviewToday>`
  - `markReviewDone(id: number): Promise<ReviewItem>`
  - `markReviewSkip(id: number): Promise<ReviewItem>`
  - `markReviewLater(id: number): Promise<ReviewItem>`
  - `fetchReportOverview(range?: ReportRange): Promise<ReportOverview>`
  - `generateWeeklyReport(): Promise<WeeklyReport>`

- [x] **Step 1: 写失败的 API 测试**

`web/src/api/review.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { ReviewItem, ReviewToday } from '@/types/review'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import {
  getTodayReview,
  markReviewDone,
  markReviewLater,
  markReviewSkip,
  refreshReview,
} from './review'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 1,
    kp_id: 197,
    kp_name: '同角三角函数基本关系',
    subject_id: 7,
    ref_type: 'mistake',
    ref_id: 31,
    ref_title: '测试错题',
    ref_available: true,
    due_at: '2026-11-14T00:00:00Z',
    interval_days: 2,
    priority: 0.72,
    estimated_minutes: 12,
    mastery: 0.2,
    mastery_t: 0.18,
    stability: 2.5,
    attempts: 3,
    overdue_days: 1.5,
    low_mastery: true,
    done_at: null,
    ...overrides,
  }
}

function today(overrides: Partial<ReviewToday> = {}): ReviewToday {
  return {
    date: '2026-11-14',
    timezone: 'Asia/Shanghai',
    items: [item()],
    item_count: 1,
    total_minutes: 12,
    cap_minutes: 35,
    truncated_count: null,
    ...overrides,
  }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('review api', () => {
  it('refreshes the today list with POST', async () => {
    http.post.mockResolvedValue(envelope(today()))
    const data = await refreshReview()
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/refresh')
    expect(data.item_count).toBe(1)
  })

  it('gets the read-only today list', async () => {
    http.get.mockResolvedValue(envelope(today()))
    await getTodayReview()
    expect(http.get).toHaveBeenCalledWith('/api/v1/review/today')
  })

  it('marks an item done', async () => {
    http.post.mockResolvedValue(envelope(item({ done_at: '2026-11-14T02:00:00Z' })))
    const row = await markReviewDone(1)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/1/done')
    expect(row.done_at).not.toBeNull()
  })

  it('marks an item skipped', async () => {
    http.post.mockResolvedValue(envelope(item()))
    await markReviewSkip(2)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/2/skip')
  })

  it('marks an item later', async () => {
    http.post.mockResolvedValue(envelope(item()))
    await markReviewLater(3)
    expect(http.post).toHaveBeenCalledWith('/api/v1/review/items/3/later')
  })
})
```

`web/src/api/reports.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiEnvelope } from '@/api/http'
import type { ReportOverview, WeeklyReport } from '@/types/reports'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/http', () => ({ default: http, API_PREFIX: '/api/v1' }))

import { fetchReportOverview, generateWeeklyReport } from './reports'

function envelope<T>(data: T) {
  const body: ApiEnvelope<T> = { code: 0, message: 'ok', trace_id: 't', data }
  return { data: body }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('reports api', () => {
  it('requests mastery overview with the range param', async () => {
    http.get.mockResolvedValue(envelope<ReportOverview>({ range: {} } as ReportOverview))
    await fetchReportOverview('7d')
    expect(http.get).toHaveBeenCalledWith('/api/v1/reports/mastery', {
      params: { range: '7d' },
    })
  })

  it('defaults to 30d', async () => {
    http.get.mockResolvedValue(envelope<ReportOverview>({ range: {} } as ReportOverview))
    await fetchReportOverview()
    expect(http.get).toHaveBeenCalledWith('/api/v1/reports/mastery', {
      params: { range: '30d' },
    })
  })

  it('posts weekly generation without a body', async () => {
    http.post.mockResolvedValue(envelope<WeeklyReport>({ generated_by: 'empty' } as WeeklyReport))
    const data = await generateWeeklyReport()
    expect(http.post).toHaveBeenCalledWith('/api/v1/reports/weekly')
    expect(data.generated_by).toBe('empty')
  })
})
```

- [x] **Step 2: 运行测试确认失败**

Run:
```bash
cd web
npm run test:run -- src/api/review.spec.ts src/api/reports.spec.ts
```

Expected: FAIL，提示找不到 `./review` / `./reports` 或类型模块。

- [x] **Step 3: 写类型与 API 客户端**

`web/src/types/review.ts`：

```ts
/** S5-5 复习清单前端类型（docs/API.md §9）。 */
export type ReviewRefType = 'question' | 'mistake'

export interface ReviewItem {
  id: number
  kp_id: number
  kp_name: string
  subject_id: number
  ref_type: ReviewRefType
  ref_id: number
  ref_title: string | null
  ref_available: boolean
  due_at: string
  interval_days: number
  priority: number
  estimated_minutes: number
  mastery: number
  mastery_t: number
  stability: number
  attempts: number
  overdue_days: number
  low_mastery: boolean
  done_at: string | null
}

export interface ReviewToday {
  date: string
  timezone: string
  items: ReviewItem[]
  item_count: number
  total_minutes: number
  cap_minutes: number
  truncated_count: number | null
}
```

`web/src/types/reports.ts`：

```ts
/** S5-6 学习报告与周报前端类型（docs/API.md §9）。 */
export type ReportRange = '7d' | '30d' | '90d'

export interface ReportRangeInfo {
  key: ReportRange
  from: string
  to: string
}

export interface ReportModule {
  kp_id: number
  kp_name: string
  exam_weight: number | null
  kp_count: number
  assessed_count: number
  mastery: number | null
}

export interface ReportHeatmapNode {
  kp_id: number
  kp_name: string
  parent_id: number | null
  level: number
  exam_weight: number | null
  mastery: number | null
  mastery_t: number | null
  color_value: number | null
  assessed: boolean
}

export interface ReportSubject {
  subject_id: number
  subject_name: string
  modules: ReportModule[]
  heatmap: ReportHeatmapNode[]
}

export interface ReportTrendPoint {
  date: string
  new_notes: number
  reviews_done: number
  new_mistakes: number
  mastered_mistakes: number
  mistakes_net: number
}

export interface ReportOverview {
  range: ReportRangeInfo
  subjects: ReportSubject[]
  trend: ReportTrendPoint[]
}

export interface WeeklyPeriod {
  from: string
  to: string
  days: number
}

export interface WeeklyTotals {
  new_notes: number
  reviews_done: number
  new_mistakes: number
  mastered_mistakes: number
  mistakes_net: number
}

export interface WeeklyWeakModule {
  subject_id: number
  kp_id: number
  kp_name: string
  mastery: number
}

export interface WeeklyWeakKp {
  subject_id: number
  kp_id: number
  kp_name: string
  level: number
  mastery: number
}

export interface WeeklyMastery {
  assessed_kp_count: number
  avg_mastery: number | null
  weak_modules: WeeklyWeakModule[]
  weak_kps: WeeklyWeakKp[]
}

export interface WeeklyStats {
  totals: WeeklyTotals
  active_days: number
  mastery: WeeklyMastery
  trend: ReportTrendPoint[]
}

export interface WeeklyValidation {
  ok: boolean
  attempts: number
  checked_numbers: string[]
  invalid_numbers: string[]
}

export interface WeeklyReport {
  period: WeeklyPeriod
  generated_by: 'llm' | 'empty'
  report_md: string
  stats: WeeklyStats
  validation: WeeklyValidation
}
```

`web/src/api/review.ts`：

```ts
/** S5-5 复习清单接口：只封装契约，不做业务计算。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { ReviewItem, ReviewToday } from '@/types/review'

export async function refreshReview(): Promise<ReviewToday> {
  const resp = await http.post<ApiEnvelope<ReviewToday>>(`${API_PREFIX}/review/refresh`)
  return resp.data.data
}

export async function getTodayReview(): Promise<ReviewToday> {
  const resp = await http.get<ApiEnvelope<ReviewToday>>(`${API_PREFIX}/review/today`)
  return resp.data.data
}

export async function markReviewDone(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/done`,
  )
  return resp.data.data
}

export async function markReviewSkip(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/skip`,
  )
  return resp.data.data
}

export async function markReviewLater(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/later`,
  )
  return resp.data.data
}
```

`web/src/api/reports.ts`：

```ts
/** S5-6 学习报告：overview 与周报两个接口。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { ReportOverview, ReportRange, WeeklyReport } from '@/types/reports'

export async function fetchReportOverview(
  range: ReportRange = '30d',
): Promise<ReportOverview> {
  const resp = await http.get<ApiEnvelope<ReportOverview>>(`${API_PREFIX}/reports/mastery`, {
    params: { range },
  })
  return resp.data.data
}

export async function generateWeeklyReport(): Promise<WeeklyReport> {
  const resp = await http.post<ApiEnvelope<WeeklyReport>>(`${API_PREFIX}/reports/weekly`)
  return resp.data.data
}
```

- [x] **Step 4: 运行测试确认通过**

Run:
```bash
cd web
npm run test:run -- src/api/review.spec.ts src/api/reports.spec.ts
```

Expected: 两个文件全部 PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/types/review.ts web/src/types/reports.ts web/src/api/review.ts web/src/api/reports.ts web/src/api/review.spec.ts web/src/api/reports.spec.ts
git commit -m "feat(s5-7): 复习与报告前端契约"
```

---

### Task 2: 复习进度纯函数

**Files:**
- Create: `web/src/views/review/useReviewProgress.ts`
- Test: `web/src/views/review/useReviewProgress.spec.ts`

**Interfaces:**
- Consumes: `ReviewItem`。
- Produces:
  - `ReviewProgress { processed: number; total: number; percent: number; label: string }`
  - `progressOf(total, processed): ReviewProgress`
  - `minutesLabel(minutes: number): string`
  - `truncatedLabel(count: number | null): string`
  - `reviewRefPath(item): string | null`

- [x] **Step 1: 写失败测试**

`web/src/views/review/useReviewProgress.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { ReviewItem } from '@/types/review'

import {
  minutesLabel,
  progressOf,
  reviewRefPath,
  truncatedLabel,
} from './useReviewProgress'

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 1,
    kp_id: 1,
    kp_name: '函数',
    subject_id: 7,
    ref_type: 'mistake',
    ref_id: 31,
    ref_title: '错题',
    ref_available: true,
    due_at: '2026-11-14T00:00:00Z',
    interval_days: 1,
    priority: 0.5,
    estimated_minutes: 10,
    mastery: 0.2,
    mastery_t: 0.2,
    stability: 1,
    attempts: 1,
    overdue_days: 0,
    low_mastery: true,
    done_at: null,
    ...overrides,
  }
}

describe('progressOf', () => {
  it('clamps processed and computes rounded percent', () => {
    expect(progressOf(3, 1)).toEqual({
      processed: 1,
      total: 3,
      percent: 33,
      label: '已处理 1/3',
    })
  })

  it('handles zero and overflow without NaN', () => {
    expect(progressOf(0, 2)).toEqual({ processed: 0, total: 0, percent: 0, label: '已处理 0/0' })
    expect(progressOf(2, 9).processed).toBe(2)
  })
})

describe('labels', () => {
  it('formats minutes and truncated count', () => {
    expect(minutesLabel(12)).toBe('12 分钟')
    expect(truncatedLabel(null)).toBe('')
    expect(truncatedLabel(0)).toBe('')
    expect(truncatedLabel(2)).toBe('有 2 项顺延到明天')
  })
})

describe('reviewRefPath', () => {
  it('routes mistakes and questions, and hides unavailable refs', () => {
    expect(reviewRefPath(item())).toBe('/mistakes/31')
    expect(reviewRefPath(item({ ref_type: 'question', ref_id: 8 }))).toBe('/questions')
    expect(reviewRefPath(item({ ref_available: false }))).toBeNull()
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/review/useReviewProgress.spec.ts
```

Expected: FAIL，模块不存在。

- [x] **Step 3: 实现纯函数**

`web/src/views/review/useReviewProgress.ts`：

```ts
/** S5-7 复习清单的纯计算，页面只消费结果。 */
import type { ReviewItem } from '@/types/review'

export interface ReviewProgress {
  processed: number
  total: number
  percent: number
  label: string
}

export function progressOf(total: number, processed: number): ReviewProgress {
  const safeTotal = Number.isFinite(total) ? Math.max(0, Math.trunc(total)) : 0
  const safeProcessed = Number.isFinite(processed)
    ? Math.min(Math.max(0, Math.trunc(processed)), safeTotal)
    : 0
  const percent = safeTotal === 0 ? 0 : Math.round((safeProcessed / safeTotal) * 100)
  return {
    processed: safeProcessed,
    total: safeTotal,
    percent,
    label: `已处理 ${safeProcessed}/${safeTotal}`,
  }
}

export function minutesLabel(minutes: number): string {
  return `${Math.max(0, Math.trunc(minutes))} 分钟`
}

export function truncatedLabel(count: number | null): string {
  return count !== null && count > 0 ? `有 ${count} 项顺延到明天` : ''
}

export function reviewRefPath(
  item: Pick<ReviewItem, 'ref_type' | 'ref_id' | 'ref_available'>,
): string | null {
  if (!item.ref_available) return null
  return item.ref_type === 'mistake' ? `/mistakes/${item.ref_id}` : '/questions'
}
```

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/review/useReviewProgress.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/views/review/useReviewProgress.ts web/src/views/review/useReviewProgress.spec.ts
git commit -m "feat(s5-7): 复习进度纯函数"
```

---

### Task 3: 复习清单页

**Files:**
- Create: `web/src/views/review/Today.vue`
- Test: `web/src/views/review/Today.spec.ts`

**Interfaces:**
- Consumes:
  - Task 1 的 `refreshReview` / `markReviewDone` / `markReviewSkip` / `markReviewLater`
  - Task 2 的 `progressOf` / `minutesLabel` / `truncatedLabel` / `reviewRefPath`
  - `PageHeader`、`EmptyState`
- Produces: `/review` 页面；`data-testid="review-item-{id}"`、`done-{id}`、`skip-{id}`、`later-{id}`、`review-refresh`、`review-progress`。

- [x] **Step 1: 写失败的页面测试**

`web/src/views/review/Today.spec.ts`：

```ts
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReviewItem, ReviewToday } from '@/types/review'
import { ElMessage } from 'element-plus'

const api = vi.hoisted(() => ({
  refreshReview: vi.fn(),
  markReviewDone: vi.fn(),
  markReviewSkip: vi.fn(),
  markReviewLater: vi.fn(),
}))
vi.mock('@/api/review', () => api)
vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessage: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
  }
})

import Today from './Today.vue'

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 1,
    kp_id: 197,
    kp_name: '同角三角函数基本关系',
    subject_id: 7,
    ref_type: 'mistake',
    ref_id: 31,
    ref_title: '测试错题',
    ref_available: true,
    due_at: '2026-11-14T00:00:00Z',
    interval_days: 2,
    priority: 0.72,
    estimated_minutes: 12,
    mastery: 0.2,
    mastery_t: 0.18,
    stability: 2.5,
    attempts: 3,
    overdue_days: 1.5,
    low_mastery: true,
    done_at: null,
    ...overrides,
  }
}

function today(overrides: Partial<ReviewToday> = {}): ReviewToday {
  return {
    date: '2026-11-14',
    timezone: 'Asia/Shanghai',
    items: [item(), item({ id: 2, ref_type: 'question', ref_id: 8, kp_name: '函数单调性' })],
    item_count: 2,
    total_minutes: 24,
    cap_minutes: 35,
    truncated_count: null,
    ...overrides,
  }
}

function mountPage() {
  return mount(Today, {
    global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.refreshReview.mockResolvedValue(today())
  api.markReviewDone.mockResolvedValue(item({ done_at: '2026-11-14T02:00:00Z' }))
  api.markReviewSkip.mockResolvedValue(item())
  api.markReviewLater.mockResolvedValue(item())
  vi.mocked(ElMessage.success).mockReset()
})

describe('Today 复习页', () => {
  it('进入页面先 refresh，并渲染日期、分钟与两项', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.refreshReview).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('2026-11-14')
    expect(wrapper.text()).toContain('24 分钟')
    expect(wrapper.findAll('[data-testid^="review-item-"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('同角三角函数基本关系')
  })

  it('完成一项后移除卡片并推进进度', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="done-1"]').trigger('click')
    await flushPromises()
    expect(api.markReviewDone).toHaveBeenCalledWith(1)
    expect(wrapper.find('[data-testid="review-item-1"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已处理 1/2')
    expect(wrapper.text()).toContain('已记录')
  })

  it('跳过和稍后分别调用对应接口并移除', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="skip-1"]').trigger('click')
    await flushPromises()
    expect(api.markReviewSkip).toHaveBeenCalledWith(1)
    await wrapper.get('[data-testid="later-2"]').trigger('click')
    await flushPromises()
    expect(api.markReviewLater).toHaveBeenCalledWith(2)
    expect(wrapper.findAll('[data-testid^="review-item-"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('今天的复习已完成')
  })

  it('显示顺延提示', async () => {
    api.refreshReview.mockResolvedValue(today({ truncated_count: 3 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('有 3 项顺延到明天')
  })

  it('空清单给空态和去组卷入口', async () => {
    api.refreshReview.mockResolvedValue(today({ items: [], item_count: 0, total_minutes: 0 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('今天没有待复习项')
    expect(wrapper.text()).toContain('去组卷')
  })

  it('操作失败保留卡片并提示可重试', async () => {
    api.markReviewDone.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="done-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="review-item-1"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('操作失败，请重试')
  })

  it('资源不可用时不显示跳转链接', async () => {
    api.refreshReview.mockResolvedValue(
      today({ items: [item({ ref_available: false })], item_count: 1 }),
    )
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('参考资源已删除')
    expect(wrapper.find('a').exists()).toBe(false)
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/review/Today.spec.ts
```

Expected: FAIL，`Today.vue` 不存在。

- [x] **Step 3: 实现页面**

`web/src/views/review/Today.vue`：

```vue
<script setup lang="ts">
/**
 * S5-7 今日复习清单。
 *
 * done/skip/later 都不改掌握度；页面只做移除、进度与“已记录”提示，
 * 不把“完成”包装成掌握度提升。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import {
  markReviewDone,
  markReviewLater,
  markReviewSkip,
  refreshReview,
} from '@/api/review'
import type { ReviewItem, ReviewToday } from '@/types/review'

import {
  minutesLabel,
  progressOf,
  reviewRefPath,
  truncatedLabel,
} from './useReviewProgress'

type ReviewAction = 'done' | 'skip' | 'later'

const router = useRouter()
const data = ref<ReviewToday | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const total = ref(0)
const processed = ref(0)
const pendingId = ref<number | null>(null)
const pendingAction = ref<ReviewAction | null>(null)
const actionError = ref('')

const items = computed(() => data.value?.items ?? [])
const progress = computed(() => progressOf(total.value, processed.value))
const truncated = computed(() => truncatedLabel(data.value?.truncated_count ?? null))
const allDone = computed(
  () => data.value !== null && items.value.length === 0 && processed.value > 0,
)

const actions: Record<
  ReviewAction,
  (id: number) => Promise<ReviewItem>
> = {
  done: markReviewDone,
  skip: markReviewSkip,
  later: markReviewLater,
}

function itemPath(item: ReviewItem): string {
  return reviewRefPath(item) ?? ''
}

function goGenerate(): void {
  void router.push('/papers/generate')
}

function overdueText(days: number): string {
  return days > 0 ? `逾期 ${days.toFixed(1)} 天` : '今日到期'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const out = await refreshReview()
    data.value = out
    total.value = out.item_count
    processed.value = 0
  } catch {
    data.value = null
    error.value = '复习清单加载失败，请重试'
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  refreshing.value = true
  error.value = ''
  try {
    const out = await refreshReview()
    data.value = out
    total.value = out.item_count
    processed.value = 0
  } catch {
    error.value = '复习清单刷新失败，请重试'
  } finally {
    refreshing.value = false
  }
}

async function act(item: ReviewItem, action: ReviewAction): Promise<void> {
  if (pendingId.value !== null) return
  pendingId.value = item.id
  pendingAction.value = action
  actionError.value = ''
  try {
    await actions[action](item.id)
    if (data.value !== null) {
      const next = data.value.items.filter((row) => row.id !== item.id)
      data.value = { ...data.value, items: next, item_count: next.length }
    }
    processed.value += 1
    ElMessage.success(action === 'later' ? '已顺延到明天' : '已记录')
  } catch {
    actionError.value = '操作失败，请重试'
  } finally {
    pendingId.value = null
    pendingAction.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="review-page">
    <PageHeader
      title="今日复习"
      description="按掌握度与到期时间排序；完成/跳过只记今天，掌握度由后续作答更新。"
    >
      <template #actions>
        <el-button
          :loading="refreshing"
          data-testid="review-refresh"
          @click="refresh"
        >
          重新生成
        </el-button>
      </template>
    </PageHeader>

    <el-skeleton v-if="loading" :rows="5" animated data-testid="review-loading" />

    <el-alert
      v-else-if="error"
      type="error"
      :closable="false"
      :title="error"
      data-testid="review-error"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <template v-else-if="data">
      <section class="review-summary">
        <div>
          <strong>{{ data.date }}</strong>
          <span>{{ data.timezone }} · {{ minutesLabel(data.total_minutes) }} / 上限 {{ data.cap_minutes }} 分钟</span>
        </div>
        <div class="review-progress" data-testid="review-progress">
          <span>{{ progress.label }}</span>
          <el-progress :percentage="progress.percent" :show-text="false" :stroke-width="8" />
        </div>
      </section>

      <el-alert
        v-if="truncated"
        type="warning"
        :closable="false"
        :title="truncated"
        data-testid="review-truncated"
      />
      <el-alert
        v-if="actionError"
        type="error"
        :closable="false"
        :title="actionError"
        data-testid="review-action-error"
      />

      <TransitionGroup
        v-if="items.length"
        name="review-list"
        tag="div"
        class="review-list"
        data-testid="review-list"
      >
        <article
          v-for="item in items"
          :key="item.id"
          class="review-card"
          :data-testid="`review-item-${item.id}`"
        >
          <header class="review-card__head">
            <div>
              <h3>{{ item.kp_name }}</h3>
              <p>
                <span v-if="item.low_mastery" class="review-badge">薄弱</span>
                <span>掌握度 {{ item.mastery_t.toFixed(2) }}</span>
                <span>{{ overdueText(item.overdue_days) }}</span>
                <span>优先级 {{ item.priority.toFixed(2) }}</span>
              </p>
            </div>
            <el-tag effect="plain">{{ minutesLabel(item.estimated_minutes) }}</el-tag>
          </header>

          <router-link
            v-if="itemPath(item)"
            :to="itemPath(item)"
            class="review-ref"
            data-testid="review-ref-link"
          >
            {{ item.ref_title || '查看参考内容' }} →
          </router-link>
          <p v-else class="review-ref review-ref--disabled">参考资源已删除</p>

          <footer class="review-actions">
            <el-button
              type="primary"
              :loading="pendingId === item.id && pendingAction === 'done'"
              :disabled="pendingId !== null"
              :data-testid="`done-${item.id}`"
              @click="act(item, 'done')"
            >
              完成
            </el-button>
            <el-button
              :loading="pendingId === item.id && pendingAction === 'skip'"
              :disabled="pendingId !== null"
              :data-testid="`skip-${item.id}`"
              @click="act(item, 'skip')"
            >
              跳过
            </el-button>
            <el-button
              :loading="pendingId === item.id && pendingAction === 'later'"
              :disabled="pendingId !== null"
              :data-testid="`later-${item.id}`"
              @click="act(item, 'later')"
            >
              稍后
            </el-button>
          </footer>
        </article>
      </TransitionGroup>

      <EmptyState
        v-else
        :title="allDone ? '今天的复习已完成' : '今天没有待复习项'"
        :description="
          allDone
            ? '完成的项不会改变掌握度；去组卷或作答后，掌握度与到期时间才会更新。'
            : '可以先组一份卷子，或稍后回来重新生成清单。'
        "
        data-testid="review-empty"
      >
        <template #actions>
          <el-button type="primary" @click="goGenerate">去组卷</el-button>
          <el-button @click="refresh">重新生成</el-button>
        </template>
      </EmptyState>
    </template>
  </div>
</template>

<style scoped>
.review-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.review-summary {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.review-summary strong {
  display: block;
  color: #101828;
  font-size: 16px;
}
.review-summary span {
  color: #667085;
  font-size: 12px;
}
.review-progress {
  display: grid;
  min-width: 240px;
  gap: 4px;
  font-size: 12px;
  color: #667085;
}
.review-list {
  display: grid;
  gap: 12px;
}
.review-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.review-card__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}
.review-card h3 {
  margin: 0;
  color: #101828;
  font-size: 16px;
}
.review-card__head p {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 6px 0 0;
  color: #667085;
  font-size: 12px;
}
.review-badge {
  padding: 0 6px;
  color: #b42318;
  background: #fef3f2;
  border-radius: 999px;
}
.review-ref {
  color: #3538cd;
  font-size: 13px;
}
.review-ref--disabled {
  color: #98a2b3;
  margin: 0;
}
.review-actions {
  display: flex;
  gap: 8px;
}
.review-list-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}
.review-list-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
```

- [x] **Step 4: 运行测试确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/review/Today.spec.ts
```

Expected: PASS。若 `ElMessage` mock 与组件内部导入不匹配，改为不 mock `element-plus`、只断言文本与 API 调用；不要在测试里等真实弹窗。

- [x] **Step 5: 提交**

```bash
git add web/src/views/review/Today.vue web/src/views/review/Today.spec.ts
git commit -m "feat(s5-7): 今日复习清单页"
```

---

### Task 4: 报告图表纯函数

**Files:**
- Create: `web/src/views/reports/useReportCharts.ts`
- Test: `web/src/views/reports/useReportCharts.spec.ts`

**Interfaces:**
- Consumes: `ReportSubject`、`ReportModule`、`ReportHeatmapNode`、`ReportTrendPoint`、`utils/masteryColor`。
- Produces:
  - `pageSummary(trend): Array<{label: string; value: number}>`
  - `assessedModules(subject): ReportModule[]`
  - `radarOption(subject): Record<string, unknown>`
  - `buildHeatmapTree(nodes): HeatmapTreeNode[]`
  - `treemapOption(nodes): Record<string, unknown>`
  - `trendOption(trend): Record<string, unknown>`
  - `hasAssessed(subject): boolean`

- [x] **Step 1: 写失败测试**

`web/src/views/reports/useReportCharts.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type {
  ReportHeatmapNode,
  ReportModule,
  ReportSubject,
  ReportTrendPoint,
} from '@/types/reports'

import {
  assessedModules,
  buildHeatmapTree,
  hasAssessed,
  pageSummary,
  radarOption,
  trendOption,
} from './useReportCharts'

function module(kp_id: number, name: string, mastery: number | null): ReportModule {
  return {
    kp_id,
    kp_name: name,
    exam_weight: 0.5,
    kp_count: 2,
    assessed_count: mastery === null ? 0 : 1,
    mastery,
  }
}

function node(
  kp_id: number,
  name: string,
  level: number,
  parent_id: number | null,
  mastery_t: number | null,
): ReportHeatmapNode {
  return {
    kp_id,
    kp_name: name,
    parent_id,
    level,
    exam_weight: 0.5,
    mastery: mastery_t,
    mastery_t,
    color_value: mastery_t === null ? null : 1 - mastery_t,
    assessed: mastery_t !== null,
  }
}

function subject(modules: ReportModule[], heatmap: ReportHeatmapNode[]): ReportSubject {
  return { subject_id: 7, subject_name: '高中数学', modules, heatmap }
}

const TREND: ReportTrendPoint[] = [
  { date: '2026-11-13', new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
  { date: '2026-11-14', new_notes: 0, reviews_done: 1, new_mistakes: 2, mastered_mistakes: 2, mistakes_net: 0 },
]

describe('pageSummary', () => {
  it('sums trend fields and keeps labels explicit', () => {
    expect(pageSummary(TREND)).toEqual([
      { label: '新增笔记', value: 1 },
      { label: '完成复习', value: 3 },
      { label: '新增错题', value: 5 },
      { label: '已掌握错题', value: 3 },
      { label: '错题净变化', value: 2 },
    ])
  })
})

describe('radar', () => {
  it('only assesses modules with non-null mastery', () => {
    const s = subject(
      [module(1, '函数', 0.3), module(2, '数列', null), module(3, '三角', 0.8)],
      [],
    )
    expect(assessedModules(s).map((m) => m.kp_id)).toEqual([1, 3])
    expect(hasAssessed(s)).toBe(true)
    const option = radarOption(s) as { radar: { indicator: Array<{ name: string }> }; series: Array<{ data: Array<{ value: number[] }> }> }
    expect(option.radar.indicator.map((row) => row.name)).toEqual(['函数', '三角'])
    expect(option.series[0]!.data[0]!.value).toEqual([0.3, 0.8])
  })

  it('reports no assessed modules', () => {
    expect(hasAssessed(subject([module(1, '函数', null)], []))).toBe(false)
  })
})

describe('heatmap tree', () => {
  it('builds level 2→3→4 and attaches orphan to root', () => {
    const nodes = [
      node(10, '函数', 2, null, 0.5),
      node(11, '单调性', 3, 10, 0.3),
      node(12, '基本公式', 4, 11, null),
      node(20, '孤儿', 3, 999, 0.6),
    ]
    const tree = buildHeatmapTree(nodes)
    expect(tree.map((row) => row.kp_id)).toEqual([10, 20])
    expect(tree[0]!.children.map((row) => row.kp_id)).toEqual([11])
    expect(tree[0]!.children[0]!.children[0]!.itemStyle.color).toBe('#9aa4b2')
    expect(tree[1]!.itemStyle.color).not.toBe('#9aa4b2')
  })
})

describe('trendOption', () => {
  it('has five series and a dashed net series', () => {
    const option = trendOption(TREND) as {
      xAxis: { data: string[] }
      series: Array<{ name: string; data: number[]; lineStyle?: { type?: string } }>
    }
    expect(option.xAxis.data).toEqual(['2026-11-13', '2026-11-14'])
    expect(option.series).toHaveLength(5)
    expect(option.series[4]!.name).toBe('错题净变化')
    expect(option.series[4]!.lineStyle?.type).toBe('dashed')
    expect(option.series[2]!.data).toEqual([3, 2])
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/reports/useReportCharts.spec.ts
```

Expected: FAIL，模块不存在。

- [x] **Step 3: 实现纯函数**

`web/src/views/reports/useReportCharts.ts`：

```ts
/** S5-7 学习报告图表纯函数：页面只负责 setOption。 */
import { COLOR_UNRATED, masteryColor } from '@/utils/masteryColor'
import type {
  ReportHeatmapNode,
  ReportModule,
  ReportSubject,
  ReportTrendPoint,
} from '@/types/reports'

export interface HeatmapTreeNode {
  name: string
  kp_id: number
  level: number
  value: number
  mastery_t: number | null
  itemStyle: { color: string; borderColor: string; borderWidth: number }
  children: HeatmapTreeNode[]
}

export function pageSummary(trend: ReportTrendPoint[]): Array<{ label: string; value: number }> {
  const sum = (key: keyof ReportTrendPoint): number =>
    trend.reduce((total, point) => total + Number(point[key]), 0)
  return [
    { label: '新增笔记', value: sum('new_notes') },
    { label: '完成复习', value: sum('reviews_done') },
    { label: '新增错题', value: sum('new_mistakes') },
    { label: '已掌握错题', value: sum('mastered_mistakes') },
    { label: '错题净变化', value: sum('mistakes_net') },
  ]
}

export function assessedModules(subject: ReportSubject): ReportModule[] {
  return subject.modules.filter((module) => module.mastery !== null)
}

export function hasAssessed(subject: ReportSubject): boolean {
  return assessedModules(subject).length > 0
}

export function radarOption(subject: ReportSubject): Record<string, unknown> {
  const modules = assessedModules(subject)
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: modules.map((module) => ({ name: module.kp_name, max: 1 })),
      radius: '62%',
      axisName: { color: '#667085', fontSize: 11 },
      splitArea: { areaStyle: { color: ['#fbfcfe', '#f4f7fb'] } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 5,
        areaStyle: { opacity: 0.18 },
        data: [
          {
            name: '模块掌握度',
            value: modules.map((module) => Number(module.mastery ?? 0)),
          },
        ],
      },
    ],
  }
}

/** 扁平热力节点组树；缺父节点的数据挂根，避免整块消失。 */
export function buildHeatmapTree(nodes: ReportHeatmapNode[]): HeatmapTreeNode[] {
  const sorted = [...nodes].sort((left, right) => left.level - right.level || left.kp_id - right.kp_id)
  const byId = new Map<number, HeatmapTreeNode>()
  const roots: HeatmapTreeNode[] = []
  for (const node of sorted) {
    byId.set(node.kp_id, {
      name: node.kp_name,
      kp_id: node.kp_id,
      level: node.level,
      value: 1,
      mastery_t: node.mastery_t,
      itemStyle: {
        color: node.assessed && node.mastery_t !== null ? masteryColor(node.mastery_t) : COLOR_UNRATED,
        borderColor: '#ffffff',
        borderWidth: 1,
      },
      children: [],
    })
  }
  for (const node of sorted) {
    const current = byId.get(node.kp_id)
    if (current === undefined) continue
    const parent = node.level > 2 && node.parent_id !== null ? byId.get(node.parent_id) : undefined
    if (parent === undefined) roots.push(current)
    else parent.children.push(current)
  }
  return roots
}

export function treemapOption(nodes: ReportHeatmapNode[]): Record<string, unknown> {
  return {
    tooltip: {
      formatter: (params: { name: string; value: number; data: HeatmapTreeNode }) => {
        const mastery = params.data.mastery_t
        return `${params.name}<br/>掌握度 ${mastery === null ? '未评估' : mastery.toFixed(2)}`
      },
    },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        upperLabel: { show: true, height: 20, color: '#344054' },
        itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
        label: { show: true, color: '#101828', fontSize: 11 },
        data: buildHeatmapTree(nodes),
      },
    ],
  }
}

export function trendOption(trend: ReportTrendPoint[]): Record<string, unknown> {
  const series = [
    { name: '新增笔记', key: 'new_notes', color: '#3b5bdb', dashed: false },
    { name: '完成复习', key: 'reviews_done', color: '#2f9e44', dashed: false },
    { name: '新增错题', key: 'new_mistakes', color: '#e8590c', dashed: false },
    { name: '已掌握错题', key: 'mastered_mistakes', color: '#7048e8', dashed: false },
    { name: '错题净变化', key: 'mistakes_net', color: '#c92a2a', dashed: true },
  ] as const
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll' },
    grid: { left: 36, right: 20, top: 24, bottom: 48 },
    xAxis: { type: 'category', data: trend.map((point) => point.date) },
    yAxis: { type: 'value' },
    series: series.map((row) => ({
      name: row.name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: row.dashed ? { type: 'dashed' } : undefined,
      itemStyle: { color: row.color },
      data: trend.map((point) => Number(point[row.key])),
    })),
  }
}
```

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/reports/useReportCharts.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/views/reports/useReportCharts.ts web/src/views/reports/useReportCharts.spec.ts
git commit -m "feat(s5-7): 报告图表纯函数"
```

---

### Task 5: 报告图片导出

**Files:**
- Create: `web/src/views/reports/exportReportImage.ts`
- Test: `web/src/views/reports/exportReportImage.spec.ts`

**Interfaces:**
- Produces:
  - `ReportImageBlock { dataUrl: string; width: number; height: number }`
  - `ReportImageLayout { width; headerHeight; margin; gap; blocks: Array<{x,y,width,height}>; totalHeight }`
  - `layoutReportImage(blocks, width?): ReportImageLayout`
  - `reportFileName(range: string, date: string): string`
  - `downloadReportImage(opts): Promise<void>`

- [x] **Step 1: 写失败测试**

`web/src/views/reports/exportReportImage.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { layoutReportImage, reportFileName } from './exportReportImage'

describe('layoutReportImage', () => {
  it('keeps equal inner width and vertical gaps', () => {
    const layout = layoutReportImage(
      [
        { width: 600, height: 300 },
        { width: 1200, height: 600 },
      ],
      1200,
    )
    expect(layout.width).toBe(1200)
    expect(layout.blocks[0]).toEqual({ x: 32, y: 110, width: 1136, height: 568 })
    expect(layout.blocks[1]!.width).toBe(1136)
    expect(layout.blocks[1]!.y).toBe(110 + 568 + 24)
    expect(layout.totalHeight).toBe(110 + 568 + 24 + 568 + 32)
  })

  it('handles no blocks without negative height', () => {
    const layout = layoutReportImage([], 1200)
    expect(layout.blocks).toEqual([])
    expect(layout.totalHeight).toBe(142)
  })
})

describe('reportFileName', () => {
  it('includes range and date', () => {
    expect(reportFileName('7d', '2026-11-14')).toBe('report-7d-2026-11-14.png')
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/reports/exportReportImage.spec.ts
```

Expected: FAIL，模块不存在。

- [x] **Step 3: 实现导出**

`web/src/views/reports/exportReportImage.ts`：

```ts
/** S5-7 报告图表导出：ECharts dataURL + 原生 Canvas，不新增依赖。 */
export interface ReportImageBlock {
  dataUrl: string
  width: number
  height: number
}

export interface ReportImageLayout {
  width: number
  headerHeight: number
  margin: number
  gap: number
  blocks: Array<{ x: number; y: number; width: number; height: number }>
  totalHeight: number
}

export const REPORT_IMAGE_WIDTH = 1200
export const REPORT_IMAGE_HEADER = 110
export const REPORT_IMAGE_MARGIN = 32
export const REPORT_IMAGE_GAP = 24

export function layoutReportImage(
  blocks: Array<Pick<ReportImageBlock, 'width' | 'height'>>,
  width = REPORT_IMAGE_WIDTH,
): ReportImageLayout {
  const innerWidth = width - REPORT_IMAGE_MARGIN * 2
  let y = REPORT_IMAGE_HEADER
  const placed = blocks.map((block) => {
    const ratio = block.width > 0 ? innerWidth / block.width : 1
    const height = Math.max(1, Math.round(block.height * ratio))
    const row = { x: REPORT_IMAGE_MARGIN, y, width: innerWidth, height }
    y += height + REPORT_IMAGE_GAP
    return row
  })
  const totalHeight =
    placed.length === 0
      ? REPORT_IMAGE_HEADER + REPORT_IMAGE_MARGIN
      : y - REPORT_IMAGE_GAP + REPORT_IMAGE_MARGIN
  return {
    width,
    headerHeight: REPORT_IMAGE_HEADER,
    margin: REPORT_IMAGE_MARGIN,
    gap: REPORT_IMAGE_GAP,
    blocks: placed,
    totalHeight,
  }
}

export function reportFileName(range: string, date: string): string {
  return `report-${range}-${date}.png`
}

function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片加载失败'))
    image.src = dataUrl
  })
}

export async function downloadReportImage(options: {
  range: string
  subjectName: string
  from: string
  to: string
  blocks: ReportImageBlock[]
}): Promise<void> {
  if (options.blocks.length === 0) throw new Error('没有可导出的图表')
  const layout = layoutReportImage(options.blocks)
  const canvas = document.createElement('canvas')
  canvas.width = layout.width
  canvas.height = layout.totalHeight
  const ctx = canvas.getContext('2d')
  if (ctx === null) throw new Error('浏览器不支持 Canvas')

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#101828'
  ctx.font = '600 30px system-ui, "PingFang SC", "Microsoft YaHei", sans-serif'
  ctx.fillText(`学习报告 · ${options.range}`, layout.margin, 52)
  ctx.fillStyle = '#667085'
  ctx.font = '14px system-ui, "PingFang SC", "Microsoft YaHei", sans-serif'
  ctx.fillText(
    `${options.subjectName} · ${options.from} ~ ${options.to}（UTC）`,
    layout.margin,
    82,
  )

  for (let index = 0; index < options.blocks.length; index += 1) {
    const image = await loadImage(options.blocks[index]!.dataUrl)
    const box = layout.blocks[index]!
    ctx.drawImage(image, box.x, box.y, box.width, box.height)
  }

  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob(resolve, 'image/png')
  })
  if (blob === null) throw new Error('导出 PNG 失败')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = reportFileName(options.range, options.to)
  link.click()
  URL.revokeObjectURL(url)
}
```

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/reports/exportReportImage.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/views/reports/exportReportImage.ts web/src/views/reports/exportReportImage.spec.ts
git commit -m "feat(s5-7): 报告图表 PNG 导出"
```

---

### Task 6: 学习报告页

**Files:**
- Create: `web/src/views/reports/Index.vue`
- Test: `web/src/views/reports/Index.spec.ts`

**Interfaces:**
- Consumes:
  - Task 1 `fetchReportOverview` / `generateWeeklyReport`
  - Task 4 `pageSummary` / `radarOption` / `treemapOption` / `trendOption` / `hasAssessed`
  - Task 5 `downloadReportImage`
  - `PageHeader`、`EmptyState`、`MdPreview`
- Produces: `/reports` 页面；test ids `report-range-7d|30d|90d`、`report-radar`、`report-treemap`、`report-trend`、`weekly-generate`、`weekly-report`、`report-export`。

- [x] **Step 1: 写失败测试**

`web/src/views/reports/Index.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReportOverview, WeeklyReport } from '@/types/reports'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    getDataURL: vi.fn(() => 'data:image/png;base64,abc'),
    dispose: vi.fn(),
  }
  return {
    chart,
    init: vi.fn((element: unknown) => ({ ...chart, getDom: () => element })),
    use: vi.fn(),
  }
})
vi.mock('echarts/core', () => ({ use: charts.use, init: charts.init }))
vi.mock('echarts/charts', () => ({ RadarChart: {}, TreemapChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({
  fetchReportOverview: vi.fn(),
  generateWeeklyReport: vi.fn(),
}))
vi.mock('@/api/reports', () => api)

vi.mock('md-editor-v3', () => ({
  MdPreview: { props: ['modelValue'], template: '<div data-testid="weekly-md">{{ modelValue }}</div>' },
}))

const image = vi.hoisted(() => ({ downloadReportImage: vi.fn() }))
vi.mock('./exportReportImage', () => image)

import Reports from './Index.vue'

function overview(overrides: Partial<ReportOverview> = {}): ReportOverview {
  return {
    range: { key: '30d', from: '2026-10-16', to: '2026-11-14' },
    subjects: [
      {
        subject_id: 7,
        subject_name: '高中数学',
        modules: [
          { kp_id: 115, kp_name: '函数', exam_weight: 0.8, kp_count: 3, assessed_count: 2, mastery: 0.52 },
          { kp_id: 120, kp_name: '数列', exam_weight: 0.4, kp_count: 2, assessed_count: 0, mastery: null },
        ],
        heatmap: [
          { kp_id: 115, kp_name: '函数', parent_id: null, level: 2, exam_weight: 0.8, mastery: 0.5, mastery_t: 0.48, color_value: 0.52, assessed: true },
          { kp_id: 120, kp_name: '数列', parent_id: null, level: 2, exam_weight: 0.4, mastery: null, mastery_t: null, color_value: null, assessed: false },
        ],
      },
    ],
    trend: [
      { date: '2026-11-13', new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
    ],
    ...overrides,
  }
}

function weekly(overrides: Partial<WeeklyReport> = {}): WeeklyReport {
  return {
    period: { from: '2026-11-08', to: '2026-11-14', days: 7 },
    generated_by: 'llm',
    report_md: '## 本周概览\n本周新增 1 条。',
    stats: {
      totals: { new_notes: 1, reviews_done: 2, new_mistakes: 3, mastered_mistakes: 1, mistakes_net: 2 },
      active_days: 2,
      mastery: { assessed_kp_count: 2, avg_mastery: 0.5, weak_modules: [], weak_kps: [] },
      trend: [],
    },
    validation: { ok: true, attempts: 1, checked_numbers: ['1', '2', '3'], invalid_numbers: [] },
    ...overrides,
  }
}

function mountPage() {
  return mount(Reports, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchReportOverview.mockResolvedValue(overview())
  api.generateWeeklyReport.mockResolvedValue(weekly())
})

describe('Reports 页面', () => {
  it('默认加载 30d，初始化三张图并渲染摘要', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.fetchReportOverview).toHaveBeenCalledWith('30d')
    expect(charts.init).toHaveBeenCalledTimes(3)
    expect(charts.chart.setOption).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('新增笔记')
    expect(wrapper.text()).toContain('模块雷达')
  })

  it('切换 range 会重新请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="report-range-7d"] input').setValue(true)
    await flushPromises()
    expect(api.fetchReportOverview).toHaveBeenLastCalledWith('7d')
  })

  it('进入页面不生成周报，点击后才调用', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.generateWeeklyReport).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="weekly-generate"]').trigger('click')
    await flushPromises()
    expect(api.generateWeeklyReport).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="weekly-report"]').text()).toContain('本周新增 1 条')
  })

  it('空数据给空态，不画假图', async () => {
    api.fetchReportOverview.mockResolvedValue(overview({ subjects: [], trend: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无知识库数据')
    expect(wrapper.find('[data-testid="report-radar"]').exists()).toBe(false)
  })

  it('加载失败给错误与重试', async () => {
    api.fetchReportOverview.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('报告加载失败')
  })

  it('导出按钮在图表就绪时可点击，并调用导出', async () => {
    const wrapper = mountPage()
    await flushPromises()
    for (const id of ['report-radar', 'report-treemap', 'report-trend']) {
      const element = wrapper.get(`[data-testid="${id}"]`).element as HTMLElement
      Object.defineProperty(element, 'clientWidth', { configurable: true, value: 600 })
      Object.defineProperty(element, 'clientHeight', { configurable: true, value: 280 })
    }
    const button = wrapper.get('[data-testid="report-export"]')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await flushPromises()
    expect(image.downloadReportImage).toHaveBeenCalled()
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/reports/Index.spec.ts
```

Expected: FAIL，`Index.vue` 不存在。

- [x] **Step 3: 实现页面**

`web/src/views/reports/Index.vue` 的脚本必须包含：

```ts
import { LineChart, RadarChart, TreemapChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { MdPreview } from 'md-editor-v3'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchReportOverview, generateWeeklyReport } from '@/api/reports'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { ReportOverview, ReportRange, WeeklyReport } from '@/types/reports'

import { downloadReportImage } from './exportReportImage'
import {
  hasAssessed,
  pageSummary,
  radarOption,
  treemapOption,
  trendOption,
} from './useReportCharts'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

echarts.use([
  RadarChart,
  TreemapChart,
  LineChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  CanvasRenderer,
])

const RANGE_OPTIONS: Array<{ value: ReportRange; label: string }> = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
]

const range = ref<ReportRange>('30d')
const data = ref<ReportOverview | null>(null)
const loading = ref(true)
const error = ref('')
const subjectIndex = ref(0)
const weekly = ref<WeeklyReport | null>(null)
const weeklyLoading = ref(false)
const weeklyError = ref('')
const exporting = ref(false)
const chartsReady = ref(false)

const radarCanvas = ref<HTMLDivElement | null>(null)
const treemapCanvas = ref<HTMLDivElement | null>(null)
const trendCanvas = ref<HTMLDivElement | null>(null)
let radarChart: echarts.ECharts | null = null
let treemapChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const subjects = computed(() => data.value?.subjects ?? [])
const activeSubject = computed(() => subjects.value[subjectIndex.value] ?? null)
const cards = computed(() => (data.value === null ? [] : pageSummary(data.value.trend)))
const radarEmpty = computed(() => activeSubject.value !== null && !hasAssessed(activeSubject.value))
const treemapEmpty = computed(() => (activeSubject.value?.heatmap.length ?? 0) === 0)
const noSubjects = computed(() => data.value !== null && subjects.value.length === 0)
const exportDisabled = computed(
  () =>
    data.value === null ||
    activeSubject.value === null ||
    radarEmpty.value ||
    treemapEmpty.value ||
    !chartsReady.value,
)

function bind(
  element: HTMLDivElement | null,
  chart: echarts.ECharts | null,
): echarts.ECharts | null {
  if (element === null) {
    chart?.dispose()
    return null
  }
  if (chart !== null && chart.getDom() === element) return chart
  chart?.dispose()
  return echarts.init(element)
}

function syncCharts(): void {
  radarChart = bind(radarCanvas.value, radarChart)
  treemapChart = bind(treemapCanvas.value, treemapChart)
  trendChart = bind(trendCanvas.value, trendChart)
  chartsReady.value =
    radarChart !== null && treemapChart !== null && trendChart !== null
}

function render(): void {
  const subject = activeSubject.value
  const current = data.value
  if (subject !== null && hasAssessed(subject)) {
    radarChart?.setOption(radarOption(subject), true)
  }
  if (subject !== null && subject.heatmap.length > 0) {
    treemapChart?.setOption(treemapOption(subject.heatmap), true)
  }
  if (current !== null) {
    trendChart?.setOption(trendOption(current.trend), true)
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchReportOverview(range.value)
    subjectIndex.value = 0
  } catch {
    data.value = null
    error.value = '报告加载失败，请重试'
  } finally {
    loading.value = false
  }
  await nextTick()
  syncCharts()
  render()
}

watch(range, load)
watch(subjectIndex, async () => {
  await nextTick()
  render()
})

async function onWeekly(): Promise<void> {
  if (weeklyLoading.value) return
  weeklyLoading.value = true
  weeklyError.value = ''
  try {
    weekly.value = await generateWeeklyReport()
  } catch {
    weekly.value = null
    weeklyError.value = '周报生成失败，请稍后重试'
  } finally {
    weeklyLoading.value = false
  }
}

function chartSource(
  chart: echarts.ECharts | null,
  element: HTMLDivElement | null,
): { dataUrl: string; width: number; height: number } | null {
  if (chart === null || element === null || element.clientWidth <= 0 || element.clientHeight <= 0) {
    return null
  }
  return {
    dataUrl: chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }),
    width: element.clientWidth,
    height: element.clientHeight,
  }
}

async function onExport(): Promise<void> {
  const subject = activeSubject.value
  const current = data.value
  if (subject === null || current === null || exportDisabled.value) return
  const blocks = [
    chartSource(radarChart, radarCanvas.value),
    chartSource(treemapChart, treemapCanvas.value),
    chartSource(trendChart, trendCanvas.value),
  ]
  if (blocks.some((block) => block === null)) {
    ElMessage.warning('图表尚未准备好，请稍后再试')
    return
  }
  exporting.value = true
  try {
    await downloadReportImage({
      range: current.range.key,
      subjectName: subject.subject_name,
      from: current.range.from,
      to: current.range.to,
      blocks: blocks as Array<{ dataUrl: string; width: number; height: number }>,
    })
  } catch {
    ElMessage.error('导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  void load()
})

onBeforeUnmount(() => {
  radarChart?.dispose()
  treemapChart?.dispose()
  trendChart?.dispose()
  radarChart = null
  treemapChart = null
  trendChart = null
})
```

模板必须覆盖：

```vue
<template>
  <div class="reports-page">
    <PageHeader title="学习报告" description="模块雷达、知识点热力与趋势；range 只影响趋势，掌握度是当前快照。">
      <template #actions>
        <el-button
          :disabled="exportDisabled || exporting"
          :loading="exporting"
          data-testid="report-export"
          @click="onExport"
        >导出图表 PNG</el-button>
      </template>
    </PageHeader>

    <div class="reports-toolbar">
      <el-radio-group v-model="range" size="small">
        <el-radio-button v-for="item in RANGE_OPTIONS" :key="item.value" :value="item.value" :data-testid="`report-range-${item.value}`">
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>
      <span v-if="data">{{ data.range.from }} ~ {{ data.range.to }}（UTC）</span>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" data-testid="report-error" />
    <el-skeleton v-if="loading" :rows="5" animated data-testid="report-loading" />

    <EmptyState v-else-if="noSubjects" title="暂无知识库数据" description="先导入知识点与笔记，再来看学习报告。" />

    <template v-else-if="data">
      <section class="report-cards">
        <div v-for="card in cards" :key="card.label" class="report-card">
          <strong>{{ card.value }}</strong><span>{{ card.label }}</span>
        </div>
      </section>

      <el-radio-group v-if="subjects.length > 1" v-model="subjectIndex" size="small" class="subject-tabs">
        <el-radio-button v-for="(subject, index) in subjects" :key="subject.subject_id" :value="index">
          {{ subject.subject_name }}
        </el-radio-button>
      </el-radio-group>

      <div class="report-grid">
        <section class="report-panel">
          <h3>模块雷达</h3>
          <p v-if="radarEmpty" class="report-empty">暂无已评估模块；未评估模块不纳入雷达。</p>
          <div ref="radarCanvas" class="report-canvas" data-testid="report-radar" />
        </section>
        <section class="report-panel">
          <h3>知识点热力</h3>
          <p v-if="treemapEmpty" class="report-empty">暂无知识点。</p>
          <div ref="treemapCanvas" class="report-canvas" data-testid="report-treemap" />
        </section>
        <section class="report-panel report-panel--wide">
          <h3>近期趋势</h3>
          <p class="report-empty">日界为 UTC；复习完成数只反映当前 done_at 快照。</p>
          <div ref="trendCanvas" class="report-canvas" data-testid="report-trend" />
        </section>
      </div>

      <section class="weekly-panel">
        <div class="weekly-head">
          <h3>本周周报</h3>
          <el-button type="primary" :loading="weeklyLoading" data-testid="weekly-generate" @click="onWeekly">
            生成周报
          </el-button>
        </div>
        <p class="weekly-hint">仅点击后调用真实 LLM，约需数秒；空数据会返回固定文案。</p>
        <el-alert v-if="weeklyError" type="error" :closable="false" :title="weeklyError" data-testid="weekly-error" />
        <div v-if="weekly" data-testid="weekly-report">
          <p>{{ weekly.period.from }} ~ {{ weekly.period.to }} · {{ weekly.generated_by === 'empty' ? '空数据' : 'LLM 生成' }} · 校验 {{ weekly.validation.attempts }} 次</p>
          <MdPreview :model-value="weekly.report_md" :no-mermaid="true" preview-theme="github" />
          <p>检查数字 {{ weekly.validation.checked_numbers.length }} 个，非法 {{ weekly.validation.invalid_numbers.length }} 个。</p>
        </div>
      </section>
    </template>
  </div>
</template>
```

样式至少包含：`.reports-page { display:flex; flex-direction:column; gap:16px }`、`.report-cards` 五列网格、`.report-grid` 两列网格、`.report-panel--wide { grid-column: 1 / -1 }`、`.report-canvas { width:100%; height:280px }`、`.weekly-panel { padding:16px; background:#fff; border:1px solid #eaecf0; border-radius:10px }`。

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/reports/Index.spec.ts
```

Expected: PASS。若测试中 `clientWidth` 为 0 导致导出不调用，先给 `report-canvas` mock 元素 `Object.defineProperty(element, 'clientWidth', { value: 600 })`，或在页面测试中只断言按钮可点击；导出核心已由 Task 5 单测覆盖。

- [x] **Step 5: 提交**

```bash
git add web/src/views/reports/Index.vue web/src/views/reports/Index.spec.ts
git commit -m "feat(s5-7): 学习报告页"
```

---

### Task 7: 练习入口页

**Files:**
- Create: `web/src/views/practice/PracticeHome.vue`
- Test: `web/src/views/practice/PracticeHome.spec.ts`

**Interfaces:**
- Consumes: `PageHeader`。
- Produces: `/practice` 页面；三张入口卡。

- [x] **Step 1: 写失败测试**

`web/src/views/practice/PracticeHome.spec.ts`：

```ts
import { mount, RouterLinkStub } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import PracticeHome from './PracticeHome.vue'

describe('PracticeHome', () => {
  it('renders three entries with correct targets', () => {
    const wrapper = mount(PracticeHome, {
      global: { plugins: [ElementPlus], stubs: { RouterLink: RouterLinkStub } },
    })
    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links.map((link) => link.props('to'))).toEqual([
      '/review',
      '/papers/generate',
      '/mistakes',
    ])
    expect(wrapper.text()).toContain('今日复习')
    expect(wrapper.text()).toContain('智能组卷')
    expect(wrapper.text()).toContain('错题回顾')
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/views/practice/PracticeHome.spec.ts
```

Expected: FAIL，组件不存在。

- [x] **Step 3: 实现页面**

`web/src/views/practice/PracticeHome.vue`：

```vue
<script setup lang="ts">
/** S5-7 练习入口：不列草稿、不新增接口，只做三个现有流程的入口。 */
import PageHeader from '@/components/common/PageHeader.vue'

const entries = [
  {
    title: '今日复习',
    description: '按掌握度与到期时间生成的清单，逐项完成或顺延。',
    to: '/review',
    action: '打开复习清单',
  },
  {
    title: '智能组卷',
    description: '选知识点、题型与难度，生成后可直接在线作答。',
    to: '/papers/generate',
    action: '开始组卷',
  },
  {
    title: '错题回顾',
    description: '查看错题、诊断结果与变式题。',
    to: '/mistakes',
    action: '打开错题本',
  },
] as const
</script>

<template>
  <div class="practice-page">
    <PageHeader title="练习" description="从复习清单、组卷或错题本进入练习；组卷保存后可直接开始作答。" />
    <div class="practice-grid">
      <article v-for="entry in entries" :key="entry.title" class="practice-card">
        <h2>{{ entry.title }}</h2>
        <p>{{ entry.description }}</p>
        <router-link :to="entry.to">
          <el-button type="primary" plain>{{ entry.action }}</el-button>
        </router-link>
      </article>
    </div>
    <p class="practice-note">
      本页不列历史草稿：当前没有 GET /papers 接口，草稿从组卷保存后的页面进入作答。
    </p>
  </div>
</template>

<style scoped>
.practice-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.practice-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.practice-card {
  display: grid;
  gap: 12px;
  padding: 20px;
  background: #fff;
  border: 1px solid #eaecf0;
  border-radius: 10px;
}
.practice-card h2 {
  margin: 0;
  font-size: 16px;
}
.practice-card p {
  margin: 0;
  color: #667085;
  font-size: 13px;
  line-height: 1.7;
}
.practice-note {
  margin: 0;
  color: #98a2b3;
  font-size: 12px;
}
</style>
```

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/views/practice/PracticeHome.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/views/practice/PracticeHome.vue web/src/views/practice/PracticeHome.spec.ts
git commit -m "feat(s5-7): 练习入口页"
```

---

### Task 8: 路由、导航与旧入口兼容

**Files:**
- Modify: `web/src/router/index.ts`
- Modify: `web/src/layouts/nav.ts`
- Test: `web/src/layouts/nav.spec.ts`
- Test: `web/src/router/index.spec.ts`

**Interfaces:**
- Produces: `/review`、`/reports`、`/practice` 路由名与导航项；`/plan` 重定向 `/review`。

- [x] **Step 1: 写失败测试**

`web/src/layouts/nav.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { NAV_ITEMS } from './nav'

describe('NAV_ITEMS', () => {
  it('has review, practice and reports entries', () => {
    const byName = Object.fromEntries(NAV_ITEMS.map((item) => [item.name, item.path]))
    expect(byName.review).toBe('/review')
    expect(byName.practice).toBe('/practice')
    expect(byName.reports).toBe('/reports')
    expect(byName.plan).toBeUndefined()
  })
})
```

`web/src/router/index.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import router from './index'

describe('S5-7 routes', () => {
  it('registers review, reports and practice', () => {
    const paths = router.getRoutes().map((route) => route.path)
    expect(paths).toContain('/review')
    expect(paths).toContain('/reports')
    expect(paths).toContain('/practice')
  })

  it('keeps /plan as a redirect to /review', () => {
    const plan = router.getRoutes().find((route) => route.path === '/plan')
    expect(plan?.redirect).toBe('/review')
  })
})
```

- [x] **Step 2: 运行确认失败**

Run:
```bash
cd web
npm run test:run -- src/layouts/nav.spec.ts src/router/index.spec.ts
```

Expected: FAIL，导航项与路由不存在。

- [x] **Step 3: 实现路由与导航**

`web/src/layouts/nav.ts` 最终 `NAV_ITEMS`：

```ts
export const NAV_ITEMS: NavItem[] = [
  { label: '笔记', name: 'notes', path: '/notes' },
  { label: '文件', name: 'files', path: '/files' },
  { label: '知识库', name: 'knowledge', path: '/knowledge' },
  { label: '题库', name: 'questions', path: '/questions' },
  { label: '组卷', name: 'papers', path: '/papers/generate' },
  { label: '练习', name: 'practice', path: '/practice' },
  { label: '智能问答', name: 'qa', path: '/qa' },
  { label: '错题本', name: 'mistakes', path: '/mistakes' },
  { label: '复习', name: 'review', path: '/review' },
  { label: '报告', name: 'reports', path: '/reports' },
  { label: '图谱', name: 'graph', path: '/graph' },
  { label: '统计', name: 'stats', path: '/stats' },
]
```

`web/src/router/index.ts` 在 `children` 中：

```ts
{
  path: 'review',
  name: 'review',
  component: () => import('@/views/review/Today.vue'),
  meta: { title: '复习清单', nav: 'review', roles: ['student'] },
},
{
  path: 'reports',
  name: 'reports',
  component: () => import('@/views/reports/Index.vue'),
  meta: { title: '学习报告', nav: 'reports', roles: ['student'] },
},
{
  path: 'practice',
  name: 'practice',
  component: () => import('@/views/practice/PracticeHome.vue'),
  meta: { title: '练习', nav: 'practice', roles: ['student'] },
},
{
  path: 'plan',
  redirect: '/review',
},
```

删除原来的 `plan` ComingSoonView 路由（同一个 path 不要重复注册）。

- [x] **Step 4: 运行确认通过**

Run:
```bash
cd web
npm run test:run -- src/layouts/nav.spec.ts src/router/index.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/router/index.ts web/src/layouts/nav.ts web/src/layouts/nav.spec.ts web/src/router/index.spec.ts
git commit -m "feat(s5-7): 复习报告练习路由与导航"
```

---

### Task 9: 文档、全量验证与验收证据

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/AI协作开发实施计划.md`（勾选 S5-7）
- Create: `.sdd/s5-7/acceptance-evidence.md`（仓库外，不提交）
- Modify: `docs/plan/s5-7-frontend-review-report-practice.md`（本文件，执行后勾选复选框）

**Interfaces:**
- Consumes: 前 8 个任务的页面与测试。
- Produces: 可交付的 S5-7 记录与真实验收证据。

- [x] **Step 1: 跑全量前端测试与构建**

Run:
```bash
cd web
npm run test:run
npm run build
```

Expected: 所有测试 PASS；`build` 退出 0（仅允许既有 chunk-size 警告）。

- [x] **Step 2: 跑后端回归**

Run:
```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
```

Expected: 仍为 S5-6 的 1435 passed（前端改动不应影响后端）。

- [x] **Step 3: 真实页面验收**

启动后端（8000）与前端 dev（5173），用学生 50：

1. `/review`：
   - 进入页面触发 `POST /review/refresh`；记录清单数量、总分钟、上限。
   - 至少完成 1 项、跳过 1 项、稍后 1 项；刷新后确认状态持久。
   - 记录空态/顺延提示（若真实数据没有，明确写“本轮真实数据未触发”）。
2. `/reports`：
   - 切换 7d/30d/90d，确认雷达/热力/趋势渲染。
   - 点击生成周报，记录 `generated_by`、`attempts`、checked/invalid 数量。
   - 点击导出 PNG，确认文件存在且能打开。
3. `/practice`：三个入口可跳转。

把真实请求状态、页面截图路径/文字观察、测试计数写入 `.sdd/s5-7/acceptance-evidence.md`。不要写假数据。

- [x] **Step 4: 更新文档**

`docs/PROGRESS.md`：
- 当前状态加 S5-7 完成摘要（页面路径、API 复用、测试计数、已知缺口：未做手机适配、练习页无草稿列表）。
- 阶段 5 勾选 `S5-7`。
- 变更记录加 S5-7 条目；如果测试计数变化，写实际输出。

`docs/AI协作开发实施计划.md`：
- `[ ] S5-7 前端复习/报告/练习页` 改成 `[x]`。

`docs/plan/s5-7-frontend-review-report-practice.md`：
- 将已完成步骤的 `- [ ]` 改为 `- [x]`。

- [x] **Step 5: 提交**

```bash
git add docs/PROGRESS.md docs/AI协作开发实施计划.md docs/plan/s5-7-frontend-review-report-practice.md
git commit -m "docs(s5-7): 同步进度与验收"
```

- [x] **Step 6: 最终检查**

Run:
```bash
git status --short
git log --oneline -5
```

Expected: 工作树干净（`.sdd` 在仓库外）；最近提交包含 S5-7 的 feat/docs。

---

## 自检结果

- **Spec 覆盖**：路由/导航 → Task 8；复习页 → Task 1–3；报告页/周报/导出 → Task 1、4–6；练习入口 → Task 7；文档与验收 → Task 9。
- **无占位符**：计划中的函数、类型、测试、命令均为具体内容；页面样式给出了必要类名与关键规则。
- **类型一致**：`ReviewToday`/`ReviewItem`、`ReportOverview`、`WeeklyReport` 与 Task 1 定义一致；`progressOf`、`radarOption`、`layoutReportImage` 名称在后续任务中保持一致。
- **明确不做**：不新增依赖、不改后端、不做手机适配、不列草稿；与 spec 一致。