# S6-5 前端任务进度页（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S6-5。产出 `views/agent/TaskList.vue`、`TaskDetail.vue`。
> 前置：S6-2 三个 Agent 接口、S6-3 学习导图页。S6-4 不做（用户决定）。
> 范围：任务列表（分页/筛选/自动刷新）、任务详情（步骤时间线/折叠输出/失败高亮/确认弹窗）、后端 `GET /agent/tasks` 分页列表。
> 状态：**待用户确认**（2026-11-17）。确认后按本 spec 写 `docs/plan/s6-5-task-pages.md`，plan 确认后才写码。

## 1. 目标与非目标

### 1.1 目标

1. 后端新增 `GET /api/v1/agent/tasks`：本人任务分页列表，支持 `status` / `task_type` 筛选，按 `created_at DESC, id DESC`；复用 `page_params / sort_params / paginate_query / apply_sort` 与 `PageData`。
2. `TaskList.vue`：任务表格/卡片（类型、状态、步骤数、token、时间），筛选、分页、刷新；有 `pending/running` 任务时 2 秒自动刷新；点击进入详情；「生成学习导图」入口。
3. `TaskDetail.vue`：任务状态头、步骤时间线、每步 thought / 工具 / 入参出参（可折叠）、耗时；新步骤按序出现并有过渡动画；失败步骤红色高亮并展开错误输出；失败任务给建议（重新创建/返回列表）。
4. `waiting_confirm` 时弹出确认框：通过/拒绝 + 备注，调用 `POST /agent/tasks/{id}/confirm` 后继续轮询；409 等错误按统一壳提示。
5. `weekly_mindmap` 成功时显示摘要/引用/降级提示，并给「查看学习导图」链接到 `/agent/mindmap/{id}`。
6. 导航用「Agent 任务」替换 S6-3 的「学习导图」入口（导航保持 14 项）；学习导图路由保留，从列表/详情进入。
7. 测试覆盖列表接口、前端列表/详情/确认/轮询；真实库 + 真实 Chrome 验收（含步骤逐条出现、失败态、确认恢复）。

### 1.2 非目标

- 不做 SSE（任务卡允许轮询/SSE；本轮用 1–2 秒轮询，不新增后端流式接口）。
- 不做任务取消/删除/重跑接口（S6-6 或后续卡；失败页只给「重新创建」引导）。
- 不做 `mistake_paper`（S6-4 不做）。
- 不做移动端适配（沿用项目桌面优先）。
- 不改状态机/工具/结果结构；本轮只加列表读接口。
- 不做消息通知/红点/WebSocket。

## 2. 已确认决策（2026-11-17）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 列表数据来源 | 新增 `GET /agent/tasks` 分页列表；不靠 localStorage 拼历史 |
| D2 | 导航 | 「Agent 任务」替换「学习导图」入口；`/agent/mindmap` 路由保留 |
| D3 | 步骤更新方式 | 轮询（列表 2 s、详情 1 s）；不引 SSE/WebSocket |
| D4 | 确认弹窗 | 通过/拒绝 + 备注（≤500 字）；`edits` 不暴露（S6-4 不做） |
| D5 | 失败建议 | 展示失败步骤的错误输出 + 「重新创建任务」/「返回列表」；不提供原地重试按钮 |
| D6 | 分页 | `page` 1–N、`page_size` 1–100（默认 10），排序固定 `created_at DESC, id DESC`，接口仍接受 `sort_by/order` 白名单 |

## 3. 后端：列表接口

### 3.1 契约（API.md §10 新增）

`GET /api/v1/agent/tasks?page=1&page_size=10&status=running&task_type=weekly_mindmap`

- 权限：student（其他角色 403/40300）
- 入参：`page` ≥1（默认 1）、`page_size` 1–100（默认 10）；`status` ∈ `pending/running/waiting_confirm/succeeded/failed`（可选）；`task_type` 可选（1–50 字）；`sort_by` ∈ `created_at/id`（默认 `created_at`）、`order` ∈ `asc/desc`（默认 `desc`）
- 出参：`Envelope[PageData[AgentTaskOut]]`：
  - `items[]`：`id/task_type/status/steps_count/token_cost/error/created_at/started_at/finished_at`
  - `total/page/page_size`
- 口径：只查本人；固定 `created_at DESC, id DESC` 兜底（避免同秒翻页重复）；筛选条件全部在 SQL；非法 status/sort 422/42200。
- 错误：401/40100、403/40300、422/42200。

### 3.2 实现

- `services/agent_service.py` 新增：
  ```python
  SORTABLE = {"created_at": AgentTask.created_at, "id": AgentTask.id}

  def list_agent_tasks(session, *, user_id, status=None, task_type=None,
                       page: PageParams, sort: SortParams) -> PageData[AgentTaskOut]
  ```
  `build` 查询固定 `AgentTask.user_id == user_id`，可选 `status/task_type`，`apply_sort` 白名单，`order_by(AgentTask.id.desc())`，`paginate_query(item_model=AgentTaskOut)`。
- `api/v1/agent.py` 新增 `@router.get("/tasks")`，参数用 `page_params/sort_params` 依赖；`status` 用 `Literal` 校验；`task_type` 用 `Query(None, min_length=1, max_length=50)`；返回 `Envelope`。
- 路由顺序：`GET /tasks` 放在 `GET /tasks/{task_id}` 前（语义清晰）。
- 不改表/迁移；不改既有三接口。

## 4. 前端：任务列表

路由 `/agent/tasks`（student，导航「Agent 任务」）：

- 顶部：标题、说明、「刷新」、「生成学习导图」（跳 `/agent/mindmap`）。
- 筛选行：状态下拉（全部/排队中/生成中/等待确认/已完成/失败）、类型下拉（全部/demo/weekly_mindmap）、每页 10。
- 主体 `el-table`：
  - 列：ID、类型（中文标签）、状态（`el-tag` 颜色：pending 灰/running 蓝/waiting 黄/succeeded 绿/failed 红）、步骤数、token、创建时间、结束时间、操作（查看）。
  - 行点击进入详情；ID 用等宽字体。
  - 空态：`el-empty` + 「生成学习导图」按钮。
- 分页：`el-pagination`（total/page/page_size），切换重新拉取。
- 轮询：列表中存在 `pending/running` 时每 2 秒重拉当前页；没有则停；页面卸载清定时器；刷新按钮手动重拉。
- 错误：`el-alert` 显示统一壳 message；不重复弹窗（http.ts 已统一弹错）。
- 状态文案映射抽 `statusLabel/statusType` 纯函数（可单测）。

## 5. 前端：任务详情

路由 `/agent/tasks/:id(\\d+)`（student）：

- 头部：返回列表、「任务 #id」、类型、状态 tag、步骤数/token、开始/结束时间。
- 轮询：`pending/running` 每 1 秒 GET；终态或 `waiting_confirm` 停止；卸载清理。
- 步骤时间线：
  - 垂直时间线（自绘 ul/li，不引额外组件），每个 step：
    - 左侧序号/状态点（ok 绿、error 红、waiting_confirm 黄）；
    - thought 文本；
    - `tool_name` tag、`latency_ms`；
    - 入参/出参折叠区（`el-collapse` 或 details）：JSON `JSON.stringify(..., null, 2)`；默认折叠；**error 步默认展开**并红框高亮。
  - 新步骤用 `transition-group`（淡入+上移）；`running` 时自动滚到最新步骤（`scrollIntoView({block:'nearest'})`），不打断用户上翻：仅当用户接近底部时自动滚。
  - 空步骤：显示「任务尚未开始」。
- 结果区：
  - `weekly_mindmap` 成功：摘要 `summary_md`、引用数量、`degraded` 警告、「查看学习导图」链接 `/agent/mindmap/{id}`；
  - 其它类型：结果 JSON 折叠展示（最多 4000 字，超出提示）。
- `failed`：红色 alert 显示 `error`；提示「查看红色错误步骤的工具输出；修复后可重新创建任务」；「返回列表」「重新创建学习导图」。
- `waiting_confirm`：
  - 黄色 alert「等待人工确认」+「通过」「拒绝」按钮；
  - 弹窗（`el-dialog`）：显示当前任务摘要，备注输入（≤500 字），通过/拒绝提交；
  - 成功 → 关闭弹窗、恢复轮询（状态回 pending）；409/其他错误由统一壳提示并刷新任务。
- 不展示 `state_json`（内部状态），只展示 `input/result/steps`。

## 6. 类型与 API 封装

- `types/agent.ts`：
  - `AgentTaskPage { items: AgentTaskSummary[]; total; page; page_size }`
  - `AgentTaskDetail.result` 从 `WeeklyMindmapResult | null` 放宽为 `AgentTaskResult = WeeklyMindmapResult | DemoAgentResult | Record<string, unknown> | null`；提供 `asWeeklyMindmapResult(result)` 类型守卫。
  - `statusLabel/statusType` 纯函数（列表/详情共用）。
- `api/agent.ts`：新增
  - `listAgentTasks(params: {page?,page_size?,status?,task_type?,sort_by?,order?}): Promise<AgentTaskPage>`
  - `confirmAgentTask(id, decision: {approved;comment?;edits?}): Promise<AgentTaskSummary>`
- `WeeklyMindmap.vue` 改用 `asWeeklyMindmapResult(task.result)`，行为不变；在新任务页头部加「返回任务列表」小链接。

## 7. 测试

### 7.1 后端

| 文件 | 覆盖 |
|---|---|
| `test_agent_list_api.py` | 200/PageData 形状；status/task_type 筛选透传；分页参数；非法 status 422；teacher 403 |
| `test_agent_service.py`（补） | `list_agent_tasks` 固定 user_id、筛选、排序默认 created_at desc + id desc、空页 |

- service 用 fake session + 捕获 statement/分页调用（或编译 SQL 断言含 `user_id/status/task_type`）；API 用 TestClient + 依赖覆盖。

### 7.2 前端

| 文件 | 覆盖 |
|---|---|
| `api/agent.spec.ts`（补） | list 参数/路径；confirm POST body |
| `TaskList.spec.ts` | 渲染行/标签；筛选触发请求；分页；有空/running 时轮询（fake timers），无运行任务停止；空态；点击跳详情 |
| `TaskDetail.spec.ts` | 步骤渲染/折叠；error 步高亮并展开；failed 建议；waiting_confirm 弹窗 → confirm 调用 → 恢复轮询；weekly 成功显示摘要/引用/导图链接；轮询在终态停止 |
| `status.spec.ts`（或并入） | `statusLabel/statusType` 映射 |
| `WeeklyMindmap.spec.ts`（回归） | 类型守卫改动后行为不变 |

- mock `@/api/agent`/`vue-router`；`useFakeTimers` 测轮询；不真渲染 Element Plus 复杂组件可用 `ElementPlus` 插件 + 选择器断言。

## 8. 验收

1. 后端 `pytest -q` 全绿（S6-3 基线 1564）。
2. 前端 `npm run test:run`、`npm run build` 全绿；记录测试数/chunk。
3. 真实库 + HTTP：
   - `GET /agent/tasks?page=1&page_size=10` → 本人任务（S6-2/S6-3 留下的 demo/weekly 任务），total/items 正确；
   - `status=failed` → 只返回失败任务（任务 3/6）；`task_type=weekly_mindmap` → 只返回 weekly；`page_size=2` 翻页不重复；
   - teacher 403、非法 status 422。
4. 真实 Chrome 1440×900：
   - `/agent/tasks` 显示任务列表、状态颜色、分页；运行中任务自动刷新（可新建 demo 任务观察行从 pending→succeeded）；
   - 打开 weekly 任务 5：步骤时间线完整（10 步）、折叠输出可展开、摘要/引用/「查看学习导图」可见；
   - 打开失败任务 3：error 步红色高亮并展开错误输出，显示建议；
   - 新建 demo `require_confirm=true` 任务 → 详情弹确认框 → 通过 → 轮询到 succeeded；拒绝分支再跑一次 → failed；
   - 步骤「逐条出现」：新建 demo 任务后在详情页观察步骤数从 0 递增（截图/说明），无 console error、无横向溢出。
5. 证据 `.sdd/s6-5/acceptance-evidence.md` + 截图。

## 9. 风险与已知边界

- 列表轮询会重复请求；任务终态后立即停，页面上限 100，可接受。
- 详情轮询 1 s 对长任务有 DB 压力；单用户演示可接受，S7-2 压测再评估。
- 无任务取消/重跑：失败只能重新创建；与 S6-6 的可靠性加固衔接。
- 详情结果 JSON 截断 4000 字；完整结果可后续加下载。
- `state_json` 不展示，排障需查库；避免泄露内部状态。
- 导航用「Agent 任务」替换「学习导图」；用户已确认，学习导图路由仍可直达。
- 确认弹窗只支持通过/拒绝 + 备注；`edits` 不在 UI 暴露（S6-4 不做）。

## 10. 契约影响

- `API.md §10`：新增 `GET /agent/tasks`；`AgentTaskDetail.result` 类型说明补 demo/weekly 两种。
- `SCHEMA.md`：无变更。
- 依赖：无新增后端/前端依赖。
- PROGRESS：S6-5 完成，下一步 S6-6；导航 14 项文案更新。