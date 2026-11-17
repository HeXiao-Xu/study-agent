# S6-2 LangGraph 状态机 + 步骤持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LangGraph 交付可挂起/恢复的 Agent 状态机、`agent_tasks`/`agent_steps` 持久化、三个 student API 与 `demo` 任务类型；不实现 S6-3/S6-4 的真实任务。

**Architecture:** `ai/agents/engine.py` 组装 `StateGraph(plan→act→observe→reflect→confirm→finalize)`，通过注入的 `RunContext` 调 S6-1 工具并逐节点写步骤；`services/agent_service.py` 是唯一业务入口（建任务/入队/执行/确认）；API 只做参数、权限与 `Envelope`；ARQ `agent.run` 执行一次图运行，挂起状态存 `agent_tasks.state_json`，确认后重新入队从 `confirm` 节点继续。

**Tech Stack:** Python 3.11、LangGraph 1.2.22、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、ARQ、PostgreSQL 16、pytest。

**Spec:** `docs/spec/s6-2-agent-engine.md`

## Global Constraints

- 只做 S6-2：`demo` 是唯一注册任务类型；`weekly_mindmap`/`mistake_paper` 返回 422「任务类型尚未启用」。
- 最大步数 12 = `agent_steps` 行数；工具失败最多重试 2 次（共 3 次尝试）；token 预算默认 20000。
- `POST /agent/tasks` 与 `POST /agent/tasks/{id}/confirm` 都是 202 + ARQ；GET 同步轮询。
- 每个节点执行后写一条 `agent_steps`，与 `agent_tasks.state_json` 同事务提交。
- 挂起/恢复不重跑已完成工具；`edits` 只存不执行（S6-4 消费）。
- 所有查询显式过滤 `user_id`；他人任务 403/40300，不存在 404/40400，非 `waiting_confirm` 确认 409/40900。
- 不新增其他直接依赖；`langgraph==1.2.22` 已安装并写入 requirements。
- 外部 LLM 不参与 S6-2 demo；测试不连库、不连 Redis、不发网络。
- 先改 `SCHEMA.md`/`API.md` 再写模型/迁移；不改历史迁移；每个 Task 先红后绿并提交。

---

### Task 1: 契约、枚举、模型与迁移 `0018_s6_2`

**Files:**
- Modify: `docs/SCHEMA.md` §8.1/§8.2/§10.13
- Modify: `docs/API.md` §10
- Modify: `backend/app/models/enums.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/models/agent_task.py`
- Create: `backend/app/models/agent_step.py`
- Create: `backend/alembic/versions/0018_s6_2.py`
- Modify: `backend/tests/test_answers_migration.py:61-64`
- Modify: `backend/tests/test_papers_migration.py:61-64`
- Modify: `backend/tests/test_report_migration.py:29-32`
- Modify: `backend/tests/test_review_migration.py:60-63`
- Test: `backend/tests/test_agent_models_migration.py`

**Interfaces:**
- Produces: `AgentTaskStatus` / `AgentStepStatus`（`StrEnum`）、`AGENT_TASK_STATUSES`、`AGENT_STEP_STATUSES`
- Produces: `AgentTask`、`AgentStep` 模型；迁移 head `0018_s6_2`
- Consumes: `in_check()`、`Base`、`User.id`、`agent_tasks.id`

- [x] **Step 1: 先改契约文档**

`docs/SCHEMA.md §8.1` 在 `result_json` 后加 `state_json`（JSONB 可空，图状态快照），在末尾加 `created_at`（TIMESTAMPTZ 非空默认 now()）；`§8.2` 的 `status` 说明改为 `ok / error / waiting_confirm（S6-2 定）`；`§10.13` 补一行 `agent_steps.status` 值集。

`docs/API.md §10` 按 spec §7 改写三个接口：POST 202、GET 详情、POST confirm 202（body `approved/comment/edits`）；注明 S6-2 只开放 `demo`，两个真实类型 S6-3/S6-4 开放。

- [x] **Step 2: 写迁移/模型失败测试（先红）**

```python
"""S6-2 agent_tasks/agent_steps 契约：列、CHECK、唯一键、FK、索引、迁移头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.agent_step import AgentStep
from app.models.agent_task import AgentTask

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_agent_task_columns_match_schema():
    assert set(AgentTask.__table__.columns.keys()) == {
        "id", "user_id", "task_type", "input_json", "status", "result_json",
        "state_json", "error", "steps_count", "token_cost",
        "started_at", "finished_at", "created_at",
    }


def test_agent_step_columns_match_schema():
    assert set(AgentStep.__table__.columns.keys()) == {
        "id", "task_id", "step_no", "thought", "tool_name",
        "tool_input_json", "tool_output_json", "latency_ms", "status",
    }


def test_agent_constraints_fk_and_indexes():
    task_constraints = {c.name for c in AgentTask.__table__.constraints}
    assert "ck_agent_tasks_status" in task_constraints
    step_constraints = {c.name for c in AgentStep.__table__.constraints}
    assert "ck_agent_steps_status" in step_constraints
    assert "uq_agent_steps_task_step" in step_constraints
    fk = next(iter(AgentStep.__table__.columns["task_id"].foreign_keys))
    assert fk.target_fullname == "agent_tasks.id"
    assert fk.ondelete == "CASCADE"
    assert {i.name for i in AgentTask.__table__.indexes} == {"ix_agent_tasks_user_status"}


def test_migration_chain_head_is_s6_2():
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_current_head() == "0018_s6_2"
```

- [x] **Step 3: 运行并确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_models_migration.py -q`
Expected: FAIL（`ModuleNotFoundError: app.models.agent_task`）

- [x] **Step 4: 加枚举**

`backend/app/models/enums.py`：

```python
class AgentTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentStepStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    WAITING_CONFIRM = "waiting_confirm"


AGENT_TASK_STATUSES: tuple[str, ...] = tuple(item.value for item in AgentTaskStatus)
AGENT_STEP_STATUSES: tuple[str, ...] = tuple(item.value for item in AgentStepStatus)
```

- [x] **Step 5: 写模型**

`agent_task.py`：`__tablename__="agent_tasks"`，`id BigInt Identity`，`user_id` FK `fk_agent_tasks_user_id`，`task_type Text`，`input_json JSONB`，`status Text default pending server_default text("'pending'")`，`result_json/state_json JSONB nullable`，`error Text`，`steps_count/token_cost Integer`，`started_at/finished_at/created_at DateTime(timezone=True)`（`created_at` server_default `func.now()`），`Index("ix_agent_tasks_user_status","user_id","status")`，`CheckConstraint(in_check("status", AGENT_TASK_STATUSES), name="ck_agent_tasks_status")`。

`agent_step.py`：`__tablename__="agent_steps"`，`task_id` FK `fk_agent_steps_task_id` `ondelete="CASCADE"`，`step_no Integer`，`thought Text`，`tool_name Text`，`tool_input_json/tool_output_json JSONB`，`latency_ms Integer`，`status Text`，`UniqueConstraint("task_id","step_no", name="uq_agent_steps_task_step")`，`CheckConstraint(in_check("status", AGENT_STEP_STATUSES), name="ck_agent_steps_status")`。

`app/models/__init__.py` 导入两个模型并加进 `__all__`。

- [x] **Step 6: 写迁移 `0018_s6_2`**

```python
revision = "0018_s6_2"
down_revision = "0017_s5_6"

def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("state_json", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("steps_count", sa.Integer(), nullable=True),
        sa.Column("token_cost", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_agent_tasks_user_id"),
        sa.CheckConstraint(
            "status IN ('pending','running','waiting_confirm','succeeded','failed')",
            name="ck_agent_tasks_status",
        ),
    )
    op.create_index("ix_agent_tasks_user_status", "agent_tasks", ["user_id", "status"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("thought", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("tool_input_json", postgresql.JSONB(), nullable=True),
        sa.Column("tool_output_json", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["agent_tasks.id"], name="fk_agent_steps_task_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('ok','error','waiting_confirm')", name="ck_agent_steps_status"
        ),
        sa.UniqueConstraint("task_id", "step_no", name="uq_agent_steps_task_step"),
    )

def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_tasks")
```

- [x] **Step 7: 更新既有迁移头断言**

四个文件里的 `"0017_s5_6"` 改为 `"0018_s6_2"`。

- [x] **Step 8: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_models_migration.py tests/test_answers_migration.py tests/test_papers_migration.py tests/test_report_migration.py tests/test_review_migration.py -q`
Expected: PASS

- [x] **Step 9: 真库迁移验证**

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head`
Expected: 输出 `0018_s6_2`；`\d agent_tasks`/`\d agent_steps` 列与约束齐全（可用 `scripts/check_services.py` 或 psql 复核）。

- [x] **Step 10: 提交**

```bash
git add docs/SCHEMA.md docs/API.md backend/app/models backend/alembic/versions/0018_s6_2.py \
  backend/tests/test_agent_models_migration.py backend/tests/test_*_migration.py
git commit -m "feat(s6-2): agent_tasks/agent_steps 表与迁移 0018"
```

---

### Task 2: 图引擎 + `demo` 任务类型

**Files:**
- Create: `backend/app/ai/agents/state.py`
- Create: `backend/app/ai/agents/engine.py`
- Create: `backend/app/ai/agents/tasks/__init__.py`
- Create: `backend/app/ai/agents/tasks/demo.py`
- Test: `backend/tests/test_agent_graph.py`
- Test: `backend/tests/test_agent_task_spec_demo.py`

**Interfaces:**
- Produces: `AgentState`（TypedDict）、`PlanStep`、`AgentStepLimitError`
- Produces: `RunContext(user, recorder, tool_invoker=invoke_tool, session=None, now=None)`、`StepRecorder` 协议、`AgentEngine(spec, ctx).run(state) -> AgentState`
- Produces: `AgentTaskSpec` 协议（`task_type/requires_confirm/validate_input/build_plan/finalize`）、`TASK_SPECS: dict[str, type[AgentTaskSpec]]`、`DemoTaskSpec`
- Produces: `new_state(...)`（初始状态）、`jsonable(value)`

- [x] **Step 1: 写图失败测试**

```python
"""S6-2 图引擎：3 步成功、重试、预算、步数、挂起/恢复。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.engine import AgentEngine, AgentStepLimitError, RunContext
from app.ai.agents.state import new_state
from app.ai.agents.tasks.demo import DemoTaskSpec
from app.core.exceptions import InvalidParamError


class MemoryRecorder:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.states: list[dict] = []

    def record(self, *, step_no, thought, status, state, tool_name=None,
               tool_input=None, tool_output=None, latency_ms=None):  # noqa: ANN001
        self.steps.append({
            "step_no": step_no, "thought": thought, "status": status,
            "tool_name": tool_name, "tool_input": tool_input,
            "tool_output": tool_output, "latency_ms": latency_ms,
        })
        self.states.append(dict(state))


def _ctx(recorder, invoker):  # noqa: ANN001
    return RunContext(
        user=SimpleNamespace(id=50), recorder=recorder, tool_invoker=invoker,
        session=None,
    )


def _state(steps, *, budget=20000, max_steps=12, confirm=False):  # noqa: ANN001
    spec = DemoTaskSpec({"steps": steps, "require_confirm": confirm})
    return spec, new_state(
        user_id=50, task_input={"steps": steps, "require_confirm": confirm},
        token_budget=budget, max_steps=max_steps,
    )


def _echo(name, ctx, payload):  # noqa: ANN001
    return {"tool": name, "payload": payload}


def test_three_step_demo_succeeds_with_complete_steps():
    recorder = MemoryRecorder()
    steps = [
        {"tool": "calculator", "input": {"expression": "1+1"}, "purpose": "算 1+1"},
        {"tool": "calculator", "input": {"expression": "2+2"}, "purpose": "算 2+2"},
        {"tool": "make_mindmap", "input": {"title": "函数"}, "purpose": "画导图"},
    ]
    spec, state = _state(steps)
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert final["status"] == "succeeded"
    assert final["result"]["summary"] == "完成 3 步"
    assert [s["tool_name"] for s in recorder.steps if s["tool_name"]] == [
        "calculator", "calculator", "make_mindmap"
    ]
    assert len(recorder.steps) == 8  # plan + act/observe*3 + finalize
    act_rows = [s for s in recorder.steps if s["tool_name"]]
    assert act_rows[0]["tool_input"] == {"expression": "1+1"}
    assert act_rows[0]["tool_output"]["payload"] == {"expression": "1+1"}
    assert act_rows[0]["latency_ms"] is not None
    assert final["artifacts"]["step_1"]["tool"] == "calculator"


def test_tool_failure_retries_twice_then_succeeds():
    recorder = MemoryRecorder()
    calls = {"n": 0}

    def flaky(name, ctx, payload):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] < 3:
            raise InvalidParamError("工具临时失败")
        return {"ok": True}

    spec, state = _state([{"tool": "calculator", "input": {}}])
    final = AgentEngine(spec, _ctx(recorder, flaky)).run(state)
    assert final["status"] == "succeeded"
    statuses = [s["status"] for s in recorder.steps]
    assert statuses.count("error") == 2 + 2  # 两次失败各 act+observe
    assert any("重试" in (s["thought"] or "") for s in recorder.steps)


def test_tool_failure_exhausts_retries():
    recorder = MemoryRecorder()

    def boom(name, ctx, payload):  # noqa: ANN001
        raise RuntimeError("boom")

    spec, state = _state([{"tool": "calculator", "input": {}}])
    final = AgentEngine(spec, _ctx(recorder, boom)).run(state)
    assert final["status"] == "failed"
    assert "重试" in final["error"]


def test_token_budget_exceeded_stops_before_tools():
    recorder = MemoryRecorder()
    spec, state = _state([{"tool": "calculator", "input": {}}], budget=100)
    state["token_cost"] = 100
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert final["status"] == "failed"
    assert "token 预算" in final["error"]
    assert [s["tool_name"] for s in recorder.steps if s["tool_name"]] == []


def test_max_steps_raises_limit_error():
    recorder = MemoryRecorder()
    spec, state = _state(
        [{"tool": "calculator", "input": {}}, {"tool": "calculator", "input": {}}],
        max_steps=2,
    )
    with pytest.raises(AgentStepLimitError):
        AgentEngine(spec, _ctx(recorder, _echo)).run(state)


def test_confirm_suspends_then_resume_approves():
    recorder = MemoryRecorder()
    steps = [{"tool": "calculator", "input": {"expression": "1+1"}}]
    spec, state = _state(steps, confirm=True)
    suspended = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    assert suspended["status"] == "waiting_confirm"
    assert recorder.steps[-1]["status"] == "waiting_confirm"
    assert len([s for s in recorder.steps if s["tool_name"]]) == 1

    suspended["confirm_decision"] = {"approved": True, "comment": None, "edits": None}
    suspended["resume_from"] = "confirm"
    suspended["status"] = "running"
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(suspended)
    assert final["status"] == "succeeded"
    assert recorder.steps[-1]["thought"] == "任务完成"
    assert len([s for s in recorder.steps if s["tool_name"]]) == 1  # 不重跑工具


def test_confirm_reject_fails():
    recorder = MemoryRecorder()
    spec, state = _state([{"tool": "calculator", "input": {}}], confirm=True)
    suspended = AgentEngine(spec, _ctx(recorder, _echo)).run(state)
    suspended["confirm_decision"] = {"approved": False, "comment": None, "edits": None}
    suspended["resume_from"] = "confirm"
    suspended["status"] = "running"
    final = AgentEngine(spec, _ctx(recorder, _echo)).run(suspended)
    assert final["status"] == "failed"
    assert final["error"] == "用户拒绝确认"
```

`test_agent_task_spec_demo.py`：

```python
from app.ai.agents.tasks.demo import DemoTaskSpec
from app.core.exceptions import InvalidParamError
import pytest


def test_demo_rejects_unknown_tool_and_empty_steps():
    with pytest.raises(InvalidParamError):
        DemoTaskSpec.validate_input({"steps": []})
    with pytest.raises(InvalidParamError):
        DemoTaskSpec.validate_input({"steps": [{"tool": "nope", "input": {}}]})


def test_demo_requires_confirm_and_plan():
    data = DemoTaskSpec.validate_input(
        {"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}],
         "require_confirm": True}
    )
    spec = DemoTaskSpec(data)
    assert spec.requires_confirm is True
    assert spec.build_plan({})[0]["tool"] == "calculator"
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_graph.py tests/test_agent_task_spec_demo.py -q`
Expected: FAIL（模块不存在）

- [x] **Step 3: 写 `state.py`**

- 常量：`STATUS_RUNNING/WAITING_CONFIRM/SUCCEEDED/FAILED`。
- `AgentState(TypedDict, total=False)` 字段与 spec §5.1 完全一致（含 `last_output`、`error`）。
- `PlanStep`（TypedDict：tool/input/purpose）。
- `new_state(*, user_id, task_input, token_budget, max_steps) -> AgentState`：填充空 plan/artifacts/citations、`current_index=0`、`retry_count=0`、`token_cost=0`、`step_count=0`、`status="running"`、`resume_from=None`。
- `jsonable(value)`：`json.loads(json.dumps(value, ensure_ascii=False, default=str))`；用于 `state_json`/步骤出参落库。

- [x] **Step 4: 写 `engine.py`**

关键签名：

```python
class StepRecorder(Protocol):
    def record(self, *, step_no: int, thought: str | None, status: str, state: AgentState,
               tool_name: str | None = None, tool_input: dict | None = None,
               tool_output: dict | None = None, latency_ms: int | None = None) -> None: ...


@dataclass
class RunContext:
    user: Any
    recorder: StepRecorder
    session: Any = None
    tool_invoker: Callable[[str, Any, dict], Any] = invoke_tool
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def invoke(self, tool: str, payload: dict) -> dict:
        out = self.tool_invoker(tool, ToolContext(session=self.session, user=self.user, now=self.now), payload)
        return out.model_dump(mode="json") if isinstance(out, BaseModel) else dict(out)


class AgentEngine:
    def __init__(self, spec: AgentTaskSpec, ctx: RunContext) -> None: ...
    def run(self, state: AgentState) -> AgentState:
        return self._build_graph().invoke(state)
```

- `_build_graph`：`StateGraph(AgentState)` + 六节点 + 边（spec §5.2）。
- 每个节点用 `_guard(state)` 包装：`step_count >= max_steps` → `AgentStepLimitError(max_steps)`。
- `_record(state, update, ...)`：先 `merged={**state,**update}`、`step_no=step_count+1`、写 `step_count` 到 merged/update，再 `ctx.recorder.record(..., state=merged)`。
- 节点实现按 spec §5.2 表：
  - `plan`：`resume_from` 非空直接返回 `{}`；否则 `spec.build_plan(state)`；预算命中写 `fatal_error`；记录 plan 行。
  - `act`：调 `ctx.invoke`，`perf_counter` 计时；异常捕获 `AppError`（message/code）与 `Exception`（固定「工具执行失败」+ logger.exception）；更新 `last_output/last_error`；记录 act 行。
  - `observe`：失败只记录 error 行并保留 `last_error`；成功把 `{tool,input,output}` 写入 `artifacts[f"step_{idx+1}"]`、`search_notes` 命中收集 `citations`、`current_index+1`、清 `last_error/last_output/retry_count`；检查预算；记录 observe 行。
  - `reflect`：`retry_count >= 2` → `fatal_error=f"工具连续失败已达重试上限：{last_error}"` 并记 error；否则 `retry_count+1`、清 `last_error`、记 ok。
  - `confirm`：无决策 → `status=waiting_confirm`、`need_human_confirm=True`、记 waiting；有决策 approved → `status=running`、记 ok；否则 `status=failed`、`fatal_error="用户拒绝确认"`、记 error。
  - `finalize`：失败 → `status=failed`、`error=fatal_error or "任务执行失败"`、`result` 保留 artifacts/citations、记 error；成功 → `result=spec.finalize(state)`、`status=succeeded`、记 ok。
- 路由函数按 spec §5.2；`confirm` 无决策时返回 `"end"` 映射到 `END`。

- [x] **Step 5: 写 `tasks/demo.py` 与注册表**

```python
class DemoInput(ToolInput):  # 或 BaseModel(extra="forbid")
    steps: list[DemoStep] = Field(min_length=1, max_length=5)
    require_confirm: bool = False
    token_budget: int | None = Field(default=None, ge=100)

class DemoStep(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    purpose: str | None = Field(default=None, max_length=200)

class DemoTaskSpec:
    task_type = "demo"
    def __init__(self, task_input: dict) -> None:
        self.task_input = task_input
        self.requires_confirm = bool(task_input.get("require_confirm"))
    @classmethod
    def validate_input(cls, raw: dict) -> dict:
        try: data = DemoInput.model_validate(raw)
        except ValidationError as exc:
            raise InvalidParamError(f"任务输入不合法：{exc.errors()[0]['msg']}") from exc
        for step in data.steps:
            if step.tool not in TOOLS:
                raise InvalidParamError(f"未知工具：{step.tool}")
        return data.model_dump()
    def build_plan(self, state) -> list[dict]:
        return [{"tool": s["tool"], "input": s["input"], "purpose": s.get("purpose") or f"调用 {s['tool']}"} for s in self.task_input["steps"]]
    def finalize(self, state) -> dict:
        return {"summary": f"完成 {len(state['plan'])} 步", "artifacts": state.get("artifacts", {}), "citations": state.get("citations", [])}

TASK_SPECS = {"demo": DemoTaskSpec}
```

`tasks/__init__.py` 导出 `TASK_SPECS`、`get_task_spec(name)`（未知返回 None）。

- [x] **Step 6: 跑图测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_graph.py tests/test_agent_task_spec_demo.py -q`
Expected: PASS

- [x] **Step 7: 提交**

```bash
git add backend/app/ai/agents backend/tests/test_agent_graph.py backend/tests/test_agent_task_spec_demo.py
git commit -m "feat(s6-2): LangGraph 状态机与 demo 任务类型"
```

---

### Task 3: Agent service（建任务/查询/确认/执行）+ ARQ handler

**Files:**
- Create: `backend/app/services/agent_service.py`
- Create: `backend/app/tasks/agent_run.py`
- Modify: `backend/app/tasks/__init__.py`
- Test: `backend/tests/test_agent_service.py`
- Test: `backend/tests/test_agent_task.py`

**Interfaces:**
- Produces: `TASK_RUN_AGENT = "agent.run"`
- Produces: `create_agent_task(session, *, owner, task_type, task_input, queue) -> AgentTask`
- Produces: `get_agent_task(session, *, task_id, viewer) -> tuple[AgentTask, list[AgentStep]]`
- Produces: `confirm_agent_task(session, *, task_id, viewer, decision, queue) -> AgentTask`
- Produces: `run_agent_task(session, agent_task_id) -> dict`
- Produces: `DbStepRecorder`

- [x] **Step 1: 写 service 失败测试**

```python
"""S6-2 Agent service：创建/查询/确认/入队失败与终态幂等。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError, NotFoundError
from app.models.agent_task import AgentTask
from app.models.user import User
from app.services import agent_service


class FakeSession:
    def __init__(self, task=None, user=None):  # noqa: ANN001
        self.task = task
        self.user = user
        self.added = []
        self.commits = 0

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)

    def commit(self):  # noqa: ANN001
        self.commits += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 71

    def refresh(self, obj):  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = 71

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is AgentTask and self.task and self.task.id == pk:
            return self.task
        if model is User:
            return self.user
        return None


class FakeQueue:
    def __init__(self, fail=False):  # noqa: ANN001
        self.calls = []
        self.fail = fail

    def enqueue(self, name, task_id):  # noqa: ANN001
        if self.fail:
            raise RuntimeError("redis down")
        self.calls.append((name, task_id))


def _owner(user_id=50):  # noqa: ANN001
    return SimpleNamespace(id=user_id, role="student")


def _task(status="pending", *, owner_id=50, state=None):  # noqa: ANN001
    task = AgentTask(
        user_id=owner_id, task_type="demo",
        input_json={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        status=status, state_json=state,
    )
    task.id = 71
    return task


def test_create_unknown_type_raises_422(monkeypatch):
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: None)
    with pytest.raises(InvalidParamError):
        agent_service.create_agent_task(
            FakeSession(), owner=_owner(), task_type="weekly_mindmap", task_input={}, queue=FakeQueue()
        )


def test_create_demo_enqueues(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: captured.update(k))
    session = FakeSession()
    task = agent_service.create_agent_task(
        session, owner=_owner(), task_type="demo",
        task_input={"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]},
        queue=FakeQueue(),
    )
    assert task.status == "pending"
    assert captured["name"] == agent_service.TASK_RUN_AGENT
    assert captured["payload"] == {"agent_task_id": 71}


def test_create_enqueue_failure_marks_failed(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("queue")
    monkeypatch.setattr(agent_service.task_service, "create_task", boom)
    task = _task()
    session = FakeSession(task)
    with pytest.raises(RuntimeError):
        agent_service.create_agent_task(
            session, owner=_owner(), task_type="demo",
            task_input={"steps": [{"tool": "calculator", "input": {}}]}, queue=FakeQueue()
        )


def test_get_other_users_task_403():
    with pytest.raises(ForbiddenError):
        agent_service.get_agent_task(FakeSession(_task()), task_id=71, viewer=_owner(99))


def test_confirm_requires_waiting_status():
    with pytest.raises(ConflictError):
        agent_service.confirm_agent_task(
            FakeSession(_task("running")), task_id=71, viewer=_owner(),
            decision={"approved": True}, queue=FakeQueue(),
        )


def test_confirm_writes_decision_and_requeues(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: captured.update(k))
    task = _task("waiting_confirm", state={"step_count": 9, "plan": [{"tool": "calculator"}]})
    session = FakeSession(task)
    agent_service.confirm_agent_task(
        session, task_id=71, viewer=_owner(), decision={"approved": True}, queue=FakeQueue()
    )
    assert task.status == "pending"
    assert task.state_json["resume_from"] == "confirm"
    assert task.state_json["confirm_decision"]["approved"] is True
    assert captured["payload"] == {"agent_task_id": 71}


def test_run_terminal_task_is_noop():
    task = _task("succeeded")
    assert agent_service.run_agent_task(FakeSession(task), 71) == {"status": "succeeded"}
```

`test_agent_task.py`：

```python
def test_agent_run_handler_returns_service_status(monkeypatch):
    from app.tasks import agent_run
    monkeypatch.setattr(agent_run, "run_agent_task", lambda session, task_id: {"status": "succeeded"})
    assert agent_run.agent_run_task(object(), {"agent_task_id": 7}) == {"status": "succeeded"}
```

> 注：`register` 在 import 时执行；测试模块名与 handler 名不要冲突。

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_service.py tests/test_agent_task.py -q`
Expected: FAIL

- [x] **Step 3: 实现 `agent_service.py`**

- 常量与状态：`TASK_RUN_AGENT = "agent.run"`；`TERMINAL = {succeeded, failed}`。
- `create_agent_task`：
  ```python
  spec_cls = TASK_SPECS.get(task_type)
  if spec_cls is None:
      raise InvalidParamError(f"任务类型尚未启用：{task_type}")
  validated = spec_cls.validate_input(task_input)
  task = AgentTask(user_id=owner.id, task_type=task_type, input_json=validated, status="pending")
  session.add(task); session.commit(); session.refresh(task)
  try:
      task_service.create_task(session, owner=owner, name=TASK_RUN_AGENT,
                               payload={"agent_task_id": task.id}, queue=queue)
  except Exception:
      task.status = "failed"; task.error = "任务入队失败"
      task.finished_at = datetime.now(timezone.utc); session.commit()
      raise
  return task
  ```
- `get_agent_task`：不存在 404；非本人 403；步骤 `select(AgentStep).where(task_id).order_by(step_no)`。
- `confirm_agent_task`：状态非 waiting_confirm → `ConflictError("当前状态不需要确认")`；`state=dict(task.state_json or {})`；写 `confirm_decision`（approved/comment/edits）、`resume_from="confirm"`、`need_human_confirm=False`；`task.status="pending"`、`task.error=None`、`task.finished_at=None`；commit；入队失败时恢复 `waiting_confirm` + 原 state/commit 并 raise。
- `run_agent_task`：
  1) 取 task；None → `{"status":"missing"}`；终态或 waiting_confirm → 原状态；
  2) 取 User（不存在 → failed）；
  3) `spec_cls = TASK_SPECS.get(...)`，未知 → failed；
  4) 状态：若有 `state_json` 且 status=running → 复用并 `resume_from="resume"`；否则 `new_state(...)`（`token_budget` 取 `input_json.token_budget` 或 settings，`max_steps=settings.agent_max_steps`）；
  5) `task.status="running"`、`started_at` 首次设置、commit；
  6) `recorder = DbStepRecorder(session, task)`；`AgentEngine(spec, RunContext(session=session,user=user,recorder=recorder)).run(state)`；
  7) 捕获 `AgentStepLimitError` → failed/error=f"超过最大步数 {max}"、finished；捕获其他异常 → logger.exception、rollback、重新取 task、failed/error="任务执行失败"、finished；返回 `{"status": task.status}`。
- `DbStepRecorder.record`：`session.add(AgentStep(... jsonable(...)))`；更新 task `steps_count/state_json/token_cost/status/result_json/error/finished_at`；`session.commit()`（允许 Agent handler 自行 commit，与 S2-8 parse worker 同一例外，需注释原因）。

- [x] **Step 4: 实现 ARQ handler**

```python
@register(TASK_RUN_AGENT)
def agent_run_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = int(payload.get("agent_task_id") or 0)
    if task_id <= 0:
        raise ValueError("payload 缺少 agent_task_id")
    return run_agent_task(session, task_id)
```

`tasks/__init__.py` 增加 `from app.tasks import agent_run as _agent_run` 与 `__all__` 项。

- [x] **Step 5: 跑测试 + 图回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_service.py tests/test_agent_task.py tests/test_agent_graph.py tests/test_task_registry.py -q`
Expected: PASS

- [x] **Step 6: 提交**

```bash
git add backend/app/services/agent_service.py backend/app/tasks backend/tests/test_agent_service.py \
  backend/tests/test_agent_task.py
git commit -m "feat(s6-2): Agent 任务 service 与 ARQ 执行入口"
```

---

### Task 4: Agent API（3 个接口）

**Files:**
- Create: `backend/app/schemas/agent.py`
- Create: `backend/app/api/v1/agent.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_agent_api.py`

**Interfaces:**
- Produces: `AgentTaskCreateIn`、`AgentConfirmIn`、`AgentTaskOut`、`AgentTaskDetailOut`、`AgentStepOut`
- Produces: `POST /api/v1/agent/tasks`（202）、`GET /api/v1/agent/tasks/{id}`、`POST /api/v1/agent/tasks/{id}/confirm`（202）

- [x] **Step 1: 写 API 失败测试**

```python
"""S6-2 Agent API：202/200、权限、409/422、Envelope。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.services import agent_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, user):  # noqa: ANN001
        self.user = user

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return None


class FakeQueue:
    def enqueue(self, name, task_id):  # noqa: ANN001
        return None


def _user(role="student"):  # noqa: ANN001
    user = User(username="agent_s62", nickname="agent", grade="高二", role=role, password_hash="x")
    user.id = 50
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(status="pending"):  # noqa: ANN001
    from app.models.agent_task import AgentTask
    task = AgentTask(user_id=50, task_type="demo", input_json={"steps": []}, status=status)
    task.id = 71
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 0
    task.token_cost = 0
    return task


def test_create_returns_202(monkeypatch):
    monkeypatch.setattr(agent_service, "create_agent_task", lambda *a, **k: _task())
    resp = _client(_user()).post("/api/v1/agent/tasks", json={"task_type": "demo", "input": {"steps": [{"tool": "calculator", "input": {"expression": "1+1"}}]}})
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"


def test_get_detail_returns_steps(monkeypatch):
    task = _task("waiting_confirm")
    step = type("Step", (), {"step_no": 1, "thought": "计划 1 步", "tool_name": None,
                             "tool_input_json": None, "tool_output_json": None,
                             "latency_ms": None, "status": "ok"})()
    monkeypatch.setattr(agent_service, "get_agent_task", lambda *a, **k: (task, [step]))
    resp = _client(_user()).get("/api/v1/agent/tasks/71")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "waiting_confirm"
    assert data["steps"][0]["step_no"] == 1


def test_confirm_returns_202(monkeypatch):
    monkeypatch.setattr(agent_service, "confirm_agent_task", lambda *a, **k: _task("pending"))
    resp = _client(_user()).post("/api/v1/agent/tasks/71/confirm", json={"approved": True})
    assert resp.status_code == 202


def test_teacher_forbidden():
    resp = _client(_user("teacher")).post("/api/v1/agent/tasks", json={"task_type": "demo", "input": {}})
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_invalid_payload_422():
    resp = _client(_user()).post("/api/v1/agent/tasks", json={"task_type": "demo"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_api.py -q`
Expected: FAIL（404 或导入失败）

- [x] **Step 3: 写 schemas 与路由**

- `AgentTaskCreateIn`：`task_type: str (1..50)`、`input: dict = Field(default_factory=dict)`。
- `AgentConfirmIn`：`approved: bool`、`comment: str|None(max_length=500)`、`edits: dict|None`。
- `AgentStepOut`：step_no/thought/tool_name/tool_input/tool_output/latency_ms/status。
- `AgentTaskOut`：id/task_type/status/steps_count/token_cost/error/created_at/started_at/finished_at。
- `AgentTaskDetailOut`：继承 + input/result/steps；`from_attributes` 不适用于 steps（手动映射 `tool_input_json→tool_input`）。
- 路由：
  ```python
  router = APIRouter(prefix="/agent", tags=["agent"])

  @router.post("/tasks", status_code=202, response_model=Envelope[AgentTaskOut])
  def create_task(payload: AgentTaskCreateIn, current_user=Depends(require_role("student")),
                  session=Depends(get_db), queue: TaskQueue = Depends(get_task_queue)):
      task = agent_service.create_agent_task(session, owner=current_user, task_type=payload.task_type,
                                             task_input=payload.input, queue=queue)
      return Envelope(trace_id=get_trace_id(), data=AgentTaskOut.model_validate(task))

  @router.get("/tasks/{task_id}", response_model=Envelope[AgentTaskDetailOut])
  def get_task(...): ...
  @router.post("/tasks/{task_id}/confirm", status_code=202, response_model=Envelope[AgentTaskOut])
  def confirm(...): ...
  ```
- `api/router.py` 导入并 `include_router(agent.router)`（放在 review/reports 附近即可）。

- [x] **Step 4: 跑 API 测试 + 全量回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_api.py tests/test_agent_service.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/app/schemas/agent.py backend/app/api/v1/agent.py backend/app/api/router.py \
  backend/tests/test_agent_api.py
git commit -m "feat(s6-2): Agent 任务三个 API"
```

---

### Task 5: 配置、文档、全量测试与真实 ARQ 验收

**Files:**
- Modify: `backend/requirements.txt`（加 `langgraph==1.2.22`）
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Create: `docs/AGENT_ENGINE.md`
- Modify: `docs/DECISIONS.md`（D-066）
- Modify: `docs/PROGRESS.md`
- Modify: `AGENTS.md` §9.6
- Create: `.sdd/s6-2/acceptance-evidence.md`

- [ ] **Step 1: 配置与依赖**

- `requirements.txt` 追加 `langgraph==1.2.22`（放在 Agent 段注释下）。
- `Settings` 加：
  ```python
  # --- Agent 状态机（S6-2）---
  agent_max_steps: int = Field(default=12, ge=1, le=50)
  agent_token_budget: int = Field(default=20000, ge=100)
  ```
- `.env.example` 追加：
  ```ini
  # --- S6-2 Agent 状态机 ---
  AGENT_MAX_STEPS=12
  AGENT_TOKEN_BUDGET=20000
  ```

- [ ] **Step 2: 写 `docs/AGENT_ENGINE.md`**

内容：图结构（Mermaid 或文本）、State 字段、六个节点职责、重试/预算/步数口径、`agent_steps` 列与状态、demo 输入示例、三个 API curl 示例、挂起/恢复时序、已知边界（token 统计、崩溃重跑、edits 不执行）。

- [ ] **Step 3: 追加 D-066、更新 PROGRESS/AGENTS**

- D-066：记录 LangGraph 版本与依赖、demo 范围、`state_json`/`created_at` 增列、步数/预算/重试口径、ARQ 异步确认、验收数字与边界。
- PROGRESS：阶段 6 加 S6-2 完成、任务清单 `[x]`、下一步 S6-3、验收数字。
- AGENTS §9.6 追加：
  ```
  - Agent 状态机样例：backend/app/ai/agents/{state,engine}.py + tasks/demo.py + services/agent_service.py + tasks/agent_run.py + api/v1/agent.py（LangGraph StateGraph 六节点；每节点写 agent_steps + state_json；挂起/确认恢复；见 D-066）
  ```

- [ ] **Step 4: 全量测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: 全绿；记录精确数字（S6-1 基线 1514 passed, 5 warnings）。

- [ ] **Step 5: 真实 ARQ 验收**

1) `cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head`
2) 启动 Redis（若未启动）、ARQ worker：
   ```bash
   ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
   ```
   以 `run_in_background` 启动并保留 job id。
3) 启动 uvicorn（8001 端口）：
   ```bash
   ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
   ```
4) 真实 HTTP：
   - 用真实 student token（同既有验收方式生成）POST demo 3 步（calculator / make_mindmap / list_mistakes）→ 202；轮询 GET 到 `succeeded`；断言 8 条 steps、act 行 tool/input/output/latency 齐全、result 有 3 个 artifacts。
   - POST demo 2 步 `require_confirm=true` → 轮询 `waiting_confirm`；POST confirm `{approved:true}` → 202 → 轮询 `succeeded`；断言前 2 步工具只执行一次，新增 confirm/finalize 行。
   - POST confirm `{approved:false}`（新任务）→ 最终 `failed` + `error="用户拒绝确认"`。
   - 越权 GET/confirm 403、非 waiting_confirm 409、未知类型 422。
5) 记录每步耗时、tok（demo 为 0）、失败与修复。

- [ ] **Step 6: 写验收证据**

`.sdd/s6-2/acceptance-evidence.md`：pytest 数字、迁移 head、真实 HTTP 请求/响应摘要、步骤行数、挂起/恢复时序、未做项。

- [ ] **Step 7: 提交**

```bash
git add backend/requirements.txt backend/app/core/config.py .env.example docs AGENTS.md
git commit -m "docs(s6-2): 状态机文档、D-066 与验收记录"
```

---

## Self-Review

**Spec coverage：**

| spec 章节 | 对应 Task |
|---|---|
| SCHEMA/API/枚举/模型/迁移 | Task 1 |
| State、六节点、路由、重试/预算/步数 | Task 2 |
| 挂起/恢复（state_json） | Task 2（引擎）+ Task 3（service 写入决策） |
| demo 任务类型 | Task 2 |
| service/ARQ handler | Task 3 |
| 三个 API | Task 4 |
| 配置/依赖/文档/真实验收 | Task 5 |

**Placeholder scan：** 无 TBD/TODO；每个实现步骤给出签名、关键分支或完整小函数。

**Type consistency：** `AgentState` 字段（含 `last_output/error`）、`RunContext(user,recorder,session,tool_invoker,now)`、`StepRecorder.record(...)`、`AgentTaskSpec` 四成员、`TASK_RUN_AGENT="agent.run"`、`TASK_SPECS` 在 Task 2/3/4 一致。

**已知取舍：** 步数上限按行数计，demo 限制 1–5 步；确认时建议 ≤4 步（confirm+finalize 另占 2 行）。token 预算在 S6-2 只统计显式 `add_tokens`，真实任务接入时补。