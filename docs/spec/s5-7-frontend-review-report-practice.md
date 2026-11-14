# S5-7 前端复习 / 报告 / 练习页（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S5-7。
> 范围：只做前端，复用 S5-5/S5-6 已交付接口；不新增后端接口、不新增前端依赖。
> 用户已确认：练习页只做入口；报告导出用图表合成 PNG；本轮不做手机适配；报告页包含周报；完成反馈用进度动画而非伪造掌握度变化。

## 1. 目标

把已经落地的复习调度与学习报告能力接成学生可用的页面，形成「组卷 → 作答 → 复习 → 报告」闭环：

1. `/review`：今天要复习什么、每项多久、完成/跳过/稍后。
2. `/reports`：模块雷达、知识点热力、近 N 天趋势、周报、导出图表 PNG。
3. `/practice`：练习入口，串起复习、组卷、错题回顾。

## 2. 不做

- 不新增 `GET /papers` 草稿列表接口；练习页不列历史草稿。
- 不新增 DOM 截图/图片导出依赖；不引入 `html-to-image`。
- 不改后端、不改数据库、不改 Prompt。
- 不做手机/窄屏适配（用户本轮明确选择）；任务卡的 H5 手机验收项本轮不满足，记录为已知缺口。
- 不导出周报 Markdown 为图片；图片只含图表区。
- 不把 `done/skip/later` 包装成掌握度变化；后端不返回掌握度变化，前端不伪造。

## 3. 路由与导航

| 路径 | name | 导航 | 权限 | 说明 |
|---|---|---|---|---|
| `/review` | `review` | 复习 | student | 今日复习清单 |
| `/reports` | `reports` | 报告 | student | 学习报告 + 周报 |
| `/practice` | `practice` | 练习 | student | 练习入口 |
| `/plan` | — | — | — | 重定向到 `/review`，兼容旧入口 |

- `layouts/nav.ts` 把原「复习计划」改为「复习」并指向 `/review`，新增「练习」「报告」。
- 路由 `meta.roles: ['student']`，沿用 `router/guard.ts` 的既有权责。
- 页面文件：
  - `web/src/views/review/Today.vue`
  - `web/src/views/reports/Index.vue`
  - `web/src/views/practice/PracticeHome.vue`

## 4. 接口与前端类型

### 4.1 复习

新增 `web/src/api/review.ts`、`web/src/types/review.ts`：

- `refreshReview(): Promise<ReviewToday>` → `POST /api/v1/review/refresh`
- `getTodayReview(): Promise<ReviewToday>` → `GET /api/v1/review/today`
- `markReviewDone(id): Promise<ReviewItem>` → `POST /api/v1/review/items/{id}/done`
- `markReviewSkip(id): Promise<ReviewItem>` → `POST /api/v1/review/items/{id}/skip`
- `markReviewLater(id): Promise<ReviewItem>` → `POST /api/v1/review/items/{id}/later`

类型镜像后端 `ReviewTodayOut` / `ReviewItemOut`：

```ts
export interface ReviewItem {
  id: number
  kp_id: number
  kp_name: string
  subject_id: number
  ref_type: 'question' | 'mistake'
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

### 4.2 报告

新增 `web/src/api/reports.ts`、`web/src/types/reports.ts`：

- `fetchReportOverview(range: ReportRange = '30d'): Promise<ReportOverview>`
  → `GET /api/v1/reports/mastery?range=...`
- `generateWeeklyReport(): Promise<WeeklyReport>`
  → `POST /api/v1/reports/weekly`（无请求体）

类型镜像：

```ts
export type ReportRange = '7d' | '30d' | '90d'

export interface ReportRangeInfo { key: ReportRange; from: string; to: string }
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

`WeeklyReport` 不再引用未定义结构。

## 5. 复习清单页

### 5.1 加载

1. `onMounted` 调 `refreshReview()`（契约要求进入页面先 refresh，不隐式依赖 GET）。
2. 成功后展示返回的 `date/timezone/items/total_minutes/cap_minutes/truncated_count`。
3. “重新生成”按钮再次调用 refresh；刷新期间禁用操作。
4. `getTodayReview()` 保留在 API 客户端，供后续只读场景；本页不自动调用。

### 5.2 展示

- 顶部：日期 + 时区、预计总分钟 / 上限、已处理进度、`truncated_count > 0` 时提示“有 N 项顺延到明天”。
- 每项卡片：
  - 知识点名、`low_mastery` 徽标、`ref_title`。
  - 掌握度 `mastery_t`（`toFixed(2)`）与优先级/逾期天数/预计分钟。
  - `ref_available=false` 时显示“参考资源已删除”，不可跳转。
  - `ref_type='mistake'` 可跳 `/mistakes/{ref_id}`；`question` 跳 `/questions`。
- 完成/跳过/稍后三个按钮，动作进行中只禁用当前项。

### 5.3 动作反馈

- done/skip：调用对应接口成功后，把该项从列表移除；`processed` +1。
- later：调用成功后移除，提示“已顺延到明天”；同样计入已处理。
- 卡片用 `<TransitionGroup>` 播放退出动画；顶部进度条宽度过渡。
- 提示文案只说“已记录”，不出现“掌握度提升/下降”。
- 接口失败：保留卡片、恢复按钮，给出局部错误；若前端已有统一 `ElMessage`，不重复弹窗。
- 全部处理完：空态“今天的复习已完成”，保留“重新生成”和“去组卷”。

### 5.4 空态 / 错误

- `items=[]`：空态文案 + “去组卷”/“重新生成”。
- refresh 失败：错误提示 + 重试按钮；不展示旧数据冒充新数据。
- 操作失败：卡片保留，页面局部提示。

## 6. 学习报告页

### 6.1 加载与 range

- 默认 `30d`；切换 `7d/30d/90d` 重新请求 overview。
- range 只影响趋势；雷达/热力是当前快照，页面文案明确说明。
- 请求期间骨架屏；失败给错误与重试。
- 多学科时用学科切换（默认第一个）；雷达/热力跟随选中学科，趋势共用。
- 无 subjects：显示“暂无知识库数据”，不画假图。

### 6.2 摘要卡

只用 overview 可精确计算的数：

- 新增笔记 = `sum(trend.new_notes)`
- 完成复习 = `sum(trend.reviews_done)`
- 新增错题 = `sum(trend.new_mistakes)`
- 已掌握错题 = `sum(trend.mastered_mistakes)`
- 净变化 = `sum(trend.mistakes_net)`

不计算“复习完成率”“薄弱点变化”。

### 6.3 雷达

- 每个学科一张，模块来自 `modules`。
- 只把 `mastery !== null` 的模块作为雷达 indicator 和 series；未评估模块不进入雷达，页面用文案注明“未评估模块未纳入雷达”，不把 null 画成 0。
- 一个已评估模块都没有时显示“暂无已评估模块”，不画 0 值。
- 数值范围 0–1，tooltip 显示模块名与掌握度；`assessed_count` 可放副标题。

### 6.4 热力 Treemap

把扁平的 `heatmap` 组树：

- `level=2` 为根，`level=3/4` 按 `parent_id` 挂到父节点。
- 找不到父节点的节点挂到该学科根级，避免丢数据。
- 仅 `assessed=true` 的节点显示掌握度；未评估节点灰色（`COLOR_UNRATED`）。
- 颜色复用 `utils/masteryColor`（按 `mastery_t` 分档），tooltip 显示名称、层级、`mastery_t`。
- 没有节点时显示“暂无知识点”。

### 6.5 趋势

- 五条线：`new_notes`、`reviews_done`、`new_mistakes`、`mastered_mistakes`、`mistakes_net`。
- `mistakes_net` 用虚线，避免与新增/掌握混淆。
- 横轴日期取 `trend[].date`；纵轴非负整数（`mistakes_net` 可为负）。
- 全 0 时仍画图但给“窗口内暂无学习活动”的说明。

### 6.6 周报

- 只有点击“生成周报”才调用 `POST /reports/weekly`；进页面不自动调用。
- 生成中按钮 loading，文案提示“约需数秒”。
- 成功：
  - 周期 `from ~ to`、`generated_by`（llm/empty）。
  - `report_md` 用 `MdPreview` 渲染，引入 `md-editor-v3/lib/preview.css` 与 KaTeX CSS。
  - 校验摘要：attempts、checked 数量、invalid 数量；不展示 Prompt/模型内部信息。
- `generated_by='empty'`：展示固定空文案，明确“本周暂无学习记录”。
- 500：局部错误“周报生成失败，请稍后重试”；不回退到假数据。
- range 切换不清空已生成周报；周报区域独立显示其 period。

### 6.7 导出图表 PNG

- 入口：报告页“导出图表 PNG”按钮；数据/图表未就绪时禁用。
- 用当前 ECharts 实例的 `getDataURL({ pixelRatio: 2, backgroundColor: '#fff' })` 取雷达、Treemap、趋势三张图。
- 原生 `Canvas` 合成：
  - 白底、标题“学习报告 · {range}”、副标题“{学科} · {from} ~ {to}”。
  - 三张图纵向排列，宽度一致，间距 24px；总高度按图片实际比例计算。
  - `canvas.toBlob` 下载 `report-{range}-{date}.png`。
- 不包含周报 Markdown、不包含页面按钮。
- 若任一图表未初始化或无数据：按钮禁用/提示，不导出残缺图。
- 导出逻辑拆成：
  - 纯布局函数（可单测尺寸/间距）。
  - 浏览器下载函数（Canvas/URL 依赖放在最薄一层）。

## 7. 练习入口页

- 三张入口卡：
  - 今日复习 → `/review`
  - 智能组卷 → `/papers/generate`
  - 错题回顾 → `/mistakes`
- 一段说明：组卷页保存草稿后可直接开始作答；本页不列历史草稿。
- 不请求额外接口。

## 8. 错误、空态与文案

- 所有页面沿用 `http.ts` 的统一错误提示；页面只保留可重试的局部状态。
- 不用假数据填图；空数据一律空态。
- 时间展示：复习页日期用后端本地日期字符串；报告页趋势日期原样显示 `YYYY-MM-DD`，并标注 UTC 口径。
- 掌握度显示统一 `toFixed(2)`；未评估显示“未评估”。

## 9. 测试

前端测试全部 mock API 与 ECharts，不真实请求。

1. `api/review.spec.ts`：5 个端点、方法、路径、解包。
2. `api/reports.spec.ts`：GET range 参数、POST 无请求体、解包。
3. `views/review/useReviewProgress.spec.ts`：已处理/进度百分比/分钟格式/按钮文案纯函数。
4. `views/review/Today.spec.ts`：进入即 refresh、渲染卡片、done/skip/later 各走对应 API 并移除、空态、失败保留卡片、truncated 提示。
5. `views/reports/useReportCharts.spec.ts`：雷达排除 null、Treemap 组树与孤儿兜底、趋势五条线、摘要卡求和。
6. `views/reports/exportReportImage.spec.ts`：布局尺寸/间距/文件名的纯函数。
7. `views/reports/Index.spec.ts`：默认 30d、range 切换、三图初始化、周报只点击生成、empty/失败、导出按钮状态。
8. `views/practice/PracticeHome.spec.ts`：三张入口卡的跳转目标。
9. `router` / `layouts/nav.spec.ts`：路由存在、`/plan` 重定向、导航项。
10. 回归：`npm run test:run`、`npm run build`；后端 `pytest -q` 确认无回归。

## 10. 验收

- `npm run test:run` 全绿，新增用例覆盖上述行为。
- `npm run build` 退出 0。
- 真实后端 + 学生 50：
  - 打开 `/review`，refresh 返回清单；完成/跳过/稍后至少各验证一次，刷新后状态持久。
  - 打开 `/reports`，切换 7d/30d/90d；雷达/热力/趋势有真实数据；生成周报成功或空数据分支符合契约；导出 PNG 可打开。
  - 打开 `/practice`，三个入口可跳转。
- 后端 pytest 仍全绿。

## 11. 已知限制

- 不做手机/窄屏适配（用户本轮确认）；侧栏与 `body min-width` 保持现状。
- 练习页不列历史草稿；没有 `GET /papers`。
- 复习页进入即调 refresh，会重算本人清单；多次进入成本可接受，但不像 GET 一样只读。
- 周报同步调用真实 LLM，每次数秒且无缓存；页面只允许手动触发。
- 导出 PNG 是图表合成，不含周报正文与页面交互控件；字体由浏览器本地字体决定。
- 雷达不画未评估模块，因此“模块总数”与雷达点数可能不同；页面用文案说明。
- `reviews_done` 仍是当前 `done_at` 快照；报告页不提供复习完成率。

## 12. 文件清单

新增：

- `web/src/types/review.ts`
- `web/src/types/reports.ts`
- `web/src/api/review.ts` + `review.spec.ts`
- `web/src/api/reports.ts` + `reports.spec.ts`
- `web/src/views/review/Today.vue`
- `web/src/views/review/useReviewProgress.ts` + `.spec.ts`
- `web/src/views/review/Today.spec.ts`
- `web/src/views/reports/Index.vue`
- `web/src/views/reports/useReportCharts.ts` + `.spec.ts`
- `web/src/views/reports/exportReportImage.ts` + `.spec.ts`
- `web/src/views/reports/Index.spec.ts`
- `web/src/views/practice/PracticeHome.vue` + `.spec.ts`
- `web/src/layouts/nav.spec.ts`（若不存在）

修改：

- `web/src/router/index.ts`
- `web/src/layouts/nav.ts`
- `docs/PROGRESS.md`
- `docs/API.md` 如发现契约字段表达不一致才改；本卡预期不改后端契约