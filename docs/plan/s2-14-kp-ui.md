# S2-14 前端知识点树管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/knowledge` 从占位页替换为知识点树 + 待确认对齐工作台：教师/管理员可增删改和拖拽，学生只读，待确认卡片支持键盘连续处理 20 条。

**Architecture:** 后端在现有知识点树上补一个原子的 `PUT /kp/order`（移动/排序）和待确认列表的 300 字摘要字段，不改表；前端用 `KnowledgeView` 管 tab/学科，`Tree` 管 el-tree 与 CRUD/拖拽，`PendingAlign` + `usePendingAlign` 管单卡队列和键盘，登录落点按角色分流。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2；Vue 3 + TypeScript + Element Plus + Vitest；不新增依赖。

**Spec:** `docs/spec/s2-14-kp-ui.md`

## Global Constraints

- 不新增数据库迁移、不新增前后端依赖；接口变化同步 `docs/API.md`。
- 知识点写接口只允许 `admin/teacher`；学生只读；所有查询/写入仍显式按 subject 隔离。
- 拖拽统一走 `PUT /api/v1/kp/order`，一次请求完成跨父级移动 + 目标同级排序；前端成功后必须重新加载树。
- 根节点（`parent_id === null`）锁定：不能拖拽、不能删除；前端限制，后端仍按通用树规则校验。
- 待确认一次只显示一张卡；`Enter` 确认、`Backspace` 忽略；输入框/弹窗内不触发。
- `note_excerpt` 只读派生：`strip()` 后前 300 字，超出追加 `…`，不新增数据库列。
- `http.ts` 已统一弹错；组件只维护局部 loading/empty/error，不重复弹窗。
- 测试数据明显假、结构真；外部 LLM/网络调用全部 mock。
- 每个任务结束提交一次；Conventional Commits 带任务号；用户负责 `git push`。
- 真实联调使用临时 teacher/student 和临时待确认数据，结束后清理；不清理用户真实数据。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `backend/app/schemas/kp.py` | 修改 | `KpOrderIn` |
| `backend/app/services/kp_service.py` | 修改 | `reorder_children` 原子移动/排序 |
| `backend/app/api/v1/kp.py` | 修改 | `PUT /kp/order` |
| `backend/app/schemas/kp_align.py` | 修改 | `note_excerpt` 300 字派生 |
| `backend/tests/test_kp_service.py` | 修改 | 排序/移动/非法树结构测试 |
| `backend/tests/test_kp_api.py` | 修改 | 排序接口权限/204/422 |
| `backend/tests/test_align_api.py` | 修改 | 摘要字段与截断测试 |
| `docs/API.md` | 修改 | 排序接口、摘要示例 |
| `web/src/types/kp.ts` | 修改 | 树、CRUD、排序、待确认类型 |
| `web/src/api/kp.ts` | 修改 | 8 个知识点/对齐 API 封装 |
| `web/src/utils/redirect.ts` | 修改 | 按角色默认落点 |
| `web/src/views/LoginView.vue` | 修改 | 教师/管理员默认 `/knowledge` |
| `web/src/views/kp/treeUtils.ts` | 新建 | 树纯函数：查找、兄弟、子树高度、drop 规则 |
| `web/src/views/kp/treeUtils.spec.ts` | 新建 | 纯函数测试 |
| `web/src/components/kp/KpNodeDialog.vue` | 新建 | 新增/编辑表单 |
| `web/src/components/kp/KpNodeDialog.spec.ts` | 新建 | 表单校验/提交/编辑只读 |
| `web/src/views/kp/Tree.vue` | 新建 | el-tree、搜索、CRUD、拖拽 |
| `web/src/views/kp/Tree.spec.ts` | 新建 | 角色只读、CRUD、拖拽参数 |
| `web/src/views/kp/usePendingAlign.ts` | 新建 | 待确认队列状态机 |
| `web/src/views/kp/PendingAlign.vue` | 新建 | 单卡 UI、键盘、空态 |
| `web/src/views/kp/PendingAlign.spec.ts` | 新建 | 确认/忽略、20 条连续处理 |
| `web/src/views/kp/KnowledgeView.vue` | 新建 | tab、学科选择、页面壳 |
| `web/src/views/kp/KnowledgeView.spec.ts` | 新建 | 学科加载/tab/错误态 |
| `web/src/router/index.ts` | 修改 | `/knowledge` 指向真实页面 |
| `web/src/utils/redirect.spec.ts` | 修改 | 角色默认落点 |
| `web/src/views/LoginView.spec.ts` | 修改 | 教师登录落点 |
| `docs/DECISIONS.md` | 修改 | D-034 |
| `docs/PROGRESS.md` | 修改 | 交付记录/测试数字/已知限制 |
| `docs/AI协作开发实施计划.md` | 修改 | S2-14 勾选 |
| `docs/spec/s2-14-kp-ui.md` | 修改 | 执行记录 |
| `docs/plan/s2-14-kp-ui.md` | 修改 | 执行记录 |

---

### Task 1: 后端原子排序/移动接口

**Files:**
- Modify: `backend/app/schemas/kp.py`
- Modify: `backend/app/services/kp_service.py`
- Modify: `backend/app/api/v1/kp.py`
- Modify: `backend/tests/test_kp_service.py`
- Modify: `backend/tests/test_kp_api.py`
- Modify: `docs/API.md`

**Interfaces:**
- Consumes: `KnowledgePoint`, `_subtree_height`, `_reassign_descendant_levels`, `require_role`, `get_current_user`, `get_db`.
- Produces:
  - `KpOrderIn(parent_id: int | None, ordered_ids: list[int], moved_id: int | None = None)`
  - `reorder_children(session, *, parent_id, ordered_ids, moved_id=None) -> None`
  - `PUT /api/v1/kp/order -> 204`

- [x] **Step 1: 写后端失败测试**

在 `backend/tests/test_kp_service.py` 末尾追加：

```python
def test_reorder_children_updates_sibling_order() -> None:
    root = _kp(1, "MATH", 1, None)
    first = _kp(2, "MATH-A", 2, 1, order_no=0)
    second = _kp(3, "MATH-B", 2, 1, order_no=1)
    third = _kp(4, "MATH-C", 2, 1, order_no=2)
    session = FakeSession(rows=[root, first, second, third], get_map={1: root})

    kp_service.reorder_children(
        session,  # type: ignore[arg-type]
        parent_id=1,
        ordered_ids=[4, 2, 3],
    )

    assert [first.order_no, second.order_no, third.order_no] == [1, 2, 0]
    assert session.commits == 1


def test_reorder_children_moves_subtree_and_recalculates_levels() -> None:
    root = _kp(1, "MATH", 1, None)
    target = _kp(2, "MATH-FUNC", 2, 1)
    moving = _kp(3, "MATH-GEO", 1, None, order_no=1)
    child = _kp(4, "MATH-GEO-01", 2, 3)
    sibling = _kp(5, "MATH-FUNC-01", 3, 2)
    session = FakeSession(
        rows=[root, target, moving, child, sibling],
        get_map={2: target},
    )

    kp_service.reorder_children(
        session,  # type: ignore[arg-type]
        parent_id=2,
        ordered_ids=[5, 3],
        moved_id=3,
    )

    assert moving.parent_id == 2
    assert moving.level == 3
    assert child.level == 4
    assert sibling.order_no == 0
    assert moving.order_no == 1
    assert root.order_no == 0
    assert session.commits == 1


def test_reorder_children_rejects_duplicate_ids() -> None:
    with pytest.raises(InvalidParamError, match="不能重复"):
        kp_service.reorder_children(
            FakeSession(),  # type: ignore[arg-type]
            parent_id=None,
            ordered_ids=[1, 1],
        )


def test_reorder_children_rejects_incomplete_sibling_set() -> None:
    root = _kp(1, "MATH", 1, None)
    first = _kp(2, "MATH-A", 2, 1)
    second = _kp(3, "MATH-B", 2, 1)
    session = FakeSession(rows=[root, first, second], get_map={1: root})

    with pytest.raises(InvalidParamError, match="全部子节点"):
        kp_service.reorder_children(
            session,  # type: ignore[arg-type]
            parent_id=1,
            ordered_ids=[2],
        )


def test_reorder_children_rejects_cycle() -> None:
    root = _kp(1, "MATH", 1, None)
    parent = _kp(2, "MATH-A", 2, 1)
    child = _kp(3, "MATH-A-01", 3, 2)
    session = FakeSession(rows=[root, parent, child], get_map={3: child})

    with pytest.raises(InvalidParamError, match="子节点"):
        kp_service.reorder_children(
            session,  # type: ignore[arg-type]
            parent_id=3,
            ordered_ids=[2],
            moved_id=2,
        )


def test_reorder_children_rejects_missing_parent() -> None:
    with pytest.raises(NotFoundError, match="父节点不存在"):
        kp_service.reorder_children(
            FakeSession(),  # type: ignore[arg-type]
            parent_id=99,
            ordered_ids=[1],
        )
```

在 `backend/tests/test_kp_api.py` 追加：

```python
def test_reorder_kp_teacher_returns_204(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    captured: dict[str, object] = {}

    def fake_reorder(session, *, parent_id, ordered_ids, moved_id=None):
        captured.update(
            parent_id=parent_id,
            ordered_ids=ordered_ids,
            moved_id=moved_id,
        )

    monkeypatch.setattr(kp_service, "reorder_children", fake_reorder)
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": [3, 2], "moved_id": 3},
        headers=_headers(user),
    )
    assert resp.status_code == 204
    assert resp.content == b""
    assert captured == {"parent_id": 1, "ordered_ids": [3, 2], "moved_id": 3}


def test_reorder_kp_accepts_root_parent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    captured: dict[str, object] = {}

    def fake_reorder(session, *, parent_id, ordered_ids, moved_id=None):
        captured.update(parent_id=parent_id, ordered_ids=ordered_ids)

    monkeypatch.setattr(kp_service, "reorder_children", fake_reorder)
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": None, "ordered_ids": [2, 1]},
        headers=_headers(user),
    )
    assert resp.status_code == 204
    assert captured["parent_id"] is None


def test_reorder_kp_forbidden_for_student(client: TestClient) -> None:
    user = _user(role="student")
    _wire(FakeSession(user=user))
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": [2]},
        headers=_headers(user),
    )
    assert resp.status_code == 403


def test_reorder_kp_rejects_empty_order(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.put(
        "/api/v1/kp/order",
        json={"parent_id": 1, "ordered_ids": []},
        headers=_headers(user),
    )
    assert resp.status_code == 422
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_kp_service.py tests/test_kp_api.py -q
```

Expected: 新用例失败；`KpOrderIn` 不存在、`PUT /kp/order` 404/405、`reorder_children` 不存在。

- [x] **Step 3: 增加 schema**

`backend/app/schemas/kp.py` 末尾追加：

```python
class KpOrderIn(BaseModel):
    """拖拽落库：目标父级 + 完整目标兄弟顺序，可顺带移动一个节点。"""

    parent_id: int | None = Field(description="目标父节点；null 表示根级")
    ordered_ids: list[int] = Field(min_length=1, max_length=200)
    moved_id: int | None = Field(default=None, ge=1)
```

- [x] **Step 4: 实现 service**

`backend/app/services/kp_service.py` 在 `delete_kp` 后、`_subtree_height` 前增加：

```python
def reorder_children(
    session: Session,
    *,
    parent_id: int | None,
    ordered_ids: list[int],
    moved_id: int | None = None,
) -> None:
    """一次事务内移动节点并归一化目标兄弟顺序；前端不承担排序正确性。"""
    ordered = list(ordered_ids)
    if not ordered:
        raise InvalidParamError("ordered_ids 不能为空")
    if len(set(ordered)) != len(ordered):
        raise InvalidParamError("ordered_ids 不能重复")
    if moved_id is not None and moved_id not in ordered:
        raise InvalidParamError("被移动节点必须包含在 ordered_ids 中")
    if moved_id is not None and parent_id == moved_id:
        raise InvalidParamError("父节点不能是自身")

    parent: KnowledgePoint | None = None
    if parent_id is not None:
        parent = session.get(KnowledgePoint, parent_id)
        if parent is None:
            raise NotFoundError("父节点不存在")

    ids = set(ordered)
    if moved_id is not None:
        ids.add(moved_id)
    found = {
        row.id: row
        for row in session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
        )
        if row.id in ids
    }
    missing = ids - set(found)
    if missing:
        raise NotFoundError("知识点不存在")

    first = next(iter(found.values()))
    subject_id = parent.subject_id if parent is not None else first.subject_id
    if any(row.subject_id != subject_id for row in found.values()):
        raise InvalidParamError("知识点不属于同一学科")
    if parent is not None and parent.subject_id != subject_id:
        raise InvalidParamError("父节点不属于同一学科")

    rows = list(
        session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.subject_id == subject_id)
        )
    )
    by_id = {row.id: row for row in rows}
    if parent_id is not None and parent_id not in by_id:
        raise NotFoundError("父节点不存在")
    if any(kp_id not in by_id for kp_id in ids):
        raise NotFoundError("知识点不存在")

    old_parent_id: int | None = None
    if moved_id is not None:
        moved = by_id[moved_id]
        old_parent_id = moved.parent_id
        cursor = parent
        while cursor is not None:
            if cursor.id == moved.id:
                raise InvalidParamError("不能移动到自己的子节点下")
            cursor = by_id.get(cursor.parent_id)
        new_level = 1 if parent is None else parent.level + 1
        height = _subtree_height(rows, moved.id)
        if new_level + height - 1 > MAX_LEVEL:
            raise InvalidParamError(f"移动后子树超过 {MAX_LEVEL} 级")
        moved.parent_id = parent_id
        moved.level = new_level
        _reassign_descendant_levels(rows, moved)

    target_ids = {row.id for row in rows if row.parent_id == parent_id}
    if target_ids != set(ordered):
        raise InvalidParamError("ordered_ids 必须包含目标父级的全部子节点")

    if moved_id is not None and old_parent_id != parent_id:
        source_siblings = sorted(
            (row for row in rows if row.parent_id == old_parent_id),
            key=lambda row: (row.order_no, row.id),
        )
        for index, row in enumerate(source_siblings):
            row.order_no = index

    for index, kp_id in enumerate(ordered):
        by_id[kp_id].order_no = index
    session.commit()
```

- [x] **Step 5: 增加路由**

`backend/app/api/v1/kp.py`：

1. 在 schema import 中加 `KpOrderIn`：

```python
from app.schemas.kp import KpCreate, KpNodeOut, KpOrderIn, KpTreeOut, KpUpdate, SubjectOut
```

2. 在 `delete_kp` 后增加：

```python
@router.put("/order", status_code=204, summary="批量排序/移动知识点")
def reorder_kp(
    payload: KpOrderIn,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> None:
    kp_service.reorder_children(
        session,
        parent_id=payload.parent_id,
        ordered_ids=payload.ordered_ids,
        moved_id=payload.moved_id,
    )
```

- [x] **Step 6: 跑后端测试**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_kp_service.py tests/test_kp_api.py -q
```

Expected: 全绿；旧 S2-9 用例不回归。

- [x] **Step 7: 更新 API.md**

在 `docs/API.md` §4 的 `DELETE /kp/{kp_id}` 后增加：

```markdown
### PUT /api/v1/kp/order
- 权限：admin / teacher
- 类型：同步，单事务
- 入参：`parent_id`（null 表示根级）、`ordered_ids`（1–200，目标父级完整子节点顺序）、`moved_id`（可选，被移动节点）
- 语义：传 `moved_id` 时先改父级、重算层级，再按 `ordered_ids` 写 `order_no`；不传只做同级排序
- 成功：204 无响应体
- 错误：父级/节点不存在 404；重复/缺兄弟/跨学科/成环/超 4 级 422；非教师/管理员 403
- 说明：`ordered_ids` 必须包含目标父级的全部子节点；跨父级移动时源父级剩余节点会归一化
```

- [x] **Step 8: 提交**

```bash
git add backend/app/schemas/kp.py backend/app/services/kp_service.py \
  backend/app/api/v1/kp.py backend/tests/test_kp_service.py \
  backend/tests/test_kp_api.py docs/API.md
git commit -m "feat(s2-14): 知识点批量排序与移动接口"
```

---

### Task 2: 待确认摘要字段

**Files:**
- Modify: `backend/app/schemas/kp_align.py`
- Modify: `backend/tests/test_align_api.py`
- Modify: `docs/API.md`

**Interfaces:**
- Consumes: `PendingAlignOut` 现有 `AliasPath` 展平。
- Produces:
  - `PendingAlignOut.note_excerpt: str`（空串默认，最长 301 字符含省略号）
  - `GET /kp/align/pending` 响应新增字段。

- [x] **Step 1: 写失败测试**

在 `backend/tests/test_align_api.py` 的 import 中加入 `from types import SimpleNamespace`，然后追加：

```python
def test_pending_align_out_truncates_note_excerpt() -> None:
    row = SimpleNamespace(
        note_id=3,
        kp_id=12,
        confidence=0.68,
        note=SimpleNamespace(
            title="函数单调性笔记",
            content_text="  " + "知" * 350 + "  ",
        ),
        knowledge_point=SimpleNamespace(name="函数的单调性", code="MATH-FUNC-02"),
    )

    out = PendingAlignOut.model_validate(row)

    assert out.note_excerpt == "知" * 300 + "…"
    assert len(out.note_excerpt) == 301


def test_pending_align_out_keeps_short_excerpt() -> None:
    row = SimpleNamespace(
        note_id=3,
        kp_id=12,
        confidence=0.68,
        note=SimpleNamespace(title="短笔记", content_text="  函数图像  "),
        knowledge_point=SimpleNamespace(name="函数", code="MATH-FUNC"),
    )

    out = PendingAlignOut.model_validate(row)

    assert out.note_excerpt == "函数图像"
```

并把 `test_pending_list_returns_page` 中的 `PendingAlignOut(...)` 增加：

```python
                    note_excerpt="函数单调性笔记摘要",
```

断言增加：

```python
    assert resp.json()["data"]["items"][0]["note_excerpt"] == "函数单调性笔记摘要"
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_align_api.py -q
```

Expected: 新用例失败；`note_excerpt` 字段不存在。

- [x] **Step 3: 实现 schema**

`backend/app/schemas/kp_align.py` 把 import 改为：

```python
from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator
```

`PendingAlignOut` 增加字段与校验：

```python
    note_excerpt: str = Field(
        default="",
        validation_alias=AliasPath("note", "content_text"),
    )

    @field_validator("note_excerpt", mode="before")
    @classmethod
    def _truncate_excerpt(cls, value: object) -> str:
        text = str(value or "").strip()
        if len(text) <= 300:
            return text
        return f"{text[:300]}…"
```

- [x] **Step 4: 跑测试**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_align_api.py tests/test_align_service.py -q
```

Expected: 全绿；既有 pending 分页/权限不回归。

- [x] **Step 5: 更新 API.md**

`docs/API.md` §4 的 `GET /kp/align/pending` 返回示例增加：

```json
{
  "note_id": 3,
  "note_title": "函数单调性笔记",
  "note_excerpt": "函数单调性：设函数 f(x) 在区间 D 上……",
  "kp_id": 12,
  "kp_name": "函数的单调性",
  "kp_code": "MATH-FUNC-02",
  "confidence": 0.68
}
```

并在字段说明中写：

```markdown
- `note_excerpt`：笔记正文去首尾空白后前 300 字；超出部分以 `…` 结尾；空正文为空串
```

- [x] **Step 6: 提交**

```bash
git add backend/app/schemas/kp_align.py backend/tests/test_align_api.py docs/API.md
git commit -m "feat(s2-14): 待确认对齐返回笔记摘要"
```

---

### Task 3: 前端类型、API 封装与角色登录落点

**Files:**
- Modify: `web/src/types/kp.ts`
- Modify: `web/src/api/kp.ts`
- Modify: `web/src/utils/redirect.ts`
- Modify: `web/src/views/LoginView.vue`
- Modify: `web/src/utils/redirect.spec.ts`
- Modify: `web/src/views/LoginView.spec.ts`

**Interfaces:**
- Consumes: `http`, `ApiEnvelope`, `PageData`, `UserRole`.
- Produces:
  - `KpNode`, `KpTree`, `KpCreatePayload`, `KpUpdatePayload`, `KpOrderPayload`, `KpDialogPayload`, `PendingAlign`, `AlignPair`, `AlignBatchResult`
  - `getKpTree`, `createKp`, `updateKp`, `deleteKp`, `reorderKp`, `listPendingAlign`, `confirmAlign`, `rejectAlign`
  - `defaultRedirectForRole(role)`, `safeRedirect(raw, fallback?)`

- [x] **Step 1: 写失败测试**

`web/src/utils/redirect.spec.ts` 改为：

```ts
import { describe, expect, it } from 'vitest'

import { defaultRedirectForRole, safeRedirect } from './redirect'

describe('safeRedirect', () => {
  it('keeps same-site path with query', () => {
    expect(safeRedirect('/notes?x=1')).toBe('/notes?x=1')
  })

  it('rejects protocol-relative and backslash paths', () => {
    expect(safeRedirect('//evil.com')).toBe('/notes')
    expect(safeRedirect('/\\evil.com')).toBe('/notes')
  })

  it('rejects non-string and empty values', () => {
    expect(safeRedirect(undefined)).toBe('/notes')
    expect(safeRedirect('')).toBe('/notes')
  })

  it('uses the supplied fallback for missing or unsafe redirects', () => {
    expect(safeRedirect(undefined, '/knowledge')).toBe('/knowledge')
    expect(safeRedirect('//evil.com', '/knowledge')).toBe('/knowledge')
  })
})

describe('defaultRedirectForRole', () => {
  it('sends teachers and admins to knowledge', () => {
    expect(defaultRedirectForRole('teacher')).toBe('/knowledge')
    expect(defaultRedirectForRole('admin')).toBe('/knowledge')
  })

  it('keeps students and parents on notes', () => {
    expect(defaultRedirectForRole('student')).toBe('/notes')
    expect(defaultRedirectForRole('parent')).toBe('/notes')
  })
})
```

`web/src/views/LoginView.spec.ts`：

1. 在路由表加：

```ts
      { path: '/knowledge', component: { template: '<div>knowledge</div>' } },
```

2. 在文件末尾加：

```ts
const teacherSession: TokenOut = {
  ...session,
  user: {
    ...session.user,
    id: 2,
    username: 'teacher_kp',
    nickname: '测试教师',
    role: 'teacher',
  },
}

it('sends a teacher to knowledge when no redirect is present', async () => {
  vi.mocked(login).mockResolvedValue(teacherSession)
  const { wrapper, router } = await mountLogin('/login')
  await wrapper.find('input[name="username"]').setValue('teacher_kp')
  await wrapper.find('input[name="password"]').setValue('Password123!')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/knowledge')
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/utils/redirect.spec.ts src/views/LoginView.spec.ts
```

Expected: `defaultRedirectForRole` 不存在、教师落点仍是 `/notes`。

- [x] **Step 3: 写类型**

`web/src/types/kp.ts` 改为：

```ts
export interface SubjectOut {
  id: number
  name: string
  code: string
  stage: string
}

export interface KpNode {
  id: number
  subject_id: number
  parent_id: number | null
  name: string
  code: string
  level: number
  description: string | null
  exam_weight: number | null
  order_no: number
  children: KpNode[]
}

export interface KpTree {
  subject: SubjectOut
  nodes: KpNode[]
}

export interface KpCreatePayload {
  subject: string
  parent_id: number | null
  code: string
  name: string
  description?: string | null
  exam_weight?: number | null
  order_no?: number
}

export interface KpUpdatePayload {
  name?: string
  description?: string | null
  exam_weight?: number | null
}

export interface KpOrderPayload {
  parent_id: number | null
  ordered_ids: number[]
  moved_id?: number
}

export interface KpDialogPayload {
  name: string
  code?: string
  description: string | null
  exam_weight: number | null
  parent_id: number | null
}

export interface PendingAlign {
  note_id: number
  kp_id: number
  confidence: number
  note_title: string
  note_excerpt: string
  kp_name: string
  kp_code: string
}

export interface AlignPair {
  note_id: number
  kp_id: number
}

export interface AlignBatchResult {
  confirmed: number
  deleted: number
  skipped: number
}
```

保留 `SubjectOut` 别名，避免现有导入断裂。

- [x] **Step 4: 写 API 封装**

`web/src/api/kp.ts` 改为：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  AlignBatchResult,
  AlignPair,
  KpCreatePayload,
  KpNode,
  KpOrderPayload,
  KpTree,
  KpUpdatePayload,
  PendingAlign,
  SubjectOut,
} from '@/types/kp'

export async function listSubjects(): Promise<SubjectOut[]> {
  const resp = await http.get<ApiEnvelope<SubjectOut[]>>(`${API_PREFIX}/kp/subjects`)
  return resp.data.data
}

export async function getKpTree(subject: string): Promise<KpTree> {
  const resp = await http.get<ApiEnvelope<KpTree>>(`${API_PREFIX}/kp/tree`, {
    params: { subject },
  })
  return resp.data.data
}

export async function createKp(payload: KpCreatePayload): Promise<KpNode> {
  const resp = await http.post<ApiEnvelope<KpNode>>(`${API_PREFIX}/kp`, payload)
  return resp.data.data
}

export async function updateKp(id: number, payload: KpUpdatePayload): Promise<KpNode> {
  const resp = await http.patch<ApiEnvelope<KpNode>>(`${API_PREFIX}/kp/${id}`, payload)
  return resp.data.data
}

export async function deleteKp(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/kp/${id}`)
}

export async function reorderKp(payload: KpOrderPayload): Promise<void> {
  await http.put(`${API_PREFIX}/kp/order`, payload)
}

export async function listPendingAlign(
  params: { page?: number; page_size?: number } = {},
): Promise<PageData<PendingAlign>> {
  const resp = await http.get<ApiEnvelope<PageData<PendingAlign>>>(
    `${API_PREFIX}/kp/align/pending`,
    { params: { page: 1, page_size: 20, ...params } },
  )
  return resp.data.data
}

export async function confirmAlign(items: AlignPair[]): Promise<AlignBatchResult> {
  const resp = await http.post<ApiEnvelope<AlignBatchResult>>(
    `${API_PREFIX}/kp/align/confirm`,
    { items },
  )
  return resp.data.data
}

export async function rejectAlign(items: AlignPair[]): Promise<AlignBatchResult> {
  const resp = await http.post<ApiEnvelope<AlignBatchResult>>(
    `${API_PREFIX}/kp/align/reject`,
    { items },
  )
  return resp.data.data
}
```

- [x] **Step 5: 改登录落点**

`web/src/utils/redirect.ts` 改为：

```ts
import type { UserRole } from '@/types/auth'

export const DEFAULT_REDIRECT = '/notes'

export function defaultRedirectForRole(role: UserRole): string {
  return role === 'teacher' || role === 'admin' ? '/knowledge' : DEFAULT_REDIRECT
}

/**
 * 登录后回跳只允许站内路径：拒绝 //host、反斜杠和非字符串，避免开放重定向。
 */
export function safeRedirect(raw: unknown, fallback: string = DEFAULT_REDIRECT): string {
  if (typeof raw !== 'string') return fallback
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) {
    return fallback
  }
  return raw
}
```

`web/src/views/LoginView.vue` 改 import：

```ts
import { defaultRedirectForRole, safeRedirect } from '@/utils/redirect'
```

登录成功处改为：

```ts
    const fallback = defaultRedirectForRole(session.user.role)
    await router.replace(safeRedirect(route.query.redirect, fallback))
```

- [x] **Step 6: 跑前端测试**

```bash
cd web
npm run test:run -- src/utils/redirect.spec.ts src/views/LoginView.spec.ts
```

Expected: 全绿；既有 `safeRedirect` 测试不变。

- [x] **Step 7: 提交**

```bash
git add web/src/types/kp.ts web/src/api/kp.ts web/src/utils/redirect.ts \
  web/src/views/LoginView.vue web/src/utils/redirect.spec.ts \
  web/src/views/LoginView.spec.ts
git commit -m "feat(s2-14): 知识点 API 类型与角色登录落点"
```

---

### Task 4: 树纯函数与知识点表单

**Files:**
- Create: `web/src/views/kp/treeUtils.ts`
- Create: `web/src/views/kp/treeUtils.spec.ts`
- Create: `web/src/components/kp/KpNodeDialog.vue`
- Create: `web/src/components/kp/KpNodeDialog.spec.ts`

**Interfaces:**
- Consumes: `KpNode`, `KpDialogPayload`.
- Produces:
  - `findKpNode(nodes, id)`, `flattenKpNodes(nodes)`, `collectSiblingIds(nodes, parentId)`, `subtreeHeight(node)`, `dropParentId(dropNode, type)`, `canDropNode(dragNode, dropNode, type)`
  - `KpNodeDialog` props `{modelValue, mode, node?, parentId?, parentName?, saving?}`；emit `update:modelValue`、`submit(KpDialogPayload)`

- [x] **Step 1: 写 treeUtils 失败测试**

`web/src/views/kp/treeUtils.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { KpNode } from '@/types/kp'
import {
  canDropNode,
  collectSiblingIds,
  dropParentId,
  findKpNode,
  flattenKpNodes,
  subtreeHeight,
} from './treeUtils'

function node(
  id: number,
  parent_id: number | null,
  level: number,
  children: KpNode[] = [],
): KpNode {
  return {
    id,
    subject_id: 1,
    parent_id,
    name: `节点${id}`,
    code: `KP-${id}`,
    level,
    description: null,
    exam_weight: null,
    order_no: 0,
    children,
  }
}

const leaf = node(3, 2, 3)
const child = node(2, 1, 2, [leaf])
const root = node(1, null, 1, [child])

describe('treeUtils', () => {
  it('finds a node recursively and flattens the tree', () => {
    expect(findKpNode([root], 3)?.code).toBe('KP-3')
    expect(findKpNode([root], 99)).toBeNull()
    expect(flattenKpNodes([root]).map((item) => item.id)).toEqual([1, 2, 3])
  })

  it('collects direct sibling ids', () => {
    expect(collectSiblingIds([root], 1)).toEqual([2])
    expect(collectSiblingIds([root], null)).toEqual([1])
    expect(collectSiblingIds([root], 2)).toEqual([3])
  })

  it('computes subtree height', () => {
    expect(subtreeHeight(root)).toBe(3)
    expect(subtreeHeight(child)).toBe(2)
    expect(subtreeHeight(leaf)).toBe(1)
  })

  it('resolves the target parent for a drop', () => {
    expect(dropParentId(child, 'inner')).toBe(2)
    expect(dropParentId(child, 'before')).toBe(1)
    expect(dropParentId(child, 'after')).toBe(1)
  })

  it('rejects invalid drop levels and locked roots', () => {
    const level4 = node(4, 3, 4)
    expect(canDropNode(root, child, 'inner')).toBe(false)
    expect(canDropNode(child, level4, 'inner')).toBe(false)
    expect(canDropNode(child, root, 'before')).toBe(false)
    expect(canDropNode(child, child, 'inner')).toBe(true)
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/kp/treeUtils.spec.ts
```

Expected: 模块不存在。

- [x] **Step 3: 实现 treeUtils**

`web/src/views/kp/treeUtils.ts`：

```ts
import type { KpNode } from '@/types/kp'

export type DropType = 'before' | 'after' | 'inner'

export function findKpNode(nodes: KpNode[], id: number | null): KpNode | null {
  if (id === null) return null
  for (const node of nodes) {
    if (node.id === id) return node
    const match = findKpNode(node.children, id)
    if (match) return match
  }
  return null
}

export function flattenKpNodes(nodes: KpNode[]): KpNode[] {
  return nodes.flatMap((node) => [node, ...flattenKpNodes(node.children)])
}

export function collectSiblingIds(nodes: KpNode[], parentId: number | null): number[] {
  return flattenKpNodes(nodes)
    .filter((node) => node.parent_id === parentId)
    .map((node) => node.id)
}

export function subtreeHeight(node: KpNode): number {
  if (!node.children.length) return 1
  return 1 + Math.max(...node.children.map(subtreeHeight))
}

export function dropParentId(dropNode: KpNode, type: DropType): number | null {
  return type === 'inner' ? dropNode.id : dropNode.parent_id
}

export function canDropNode(
  dragNode: KpNode,
  dropNode: KpNode,
  type: DropType,
): boolean {
  if (dragNode.parent_id === null) return false
  if (type !== 'inner' && dropNode.parent_id === null) return false
  const newLevel = type === 'inner' ? dropNode.level + 1 : dropNode.level
  return newLevel + subtreeHeight(dragNode) - 1 <= 4
}
```

- [x] **Step 4: 写表单失败测试**

`web/src/components/kp/KpNodeDialog.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import KpNodeDialog from './KpNodeDialog.vue'

function mountDialog(mode: 'create' | 'edit' = 'create') {
  return mount(KpNodeDialog, {
    props: {
      modelValue: true,
      mode,
      parentId: 1,
      parentName: '高中数学',
      node:
        mode === 'edit'
          ? {
              id: 2,
              subject_id: 1,
              parent_id: 1,
              name: '函数',
              code: 'MATH-FUNC',
              level: 2,
              description: '原描述',
              exam_weight: 0.5,
              order_no: 0,
              children: [],
            }
          : null,
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('KpNodeDialog', () => {
  it('submits name and code on create', async () => {
    const wrapper = mountDialog()
    await wrapper.find('input[name="kp-name"]').setValue('函数的单调性')
    await wrapper.find('input[name="kp-code"]').setValue('MATH-FUNC-01')
    await wrapper.find('[data-testid="kp-save"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
      name: '函数的单调性',
      code: 'MATH-FUNC-01',
      parent_id: 1,
    })
  })

  it('does not submit an empty create form', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="kp-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('keeps code read-only when editing', async () => {
    const wrapper = mountDialog('edit')
    expect(
      wrapper.find('input[name="kp-code"]').attributes('disabled'),
    ).toBeDefined()
    expect(
      (wrapper.find('input[name="kp-code"]').element as HTMLInputElement).value,
    ).toBe('MATH-FUNC')
  })
})
```

- [x] **Step 5: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/components/kp/KpNodeDialog.spec.ts
```

Expected: 组件不存在。

- [x] **Step 6: 实现 KpNodeDialog**

`web/src/components/kp/KpNodeDialog.vue`：

```vue
<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import type { KpDialogPayload, KpNode } from '@/types/kp'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  node?: KpNode | null
  parentId?: number | null
  parentName?: string
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: KpDialogPayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  code: '',
  description: '',
  exam_weight: undefined as number | undefined,
})

const title = computed(() => (props.mode === 'create' ? '新增知识点' : '编辑知识点'))
const parentLabel = computed(() => props.parentName ?? '根级')
const rules = computed<FormRules>(() => ({
  name: [
    { required: true, message: '请输入知识点名称', trigger: 'blur' },
    { max: 100, message: '名称不能超过 100 字', trigger: 'blur' },
  ],
  ...(props.mode === 'create'
    ? {
        code: [
          { required: true, message: '请输入知识点编码', trigger: 'blur' },
          { max: 50, message: '编码不能超过 50 字', trigger: 'blur' },
        ],
      }
    : {}),
  description: [{ max: 500, message: '描述不能超过 500 字', trigger: 'blur' }],
}))

function fillForm(): void {
  form.name = props.node?.name ?? ''
  form.code = props.node?.code ?? ''
  form.description = props.node?.description ?? ''
  form.exam_weight = props.node?.exam_weight ?? undefined
  void nextTick(() => formRef.value?.clearValidate())
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) fillForm()
  },
  { immediate: true },
)

function close(): void {
  emit('update:modelValue', false)
}

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  emit('submit', {
    name: form.name.trim(),
    code: props.mode === 'create' ? form.code.trim() : undefined,
    description: form.description.trim() || null,
    exam_weight: form.exam_weight ?? null,
    parent_id: props.node?.parent_id ?? props.parentId ?? null,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="父节点">
        <el-input :model-value="parentLabel" disabled />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input
          v-model="form.name"
          name="kp-name"
          maxlength="100"
          placeholder="例如：函数的单调性"
        />
      </el-form-item>
      <el-form-item label="编码" prop="code">
        <el-input
          v-model="form.code"
          name="kp-code"
          maxlength="50"
          :disabled="mode === 'edit'"
          placeholder="例如：MATH-FUNC-01"
        />
      </el-form-item>
      <el-form-item label="描述" prop="description">
        <el-input
          v-model="form.description"
          name="kp-description"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="可选：这个知识点包含什么"
        />
      </el-form-item>
      <el-form-item label="权重" prop="exam_weight">
        <el-input-number
          v-model="form.exam_weight"
          :min="0"
          :max="1"
          :step="0.05"
          :precision="2"
          controls-position="right"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="saving" @click="close">取消</el-button>
      <el-button
        type="primary"
        data-testid="kp-save"
        :loading="saving"
        @click="submit"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>
```

注意：`parent_id` 由 `Tree` 在提交时结合 `dialogParent` 覆盖，组件不依赖 `parentName` 推断；保留表单展示即可。

- [x] **Step 7: 跑测试**

```bash
cd web
npm run test:run -- src/views/kp/treeUtils.spec.ts src/components/kp/KpNodeDialog.spec.ts
```

Expected: 全绿；如 Element Plus 表单校验异步未落，追加 `await flushPromises()`，不要用固定长 sleep。

- [x] **Step 8: 提交**

```bash
git add web/src/views/kp/treeUtils.ts web/src/views/kp/treeUtils.spec.ts \
  web/src/components/kp/KpNodeDialog.vue web/src/components/kp/KpNodeDialog.spec.ts
git commit -m "feat(s2-14): 知识点树工具与编辑表单"
```

---

### Task 5: 知识点树页面

**Files:**
- Create: `web/src/views/kp/Tree.vue`
- Create: `web/src/views/kp/Tree.spec.ts`

**Interfaces:**
- Consumes: Task 3 API、Task 4 `KpNodeDialog`/`treeUtils`、`useAuthStore`、`ElTree`、`ElMessageBox`。
- Produces: `<Tree :subject="math" />`；内部完成加载、搜索、CRUD、拖拽、错误/空态。

- [x] **Step 1: 写失败测试**

`web/src/views/kp/Tree.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  getKpTree: vi.fn(),
  createKp: vi.fn(),
  updateKp: vi.fn(),
  deleteKp: vi.fn(),
  reorderKp: vi.fn(),
}))

import { createKp, deleteKp, getKpTree, reorderKp } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import type { KpNode, KpTree } from '@/types/kp'
import KpNodeDialog from '@/components/kp/KpNodeDialog.vue'
import Tree from './Tree.vue'

const root: KpNode = {
  id: 1,
  subject_id: 1,
  parent_id: null,
  name: '高中数学',
  code: 'MATH',
  level: 1,
  description: null,
  exam_weight: null,
  order_no: 0,
  children: [
    {
      id: 2,
      subject_id: 1,
      parent_id: 1,
      name: '函数',
      code: 'MATH-FUNC',
      level: 2,
      description: null,
      exam_weight: null,
      order_no: 0,
      children: [],
    },
  ],
}

const treeData: KpTree = {
  subject: { id: 1, name: '高中数学', code: 'math', stage: '高中' },
  nodes: [root],
}

async function mountTree(role: 'student' | 'teacher' = 'teacher') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.setSession('token', {
    id: 1,
    username: '测试用户_1',
    nickname: '测试用户_1',
    grade: '高一',
    role,
    created_at: '2026-10-30T00:00:00Z',
  })
  vi.mocked(getKpTree).mockResolvedValue(treeData)
  const wrapper = mount(Tree, {
    props: { subject: 'math' },
    global: { plugins: [pinia, ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

describe('Tree', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows management controls for a teacher', async () => {
    const wrapper = await mountTree('teacher')
    expect(wrapper.text()).toContain('新增根节点')
    expect(wrapper.text()).toContain('函数')
  })

  it('hides management controls for a student', async () => {
    const wrapper = await mountTree('student')
    expect(wrapper.text()).not.toContain('新增根节点')
    expect(wrapper.text()).toContain('只读')
  })

  it('submits a create payload from the dialog', async () => {
    vi.mocked(createKp).mockResolvedValue(root)
    const wrapper = await mountTree('teacher')
    await wrapper.find('[data-testid="add-root"]').trigger('click')
    const dialog = wrapper.findComponent(KpNodeDialog)
    dialog.vm.$emit('submit', {
      name: '新节点',
      code: 'MATH-NEW',
      description: null,
      exam_weight: null,
      parent_id: null,
    })
    await flushPromises()
    expect(createKp).toHaveBeenCalledWith(
      expect.objectContaining({
        subject: 'math',
        parent_id: null,
        name: '新节点',
        code: 'MATH-NEW',
      }),
    )
  })

  it('calls reorderKp with the post-drop sibling order', async () => {
    vi.mocked(reorderKp).mockResolvedValue()
    const wrapper = await mountTree('teacher')
    const elTree = wrapper.findComponent({ name: 'ElTree' })
    elTree.vm.$emit(
      'node-drop',
      {
        data: { ...treeData.nodes[0].children[0] },
        parent: {
          childNodes: [
            { data: treeData.nodes[0].children[0] },
            { data: { ...root, id: 3, name: '新节点', code: 'MATH-NEW' } },
          ],
        },
      },
      { data: treeData.nodes[0] },
      'inner',
    )
    await flushPromises()
    expect(reorderKp).toHaveBeenCalledWith({
      parent_id: 1,
      ordered_ids: [2, 3],
      moved_id: 2,
    })
  })

  it('deletes a child after confirmation', async () => {
    vi.mocked(deleteKp).mockResolvedValue()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = await mountTree('teacher')
    const deleteButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('删除'))
    expect(deleteButton).toBeTruthy()
    await deleteButton!.trigger('click')
    await flushPromises()
    expect(deleteKp).toHaveBeenCalledWith(2)
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/kp/Tree.spec.ts
```

Expected: `Tree.vue` 不存在。

- [x] **Step 3: 实现 Tree.vue**

`web/src/views/kp/Tree.vue`：

```vue
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTree } from 'element-plus'

import { createKp, deleteKp, getKpTree, reorderKp, updateKp } from '@/api/kp'
import EmptyState from '@/components/common/EmptyState.vue'
import KpNodeDialog from '@/components/kp/KpNodeDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { KpDialogPayload, KpNode, KpTree } from '@/types/kp'
import {
  canDropNode,
  collectSiblingIds,
  dropParentId,
  findKpNode,
  flattenKpNodes,
} from './treeUtils'

const props = defineProps<{ subject: string }>()

const auth = useAuthStore()
const canManage = computed(
  () => auth.user?.role === 'admin' || auth.user?.role === 'teacher',
)

const tree = ref<KpTree | null>(null)
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const treeRef = ref<InstanceType<typeof ElTree> | null>(null)
const treeKey = ref(0)
const expandedKeys = ref<number[]>([])
const expandedIds = ref<Set<number>>(new Set())
const busy = ref(false)

const dialogOpen = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogNode = ref<KpNode | null>(null)
const dialogParent = ref<KpNode | null>(null)
const dialogParentName = ref('根级')
const saving = ref(false)

function rootIds(): number[] {
  return (tree.value?.nodes ?? []).map((node) => node.id)
}

function currentExpanded(): number[] {
  return expandedIds.value.size ? [...expandedIds.value] : rootIds()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    tree.value = await getKpTree(props.subject)
    expandedKeys.value = currentExpanded()
    treeKey.value += 1
  } catch {
    error.value = '知识点树加载失败，请重试'
  } finally {
    loading.value = false
  }
}

function onExpand(data: KpNode): void {
  expandedIds.value.add(data.id)
}

function onCollapse(data: KpNode): void {
  expandedIds.value.delete(data.id)
}

function filterNode(value: string, data: KpNode): boolean {
  const text = value.trim().toLowerCase()
  if (!text) return true
  return (
    data.name.toLowerCase().includes(text) || data.code.toLowerCase().includes(text)
  )
}

function applyFilter(value: string): void {
  const text = value.trim()
  if (!tree.value) return
  if (!text) {
    expandedKeys.value = currentExpanded()
    treeKey.value += 1
    return
  }
  expandedKeys.value = flattenKpNodes(tree.value.nodes)
    .filter((node) => node.children.length > 0)
    .map((node) => node.id)
  treeKey.value += 1
  void nextTick(() => treeRef.value?.filter(text))
}

watch(keyword, applyFilter)
watch(
  () => props.subject,
  () => {
    expandedIds.value.clear()
    keyword.value = ''
    void load()
  },
)

function openCreate(parent: KpNode | null): void {
  dialogMode.value = 'create'
  dialogNode.value = null
  dialogParent.value = parent
  dialogParentName.value = parent?.name ?? '根级'
  dialogOpen.value = true
}

function openEdit(node: KpNode): void {
  dialogMode.value = 'edit'
  dialogNode.value = node
  dialogParent.value = findKpNode(tree.value?.nodes ?? [], node.parent_id)
  dialogParentName.value = dialogParent.value?.name ?? '根级'
  dialogOpen.value = true
}

async function onDialogSubmit(payload: KpDialogPayload): Promise<void> {
  if (!tree.value) return
  saving.value = true
  try {
    if (dialogMode.value === 'create') {
      const parentId = dialogParent.value?.id ?? null
      await createKp({
        subject: props.subject,
        parent_id: parentId,
        code: payload.code ?? '',
        name: payload.name,
        description: payload.description,
        exam_weight: payload.exam_weight,
        order_no: collectSiblingIds(tree.value.nodes, parentId).length,
      })
      ElMessage.success('知识点已创建')
    } else if (dialogNode.value) {
      await updateKp(dialogNode.value.id, {
        name: payload.name,
        description: payload.description,
        exam_weight: payload.exam_weight,
      })
      ElMessage.success('知识点已更新')
    }
    dialogOpen.value = false
    await load()
  } catch {
    // http.ts 已统一提示；保留弹窗让用户修改。
  } finally {
    saving.value = false
  }
}

async function removeNode(node: KpNode): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除“${node.name}”吗？有子节点或被引用时后端会拒绝。`,
      '删除知识点',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteKp(node.id)
    ElMessage.success('知识点已删除')
    await load()
  } catch {
    await load()
  }
}

interface DragNode {
  data: KpNode
  parent?: { childNodes?: DragNode[] } | null
}

function allowDrag(node: DragNode): boolean {
  return canManage.value && !keyword.value.trim() && node.data.parent_id !== null
}

function allowDrop(dragNode: DragNode, dropNode: DragNode, type: string): boolean {
  if (!canManage.value || keyword.value.trim()) return false
  return canDropNode(dragNode.data, dropNode.data, type as 'before' | 'after' | 'inner')
}

async function onNodeDrop(
  dragging: DragNode,
  dropNode: DragNode,
  type: 'before' | 'after' | 'inner',
): Promise<void> {
  if (!canManage.value || busy.value) return
  busy.value = true
  try {
    const parentId = dropParentId(dropNode.data, type)
    const orderedIds = (dragging.parent?.childNodes ?? []).map(
      (node) => node.data.id,
    )
    await reorderKp({
      parent_id: parentId,
      ordered_ids: orderedIds,
      moved_id: dragging.data.id,
    })
    await load()
  } catch {
    await load()
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="kp-tree-panel">
    <div class="kp-toolbar">
      <el-input
        v-model="keyword"
        class="kp-search"
        clearable
        placeholder="搜索知识点名称或编码"
        name="kp-search"
      />
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button
        v-if="canManage"
        type="primary"
        data-testid="add-root"
        @click="openCreate(null)"
      >
        新增根节点
      </el-button>
    </div>

    <div v-if="!canManage" class="kp-readonly" role="note">
      只读：教师或管理员可编辑知识点
    </div>

    <div v-if="error" class="kp-error" role="alert">
      {{ error }}
      <el-button link type="primary" @click="load">重试</el-button>
    </div>

    <div v-loading="loading || busy" class="kp-tree-wrap">
      <EmptyState
        v-if="!loading && tree && !tree.nodes.length"
        title="还没有知识点"
        description="教师或管理员可以新增根节点。"
      />
      <el-tree
        v-else-if="tree"
        :key="treeKey"
        ref="treeRef"
        :data="tree.nodes"
        node-key="id"
        :props="{ children: 'children', label: 'name' }"
        :default-expanded-keys="expandedKeys"
        :filter-node-method="filterNode"
        :draggable="canManage && !keyword.trim()"
        :allow-drag="allowDrag"
        :allow-drop="allowDrop"
        :expand-on-click-node="false"
        @node-expand="onExpand"
        @node-collapse="onCollapse"
        @node-drop="onNodeDrop"
      >
        <template #default="{ data }">
          <div class="kp-node">
            <span class="kp-node-name">{{ data.name }}</span>
            <el-tag size="small" effect="plain">{{ data.code }}</el-tag>
            <span class="kp-node-meta">
              L{{ data.level }}
              <template v-if="data.exam_weight !== null">
                · 权重 {{ data.exam_weight }}
              </template>
            </span>
            <span v-if="canManage" class="kp-node-actions">
              <el-button
                v-if="data.level < 4"
                link
                type="primary"
                @click.stop="openCreate(data)"
              >
                新增子节点
              </el-button>
              <el-button link @click.stop="openEdit(data)">编辑</el-button>
              <el-button
                v-if="data.parent_id !== null"
                link
                type="danger"
                @click.stop="removeNode(data)"
              >
                删除
              </el-button>
            </span>
          </div>
        </template>
      </el-tree>
    </div>

    <KpNodeDialog
      v-model="dialogOpen"
      :mode="dialogMode"
      :node="dialogNode"
      :parent-id="dialogParent?.id ?? null"
      :parent-name="dialogParentName"
      :saving="saving"
      @submit="onDialogSubmit"
    />
  </div>
</template>

<style scoped>
.kp-tree-panel {
  min-width: 0;
}

.kp-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.kp-search {
  max-width: 320px;
}

.kp-readonly {
  padding: 8px 12px;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
  background: #f6f8fa;
  border-radius: var(--app-radius-sm);
}

.kp-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 12px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.kp-tree-wrap {
  min-height: 260px;
  padding: 12px;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.kp-node {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-width: 0;
}

.kp-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kp-node-meta {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.kp-node-actions {
  display: inline-flex;
  gap: 4px;
  margin-left: auto;
}
</style>
```

- [x] **Step 4: 跑测试**

```bash
cd web
npm run test:run -- src/views/kp/Tree.spec.ts
```

Expected: 全绿；若 `ElTree` 组件名在测试中解析不到，改用 `wrapper.find('.el-tree')` 后触发 `node-drop` 不可行时，用 `wrapper.vm` 暴露 `onNodeDrop` 测试（仅测试辅助，不改变生产逻辑）。

- [x] **Step 5: 提交**

```bash
git add web/src/views/kp/Tree.vue web/src/views/kp/Tree.spec.ts
git commit -m "feat(s2-14): 知识点树 CRUD 与拖拽"
```

---

### Task 6: 待确认单卡队列

**Files:**
- Create: `web/src/views/kp/usePendingAlign.ts`
- Create: `web/src/views/kp/PendingAlign.vue`
- Create: `web/src/views/kp/PendingAlign.spec.ts`

**Interfaces:**
- Consumes: Task 3 `listPendingAlign/confirmAlign/rejectAlign`、`PendingAlign`。
- Produces:
  - `usePendingAlign()` 返回 `{ queue, total, current, loading, busy, error, load, confirmCurrent, rejectCurrent }`
  - `<PendingAlign />` 自动加载、监听 Enter/Backspace、显示摘要与候选知识点。

- [x] **Step 1: 写失败测试**

`web/src/views/kp/PendingAlign.spec.ts`：

```ts
import { flushPromises, mount, enableAutoUnmount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  listPendingAlign: vi.fn(),
  confirmAlign: vi.fn(),
  rejectAlign: vi.fn(),
}))

import { confirmAlign, listPendingAlign, rejectAlign } from '@/api/kp'
import type { PendingAlign as PendingItem } from '@/types/kp'
import PendingAlign from './PendingAlign.vue'

enableAutoUnmount(afterEach)

function item(id: number): PendingItem {
  return {
    note_id: id,
    kp_id: 100 + id,
    confidence: 0.68,
    note_title: `笔记${id}`,
    note_excerpt: `这是第 ${id} 条摘要`,
    kp_name: `知识点${id}`,
    kp_code: `MATH-${id}`,
  }
}

function page(items: PendingItem[], total = items.length) {
  return { items, total, page: 1, page_size: 20 }
}

async function mountPending() {
  const wrapper = mount(PendingAlign, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

describe('PendingAlign', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(confirmAlign).mockResolvedValue({ confirmed: 1, deleted: 0, skipped: 0 })
    vi.mocked(rejectAlign).mockResolvedValue({ confirmed: 0, deleted: 1, skipped: 0 })
  })

  it('renders excerpt and candidate knowledge point', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    const wrapper = await mountPending()
    expect(wrapper.text()).toContain('笔记1')
    expect(wrapper.text()).toContain('这是第 1 条摘要')
    expect(wrapper.text()).toContain('知识点1')
    expect(wrapper.text()).toContain('MATH-1')
  })

  it('confirms with Enter and shows the next card', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1), item(2)]))
    const wrapper = await mountPending()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(confirmAlign).toHaveBeenCalledWith([{ note_id: 1, kp_id: 101 }])
    expect(wrapper.text()).toContain('笔记2')
  })

  it('rejects with Backspace', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    const wrapper = await mountPending()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Backspace' }))
    await flushPromises()
    expect(rejectAlign).toHaveBeenCalledWith([{ note_id: 1, kp_id: 101 }])
  })

  it('does not act when focus is in an input', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([item(1)]))
    await mountPending()
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()
    expect(confirmAlign).not.toHaveBeenCalled()
    input.remove()
  })

  it('shows empty state when there is nothing pending', async () => {
    vi.mocked(listPendingAlign).mockResolvedValue(page([]))
    const wrapper = await mountPending()
    expect(wrapper.text()).toContain('暂无待确认')
  })

  it('handles 20 sequential confirmations without stale cards', async () => {
    const items = Array.from({ length: 20 }, (_, index) => item(index + 1))
    vi.mocked(listPendingAlign)
      .mockResolvedValueOnce(page(items, 20))
      .mockResolvedValueOnce(page([], 0))
    const wrapper = await mountPending()

    for (let index = 0; index < 20; index += 1) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
      await flushPromises()
    }

    expect(confirmAlign).toHaveBeenCalledTimes(20)
    expect(wrapper.text()).toContain('暂无待确认')
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/kp/PendingAlign.spec.ts
```

Expected: 组件不存在。

- [x] **Step 3: 实现 composable**

`web/src/views/kp/usePendingAlign.ts`：

```ts
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { confirmAlign, listPendingAlign, rejectAlign } from '@/api/kp'
import type { PendingAlign } from '@/types/kp'

export function usePendingAlign() {
  const queue = ref<PendingAlign[]>([])
  const total = ref(0)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const current = computed(() => queue.value[0] ?? null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const result = await listPendingAlign({ page: 1, page_size: 20 })
      queue.value = result.items
      total.value = result.total
    } catch {
      error.value = '待确认队列加载失败，请重试'
    } finally {
      loading.value = false
    }
  }

  async function act(kind: 'confirm' | 'reject'): Promise<void> {
    const target = current.value
    if (!target || busy.value) return
    busy.value = true
    try {
      const pair = [{ note_id: target.note_id, kp_id: target.kp_id }]
      const result =
        kind === 'confirm' ? await confirmAlign(pair) : await rejectAlign(pair)
      const changed = kind === 'confirm' ? result.confirmed : result.deleted
      if (changed !== 1 || result.skipped > 0) {
        ElMessage.warning('对齐状态已变化，已重新加载队列')
        await load()
        return
      }
      queue.value.shift()
      total.value = Math.max(0, total.value - 1)
      if (!queue.value.length) await load()
    } catch {
      // http.ts 已统一提示；保留当前卡，允许用户重试。
    } finally {
      busy.value = false
    }
  }

  return {
    queue,
    total,
    current,
    loading,
    busy,
    error,
    load,
    confirmCurrent: () => act('confirm'),
    rejectCurrent: () => act('reject'),
  }
}
```

- [x] **Step 4: 实现 PendingAlign.vue**

`web/src/views/kp/PendingAlign.vue`：

```vue
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import { usePendingAlign } from './usePendingAlign'

const {
  total,
  current,
  loading,
  busy,
  error,
  load,
  confirmCurrent,
  rejectCurrent,
} = usePendingAlign()

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return Boolean(
    target.closest('input, textarea, select, [contenteditable="true"], .el-dialog'),
  )
}

function onKeydown(event: KeyboardEvent): void {
  if (!current.value || busy.value || isEditableTarget(event.target)) return
  if (event.key === 'Enter') {
    event.preventDefault()
    void confirmCurrent()
  } else if (event.key === 'Backspace') {
    event.preventDefault()
    void rejectCurrent()
  }
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="pending-panel">
    <div v-if="loading" class="pending-loading" v-loading="true" />

    <div v-else-if="error" class="pending-error" role="alert">
      {{ error }}
      <el-button link type="primary" @click="load">重试</el-button>
    </div>

    <EmptyState
      v-else-if="!current"
      title="暂无待确认对齐"
      description="新笔记自动对齐后，低置信度候选会出现在这里。"
    />

    <template v-else>
      <div class="pending-meta">
        <span>待确认 {{ total }} 条</span>
        <span class="pending-hint">Enter 确认 · Backspace 忽略</span>
      </div>

      <article class="pending-card" tabindex="0" :aria-busy="busy">
        <section class="note-pane">
          <p class="pane-label">笔记内容</p>
          <h3 class="note-title">{{ current.note_title }}</h3>
          <p class="note-excerpt">
            {{ current.note_excerpt || '（这条笔记暂无摘要）' }}
          </p>
        </section>

        <section class="candidate-pane">
          <p class="pane-label">候选知识点</p>
          <h3 class="kp-title">{{ current.kp_name }}</h3>
          <p class="kp-code">{{ current.kp_code }}</p>
          <div class="confidence">
            <span>置信度</span>
            <strong>{{ Math.round(current.confidence * 100) }}%</strong>
          </div>
        </section>
      </article>

      <div class="pending-actions">
        <el-button
          type="primary"
          data-testid="confirm-align"
          :loading="busy"
          @click="confirmCurrent"
        >
          确认对齐
        </el-button>
        <el-button data-testid="reject-align" :disabled="busy" @click="rejectCurrent">
          忽略
        </el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pending-panel {
  min-height: 320px;
}

.pending-loading {
  min-height: 240px;
}

.pending-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.pending-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.pending-hint {
  color: var(--app-text-tertiary);
}

.pending-card {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(260px, 1fr);
  gap: 0;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
}

.note-pane,
.candidate-pane {
  padding: 26px;
}

.note-pane {
  border-right: 1px solid var(--app-border);
}

.candidate-pane {
  background: #fafbfc;
}

.pane-label {
  margin: 0 0 10px;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.note-title,
.kp-title {
  margin: 0 0 12px;
  font-size: 18px;
}

.note-excerpt {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  color: var(--app-text-secondary);
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
}

.kp-code {
  margin: 0 0 18px;
  color: var(--app-text-tertiary);
  font-family: var(--app-font-mono);
  font-size: 12px;
}

.confidence {
  display: flex;
  justify-content: space-between;
  padding-top: 14px;
  color: var(--app-text-secondary);
  border-top: 1px solid var(--app-border);
}

.pending-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 18px;
}
</style>
```

- [x] **Step 5: 跑测试**

```bash
cd web
npm run test:run -- src/views/kp/PendingAlign.spec.ts
```

Expected: 全绿；20 条连续确认只发 20 次确认请求，结束后显示空态。

- [x] **Step 6: 提交**

```bash
git add web/src/views/kp/usePendingAlign.ts \
  web/src/views/kp/PendingAlign.vue web/src/views/kp/PendingAlign.spec.ts
git commit -m "feat(s2-14): 待确认对齐单卡队列与键盘操作"
```

---

### Task 7: 知识库页面壳与路由

**Files:**
- Create: `web/src/views/kp/KnowledgeView.vue`
- Create: `web/src/views/kp/KnowledgeView.spec.ts`
- Modify: `web/src/router/index.ts`

**Interfaces:**
- Consumes: `listSubjects`, `Tree`, `PendingAlign`, `PageHeader`、`EmptyState`。
- Produces: `/knowledge` 页面，两个 tab，学科选择。

- [x] **Step 1: 写失败测试**

`web/src/views/kp/KnowledgeView.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/kp', () => ({
  listSubjects: vi.fn(),
}))

import { listSubjects } from '@/api/kp'
import KnowledgeView from './KnowledgeView.vue'

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(KnowledgeView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: {
        Tree: { template: '<div data-testid="tree-stub">tree</div>' },
        PendingAlign: { template: '<div data-testid="pending-stub">pending</div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('KnowledgeView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads subjects and shows the tree tab by default', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    expect(listSubjects).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('知识点树')
    expect(wrapper.find('[data-testid="tree-stub"]').exists()).toBe(true)
  })

  it('switches to the pending tab', async () => {
    vi.mocked(listSubjects).mockResolvedValue([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    const wrapper = await mountView()
    const tabs = wrapper.findAll('.el-tabs__item')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="pending-stub"]').exists()).toBe(true)
  })

  it('shows a load error with retry', async () => {
    vi.mocked(listSubjects).mockRejectedValueOnce(new Error('network'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('学科加载失败')
    vi.mocked(listSubjects).mockResolvedValueOnce([
      { id: 1, name: '高中数学', code: 'math', stage: '高中' },
    ])
    await wrapper.find('[data-testid="retry-subjects"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="tree-stub"]').exists()).toBe(true)
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/kp/KnowledgeView.spec.ts
```

Expected: 页面不存在。

- [x] **Step 3: 实现 KnowledgeView**

`web/src/views/kp/KnowledgeView.vue`：

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { listSubjects } from '@/api/kp'
import PageHeader from '@/components/common/PageHeader.vue'
import type { SubjectOut } from '@/types/kp'
import PendingAlign from './PendingAlign.vue'
import Tree from './Tree.vue'

const subjects = ref<SubjectOut[]>([])
const selectedSubject = ref('')
const activeTab = ref<'tree' | 'pending'>('tree')
const loading = ref(false)
const error = ref('')

const selected = computed(
  () => subjects.value.find((subject) => subject.code === selectedSubject.value) ?? null,
)

async function loadSubjects(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    subjects.value = await listSubjects()
    if (!subjects.value.some((subject) => subject.code === selectedSubject.value)) {
      selectedSubject.value = subjects.value[0]?.code ?? ''
    }
  } catch {
    error.value = '学科加载失败，请重试'
  } finally {
    loading.value = false
  }
}

onMounted(loadSubjects)
</script>

<template>
  <div class="knowledge-page">
    <PageHeader
      title="知识库"
      description="浏览知识点树，处理笔记自动对齐产生的待确认候选。"
    />

    <div v-if="error" class="knowledge-error" role="alert">
      {{ error }}
      <el-button
        link
        type="primary"
        data-testid="retry-subjects"
        @click="loadSubjects"
      >
        重试
      </el-button>
    </div>

    <el-tabs v-model="activeTab" class="knowledge-tabs">
      <el-tab-pane label="知识点树" name="tree">
        <div class="subject-bar">
          <span class="subject-label">学科</span>
          <el-select
            v-model="selectedSubject"
            placeholder="选择学科"
            :loading="loading"
            style="width: 220px"
          >
            <el-option
              v-for="subject in subjects"
              :key="subject.code"
              :label="subject.name"
              :value="subject.code"
            />
          </el-select>
        </div>

        <Tree v-if="selected" :subject="selected.code" />
        <div v-else-if="!loading && !error" class="subject-empty">
          暂无学科数据
        </div>
      </el-tab-pane>

      <el-tab-pane label="待确认对齐" name="pending">
        <PendingAlign v-if="activeTab === 'pending'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.knowledge-page {
  min-width: 0;
}

.knowledge-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 14px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.knowledge-tabs {
  margin-top: 8px;
}

.subject-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.subject-label {
  color: var(--app-text-secondary);
  font-size: 13px;
}

.subject-empty {
  padding: 48px;
  color: var(--app-text-tertiary);
  text-align: center;
}
</style>
```

- [x] **Step 4: 改路由**

`web/src/router/index.ts` 把 knowledge 路由改为：

```ts
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('@/views/kp/KnowledgeView.vue'),
          meta: { title: '知识库', nav: 'knowledge' },
        },
```

- [x] **Step 5: 跑前端测试与构建**

```bash
cd web
npm run test:run -- src/views/kp/KnowledgeView.spec.ts
npm run test:run
npm run build
```

Expected: 页面测试通过；全套 Vitest 全绿；`vue-tsc + vite build` 退出 0。

- [x] **Step 6: 提交**

```bash
git add web/src/views/kp/KnowledgeView.vue \
  web/src/views/kp/KnowledgeView.spec.ts web/src/router/index.ts
git commit -m "feat(s2-14): 知识库页面与路由"
```

---

### Task 8: 真实联调、文档与收尾

**Files:**
- Modify: `docs/API.md`（补齐执行记录里的实测/错误）
- Modify: `docs/DECISIONS.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s2-14-kp-ui.md`
- Modify: `docs/plan/s2-14-kp-ui.md`

**Interfaces:**
- Consumes: 前七个任务交付物；真实 PostgreSQL/Redis/前端 dev server。
- Produces: 可复现的验收证据、D-034、进度记录、清理后的环境。

- [x] **Step 1: 跑全量自动测试**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
```

Expected: 后端全绿（基线 512 + 本任务新增）；前端全绿（基线 56 + 本任务新增）；build 退出 0。

- [x] **Step 2: 准备临时 teacher/student 与验收数据**

先启动后端/前端（依赖本地 Postgres、Redis；本任务 CRUD 不需要 ARQ Worker）：

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ../web
npm run dev -- --host 127.0.0.1
```

用真实注册接口创建临时账号（不要写死到代码）：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"s214_teacher","password":"Password123!","nickname":"验收教师","role":"teacher"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"s214_student","password":"Password123!","nickname":"验收学生","role":"student"}'
```

登录拿 token：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"s214_teacher","password":"Password123!"}'
```

把返回的 `access_token` 记为 `$TEACHER_TOKEN`；学生同理 `$STUDENT_TOKEN`。

- [x] **Step 3: 真实 CRUD/拖拽/权限联调**

1. 浏览器 1440×900 打开 `http://127.0.0.1:5173/knowledge`，用 teacher 登录（无 redirect 应落到 `/knowledge`）。
2. 新增子节点“验收-函数临时”（编码 `S214-TMP-01`）→ 改名“验收-函数临时2” → 改权重 0.3 → 拖到另一父级 → 同级拖拽 → 刷新页面，确认父子关系/顺序保持。
3. 用 API 验证顺序：

```bash
curl -s http://127.0.0.1:8000/api/v1/kp/tree?subject=math \
  -H "Authorization: Bearer $TEACHER_TOKEN"
```

4. 尝试删除有子节点的临时节点，确认页面出现 409 文案；删除叶子节点成功。
5. 用 student 打开 `/knowledge`：
   - 树可见可搜索；
   - 无“新增根节点”、无节点操作按钮、不可拖拽；
   - 直接 `curl -X PUT /kp/order` 用 student token 应返回 403。
6. 检查浏览器 console error 为 0，1440×900 无横向滚动。

- [x] **Step 4: 准备 20 条临时待确认并验收键盘队列**

在 `backend` 用下面的一次性 Python 脚本为 `s214_student` 创建 20 条测试笔记 + `note_kps` 待确认行；`confidence` 取 0.66，`source='ai'`，`confirmed=false`，`kp_id` 选当前真实存在的 level 3 知识点。标题/正文必须是明显假的“验收临时笔记-XX”，不得写真实学生信息：

```bash
cd backend
../.venv/Scripts/python.exe - <<'PY'
from decimal import Decimal

from sqlalchemy import select

from app.core.db import new_session
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.subject import Subject
from app.models.user import User

with new_session() as session:
    student = session.scalar(select(User).where(User.username == "s214_student"))
    subject = session.scalar(select(Subject).where(Subject.code == "math"))
    if student is None or subject is None:
        raise SystemExit("请先创建 s214_student 与 math 学科")
    kp = session.scalar(
        select(KnowledgePoint)
        .where(KnowledgePoint.subject_id == subject.id, KnowledgePoint.level == 3)
        .order_by(KnowledgePoint.id)
        .limit(1)
    )
    if kp is None:
        raise SystemExit("没有可用的 level 3 知识点")
    existing = session.scalar(
        select(Note).where(
            Note.user_id == student.id,
            Note.title.like("验收临时笔记-%"),
        )
    )
    if existing is not None:
        raise SystemExit("临时数据已存在，请先执行 Step 5 清理")

    for index in range(1, 21):
        note = Note(
            user_id=student.id,
            subject_id=subject.id,
            title=f"验收临时笔记-{index:02d}",
            content_md=f"# 验收临时笔记-{index:02d}\n\n函数的单调性用于 S2-14 验收。",
            content_text=f"验收临时笔记-{index:02d}：函数的单调性用于验收。",
            tags=[],
            folder=None,
            source_file_id=None,
        )
        session.add(note)
        session.flush()
        session.add(
            NoteKp(
                note_id=note.id,
                kp_id=kp.id,
                confidence=Decimal("0.660"),
                source="ai",
                confirmed=False,
            )
        )
    session.commit()
    print(f"seed student={student.id} kp={kp.id} notes=20")
PY
```

启动前端，用 `s214_student` 登录并进入 `/knowledge` → 待确认对齐：

1. 确认卡片左侧显示“验收临时笔记-XX”与摘要，右侧显示候选知识点和 66%。
2. 连续按 `Enter` 20 次：
   - 每次只发 1 次 `/align/confirm` 请求（DevTools Network 统计 20 次）；
   - 卡片逐条切换，最后显示“暂无待确认对齐”；
   - 页面不冻结、无旧卡残留、无重复确认；
   - console error 0。
3. 重新准备 1 条，按 `Backspace`，确认忽略成功、队列清空。
4. 检查 `note_kps` 中临时行已按确认/忽略规则处理；记录实际数字。

- [x] **Step 5: 清理临时数据**

用一次性脚本/API 删除临时数据。下面脚本先删 `note_kps`/临时笔记，再删临时用户，最后删验收创建的 `S214-*` 知识点：

```bash
cd backend
../.venv/Scripts/python.exe - <<'PY'
from sqlalchemy import delete, select

from app.core.db import new_session
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.user import User

with new_session() as session:
    student = session.scalar(select(User).where(User.username == "s214_student"))
    teacher = session.scalar(select(User).where(User.username == "s214_teacher"))
    note_ids: list[int] = []

    if student is not None:
        note_ids = list(
            session.scalars(
                select(Note.id).where(
                    Note.user_id == student.id,
                    Note.title.like("验收临时笔记-%"),
                )
            )
        )
        if note_ids:
            session.execute(delete(NoteKp).where(NoteKp.note_id.in_(note_ids)))
            session.execute(delete(Note).where(Note.id.in_(note_ids)))
        session.delete(student)
    if teacher is not None:
        session.delete(teacher)

    temp_kps = list(
        session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.code.like("S214-%"))
        )
    )
    kp_ids = [kp.id for kp in temp_kps]
    if kp_ids:
        session.execute(delete(NoteKp).where(NoteKp.kp_id.in_(kp_ids)))
        session.execute(
            delete(KnowledgeEdge).where(
                (KnowledgeEdge.src_kp_id.in_(kp_ids))
                | (KnowledgeEdge.dst_kp_id.in_(kp_ids))
            )
        )
        for kp in sorted(temp_kps, key=lambda row: row.level, reverse=True):
            session.delete(kp)

    session.commit()
    print(f"cleaned notes={len(note_ids)} temp_kps={len(temp_kps)}")
PY
```

清理后直接用数据库确认临时用户名、临时笔记、临时知识点均为 0：

```bash
cd backend
../.venv/Scripts/python.exe - <<'PY'
from sqlalchemy import func, select

from app.core.db import new_session
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.user import User

with new_session() as session:
    print("users", session.scalar(select(func.count()).where(User.username.in_(["s214_teacher", "s214_student"]))))
    print("notes", session.scalar(select(func.count()).where(Note.title.like("验收临时笔记-%"))))
    print("kps", session.scalar(select(func.count()).where(KnowledgePoint.code.like("S214-%"))))
PY
```

Expected: `users 0`、`notes 0`、`kps 0`。

- [x] **Step 6: 更新文档**

`docs/DECISIONS.md` 追加：

```markdown
## D-034 前端知识点树管理（S2-14）

- 背景：S2-9 已有知识点树 CRUD、S2-10 已有待确认队列，但 `/knowledge` 仍是占位页；S2-14 交付树管理 + 键盘确认卡片。spec 见 `docs/spec/s2-14-kp-ui.md`。
- 决策 1（页面）：单页 `/knowledge` + 两个 tab（知识点树 / 待确认对齐），不拆两个路由。
- 决策 2（权限）：学生只读；admin/teacher 可 CRUD/拖拽；待确认仍只处理本人笔记。
- 决策 3（拖拽）：新增 `PUT /api/v1/kp/order`，`parent_id + ordered_ids + moved_id` 一次事务完成跨级移动/同级排序；根节点前端锁定。
- 决策 4（摘要）：`PendingAlignOut.note_excerpt` 从 `content_text` 派生前 300 字 + `…`，不加列、不查完整正文。
- 决策 5（待确认）：一次一张卡，`Enter` 确认、`Backspace` 忽略；busy 锁防重复，20 条连续处理不整页刷新。
- 决策 6（登录）：教师/管理员无 redirect 时默认 `/knowledge`；学生仍 `/notes`。
- 决策 7（测试）：后端新增排序/摘要契约，前端新增树工具/表单/树页/待确认/页面壳；真实 1440 浏览器 + 临时账号 + 20 条真实待确认行。
- 决策 8（已知代价）：搜索仅当前学科前端过滤；无批量确认/撤销；根节点锁定只在前端；`PUT /order` 要求目标兄弟全集，前端失败后重载树。
- 验证：`pytest` 全绿（基线 512 + 本任务新增）、Vitest 全绿（基线 56 + 本任务新增）、`npm run build` 退出 0；真实 1440 浏览器完成 CRUD/拖拽/20 条键盘确认，console error 0；临时账号/笔记/知识点清理为 0；具体实测数字写入 PROGRESS。
```

`docs/PROGRESS.md` 在 S2-13 后追加 S2-14 小节，写清交付、测试数字、验收命令、已知限制。`docs/AI协作开发实施计划.md` 把 `[ ] S2-14` 改为 `[x] S2-14`。spec 末尾追加“执行记录”。plan 每个任务勾选并追加验证记录。

- [x] **Step 7: 最终检查与提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git diff --check
git status --short
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../web && npm run test:run && npm run build
```

Expected: 全绿；工作区只剩本次文档修改；无临时文件/账号/测试数据。

```bash
git add docs/API.md docs/DECISIONS.md docs/PROGRESS.md \
  docs/AI协作开发实施计划.md docs/spec/s2-14-kp-ui.md docs/plan/s2-14-kp-ui.md
git commit -m "docs(s2-14): 知识点树管理验收记录"
```

不执行 `git push`；由用户推送。

## 执行记录（2026-10-30）

- Task 1–2 后端：`PUT /kp/order` + `note_excerpt` 已实现，新增 12 条测试，pytest 524 passed / 1 warning；API.md 已同步。
- Task 3–7 前端：类型/API、登录落点、树工具/表单/树页、待确认队列、页面壳与路由已实现；Vitest 82 passed / 19 files，build 退出 0。
- Task 8 真实验收：teacher/student 临时账号、20 条真实待确认行、跨级拖拽、搜索、CRUD、20 次 Enter + 1 次 Backspace、console error 0、无横向溢出；临时数据已清理。
- 偏离：Tree 的 node-drop 顺序从 `dropNode` 的 `childNodes` 读取（Element 在 emit 前已移除源节点，`dragging.parent` 不可靠）；KpNodeDialog 测试用 ElDialog stub 绕开 teleport；Element 树回调类型按官方 `FilterValue`/`TreeNodeData` 对齐。
