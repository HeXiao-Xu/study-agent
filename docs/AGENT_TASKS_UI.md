# Agent 任务中心（S6-5）

> 页面：`web/src/views/agent/TaskList.vue`、`TaskDetail.vue`；接口：`GET /api/v1/agent/tasks`（分页）、`GET /agent/tasks/{id}`、`POST /agent/tasks/{id}/confirm`。
> 决策：D-068。前置：S6-2 状态机、S6-3 学习导图；S6-4 不做。

## 1. 任务列表

- 路由 `/agent/tasks`，导航「Agent 任务」（替换原「学习导图」入口，导航仍 14 项；`/agent/mindmap` 路由保留，从列表/详情进入）。
- 筛选：状态（排队中/生成中/等待确认/已完成/失败）、类型（学习导图/演示任务）；分页 10/20/50。
- 表格列：ID、类型、状态 tag、步骤数、token、创建时间、结束时间、查看。
- 轮询：当前页存在 `pending/running` 时每 2 秒重拉；全部终态后停止；卸载清定时器。
- 空态给「生成学习导图」入口；错误用统一 `ElMessage` + 页内 alert。

## 2. 任务详情

- 路由 `/agent/tasks/:id`；`pending/running` 每 1 秒轮询，终态/`waiting_confirm` 停止。
- 步骤时间线：
  - 每条显示 `step_no`、步骤状态 tag、工具名、耗时、thought；
  - 入参/出参用原生 `<details>` 折叠；**error 步默认展开**并红框高亮；
  - `transition-group` 淡入上移；运行中且用户接近底部时自动滚到最新步骤。
- 结果：
  - `weekly_mindmap` 成功 → 摘要、引用标签、降级提示、「查看学习导图」链接；
  - 其它结果 JSON 折叠展示（截断 4000 字）。
- 失败：红色 alert + `error` + 建议「展开红色错误步骤查看工具输出；修复后重新创建任务」+ 重新创建/返回列表。
- `waiting_confirm`：通过/拒绝按钮 → 弹窗备注（≤500 字）→ `POST confirm`（202）→ 状态回 pending 并恢复轮询；409 等由统一错误壳提示。
- 不展示 `state_json`（内部状态）。

## 3. 后端列表接口

`GET /api/v1/agent/tasks?page=1&page_size=10&status=running&task_type=weekly_mindmap`

- 仅 student 本人；`PageData[AgentTaskOut]`；排序固定 `created_at DESC, id DESC`（`sort_by` 白名单 `created_at/id`）。
- 筛选条件全部下推 SQL；非法 status/排序 422/42200；teacher 403。

## 4. 状态映射

| status | 文案 | tag |
|---|---|---|
| pending | 排队中 | info |
| running | 生成中 | primary |
| waiting_confirm | 等待确认 | warning |
| succeeded | 已完成 | success |
| failed | 失败 | danger |

## 5. 验证（详见 `.sdd/s6-5/acceptance-evidence.md`）

- 后端 1569 passed；前端 383 passed / 65 files，build 0。
- 真实列表：user 18 共 9 个任务；`status=failed` 过滤、`task_type` 过滤、`page_size=2` 翻页不重复；teacher 403、非法 status 422。
- Chrome 1440×900：列表 9 行；任务 5 详情 10 步 + 导图链接；任务 11 失败 11 步/8 个 error 行且错误输出默认展开；任务 8 确认通过后轮询到 succeeded；慢任务 12 步骤数按 `1→3→6` 递增；无横向溢出、console error 0。

## 6. 已知边界

- 轮询非 SSE；任务终态后立即停，长任务每 1 秒一次 DB 查询（单用户可接受，S7-2 再评估）。
- 无取消/原地重跑；失败只能重新创建（S6-6）。
- 结果 JSON 截断 4000 字；`state_json` 不展示。
- 导航用「Agent 任务」替换「学习导图」入口；学习导图仍可直达。
- 确认弹窗只通过/拒绝 + 备注；`edits` 不暴露（S6-4 不做）。