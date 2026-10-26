# S2-3 RBAC 与数据隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可组合的 `require_role` / `require_student_access` 依赖与 `ensure_student_access` 服务层守卫，并用测试证明「A 学生的笔记 B 访问返回 403」。

**Architecture:** 权限判定全部在 `core/permissions.py`：角色来自数据库（S2-2 的 `get_current_user` 回表），跨学生访问查 `user_relations`。路由用依赖，service 用 `ensure_student_access`。本卡不新增生产接口，验收靠测试内临时 FastAPI 应用。

**Tech Stack:** Python 3.11 + FastAPI 0.143 + SQLAlchemy 2.1 + Pytest 9。

**Spec:** `docs/spec/s2-3-rbac.md`

## Global Constraints

- 不新增依赖、不新增迁移、**不新增生产接口**（用户 2026-10-26 拍板）。
- admin **不绕过**学生数据权限；管理接口只用 `require_role("admin")`。
- 越权统一 `403/40300`「无权访问该资源」，不区分“无权限”与“目标不存在”。
- 权限判定只看数据库 `role` 与 `user_relations`，token 里的 role 不参与。
- 测试禁止连真实数据库：`get_db` 一律依赖覆盖 + fake session。
- 任务卡硬验收用例名固定为 `test_b_cannot_read_a_notes_returns_403`（论文可引用）。
- 命令在仓库根 `E:\BiShe-AIStudy\study-agent` 的 Git Bash 下执行。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/core/permissions.py` | 两个依赖工厂 + 两个服务层函数 | 新建 |
| `backend/tests/test_permissions.py` | 纯函数/依赖单元测试（13 例） | 新建 |
| `backend/tests/test_permissions_api.py` | 测试内临时 FastAPI 应用（10 例，含硬验收） | 新建 |
| `docs/API.md` | §0 权限矩阵与隔离规则 | 修改 |
| `AGENTS.md` | §9.2 学生数据接口约定、§9.6 权限锚点 | 修改 |
| `docs/DECISIONS.md` | D-023 | 修改 |
| `docs/PROGRESS.md` | 进度与变更日志 | 修改 |

---

### Task 1: 先写测试（红）

**Files:**
- Create: `backend/tests/test_permissions.py`、`backend/tests/test_permissions_api.py`

**Interfaces:**
- 测试依赖（Task 2 实现）：`app.core.permissions.{require_role, require_student_access, has_student_relation, can_access_student, ensure_student_access}`。

- [ ] **Step 1: 写单元测试 `tests/test_permissions.py`**

```python
"""S2-3 权限单元测试：真值表、依赖工厂、服务层守卫（spec §6.1）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import ForbiddenError
from app.core.permissions import (
    can_access_student,
    ensure_student_access,
    has_student_relation,
    require_role,
    require_student_access,
)
from app.models.user import User
from app.models.user_relation import UserRelation


class FakeSession:
    """只回答两种查询：select(User) 与 select(UserRelation.id)。"""

    def __init__(self, *, user: User | None = None, relation: int | None = None) -> None:
        self.user = user
        self.relation = relation
        self.statements: list[object] = []

    def scalar(self, statement: object):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected statement: {statement}")


def _user(user_id: int, role: str) -> User:
    user = User(
        username=f"user_{user_id}",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


STUDENT_A = _user(1, "student")
STUDENT_B = _user(2, "student")
PARENT = _user(3, "parent")
TEACHER = _user(4, "teacher")
ADMIN = _user(5, "admin")


def test_self_can_access_own_data() -> None:
    session = FakeSession(user=STUDENT_A)
    assert can_access_student(session, STUDENT_A, STUDENT_A.id) is True
    assert session.statements == []  # 本人直接放行，不查关系表


def test_bound_parent_can_access_student() -> None:
    session = FakeSession(user=PARENT, relation=10)
    assert can_access_student(session, PARENT, STUDENT_A.id) is True


def test_unbound_parent_cannot_access_student() -> None:
    session = FakeSession(user=PARENT, relation=None)
    assert can_access_student(session, PARENT, STUDENT_A.id) is False


def test_bound_teacher_can_access_student() -> None:
    session = FakeSession(user=TEACHER, relation=11)
    assert can_access_student(session, TEACHER, STUDENT_A.id) is True


def test_unbound_teacher_cannot_access_student() -> None:
    session = FakeSession(user=TEACHER, relation=None)
    assert can_access_student(session, TEACHER, STUDENT_A.id) is False


def test_other_student_cannot_access() -> None:
    session = FakeSession(user=STUDENT_B)
    assert can_access_student(session, STUDENT_B, STUDENT_A.id) is False
    assert session.statements == []  # 学生角色不查关系表


def test_admin_does_not_bypass_student_access() -> None:
    session = FakeSession(user=ADMIN, relation=None)
    assert can_access_student(session, ADMIN, STUDENT_A.id) is False


def test_admin_can_access_own_data() -> None:
    session = FakeSession(user=ADMIN)
    assert can_access_student(session, ADMIN, ADMIN.id) is True


def test_ensure_student_access_raises_403_for_outsider() -> None:
    session = FakeSession(user=STUDENT_B)
    with pytest.raises(ForbiddenError) as excinfo:
        ensure_student_access(session, STUDENT_B, STUDENT_A.id)
    assert excinfo.value.code == 40300
    assert excinfo.value.message == "无权访问该资源"


def test_ensure_student_access_passes_for_bound_parent() -> None:
    session = FakeSession(user=PARENT, relation=10)
    ensure_student_access(session, PARENT, STUDENT_A.id)


def test_require_role_rejects_unknown_role_name() -> None:
    with pytest.raises(ValueError):
        require_role("admn")


def test_require_role_allows_and_denies() -> None:
    dependency = require_role("admin")
    assert dependency(ADMIN) is ADMIN
    with pytest.raises(ForbiddenError) as excinfo:
        dependency(STUDENT_A)
    assert excinfo.value.code == 40300


def test_has_student_relation_hit_and_miss() -> None:
    assert has_student_relation(FakeSession(user=PARENT, relation=10), viewer_id=3, student_id=1) is True
    assert has_student_relation(FakeSession(user=PARENT, relation=None), viewer_id=3, student_id=1) is False
```

> 说明：`require_student_access` 依赖要 `student_id` 路径参数，单元层不易直接调，放在 API 测试里覆盖。

- [ ] **Step 2: 写接口级测试 `tests/test_permissions_api.py`**

```python
"""S2-3 权限集成测试：测试内临时 FastAPI 应用（spec §6.2）。

生产代码不新增任何接口；这里挂两条测试路由，验证依赖行为，
其中 test_b_cannot_read_a_notes_returns_403 是任务卡硬验收。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import install_exception_handlers
from app.core.permissions import require_role, require_student_access
from app.core.security import create_access_token
from app.models.user import User
from app.models.user_relation import UserRelation


class FakeSession:
    def __init__(self, *, user: User, relation: int | None = None) -> None:
        self.user = user
        self.relation = relation

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected statement: {statement}")


def _user(user_id: int, username: str, role: str) -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


A = _user(1, "student_a", "student")
B = _user(2, "student_b", "student")
PARENT = _user(3, "parent_1", "parent")
TEACHER = _user(4, "teacher_1", "teacher")
ADMIN = _user(5, "admin_1", "admin")


def _make_app() -> FastAPI:
    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/students/{student_id}/notes")
    def student_notes(
        student_id: int, viewer: User = Depends(require_student_access)
    ) -> dict[str, object]:
        return {"owner_id": student_id, "viewer": viewer.username}

    @test_app.get("/admin/only")
    def admin_only(viewer: User = Depends(require_role("admin"))) -> dict[str, object]:
        return {"ok": True, "viewer": viewer.username}

    return test_app


def _client_for(user: User, *, relation: int | None = None) -> TestClient:
    test_app = _make_app()
    test_app.dependency_overrides[get_db] = lambda: FakeSession(user=user, relation=relation)
    return TestClient(test_app)


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def test_a_can_read_a_notes() -> None:
    with _client_for(A) as client:
        resp = client.get("/students/1/notes", headers=_headers(A))
    assert resp.status_code == 200
    assert resp.json()["owner_id"] == 1


def test_b_cannot_read_a_notes_returns_403() -> None:
    with _client_for(B) as client:
        resp = client.get("/students/1/notes", headers=_headers(B))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
    assert resp.json()["message"] == "无权访问该资源"


def test_bound_parent_can_read_student_notes() -> None:
    with _client_for(PARENT, relation=10) as client:
        resp = client.get("/students/1/notes", headers=_headers(PARENT))
    assert resp.status_code == 200


def test_unbound_parent_cannot_read_student_notes() -> None:
    with _client_for(PARENT, relation=None) as client:
        resp = client.get("/students/1/notes", headers=_headers(PARENT))
    assert resp.status_code == 403


def test_bound_teacher_can_read_student_notes() -> None:
    with _client_for(TEACHER, relation=11) as client:
        resp = client.get("/students/1/notes", headers=_headers(TEACHER))
    assert resp.status_code == 200


def test_admin_cannot_read_student_notes() -> None:
    with _client_for(ADMIN, relation=None) as client:
        resp = client.get("/students/1/notes", headers=_headers(ADMIN))
    assert resp.status_code == 403


def test_admin_can_read_admin_endpoint() -> None:
    with _client_for(ADMIN) as client:
        resp = client.get("/admin/only", headers=_headers(ADMIN))
    assert resp.status_code == 200


def test_student_cannot_read_admin_endpoint() -> None:
    with _client_for(A) as client:
        resp = client.get("/admin/only", headers=_headers(A))
    assert resp.status_code == 403


def test_missing_token_returns_401() -> None:
    with _client_for(A) as client:
        resp = client.get("/students/1/notes")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_unbound_parent_gets_403_even_for_missing_student() -> None:
    with _client_for(PARENT, relation=None) as client:
        resp = client.get("/students/999/notes", headers=_headers(PARENT))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
```

- [ ] **Step 3: 跑测试确认红**

Run:
```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_permissions.py tests/test_permissions_api.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.core.permissions'`

---

### Task 2: 实现 `core/permissions.py`（绿）

**Files:**
- Create: `backend/app/core/permissions.py`

**Interfaces:**
- Consumes: `get_current_user` / `get_db`（api/deps）、`ForbiddenError`、`UserRole`、`User`、`UserRelation`。
- Produces: 见下。

- [ ] **Step 1: 实现**

```python
"""S2-3 RBAC 与数据隔离（spec §4）。

为什么只做依赖、不做装饰器：FastAPI 依赖可组合、自动进 OpenAPI，
测试里能用 dependency_overrides 替换；装饰器会把参数与返回类型藏起来。

为什么 admin 不绕过 require_student_access：管理端有自己的 require_role("admin")
接口；若这里放行 admin，任何普通学生数据接口都会变成管理员的隐式全量读口子。
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenError
from app.models.enums import UserRole
from app.models.user import User
from app.models.user_relation import UserRelation

_VIEWER_ROLES = frozenset({UserRole.PARENT.value, UserRole.TEACHER.value})
_ALL_ROLES = frozenset(member.value for member in UserRole)


def require_role(*roles: str) -> Callable[..., User]:
    """管理接口用：只有列出的角色可进。

    角色名在工厂阶段校验：拼错立即 ValueError，不留到运行期变成静默 403。
    """
    allowed = frozenset(roles)
    unknown = allowed - _ALL_ROLES
    if unknown:
        raise ValueError(f"未知角色：{', '.join(sorted(unknown))}")
    if not allowed:
        raise ValueError("require_role 至少需要一个角色")

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise ForbiddenError("无权访问该资源")
        return current_user

    return dependency


def has_student_relation(session: Session, *, viewer_id: int, student_id: int) -> bool:
    """查看方是否已绑定该学生（user_relations.teacher_id 语义为“查看方”）。"""
    stmt = select(UserRelation.id).where(
        UserRelation.teacher_id == viewer_id,
        UserRelation.student_id == student_id,
    )
    return session.scalar(stmt) is not None


def can_access_student(session: Session, viewer: User, student_id: int) -> bool:
    if viewer.id == student_id:
        return True
    if viewer.role not in _VIEWER_ROLES:
        return False
    return has_student_relation(session, viewer_id=viewer.id, student_id=student_id)


def ensure_student_access(session: Session, viewer: User, student_id: int) -> None:
    """service 层用：资源的 user_id 来自数据库时，先拿它调这里再继续查/改。"""
    if not can_access_student(session, viewer, student_id):
        raise ForbiddenError("无权访问该资源")


def require_student_access(
    student_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> User:
    """路由依赖：本人或已绑定家长/老师放行。

    只能用于路径含 ``{student_id}`` 的路由（FastAPI 按同名参数从路径注入）；
    若路径没有该参数，FastAPI 会把它当 query 参数——此时请改用
    ensure_student_access()。
    """
    ensure_student_access(session, current_user, student_id)
    return current_user
```

- [ ] **Step 2: 跑本卡测试**

Run:
```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_permissions.py tests/test_permissions_api.py -q
```
Expected: `23 passed`

- [ ] **Step 3: 全量回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `260 passed, 1 warning`（基线 237 + 23）

- [ ] **Step 4: 提交**

```bash
git add backend/app/core/permissions.py backend/tests/test_permissions.py backend/tests/test_permissions_api.py
git commit -m "feat(s2-3): RBAC 与数据隔离依赖"
```

---

### Task 3: 文档同步与收尾

**Files:**
- Modify: `docs/API.md`、`AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`

- [ ] **Step 1: API.md §0**

把认证行的尾巴 `⚠ RBAC 细则 S2-3 定稿` 去掉，改为 `RBAC 与数据隔离见下`，并在该行后插入：

```markdown
- 角色与数据范围（S2-3 定稿）：

| 角色 | 数据范围 | 说明 |
|---|---|---|
| student | 仅本人 | 学生数据接口隐式 `WHERE user_id = 当前用户` |
| parent / teacher | 本人 + 已绑定学生 | 绑定关系在 `user_relations`（`teacher_id`=查看方）；跨学生访问必须过 `require_student_access` / `ensure_student_access` |
| admin | 仅专用管理接口 | 通过 `require_role("admin")` 判定；**不继承**学生数据权限 |

- 数据隔离（S2-3 定稿）：访问他人学生数据失败统一 `403/40300`「无权访问该资源」，不区分“无权限”与“不存在”；服务层查询必须显式 `WHERE <model>.user_id = <已授权学生>`，禁止只校验角色就返回数据；token 内 `role` 不作为权限来源（以数据库为准）。
```

- [ ] **Step 2: AGENTS.md**

§9.2 在「数据库」那条之后加：

```markdown
- 学生数据接口（S2-3）：先过 `require_student_access` / `ensure_student_access`，再查库；SQL 显式 `where(<Model>.user_id == student_id)`，越权统一 `403/40300`，不泄露目标是否存在
```

§9.6 在「后端认证样例」之后加：

```markdown
- 权限样例：backend/app/core/permissions.py（`require_role` 工厂校验角色名；`require_student_access` 用于 `/students/{student_id}/...` 路径；service 用 `ensure_student_access`；本人或已绑定 parent/teacher 放行，admin 不绕过；越权 403/40300）
```

- [ ] **Step 3: DECISIONS.md 追加 D-023**

按 D-021/D-022 的格式写：6 条决策（验收载体、admin 不绕过、查看方角色、403 不泄露、依赖而非装饰器、DB 为准）+ 验证（pytest 数字）+ 已知不足（无绑定管理接口/审计/缓存、本卡无 curl）。验证数字用 Task 2 Step 3 的实测值。

- [ ] **Step 4: PROGRESS.md**

1. 当前状态：最近完成 S2-3，下一步 S2-4；
2. 任务清单 S2-3 打 `[x]`；
3. 遗留问题表加：无家长-学生绑定管理接口（S2-5 起用 SQL 或后续卡）、无越权审计日志；
4. 变更日志追加 `### 2026-10-26（S2-3）`：交付、决策、验收证据（pytest 数字 + 硬验收用例名）、已知限制、文档同步。

- [ ] **Step 5: 全量回归 + 工作区核对**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd .. && git status --short && git log --oneline -3
```
Expected: `260 passed`；工作区仅剩文档改动；最新提交为 feat(s2-3)。

- [ ] **Step 6: 提交**

```bash
git add docs/ AGENTS.md
git commit -m "docs(s2-3): 权限矩阵、决策与进度同步"
```

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §2.1 做（permissions + 测试 + 文档） | Task 1–3 |
| §2.3 决策 6 条 | Task 2 代码注释 + Task 3 文档 |
| §3 权限模型 | Task 1 真值表 + Task 3 API.md |
| §4 函数契约 | Task 2 |
| §5 使用约定 | Task 3 AGENTS + spec 留存 |
| §6 测试（13 + 10） | Task 1 |
| §7 验收 | Task 2 Step 2–3、Task 3 Step 5 |
| §8 已知限制 | Task 3 Step 3–4 |
| §9 文档同步 | Task 3 Step 1–2、6 |

**2. Placeholder scan**：无 TBD；每个代码步骤给出完整文件内容。

**3. Type consistency**：`require_role` 返回 `Callable[..., User]`；`require_student_access` 返回 `User`；`ensure_student_access` 返回 `None`；`can_access_student`/`has_student_relation` 返回 `bool`；错误码 `40300` 与 `ForbiddenError` 默认一致。

## 执行记录

- 2026-10-26 实施完成，2 个功能提交 + 本条文档提交：`c893a9d` 权限依赖与测试 → 本条 `docs(s2-3)`。
- 测试：`pytest -q` → **260 passed, 1 warning**（基线 237 + 新增 23：单元 13 + 接口 10）。
- 硬验收：`tests/test_permissions_api.py::test_b_cannot_read_a_notes_returns_403` PASSED（403 / 40300 /「无权访问该资源」）。
- 与 plan 的偏差：无。测试内临时应用按 plan 的干净写法（`_make_app()` + `_client_for()`），未留下 `_CURRENT_APP` 之类的隐式全局。
- 说明：本卡无生产接口，**没有 curl 证据**；S2-5 用真实笔记接口补 A/B 403 的端到端演示。