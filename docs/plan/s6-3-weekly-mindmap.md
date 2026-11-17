# S6-3 周笔记整理 + 思维导图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `weekly_mindmap` 任务（过去 N 天笔记 → 知识点子图 → LLM 聚类 → Mermaid + 摘要/引用）与「学习导图」前端页（渲染 + 导出 PNG）；S6-4 不做。

**Architecture:** 在 S6-2 图上增加 `AgentTaskSpec.extend_plan(state)` 动态追加步骤；`weekly_mindmap` 的 spec 按「取笔记 → 取知识点子图 → LLM 聚类并生成 make_mindmap 计划 → finalize 组装摘要/引用」推进，结果只写 `agent_tasks.result_json`。前端新增 `/agent/mindmap/:taskId?` 页面，1 秒轮询任务、`mermaid` 渲染 SVG、Canvas 导出 PNG，失败时显示工具产出的 `fallback_text`。

**Tech Stack:** Python 3.11、LangGraph 1.2.22、Pydantic v2、FastAPI、SQLAlchemy、Jinja2、Vue 3 + TS + Element Plus、mermaid 11.17.2、Vitest。

**Spec:** `docs/spec/s6-3-weekly-mindmap.md`

## Global Constraints

- 只做 `weekly_mindmap`；`mistake_paper` 不注册（用户确认 S6-4 不做），仍 422。
- 不新建笔记/不改 `notes`/`note_kps`；结果只存 `agent_tasks.result_json`。
- 不新增后端工具；`list_notes` 只扩出参 `preview/kp_ids/kp_names`，旧字段不变。
- 最大步数 12 不变；知识点子图最多 3 个（3 子图 + 导图正好 12 行）。
- LLM 聚类失败必须降级为确定性树并 `degraded=true`，任务不因此失败；Mermaid 渲染失败由前端显示 `fallback_text`。
- 真实库 7 天无笔记时返回 `note_count=0` 空态，不造假；验收另跑 30 天真实笔记并如实记录。
- 测试不连库、不调真实 LLM、不真渲染 mermaid；外部调用在测试中 mock。
- 前端只新增 `mermaid@^11` 依赖；不引入截图/导出库。
- 每个 Task 先红后绿；完成后跑对应测试并提交（Conventional Commits 含 `s6-3`）。

---

### Task 1: 引擎动态规划 `extend_plan`

**Files:**
- Modify: `backend/app/ai/agents/engine.py`
- Modify: `backend/app/ai/agents/tasks/demo.py`
- Test: `backend/tests/test_agent_engine_extension.py`
- Test: `backend/tests/test_agent_graph.py`（补 demo 空扩展断言）

**Interfaces:**
- Produces: `PlanExtension(steps: list[PlanStep] = [], token_cost: int = 0, thought: str | None = None)`
- Produces: `AgentTaskSpec.extend_plan(self, state: AgentState) -> PlanExtension`
- Consumes: observe 成功后的 state/artifacts/current_index

- [x] **Step 1: 写失败测试**

```python
"""S6-3 引擎动态规划：observe 后追加步骤、token 累加、步数上限。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.engine import (
    AgentEngine,
    AgentStepLimitError,
    PlanExtension,
    RunContext,
)
from app.ai.agents.state import new_state


class Recorder:
    def __init__(self):  # noqa: ANN001
        self.steps = []

    def record(self, *, step_no, thought, status, state, tool_name=None,
               tool_input=None, tool_output=None, latency_ms=None):  # noqa: ANN001
        self.steps.append({"step_no": step_no, "thought": thought, "status": status,
                           "tool_name": tool_name, "tool_output": tool_output})


class SequenceSpec:
    task_type = "seq"
    requires_confirm = False

    def __init__(self, *, total=2, token_cost=0):  # noqa: ANN001
        self.total = total
        self.token_cost = token_cost

    def build_plan(self, state):  # noqa: ANN001
        return [{"tool": "calculator", "input": {"expression": "1+1"}, "purpose": "第一步"}]

    def extend_plan(self, state):  # noqa: ANN001
        done = len([s for s in state.get("plan") or [] if s["tool"] == "calculator"])
        if done < self.total:
            return PlanExtension(
                steps=[{"tool": "calculator", "input": {"expression": "2+2"}, "purpose": f"第{done + 1}步"}],
                token_cost=self.token_cost,
                thought="追加下一步",
            )
        return PlanExtension()

    def finalize(self, state):  # noqa: ANN001
        return {"summary": "ok", "artifacts": state.get("artifacts") or {}}


def _run(spec, *, max_steps=12, state=None):  # noqa: ANN001
    recorder = Recorder()
    engine = AgentEngine(
        spec,
        RunContext(
            user=SimpleNamespace(id=50),
            recorder=recorder,
            tool_invoker=lambda name, ctx, payload: {"echo": payload},
        ),
    )
    initial = state or new_state(user_id=50, task_input={}, token_budget=20000, max_steps=max_steps)
    final = engine.run(initial)
    return final, recorder


def test_extend_plan_appends_steps_and_accumulates_tokens():
    final, recorder = _run(SequenceSpec(total=2, token_cost=7))
    assert final["status"] == "succeeded"
    assert len([s for s in recorder.steps if s["tool_name"] == "calculator"]) == 2
    assert final["token_cost"] == 14
    assert any("追加下一步" in (s["thought"] or "") for s in recorder.steps)


def test_extend_plan_can_stop():
    final, recorder = _run(SequenceSpec(total=1))
    assert final["status"] == "succeeded"
    assert len([s for s in recorder.steps if s["tool_name"] == "calculator"]) == 1


def test_extended_steps_respect_max_steps():
    with pytest.raises(AgentStepLimitError):
        _run(SequenceSpec(total=10), max_steps=4)
```

`test_agent_graph.py` 补：

```python
def test_demo_spec_has_empty_extend_plan():
    spec = DemoTaskSpec({"steps": [{"tool": "calculator", "input": {}}]})
    assert spec.extend_plan({}).steps == []
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_engine_extension.py -q`
Expected: FAIL（`PlanExtension`/`extend_plan` 不存在）

- [x] **Step 3: 实现引擎扩展**

- `engine.py` 增加 `PlanExtension` frozen dataclass；`AgentTaskSpec` 增加 `extend_plan`。
- `_observe` 成功分支在写 artifacts/current_index 之后：

```python
prospective = {**state, **update}
extension = self.spec.extend_plan(prospective)
if extension.steps:
    plan = list(prospective.get("plan") or [])
    plan.extend(extension.steps)
    update["plan"] = plan
    prospective["plan"] = plan
if extension.token_cost:
    update["token_cost"] = int(prospective.get("token_cost") or 0) + extension.token_cost
    prospective["token_cost"] = update["token_cost"]
hit = self._budget_hit(prospective, update)
thought = extension.thought or f"步骤 {index + 1} 成功，产物已收集"
self._record(state, update, thought=thought, status="error" if hit else "ok")
```

- `demo.DemoTaskSpec` 增加 `def extend_plan(self, state): return PlanExtension()`。
- 不新增节点；扩展后的步骤仍走 `act → observe`，guard 负责 12 行上限。

- [x] **Step 4: 跑测试 + S6-2 图回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_engine_extension.py tests/test_agent_graph.py tests/test_agent_task_spec_demo.py -q`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/app/ai/agents backend/tests/test_agent_engine_extension.py backend/tests/test_agent_graph.py
git commit -m "feat(s6-3): 状态机支持 observe 后动态追加步骤"
```

---

### Task 2: `list_notes` 出参补 `preview/kp_ids/kp_names`

**Files:**
- Modify: `backend/app/ai/agents/tools/list_notes.py`
- Test: `backend/tests/test_agent_tool_list_notes.py`
- Modify: `docs/AGENT_TOOLS.md`（工具表 `list_notes` 出参）

**Interfaces:**
- Produces: `NoteBrief.preview: str | None`、`NoteBrief.kp_ids: list[int]`、`NoteBrief.kp_names: list[str]`
- Consumes: `Note.content_text`、`NoteKp`、`KnowledgePoint`

- [ ] **Step 1: 改造失败测试**

在 `test_agent_tool_list_notes.py` 增加 FakeSession：

```python
class _Rows:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = rows

    def all(self):  # noqa: ANN201
        return self._rows


class _Session:
    def __init__(self, *, previews, kps):  # noqa: ANN001
        self.previews = previews
        self.kps = kps
        self.calls = 0

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.calls += 1
        return _Rows(self.previews if self.calls == 1 else self.kps)


def test_list_notes_adds_preview_and_knowledge_points(monkeypatch):
    monkeypatch.setattr(
        tool,
        "list_notes_service",
        lambda *a, **k: PageData(items=[_note(1)], total=1, page=1, page_size=20),
    )
    ctx = ToolContext(
        session=_Session(previews=[(1, "函数内容" * 100)], kps=[(1, 137, "函数的单调性")]),
        user=SimpleNamespace(id=18),
    )  # type: ignore[arg-type]
    out = tool.list_notes(ctx, tool.ListNotesIn())
    assert out.items[0].preview == ("函数内容" * 100)[:200]
    assert out.items[0].kp_ids == [137]
    assert out.items[0].kp_names == ["函数的单调性"]


def test_list_notes_skips_extra_queries_when_empty(monkeypatch):
    session = _Session(previews=[], kps=[])
    monkeypatch.setattr(
        tool, "list_notes_service",
        lambda *a, **k: PageData(items=[], total=0, page=1, page_size=20),
    )
    ctx = ToolContext(session=session, user=SimpleNamespace(id=18))  # type: ignore[arg-type]
    tool.list_notes(ctx, tool.ListNotesIn())
    assert session.calls == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_tool_list_notes.py -q`
Expected: FAIL（`preview` 字段不存在/查询次数不符）

- [ ] **Step 3: 实现两条批查**

- `_load_previews(session, ids) -> dict[int,str]`：`select(Note.id, Note.content_text).where(Note.id.in_(ids))`，映射 `content_text[:200]`。
- `_load_kps(session, ids) -> dict[int, list[tuple[int,str]]]`：`select(NoteKp.note_id, KnowledgePoint.id, KnowledgePoint.name).join(...).where(note_id.in_(ids)).order_by(NoteKp.note_id, NoteKp.weight.desc(), KnowledgePoint.id)`；每篇最多 10 个。
- `NoteBrief` 加三字段，默认 `None/[]/[]`；`_to_brief(item, preview, kps)` 填充。
- `list_notes` 在 `items` 非空时执行两条查询；空列表直接返回。

- [ ] **Step 4: 跑测试 + 工具回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_tool_list_notes.py tests/test_agent_tools_schema_export.py -q`
Expected: PASS（schema 输出会变化，需重新生成 `backend/data/agent_tools.json` 并提交）

- [ ] **Step 5: 重新导出 schema 并提交**

```bash
cd .. && .venv/Scripts/python.exe scripts/export_agent_tools.py
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_tools_schema_export.py -q
git add backend/app/ai/agents/tools/list_notes.py backend/data/agent_tools.json \
  backend/tests/test_agent_tool_list_notes.py docs/AGENT_TOOLS.md
git commit -m "feat(s6-3): list_notes 补 preview 与知识点"
```

---

### Task 3: LLM 聚类适配器 + Prompt

**Files:**
- Create: `backend/app/ai/prompts/weekly_mindmap_v1.md`
- Create: `backend/app/ai/agents/tasks/weekly_mindmap.py`（Step 3 只放聚类部分）
- Test: `backend/tests/test_agent_weekly_cluster.py`

**Interfaces:**
- Produces: `ClusterContext(days, notes, subgraphs)`、`ClusterResult/ClusterBranch`、`ClusterError`
- Produces: `render_cluster_prompt(context) -> str`、`generate_cluster(context, *, llm_client=None, max_retries=2) -> tuple[ClusterResult, int]`

- [ ] **Step 1: 写失败测试**

```python
"""S6-3 聚类适配器：严格 JSON、引用校验、重试与 token。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tasks import weekly_mindmap as wm
from app.ai.agents.tasks.weekly_mindmap import ClusterContext, ClusterError

VALID = (
    '{"title":"上周学习导图","branches":['
    '{"kp_id":137,"title":"函数的单调性","conclusion":"复习了定义法与图像法。",'
    '"note_ids":[54],"children":["定义法","图像法"]}]}'
)


class FakeLLM:
    def __init__(self, texts):  # noqa: ANN001
        self.texts = list(texts)
        self.calls = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):  # noqa: ANN001
        self.calls.append(SimpleNamespace(scene=scene, max_tokens=max_tokens))
        return SimpleNamespace(text=self.texts.pop(0), total_tokens=120)


def _context():
    return ClusterContext(
        days=7,
        notes=[{"note_id": 54, "title": "函数", "preview": "内容", "kp_names": ["函数的单调性"]}],
        subgraphs=[{"nodes": [{"kp_id": 137, "name": "函数的单调性"}], "edges": []}],
    )


def test_cluster_prompt_contains_notes_and_schema():
    text = wm.render_cluster_prompt(_context())
    assert "note_id" in text and "函数的单调性" in text
    assert "branches" in text


def test_generate_cluster_returns_result_and_tokens():
    llm = FakeLLM([VALID])
    result, tokens = wm.generate_cluster(_context(), llm_client=llm)
    assert result.title == "上周学习导图"
    assert result.branches[0].note_ids == [54]
    assert tokens == 120
    assert llm.calls[0].scene == "agent"
    assert llm.calls[0].max_tokens == 2200


def test_generate_cluster_retries_then_raises():
    llm = FakeLLM(["x", "y", "z"])
    with pytest.raises(ClusterError):
        wm.generate_cluster(_context(), llm_client=llm)


def test_generate_cluster_filters_invalid_citations_and_kp():
    bad = VALID.replace('"note_ids":[54]', '"note_ids":[999]').replace('"kp_id":137', '"kp_id":999')
    llm = FakeLLM([bad, bad, bad])
    with pytest.raises(ClusterError):
        wm.generate_cluster(_context(), llm_client=llm)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_weekly_cluster.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 Prompt**

`weekly_mindmap_v1.md`：角色（学习总结）、输入变量 `{{ days }}` `{{ notes_json }}` `{{ subgraphs_json }}`、严格 JSON schema（`title/branches/kp_id/title/conclusion/note_ids/children`）、要求：
- 只用输入笔记与知识点；`note_ids` 必须来自输入；
- 1–8 个分支；分支标题/结论各 ≤200 字；children 0–6 个；
- 只输出 JSON，不要 Markdown 围栏/解释；
- 不要编造笔记 id、知识点 id 或数字。

- [ ] **Step 4: 实现聚类适配器**

- `ClusterBranch`/`ClusterResult` Pydantic（extra=forbid、长度上限、branches 1–8）。
- `render_cluster_prompt`：Jinja2 StrictUndefined；`notes_json`/`subgraphs_json` 用 `json.dumps(ensure_ascii=False)`。
- `generate_cluster`：
  ```python
  client = llm_client or get_llm_client()
  messages=[LLMMessage(role="user", content=render_cluster_prompt(context))]
  for attempt in range(max_retries+1):
      resp=client.chat(messages, temperature=0.3, max_tokens=2200, scene="agent")
      try:
          parsed=ClusterResult.model_validate(loads_lenient_json(resp.text))
      except (ValidationError, ValueError): continue
      cleaned = sanitize_branches(parsed, note_ids=..., kp_ids=...)
      if not any(b.note_ids for b in cleaned.branches):
          continue
      return cleaned, resp.total_tokens
  raise ClusterError("聚类失败")
  ```
- `sanitize_branches`：`note_ids` 取交集、去重；`kp_id` 不在候选置 null；`children` 去空截断；分支标题/结论 strip。
- `get_llm_client` 与 `loads_lenient_json` 在模块级导入，测试可 monkeypatch。

- [ ] **Step 5: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_weekly_cluster.py tests/test_variant_json_repair.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/prompts/weekly_mindmap_v1.md backend/app/ai/agents/tasks/weekly_mindmap.py \
  backend/tests/test_agent_weekly_cluster.py
git commit -m "feat(s6-3): 周导图 LLM 聚类适配器与 Prompt"
```

---

### Task 4: `weekly_mindmap` 任务类型 + 注册 + API

**Files:**
- Modify: `backend/app/ai/agents/tasks/weekly_mindmap.py`（补 `WeeklyMindmapTaskSpec`）
- Modify: `backend/app/ai/agents/tasks/__init__.py`
- Test: `backend/tests/test_agent_task_weekly_mindmap.py`
- Modify: `backend/tests/test_agent_service.py`（weekly 可创建、mistake_paper 仍 422）
- Modify: `docs/API.md §10`（任务类型）

**Interfaces:**
- Produces: `WeeklyMindmapTaskSpec(task_input, *, llm_client=None, now=None)`：`task_type="weekly_mindmap"`、`requires_confirm=False`、`build_plan/extend_plan/finalize`
- Produces: 结果 JSON（`task_type/days/note_count/kp_count/summary_md/mermaid/fallback_text/citations/degraded/cluster_prompt_version`）

- [ ] **Step 1: 写失败测试**

```python
"""S6-3 weekly_mindmap：日期窗口、三阶段扩展、摘要/引用/空窗口/降级。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tasks.weekly_mindmap import WeeklyMindmapTaskSpec

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


def _notes_artifact(notes):
    return {"step_1": {"tool": "list_notes", "input": {}, "output": {"items": notes}}}


def test_validate_input_and_build_plan_window():
    data = WeeklyMindmapTaskSpec.validate_input({"days": 7})
    spec = WeeklyMindmapTaskSpec(data, now=NOW)
    assert spec.build_plan({})[0]["tool"] == "list_notes"
    payload = spec.build_plan({})[0]["input"]
    assert payload["start_date"] == "2026-11-11"
    assert payload["end_date"] == "2026-11-17"


def test_extend_prefers_top_three_kps():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    state = {
        "plan": [{"tool": "list_notes"}],
        "artifacts": _notes_artifact([
            {"note_id": 1, "kp_ids": [11], "kp_names": ["A"], "title": "n1"},
            {"note_id": 2, "kp_ids": [11, 12], "kp_names": ["A", "B"], "title": "n2"},
            {"note_id": 3, "kp_ids": [13], "kp_names": ["C"], "title": "n3"},
        ]),
    }
    ext = spec.extend_plan(state)
    assert [s["input"]["kp_id"] for s in ext.steps] == [11, 12, 13]
    assert all(s["tool"] == "get_kp_subgraph" for s in ext.steps)


def test_extend_builds_mindmap_after_subgraphs_with_llm():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    state = {
        "plan": [{"tool": "list_notes"}, {"tool": "get_kp_subgraph"}],
        "artifacts": {
            **_notes_artifact([{"note_id": 54, "title": "函数", "kp_ids": [137], "kp_names": ["单调性"], "preview": "x"}]),
            "step_2": {"tool": "get_kp_subgraph", "input": {"kp_id": 137}, "output": {"nodes": [], "edges": []}},
        },
    }
    # spec 内部使用 fake LLM：构造时传入
    fake = SimpleNamespace(chat=lambda *a, **k: SimpleNamespace(
        text='{"title":"导图","branches":[{"kp_id":137,"title":"单调性","conclusion":"复习了定义法。","note_ids":[54],"children":[]}]}',
        total_tokens=80))
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW, llm_client=fake)
    ext = spec.extend_plan(state)
    assert ext.token_cost == 80
    assert ext.steps[0]["tool"] == "make_mindmap"
    assert ext.steps[0]["input"]["nodes"][0]["name"] == "单调性"


def test_empty_window_finalize_returns_empty_state():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    result = spec.finalize({
        "plan": [{"tool": "list_notes"}],
        "artifacts": _notes_artifact([]),
    })
    assert result["note_count"] == 0
    assert result["mermaid"] == ""
    assert "没有笔记" in result["summary_md"]


def test_finalize_summary_and_citations_from_cluster():
    spec = WeeklyMindmapTaskSpec({"days": 7}, now=NOW)
    spec._cluster = SimpleNamespace(  # noqa: SLF001
        title="导图",
        branches=[SimpleNamespace(kp_id=137, title="单调性", conclusion="复习了定义法。", note_ids=[54], children=[])],
    )
    result = spec.finalize({
        "plan": [{"tool": "make_mindmap"}],
        "artifacts": {
            **_notes_artifact([{"note_id": 54, "title": "函数", "kp_ids": [137], "kp_names": ["单调性"]}]),
            "step_3": {"tool": "make_mindmap", "input": {}, "output": {"mermaid": "mindmap\n  root((导图))", "fallback_text": "- 导图"}},
        },
    })
    assert result["mermaid"].startswith("mindmap")
    assert "引用：笔记 #54" in result["summary_md"]
    assert result["citations"] == [{"note_id": 54, "note_title": "函数"}]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_task_weekly_mindmap.py -q`
Expected: FAIL（`WeeklyMindmapTaskSpec` 不存在）

- [ ] **Step 3: 实现 `WeeklyMindmapTaskSpec`**

- 输入 `WeeklyInput(days 1–30=7, subject_id≥1|None)`；`validate_input` 抛 `InvalidParamError`。
- `build_plan`：UTC 日期窗口 + `limit=50`；`purpose=f"取过去 {days} 天笔记"`。
- `extend_plan` 按 spec §3.3 三阶段：
  - 无 `get_kp_subgraph` 且笔记 kp 非空 → top3 子图；无 kp 直接进聚类；
  - 无 `make_mindmap` → 聚类（`self._llm_client`）+ 转 nodes/edges；捕获 `ClusterError` 走 `_fallback_cluster` 并设 `self._degraded=True`；
  - 已有 → 空。
- `_cluster` 结果存 `self._cluster`；`_subgraphs(state)` 从 artifacts 取。
- `_nodes_from_cluster`：分支 `b{i}` 顶层 + children `b{i}_{j}`；`parent_id` 指向分支；空 children 也保留分支。
- `finalize`：
  - 无笔记 → 空结果（固定文案）。
  - 有笔记：从 artifacts 找 `make_mindmap` 输出；摘要按 `self._cluster`（缺失时用 artifacts 的 make_mindmap 输入节点构造兜底）；引用按 branch.note_ids 去重；`degraded`。
  - `kp_count` = 所有笔记 `kp_ids` 去重数；`note_count` = len(notes)。
- 注册 `TASK_SPECS["weekly_mindmap"]=WeeklyMindmapTaskSpec`；`demo` 保留。
- `docs/API.md §10` 更新任务类型说明与 weekly result 字段。

- [ ] **Step 4: 补 service 测试**

`test_agent_service.py`：
```python
def test_create_weekly_mindmap_allowed(monkeypatch):
    monkeypatch.setattr(agent_service.task_service, "create_task", lambda *a, **k: None)
    task = agent_service.create_agent_task(
        FakeSession(), owner=_owner(), task_type="weekly_mindmap",
        task_input={"days": 7}, queue=FakeQueue(),
    )
    assert task.task_type == "weekly_mindmap"

def test_create_mistake_paper_still_rejected():
    with pytest.raises(InvalidParamError):
        agent_service.create_agent_task(
            FakeSession(), owner=_owner(), task_type="mistake_paper",
            task_input={}, queue=FakeQueue(),
        )
```

- [ ] **Step 5: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_task_weekly_mindmap.py tests/test_agent_service.py tests/test_agent_api.py tests/test_agent_engine_extension.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/agents/tasks backend/tests/test_agent_task_weekly_mindmap.py \
  backend/tests/test_agent_service.py docs/API.md
git commit -m "feat(s6-3): weekly_mindmap 任务类型与注册"
```

---

### Task 5: 前端「学习导图」页 + Mermaid 渲染 + PNG 导出

**Files:**
- Modify: `web/package.json` / `web/package-lock.json`（已装 `mermaid@^11`）
- Create: `web/src/types/agent.ts`
- Create: `web/src/api/agent.ts`
- Create: `web/src/api/agent.spec.ts`
- Create: `web/src/views/agent/mermaid.ts`
- Create: `web/src/views/agent/mermaid.spec.ts`
- Create: `web/src/views/agent/exportMindmap.ts`
- Create: `web/src/views/agent/exportMindmap.spec.ts`
- Create: `web/src/views/agent/WeeklyMindmap.vue`
- Create: `web/src/views/agent/WeeklyMindmap.spec.ts`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/layouts/nav.ts`

**Interfaces:**
- Produces: `createAgentTask(payload): Promise<AgentTaskSummary>`、`getAgentTask(id): Promise<AgentTaskDetail>`
- Produces: `renderMermaid(code): Promise<string>`、`parseSvgSize(svg): {width,height}`、`downloadSvgAsPng(svg, filename): Promise<void>`
- Produces: `/agent/mindmap/:taskId?`、导航「学习导图」

- [ ] **Step 1: 先写前端失败测试**

`src/api/agent.spec.ts`：mock `@/api/http`，断言 POST `/api/v1/agent/tasks`、GET `/api/v1/agent/tasks/7`。
`src/views/agent/mermaid.spec.ts`：`vi.mock('mermaid', ...)`，断言 initialize 一次、render 返回 svg、失败透传。
`src/views/agent/exportMindmap.spec.ts`：`parseSvgSize` 解析 width/height 与 viewBox；缺失抛错；`downloadSvgAsPng` 空字符串拒绝。
`src/views/agent/WeeklyMindmap.spec.ts`：mock api/mermaid/export：
- 无 taskId 时显示生成表单；点击后 `createAgentTask` 被调用并轮询；
- 有 taskId 时 `getAgentTask` 返回 succeeded+result，摘要/导图容器出现；
- renderMermaid 抛错 → `fallback_text` 出现；
- `note_count=0` → 空态文案；
- 「导出 PNG」调用 `downloadSvgAsPng`。

测试骨架（页面）：

```ts
const api = vi.hoisted(() => ({ createAgentTask: vi.fn(), getAgentTask: vi.fn() }))
vi.mock('@/api/agent', () => api)
const mermaid = vi.hoisted(() => ({ renderMermaid: vi.fn(async () => '<svg width="800" height="600"></svg>') }))
vi.mock('./mermaid', () => mermaid)
const exporter = vi.hoisted(() => ({ downloadSvgAsPng: vi.fn(async () => undefined) }))
vi.mock('./exportMindmap', async () => ({ ...(await vi.importActual('./exportMindmap')), ...exporter }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: routeParams }), useRouter: () => ({ replace: vi.fn() }) }))
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/api/agent.spec.ts src/views/agent`
Expected: FAIL（页面/模块不存在）

- [ ] **Step 3: 实现 API 与类型**

- `types/agent.ts`：`AgentTaskSummary`、`AgentStep`、`WeeklyMindmapResult`、`AgentTaskDetail`（字段与 API.md 一致；`result` 使用 `WeeklyMindmapResult | null`）。
- `api/agent.ts`：POST/GET，沿用 `ApiEnvelope` 解包。

- [ ] **Step 4: 实现 Mermaid 与导出**

`mermaid.ts`：

```ts
import mermaid from 'mermaid'

let initialized = false

export async function renderMermaid(code: string): Promise<string> {
  if (!initialized) {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'default' })
    initialized = true
  }
  const { svg } = await mermaid.render(`weekly-mindmap-${Date.now()}`, code)
  if (!svg.includes('<svg')) throw new Error('Mermaid 未返回 SVG')
  return svg
}
```

`exportMindmap.ts`：

```ts
export function parseSvgSize(svgText: string): { width: number; height: number } {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml')
  const svg = doc.documentElement
  if (svg.nodeName.toLowerCase() !== 'svg') throw new Error('不是有效的 SVG')
  const width = Number(svg.getAttribute('width') ?? 0)
  const height = Number(svg.getAttribute('height') ?? 0)
  if (width > 0 && height > 0) return { width, height }
  const viewBox = (svg.getAttribute('viewBox') ?? '').split(/\s+/).map(Number)
  if (viewBox.length === 4 && viewBox[2]! > 0 && viewBox[3]! > 0) {
    return { width: viewBox[2]!, height: viewBox[3]! }
  }
  throw new Error('SVG 缺少尺寸')
}

export async function downloadSvgAsPng(svgText: string, filename: string): Promise<void> { ... }
```

- [ ] **Step 5: 实现页面**

- `WeeklyMindmap.vue`：按 spec §4.2；轮询 `setTimeout` 1s；`onBeforeUnmount` clear；`renderMermaid` 异常置 `renderFailed`；`ElMessage` 错误；`v-html` 渲染 SVG；摘要 `<pre>`；引用 `<ul>`；空态/失败/降级提示；导出按钮调用 `downloadSvgAsPng(svg, `学习导图-${taskId}-${date}.png`)`。
- 路由：`path: 'agent/mindmap/:taskId(\\d+)?'`，`meta: { title: '学习导图', nav: 'mindmap', roles: ['student'] }`。
- 导航：`{ label: '学习导图', name: 'mindmap', path: '/agent/mindmap' }`（放在「报告」/「图谱」之间）。

- [ ] **Step 6: 跑前端测试与构建**

Run: `cd web && npm run test:run -- src/api/agent.spec.ts src/views/agent`
Run: `cd web && npm run test:run`（全量）
Run: `cd web && npm run build`
Expected: 全绿；记录前端测试文件/用例数与构建包体（mermaid chunk 体积）。

- [ ] **Step 7: 提交**

```bash
git add web/package.json web/package-lock.json web/src/api/agent.ts web/src/api/agent.spec.ts \
  web/src/types/agent.ts web/src/views/agent web/src/router/index.ts web/src/layouts/nav.ts
git commit -m "feat(s6-3): 学习导图页、Mermaid 渲染与 PNG 导出"
```

---

### Task 6: 文档、全量测试与真实库/浏览器验收

**Files:**
- Create: `docs/AGENT_WEEKLY.md`
- Modify: `docs/DECISIONS.md`（D-067）
- Modify: `docs/PROGRESS.md`（S6-3 完成、S6-4 不做、下一步 S6-5）
- Modify: `AGENTS.md` §9.6
- Create: `.sdd/s6-3/acceptance-evidence.md`

- [ ] **Step 1: 文档**

- `AGENT_WEEKLY.md`：任务流程、动态规划、结果 JSON、前端页/导出、空窗口/降级、边界。
- D-067：Mermaid 依赖、结果只落 result_json、S6-4 跳过、动态规划、LLM 降级、7 天真实库缺口、验收数字。
- PROGRESS：S6-3 完成、S6-4 标「用户决定不做（组卷已有 S5-1/S5-2）」、下一步 S6-5。
- AGENTS §9.6 追加 weekly 任务/前端页锚点。

- [ ] **Step 2: 全量测试**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../web && npm run test:run && npm run build
```

Expected: 后端全绿（S6-2 基线 1543）、前端全绿、build 退出 0；记录精确数字与 mermaid chunk 体积。

- [ ] **Step 3: 后端真实库验收**

启动 Redis/ARQ/uvicorn（同 S6-2）后，用 user 18 的真实 token：

1. 7 天窗口：
   ```bash
   POST /api/v1/agent/tasks {"task_type":"weekly_mindmap","input":{"days":7}}
   # 轮询 → succeeded；result.note_count=0、mermaid=""、summary 含「没有笔记」
   ```
   如实记录「真实库 7 天无笔记，未生成导图」。
2. 30 天窗口：
   ```bash
   POST {"task_type":"weekly_mindmap","input":{"days":30}}
   # 轮询 → succeeded/ failed；若 succeeded：记录 steps 数、note_count（应为 4）、
   # kp_count、mermaid 前 200 字、citations、degraded、LLM 耗时/token_cost
   ```
3. 若真实 LLM 降级，记录 `degraded=true` 与原因；不修饰。
4. 越权/非法：teacher 403、days=0 422、`mistake_paper` 422。

- [ ] **Step 4: 前端 Chrome 验收**

- 启动 `npm run dev`（5173），用真实 token 登录（既有 localStorage 注入/登录方式）。
- 打开 `/agent/mindmap`：选 30 天生成 → 状态轮询 → 导图 SVG 可见；点「导出 PNG」→ 下载文件非空、尺寸合理。
- 打开 7 天任务：空态文案；无 Mermaid 容器。
- 渲染失败降级：可用 dev 注入坏 mermaid（或在页面 mock）验证 `fallback_text` 出现；记录方式。
- 1440×900 无横向溢出、console error 0。

- [ ] **Step 5: 验收证据**

`.sdd/s6-3/acceptance-evidence.md`：pytest/vitest/build 数字、真实 7d/30d 结果、Chrome 截图文件名、未满足项（7 天真实数据缺口）。

- [ ] **Step 6: 提交**

```bash
git add docs/AGENT_WEEKLY.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md
git commit -m "docs(s6-3): 周导图文档、D-067 与验收记录"
```

---

## Self-Review

**Spec coverage：**

| spec 章节 | Task |
|---|---|
| 动态规划引擎 | Task 1 |
| list_notes 出参 | Task 2 |
| LLM 聚类/Prompt/降级 | Task 3 |
| weekly spec/注册/API | Task 4 |
| 前端页/Mermaid/PNG | Task 5 |
| 文档/全量/真实验收 | Task 6 |

**Placeholder scan：** 无 TBD/TODO；实现步骤给出签名、关键分支、测试断言。

**Type consistency：** `PlanExtension(steps,token_cost,thought)`、`extend_plan(state)`、`ClusterResult/branches`、`WeeklyMindmapTaskSpec(task_input,llm_client,now)`、结果 JSON 字段在 Task 3/4/5 一致；前端 `WeeklyMindmapResult` 与后端 result 字段一一对应。

**已知取舍：** 真实库 7 天无笔记 → 用 30 天真实数据验收并如实记录；3 个知识点子图 + 导图恰好 12 行，超过会失败；mermaid 包体积增大记录在验收。