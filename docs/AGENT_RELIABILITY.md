# Agent 可靠性（S6-6）

> 代码：`ai/agents/engine.py`（deadline/日志/部分结果）、`ai/agents/tools/base.py`（参数校验/写门禁）、`services/agent_service.py`（重跑/超时落库）、`api/v1/agent.py`（retry）。
> 决策：D-069。状态机与工具见 [AGENT_ENGINE.md](AGENT_ENGINE.md)、[AGENT_TOOLS.md](AGENT_TOOLS.md)。

## 1. 失败分类与处理

| 场景 | 处理 | 任务终态 | 已有产物 |
|---|---|---|---|
| 工具 AppError（404/403/409/422/500 业务错） | 记 `agent_tool_failed`，进入重试（≤2 次） | 重试耗尽 → failed，error 含「重试上限」 | `result` 保留 artifacts/citations |
| 工具 `TimeoutError` | 记 `agent_tool_timeout`，同普通失败重试 | 同上 | 同上 |
| 未预期异常 | `logger.exception`，同失败重试 | 同上 | 同上 |
| 任务墙钟超时 | 每节点前检查 `deadline_at`，记 `agent_task_timeout` | failed「任务执行超时」 | 从最后已提交 state 取 artifacts/citations |
| token 预算耗尽 | plan/observe 后检查，记 `agent_budget_exhausted` | failed「token 预算不足…」 | 保留 artifacts/citations |
| 步数超限（12） | `_guard` 记 `agent_step_limit` | failed「超过最大步数 12」 | 保留已提交部分 |
| LLM 返回非 JSON | 生成题重试 2 次后 `ToolExecutionError`；周导图聚类重试后降级 `degraded=true` | 生成题失败 / 导图成功降级 | 周导图仍出结构树 |
| 工具参数非法 | `invoke_tool` 校验失败 → 422，handler 不执行；create 期 422 | 不创建任务/不执行 | — |
| 写工具未确认 | `allow_write=False` → 403，handler 不执行 | — | — |

## 2. 超时

- `AGENT_TASK_TIMEOUT_SECONDS` 默认 600；`.env.example` 同步。
- `new_state(timeout_seconds=...)` 写 `deadline_at = time.time()+timeout`，随 `state_json` 持久化；恢复沿用。
- 每个节点执行前检查 deadline；超时抛 `AgentTaskTimeoutError`，service 置 failed 并保留最后已提交产物。
- demo 支持 `task_timeout_seconds` 覆盖（1–3600，仅验收用）。
- **不打断正在执行的工具**：长工具要等返回后下一个节点才判超时；工具自身 HTTP 超时由 LLM/Embedding 适配器配置兜底。

## 3. 预算与限步

- `AGENT_TOKEN_BUDGET` 默认 20000；weekly 任务可用 `token_budget` 覆盖（≥100）。
- 只统计任务定义显式累加的 token（`PlanExtension.token_cost`）；`generate_questions` 等工具的 LLM 用量未回报，预算对这类工具是近似。
- 预算命中 → `fatal_error`，路由 finalize，结果保留已有 artifacts/citations。
- 最大步数 12 按 `agent_steps` 行数；命中抛 `AgentStepLimitError`，service 保留部分结果。

## 4. 失败重跑

`POST /api/v1/agent/tasks/{id}/retry`（202）：

- 仅本人、仅 `failed`；其他状态 409。
- `SELECT ... FOR UPDATE` 串行化；删除该任务全部 `agent_steps`，重置 state/result/error/steps_count/token_cost/started_at/finished_at，status=pending，重新入队。
- 重复/并发重跑只有第一次 202；入队失败置 failed +「任务入队失败」。
- **不保留上一次步骤日志**；重跑从 step_no=1 重新写，避免唯一键冲突。需要历史时另加 attempt/归档表。
- 重跑输出可能因 LLM 非确定性而不同；幂等指不重复写业务数据、不重复步骤，不保证逐字节一致。

## 5. 参数校验与写门禁

- `invoke_tool` 先按 `ToolSpec.input_model` 校验（`extra="forbid"`）；失败抛 `ToolInputError`（422/42200），handler 不执行，记 `agent_tool_input_invalid`。
- `ToolContext.allow_write` 默认 False；`ToolSpec.write=True` 且未授权 → `ForbiddenError`（403/40300），handler 不执行，记 `agent_tool_write_blocked`。
- 当前 11 个工具全 `write=False`；未来写工具必须由任务确认后显式放行，且仍受 confirm 节点保护。
- 创建期 demo/weekly 也做工具输入 schema 校验，错误消息统一中文（`format_validation_error`）。

## 6. 日志事件

| 事件 | 级别 | 位置 |
|---|---|---|
| `agent_tool_failed` | WARNING | engine.act（tool/step/code） |
| `agent_tool_timeout` | WARNING | engine.act |
| `agent_tool_retry` / `agent_tool_retry_exhausted` | WARNING | engine.reflect |
| `agent_budget_exhausted` | WARNING | engine._budget_hit |
| `agent_task_timeout` | WARNING | engine._guard |
| `agent_step_limit` | WARNING | engine._guard |
| `agent_task_timeout_failed` / `agent_task_step_limit` | WARNING | service |
| `agent_task_retry` | INFO | service retry |
| `agent_tool_input_invalid` / `agent_tool_write_blocked` | WARNING | tools.base |

不记录工具正文、Prompt、Key；堆栈只 `logger.exception`。

## 7. 5 类失败验收（详见 `.sdd/s6-6/acceptance-evidence.md`）

| 场景 | 实测 |
|---|---|
| 工具报错 | demo `kp_id=999999` → 3 次尝试、11 步、failed「重试上限」、error 步含 40400 |
| 超时 | demo `task_timeout_seconds=1` + `generate_questions` → failed「任务执行超时」、2 步、部分结果保留 |
| 超预算 | weekly 30d `token_budget=100` → LLM 2294 token 后 failed「token 预算不足…」、artifacts step_1/2 保留 |
| 参数非法 | HTTP 创建 `calculator expression=""` → 422/42200，handler 不执行（单测） |
| LLM 非 JSON | 单测：生成题 3 次非法 JSON → `ToolExecutionError`；周导图聚类非法 JSON → 降级 `degraded=true` |
| 重跑 | failed 任务 retry → 202；第二次 409；重跑后步骤 1..11、再次 failed，无唯一键冲突 |

## 8. 已知边界

- 任务超时不打断当前工具；子线程硬超时有 Session 跨线程风险，未做。
- 重跑清空旧步骤，丢上一次审计。
- token 预算只统计显式累加；工具内 LLM 用量未回报。
- 写门禁只覆盖工具层；任务级写确认仍由 confirm 节点承担。
- 参数非法在创建期即 422，不会产生 agent_steps；运行期无外部篡改入口。