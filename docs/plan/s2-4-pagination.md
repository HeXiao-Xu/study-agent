# S2-4 通用分页/排序/筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `PageData[T]`、`PageParams`/`SortParams` 依赖、`paginate_query()` 与 `apply_sort()`，让 S2-5/S4 的列表接口一行接入统一分页与白名单排序。

**Architecture:** `fastapi-pagination` 只负责执行（count + limit/offset），响应形状由自建 `PageData` 固定为 `{items,total,page,page_size}` 并套进 `Envelope`。排序用「字段名 → 列对象」白名单映射，非法输入抛 `InvalidParamError`（42200）。

**Tech Stack:** Python 3.11 + FastAPI 0.143 + Pydantic 2.14 + SQLAlchemy 2.1 + fastapi-pagination 0.16.1 + Pytest 9（测试用 SQLite 内存库）。

**Spec:** `docs/spec/s2-4-pagination.md`

## Global Constraints

- 只新增一个依赖：`fastapi-pagination==0.16.1`（2026-10-26 用户批准）；不加 `python-multipart` 等无关包。
- 响应固定 `{items, total, page, page_size}`，**不得**把库原生的 `size`/`pages` 泄给前端。
- query 参数固定 `page`（默认 1，≥1）/ `page_size`（默认 20，1–100）/ `sort_by` / `order`（asc|desc，默认 desc）。
- 排序只接受白名单字段；禁止字符串拼接 `order_by`。
- 不新增生产路由；本卡无 curl 证据（留 S2-5/S4）。
- 测试不连 PostgreSQL、不发网络请求；分页逻辑用 SQLite 内存库真执行。
- 命令在仓库根 `E:\BiShe-AIStudy\study-agent` 的 Git Bash 下执行。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/requirements.txt` | 钉 `fastapi-pagination==0.16.1` | 修改 |
| `backend/app/schemas/common.py` | 新增 `PageData[T]` | 修改 |
| `backend/app/utils/pagination.py` | 参数依赖、分页执行、白名单排序 | 新建 |
| `backend/tests/test_pagination.py` | 单元测试 12 条（SQLite 真执行） | 新建 |
| `backend/tests/test_pagination_api.py` | 接口测试 8 条（临时 FastAPI 应用） | 新建 |
| `docs/API.md` | §0 分页/排序定稿 | 修改 |
| `AGENTS.md` | §9.2 列表接口约定、§9.6 分页锚点 | 修改 |
| `docs/DECISIONS.md` | D-024 | 修改 |
| `docs/PROGRESS.md` | 进度与变更日志 | 修改 |

---

### Task 1: 依赖与失败测试（红）

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/test_pagination.py`、`backend/tests/test_pagination_api.py`

**Interfaces:**
- 测试依赖（Task 2 实现）：`app.utils.pagination.{PageParams, SortParams, page_params, sort_params, paginate_query, apply_sort}`、`app.schemas.common.PageData`。

- [ ] **Step 1: 安装并钉版本**

```bash
cd /e/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple "fastapi-pagination==0.16.1"
.venv/Scripts/python.exe -m pip list | grep -i fastapi-pagination
```

`backend/requirements.txt` 追加（放在 S2-2 认证段之后）：

```
# --- S2-4 通用分页（任务卡点名；版本 2026-10-26 实测）---
fastapi-pagination==0.16.1
```

- [ ] **Step 2: 写单元测试 `tests/test_pagination.py`**

```python
"""S2-4 分页与排序单元测试（spec §6.1）。

用 SQLite 内存库真执行 SQL：分页件没有业务逻辑，只有真实执行才能证明
count 与 limit/offset 的配合正确；SQLite 是进程内库，不违反“测试不连外部服务”。
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.exceptions import InvalidParamError
from app.schemas.common import PageData
from app.utils.pagination import PageParams, apply_sort, page_params, paginate_query


class _Base(DeclarativeBase):
    pass


class Demo(_Base):
    __tablename__ = "pagination_demo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class DemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


@pytest.fixture
def session() -> Session:
    # 内存库默认每个连接一份；StaticPool 让 Session 始终复用同一连接（TestClient 跨线程也成立）
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Demo(name=f"n{index}") for index in range(5)])
        db.commit()
        yield db


def _ids(page: PageData[DemoOut]) -> list[int]:
    return [item.id for item in page.items]


def test_page_params_defaults() -> None:
    params = PageParams()
    assert (params.page, params.page_size) == (1, 20)


def test_page_params_dependency_builds_dataclass() -> None:
    assert page_params(2, 10) == PageParams(page=2, page_size=10)


def test_paginate_first_page(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=1, page_size=2), item_model=DemoOut)
    assert _ids(page) == [1, 2]
    assert (page.total, page.page, page.page_size) == (5, 1, 2)


def test_paginate_second_page(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=2, page_size=2), item_model=DemoOut)
    assert _ids(page) == [3, 4]
    assert page.total == 5


def test_paginate_beyond_last_page_returns_empty(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=9, page_size=2), item_model=DemoOut)
    assert page.items == []
    assert page.total == 5


def test_paginate_converts_items_to_output_model(session: Session) -> None:
    page = paginate_query(
        session, select(Demo).order_by(Demo.id), PageParams(), item_model=DemoOut
    )
    assert all(isinstance(item, DemoOut) for item in page.items)


def test_apply_sort_ascending(session: Session) -> None:
    stmt = apply_sort(select(Demo), sort_by="id", order="asc", allowed={"id": Demo.id})
    assert [item.id for item in session.scalars(stmt).all()] == [1, 2, 3, 4, 5]


def test_apply_sort_descending(session: Session) -> None:
    stmt = apply_sort(
        select(Demo), sort_by="name", order="desc", allowed={"name": Demo.name}
    )
    assert [item.name for item in session.scalars(stmt).all()] == ["n4", "n3", "n2", "n1", "n0"]


def test_apply_sort_rejects_unknown_field() -> None:
    with pytest.raises(InvalidParamError) as excinfo:
        apply_sort(select(Demo), sort_by="password", order="asc", allowed={"id": Demo.id})
    assert excinfo.value.code == 42200
    assert "不支持的排序字段" in excinfo.value.message


def test_apply_sort_rejects_unknown_order() -> None:
    with pytest.raises(InvalidParamError):
        apply_sort(select(Demo), sort_by="id", order="sideways", allowed={"id": Demo.id})


def test_apply_sort_without_sort_or_default_keeps_stmt() -> None:
    stmt = apply_sort(select(Demo), sort_by=None, order="desc", allowed={"id": Demo.id})
    assert "ORDER BY" not in str(stmt)


def test_apply_sort_uses_default_sort() -> None:
    stmt = apply_sort(
        select(Demo), sort_by=None, order="asc", allowed={"id": Demo.id}, default_sort="id"
    )
    assert "ORDER BY" in str(stmt)
```

- [ ] **Step 3: 写接口测试 `tests/test_pagination_api.py`**

```python
"""S2-4 分页参数与响应形状接口测试（spec §6.2）。"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.exceptions import install_exception_handlers
from app.schemas.common import Envelope, PageData
from app.utils.pagination import (
    PageParams,
    SortParams,
    apply_sort,
    page_params,
    paginate_query,
    sort_params,
)


class _Base(DeclarativeBase):
    pass


class Demo(_Base):
    __tablename__ = "pagination_api_demo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class DemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


SORT_FIELDS = {"id": Demo.id, "name": Demo.name}


@pytest.fixture
def session() -> Iterator[Session]:
    # TestClient 在另一个线程里跑路由；StaticPool 保证它和夹具共用同一个内存库连接
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Demo(name=f"n{index}") for index in range(5)])
        db.commit()
        yield db


def _make_app(db: Session) -> FastAPI:
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.dependency_overrides[get_db] = lambda: db

    @test_app.get("/demos", response_model=Envelope[PageData[DemoOut]])
    def list_demos(
        params: PageParams = Depends(page_params),
        sorting: SortParams = Depends(sort_params),
        session: Session = Depends(get_db),
    ) -> Envelope[PageData[DemoOut]]:
        stmt = apply_sort(
            select(Demo),
            sort_by=sorting.sort_by,
            order=sorting.order,
            allowed=SORT_FIELDS,
            default_sort="id",
        )
        return Envelope(
            trace_id=get_trace_id(),
            data=paginate_query(session, stmt, params, item_model=DemoOut),
        )

    return test_app


def _client(db: Session) -> TestClient:
    return TestClient(_make_app(db))


def test_default_request_returns_four_field_page(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert (data["total"], data["page"], data["page_size"]) == (5, 1, 20)


def test_second_page_returns_expected_items(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page": 2, "page_size": 2})
    data = resp.json()["data"]
    assert [item["id"] for item in data["items"]] == [3, 2]  # 默认 id desc


def test_page_zero_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page": 0})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_page_size_over_limit_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page_size": 101})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_unknown_sort_field_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"sort_by": "password"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200
    assert "不支持的排序字段" in resp.json()["message"]


def test_invalid_order_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"order": "sideways"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_sort_by_name_ascending(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"sort_by": "name", "order": "asc"})
    names = [item["name"] for item in resp.json()["data"]["items"]]
    assert names == ["n0", "n1", "n2", "n3", "n4"]


def test_total_is_stable_across_pages(session: Session) -> None:
    with _client(session) as client:
        first = client.get("/demos", params={"page": 1, "page_size": 2}).json()["data"]
        second = client.get("/demos", params={"page": 2, "page_size": 2}).json()["data"]
    assert first["total"] == second["total"] == 5
```

- [ ] **Step 4: 跑测试确认红**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_pagination.py tests/test_pagination_api.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.utils.pagination'`（或 `ImportError: cannot import name 'PageData'`）

---

### Task 2: 实现分页件（绿）

**Files:**
- Modify: `backend/app/schemas/common.py`
- Create: `backend/app/utils/pagination.py`

**Interfaces:**
- Consumes: `fastapi_pagination.{Params}`, `fastapi_pagination.ext.sqlalchemy.paginate`、`InvalidParamError`。
- Produces: 见 §4。

- [ ] **Step 1: `schemas/common.py` 加 `PageData`**

在 `Envelope` 之后追加：

```python
class PageData(BaseModel, Generic[T]):
    """列表接口的统一分页 data（API.md §0，S2-4）。

    只暴露任务卡要求的 4 个字段；底层 fastapi-pagination 的 size/pages 不泄给前端。
    """

    items: list[T]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 2: 写 `utils/pagination.py`**

```python
"""S2-4 统一分页/排序（spec §4）。

分页执行交给 fastapi-pagination（count 会剥掉 ORDER BY，limit/offset 由库生成），
但响应形状固定为 PageData 的 {items,total,page,page_size}，不把库的 size/pages 泄给前端。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from fastapi import Query
from fastapi_pagination import Params
from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa
from pydantic import BaseModel
from sqlalchemy import Select, asc, desc
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.schemas.common import PageData

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True)
class SortParams:
    sort_by: str | None = None
    order: str = "desc"


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数（1–100）"
    ),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def sort_params(
    sort_by: str | None = Query(None, description="排序字段（白名单见各接口）"),
    order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
) -> SortParams:
    return SortParams(sort_by=sort_by, order=order)


def paginate_query(
    session: Session,
    stmt: Select,
    params: PageParams,
    *,
    item_model: type[T],
) -> PageData[T]:
    page = paginate_sa(
        session,
        stmt,
        params=Params(page=params.page, size=params.page_size),
    )
    return PageData(
        items=[item_model.model_validate(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.size,
    )


def apply_sort(
    stmt: Select,
    *,
    sort_by: str | None,
    order: str,
    allowed: Mapping[str, Any],
    default_sort: str | None = None,
) -> Select:
    """白名单排序：allowed 的 key 才能出现在 ORDER BY，从结构上防注入。"""
    field = sort_by or default_sort
    if field is None:
        return stmt
    column = allowed.get(field)
    if column is None:
        options = ", ".join(sorted(allowed))
        raise InvalidParamError(f"不支持的排序字段：{field}（可选：{options}）")
    direction = order.lower()
    if direction not in {"asc", "desc"}:
        raise InvalidParamError("排序方向只能是 asc 或 desc")
    return stmt.order_by(asc(column) if direction == "asc" else desc(column))
```

- [ ] **Step 3: 跑本卡测试**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_pagination.py tests/test_pagination_api.py -q
```
Expected: `20 passed`

- [ ] **Step 4: 全量回归**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```
Expected: `280 passed, 1 warning`（基线 260 + 20）

- [ ] **Step 5: 提交**

```bash
git add backend/requirements.txt backend/app/schemas/common.py backend/app/utils/pagination.py backend/tests/test_pagination.py backend/tests/test_pagination_api.py
git commit -m "feat(s2-4): 通用分页与白名单排序"
```

---

### Task 3: 文档同步与收尾

**Files:**
- Modify: `docs/API.md`、`AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`

- [ ] **Step 1: API.md §0**

把原来的 `- 分页：列表接口统一分页参数（fastapi-pagination，S2-4 交付）` 替换为：

```markdown
- 分页（S2-4 定稿）：所有列表接口统一 query `page`（默认 1，≥1）+ `page_size`（默认 20，1–100）；响应 `data = {items, total, page, page_size}`；越界/非整数 → `422/42200`；超过末页返回空 `items`，`total` 不变
- 排序（S2-4 定稿）：`sort_by`（字段白名单，各接口在文档中列出）+ `order`（`asc`/`desc`，默认 `desc`）；非白名单字段 → `422/42200`「不支持的排序字段：xxx（可选：...）」；筛选一律显式 query 参数，不使用通用 filter DSL
```

- [ ] **Step 2: AGENTS.md**

§9.2 在「学生数据接口（S2-3）」之后加：

```markdown
- 列表接口（S2-4）：统一用 `page_params` / `sort_params` / `paginate_query` / `apply_sort`（utils/pagination.py）；禁止手写 `limit/offset`、禁止字符串拼接 `order_by`；排序字段必须来自白名单映射
```

§9.6 在「权限样例」之后加：

```markdown
- 分页样例：backend/app/utils/pagination.py + backend/app/schemas/common.py 的 `PageData`（`{items,total,page,page_size}` 套 `Envelope`；fastapi-pagination 只负责 count + limit/offset；`apply_sort` 白名单防注入；非法字段 422/42200）
```

- [ ] **Step 3: DECISIONS.md 追加 D-024**

6 条决策（库选型、形状适配、上限 100、白名单、默认排序、SQLite 测试）+ 验证（pytest 数字）+ 已知不足（count/深分页成本、无 cursor/多字段/pages、本卡无 curl）。验证数字用 Task 2 Step 4 的实测值。

- [ ] **Step 4: PROGRESS.md**

1. 当前状态：最近完成 S2-4，下一步 S2-5；
2. 任务清单 S2-4 打 `[x]`；
3. 遗留问题表加：深分页 count/offset 成本（量大改 keyset）、无多字段排序、无 `pages` 字段；
4. 变更日志追加 `### 2026-10-26（S2-4）`：交付、依赖、决策、验收（pytest 数字、20 条用例构成）、复用计划（S2-5/S4）、已知限制、文档同步。

- [ ] **Step 5: 全量回归 + 工作区核对**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd .. && git status --short && git log --oneline -3
```
Expected: `280 passed`；工作区仅剩文档；最新提交为 feat(s2-4)。

- [ ] **Step 6: 提交**

```bash
git add docs/ AGENTS.md
git commit -m "docs(s2-4): 分页契约、决策与进度同步"
```

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §2.1 做（PageData/参数依赖/执行/排序/测试/依赖/文档） | Task 1–3 |
| §2.3 决策 7 条 | Task 2 实现 + Task 3 文档 |
| §3 契约（参数、响应、排序） | Task 2 + Task 3 API.md |
| §4 函数契约 | Task 2 |
| §5 使用约定 | Task 3 AGENTS + spec 留存 |
| §6 测试（12 + 8） | Task 1 |
| §7 验收 | Task 2 Step 3–4、Task 3 Step 5 |
| §8 已知限制 | Task 3 Step 3–4 |
| §9 文档同步 | Task 3 Step 1–2、6 |

**2. Placeholder scan**：无 TBD；每个代码步骤给出完整文件内容；文档步骤给出精确替换文本。

**3. Type consistency**：`PageData[T]`（schemas/common）被 `paginate_query` 返回；`PageParams`/`SortParams` 为 frozen dataclass；`apply_sort` 接受 `Mapping[str, Any]`（列对象）；错误码 `42200` 与 `InvalidParamError` 一致；`item_model: type[T]` 限定 Pydantic 模型。

## 执行记录

- 2026-10-26 实施完成，2 个提交：`092633d` feat 分页件与测试 → 本条 `docs(s2-4)`。
- 测试：`pytest tests/test_pagination.py tests/test_pagination_api.py -q` → **20 passed**；全量 `pytest -q` → **280 passed, 1 warning**（基线 260 + 20）。
- 与 plan 的唯一偏差：测试夹具改用 `StaticPool` + `check_same_thread=False`。原因：SQLite 内存库默认每连接一份，TestClient 在另一线程执行路由会拿到新连接，报 `no such table`（首次运行 4 failed / 16 passed）；加 StaticPool 后共用同一连接。已回填到 plan 代码块，spec §2.3-7 同步说明。
- 说明：本卡无生产接口，**没有 curl 证据**；复用验收在 S2-5（笔记列表）与 S4（错题/题目列表）落地时补。