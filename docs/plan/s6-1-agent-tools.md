# S6-1 Agent 工具集（11 个工具 + schema 导出）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `backend/app/ai/agents/tools/` 交付方案 §6.7 的 11 个工具、统一注册表与调用入口、OpenAI function-calling schema 导出和独立 CLI；不写库、不改 API/表结构。

**Architecture:** 工具层位于 `app.ai.agents.tools`，每个工具一个模块：Pydantic 入参/出参 + handler，统一登记到 `registry.TOOLS`。工具只读，复用 `retrieval_service / note_service / graph_service / mistake_service / mastery_service / question_service / review_service / paper_plan_service / ai.gen`；缺的批量查询只在既有 service 做向后兼容增量。schema 由 `schema_export.build_export_payload()` 生成，脚本落到 `backend/data/agent_tools.json`。

**Tech Stack:** Python 3.11、Pydantic v2、SQLAlchemy 2.0、Jinja2、pytest、FastAPI 项目既有异常/分页设施。

**Spec:** `docs/spec/s6-1-agent-tools.md`

## Global Constraints

- 11 个工具名与方案 §6.7 完全一致：`search_notes/list_notes/get_kp_subgraph/list_mistakes/get_mastery/search_questions/generate_questions/make_mindmap/create_review_plan/export_paper_pdf/calculator`。
- 工具只读：不 `commit`、不 `rollback`、不写 `questions`/`review_items`/`agent_*`；`generate_questions`/`create_review_plan` 只返回草稿/建议。
- 入参模型 `extra="forbid"`，`str_strip_whitespace=True`；所有数量上限按 spec，超限 422。
- 只查 `ctx.user.id` 的数据；题库是公共语料但工具不返回答案。
- 外部 LLM 在 pytest 中必须 mock；测试不连库、不发网络。
- 不新增依赖、不加迁移、不改 `API.md`/`SCHEMA.md`；`generate_questions` 复用 `scene="gen"`。
- 先红后绿；每个 Task 结束跑该 Task 的测试并提交 Conventional Commit（含 `s6-1`）。
- 新代码先照锚点：`services/retrieval_service.py`（薄编排）、`ai/gen/variant_generator.py`（严格 JSON + 重试）、`schemas/*`（Pydantic v2）。

---

### Task 1: 工具基座 + 纯函数工具（calculator / make_mindmap）

**Files:**
- Create: `backend/app/ai/agents/__init__.py`（空文件，声明包）
- Create: `backend/app/ai/agents/tools/__init__.py`
- Create: `backend/app/ai/agents/tools/base.py`
- Create: `backend/app/ai/agents/tools/calculator.py`
- Create: `backend/app/ai/agents/tools/make_mindmap.py`
- Create: `backend/app/ai/agents/tools/registry.py`
- Test: `backend/tests/test_agent_tool_calculator.py`
- Test: `backend/tests/test_agent_tool_make_mindmap.py`
- Test: `backend/tests/test_agent_tools_registry.py`（本 Task 只断言已登记 2 个工具）

**Interfaces:**
- Produces: `ToolContext(session, user, now)`、`ToolInput`、`ToolOutput`、`ToolSpec`、`ToolInputError`、`ToolExecutionError`、`invoke_tool(name, ctx, payload) -> ToolOutput`、`TOOLS: dict[str, ToolSpec]`、`TOOL_ORDER: list[str]`
- Produces: `calculator.evaluate_expression(expression) -> CalculatorOut`；`make_mindmap.build_mindmap(title, nodes, edges) -> MindmapOut`
- 本 Task 结束后 `TOOL_ORDER == ["make_mindmap", "calculator"]`（按方案顺序占位，Task 3/4/5 补齐并最终重排为方案原序）。

- [x] **Step 1: 写 calculator 失败测试**

```python
"""S6-1 calculator：AST 白名单求值。"""
from __future__ import annotations

import pytest

from app.ai.agents.tools import calculator
from app.core.exceptions import InvalidParamError


def test_calculator_arithmetic_precedence_and_parens():
    out = calculator.evaluate_expression("2 + 3 * (4 - 1)")
    assert out.value == pytest.approx(11)
    assert out.exact is True


def test_calculator_supports_floor_mod_power_and_unary():
    assert calculator.evaluate_expression("-7 // 2").value == -4
    assert calculator.evaluate_expression("2 ** 10").value == 1024
    assert calculator.evaluate_expression("7 % 4").value == 3


def test_calculator_returns_text_with_twelve_significant_digits():
    out = calculator.evaluate_expression("1 / 3")
    assert out.value == pytest.approx(1 / 3)
    assert out.text == "0.333333333333"


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "sqrt(4)", "x + 1", "1 if 1 else 2", "'a' + 'b'", "True + 1", "1j + 1"],
)
def test_calculator_rejects_non_whitelisted_nodes(expression):
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression(expression)


def test_calculator_rejects_division_by_zero_and_overflow():
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression("1 / 0")
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression("9 ** 101")
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tool_calculator.py -q`
Expected: FAIL（`ModuleNotFoundError: app.ai.agents.tools` 或 `AttributeError: evaluate_expression`）

- [x] **Step 3: 实现 `base.py` 与 `calculator.py`**

`base.py` 关键内容：

```python
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import CODE_INTERNAL, AppError, InvalidParamError, NotFoundError
from app.models.user import User

logger = logging.getLogger(__name__)


class ToolInputError(InvalidParamError):
    def __init__(self, message: str = "工具参数不合法") -> None:
        super().__init__(message)


class ToolExecutionError(AppError):
    def __init__(self, message: str = "工具执行失败") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    session: Session
    user: User
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    handler: Callable[[ToolContext, Any], ToolOutput]
    write: bool = False


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    message = str(error.get("msg", "参数不合法")).removeprefix("Value error, ").strip()
    return message or "参数不合法"


def invoke_tool(name: str, ctx: ToolContext, payload: dict[str, Any]) -> ToolOutput:
    from app.ai.agents.tools.registry import TOOLS

    spec = TOOLS.get(name)
    if spec is None:
        raise NotFoundError("工具不存在")
    try:
        data = spec.input_model.model_validate(payload)
    except ValidationError as exc:
        raise ToolInputError(f"工具参数不合法：{_first_error(exc)}") from exc
    try:
        return spec.handler(ctx, data)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - Agent 调用点需要统一失败语义
        logger.exception("agent_tool_failed tool=%s", name)
        raise ToolExecutionError(f"工具 {name} 执行失败") from exc
```

`calculator.py` 关键内容：

```python
from __future__ import annotations

import ast
import math
from typing import Literal

from pydantic import Field

from app.ai.agents.tools.base import (
    ToolContext,
    ToolInput,
    ToolOutput,
    ToolSpec,
)
from app.core.exceptions import InvalidParamError

MAX_LENGTH = 200
MAX_EXPONENT = 100
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


class CalculatorIn(ToolInput):
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)


class CalculatorOut(ToolOutput):
    expression: str
    value: float
    text: str
    exact: bool


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise InvalidParamError("只支持数字算式")
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left, right = _eval(node.left), _eval(node.right)
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return float(left // right)
            if isinstance(node.op, ast.Mod):
                return float(left % right)
            if abs(right) > MAX_EXPONENT:
                raise InvalidParamError("乘方指数过大")
            return float(left**right)
        except ZeroDivisionError as exc:
            raise InvalidParamError("不能除以 0") from exc
        except OverflowError as exc:
            raise InvalidParamError("计算结果超出范围") from exc
    raise InvalidParamError("只支持四则、整除、取模与乘方")


def evaluate_expression(expression: str) -> CalculatorOut:
    clean = expression.strip()
    if not clean:
        raise InvalidParamError("expression 不能为空")
    try:
        tree = ast.parse(clean, mode="eval")
    except SyntaxError as exc:
        raise InvalidParamError("算式格式不正确") from exc
    value = _eval(tree)
    if not math.isfinite(value):
        raise InvalidParamError("计算结果超出范围")
    exact = float(value).is_integer()
    return CalculatorOut(
        expression=clean,
        value=value,
        text=format(value, ".12g"),
        exact=exact,
    )


def _handler(ctx: ToolContext, data: CalculatorIn) -> CalculatorOut:
    return evaluate_expression(data.expression)


SPEC = ToolSpec(
    name="calculator",
    description=(
        "用途：对算术表达式求值，避免心算错误。"
        "参数 expression 只支持数字、括号、+ - * / // % ** 与一元正负号，不接受变量或函数。"
        "返回 value（浮点）、text（12 位有效数字）与 exact（是否整数）。"
    ),
    input_model=CalculatorIn,
    output_model=CalculatorOut,
    handler=_handler,
)
```

- [x] **Step 4: 运行 calculator 测试**

Run: `cd backend && python -m pytest tests/test_agent_tool_calculator.py -q`
Expected: PASS（7 passed）

- [x] **Step 5: 写 make_mindmap 失败测试**

```python
"""S6-1 make_mindmap：树/图两种 Mermaid 输出与纯文本降级。"""
from __future__ import annotations

from app.ai.agents.tools.make_mindmap import MindmapNode, build_mindmap


def _node(node_id: str, name: str, parent_id: str | None = None) -> MindmapNode:
    return MindmapNode(id=node_id, name=name, parent_id=parent_id)


def test_mindmap_builds_tree_from_parent_ids():
    out = build_mindmap(
        "上周函数",
        [_node("1", "函数"), _node("2", "定义域", "1"), _node("3", "值域", "1")],
        [],
    )
    assert out.mode == "mindmap"
    assert out.mermaid.splitlines()[0] == "mindmap"
    assert "root((上周函数))" in out.mermaid
    assert "定义域" in out.mermaid and "值域" in out.mermaid
    assert "- 函数" in out.fallback_text


def test_mindmap_falls_back_to_graph_on_cycle():
    nodes = [_node("a", "A", "b"), _node("b", "B", "a")]
    out = build_mindmap("环", nodes, [])
    assert out.mode == "graph"
    assert out.mermaid.startswith("graph TD")
    assert "A" in out.mermaid and "B" in out.mermaid


def test_mindmap_uses_edges_when_parent_missing():
    nodes = [MindmapNode(id="a", name="A"), MindmapNode(id="b", name="B")]
    out = build_mindmap("边", nodes, [{"src": "a", "dst": "b", "relation": "contains"}])
    assert out.mode == "mindmap"
    assert out.node_count == 2


def test_mindmap_sanitizes_labels_and_truncates():
    name = "函数(定义域)[值域]\n第二行" + "长" * 50
    out = build_mindmap("标题(测试)", [_node("1", name)], [])
    assert "\\n" not in out.mermaid
    assert "（" in out.mermaid  # 半角括号转全角，避免 Mermaid 语法冲突
    assert out.truncated is True
    assert out.node_count == 1


def test_mindmap_caps_nodes_at_80():
    nodes = [_node(str(i), f"节点{i}") for i in range(90)]
    out = build_mindmap("大图", nodes, [])
    assert out.node_count == 80
    assert out.truncated is True
```

- [x] **Step 6: 运行并确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tool_make_mindmap.py -q`
Expected: FAIL（`ModuleNotFoundError` / `build_mindmap` 未定义）

- [x] **Step 7: 实现 `make_mindmap.py`**

要点（完整写出关键分支，不要留 TODO）：

- `MindmapNode(BaseModel)`：`id: str|int` 归一为 `str`；`name: str`（1–80）；`parent_id: str|int|None`。
- `MindmapEdge(BaseModel)`：`src/dst` 归一 `str`；`relation: str|None`。
- `MindmapOut(ToolOutput)`：`mermaid`、`fallback_text`、`node_count`、`edge_count`、`truncated`、`mode: Literal["mindmap","graph"]`。
- `build_mindmap(title, nodes, edges)`：
  1) 去重 id（保留首次出现）、截到 80 个；
  2) `parent_map`：优先每个节点自带 `parent_id`；若父不在集合内则忽略；
  3) 若没有任何父子关系，用 `edges` 中 `relation == "contains"`（没有则取全部边）按顺序建父子；
  4) 校验：每个节点至多一个父、无环、恰有根；不满足 → `mode="graph"`；
  5) `mindmap`：标题节点 `root((净化标题))`，DFS 前缀 2 空格递增；`graph`：`graph TD` + `n{index}["净化名"] --> n{index2}["净化名"]`（节点无标签用 id 显示名）；
  6) `fallback_text`：树是 `- 根` + 两空格缩进子级；图是 `A --> B` 列表；
  7) 净化：`\r\n`→空格；`()[]{}<>`→全角；去首尾空白；截 40 字。
- `SPEC` 描述写清「什么时候用（生成导图）、参数（节点/边/标题）、返回（Mermaid + 纯文本降级）」。

- [x] **Step 8: 运行 make_mindmap 测试**

Run: `cd backend && python -m pytest tests/test_agent_tool_make_mindmap.py -q`
Expected: PASS

- [x] **Step 9: 写 registry 基础测试**

```python
"""S6-1 工具注册表：本 Task 先覆盖基座契约。"""
from __future__ import annotations

import pytest

from app.ai.agents.tools.base import (
    ToolContext,
    ToolExecutionError,
    ToolInputError,
    invoke_tool,
)
from app.ai.agents.tools.registry import TOOL_ORDER, TOOLS


class _FakeSession:
    pass


class _User:
    id = 50
    role = "student"


def _ctx() -> ToolContext:
    return ToolContext(session=_FakeSession(), user=_User())  # type: ignore[arg-type]


def test_registry_starts_with_two_pure_tools():
    assert TOOL_ORDER == ["make_mindmap", "calculator"]
    assert set(TOOLS) == set(TOOL_ORDER)


def test_invoke_unknown_tool_raises_404():
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        invoke_tool("nope", _ctx(), {})


def test_invoke_invalid_input_raises_422():
    with pytest.raises(ToolInputError):
        invoke_tool("calculator", _ctx(), {"expression": ""})


def test_invoke_wraps_unexpected_error():
    spec = TOOLS["calculator"]
    original = spec.handler
    TOOLS["calculator"] = type(spec)(
        **{**spec.__dict__, "handler": lambda ctx, data: (_ for _ in ()).throw(RuntimeError("boom"))}
    )
    try:
        with pytest.raises(ToolExecutionError):
            invoke_tool("calculator", _ctx(), {"expression": "1+1"})
    finally:
        TOOLS["calculator"] = original
```

> 若 `ToolSpec` 用 `dataclasses.replace` 更简洁，可改写：`import dataclasses; TOOLS["calculator"] = dataclasses.replace(spec, handler=...)`。

- [x] **Step 10: 运行 registry 测试**

Run: `cd backend && python -m pytest tests/test_agent_tools_registry.py -q`
Expected: PASS

- [x] **Step 11: 提交**

```bash
git add backend/app/ai/agents backend/tests/test_agent_tool_calculator.py \
  backend/tests/test_agent_tool_make_mindmap.py backend/tests/test_agent_tools_registry.py
git commit -m "feat(s6-1): 工具基座与 calculator/make_mindmap"
```

---

### Task 2: 服务层最小增量（mastery_details / QuestionFilters / MistakeFilters）

**Files:**
- Modify: `backend/app/services/mastery_service.py`（文件末尾加 `KpMasteryState` + `mastery_details`）
- Modify: `backend/app/services/question_service.py:680-732`（`QuestionFilters` 与 `build_questions_query`）
- Modify: `backend/app/services/mistake_service.py:71-80,529-567`（`MistakeFilters` 与 `build_mistakes_query`）
- Test: `backend/tests/test_agent_tools_service_support.py`

**Interfaces:**
- Produces: `mastery_service.KpMasteryState`（frozen dataclass：`kp_id:int, kp_name:str, subject_id:int, exam_weight:float|None, mastery_t:float|None, assessed:bool, attempts:int, stability:float, last_practice_at:datetime|None, due_at:datetime|None`）
- Produces: `mastery_service.mastery_details(session, *, user_id: int, kp_ids: Sequence[int], now: datetime|None = None) -> list[KpMasteryState]`（按输入 id 顺序返回命中的知识点；不存在的 id 不返回）
- Produces: `QuestionFilters(kp_ids: list[int]|None=None, difficulty: int|None=None, exclude_user_id: int|None=None, exclude_done_since: datetime|None=None)`
- Produces: `MistakeFilters(kp_ids: list[int]|None=None)`

- [ ] **Step 1: 写 service 增量失败测试**

```python
"""S6-1 工具所需的 service 增量：可编译 SQL + 掌握度批量折算。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from app.services import mastery_service, mistake_service, question_service


def _sql(stmt) -> str:  # noqa: ANN001
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_question_filters_new_fields_compile_into_sql():
    stmt = question_service.build_questions_query(
        filters=question_service.QuestionFilters(
            kp_ids=[101, 102],
            difficulty=3,
            exclude_user_id=50,
            exclude_done_since=datetime(2026, 11, 3, tzinfo=timezone.utc),
        )
    )
    sql = _sql(stmt)
    assert "question_kps.kp_id IN" in sql
    assert "questions.difficulty =" in sql
    assert "NOT (EXISTS" in sql
    assert "mistakes.user_id =" in sql


def test_question_filters_default_sql_unchanged():
    stmt = question_service.build_questions_query(filters=question_service.QuestionFilters())
    sql = _sql(stmt)
    assert "mistakes" not in sql
    assert "question_kps" not in sql


def test_mistake_filters_kp_ids_compiles_or_exists():
    stmt = mistake_service.build_mistakes_query(
        user_id=50, filters=mistake_service.MistakeFilters(kp_ids=[101, 102])
    )
    sql = _sql(stmt)
    assert "question_kps.kp_id IN" in sql
    assert "mistake_analyses.kp_ids" in sql


def test_mastery_details_marks_assessed_and_missing(monkeypatch):
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    class _Rows:
        def __init__(self, rows):  # noqa: ANN001
            self._rows = rows

        def all(self):  # noqa: ANN201
            return self._rows

    class _Session:
        def __init__(self):  # noqa: ANN001
            self.calls = 0

        def execute(self, stmt):  # noqa: ANN001, ANN201
            self.calls += 1
            if self.calls == 1:
                return _Rows([(101, "函数", 7, None), (102, "定义域", 7, 0.8)])
            return _Rows([(101, 0.4, 2.0, now)])

    states = mastery_service.mastery_details(
        _Session(), user_id=50, kp_ids=[101, 102, 999], now=now
    )
    assert [state.kp_id for state in states] == [101, 102]
    assert states[0].assessed is True
    assert states[0].mastery_t == 0.4
    assert states[1].assessed is False
    assert states[1].mastery_t is None
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tools_service_support.py -q`
Expected: FAIL（字段/函数不存在）

- [ ] **Step 3: 实现 `mastery_details`**

在 `mastery_service.py` 末尾追加：

```python
@dataclass(frozen=True)
class KpMasteryState:
    kp_id: int
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery_t: float | None
    assessed: bool
    attempts: int
    stability: float
    last_practice_at: datetime | None
    due_at: datetime | None


def mastery_details(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    now: datetime | None = None,
) -> list[KpMasteryState]:
    """批量取知识点 + 本人掌握度；无掌握度行的知识点 assessed=False。

    两条 IN 查询（知识点、掌握度），禁止逐 id 查库；顺序按入参 id 首次出现。
    """
    from app.models.knowledge_point import KnowledgePoint
    from app.models.mastery import Mastery

    order = list(dict.fromkeys(int(kp_id) for kp_id in kp_ids))
    if not order:
        return []
    kp_rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        ).where(KnowledgePoint.id.in_(order))
    ).all()
    kp_map = {
        int(row[0]): (str(row[1]), int(row[2]), float(row[3]) if row[3] is not None else None)
        for row in kp_rows
    }
    mastery_rows = session.execute(
        select(
            Mastery.kp_id,
            Mastery.mastery,
            Mastery.stability,
            Mastery.last_practice_at,
            Mastery.attempts,
            Mastery.due_at,
        ).where(Mastery.user_id == user_id, Mastery.kp_id.in_(order))
    ).all()
    mastery_map = {int(row[0]): row for row in mastery_rows}
    moment = now or datetime.now(timezone.utc)
    states: list[KpMasteryState] = []
    for kp_id in order:
        if kp_id not in kp_map:
            continue
        name, subject_id, exam_weight = kp_map[kp_id]
        row = mastery_map.get(kp_id)
        if row is None:
            states.append(
                KpMasteryState(
                    kp_id=kp_id,
                    kp_name=name,
                    subject_id=subject_id,
                    exam_weight=exam_weight,
                    mastery_t=None,
                    assessed=False,
                    attempts=0,
                    stability=1.0,
                    last_practice_at=None,
                    due_at=None,
                )
            )
            continue
        _, mastery, stability, last_practice_at, attempts, due_at = row
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (moment - last_practice_at).total_seconds() / 86400.0)
        states.append(
            KpMasteryState(
                kp_id=kp_id,
                kp_name=name,
                subject_id=subject_id,
                exam_weight=exam_weight,
                mastery_t=decayed_mastery(float(mastery), float(stability), days=days),
                assessed=True,
                attempts=int(attempts),
                stability=float(stability),
                last_practice_at=last_practice_at,
                due_at=due_at,
            )
        )
    return states
```

- [ ] **Step 4: 实现 `QuestionFilters` / `build_questions_query` 增量**

`QuestionFilters` 追加字段；`build_questions_query` 在 `kp_id` 分支后追加：

```python
    if filters.kp_ids:
        stmt = stmt.where(
            exists().where(
                QuestionKp.question_id == Question.id,
                QuestionKp.kp_id.in_(filters.kp_ids),
            )
        )
    if filters.difficulty is not None:
        stmt = stmt.where(Question.difficulty == filters.difficulty)
    if filters.exclude_user_id is not None and filters.exclude_done_since is not None:
        from app.models.mistake import Mistake

        done_since = exists().where(
            Mistake.user_id == filters.exclude_user_id,
            Mistake.question_id == Question.id,
            func.greatest(Mistake.last_review_at, Mistake.created_at)
            >= filters.exclude_done_since,
        )
        stmt = stmt.where(~done_since)
```

并在文件头补 `from sqlalchemy import func`（若已 import select/exists，补齐）。

- [ ] **Step 5: 实现 `MistakeFilters.kp_ids`**

```python
    if filters.kp_ids:
        conditions = [
            exists().where(
                QuestionKp.question_id == Mistake.question_id,
                QuestionKp.kp_id == int(kp_id),
            )
            for kp_id in filters.kp_ids
        ]
        conditions.extend(
            exists().where(MistakeAnalysis.mistake_id == Mistake.id).where(
                MistakeAnalysis.kp_ids.contains([int(kp_id)])
            )
            for kp_id in filters.kp_ids
        )
        stmt = stmt.where(or_(*conditions))
```

文件头补 `from sqlalchemy import or_`（若未导入）。

- [ ] **Step 6: 跑新增测试 + 既有 service/API 回归**

Run: `cd backend && python -m pytest tests/test_agent_tools_service_support.py tests/test_question_service.py tests/test_mistakes_api.py tests/test_mastery_service.py -q`
Expected: PASS（既有测试不改一行仍绿）

- [ ] **Step 7: 提交**

```bash
git add backend/app/services backend/tests/test_agent_tools_service_support.py
git commit -m "feat(s6-1): 工具所需 service 增量（批量掌握度/题目与错题过滤）"
```

---

### Task 3: 只读工具（search_notes / list_notes / get_kp_subgraph / list_mistakes / get_mastery / search_questions）

**Files:**
- Create: `backend/app/ai/agents/tools/search_notes.py`
- Create: `backend/app/ai/agents/tools/list_notes.py`
- Create: `backend/app/ai/agents/tools/get_kp_subgraph.py`
- Create: `backend/app/ai/agents/tools/list_mistakes.py`
- Create: `backend/app/ai/agents/tools/get_mastery.py`
- Create: `backend/app/ai/agents/tools/search_questions.py`
- Modify: `backend/app/ai/agents/tools/registry.py`（登记 6 个；顺序：search_notes, list_notes, get_kp_subgraph, list_mistakes, get_mastery, search_questions, make_mindmap, calculator）
- Test: `backend/tests/test_agent_tool_search_notes.py`
- Test: `backend/tests/test_agent_tool_list_notes.py`
- Test: `backend/tests/test_agent_tool_get_kp_subgraph.py`
- Test: `backend/tests/test_agent_tool_list_mistakes.py`
- Test: `backend/tests/test_agent_tool_get_mastery.py`
- Test: `backend/tests/test_agent_tool_search_questions.py`

**Interfaces:**
- Consumes: Task 1 的 `ToolContext/ToolInput/ToolOutput/ToolSpec`；Task 2 的 `mastery_details`、`QuestionFilters` 新字段、`MistakeFilters.kp_ids`
- Produces（全部 handler 只返回 output，不写库）：
  - `search_notes.search_notes(ctx, data) -> SearchNotesOut`
  - `list_notes.list_notes(ctx, data) -> ListNotesOut`
  - `get_kp_subgraph.get_kp_subgraph(ctx, data) -> KpSubgraphOut`
  - `list_mistakes.list_mistakes(ctx, data) -> ListMistakesOut`
  - `get_mastery.get_mastery(ctx, data) -> GetMasteryOut`
  - `search_questions.search_questions(ctx, data) -> SearchQuestionsOut`

- [ ] **Step 1: 写 6 个工具的失败测试（只列关键断言）**

`test_agent_tool_search_notes.py`：

```python
from types import SimpleNamespace
import pytest
from app.ai.agents.tools import search_notes as tool
from app.ai.agents.tools.base import ToolContext
from app.core.exceptions import InvalidParamError
from app.schemas.retrieval import RetrievalHit, RetrievalSearchResponse


def _hit() -> RetrievalHit:
    return RetrievalHit(
        chunk_id=1, note_id=2, note_title="函数笔记", chunk_index=0,
        chunk_type="note", content="长" * 1500, snippet="长…", rrf_score=0.9,
    )


def test_search_notes_maps_hits_and_truncates(monkeypatch):
    captured = {}

    def fake_search(session, *, user_id, query, top_k, retrieval, scope, debug):  # noqa: ANN001
        captured.update(user_id=user_id, query=query, top_k=top_k, retrieval=retrieval, debug=debug)
        return RetrievalSearchResponse(
            query=query, top_k=top_k, rerank=False, elapsed_ms=12, embedding_ms=8,
            hits=[_hit()],
        )

    monkeypatch.setattr(tool, "search_chunks", fake_search)
    ctx = ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]
    out = tool.search_notes(ctx, tool.SearchNotesIn(query="函数", top_k=3))
    assert captured["user_id"] == 50 and captured["debug"] is False
    assert out.hit_count == 1
    assert out.hits[0].truncated is True
    assert len(out.hits[0].content) == 1200


def test_search_notes_rejects_empty_query():
    with pytest.raises(InvalidParamError):
        tool.SearchNotesIn(query="")
```

`test_agent_tool_list_notes.py`：

```python
def test_list_notes_passes_date_window_and_converts_end_inclusive(monkeypatch):
    captured = {}

    def fake_list(session, *, owner, params, sorting, **kwargs):  # noqa: ANN001
        captured.update(owner_id=owner.id, page_size=params.page_size, **kwargs)
        from app.schemas.common import PageData
        return PageData(items=[], total=0, page=1, page_size=params.page_size)

    monkeypatch.setattr(tool, "list_notes_service", fake_list)
    ctx = ...
    out = tool.list_notes(ctx, tool.ListNotesIn(start_date=date(2026, 11, 10), end_date=date(2026, 11, 16), limit=5))
    assert captured["created_from"] == datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert captured["created_to"].date() == date(2026, 11, 16)
    assert out.total == 0
```

`test_agent_tool_get_kp_subgraph.py`：构造 `GraphSnapshotOut`（3 节点 2 边），断言 depth=1 含中心+1 跳、depth=2 含全部；中心不存在 → `NotFoundError`；输出按 id 升序。

`test_agent_tool_list_mistakes.py`：fake `list_mistakes_service` 返回 `PageData[MistakeSummaryOut]`，断言 `MistakeFilters.kp_ids/status` 透传、输出字段映射、不返回答案。

`test_agent_tool_get_mastery.py`：monkeypatch `mastery_service.mastery_details` 返回两状态，断言 `assessed_count/unassessed_kp_ids/missing_kp_ids` 与 `mastery_t` 原样。

`test_agent_tool_search_questions.py`：fake `list_questions_service` 返回两题（一 verified=False、一 True），断言 `exclude_done_since` 等于 `ctx.now - 14 天`、输出 verified 优先、`answer_md` 不出现在字段里、stem 截 2000。

- [ ] **Step 2: 运行 6 个测试文件确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tool_search_notes.py tests/test_agent_tool_list_notes.py tests/test_agent_tool_get_kp_subgraph.py tests/test_agent_tool_list_mistakes.py tests/test_agent_tool_get_mastery.py tests/test_agent_tool_search_questions.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `search_notes.py`**

- `SearchNotesIn` 字段按 spec 5.1；`model_validator` 校验 `end_date >= start_date`。
- 导入 `from app.services.retrieval_service import search_chunks`（测试 monkeypatch 此名字）。
- handler 组装 `RetrievalScopeIn(...)`（仅在有 scope 字段时传对象），调 `search_chunks(..., debug=False)`；映射 hits：`content[:1200]`、`truncated=len(content)>1200`。
- 输出字段按 spec 5.1。

- [ ] **Step 4: 实现 `list_notes.py`**

- 导入 `from app.services.note_service import list_notes as list_notes_service`。
- 日期窗口：`created_from = datetime.combine(start, time.min, timezone.utc)`；`created_to = datetime.combine(end + timedelta(days=1), time.min, timezone.utc) - timedelta(microseconds=1)`。
- 多标签：`tag = tags[0]`，取回后 `items = [i for i in items if set(tags).issubset(set(i.tags or []))]`；`total` 保留服务端值，输出加 `filtered_total=len(items)` 字段（spec §5.2 说明）。
- 调 `list_notes_service(session=ctx.session, owner=ctx.user, params=PageParams(1, limit), sorting=SortParams("created_at", "desc"), subject_id=..., tag=tag, created_from=..., created_to=...)`。

- [ ] **Step 5: 实现 `get_kp_subgraph.py`**

- `session.get(KnowledgePoint, kp_id)` → 不存在 `NotFoundError("知识点不存在")`；取 `subject_id`。
- `snapshot = graph_service.snapshot(session=ctx.session, subject_id=..., user_id=ctx.user.id, now=ctx.now)`。
- 纯函数 `_bfs_subgraph(nodes, edges, center, depth)`：邻接表（无向）、BFS 记录距离、返回节点集合；边保留两端都在集合的；按 `kp_id/src,dst` 升序。
- 节点映射 `mastery` 来自 snapshot 节点；`exam_weight` 原样。
- 单测直接测 `_bfs_subgraph`（不 mock）+ handler（monkeypatch `graph_service.snapshot`）。

- [ ] **Step 6: 实现 `list_mistakes.py`**

- 导入 `from app.services.mistake_service import list_mistakes as list_mistakes_service`。
- `MistakeFilters(kp_ids=..., status=..., created_from=..., created_to=...)`；`PageParams(1, limit)`、`SortParams("created_at", "desc")`。
- 映射 `PageData.items`（`MistakeSummaryOut`）→ 出参；`total` 原样。

- [ ] **Step 7: 实现 `get_mastery.py`**

- 调 `mastery_service.mastery_details(ctx.session, user_id=ctx.user.id, kp_ids=data.kp_ids, now=ctx.now)`。
- `found = {s.kp_id for s in states}`；`missing = [kp for kp in data.kp_ids if kp not in found]`；`unassessed = [s.kp_id for s in states if not s.assessed]`。
- 输出按入参 id 顺序（service 已保证）。

- [ ] **Step 8: 实现 `search_questions.py`**

- 导入 `from app.services.question_service import list_questions as list_questions_service`。
- `exclude_done_since = None if days == 0 else ctx.now - timedelta(days=days)`。
- `QuestionFilters(kp_ids=..., subject_id=..., qtype=..., difficulty=..., exclude_user_id=ctx.user.id if days else None, exclude_done_since=...)`。
- `PageParams(1, limit)`、`SortParams("id", "desc")`。
- 映射：`stem_md` 截 2000 + `truncated`；`stem_excerpt` 用前 120 字；options 转 `[{key,text}]`；不取 `answer_md/analysis_md`。
- 页内稳定排序：`sorted(items, key=lambda x: (not x.verified, -x.question_id))`。

- [ ] **Step 9: 更新 `registry.py` 并跑测试**

`registry.py`：

```python
from app.ai.agents.tools import (
    calculator, get_kp_subgraph, get_mastery, list_mistakes, list_notes,
    make_mindmap, search_notes, search_questions,
)

_TOOL_MODULES = (
    search_notes, list_notes, get_kp_subgraph, list_mistakes, get_mastery,
    search_questions, make_mindmap, calculator,
)
TOOL_ORDER = [module.SPEC.name for module in _TOOL_MODULES]
TOOLS = {module.SPEC.name: module.SPEC for module in _TOOL_MODULES}
```

Run: `cd backend && python -m pytest tests/test_agent_tool_search_notes.py tests/test_agent_tool_list_notes.py tests/test_agent_tool_get_kp_subgraph.py tests/test_agent_tool_list_mistakes.py tests/test_agent_tool_get_mastery.py tests/test_agent_tool_search_questions.py tests/test_agent_tools_registry.py -q`
Expected: PASS（registry 测试需同步改为 8 个工具的期望顺序）

- [ ] **Step 10: 提交**

```bash
git add backend/app/ai/agents/tools backend/tests/test_agent_tool_*.py
git commit -m "feat(s6-1): 六个只读 Agent 工具"
```

---

### Task 4: `generate_questions`（Prompt + LLM 适配 + 工具）

**Files:**
- Create: `backend/app/ai/prompts/agent_gen_questions_v1.md`
- Create: `backend/app/ai/agents/tools/generate_questions.py`
- Modify: `backend/app/ai/agents/tools/registry.py`（插入到 search_questions 后）
- Test: `backend/tests/test_agent_tool_generate_questions.py`

**Interfaces:**
- Consumes: `ai.gen.variant_generator.GeneratedVariant`（复用严格字段/题型↔选项校验）、`ai.gen.json_repair.loads_lenient_json`、`ai.llm.get_llm_client`
- Produces: `generate_questions.generate_question_drafts(context, *, llm_client=None, max_retries=2) -> tuple[list[GeneratedVariant], int]`；`generate_questions.generate_questions(ctx, data) -> GenerateQuestionsOut`

- [ ] **Step 1: 写失败测试**

```python
"""S6-1 generate_questions：严格 JSON、重试、只出草稿。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tools import generate_questions as tool
from app.ai.agents.tools.base import ToolContext, ToolExecutionError


class _FakeLLM:
    def __init__(self, texts):  # noqa: ANN001
        self.texts = list(texts)
        self.calls = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):  # noqa: ANN001
        self.calls.append(SimpleNamespace(temperature=temperature, max_tokens=max_tokens, scene=scene))
        return SimpleNamespace(text=self.texts.pop(0))


_VALID = (
    '{"questions":[{"stem_md":"已知 $f(x)=x^2$，求 $f(2)$。",'
    '"options":null,"answer_md":"4","analysis_md":"代入 x=2 得 4。",'
    '"qtype":"解答","difficulty":3}]}'
)


def _ctx() -> ToolContext:
    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            name = model.__name__
            if name == "KnowledgePoint":
                return SimpleNamespace(id=pk, name="函数", subject_id=7)
            return SimpleNamespace(id=7, name="高中数学")

    return ToolContext(session=_Session(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def test_generate_questions_returns_drafts_and_retries(monkeypatch):
    llm = _FakeLLM(["不是 JSON", _VALID])
    out = tool.generate_questions(_ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm)
    assert out.count == 1
    assert out.attempts == 2
    assert out.questions[0].answer_md == "4"
    assert out.prompt_version == "agent_gen_questions_v1"
    assert llm.calls[0].scene == "gen"
    assert llm.calls[0].max_tokens == 3500


def test_generate_questions_exhausted_retries_raises(monkeypatch):
    llm = _FakeLLM(["x", "y", "z"])
    with pytest.raises(ToolExecutionError):
        tool.generate_questions(_ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm)


def test_generate_questions_count_mismatch_is_retried(monkeypatch):
    llm = _FakeLLM(['{"questions":[]}', _VALID])
    out = tool.generate_questions(_ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm)
    assert out.attempts == 2


def test_generate_questions_rejects_bad_option_shape(monkeypatch):
    bad = _VALID.replace('"options":null', '"options":[{"key":"A","text":"x"}]')
    llm = _FakeLLM([bad, bad, bad])
    with pytest.raises(ToolExecutionError):
        tool.generate_questions(_ctx(), tool.GenerateQuestionsIn(kp_id=101, count=1), llm_client=llm)
```

> 实现里 `generate_questions(ctx, data, *, llm_client=None)` 多一个仅测试用的关键字参数；注册表 handler 用 lambda 适配（`lambda ctx, data: generate_questions(ctx, data)`），避免把 `llm_client` 暴露给 S6-2。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tool_generate_questions.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 Prompt `backend/app/ai/prompts/agent_gen_questions_v1.md`**

必须包含：角色（高中数学命题）、输入变量 `{{subject_name}}` `{{kp_name}}` `{{difficulty}}` `{{difficulty_label}}` `{{qtype}}` `{{count}}` `{{question_shape}}`；严格 JSON 结构示例；LaTeX 反斜杠双写；`analysis_md` 10–200 字；「不要输出 Markdown 代码围栏/解释/多余字段」；单选/多选必须 ≥2 个唯一 key，填空/解答 `options=null`。

- [ ] **Step 4: 实现适配器与工具**

关键代码：

```python
SCENE = "gen"
PROMPT_VERSION = "agent_gen_questions_v1"
PROMPT_FILE = "agent_gen_questions_v1.md"
MAX_TOKENS = 3500
TEMPERATURE = 0.7
MAX_RETRIES = 2
DIFFICULTY_LABELS = {1: "入门", 2: "简单", 3: "中等", 4: "较难", 5: "压轴"}

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)

def render_prompt(context: GenerationContext) -> str: ...

class _ItemsOut(BaseModel):
    questions: list[GeneratedVariant]

def generate_question_drafts(context, *, llm_client=None, max_retries=MAX_RETRIES):
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]
    last_error = None
    for attempt in range(max_retries + 1):
        response = client.chat(messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE)
        try:
            parsed = _ItemsOut.model_validate(loads_lenient_json(response.text))
            if len(parsed.questions) != context.count:
                raise ValueError(f"生成条数不符：{len(parsed.questions)} != {context.count}")
            return parsed.questions, attempt + 1
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("agent_generate_questions_retry attempt=%s error=%s", attempt + 1, exc)
    raise ToolExecutionError("题目生成失败，请稍后重试")
```

工具 handler：`session.get(KnowledgePoint)` / `session.get(Subject)`，不存在 → `NotFoundError("知识点不存在")`；`GenerationContext(kp_name, subject_name, difficulty, qtype, count, difficulty_label, question_shape)`；映射 `GeneratedVariant` → 出参（`options` 转 `[{key,text}]`）。

- [ ] **Step 5: 跑测试 + Prompt 渲染边界**

Run: `cd backend && python -m pytest tests/test_agent_tool_generate_questions.py tests/test_variant_generator.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/prompts/agent_gen_questions_v1.md \
  backend/app/ai/agents/tools/generate_questions.py \
  backend/app/ai/agents/tools/registry.py backend/tests/test_agent_tool_generate_questions.py
git commit -m "feat(s6-1): generate_questions 工具与命题 Prompt"
```

---

### Task 5: `create_review_plan` / `export_paper_pdf`

**Files:**
- Create: `backend/app/ai/agents/tools/create_review_plan.py`
- Create: `backend/app/ai/agents/tools/export_paper_pdf.py`
- Modify: `backend/app/ai/agents/tools/registry.py`（补齐 11 个，顺序与方案一致）
- Test: `backend/tests/test_agent_tool_create_review_plan.py`
- Test: `backend/tests/test_agent_tool_export_paper_pdf.py`

**Interfaces:**
- Consumes: `mastery_service.mastery_details`；`review_service.local_bounds/estimated_minutes/review_priority/review_interval_days/overdue_ratio`；`paper_plan_service.get_paper`
- Produces: `create_review_plan.create_review_plan(ctx, data) -> ReviewPlanOut`（不写库）；`export_paper_pdf.export_paper_pdf(ctx, data) -> ExportPaperPdfOut`

- [ ] **Step 1: 写失败测试**

`test_agent_tool_create_review_plan.py`：

```python
from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import create_review_plan as tool
from app.ai.agents.tools.base import ToolContext
from app.services.mastery_service import KpMasteryState

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


def _state(kp_id, mastery_t, *, assessed=True, exam_weight=None, due_at=None):  # noqa: ANN001
    return KpMasteryState(
        kp_id=kp_id, kp_name=f"知识点{kp_id}", subject_id=7, exam_weight=exam_weight,
        mastery_t=mastery_t, assessed=assessed, attempts=1, stability=2.0,
        last_practice_at=None, due_at=due_at,
    )


def test_review_plan_orders_weak_first_and_rotates_days(monkeypatch):
    monkeypatch.setattr(tool.mastery_service, "mastery_details", lambda *a, **k: [
        _state(1, 0.8), _state(2, 0.2), _state(3, None, assessed=False),
    ])
    ctx = ToolContext(session=object(), user=SimpleNamespace(id=50), now=NOW)  # type: ignore[arg-type]
    out = tool.create_review_plan(ctx, tool.CreateReviewPlanIn(kp_ids=[1, 2, 3], days=2))
    assert [item.kp_id for item in out.items] == [2, 1, 3]
    assert [item.day for item in out.items] == [1, 2, 1]
    assert out.items[2].mastery_t is None
    assert "尚未评估" in out.items[2].reason
    assert out.total_minutes == 18


def test_review_plan_first_day_is_tomorrow_local():
    dates = tool._day_dates(NOW, 3)  # noqa: SLF001
    assert dates[0].isoformat() == "2026-11-18"
    assert dates[-1].isoformat() == "2026-11-20"
```

`test_agent_tool_export_paper_pdf.py`：

```python
from types import SimpleNamespace
import pytest
from app.ai.agents.tools import export_paper_pdf as tool
from app.ai.agents.tools.base import ToolContext
from app.core.exceptions import ForbiddenError, NotFoundError


def _ctx():
    return ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def test_export_paper_pdf_returns_url(monkeypatch):
    monkeypatch.setattr(tool, "get_paper", lambda *a, **k: SimpleNamespace(
        id=9, title="函数小卷", total_score=55, items=[1, 2, 3],
    ))
    out = tool.export_paper_pdf(_ctx(), tool.ExportPaperPdfIn(paper_id=9, variant="answers"))
    assert out.download_url == "/api/v1/papers/9/export.pdf?variant=answers"
    assert out.filename == "试卷-9-答案卷.pdf"
    assert out.question_count == 3


def test_export_paper_pdf_not_found(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise NotFoundError("试卷不存在")
    monkeypatch.setattr(tool, "get_paper", boom)
    with pytest.raises(NotFoundError):
        tool.export_paper_pdf(_ctx(), tool.ExportPaperPdfIn(paper_id=404))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tool_create_review_plan.py tests/test_agent_tool_export_paper_pdf.py -q`
Expected: FAIL

- [ ] **Step 3: 实现 `create_review_plan.py`**

- `_day_dates(now, days)`：用 `review_service.local_bounds(now, ZoneInfo("Asia/Shanghai"))` 取本地日 → 从「明天」起 `days` 个 `date`。
- 排序：`assessed` 先按 `mastery_t` 升序，未评估排后按 `kp_id`；`index % days` 分天。
- 每个 item：`planned_minutes = review_service.estimated_minutes("question", 3)`；`interval = review_service.review_interval_days(stability, mastery_t)`；`overdue = review_service.overdue_ratio(due_at, now, interval) if due_at else 0.0`；`priority = review_service.review_priority(mastery_t or 0.5, overdue, exam_weight)`。
- `reason`：已评估 → `f"掌握度 {mastery_t:.2f}，建议优先复习"`；未评估 → `"尚未评估，建议先做一次练习"`。
- `by_day` 汇总；不写库、不 commit。

- [ ] **Step 4: 实现 `export_paper_pdf.py`**

- `get_paper = paper_plan_service.get_paper`（测试 monkeypatch 的名字）。
- `detail = get_paper(ctx.session, user_id=ctx.user.id, paper_id=data.paper_id)`。
- `filename = f"试卷-{paper_id}-{'题干卷' if variant=='questions' else '答案卷'}.pdf"`；`download_url = f"/api/v1/papers/{paper_id}/export.pdf?variant={variant}"`。
- 出参 `question_count=len(detail.items)`、`total_score=detail.total_score`、`title=detail.title`。

- [ ] **Step 5: 补齐 registry 为 11 个（方案顺序）**

```python
_TOOL_MODULES = (
    search_notes, list_notes, get_kp_subgraph, list_mistakes, get_mastery,
    search_questions, generate_questions, make_mindmap, create_review_plan,
    export_paper_pdf, calculator,
)
```

- [ ] **Step 6: 跑测试 + 更新 registry 断言**

Run: `cd backend && python -m pytest tests/test_agent_tool_create_review_plan.py tests/test_agent_tool_export_paper_pdf.py tests/test_agent_tools_registry.py -q`
Expected: PASS（registry 期望 11 个工具，顺序与方案一致）

- [ ] **Step 7: 提交**

```bash
git add backend/app/ai/agents/tools backend/tests/test_agent_tool_*.py
git commit -m "feat(s6-1): 复习计划与试卷导出工具，注册表补齐 11 个"
```

---

### Task 6: schema 导出 + 独立 CLI

**Files:**
- Create: `backend/app/ai/agents/tools/schema_export.py`
- Create: `backend/data/agent_tools.json`（由脚本生成）
- Create: `scripts/export_agent_tools.py`
- Create: `scripts/agent_tools.py`
- Modify: `backend/app/ai/agents/tools/__init__.py`（导出 `TOOLS/TOOL_ORDER/invoke_tool/ToolContext`）
- Test: `backend/tests/test_agent_tools_schema_export.py`

**Interfaces:**
- Produces: `schema_export.build_export_payload() -> dict`、`schema_export.dumps_payload(payload) -> str`（`ensure_ascii=False, indent=2` + 末尾换行）
- Produces: `scripts/export_agent_tools.py --out <path>`（默认 `backend/data/agent_tools.json`）；`scripts/agent_tools.py list|schema|call`

- [ ] **Step 1: 写失败测试**

```python
"""S6-1 schema 导出：11 条 OpenAI function + 仓库文件不漂移。"""
from __future__ import annotations

import json
from pathlib import Path

from app.ai.agents.tools.schema_export import build_export_payload, dumps_payload


def test_export_payload_has_11_openai_functions():
    payload = build_export_payload()
    assert payload["version"] == 1
    assert len(payload["tools"]) == 11
    names = [item["function"]["name"] for item in payload["tools"]]
    assert names == [
        "search_notes", "list_notes", "get_kp_subgraph", "list_mistakes",
        "get_mastery", "search_questions", "generate_questions", "make_mindmap",
        "create_review_plan", "export_paper_pdf", "calculator",
    ]
    for item in payload["tools"]:
        function = item["function"]
        assert item["type"] == "function"
        assert function["description"]
        assert function["parameters"]["type"] == "object"
        assert function["parameters"]["additionalProperties"] is False
    assert set(payload["outputs"]) == set(names)


def test_committed_schema_file_matches_generator():
    path = Path(__file__).resolve().parents[1] / "data" / "agent_tools.json"
    assert path.read_text(encoding="utf-8") == dumps_payload(build_export_payload())
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_agent_tools_schema_export.py -q`
Expected: FAIL（模块/文件不存在）

- [ ] **Step 3: 实现 `schema_export.py` 与 `__init__.py`**

```python
# schema_export.py
def build_export_payload() -> dict:
    from app.ai.agents.tools.registry import TOOLS, TOOL_ORDER

    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOLS[name].description,
                "parameters": TOOLS[name].input_model.model_json_schema(),
            },
        }
        for name in TOOL_ORDER
    ]
    outputs = {name: TOOLS[name].output_model.model_json_schema() for name in TOOL_ORDER}
    return {"version": 1, "tools": tools, "outputs": outputs}


def dumps_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
```

- [ ] **Step 4: 写导出脚本并生成文件**

```python
# scripts/export_agent_tools.py
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.agents.tools.schema_export import build_export_payload, dumps_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "backend" / "data" / "agent_tools.json"))
    args = parser.parse_args()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_payload(build_export_payload()), encoding="utf-8")
    print(f"已写入 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `cd backend && python ../scripts/export_agent_tools.py`
Expected: 打印已写入，生成 `backend/data/agent_tools.json`

- [ ] **Step 5: 写 CLI `scripts/agent_tools.py`**

子命令：
- `list`：打印 `name — description 第一句`；
- `schema`：打印 `dumps_payload(build_export_payload())`；
- `call --user-id 50 <tool> '<json>'`：`with new_session() as session:` → `session.get(User, user_id)`（不存在退出 2）→ `ToolContext(session, user)` → `invoke_tool` → `print(out.model_dump_json(indent=2))`；`AppError` 打印 `code/message` 退出 1。

- [ ] **Step 6: 跑 schema 测试 + CLI 冒烟**

Run:
```bash
cd backend && python -m pytest tests/test_agent_tools_schema_export.py -q
cd .. && python scripts/agent_tools.py list
python scripts/agent_tools.py call --user-id 50 calculator '{"expression":"1/3"}'
```
Expected: 测试 PASS；list 11 行；calculator 输出 `"text": "0.333333333333"`。

- [ ] **Step 7: 提交**

```bash
git add backend/app/ai/agents/tools backend/data/agent_tools.json scripts/export_agent_tools.py \
  scripts/agent_tools.py backend/tests/test_agent_tools_schema_export.py
git commit -m "feat(s6-1): 工具 schema 导出与独立 CLI"
```

---

### Task 7: 文档、全量验收与真实库逐个调用

**Files:**
- Create: `docs/AGENT_TOOLS.md`
- Modify: `docs/DECISIONS.md`（追加 D-065）
- Modify: `docs/PROGRESS.md`（阶段 6 / 下一步 / 验收数字 / 遗留）
- Modify: `AGENTS.md` §9.6（追加工具层锚点）
- Create: `.sdd/s6-1/acceptance-evidence.md`（区分实测数字与未做项）

- [ ] **Step 1: 写 `docs/AGENT_TOOLS.md`**

内容：11 个工具表（名称/用途/入参/出参/是否写库）、`ToolContext` 契约、schema 再生成命令、CLI 调用示例、错误语义、已知边界（全学科 snapshot、复用 `gen` 场景、导出只给链接、计划不写库）。

- [ ] **Step 2: 追加 D-065**

标题 `## D-065 Agent 工具集（S6-1）`；记录：11 vs 10、纯函数口径、只读草稿、schema 与 CLI、service 三处增量、复用 `gen`、验收数字与已知边界。

- [ ] **Step 3: 更新 PROGRESS**

- 当前状态加 S6-1 完成；任务清单 `[x] S6-1`；下一步改 `S6-2 LangGraph 状态机 + 步骤持久化`；贴真实验收数字与 11 个工具逐个调用结果摘要。

- [ ] **Step 4: 更新 AGENTS §9.6 锚点**

追加一条：
```
- Agent 工具样例：backend/app/ai/agents/tools/{base,registry,schema_export}.py + calculator.py（Pydantic 入参/出参、`ToolSpec` 注册、`invoke_tool` 统一错误壳、schema 导出脚本 + CLI；工具只读，写操作留 S6-2 确认）
```

- [ ] **Step 5: 全量测试**

Run: `cd backend && python -m pytest -q`
Expected: 全绿；记录精确数字（基线 1458 passed, 5 warnings）。

- [ ] **Step 6: 真实库逐个调用（user 50）**

```bash
cd study-agent
python scripts/agent_tools.py list
python scripts/agent_tools.py call --user-id 50 calculator '{"expression":"2**10"}'
python scripts/agent_tools.py call --user-id 50 make_mindmap '{"title":"函数","nodes":[{"id":"1","name":"函数"},{"id":"2","name":"定义域","parent_id":"1"}]}'
python scripts/agent_tools.py call --user-id 50 list_notes '{"limit":3}'
python scripts/agent_tools.py call --user-id 50 list_mistakes '{"limit":3}'
python scripts/agent_tools.py call --user-id 50 get_mastery '{"kp_ids":[197,198]}'
python scripts/agent_tools.py call --user-id 50 get_kp_subgraph '{"kp_id":197,"depth":2}'
python scripts/agent_tools.py call --user-id 50 search_questions '{"kp_ids":[197],"limit":3}'
python scripts/agent_tools.py call --user-id 50 create_review_plan '{"kp_ids":[197,198],"days":2}'
python scripts/agent_tools.py call --user-id 50 export_paper_pdf '{"paper_id":13}'
python scripts/agent_tools.py call --user-id 50 search_notes '{"query":"函数的定义域","top_k":3}'
python scripts/agent_tools.py call --user-id 50 generate_questions '{"kp_id":197,"difficulty":3,"count":3,"qtype":"解答"}'
```
Expected：全部返回 JSON；`search_notes`/`generate_questions` 走真实外部调用（记录耗时/条数）；`export_paper_pdf` 用真实存在的本人试卷 id（不存在就换 id 并如实记录）。

- [ ] **Step 7: 写验收证据**

`.sdd/s6-1/acceptance-evidence.md`：pytest 数字、schema 11 条、每个工具的命令与关键出参（不贴学生隐私正文）、失败与修复记录。

- [ ] **Step 8: 提交**

```bash
git add docs/AGENT_TOOLS.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md .sdd/s6-1
git commit -m "docs(s6-1): 工具目录、决策与验收记录"
```

---

## Self-Review

**Spec coverage：**

| spec 章节 | 对应 Task |
|---|---|
| 11 个工具清单/入参出参 | Task 1（2）、Task 3（6）、Task 4（1）、Task 5（2） |
| 公共契约（ToolContext/Spec/错误/invoke） | Task 1 |
| schema 导出与仓库文件 | Task 6 |
| 服务增量 | Task 2 |
| generate_questions Prompt | Task 4 |
| 单测清单 | 各 Task 内；schema/service 支撑在 Task 2/6 |
| 验收/文档/提交 | Task 7 |

**Placeholder scan：** 无 TBD/TODO；每个实现步骤都给了函数签名、关键分支或可执行命令。

**Type consistency：** `ToolContext(session,user,now)`、`ToolSpec(name,description,input_model,output_model,handler,write)`、`invoke_tool(name,ctx,payload)`、`mastery_details(...)->list[KpMasteryState]`、`QuestionFilters` 新字段名、`MistakeFilters.kp_ids` 在各 Task 中一致；工具名与方案 §6.7 一致。

**已知取舍：** Task 1 的 registry 测试先断言 2 个工具，Task 3 改 8 个、Task 5 改 11 个——每次改断言是刻意的增量红绿，不是漏写。