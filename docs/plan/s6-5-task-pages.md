# S6-5 前端任务进度页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `GET /agent/tasks` 分页列表与「Agent 任务」列表/详情页：状态筛选、自动刷新、步骤时间线（折叠输出/错误高亮）、失败建议、人工确认弹窗；导航用「Agent 任务」替换「学习导图」入口。

**Architecture:** 后端在 `agent_service.list_agent_tasks` 复用分页/排序设施，API 只加一个 student 读接口；前端 `TaskList.vue` 负责分页/筛选/2 s 轮询，`TaskDetail.vue` 负责 1 s 轮询、步骤渲染与确认；类型/API 封装集中在 `types/agent.ts`、`api/agent.ts`。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、Pydantic v2、Vue 3 + TS、Element Plus、Vitest。

**Spec:** `docs/spec/s6-5-task-pages.md`

## Global Constraints

- 只加 `GET /agent/tasks` 一个后端读接口；不改状态机/表/结果结构。
- 列表只查本人；`created_at DESC, id DESC`；`status/task_type` 筛选；page_size 1–100 默认 10。
- 轮询：列表 2 s（仅存在 pending/running）、详情 1 s（仅 pending/running）；终态/卸载停止。
- 不展示 `state_json`；结果 JSON 截断 4000 字；确认弹窗只通过/拒绝 + 备注。
- 导航用「Agent 任务」替换「学习导图」，保持 14 项；`/agent/mindmap` 路由保留。
- 不新增依赖；测试不连库/不发网络；每个 Task 先红后绿并提交。

---

### Task 1: 后端列表接口

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/api/v1/agent.py`
- Modify: `docs/API.md §10`
- Test: `backend/tests/test_agent_list_api.py`
- Test: `backend/tests/test_agent_service.py`（补 list）

**Interfaces:**
- Produces: `list_agent_tasks(session, *, user_id, status=None, task_type=None, page: PageParams, sort: SortParams) -> PageData[AgentTaskOut]`
- Produces: `GET /api/v1/agent/tasks`（200 `Envelope[PageData[AgentTaskOut]]`）

- [x] **Step 1: 写失败测试**

```python
"""S6-5 Agent 任务列表：筛选、分页、权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.common import PageData
from app.services import agent_service


class FakeSession:
    def __init__(self, user):  # noqa: ANN001
        self.user = user

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user


def _user(role="student"):  # noqa: ANN001
    user = User(username="agent_s65", nickname="a", grade="高二", role=role, password_hash="x")
    user.id = 50
    return user


def _client(user):  # noqa: ANN001
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _task(task_id=7, status="succeeded"):  # noqa: ANN001
    from app.models.agent_task import AgentTask
    task = AgentTask(user_id=50, task_type="weekly_mindmap", input_json={}, status=status)
    task.id = task_id
    task.created_at = datetime(2026, 11, 17, tzinfo=timezone.utc)
    task.steps_count = 4
    task.token_cost = 0
    task.error = None
    task.started_at = None
    task.finished_at = None
    return task


def test_list_returns_page_and_passes_filters(monkeypatch):
    captured = {}

    def fake_list(session, *, user_id, status, task_type, page, sort):  # noqa: ANN001
        captured.update(user_id=user_id, status=status, task_type=task_type, page=page, sort=sort)
        return PageData(items=[], total=0, page=page.page, page_size=page.page_size)

    monkeypatch.setattr(agent_service, "list_agent_tasks", fake_list)
    resp = _client(_user()).get(
        "/api/v1/agent/tasks",
        params={"status": "failed", "task_type": "weekly_mindmap", "page_size": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["page_size"] == 2
    assert captured["user_id"] == 50
    assert captured["status"] == "failed"
    assert captured["task_type"] == "weekly_mindmap"


def test_list_rejects_bad_status():
    resp = _client(_user()).get("/api/v1/agent/tasks", params={"status": "nope"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_list_teacher_forbidden():
    resp = _client(_user("teacher")).get("/api/v1/agent/tasks")
    assert resp.status_code == 403
```

`test_agent_service.py` 补：

```python
def test_list_agent_tasks_scopes_user_and_sort(monkeypatch):
    captured = {}

    def fake_page(session, stmt, page, *, item_model):  # noqa: ANN001
        captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
        captured["item_model"] = item_model
        from app.schemas.common import PageData
        return PageData(items=[], total=0, page=page.page, page_size=page.page_size)

    monkeypatch.setattr(agent_service, "paginate_query", fake_page)
    from app.utils.pagination import PageParams, SortParams
    agent_service.list_agent_tasks(
        object(), user_id=50, status="running", task_type="demo",
        page=PageParams(page=2, page_size=5), sort=SortParams(),
    )
    sql = captured["sql"]
    assert "agent_tasks.user_id =" in sql
    assert "agent_tasks.status =" in sql
    assert "agent_tasks.task_type =" in sql
    assert "ORDER BY agent_tasks.created_at DESC" in sql
    assert "agent_tasks.id DESC" in sql
```

- [x] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_list_api.py -q`
Expected: FAIL（404）

- [x] **Step 3: 实现 service**

```python
from app.schemas.agent import AgentTaskOut
from app.schemas.common import PageData
from app.utils.pagination import PageParams, SortParams, apply_sort, paginate_query

_AGENT_TASK_SORTABLE = {
    "created_at": AgentTask.created_at,
    "id": AgentTask.id,
}


def list_agent_tasks(
    session: Session,
    *,
    user_id: int,
    status: str | None,
    task_type: str | None,
    page: PageParams,
    sort: SortParams,
) -> PageData[AgentTaskOut]:
    stmt = select(AgentTask).where(AgentTask.user_id == user_id)
    if status:
        stmt = stmt.where(AgentTask.status == status)
    if task_type:
        stmt = stmt.where(AgentTask.task_type == task_type)
    stmt = apply_sort(
        stmt,
        sort_by=sort.sort_by or "created_at",
        order=sort.order if sort.sort_by else "desc",
        allowed=_AGENT_TASK_SORTABLE,
        default_sort="created_at",
    )
    # 同秒创建时用 id 兜底，避免翻页重复/漏行（S4-1/S4-5 同类坑）
    stmt = stmt.order_by(AgentTask.id.desc())
    return paginate_query(session, stmt, page, item_model=AgentTaskOut)
```

- [x] **Step 4: 实现 API**

```python
from typing import Literal
from fastapi import Query
from app.schemas.common import Envelope, PageData
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

AgentTaskStatusIn = Literal["pending", "running", "waiting_confirm", "succeeded", "failed"]


@router.get("/tasks", response_model=Envelope[PageData[AgentTaskOut]], summary="Agent 任务分页列表")
def list_agent_tasks(
    status: AgentTaskStatusIn | None = Query(None),
    task_type: str | None = Query(None, min_length=1, max_length=50),
    page: PageParams = Depends(page_params),
    sorting: SortParams = Depends(sort_params),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PageData[AgentTaskOut]]:
    data = agent_service.list_agent_tasks(
        session, user_id=current_user.id, status=status, task_type=task_type,
        page=page, sort=sorting,
    )
    return Envelope(trace_id=get_trace_id(), data=data)
```

- [x] **Step 5: 更新 API.md §10**

在 `GET /agent/tasks/{id}` 前加 `GET /agent/tasks` 契约：参数、`PageData` 形状、筛选/排序白名单、403/422。

- [x] **Step 6: 跑测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_agent_list_api.py tests/test_agent_service.py tests/test_agent_api.py -q`
Expected: PASS

- [x] **Step 7: 提交**

```bash
git add backend/app/services/agent_service.py backend/app/api/v1/agent.py \
  backend/tests/test_agent_list_api.py backend/tests/test_agent_service.py docs/API.md
git commit -m "feat(s6-5): Agent 任务分页列表接口"
```

---

### Task 2: 前端类型、API、状态映射与导图页类型守卫

**Files:**
- Modify: `web/src/types/agent.ts`
- Modify: `web/src/api/agent.ts`
- Modify: `web/src/api/agent.spec.ts`
- Create: `web/src/views/agent/status.ts`
- Create: `web/src/views/agent/status.spec.ts`
- Modify: `web/src/views/agent/WeeklyMindmap.vue`（用 `asWeeklyMindmapResult`）
- Test: `web/src/views/agent/WeeklyMindmap.spec.ts`（回归）

**Interfaces:**
- Produces: `AgentTaskPage`、`AgentTaskResult`、`asWeeklyMindmapResult(result)`、`statusLabel(status)`、`statusType(status)`
- Produces: `listAgentTasks(params)`、`confirmAgentTask(id, decision)`

- [x] **Step 1: 写失败测试**

`status.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { statusLabel, statusType } from './status'

describe('agent status mapping', () => {
  it('maps every status', () => {
    expect(statusLabel('pending')).toBe('排队中')
    expect(statusLabel('running')).toBe('生成中')
    expect(statusLabel('waiting_confirm')).toBe('等待确认')
    expect(statusLabel('succeeded')).toBe('已完成')
    expect(statusLabel('failed')).toBe('失败')
  })
  it('maps tag types', () => {
    expect(statusType('succeeded')).toBe('success')
    expect(statusType('failed')).toBe('danger')
    expect(statusType('waiting_confirm')).toBe('warning')
    expect(statusType('running')).toBe('primary')
    expect(statusType('pending')).toBe('info')
    expect(statusType('unknown')).toBe('info')
  })
})
```

`agent.spec.ts` 补：

```ts
it('lists tasks with filters', async () => {
  http.get.mockResolvedValue(envelope({ items: [], total: 0, page: 1, page_size: 10 }))
  await listAgentTasks({ page: 2, page_size: 10, status: 'failed', task_type: 'weekly_mindmap' })
  expect(http.get).toHaveBeenCalledWith('/api/v1/agent/tasks', {
    params: { page: 2, page_size: 10, status: 'failed', task_type: 'weekly_mindmap' },
  })
})

it('confirms a task', async () => {
  http.post.mockResolvedValue(envelope({ id: 5, status: 'pending' }))
  await confirmAgentTask(5, { approved: true, comment: '可以' })
  expect(http.post).toHaveBeenCalledWith('/api/v1/agent/tasks/5/confirm', {
    approved: true, comment: '可以',
  })
})
```

- [x] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/views/agent/status.spec.ts src/api/agent.spec.ts`
Expected: FAIL（模块/方法不存在）

- [x] **Step 3: 实现类型/API/状态**

- `AgentTaskResult = WeeklyMindmapResult | DemoAgentResult | Record<string, unknown> | null`；`AgentTaskDetail.result: AgentTaskResult`。
- `asWeeklyMindmapResult(result: AgentTaskResult): WeeklyMindmapResult | null`：`result && result.task_type === 'weekly_mindmap'` 时断言。
- `DemoAgentResult { summary: string; artifacts: Record<string, unknown>; citations: unknown[] }`。
- `status.ts` 返回中文标签与 Element tag type（`primary` 用于 running；Element Plus tag 支持 primary/info/success/warning/danger）。
- `api/agent.ts` 加 list/confirm；参数对象去掉 undefined 字段再传？axios 会忽略 undefined query；直接传即可。
- `WeeklyMindmap.vue`：`result = computed(() => asWeeklyMindmapResult(task.value?.result ?? null))`。

- [x] **Step 4: 跑测试**

Run: `cd web && npm run test:run -- src/api/agent.spec.ts src/views/agent/status.spec.ts src/views/agent/WeeklyMindmap.spec.ts`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add web/src/types/agent.ts web/src/api/agent.ts web/src/api/agent.spec.ts \
  web/src/views/agent/status.ts web/src/views/agent/status.spec.ts web/src/views/agent/WeeklyMindmap.vue
git commit -m "feat(s6-5): Agent 任务类型、列表/确认 API 与状态映射"
```

---

### Task 3: 任务列表页 + 路由/导航

**Files:**
- Create: `web/src/views/agent/TaskList.vue`
- Create: `web/src/views/agent/TaskList.spec.ts`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/layouts/nav.ts`
- Modify: `web/src/layouts/MainLayout.spec.ts`（导航数量不变，文案替换）

**Interfaces:**
- Produces: `/agent/tasks`（nav `agent-tasks`）、表格/筛选/分页/2 s 轮询

- [x] **Step 1: 写失败测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentTaskPage } from '@/types/agent'

const api = vi.hoisted(() => ({ listAgentTasks: vi.fn(), getAgentTask: vi.fn(), createAgentTask: vi.fn(), confirmAgentTask: vi.fn() }))
vi.mock('@/api/agent', () => api)
const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => ({ params: {} }) }))

import TaskList from './TaskList.vue'

function page(overrides: Partial<AgentTaskPage> = {}): AgentTaskPage {
  return {
    items: [
      { id: 5, task_type: 'weekly_mindmap', status: 'succeeded', steps_count: 10, token_cost: 2296, error: null,
        created_at: '2026-11-17T07:50:52Z', started_at: null, finished_at: '2026-11-17T07:51:08Z' },
      { id: 6, task_type: 'demo', status: 'failed', steps_count: 6, token_cost: 0, error: '用户拒绝确认',
        created_at: '2026-11-17T07:55:31Z', started_at: null, finished_at: null },
    ],
    total: 2, page: 1, page_size: 10, ...overrides,
  }
}

function mountPage() { return mount(TaskList, { global: { plugins: [ElementPlus] } }) }

beforeEach(() => { api.listAgentTasks.mockReset(); api.listAgentTasks.mockResolvedValue(page()); push.mockClear() })
afterEach(() => { vi.useRealTimers() })

describe('TaskList', () => {
  it('renders tasks and labels', async () => {
    const wrapper = mountPage(); await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalled()
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('学习导图')
  })

  it('filters and reloads', async () => {
    const wrapper = mountPage(); await flushPromises()
    await wrapper.find('[data-testid="refresh"]').trigger('click'); await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)
  })

  it('opens detail on row click', async () => {
    const wrapper = mountPage(); await flushPromises()
    await wrapper.find('[data-testid="task-row-5"]').trigger('click')
    expect(push).toHaveBeenCalledWith('/agent/tasks/5')
  })

  it('polls while a running task exists and stops after terminal', async () => {
    vi.useFakeTimers()
    api.listAgentTasks.mockResolvedValueOnce(page({ items: [{ ...page().items[0]!, status: 'running' }] }))
    api.listAgentTasks.mockResolvedValue(page())
    mountPage(); await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(4000); await flushPromises()
    expect(api.listAgentTasks).toHaveBeenCalledTimes(2)
  })
})
```

- [x] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/views/agent/TaskList.spec.ts`
Expected: FAIL（组件不存在）

- [x] **Step 3: 实现 TaskList**

- 结构：`page-head`（标题/说明/刷新/生成学习导图）、筛选 `el-select`（status/task_type）+ `el-button` 查询、`el-table` + `el-pagination`、空态、error alert。
- 数据：`items/total/page/pageSize/filters`；`load()` 调 `listAgentTasks`，失败设 error。
- 轮询：`hasRunning = items.some(status pending/running)`；`schedule()` 2 s；`load` 后按新数据决定是否继续；卸载 clear；筛选/分页时 `stop()` 再 load。
- 行：`:row-class-name`? 用 `@row-click="open(row)"`；ID 列加 `data-testid` 不方便，改为自定义列：
  ```vue
  <el-table-column label="ID" width="90">
    <template #default="{ row }">
      <span class="mono" :data-testid="`task-row-${row.id}`" @click="open(row)">#{{ row.id }}</span>
    </template>
  </el-table-column>
  ```
  行点击也调用 open（避免测试依赖 tr）。
- 状态 tag 用 `statusLabel/statusType`。
- 导航：`nav.ts` 删除「学习导图」项，新增 `{ label:'Agent 任务', name:'agent-tasks', path:'/agent/tasks' }`（仍在报告之后）。
- 路由：`agent/tasks`（name `agent-tasks`）、`agent/tasks/:id(\\d+)`（name `agent-task-detail`），student；放在 mindmap 路由旁。
- MainLayout 导航数量仍 14，文案断言若存在「学习导图」需改为「Agent 任务」；搜索测试里的文案。

- [x] **Step 4: 跑测试 + 构建**

Run: `cd web && npm run test:run -- src/views/agent/TaskList.spec.ts src/layouts/MainLayout.spec.ts`
Run: `cd web && npm run build`
Expected: PASS / build 0

- [x] **Step 5: 提交**

```bash
git add web/src/views/agent/TaskList.vue web/src/views/agent/TaskList.spec.ts \
  web/src/router/index.ts web/src/layouts/nav.ts web/src/layouts/MainLayout.spec.ts
git commit -m "feat(s6-5): Agent 任务列表页与导航"
```

---

### Task 4: 任务详情页（时间线/折叠/失败/确认）

**Files:**
- Create: `web/src/views/agent/TaskDetail.vue`
- Create: `web/src/views/agent/TaskDetail.spec.ts`

**Interfaces:**
- Consumes: `getAgentTask`、`confirmAgentTask`、`statusLabel/statusType`、`asWeeklyMindmapResult`
- Produces: `/agent/tasks/:id` 详情页、确认弹窗与轮询

- [x] **Step 1: 写失败测试**

```ts
const api = vi.hoisted(() => ({ getAgentTask: vi.fn(), confirmAgentTask: vi.fn() }))
vi.mock('@/api/agent', () => api)
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '5' } }),
  useRouter: () => ({ push: vi.fn() }),
}))
import TaskDetail from './TaskDetail.vue'

function detail(overrides: Partial<AgentTaskDetail> = {}): AgentTaskDetail { ... }

it('renders step timeline and weekly result link', async () => {
  api.getAgentTask.mockResolvedValue(detail())
  const wrapper = mount(TaskDetail, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('计划')
  expect(wrapper.findAll('[data-testid="step-row"]')).toHaveLength(2)
  expect(wrapper.get('[data-testid="mindmap-link"]').attributes('href')).toBe('/agent/mindmap/5')
})

it('highlights and expands error step', async () => {
  api.getAgentTask.mockResolvedValue(detail({ status: 'failed', error: '工具失败', steps: [errorStep] }))
  const wrapper = mount(TaskDetail, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.find('.step-error').exists()).toBe(true)
  expect(wrapper.text()).toContain('工具执行失败')
  expect(wrapper.text()).toContain('重新创建任务')
})

it('confirms a waiting task', async () => {
  api.getAgentTask.mockResolvedValue(detail({ status: 'waiting_confirm' }))
  api.confirmAgentTask.mockResolvedValue({ ... })
  const wrapper = mount(TaskDetail, { attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
  await wrapper.get('[data-testid="confirm-approve"]').trigger('click')
  await flushPromises()
  const button = Array.from(document.querySelectorAll('button')).find((el) => el.textContent?.includes('提交'))
  button?.click()
  await flushPromises()
  expect(api.confirmAgentTask).toHaveBeenCalledWith(5, { approved: true, comment: '' })
})
```

- [x] **Step 2: 运行确认失败**

Run: `cd web && npm run test:run -- src/views/agent/TaskDetail.spec.ts`
Expected: FAIL

- [x] **Step 3: 实现详情页**

- 头部：返回 `/agent/tasks`、`任务 #id`、类型标签、状态 tag、步骤/token/时间。
- `load(id)`、`poll()` 1 s；终态/waiting 停止；失败设 error。
- 步骤列表：
  ```vue
  <transition-group name="step" tag="ol" class="timeline">
    <li v-for="step in steps" :key="step.step_no" :data-testid="'step-row'"
        :class="['step', step.status === 'error' ? 'step-error' : '']">
      <div class="step-head"><span class="step-no">#{{ step.step_no }}</span>
        <el-tag size="small" :type="stepTag(step.status)">{{ step.status }}</el-tag>
        <el-tag v-if="step.tool_name" size="small" effect="plain">{{ step.tool_name }}</el-tag>
        <span v-if="step.latency_ms !== null" class="latency">{{ step.latency_ms }} ms</span>
      </div>
      <p class="thought">{{ step.thought || '—' }}</p>
      <el-collapse v-if="step.tool_input || step.tool_output" :model-value="step.status==='error' ? ['io'] : []">
        <el-collapse-item name="io" title="工具入参 / 出参">
          <pre v-if="step.tool_input">入参：{{ pretty(step.tool_input) }}</pre>
          <pre v-if="step.tool_output">出参：{{ pretty(step.tool_output) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </li>
  </transition-group>
  ```
  - `pretty(value)` 截断 4000 字。
  - 自动滚到最新：`watch(steps.length)`，仅当 `running` 且用户接近底部（`window.innerHeight + scrollY >= document.body.offsetHeight - 80`）时 `lastStepRef?.scrollIntoView?.({block:'nearest'})`（jsdom 无此方法时用可选调用）。
- 结果区：`weekly = computed(() => asWeeklyMindmapResult(task.result))`；有 weekly 显示摘要/引用数/degraded/`<a data-testid="mindmap-link" :href="'/agent/mindmap/'+id">查看学习导图</a>`；demo 结果折叠 JSON。
- failed：`el-alert :title="task.error"` + 建议文本 + 「重新创建学习导图」（跳 `/agent/mindmap`）+ 返回列表。
- waiting_confirm：alert + `data-testid="confirm-approve"`/`confirm-reject` 打开弹窗；弹窗备注（≤500）、提交调 `confirmAgentTask(id,{approved,comment})`；成功后关闭并 `load` 恢复轮询；失败清 loading 由 http 统一提示。
- 轮询在终态停止；卸载清理。

- [x] **Step 4: 跑测试 + 全量前端**

Run: `cd web && npm run test:run -- src/views/agent/TaskDetail.spec.ts`
Run: `cd web && npm run test:run`
Run: `cd web && npm run build`
Expected: 全绿 / build 0

- [x] **Step 5: 提交**

```bash
git add web/src/views/agent/TaskDetail.vue web/src/views/agent/TaskDetail.spec.ts
git commit -m "feat(s6-5): Agent 任务详情页、步骤时间线与确认弹窗"
```

---

### Task 5: 文档、全量测试与真实验收

**Files:**
- Create: `docs/AGENT_TASKS_UI.md`
- Modify: `docs/DECISIONS.md`（D-068）
- Modify: `docs/PROGRESS.md`
- Modify: `AGENTS.md` §9.6
- Create: `.sdd/s6-5/acceptance-evidence.md` + 截图

- [ ] **Step 1: 文档**

- `AGENT_TASKS_UI.md`：列表/详情交互、轮询口径、确认流程、失败态、导航替换、边界。
- D-068：列表接口新增、导航替换、轮询而非 SSE、确认弹窗字段、验收数字。
- PROGRESS：S6-5 完成、下一步 S6-6、导航文案。
- AGENTS §9.6 追加任务页锚点。

- [ ] **Step 2: 全量测试**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../web && npm run test:run && npm run build
```

记录精确数字（后端 S6-3 基线 1564，前端 370/62）。

- [ ] **Step 3: 真实后端验收**

启动 worker/uvicorn 后：

```bash
GET /api/v1/agent/tasks?page=1&page_size=10
GET /api/v1/agent/tasks?status=failed
GET /api/v1/agent/tasks?task_type=weekly_mindmap&page_size=2
GET /api/v1/agent/tasks?page=2&page_size=2
```

断言 total/items/翻页不重复；teacher 403、非法 status 422。

- [ ] **Step 4: 真实 Chrome 验收**

- `/agent/tasks`：列表行、状态颜色、筛选、分页；新建 demo 任务观察行 pending→succeeded（2 s 自动刷新）。
- 打开 weekly 任务 5：10 步时间线、折叠入参/出参、摘要/引用、导图链接。
- 打开失败任务 3/6：error 步红色高亮且默认展开，显示建议。
- 新建 demo `require_confirm=true`：详情等待确认 → 弹窗通过 → 轮询 succeeded；再建一个拒绝 → failed。
- 步骤逐条出现：新建 demo 3 步任务后在详情页记录步骤数 0→2→4→…（截图/文字）；console error 0、无横向溢出。
- 截图 `.sdd/s6-5/task-list.png`、`task-detail.png`、`task-failed.png`、`task-confirm.png`。

- [ ] **Step 5: 证据与提交**

`.sdd/s6-5/acceptance-evidence.md` 记录 pytest/vitest/build、HTTP 响应摘要、Chrome 结果与失败修复。

```bash
git add docs/AGENT_TASKS_UI.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md
git commit -m "docs(s6-5): 任务页文档、D-068 与验收记录"
```

---

## Self-Review

**Spec coverage：**

| spec 章节 | Task |
|---|---|
| 后端列表接口 | Task 1 |
| 类型/API/状态映射 | Task 2 |
| 任务列表页/导航 | Task 3 |
| 任务详情/时间线/确认 | Task 4 |
| 文档/全量/真实验收 | Task 5 |

**Placeholder scan：** 无 TBD/TODO；关键函数签名、接口参数、测试断言已给出。

**Type consistency：** `AgentTaskPage`、`AgentTaskResult`、`asWeeklyMindmapResult`、`listAgentTasks`、`confirmAgentTask`、`statusLabel/statusType` 在 Task 2/3/4 一致；后端 `list_agent_tasks` 参数与 API 路由一致。

**已知取舍：** 列表轮询 2 s、详情 1 s；失败不原地重试；`state_json` 不展示；导航替换而非新增。