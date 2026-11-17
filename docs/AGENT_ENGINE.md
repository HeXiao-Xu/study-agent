# Agent 状态机（S6-2）

> 代码：`backend/app/ai/agents/{state,engine}.py`、`backend/app/ai/agents/tasks/demo.py`、`backend/app/services/agent_service.py`、`backend/app/tasks/agent_run.py`、`backend/app/api/v1/agent.py`
> 表：`agent_tasks` / `agent_steps`（SCHEMA §8.1/§8.2，迁移 `0018_s6_2`）
> 决策：D-066；工具清单见 [AGENT_TOOLS.md](AGENT_TOOLS.md)。

## 1. 图结构

```text
START → plan ──(无步骤/预算耗尽)──────────────→ finalize → END
           ├──(resume_from=confirm)───────────→ confirm
           └──→ act → observe ──(失败)────────→ reflect ──(重试<2)→ act
                            ├──(预算/致命)────→ finalize
                            ├──(全部完成且需确认)→ confirm
                            └──(全部完成)──────→ finalize
confirm ──(无决策)──→ END（waiting_confirm）
        └──(已确认/拒绝)──→ finalize
```

- 六节点：`plan / act / observe / reflect / confirm / finalize`；每个节点执行后写一条 `agent_steps`，并在同一事务更新 `agent_tasks.state_json`。
- 最大步数 12 **按 agent_steps 行数计**。3 步任务成功 = 8 行；需确认 +1；确认恢复再 +confirm/finalize 2 行。
- 工具失败最多重试 2 次（共 3 次尝试）；token 预算默认 20000，超限终止并保留已产出的 artifacts。
- `LangGraph==1.2.22`（`StateGraph`，无 checkpointer；挂起快照存 `state_json`）。

## 2. State（`AgentState`）

| 字段 | 含义 |
|---|---|
| `user_id` / `task_input` | 任务发起者与校验后的输入 |
| `plan` / `current_index` | 工具计划（tool/input/purpose）与当前步 |
| `artifacts` | `{step_1: {tool,input,output}, ...}`，中间产物 |
| `citations` | `search_notes` 命中收集的 `{note_id,note_title,chunk_id}` |
| `need_human_confirm` / `confirm_decision` | 是否需确认；`{approved,comment,edits}` |
| `retry_count` / `token_budget` / `token_cost` | 重试次数与预算 |
| `max_steps` / `step_count` | 步数上限与已写步骤数 |
| `last_error` / `fatal_error` / `error` | 当前工具错误 / 终止原因 / 最终错误 |
| `status` / `resume_from` / `result` | running/waiting_confirm/succeeded/failed；confirm/resume；最终结果 |

## 3. 表与步骤语义

`agent_steps` 每行：`step_no`（从 1 连续）、`thought`、`tool_name`、`tool_input_json`、`tool_output_json`、`latency_ms`、`status ∈ {ok,error,waiting_confirm}`。
`agent_tasks` 额外：`state_json`（每节点快照）、`created_at`（S6-2 增列）；`steps_count/token_cost` 随步骤更新；waiting_confirm 时 `result_json` 存中间产物。

一次成功 3 步的步骤形态：

```text
1  plan      ok    —            计划 3 步：calculator、make_mindmap、list_mistakes
2  act       ok    calculator   计算 2 的 10 次方            latency
3  observe   ok    —            步骤 1 成功，产物已收集
4  act       ok    make_mindmap 生成导图                      latency
5  observe   ok    —            步骤 2 成功，产物已收集
6  act       ok    list_mistakes 取最近错题                   latency
7  observe   ok    —            步骤 3 成功，产物已收集
8  finalize  ok    —            任务完成
```

## 4. 三个 API

```bash
# 创建（202，立即返回，ARQ 执行）
curl -X POST http://127.0.0.1:8001/api/v1/agent/tasks \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_type":"demo","input":{"steps":[
        {"tool":"calculator","input":{"expression":"2**10"},"purpose":"计算"},
        {"tool":"make_mindmap","input":{"title":"函数","nodes":[{"id":"1","name":"函数"}]}}
      ]}}'

# 轮询（状态 + 步骤 + 结果）
curl http://127.0.0.1:8001/api/v1/agent/tasks/1 -H "Authorization: Bearer $TOKEN"

# 人工确认（仅 waiting_confirm；202，异步恢复）
curl -X POST http://127.0.0.1:8001/api/v1/agent/tasks/1/confirm \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"approved":true,"comment":"可以","edits":null}'
```

- 创建/确认都只接受 student；GET 仅本人（他人 403/40300，不存在 404/40400）。
- 非 `waiting_confirm` 调 confirm → 409/40900。
- `demo` 是 S6-2 唯一任务类型；`weekly_mindmap`/`mistake_paper` 在 S6-3/S6-4 注册后开放。
- `edits` 只存进确认决策，不执行（S6-4 消费）。

## 5. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_MAX_STEPS` | 12 | agent_steps 行数上限 |
| `AGENT_TOKEN_BUDGET` | 20000 | 单任务 token 预算；demo 输入可覆盖（≥100） |

## 6. 挂起/恢复时序

```text
POST /agent/tasks (require_confirm=true)
  → ARQ agent.run → plan/act/observe ×N → confirm（无决策）
  → 写 waiting_confirm 步骤 + state_json/result_json → 图结束
GET  → status=waiting_confirm，result.awaiting_confirm=true
POST /confirm {approved:true}
  → 写 state.confirm_decision + resume_from=confirm，status=pending → 再入队
  → agent.run 读 state_json → plan 跳过 → confirm 记录 → finalize
  → status=succeeded；前 N 步工具不重跑
```

## 7. 已知边界

- token 预算只统计任务定义显式 `ctx.add_tokens` 的量；S6-1 工具不回报 token，S6-3/S6-4 的规划器必须自行累加。
- 进程崩溃后 `status=running` 会从 `state_json` 续跑；极端情况下 act 成功但 observe 未提交会重跑一次只读工具。写工具必须等 S6-4 确认节点保护。
- `edits` 只存不执行；任务列表/取消/SSE 未做（S6-5/S6-6）。
- 并发双执行无行锁；依赖 ARQ 单 job 与 confirm 状态机收敛，S6-6 再加幂等/租约。
- `agent_steps` 无 `created_at`，时间线只靠 `step_no`；需要时间戳时再迁移。