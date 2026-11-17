# S6-6 Agent 可靠性加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 在 5 类失败（工具报错/超时/超预算/参数非法/LLM 非 JSON）下优雅降级、保留已有产物并留日志；失败任务可幂等重跑（清空旧步骤）。

**Architecture:** 引擎增加任务级 deadline（`deadline_at`）与部分结果保留；tool 层加 `allow_write` 门禁与校验失败日志；service 新增 `retry_agent_task`（failed → 清步骤/重置 → 202 入队）；前端失败详情加「重跑任务」。不新增表/依赖。

**Tech Stack:** LangGraph 1.2.22、FastAPI、SQLAlchemy、Vue 3 + Element Plus、pytest、Vitest。

**Spec:** `docs/spec/s6-6-reliability.md`

## Global Constraints

- 重跑只允许 `failed`；清空旧 `agent_steps` 后从头跑；行锁保证并发只成功一次；重复 409。
- 超时按任务级 deadline（默认 600s，`AGENT_TASK_TIMEOUT_SECONDS`），不把工具放子线程；工具 `TimeoutError` 按可重试失败。
- 预算/限步/超时终止都保留已有 artifacts/citations。
- `ToolContext.allow_write` 默认 False；`ToolSpec.write=True` 未授权 403，handler 不执行；当前 11 工具全只读。
- 失败日志只记计数/工具/步骤/错误码，不记工具正文、Prompt、Key。
- 不新增表/迁移/依赖；前端仍轮询。
- 每个 Task 先红后绿并提交；验收后创建本地 tag `m5-agent-done`。

---

### Task 1: 引擎超时/限步/预算保留 + 日志 + 输入扩展

**Files:**
- Modify: `backend/app/ai/agents/state.py`
- Modify: `backend/app/ai/agents/engine.py`
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `backend/app/ai/agents/tasks/demo.py`
- Modify: `backend/app/ai/agents/tasks/weekly_mindmap.py`
- Test: `backend/tests/test_agent_reliability.py`

**Interfaces:**
- Produces: `AgentTaskTimeoutError`；`new_state(..., timeout_seconds=None)` + `deadline_at`
- Produces: `DbStepRecorder.last_state`；service 超时/限步用 last_state 写部分 result
- Produces: `DemoInput.task_timeout_seconds`、`WeeklyInput.token_budget`

- [x] **Step 1: 写失败测试**

```python
"""S6-6 可靠性：超时、工具超时、预算/限步保留产物、日志。"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

from app.ai.agents.engine import (
    AgentEngine,
    AgentStepLimitError,
    AgentTaskTimeoutError,
    PlanExtension,
    RunContext,
)
from app.ai.agents.state import new_state


class Recorder:
    def __init__(self):  # noqa: ANN001
        self.steps = []

    def record(self, *, step_no, thought, status, state, **kwargs):  # noqa: ANN001
        self.steps.append(step_no)


class OneStepSpec:
    task_type = "one"
    requires_confirm = False

    def build_plan(self, state):  # noqa: ANN001
        return [{"tool": "calculator", "input": {}, "purpose": "一步"}]

    def extend_plan(self, state):  # noqa: ANN001
        return PlanExtension()

    def finalize(self, state):  # noqa: ANN001
        return {"artifacts": state.get("artifacts") or {}}


def _engine(spec, invoker):  # noqa: ANN001
    return AgentEngine(
        spec,
        RunContext(user=SimpleNamespace(id=18), recorder=Recorder(), tool_invoker=invoker),
    )


def test_deadline_in_past_raises_timeout(caplog):
    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=12)
    state["deadline_at"] = time.time() - 1
    state["step_count"] = 1
    with caplog.at_level(logging.WARNING):
        with pytest.raises(AgentTaskTimeoutError):
            _engine(OneStepSpec(), lambda *a, **k: {}).run(state)
    assert "agent_task_timeout" in caplog.text


def test_tool_timeout_error_is_retried_then_fails(caplog):
    calls = {"n": 0}

    def boom(*a, **k):  # noqa: ANN002, ANN003
        calls["n"] += 1
        raise TimeoutError("slow")

    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=12)
    with caplog.at_level(logging.WARNING):
        final = _engine(OneStepSpec(), boom).run(state)
    assert final["status"] == "failed"
    assert "重试" in final["error"]
    assert calls["n"] == 3
    assert "agent_tool_timeout" in caplog.text


def test_budget_exhausted_keeps_artifacts_and_logs(caplog):
    state = new_state(user_id=18, task_input={}, token_budget=100, max_steps=12)
    state["token_cost"] = 100
    with caplog.at_level(logging.WARNING):
        final = _engine(OneStepSpec(), lambda *a, **k: {}).run(state)
    assert final["status"] == "failed"
    assert "token 预算" in final["error"]
    assert final["result"]["artifacts"] == {}
    assert "agent_budget_exhausted" in caplog.text


def test_step_limit_error_class_is_raised():
    state = new_state(user_id=18, task_input={}, token_budget=20000, max_steps=1)
    with pytest.raises(AgentStepLimitError):
        _engine(OneStepSpec(), lambda *a, **k: {}).run(state)
```

`test_agent_task_spec_demo.py` 补 task_timeout_seconds 校验；`test_agent_task_weekly_mindmap.py` 补 token_budget 校验。

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_reliability.py -q`
Expected: FAIL（`AgentTaskTimeoutError` 不存在）

- [x] **Step 3: state/config/engine**

- `state.py`：`import time`；`new_state(..., timeout_seconds: float | None = None)` 写 `deadline_at=time.time()+timeout_seconds if timeout_seconds else None`；`AgentState` 加 `deadline_at: float | None`。
- `config.py`：`agent_task_timeout_seconds: int = Field(default=600, ge=10, le=3600)`；`.env.example` 加 `AGENT_TASK_TIMEOUT_SECONDS=600`。
- `engine.py`：
  - `class AgentTaskTimeoutError(Exception)`；`_guard` 先检查 deadline，再检查步数，均 `logger.warning`。
  - `_act` 增 `except TimeoutError` 分支（message「工具执行超时」、tool_output `{error,code:50000}`、WARNING `agent_tool_timeout`）；AppError 分支补 WARNING `agent_tool_failed`。
  - `_reflect` 增 WARNING `agent_tool_retry` / `agent_tool_retry_exhausted`。
  - `_budget_hit` 命中时 WARNING `agent_budget_exhausted`。
- `DemoInput` 加 `task_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)`；`WeeklyInput` 加 `token_budget: int | None = Field(default=None, ge=100)`。
- service `run_agent_task` 建 state 时：
  ```python
  timeout_seconds = int(task.input_json.get("task_timeout_seconds") or settings.agent_task_timeout_seconds)
  state = new_state(..., timeout_seconds=timeout_seconds)
  ```
- service 捕获 `AgentTaskTimeoutError` / `AgentStepLimitError`：错误信息分别「任务执行超时」「超过最大步数 N」；`DbStepRecorder.last_state` 取部分结果写 `result_json`。
- `DbStepRecorder.last_state` 在 `record` 中更新为 `snapshot`。

- [x] **Step 4: 跑可靠性/图/任务测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_reliability.py tests/test_agent_graph.py tests/test_agent_engine_extension.py tests/test_agent_task_weekly_mindmap.py tests/test_agent_task_spec_demo.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/app/ai/agents backend/app/services/agent_service.py backend/app/core/config.py .env.example \
  backend/tests/test_agent_reliability.py backend/tests/test_agent_task_weekly_mindmap.py \
  backend/tests/test_agent_task_spec_demo.py
git commit -m "feat(s6-6): 任务超时/限步/预算保留与失败日志"
```

---

### Task 2: 参数校验不执行 + 写操作门禁

**Files:**
- Modify: `backend/app/ai/agents/tools/base.py`
- Modify: `backend/app/ai/agents/tools/__init__.py`（若导出 ToolContext 已含）
- Test: `backend/tests/test_agent_tools_registry.py`

**Interfaces:**
- Produces: `ToolContext.allow_write: bool = False`
- Produces: `invoke_tool` 对 write 工具未授权 403/40300；校验失败 WARNING 日志

- [x] **Step 1: 写失败测试**

```python
def test_invalid_tool_input_does_not_call_handler(monkeypatch):
    called = {"n": 0}
    spec = TOOLS["calculator"]
    original = spec.handler

    def spy(ctx, data):  # noqa: ANN001
        called["n"] += 1
        return original(ctx, data)

    TOOLS["calculator"] = dataclasses.replace(spec, handler=spy)
    try:
        with pytest.raises(ToolInputError):
            invoke_tool("calculator", _ctx(), {"expression": ""})
        assert called["n"] == 0
    finally:
        TOOLS["calculator"] = spec


def test_write_tool_requires_allow_write(monkeypatch):
    called = {"n": 0}
    fake = ToolSpec(
        name="fake_write",
        description="写入测试",
        input_model=CalculatorIn,
        output_model=CalculatorOut,
        handler=lambda ctx, data: (called.update(n=called["n"] + 1) or CalculatorOut(expression="1", value=1, text="1", exact=True)),
        write=True,
    )
    TOOLS["fake_write"] = fake
    try:
        with pytest.raises(ForbiddenError):
            invoke_tool("fake_write", _ctx(), {"expression": "1"})
        assert called["n"] == 0
        allowed = ToolContext(session=_FakeSession(), user=_User(), allow_write=True)
        out = invoke_tool("fake_write", allowed, {"expression": "1"})
        assert out.value == 1
        assert called["n"] == 1
    finally:
        TOOLS.pop("fake_write", None)
```

需导入 `dataclasses`、`ToolSpec`、`CalculatorIn/Out`、`ForbiddenError`。

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_tools_registry.py -q`
Expected: FAIL（`allow_write`/403 未实现）

- [x] **Step 3: 实现门禁**

- `ToolContext` 加 `allow_write: bool = False`。
- `invoke_tool` 取到 spec 后：
  ```python
  if spec.write and not ctx.allow_write:
      logger.warning("agent_tool_write_blocked tool=%s", name)
      raise ForbiddenError("写操作需要人工确认")
  ```
- 入参校验失败时 `logger.warning("agent_tool_input_invalid tool=%s error=%s", name, ...)` 后再抛 `ToolInputError`。
- 现有 11 个工具 `write=False` 不变；页面/服务不传 `allow_write`。

- [x] **Step 4: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_tools_registry.py tests/test_agent_tool_calculator.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/app/ai/agents/tools backend/tests/test_agent_tools_registry.py
git commit -m "feat(s6-6): 工具参数校验不执行与写操作 allow_write 门禁"
```

---

### Task 3: 失败任务重跑（service + API）

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/api/v1/agent.py`
- Modify: `docs/API.md §10`
- Test: `backend/tests/test_agent_retry_api.py`
- Test: `backend/tests/test_agent_service.py`（补 retry）

**Interfaces:**
- Produces: `retry_agent_task(session, *, task_id, viewer, queue) -> AgentTask`
- Produces: `POST /api/v1/agent/tasks/{id}/retry`（202）

- [x] **Step 1: 写失败测试**

```python
"""S6-6 失败任务重跑：202/403/404/409。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError
from app.core.security import create_access_token
from app.main import app
from app.services import agent_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, user):  # noqa: ANN001
        self.user = user

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user


class FakeQueue:
    def enqueue(self, name, task_id):  # noqa: ANN001
        return None


def _user(role="student"):  # noqa: ANN001
    from app.models.user import User
    user = User(username="retry_s66", nickname="r", grade="高二", role=role, password_hash="x")
    user.id = 18
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(status="failed"):  # noqa: ANN001
    from app.models.agent_task import AgentTask
    task = AgentTask(user_id=18, task_type="weekly_mindmap", input_json={"days": 30}, status=status)
    task.id = 11
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 11
    task.token_cost = 0
    task.error = "old"
    task.started_at = None
    task.finished_at = None
    return task


def test_retry_returns_202(monkeypatch):
    monkeypatch.setattr(agent_service, "retry_agent_task", lambda *a, **k: _task("pending"))
    resp = _client(_user()).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"


def test_retry_conflict_409(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise ConflictError("只有失败任务可以重跑")
    monkeypatch.setattr(agent_service, "retry_agent_task", boom)
    resp = _client(_user()).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 409


def test_retry_teacher_forbidden():
    resp = _client(_user("teacher")).post("/api/v1/agent/tasks/11/retry")
    assert resp.status_code == 403
```

`test_agent_service.py` 补：

```python
def test_retry_resets_failed_task(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: captured.update(k))
    task = _task("failed")
    task.state_json = {"step_count": 11}
    task.result_json = {"artifacts": {}}
    task.error = "old"
    task.steps_count = 11
    task.token_cost = 5
    session = FakeSession(task)
    agent_service.retry_agent_task(
        session, task_id=71, viewer=_owner(), queue=FakeQueue()
    )
    assert task.status == "pending"
    assert task.state_json is None and task.result_json is None
    assert task.error is None
    assert task.steps_count == 0 and task.token_cost == 0
    assert captured["payload"] == {"agent_task_id": 71}


def test_retry_non_failed_conflict():
    with pytest.raises(ConflictError):
        agent_service.retry_agent_task(
            FakeSession(_task("succeeded")), task_id=71, viewer=_owner(), queue=FakeQueue()
        )
```

> FakeSession.get 需接受 `with_for_update` 关键字；当前实现签名可改为 `def get(self, model, pk, **kwargs)`。`session.execute(delete...)` 需 fake 实现返回 None。

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_retry_api.py -q`
Expected: FAIL（404）

- [x] **Step 3: 实现 service/API**

- service：
  ```python
  from sqlalchemy import delete
  def retry_agent_task(session, *, task_id, viewer, queue) -> AgentTask:
      task = session.get(AgentTask, task_id, with_for_update=True)
      if task is None: raise NotFoundError("任务不存在")
      if task.user_id != viewer.id: raise ForbiddenError("无权访问该任务")
      if task.status != STATUS_FAILED: raise ConflictError("只有失败任务可以重跑")
      previous_error = task.error
      session.execute(delete(AgentStep).where(AgentStep.task_id == task.id))
      task.state_json = None
      task.result_json = None
      task.error = None
      task.steps_count = 0
      task.token_cost = 0
      task.started_at = None
      task.finished_at = None
      task.status = "pending"
      session.commit()
      logger.info("agent_task_retry task_id=%s previous_error=%s", task.id, previous_error)
      try:
          task_service.create_task(session, owner=viewer, name=TASK_RUN_AGENT,
                                   payload={"agent_task_id": task.id}, queue=queue)
      except Exception:
          task.status = STATUS_FAILED
          task.error = "任务入队失败"
          task.finished_at = _now()
          session.commit()
          raise
      return task
  ```
- API：`@router.post("/tasks/{task_id}/retry", status_code=202, response_model=Envelope[AgentTaskOut])`，student，调用 service。
- API.md 补契约（仅 failed；清空旧步骤；202；409）。

- [x] **Step 4: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_retry_api.py tests/test_agent_service.py tests/test_agent_list_api.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/app/services/agent_service.py backend/app/api/v1/agent.py \
  backend/tests/test_agent_retry_api.py backend/tests/test_agent_service.py docs/API.md
git commit -m "feat(s6-6): 失败任务重跑接口（清空旧步骤、幂等）"
```

---

### Task 4: 前端重跑按钮

**Files:**
- Modify: `web/src/api/agent.ts`
- Modify: `web/src/api/agent.spec.ts`
- Modify: `web/src/views/agent/TaskDetail.vue`
- Modify: `web/src/views/agent/TaskDetail.spec.ts`
- Modify: `web/src/views/agent/status.ts`（无需改，复用）

**Interfaces:**
- Produces: `retryAgentTask(id): Promise<AgentTaskSummary>`
- Produces: 失败详情「重跑任务」按钮

- [ ] **Step 1: 写失败测试**

`agent.spec.ts` 补：

```ts
it('retries a failed task', async () => {
  http.post.mockResolvedValue(envelope({ id: 11, status: 'pending' }))
  await retryAgentTask(11)
  expect(http.post).toHaveBeenCalledWith('/api/v1/agent/tasks/11/retry')
})
```

`TaskDetail.spec.ts` 补：

```ts
it('offers retry on failed tasks', async () => {
  const failed = detail({ status: 'failed', error: '工具连续失败', result: null, steps: [] })
  api.getAgentTask.mockResolvedValue(failed)
  api.retryAgentTask.mockResolvedValue({ id: 5, status: 'pending' })
  const wrapper = mountPage()
  await flushPromises()
  await wrapper.get('[data-testid="retry"]').trigger('click')
  await flushPromises()
  expect(api.retryAgentTask).toHaveBeenCalledWith(5)
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/api/agent.spec.ts src/views/agent/TaskDetail.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

- `api/agent.ts` 加 `retryAgentTask`。
- `TaskDetail.vue` failed alert 区域加：
  ```vue
  <el-button type="warning" :loading="retrying" data-testid="retry" @click="retryTask">
    重跑任务
  </el-button>
  ```
  `retryTask`：`retrying=true`；`await retryAgentTask(taskId)`；`await load()`；catch 写页内 error；finally false。
- 注释说明重跑会清空旧步骤、从头执行（UI 提示文案「重跑会清空旧步骤并重新执行」）。

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd web && npm run test:run -- src/api/agent.spec.ts src/views/agent/TaskDetail.spec.ts`
Run: `cd web && npm run build`
Expected: PASS / build 0

- [ ] **Step 5: 提交**

```bash
git add web/src/api/agent.ts web/src/api/agent.spec.ts web/src/views/agent/TaskDetail.vue \
  web/src/views/agent/TaskDetail.spec.ts
git commit -m "feat(s6-6): 任务详情失败重跑按钮"
```

---

### Task 5: 文档、全量测试、5 类失败真实验收与 tag

**Files:**
- Create: `docs/AGENT_RELIABILITY.md`
- Modify: `docs/DECISIONS.md`（D-069）
- Modify: `docs/PROGRESS.md`
- Modify: `AGENTS.md` §9.6
- Create: `.sdd/s6-6/acceptance-evidence.md` + 截图

- [ ] **Step 1: 文档**

- `AGENT_RELIABILITY.md`：失败分类与状态、超时/预算/限步口径、部分结果、重跑语义、写门禁、日志事件表、5 类场景复现命令、已知边界。
- D-069：任务级超时、重跑清步骤、allow_write、日志、验收数字。
- PROGRESS：S6-6 完成、下一步 S7-1、tag `m5-agent-done` 本地已打。
- AGENTS §9.6 追加可靠性锚点。

- [ ] **Step 2: 全量测试**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../web && npm run test:run && npm run build
```

记录数字（S6-5 基线：后端 1569、前端 383/65）。

- [ ] **Step 3: 5 类失败真实验收**

启动 worker/uvicorn 后（user 18）：

1. **工具报错**：POST demo `get_kp_subgraph 999999` → failed、3 次尝试、error 含「重试上限」；GET 步骤含 error 行。
2. **超时**：POST demo `{"task_timeout_seconds":1,"steps":[{"tool":"generate_questions","input":{"kp_id":137,"difficulty":3,"count":1,"qtype":"解答"}}]}` → failed「任务执行超时」，已有步骤/产物保留；worker 日志含 `agent_task_timeout`。
3. **超预算**：POST `weekly_mindmap {"days":30,"token_budget":100}` → failed「token 预算不足…」，`result.artifacts/citations` 非空；日志含 `agent_budget_exhausted`。
4. **参数非法**：POST demo `calculator {"expression":""}` → 422；`scripts/agent_tools.py call --user-id 18 calculator '{"expression":""}'` → 422；单测断言 handler 未执行。
5. **LLM 非 JSON**：单测证据（`generate_questions` 重试耗尽、weekly 聚类降级）；真实 LLM 不强制失败，证据里注明。
6. **重跑**：POST `/agent/tasks/{failed_id}/retry` → 202；轮询再次 failed；步骤从 1 重新开始、数量与修复前一致；pending 时再次 retry → 409；Chrome 点「重跑任务」复现。
7. 日志检索：`agent_tool_retry`/`agent_task_timeout`/`agent_budget_exhausted`/`agent_task_retry` 至少各 1 条。

- [ ] **Step 4: 前端 Chrome**

- 失败详情点「重跑任务」→ 状态回排队中/生成中 → 轮询到 failed；步骤时间线从头开始；无 console error。
- 超时/超预算任务详情能看到错误与已有结果（如 weekly 的 artifacts）。
- 截图 `.sdd/s6-6/*.png`。

- [ ] **Step 5: tag 与提交**

```bash
git tag m5-agent-done
git add docs/AGENT_RELIABILITY.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md
git commit -m "docs(s6-6): 可靠性文档、D-069 与验收记录"
```

---

## Self-Review

**Spec coverage：**

| spec 章节 | Task |
|---|---|
| 超时/限步/预算/日志 | Task 1 |
| 参数校验/写门禁 | Task 2 |
| 重跑 service/API | Task 3 |
| 前端重跑 | Task 4 |
| 文档/全量/5 类验收/tag | Task 5 |

**Placeholder scan：** 无 TBD/TODO；关键签名/字段/测试断言给全。

**Type consistency：** `AgentTaskTimeoutError`、`deadline_at`、`DbStepRecorder.last_state`、`ToolContext.allow_write`、`retry_agent_task`、`retryAgentTask` 在各 Task 一致；`DemoInput.task_timeout_seconds` 与 `WeeklyInput.token_budget` 在 service 读取时字段名一致。

**已知取舍：** 重跑不保留旧步骤；超时不打断正在执行的工具；token 预算仍只统计显式累加。