# S6-2 LangGraph 状态机 + 步骤持久化（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S6-2。产出 `ai/agents/graph.py`、`agent_tasks`/`agent_steps` 表、`api/v1/agent.py`。
> 方案依据：`docs/个性化学习智能体-毕业设计完整方案.md` §6.7（State / 节点 / 条件路由 / 最大步数 12 / 步骤日志）。
> 前置：S6-1 的 11 个工具与 `invoke_tool` 已交付（D-065）。
> 状态：**已确认**（2026-11-17）。实现按 `docs/plan/s6-2-agent-engine.md` 执行。
> 范围：状态机引擎 + 步骤/状态持久化 + 三个 Agent API + demo 任务类型 + 挂起/恢复。**不写** weekly_mindmap / mistake_paper 的真实编排（S6-3/S6-4）。

## 1. 目标与非目标

### 1.1 目标

1. 用 **LangGraph `StateGraph`** 实现 `plan → act → observe → (reflect → act)* → confirm → finalize` 状态机；工具失败重试 ≤2、超 token 预算终止、需确认时挂起、最大步数 12。
2. 首次落地 `agent_tasks` / `agent_steps` 两张表（SCHEMA §8.1/§8.2）：任务状态、结果、步骤日志、耗时、token 成本、挂起快照。
3. 每个节点执行后写一条 `agent_steps`，并提供 `task_id + step_no` 唯一约束，支持按序回放。
4. 三个 student API：创建（202 入队）、查询（状态 + 步骤）、人工确认（202 恢复执行）。
5. 挂起/恢复可跨进程：`waiting_confirm` 时把图状态落库，确认后从 `confirm` 节点继续，不重跑已完成的工具。
6. 提供 `demo` 任务类型（3 步假任务）用于本卡验收；`weekly_mindmap`/`mistake_paper` 留给 S6-3/S6-4 注册。
7. 自动化测试覆盖图路由、重试、预算、步数上限、挂起/恢复、service、API、迁移；真实库 + 真实 ARQ 跑通 3 步任务与确认恢复。

### 1.2 非目标（留给后续卡）

- 不做任务 A（周笔记整理 + 思维导图）与任务 B（错题组卷）的规划 Prompt 与业务编排（S6-3/S6-4）。
- 不做前端任务进度页（S6-5）。
- 不做 5 种失败场景的完整加固、工具调用缓存、失败任务重跑幂等（S6-6）。
- 不做任务列表 / 取消 / 删除接口（S6-5 需要时再加）。
- 不做 SSE 流式步骤推送；GET 轮询足够（S6-5 若要 SSE 另开卡）。
- 不把 `edits`（换题/调难度）应用到图上；S6-2 只存进确认决策，S6-4 消费。
- 不引入第二个依赖：不装 `langgraph-checkpoint-postgres`，挂起快照用自有 `state_json`，不建 LangGraph 自己的 checkpoint 表。

## 2. 用户已确认的决策（2026-11-17）

| # | 决策 | 选择 |
|---|---|---|
| D1 | Agent 框架 | 安装 `langgraph==1.2.22`（2026-11-14 当前版，Python ≥3.10），写入 `backend/requirements.txt`；使用 `StateGraph`，不用 LangChain AgentExecutor |
| D2 | 任务类型范围 | S6-2 只注册 `demo`；公开 API 接受 `demo`，`weekly_mindmap`/`mistake_paper` 在 S6-3/S6-4 注册后开放 |
| D3 | 确认语义 | `POST /agent/tasks` 与 `POST /agent/tasks/{id}/confirm` 都是 **202 + 入 ARQ 队列**；GET 轮询状态与步骤。同步 confirm 的实现不采用 |
| D4 | 挂起快照 | `agent_tasks` 新增 `state_json`（JSONB，可空），每个节点与 `agent_steps` 同事务写入；恢复时从 `state_json` 读回 |
| D5 | 任务创建时间 | `agent_tasks` 新增 `created_at`（TIMESTAMPTZ，默认 now()），供排序/列表与 S6-5 使用 |
| D6 | 步骤状态 | `agent_steps.status` 取值 `ok / error / waiting_confirm`（S6-2 定稿），TEXT + CHECK |
| D7 | 最大步数口径 | 最大步数 12 指 **agent_steps 行数**（plan/act/observe/reflect/confirm/finalize 每次执行都算 1 行）；达到上限时任务失败并写清原因 |
| D8 | 重试口径 | 单个工具失败后最多再重试 **2 次**（共 3 次尝试）；`reflect` 节点递增 `retry_count`，用尽转 `finalize` 失败 |
| D9 | token 预算 | 默认 `AGENT_TOKEN_BUDGET=20000`；`token_cost` 由规划器/任务定义通过 `RunContext.add_tokens()` 累加，S6-1 工具暂不回报用量；达到/超过预算即终止并保留已有产物 |
| D10 | 工具失败语义 | 工具抛 `AppError` 或未知异常都作为「本步失败」进入重试；最终失败写 `agent_steps.status=error` 与任务 `error`，不向 ARQ 抛异常（避免 runner 重复执行） |

## 3. 架构与目录

```
backend/app/ai/agents/
├── state.py            # AgentState TypedDict、PlanStep、状态常量、JSON 化辅助
├── engine.py           # LangGraph 图组装、节点、条件路由、RunContext、StepRecorder 协议
├── tasks/
│   ├── __init__.py     # TASK_SPECS 注册表（demo）
│   └── demo.py         # DemoTaskSpec + DemoInput 校验
├── tools/              # S6-1 已交付
backend/app/models/
├── agent_task.py
└── agent_step.py
backend/app/services/agent_service.py        # 创建/查询/确认/执行编排
backend/app/tasks/agent_run.py               # @register("agent.run")
backend/app/schemas/agent.py
backend/app/api/v1/agent.py
backend/alembic/versions/0018_s6_2.py
backend/tests/test_agent_*.py
docs/AGENT_ENGINE.md
```

分层：

- `engine.py` 不 import service/API；通过 `RunContext` 注入 session、user、recorder、工具调用器，便于纯单测。
- `agent_service.py` 是 Agent 任务唯一业务入口：建任务、入队、状态机执行、确认。
- API 只做参数校验/权限/Envelope；业务错误由 service 抛 `AppError`。
- `tasks/agent_run.py` 是 ARQ handler；`TASK_RUN_AGENT = "agent.run"` 常量定义在 `agent_service.py`（task 反向导入，沿用 S3-1/S4-3 防循环导入）。
- `engine` 只依赖 S6-1 `invoke_tool` 的签名；demo 以外任务在 S6-3/S6-4 实现 `AgentTaskSpec`。

## 4. 数据模型与迁移（SCHEMA §8.1/§8.2）

### 4.1 `agent_tasks`（在 SCHEMA 原表上补两列）

| 字段 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | 主键 |
| user_id | BIGINT FK→users.id | 否 | — | 发起者 |
| task_type | TEXT | 否 | — | `demo`（S6-2）；`weekly_mindmap`/`mistake_paper`（S6-3/4） |
| input_json | JSONB | 否 | — | 校验后的任务输入 |
| status | TEXT | 否 | `pending` | `pending/running/waiting_confirm/succeeded/failed`，CHECK `ck_agent_tasks_status` |
| result_json | JSONB | 是 | — | 任务结果；waiting_confirm 时存中间产物 |
| **state_json** | JSONB | 是 | — | **S6-2 新增**：图状态快照，每节点写 |
| error | TEXT | 是 | — | 失败原因 |
| steps_count | INTEGER | 是 | — | 已写步骤数 |
| token_cost | INTEGER | 是 | — | 累计 token |
| started_at | TIMESTAMPTZ | 是 | — | 首次开始 |
| finished_at | TIMESTAMPTZ | 是 | — | 终态时间 |
| **created_at** | TIMESTAMPTZ | 否 | now() | **S6-2 新增**：创建时间 |

索引：`ix_agent_tasks_user_status(user_id, status)`。

### 4.2 `agent_steps`

| 字段 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | 主键 |
| task_id | BIGINT FK→agent_tasks.id ON DELETE CASCADE | 否 | — | 所属任务 |
| step_no | INTEGER | 否 | — | 从 1 连续递增 |
| thought | TEXT | 是 | — | 本节点思考/说明 |
| tool_name | TEXT | 是 | — | 仅 act 步有 |
| tool_input_json | JSONB | 是 | — | 仅 act 步有 |
| tool_output_json | JSONB | 是 | — | 仅 act 步有；失败时为 `{error, code}` |
| latency_ms | INTEGER | 是 | — | 仅 act 步计时 |
| status | TEXT | 否 | — | `ok/error/waiting_confirm`，CHECK `ck_agent_steps_status` |

约束：`uq_agent_steps_task_step(task_id, step_no)`。不加 `created_at`（回放靠 step_no；时间线要时间戳时 S6-5 再迁移）。

### 4.3 迁移 `0018_s6_2`

- `down_revision=0017_s5_6`；创建两张表、CHECK、唯一键、索引、外键；`agent_tasks.created_at` 用 `server_default=sa.text("now()")`。
- 不修改历史迁移；降级按 steps → tasks 顺序 drop。
- 迁移测试断言：列集合、CHECK 名、唯一键名、FK 目标、索引名、`alembic head == "0018_s6_2"`。

## 5. 状态定义与图

### 5.1 `AgentState`（TypedDict, total=False）

```python
user_id: int
task_input: dict
plan: list[dict]              # [{tool, input, purpose}]
current_index: int
artifacts: dict               # {"step_1": {"tool","input","output"}, ...}
citations: list[dict]         # [{note_id, note_title, chunk_id}]
need_human_confirm: bool
confirm_decision: dict | None # {approved, comment, edits}
retry_count: int
token_budget: int
token_cost: int
max_steps: int
step_count: int
last_error: str | None
fatal_error: str | None
status: str                   # running/waiting_confirm/succeeded/failed
resume_from: str | None       # confirm | resume
result: dict | None
```

### 5.2 节点与路由

```text
START → plan
plan   → confirm（resume_from="confirm"）/ act（resume_from="resume" 且有 plan）/ finalize（无步骤）/ act
act    → observe
observe→ reflect（last_error）/ finalize（fatal_error 或预算耗尽）/ confirm（全部完成且 requires_confirm）/
         finalize（全部完成且不需要确认）/ act
reflect→ finalize（retry_count≥2）/ act（重试同一步）
confirm→ finalize（已确认/拒绝）/ END（无决策，挂起）
finalize→ END
```

节点职责：

| 节点 | 做什么 | `agent_steps` 行 |
|---|---|---|
| `plan` | 调 `AgentTaskSpec.build_plan()`；检查预算；生成计划 | thought=计划摘要；status=ok |
| `act` | 取 `plan[current_index]`，调 `invoke_tool`，计时；成功/失败写状态 | tool_name/input/output/latency；status=ok 或 error |
| `observe` | 成功则收产物/引用、`current_index+1`、清 `retry_count`；失败保留 `last_error`；检查预算/完成 | thought=评估；status=ok/error |
| `reflect` | 失败重试计数；用尽写 `fatal_error` | thought=第几次重试/放弃；status=ok/error |
| `confirm` | 无决策 → `need_human_confirm=True`、`status=waiting_confirm`；有决策按 approved 继续或失败 | thought=等待/通过/拒绝；status=waiting_confirm/ok/error |
| `finalize` | 调 `AgentTaskSpec.finalize()`；成功写 result，失败写 error | thought=完成/失败；status=ok/error |

### 5.3 步数、预算、重试

- **步数**：每个节点执行前检查 `step_count >= max_steps`；命中抛 `AgentStepLimitError`，由 service 把任务置 `failed`、`error="超过最大步数 12"`，不再写步骤。
- **预算**：`plan` 与 `observe` 每次更新后检查 `token_cost >= token_budget`；命中写 `fatal_error="token 预算不足"` 并路由 `finalize`；已有 `artifacts` 保留在 `result`。
- **重试**：`act` 抛异常不算节点异常，写入 `last_error`；`observe` 记录失败；`reflect` 若 `retry_count >= 2` 则 `fatal_error`，否则 `retry_count += 1` 并回到同一步 `act`。
- **工具入参校验**：`invoke_tool` 已做 Pydantic 校验；校验失败按普通工具失败重试（错误信息进 `tool_output_json.error`）。
- **最大步数语义**：一次 3 步 demo 成功 = plan(1)+act/observe×3(6)+finalize(1)=8 行；需确认再 +confirm(1)=9 行；确认恢复再 +confirm(1)+finalize(1)=11 行。因此 demo 允许 1–5 步，需确认时建议 ≤4 步。

### 5.4 挂起与恢复

- `confirm` 无决策时：写 `agent_steps(status=waiting_confirm)`、`state_json`、任务 `status=waiting_confirm`、`result_json={artifacts,citations,awaiting_confirm:true}`；图结束。
- 确认接口：任务必须 `waiting_confirm`（否则 409）；把 `confirm_decision` 写入 `state_json`、`resume_from="confirm"`、`need_human_confirm=False`、任务回到 `pending`，再入队。
- 恢复执行：`plan` 节点检测 `resume_from` 直接跳过（不新增 plan 行），路由到 `confirm`；`confirm` 记录决策行后到 `finalize`。已完成的工具不重跑。
- 进程崩溃后重跑：若 `status=running` 且已有 `state_json`，置 `resume_from="resume"`，`plan` 跳过；若 `current_index < len(plan)` 回到当前步 `act`（act 成功但 observe 未提交的极端情况会重跑一次工具；S6-1 工具只读，可接受；写工具在 S6-4 由确认流程保护）。

## 6. `demo` 任务类型

- 注册名：`demo`；`requires_confirm` 由输入决定。
- 输入模型（Pydantic，`extra="forbid"`）：

```json
{
  "steps": [
    {"tool": "calculator", "input": {"expression": "2**10"}, "purpose": "计算 2 的 10 次方"},
    {"tool": "make_mindmap", "input": {"title": "函数", "nodes": [{"id": "1", "name": "函数"}]}}
  ],
  "require_confirm": false,
  "token_budget": 20000
}
```

- `steps` 1–5；`tool` 必须在 S6-1 注册表内（创建时校验，未知 422）；`input` 为对象；`purpose` ≤200 字。
- `build_plan` 原样转成 `PlanStep`；`finalize` 返回 `{summary: "完成 N 步", artifacts, citations}`。
- `requires_confirm=True` 时，所有步骤完成后挂起等确认。
- 真实任务 S6-3/S6-4 只需新增 `AgentTaskSpec` 并注册，不改引擎/API。

## 7. API 契约（替换 API.md §10 占位）

### 7.1 `POST /api/v1/agent/tasks`

- 权限：student（其他角色 403/40300）
- 类型：**202** 异步（写 `agent_tasks` + `async_tasks`，入 ARQ `agent.run`）
- 入参：`{task_type: "demo", input: {...}}`（input 结构随类型；S6-2 仅 demo）
- 出参：`Envelope[AgentTaskOut]`：`id/task_type/status/steps_count/token_cost/error/created_at/started_at/finished_at`
- 错误：422/42200（未知任务类型「任务类型尚未启用：x」、输入不合法、steps 越界、未知工具）；500/50000（任务队列不可用，且 agent 任务置 failed）
- 口径：创建成功即返回，不等待执行。

### 7.2 `GET /api/v1/agent/tasks/{id}`

- 权限：student（仅本人；他人 403/40300，不存在 404/40400）
- 类型：同步
- 出参：`Envelope[AgentTaskDetailOut]`：上面的字段 + `input` + `result` + `steps[]`
  - step：`step_no/thought/tool_name/tool_input/tool_output/latency_ms/status`
  - 按 `step_no ASC`；执行中也可查（步骤可能持续增加）
- 错误：404/40400、403/40300

### 7.3 `POST /api/v1/agent/tasks/{id}/confirm`

- 权限：student（仅本人）
- 类型：**202** 异步（写决策 + 重新入队）
- 入参：`{approved: bool, comment?: string|null(≤500), edits?: object|null}`
- 出参：`Envelope[AgentTaskOut]`（status 回到 `pending`）
- 错误：404/403/409「当前状态不需要确认」/500 队列不可用（状态恢复为 waiting_confirm）
- 拒绝语义：`approved=false` → 恢复后 `confirm` 节点写 `status=error`，`finalize` 把任务置 `failed`，`error="用户拒绝确认"`。

## 8. 配置与依赖

| 项 | 值 | 说明 |
|---|---|---|
| `langgraph` | `==1.2.22` | 新增直接依赖；传递依赖由 pip 解析（langchain-core 1.8.1、langgraph-checkpoint 4.3.2 等） |
| `AGENT_MAX_STEPS` | 12 | `Field(ge=1, le=50)`；超过即失败 |
| `AGENT_TOKEN_BUDGET` | 20000 | `Field(ge=100)`；单任务默认预算；demo 输入可覆盖（≥100） |

`docs/.env.example` 增加上述两项；`backend/requirements.txt` 增加 langgraph 固定版本；不新增其他直接依赖。

## 9. 测试

| 文件 | 覆盖 |
|---|---|
| `test_agent_models_migration.py` | 两表列/CHECK/唯一键/FK/索引；迁移 head `0018_s6_2` |
| `test_agent_graph.py` | 3 步成功（8 行、thought/tool/input/output/latency、artifacts）；失败重试 2 次后成功；重试耗尽失败；token 预算终止；最大步数抛错；挂起 waiting_confirm；确认通过/拒绝恢复；resume 不重跑 plan |
| `test_agent_service.py` | 创建 demo（未知类型 422、非法输入 422、未知工具 422、入队失败置 failed）；查询（404/403）；确认（非 waiting_confirm 409、写入决策并回 pending、入队失败恢复 waiting）；执行终态幂等 |
| `test_agent_api.py` | 202 创建/确认、GET 详情与步骤顺序、权限 403/404、409、422、Envelope；不连库不连 Redis（依赖覆盖 + fake queue） |
| `test_agent_task.py` | `agent.run` handler 透传 `run_agent_task` 返回值；不 commit async_tasks |
| `test_agent_task_spec_demo.py` | DemoInput 校验、build_plan/finalize、requires_confirm、步骤上限 |

- 图测试用 fake `StepRecorder` + fake `tool_invoker`，不连库、不调 LLM；
- service/API 测试用 fake session/queue，monkeypatch `task_service.create_task`；
- 现有测试不得回归；`pytest -q` 全绿。

## 10. 验收（真实库 + 真实 ARQ）

1. `alembic upgrade head` → `0018_s6_2`，两表存在。
2. 启动 Redis、ARQ Worker、uvicorn（本地端口）。
3. 真实 HTTP：
   - POST demo（3 步：`calculator` + `make_mindmap` + `list_mistakes`，无需确认）→ 202；轮询 GET 到 `succeeded`；`steps` 8 条，plan/act/observe/finalize 齐全，act 行有 tool/input/output/latency；`result` 带 3 个 artifacts。
   - POST demo（2 步，`require_confirm=true`）→ 轮询到 `waiting_confirm`；GET 能看到中间产物；POST confirm `{approved:true}` → 202 → 轮询 `succeeded`；步骤包含 confirm 与 finalize，且没有重复执行前 2 步。
   - POST confirm `{approved:false}` → 最终 `failed` + `error="用户拒绝确认"`。
   - 越权 GET/confirm 403、非 waiting_confirm 409、未知类型 422。
4. 记录实测耗时/步数/结果；失败如实记录。
5. 文档：`docs/AGENT_ENGINE.md`、D-066、PROGRESS、AGENTS §9.6 锚点、SCHEMA/API 更新。
6. Conventional Commit：`feat(s6-2): ...`；`git push` 由用户执行。

## 11. 风险与已知边界

- **LangGraph 传递依赖**：安装带入 langchain-core 1.8.1、httpx2 等；需跑全量 pytest 确认无冲突；requirements 只固定直接依赖 `langgraph==1.2.22`。
- **SCHEMA 增量**：`state_json`/`created_at` 是 S6-2 的必要增列；已在本 spec 明确，实施时先改 SCHEMA 再迁移，不改历史迁移。
- **步数口径**：12 行包含 plan/observe/finalize；真实任务最多约 5 个工具步。demo 限制 1–5 步；需确认时建议 ≤4 步。S6-3/S6-4 需按此预算设计工具数。
- **token 预算统计不全**：S6-1 工具不回报 token；S6-2 只能统计 `RunContext.add_tokens()` 的显式累加。S6-3/S6-4 的 LLM 规划器必须调用它，否则预算形同虚设。
- **崩溃恢复重跑**：极端情况下 act 成功但 observe 未提交，会重跑一次只读工具；写工具（S6-4）必须靠确认节点保护，不能靠重试。
- **确认只做通过/拒绝**：`edits` 只存不执行，换题/调难度在 S6-4。
- **队列幂等**：重复 POST confirm 在第一次已把状态改走后，第二次会 409；ARQ 重复投递由 `run_agent_task` 的终态/waiting 检查兜底。
- **并发**：同一任务两个执行实例可能同时写步骤（目前无行锁/租约）；S6-2 依赖 ARQ 单 job + confirm 409 收敛，S6-6 再加幂等/锁。
- **LangGraph API 变化**：锁定 1.2.22；升级需重跑图测试。

## 12. 契约影响

- `API.md §10`：三个接口由占位改为定稿；`type` 在 S6-2 只开放 `demo`。
- `SCHEMA.md §8.1`：新增 `state_json`、`created_at`；§8.2 的 `status` 取值定稿；§10.13 增加 agent_steps.status 行。
- 依赖：`backend/requirements.txt` + `langgraph==1.2.22`。
- 配置：`.env.example` + `AGENT_MAX_STEPS`、`AGENT_TOKEN_BUDGET`。
- 无前端改动；无新 `llm_call_logs.scene`（S6-2 demo 不调 LLM，且 `agent` 场景已在 CHECK 内）。