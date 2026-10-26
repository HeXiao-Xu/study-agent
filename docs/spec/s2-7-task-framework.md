# S2-7 异步任务框架 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-7
- 日期：2026-10-26
- 状态：已实现并验收（2026-10-26；pytest 401/401 + 真实 Redis/Worker/Postgres 全流程；实施记录见 docs/plan/s2-7-task-framework.md）
- 上游：S0-4（Redis 在跑）、S2-2（认证）、S2-3（权限）、S2-5（迁移 0003 为当前 head）
- 下游：S2-8 文档解析 Worker（`parse_document` 任务 + 进度回写）、S4/S5 的异步接口（错题诊断、组卷等）
- 产物：迁移 `0004_s2_7_async_tasks.py`、`models/async_task.py`、`tasks/{registry,queue,worker,demo}.py`、`services/task_service.py`、`schemas/tasks.py`、`api/v1/tasks.py`、4 个测试文件

## 1. 目标

1. 统一提交入口：`enqueue(task_name, payload, owner)` 先落库（`pending`）再进 ARQ 队列，返回**任务 id**；入队失败时任务落 `failed` 并抛 500/50000。
2. Worker 按注册表执行任务：`pending → running → succeeded`，失败按 **最多 3 次尝试、指数退避 2s/4s** 重试，终态 `failed` 且错误可读。
3. `GET /api/v1/tasks/{id}` 供前端轮询；`POST /api/v1/tasks/demo` 提交“睡 N 秒”的验收任务（可指定 `fail=true` 验证重试）。
4. 状态持久化在 Postgres，不依赖 ARQ 的结果过期策略；Worker 用独立进程，启动命令进 README。
5. 测试不连 Redis/Postgres：队列与状态更新都可注入假实现。

非目标：定时任务（APScheduler，后续卡）、任务取消/重跑接口、任务列表分页、优先级队列、Worker 多机扩展、SSE 推送。

## 2. 范围

### 2.1 做

- 依赖 `arq`（自带 redis），版本安装后锁定。
- 迁移 0004：`async_tasks` 表 + `TaskStatus` 枚举常量。
- `app/tasks/registry.py`：任务名 → 同步处理函数（`(Session, dict) -> dict | None`）。
- `app/tasks/demo.py`：`demo.sleep` 任务。
- `app/tasks/queue.py`：`TaskQueue` 协议 + `ArqTaskQueue` + `get_task_queue()`。
- `app/tasks/worker.py`：`run_task` 协程 + `WorkerSettings`。
- `app/services/task_service.py`：`create_task` / `submit_demo` / `get_task` / `execute_task`（同步执行体）。
- `app/schemas/tasks.py`、`app/api/v1/tasks.py`、`router.py` 挂载。
- 配置 4 项 + 异常 `TaskQueueUnavailableError`。
- 测试 5 个文件共 33 条。
- 真实 Redis + Worker + Postgres 验收：`pending → running → succeeded`；`fail=true` 时 3 次尝试后 `failed`。

### 2.2 不做

- 不接 APScheduler、不做 beat/周期任务。
- 不做任务取消、重跑、列表、统计。
- 不做 SSE/WebSocket 推送（S3-5 再定）。
- 不把 S2-8 的解析逻辑写进来；本卡只交付框架 + demo 任务。
- 不做多队列/优先级/去重（同一任务重复提交会各建一行）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 用 **ARQ** 而不是 Celery | AGENTS §2 已定 ARQ；异步原生、依赖小；S2-8 的同步解析用 `asyncio.to_thread` 包一层即可 |
| 2 | 状态存 **DB 表 `async_tasks`**，ARQ 只当执行器 | ARQ 结果默认 1 小时过期、无历史、无法按用户鉴权；DB 还能给 S2-11 前端直接查 |
| 3 | 提供 `POST /tasks/demo`（student，`seconds` 1–10，`fail` bool） | 任务卡验收就是“提交睡 5 秒任务 + 轮询”，没有提交端点就无法端到端验收 |
| 4 | 状态机 `pending → running → succeeded`；可重试失败回 `pending`，终态 `failed` | 轮询方只需看 4 个值；重试期间回 pending 比一直 running 更诚实 |
| 5 | 最多 3 次尝试，指数退避 `2s`、`4s`（`task_retry_base_seconds * 2^(try-1)`） | 任务卡点名“最多 3 次 + 指数退避”；本地故障多为瞬时 |
| 6 | 处理函数是**同步** `(Session, dict) -> dict | None`，Worker 里 `asyncio.to_thread` 执行 | 现有代码全是同步 SQLAlchemy；在 async worker 里直接跑 CPU/IO 同步代码会阻塞事件循环 |
| 7 | 提交时校验任务名是否已注册，未注册 → 422/42200；运行时仍未注册 → `failed` | 早失败给出可读错误，同时防“注册表在 worker 端缺项”时静默 |
| 8 | 入队失败 → 任务 `failed` +「任务入队失败」+ 抛 500/50000「任务队列不可用」 | 不能留下永远 pending 的幽灵任务；错误话术不泄露 Redis 地址 |
| 9 | `GET /tasks/{id}` 仅创建者可见（admin 不绕过） | 任务 payload/error 可能含业务数据，最小暴露 |
| 10 | 轮询约定：提交 `202` + id；客户端每 1–2s 轮询，`status ∈ {succeeded, failed}` 即停 | 写进 API.md §0，S2-8 前端直接照做 |
| 11 | ARQ job id 固定 `task:{id}`，`max_tries=3`、`job_timeout=300s` | 一个任务行对应一个 job，排障时能直接对上 |
| 12 | 终态任务再次被投递 → 直接返回，不重复执行 | Worker 重启/重复投递时的幂等保护 |

## 4. 数据（迁移 0004）

`async_tasks`：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | 主键；同时用作 ARQ job id |
| user_id | BIGINT FK users.id | 否 | — | 创建者 |
| name | TEXT | 否 | — | 任务名（注册表键，如 `demo.sleep`） |
| status | TEXT | 否 | `'pending'` | CHECK `pending/running/succeeded/failed` |
| payload | JSONB | 否 | `'{}'` | 提交参数 |
| result | JSONB | 是 | — | 成功结果 |
| error | TEXT | 是 | — | 最近一次失败原因（重试中也写） |
| attempts | INT | 否 | `0` | 已执行次数（= ARQ job_try） |
| created_at | TIMESTAMPTZ | 否 | now() | |
| started_at | TIMESTAMPTZ | 是 | — | 首次开始执行时间（重试不覆盖） |
| finished_at | TIMESTAMPTZ | 是 | — | 终态时间 |

索引：`ix_async_tasks_user_id_created_at (user_id, created_at DESC)`、`ix_async_tasks_status (status)`。

枚举：`app/models/enums.py` 新增 `TaskStatus`（StrEnum，4 个值），CHECK 用 `in_check`（D-021）。

## 5. 接口契约

### POST /api/v1/tasks/demo

- 权限：`student`
- 类型：异步任务提交
- 请求体：`{"seconds": 5, "fail": false}`（`seconds` 1–10，默认 5；`fail` 默认 false）
- 成功：**202**，`Envelope[TaskOut]`：`id` / `name` / `status`（= `pending`）/ `created_at`
- 错误：`403/40300` 非 student；`422/42200` 参数越界；`500/50000` 任务队列不可用

### GET /api/v1/tasks/{task_id}

- 权限：仅创建者（admin 不绕过）
- 出参：`Envelope[TaskDetailOut]`
  - `id` / `name` / `status` / `attempts` / `payload` / `result` / `error` / `created_at` / `started_at` / `finished_at`
- 错误：`404/40400`「任务不存在」；`403/40300`「无权访问该任务」

## 6. 组件契约

### registry.py

```python
TaskHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]
HANDLERS: dict[str, TaskHandler]
def register(name: str) -> Callable[[TaskHandler], TaskHandler]
def get_handler(name: str) -> TaskHandler | None
```

`register` 重复注册同名任务 → `ValueError`（启动期错误，不做运行时兜底）。

### demo.py

```python
@register("demo.sleep")
def demo_sleep(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    seconds = int(payload.get("seconds", 5))
    time.sleep(seconds)
    if payload.get("fail"):
        raise RuntimeError("演示任务按请求失败")
    return {"slept": seconds}
```

### queue.py

```python
class TaskQueue(Protocol):
    def enqueue(self, name: str, task_id: int) -> None: ...

class ArqTaskQueue:
    def enqueue(self, name, task_id) -> None:
        asyncio.run(self._enqueue(name, task_id))
```

`_enqueue`：`create_pool(RedisSettings.from_dsn(settings.redis_url))` → `enqueue_job("run_task", task_id, _job_id=f"task:{task_id}", _job_timeout=..., _max_tries=settings.task_max_tries)` → `await pool.aclose()`；任何异常（含 `job is None`）包成 `TaskQueueUnavailableError`。

> 为什么每次 `asyncio.run`：提交是低频动作（每次上传一次），一连接一循环的代价可忽略；比维护后台事件循环线程简单，且测试注入假队列即可。

### worker.py

```python
async def run_task(ctx: dict[str, Any], task_id: int) -> str:
    outcome = await asyncio.to_thread(execute_task, task_id, int(ctx.get("job_try", 1)))
    if outcome.retry_in is not None:
        raise Retry(defer=outcome.retry_in)
    return outcome.status
```

`WorkerSettings`：`functions=[run_task]`、`redis_settings=RedisSettings.from_dsn(...)`、`job_timeout`、`max_tries`、`keep_result`、`health_check_interval=30`。

### task_service.py

- `create_task(session, *, owner, name, payload, queue) -> AsyncTask`：未注册 422 → 建行 `pending` → commit → `queue.enqueue(...)`；入队异常 → 行置 `failed` + error + commit → 抛 `TaskQueueUnavailableError`。
- `submit_demo(session, *, owner, seconds, fail, queue) -> AsyncTask`：走 `create_task("demo.sleep", {...})`。
- `get_task(session, *, task_id, viewer) -> AsyncTask`：不存在 404「任务不存在」；`user_id != viewer.id` → 403「无权访问该任务」。
- `execute_task(task_id: int, job_try: int) -> TaskOutcome`（同步，Worker 线程内）：
  1. 开独立 session；行不存在 → 记录日志并返回 `status="missing"`（不抛，避免 Worker 反复重试）。
  2. 已终态 → 直接返回当前状态（幂等）。
  3. 处理器缺失 → 置 `failed` +「未知任务类型：x」。
  4. `status=running`、`attempts=job_try`、首次写 `started_at`、commit。
  5. 成功 → `succeeded` + `result` + `finished_at`。
  6. 失败且 `job_try < max_tries` → 回 `pending` + `error=f"第 {job_try} 次失败：{exc}"`，返回 `retry_in=base * 2 ** (job_try - 1)`。
  7. 失败且最后一次 → `failed` + error + `finished_at`。
  8. `finally` 关闭 session；日志只记 task_id/name/status/attempts，不记 payload 全文。

`TaskOutcome` 是 dataclass：`status: str`、`retry_in: float | None`。

## 7. 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `TASK_MAX_TRIES` | `3` | 最大尝试次数 |
| `TASK_RETRY_BASE_SECONDS` | `2.0` | 退避基数（2s、4s） |
| `TASK_JOB_TIMEOUT_SECONDS` | `300` | 单次执行超时 |
| `TASK_RESULT_KEEP_SECONDS` | `3600` | ARQ 结果保留（页面主查 DB，不依赖它） |

`.env.example` 同步；`REDIS_URL` 已有。

## 8. 测试计划（33 条，不连 Redis/Postgres）

`tests/test_task_registry.py`（5）
1. 注册后可取回同一处理器
2. 重复注册同名任务 → ValueError
3. `.all` 后缀任务名 → ValueError
4. `demo_sleep` 返回 `{"slept": N}`
5. `demo_sleep` 在 `fail=true` 时抛 RuntimeError

`tests/test_task_queue.py`（5）
1. enqueue 调用 `enqueue_job` 参数正确（名字、task_id、`task:{id}`、超时、重试数）
2. 池在结束时 `aclose`
3. `enqueue_job` 返回 None → `TaskQueueUnavailableError`
4. `enqueue_job` 抛连接异常 → `TaskQueueUnavailableError`（message 不含地址）
5. 不向 `enqueue_job` 传 `_max_tries`/`_job_timeout`（ARQ 0.28 不支持，会被当函数 kwargs）

`tests/test_task_runner.py`（8）
1. 成功：pending→running→succeeded，attempts/started_at/finished_at/result 正确
2. 已终态再执行 → 不调用 handler
3. 行不存在 → `status="missing"` 且不抛
4. 未知任务名 → failed + error 含任务名
5. 首次失败（job_try=1）→ 回 pending、error 含「第 1 次」、retry_in=2.0
6. 第二次失败（job_try=2）→ retry_in=4.0
7. 第三次失败（job_try=3）→ failed、finished_at 非空、attempts=3
8. handler 抛异常不外泄（execute_task 返回 outcome，不 raise）

`tests/test_task_service.py`（8）
1. create 未注册任务名 → 422
2. create 成功 → pending 行 + 队列收到 name/task_id
3. create 入队失败 → 行 failed + error「任务入队失败」+ 抛 50000
4. submit_demo 默认 seconds=5、fail=False
5. get 本人 → 返回行
6. get 他人 → 403
7. get 不存在 → 404
8. demo 任务名常量与注册表一致

`tests/test_tasks_api.py`（7）
1. POST demo → 202 + `status=pending` + 队列被调用
2. GET 自己的任务 → 200（running 用例）
3. GET 他人任务 → 403/40300
4. GET 不存在 → 404/40400
5. POST 未带 token → 401
6. POST teacher → 403
7. POST `seconds=0` → 422/42200

## 9. 验收（真实 Redis + Worker + Postgres）

1. `alembic upgrade head` → `0004_s2_7`；`\d async_tasks` 有 CHECK 与两个索引。
2. 起 uvicorn + `arq app.tasks.worker.WorkerSettings`（两个后台进程）。
3. `POST /tasks/demo {"seconds":5}` → 202，立即 `GET` 得到 `pending`（或已 `running`）。
4. 轮询：观察到 `running`（attempts=1、started_at 非空）→ 约 5s 后 `succeeded`（result `{"slept":5}`、finished_at 非空）。
5. `POST /tasks/demo {"seconds":1,"fail":true}` → 轮询到 `failed`，`attempts=3`，`error` 含第 3 次失败；时间线上的重试间隔可读（psql 查 error 文本 + attempts）。
6. 越权：B 查 A 的任务 → 403/40300。
7. Worker 日志出现 `task_started` / `task_succeeded` / `task_retry` / `task_failed`（只含 id/name/attempts）。
8. 清理任务行与测试用户；`pytest` 全绿。

## 10. 文档同步

- `API.md` §0 轮询约定（替换 TODO）+ 新增 §2.5「异步任务」两接口 + §12 缺口（取消/重跑/列表/SSE）。
- `SCHEMA.md` 新增 `async_tasks` 表（§4.5 或 §5 末尾）+ §10 状态枚举。
- `AGENTS.md` §9.2 异步任务约定 + §9.6 任务框架锚点 + 目录说明（`app/tasks`）。
- `DECISIONS.md` D-027。
- `PROGRESS.md` 状态、清单、遗留、日志。
- `README.md` 日常启动加「③ 异步 Worker」命令。
- `requirements.txt`（arq + redis 实测版本）、`.env.example` 四项配置。
- spec/plan 执行记录。

## 11. 已知限制

- 提交时用 `asyncio.run` 建短连接：高频提交会浪费连接（当前量级无影响）。
- 只支持单队列/单 Worker；多 Worker 并发时任务会被随机取走（ARQ 语义），没有优先级。
- 没有任务取消/重跑/列表接口；`error` 只保留最近一次失败文本。
- Worker 崩溃时 running 行会留在 running（无心跳回收），需要人工/后续卡清理。
- `demo.sleep` 是验收/联调端点，生产前端不该暴露入口。
- 任务结果写 DB 可能较大（JSONB），当前无大小限制。
- 轮询接口不做长轮询/推送，前端按 1–2s 间隔查询。