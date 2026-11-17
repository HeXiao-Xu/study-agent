# S6-6 Agent 可靠性加固（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S6-6。产出：重试/预算/限步/参数校验完整实现 + 文档。
> 验收：构造 5 种失败场景（工具报错、超时、超预算、参数非法、LLM 返回非 JSON），全部优雅处理且有日志。
> 前置：S6-2 状态机、S6-5 任务中心。S6-4 不做。
> 状态：**待用户确认**（2026-11-17）。确认后按本 spec 写 `docs/plan/s6-6-reliability.md`，plan 确认后才写码。

## 1. 目标与非目标

### 1.1 目标

1. **失败任务可重跑且幂等**：新增 `POST /agent/tasks/{id}/retry`（202），仅 `failed` 可重跑；清空该任务旧 `agent_steps`、重置 state/result/计数后重新入队；并发/重复重跑第二次 409。
2. **超时**：新增 `AGENT_TASK_TIMEOUT_SECONDS`（默认 600）与 `AgentTaskTimeoutError`；每个节点执行前检查 deadline，超时任务 `failed` 且保留已有产物；工具抛 `TimeoutError` 按普通可重试失败处理并记日志。
3. **预算/限步**：token 预算与最大步数终止时保留已有 artifacts/citations；`AgentStepLimitError` 与超时走同一「保留部分结果」路径；新增结构化 WARNING 日志。
4. **参数校验不执行**：`invoke_tool` 的 Pydantic 校验失败时 handler 一定不被调用（补测试）；demo/weekly 创建期校验仍 422。
5. **写操作门禁**：`ToolContext` 增 `allow_write`（默认 False）；`invoke_tool` 对 `ToolSpec.write=True` 且未授权直接 403/40300，handler 不执行；当前 11 个工具全只读，行为不变。
6. **日志**：工具失败/重试/重试耗尽、预算耗尽、超时、限步、重跑请求都有 WARNING/INFO 日志（含 task_id/tool/step_no），堆栈只进日志。
7. **前端**：失败任务详情提供「重跑任务」按钮（调用 retry → 轮询），409 由统一错误壳提示。
8. **文档**：`docs/AGENT_RELIABILITY.md` 汇总失败语义、5 类场景与验证方法；DECISIONS D-069；里程碑 tag `m5-agent-done`。
9. 测试覆盖 5 类失败 + 重跑幂等 + 写门禁 + 日志；真实环境跑通工具报错/超时/超预算/重跑，LLM 非 JSON 用单测（无法安全地让真实 LLM 必错）。

### 1.2 非目标

- 不引入每工具线程级硬超时（避免 SQLAlchemy Session 跨线程）；工具自身 HTTP 超时仍由适配器配置。
- 不做任务取消/暂停/删除接口。
- 不做重跑历史保留（重跑清空旧步骤，见 D-069；要历史需另加 attempt 维度/归档表）。
- 不做写工具本身（当前 11 个工具全只读）；只落门禁与测试。
- 不做 SSE/通知；前端仍轮询。
- 不改 5 种失败场景之外的工具业务语义。

## 2. 已确认决策（2026-11-17）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 重跑语义 | 仅 failed 可重跑；清空旧 `agent_steps` 与 state/result，从头重跑；重复/并发重跑 409 |
| D2 | 超时粒度 | 任务级 deadline（`AGENT_TASK_TIMEOUT_SECONDS` 默认 600）+ 工具 `TimeoutError` 归类为可重试失败；不引入子线程执行 |
| D3 | 写门禁 | `ToolContext.allow_write=False` 默认；`invoke_tool` 对 write 工具未授权 403；当前工具全只读 |
| D4 | 预算/限步 | 终止时保留已有 artifacts/citations；超时同样保留 |
| D5 | 5 类失败验证 | 工具报错/超时/超预算/重跑用真实 HTTP；参数非法用真实 422 + handler 不执行单测；LLM 非 JSON 用 fake LLM 单测（生成题重试耗尽、聚类降级） |
| D6 | 里程碑 | 验收后创建本地 tag `m5-agent-done`（不 push） |

## 3. 后端设计

### 3.1 超时与限步

- `Settings` 新增 `agent_task_timeout_seconds: int = Field(default=600, ge=10, le=3600)`；`.env.example` 同步。
- `state.py` 的 `new_state()` 新增 `timeout_seconds: float | None = None`，写入 `deadline_at: float | None = time.time() + timeout_seconds`；持久化在 `state_json`，恢复时沿用。
- `engine.py` 新增 `AgentTaskTimeoutError`；`_guard` 每个节点前：
  1) `deadline_at` 存在且 `time.time() > deadline_at` → `logger.warning("agent_task_timeout ...")` + raise；
  2) `step_count >= max_steps` → `logger.warning("agent_step_limit ...")` + raise。
- `act` 对 `TimeoutError` 单独分支：`last_error="工具执行超时"`、`tool_output={"error":..., "code":50000}`、WARNING 日志，进入正常重试。
- 工具自身异常仍按 AppError/其他异常分类；AppError 失败也补 WARNING（tool/step/code/message）。
- service 捕获 `AgentTaskTimeoutError` / `AgentStepLimitError`：`failed` + 固定 error；从 `DbStepRecorder.last_state` 取已有 artifacts/citations 写 `result_json`，保证「返回已有产物」。
- `DemoInput` 增 `task_timeout_seconds: int | None`（1–3600，仅供 demo 验收覆盖 deadline）；service 建 state 时优先用它，否则 settings。

### 3.2 预算

- 现有 `plan/observe` 检查保留；`_budget_hit` 增 WARNING 日志（task_id、cost、budget）。
- `WeeklyInput` 增 `token_budget: int | None`（≥100），让真实超预算场景可用：weekly 聚类 token 累加后触发 `finalize`，任务 failed 但 `result` 保留 artifacts/citations。
- 预算终止语义不变：`result = {artifacts,citations}`；`error="token 预算不足，已终止并保留现有产物"`。

### 3.3 重跑（retry）

`POST /api/v1/agent/tasks/{id}/retry`：

- 权限：student 仅本人（404/403）。
- 类型：**202** 异步。
- 前置：`status == failed`，否则 409/40900「只有失败任务可以重跑」。
- 行为（service `retry_agent_task`）：
  1) `session.get(AgentTask, id, with_for_update=True)` 串行化并发重跑；
  2) 删除该任务全部 `agent_steps`（`DELETE WHERE task_id`）；
  3) 重置 `state_json/result_json/error/steps_count/token_cost/started_at/finished_at`，`status=pending`；
  4) commit 后 `task_service.create_task(name="agent.run", payload={"agent_task_id": id})`；
  5) 入队失败：任务置 `failed`、`error="任务入队失败"`、commit，抛 `TaskQueueUnavailableError`。
- 出参：`Envelope[AgentTaskOut]`（status=pending）。
- 幂等：第一次重跑把状态改 pending 并提交；第二次读到非 failed → 409；行锁保证并发只成功一个。
- 旧步骤被清空：重跑从头写 1..N，无唯一键冲突；旧尝试日志不保留（D-069 记录）。

### 3.4 参数校验与写门禁

- `invoke_tool`：Pydantic 校验失败 → `ToolInputError`，handler 不执行；新增 WARNING 日志（tool、错误类型）。
- `ToolContext` 增 `allow_write: bool = False`；`invoke_tool` 在取到 spec 后：
  ```python
  if spec.write and not ctx.allow_write:
      logger.warning("agent_tool_write_blocked tool=%s", name)
      raise ForbiddenError("写操作需要人工确认")
  ```
- 11 个工具 `write=False` 断言保留；新增测试用临时 `ToolSpec(write=True)` 验证 403 且 handler 未调用、`allow_write=True` 时可执行。
- 说明：S6-2 的 confirm 节点是任务级确认；未来写工具必须由任务定义确认后显式传 `allow_write=True`，本轮无写工具。

### 3.5 日志清单

| 事件 | 级别 | 字段 |
|---|---|---|
| `agent_tool_failed` | WARNING | task_id/step_no/tool/code/message |
| `agent_tool_timeout` | WARNING | task_id/step_no/tool |
| `agent_tool_retry` | WARNING | task_id/step_no/tool/retry |
| `agent_tool_retry_exhausted` | WARNING | task_id/step_no/tool/error |
| `agent_budget_exhausted` | WARNING | task_id/cost/budget |
| `agent_task_timeout` | WARNING | task_id/deadline |
| `agent_step_limit` | WARNING | task_id/step_count/max_steps |
| `agent_task_retry` | INFO | task_id/previous_error |
| `agent_tool_write_blocked` | WARNING | tool |

- 不记录工具出参正文、Prompt、Key；堆栈只 `logger.exception`。

## 4. 前端

- `api/agent.ts` 新增 `retryAgentTask(id): Promise<AgentTaskSummary>`（POST `/agent/tasks/{id}/retry`）。
- `TaskDetail.vue` 失败卡片新增「重跑任务」按钮（`data-testid="retry"`，loading 态）；点击 → `retryAgentTask` → 成功后 `load()` 恢复轮询；失败由统一错误壳提示并写页内 error。
- 任务列表失败行不加重跑按钮（避免误触），详情页承载。
- 重跑后步骤从 1 重新出现，时间线清空重建（轮询自然刷新）。

## 5. 测试

| 文件 | 覆盖 |
|---|---|
| `test_agent_reliability.py` | 任务超时（deadline 过期）；工具 TimeoutError 重试；预算耗尽保留 result；限步保留 result；日志（caplog） |
| `test_agent_tools_registry.py`（补） | 参数非法 handler 不执行；write=True 未授权 403 且 handler 不执行；allow_write=True 放行 |
| `test_agent_service.py`（补） | retry 仅 failed；重置字段/清空步骤；重复/并发 409；入队失败置 failed |
| `test_agent_retry_api.py` | 202/403/404/409；Envelope |
| `api/agent.spec.ts`（补） | retry 路径/方法 |
| `TaskDetail.spec.ts`（补） | failed 页「重跑任务」调用 retry 并恢复轮询；409 错误提示 |
| `test_agent_task_weekly_mindmap.py`（补） | token_budget 输入校验 |
| `test_agent_task_spec_demo.py`（补） | task_timeout_seconds 输入校验 |

## 6. 验收（真实 + 单测）

1. 后端 `pytest -q` 全绿；前端 `npm run test:run`/`build` 全绿。
2. 5 类失败：
   - **工具报错**：真实 demo `get_kp_subgraph(kp_id=999999)` → 3 次尝试、failed、「重试上限」错误、步骤含红色 error 行（S6-5 已实测，本轮复跑留证）。
   - **超时**：真实 demo `{task_timeout_seconds:1, steps:[generate_questions]}` → failed「任务执行超时」，已有步骤/产物保留；worker 日志含 `agent_task_timeout`。
   - **超预算**：真实 `weekly_mindmap {days:30, token_budget:100}` → failed「token 预算不足…」，`result.artifacts/citations` 非空；日志含 `agent_budget_exhausted`。
   - **参数非法**：HTTP 创建非法 tool input → 422（handler 未执行）；`scripts/agent_tools.py call calculator '{"expression":""}'` → 422；单测断言 handler 不执行。
   - **LLM 非 JSON**：单测覆盖 `generate_questions` 3 次非法 JSON → `ToolExecutionError`；`weekly_mindmap` 聚类非法 JSON → 降级 `degraded=true`（真实 LLM 无法安全强制失败，证据引用单测）。
3. 重跑：真实失败任务 `POST retry` → 202 → 轮询再次 failed；重跑后步骤从 1 开始（无唯一键冲突）；重复 retry 在 pending/running 时 409；Chrome 详情页点「重跑任务」可复现。
4. 日志：worker 输出中能检索到上述事件（至少 `agent_tool_retry`/`agent_task_timeout`/`agent_budget_exhausted`/`agent_task_retry`）。
5. 截图/证据 `.sdd/s6-6/acceptance-evidence.md`；创建本地 tag `m5-agent-done`。
6. 文档：`AGENT_RELIABILITY.md`、D-069、PROGRESS、AGENTS §9.6。

## 7. 风险与已知边界

- 任务级超时不打断正在执行的工具；若单个工具卡住，要等它返回后下一个节点才判超时（工具层 HTTP 超时仍由适配器兜底）。子线程硬超时会引入 Session 跨线程风险，故不做。
- 重跑清空旧步骤 = 丢历史审计；需要保留时另加 attempt/归档表。
- 重跑后 LLM 结果可能不同（非确定性）；幂等指不重复写数据/不重复步骤，不保证输出逐字节一致。
- token 预算仍只统计显式 `add_tokens`；`generate_questions` 等工具的 LLM 用量未回报（S6-1 遗留），预算对这类工具是近似。
- 写门禁只覆盖工具层；任务级写操作确认仍由 confirm 节点承担，未来写工具需同时满足两者。
- 参数非法在创建期即 422，不会进 agent_steps；运行期只可能出现在外部传入工具参数被篡改（当前无入口）。

## 8. 契约影响

- `API.md §10`：新增 `POST /agent/tasks/{id}/retry`；说明重跑清空步骤。
- `SCHEMA.md`：无变更（不新增 attempt 表/列）。
- 配置：`.env.example` + `AGENT_TASK_TIMEOUT_SECONDS=600`。
- 依赖：无新增。
- `AGENT_TOOLS.md`/`AGENT_ENGINE.md` 补超时/预算/写门禁说明。