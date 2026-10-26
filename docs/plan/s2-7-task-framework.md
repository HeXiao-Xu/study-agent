# S2-7 异步任务框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 ARQ + Postgres 状态表交付可提交、可轮询、可重试的异步任务框架，并用 `demo.sleep` 任务做端到端验收。

**Architecture:** 提交时先写 `async_tasks`（pending）再投 ARQ 队列（job id 固定 `task:{id}`）；独立 Worker 进程执行 `run_task`，在线程池里跑同步处理函数，按状态机回写 running/succeeded/failed；ARQ 只负责投递与延时重试，状态与历史全部在 DB。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.1（同步）、Alembic、PostgreSQL 16、ARQ 0.28.0（redis 5.3.1）、pytest。

**Spec:** `docs/spec/s2-7-task-framework.md`

## Global Constraints

- 依赖只加 `arq==0.28.0` 与 `redis==5.3.1`（后者已被 arq 拉入，显式锁定版本）；不得引入 Celery。
- ARQ 0.28 的 `enqueue_job` 参数只有 `_job_id/_queue_name/_defer_*/_expires/_job_try`；**没有** `_max_tries`/`_job_timeout`，这两个只能写在 `WorkerSettings`（`max_tries`/`job_timeout`）。传进去会被当作函数 kwargs。
- Redis 一律用 `redis://127.0.0.1:6379/0`：Windows 解析 `localhost` 先走 `::1`，Docker 只发布 IPv4，会 20s 超时（与 `core/db.py` 里 Postgres 的注释同因）。
- 处理函数签名固定为同步 `(Session, dict[str, Any]) -> dict[str, Any] | None`；处理器**不得自行 `commit`**，由框架统一提交/回滚。
- 状态值只允许 `pending/running/succeeded/failed`；枚举常量进 `app/models/enums.py`，CHECK 用 `in_check`（D-021）。
- 测试禁止连 Redis/Postgres：队列、session 一律注入假实现。
- 提交信息用 Conventional Commits 并带 `(s2-7)`；`git push` 由用户执行。
- 接口契约以 `docs/API.md` 为准；本卡新增两个接口，改动前先补文档（Task 7 前先按 spec §5 实现，Task 7 同步）。

---

### Task 1: 依赖、配置、枚举、模型与迁移 0004

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/exceptions.py`
- Modify: `backend/app/models/enums.py`
- Create: `backend/app/models/async_task.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0004_s2_7_async_tasks.py`
- Modify: `.env.example`
- Modify: `.env`（本地未跟踪文件，仅把 Redis 主机改成 127.0.0.1）
- Test: 无单测；本任务以 `alembic upgrade head` + `alembic check` + psql 验证

**Interfaces:**
- Consumes: `app.core.db.Base`、`app.models.enums.in_check`
- Produces: `TaskStatus`（`PENDING/RUNNING/SUCCEEDED/FAILED`）、`AsyncTask`（字段 `id/user_id/name/status/payload/result/error/attempts/created_at/started_at/finished_at`）、`TaskQueueUnavailableError`、`Settings.task_max_tries/task_retry_base_seconds/task_job_timeout_seconds/task_result_keep_seconds`

- [ ] **Step 1: 锁定依赖**

`backend/requirements.txt` 末尾追加：

```
# --- S2-7 异步任务框架（ARQ + Redis；2026-10-26 用户批准）---
arq==0.28.0
redis==5.3.1
```

安装并确认（已在本机装过 arq 0.28.0，redis 被解析为 5.3.1）：

Run: `cd backend && ../.venv/Scripts/python.exe -m pip install -q -i https://repo.huaweicloud.com/repository/pypi/simple arq==0.28.0 && ../.venv/Scripts/python.exe -m pip show arq redis | grep -E "^(Name|Version)"`
Expected: `Name: arq / Version: 0.28.0`、`Name: redis / Version: 5.3.1`

- [ ] **Step 2: 配置项**

`backend/app/core/config.py` 在 MinIO/上传配置之后追加：

```python
    # --- S2-7 异步任务（ARQ Worker）---
    task_max_tries: int = 3
    task_retry_base_seconds: float = 2.0
    task_job_timeout_seconds: int = 300
    task_result_keep_seconds: int = 3600
```

`.env.example` 在 `UPLOAD_ALLOWED_EXTENSIONS` 之后追加：

```
TASK_MAX_TRIES=3
TASK_RETRY_BASE_SECONDS=2.0
TASK_JOB_TIMEOUT_SECONDS=300
TASK_RESULT_KEEP_SECONDS=3600
```

`.env.example` 与本地 `.env` 的 `REDIS_URL` 都改为：

```
REDIS_URL=redis://127.0.0.1:6379/0
```

- [ ] **Step 3: 异常类型**

`backend/app/core/exceptions.py` 在 `StorageUnavailableError` 之后追加：

```python
class TaskQueueUnavailableError(AppError):
    """任务入队失败：Redis 不可用或队列操作异常（不泄露地址）。"""

    def __init__(self, message: str = "任务队列不可用") -> None:
        super().__init__(message, code=CODE_INTERNAL_ERROR, http_status=500)
```

- [ ] **Step 4: 枚举**

`backend/app/models/enums.py` 在 `EdgeSource` 之后追加：

```python
class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
```

- [ ] **Step 5: 模型**

`backend/app/models/async_task.py`：

```python
"""async_tasks ORM 模型（S2-7）：异步任务状态，SCHEMA §4.4。

ARQ 只负责投递与延时重试；状态、结果与历史全部落这张表，
所以结果不会随 ARQ 的 keep_result 过期而消失。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import TaskStatus, in_check


class AsyncTask(Base):
    __tablename__ = "async_tasks"
    __table_args__ = (
        Index("ix_async_tasks_user_id_created_at", "user_id", "created_at"),
        Index("ix_async_tasks_status", "status"),
        CheckConstraint(
            in_check("status", [s.value for s in TaskStatus]),
            name="ck_async_tasks_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_async_tasks_user_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=TaskStatus.PENDING.value, server_default="pending"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`backend/app/models/__init__.py` 追加导入与 `__all__` 条目：`from app.models.async_task import AsyncTask`（按文件现有风格放）。

- [ ] **Step 6: 迁移**

`backend/alembic/versions/0004_s2_7_async_tasks.py`：

```python
"""S2-7 异步任务状态表 async_tasks

Revision ID: 0004_s2_7
Revises: 0003_s2_5
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_s2_7"
down_revision = "0003_s2_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "async_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_async_tasks_user_id"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_async_tasks_status",
        ),
    )
    op.create_index(
        "ix_async_tasks_user_id_created_at",
        "async_tasks",
        ["user_id", "created_at"],
    )
    op.create_index("ix_async_tasks_status", "async_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_async_tasks_status", table_name="async_tasks")
    op.drop_index("ix_async_tasks_user_id_created_at", table_name="async_tasks")
    op.drop_table("async_tasks")
```

- [ ] **Step 7: 迁移验证**

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head`
Expected: 含 `Running upgrade 0003_s2_5 -> 0004_s2_7`

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic check`
Expected: `No new upgrade operations detected.`

Run: `docker exec study-agent-postgres psql -U study -d study_agent -c "\d async_tasks"`
Expected: 表存在，`ck_async_tasks_status`、`fk_async_tasks_user_id`、两个索引都在

- [ ] **Step 8: 提交**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/app/core/exceptions.py backend/app/models/enums.py backend/app/models/async_task.py backend/app/models/__init__.py backend/alembic/versions/0004_s2_7_async_tasks.py .env.example
git commit -m "feat(s2-7): 异步任务表与队列配置"
```

---

### Task 2: 任务注册表、demo 任务与 ARQ 队列适配器

**Files:**
- Create: `backend/app/tasks/__init__.py`（导入 demo 触发注册）
- Create: `backend/app/tasks/registry.py`
- Create: `backend/app/tasks/demo.py`
- Create: `backend/app/tasks/queue.py`
- Test: `backend/tests/test_task_registry.py`、`backend/tests/test_task_queue.py`

**Interfaces:**
- Consumes: `app.core.config.get_settings`、`app.core.exceptions.TaskQueueUnavailableError`
- Produces: `TaskHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]`、`register(name)`、`get_handler(name)`、`HANDLERS`、`TASK_DEMO_SLEEP = "demo.sleep"`、`TaskQueue` 协议（`enqueue(name: str, task_id: int) -> None`）、`ArqTaskQueue`、`get_task_queue()`

- [ ] **Step 1: 写失败测试（注册表）**

`backend/tests/test_task_registry.py`：

```python
"""S2-7 任务注册表与 demo 任务。"""
from __future__ import annotations

import pytest

from app.tasks import registry
from app.tasks.demo import demo_sleep


def test_register_and_get_handler() -> None:
    def handler(session, payload):  # noqa: ANN001
        return {"ok": True}

    registry.register("unit.echo")(handler)
    assert registry.get_handler("unit.echo") is handler


def test_register_duplicate_name_raises() -> None:
    def handler(session, payload):  # noqa: ANN001
        return None

    registry.register("unit.dup")(handler)
    with pytest.raises(ValueError):
        registry.register("unit.dup")(handler)


def test_all_suffix_is_rejected() -> None:
    with pytest.raises(ValueError):
        registry.register("unit.all")


def test_demo_sleep_returns_slept_seconds() -> None:
    assert demo_sleep(None, {"seconds": 0}) == {"slept": 0}  # type: ignore[arg-type]


def test_demo_sleep_fail_raises() -> None:
    with pytest.raises(RuntimeError):
        demo_sleep(None, {"seconds": 0, "fail": True})  # type: ignore[arg-type]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_registry.py -q`
Expected: FAIL / INTERNALERROR，`ModuleNotFoundError: app.tasks.registry`

- [ ] **Step 3: 实现注册表**

`backend/app/tasks/registry.py`：

```python
"""任务注册表（S2-7）：任务名 → 同步处理函数。

处理函数签名 (Session, payload) -> dict | None；不得自行 commit，
由 runner 统一提交/回滚。名字以 ".all" 结尾是为未来的批量任务预留。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

TaskHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]

HANDLERS: dict[str, TaskHandler] = {}


def register(name: str) -> Callable[[TaskHandler], TaskHandler]:
    if not name or name.endswith(".all"):
        raise ValueError(f"非法任务名：{name!r}")

    def decorator(func: TaskHandler) -> TaskHandler:
        if name in HANDLERS:
            raise ValueError(f"任务名已注册：{name}")
        HANDLERS[name] = func
        return func

    return decorator


def get_handler(name: str) -> TaskHandler | None:
    return HANDLERS.get(name)
```

`backend/app/tasks/demo.py`：

```python
"""验收/联调用的演示任务（S2-7）。"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.tasks.registry import register

TASK_DEMO_SLEEP = "demo.sleep"


@register(TASK_DEMO_SLEEP)
def demo_sleep(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    seconds = int(payload.get("seconds", 5))
    time.sleep(seconds)
    if payload.get("fail"):
        raise RuntimeError("演示任务按请求失败")
    return {"slept": seconds}
```

- [ ] **Step 4: 运行注册表测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_registry.py -q`
Expected: `5 passed`

- [ ] **Step 5: 写失败测试（队列）**

`backend/tests/test_task_queue.py`：

```python
"""S2-7 ARQ 队列适配器：假 pool，不连 Redis。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import TaskQueueUnavailableError
from app.tasks import queue as queue_module


class FakeJob:
    job_id = "task:9"


class FakePool:
    def __init__(self, *, result: FakeJob | None = None, error: Exception | None = None):
        self.result = result if result is not None else FakeJob()
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def enqueue_job(self, function, *args, **kwargs):  # noqa: ANN001
        self.calls.append({"function": function, "args": args, **kwargs})
        if self.error is not None:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> FakePool:
    fake = FakePool()
    created: list[FakePool] = []

    async def fake_create_pool(settings_=None):  # noqa: ANN001
        created.append(fake)
        return fake

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(
        queue_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://127.0.0.1:6379/0",
            task_job_timeout_seconds=300,
            task_max_tries=3,
        ),
    )
    fake.created = created  # type: ignore[attr-defined]
    return fake


def test_enqueue_passes_task_id_and_fixed_job_id(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    call = pool.calls[0]
    assert call["function"] == "run_task"
    assert call["args"] == (9,)
    assert call["_job_id"] == "task:9"


def test_enqueue_does_not_pass_worker_settings_as_kwargs(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert set(pool.calls[0]) == {"function", "args", "_job_id"}


def test_enqueue_closes_pool(pool: FakePool) -> None:
    queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert pool.closed is True


def test_enqueue_none_job_raises(pool: FakePool) -> None:
    pool.result = None
    with pytest.raises(TaskQueueUnavailableError):
        queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)


def test_enqueue_redis_error_is_wrapped(pool: FakePool) -> None:
    pool.error = OSError("connection refused")
    with pytest.raises(TaskQueueUnavailableError) as excinfo:
        queue_module.ArqTaskQueue().enqueue("demo.sleep", 9)
    assert "redis" not in excinfo.value.message.lower()
    assert pool.closed is True
```

- [ ] **Step 6: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_queue.py -q`
Expected: FAIL，`ModuleNotFoundError: app.tasks.queue`

- [ ] **Step 7: 实现队列适配器**

`backend/app/tasks/queue.py`：

```python
"""ARQ 队列适配器（S2-7）。

提交是低频动作（每次上传一次），所以每次 asyncio.run 建短连接；
比维护后台事件循环线程简单，测试也能直接注入 TaskQueue 假实现。

注意：ARQ 0.28 的 enqueue_job 没有 _max_tries/_job_timeout 参数，
超时与重试次数只能配在 WorkerSettings（worker.py）。
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Protocol

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.exceptions import TaskQueueUnavailableError


class TaskQueue(Protocol):
    def enqueue(self, name: str, task_id: int) -> None: ...


class ArqTaskQueue:
    def enqueue(self, name: str, task_id: int) -> None:
        asyncio.run(self._enqueue(name, task_id))

    async def _enqueue(self, name: str, task_id: int) -> None:
        settings = get_settings()
        pool = None
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            job = await pool.enqueue_job("run_task", task_id, _job_id=f"task:{task_id}")
            if job is None:
                raise TaskQueueUnavailableError()
        except TaskQueueUnavailableError:
            raise
        except Exception as exc:  # Redis/连接/序列化异常统一收敛，不泄露地址
            raise TaskQueueUnavailableError() from exc
        finally:
            if pool is not None:
                try:
                    await pool.aclose()
                except Exception:  # 关闭失败不影响已入队结果
                    pass


@lru_cache
def get_task_queue() -> TaskQueue:
    return ArqTaskQueue()
```

- [ ] **Step 8: 运行队列测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_queue.py tests/test_task_registry.py -q`
Expected: `10 passed`

- [ ] **Step 9: 提交**

```bash
git add backend/app/tasks/registry.py backend/app/tasks/demo.py backend/app/tasks/queue.py backend/tests/test_task_registry.py backend/tests/test_task_queue.py
git commit -m "feat(s2-7): 任务注册表、演示任务与 ARQ 队列适配器"
```

---

### Task 3: 任务服务（提交 / 查询）

**Files:**
- Create: `backend/app/services/task_service.py`
- Test: `backend/tests/test_task_service.py`

**Interfaces:**
- Consumes: `AsyncTask`、`TaskStatus`、`get_handler`、`TaskQueue`、`TaskQueueUnavailableError`、`InvalidParamError`、`NotFoundError`、`ForbiddenError`
- Produces: `TASK_DEMO_SLEEP`（从 demo 透传）、`create_task(session, *, owner, name, payload, queue) -> AsyncTask`、`submit_demo(session, *, owner, seconds, fail, queue) -> AsyncTask`、`get_task(session, *, task_id, viewer) -> AsyncTask`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_task_service.py`：

```python
"""S2-7 任务服务：假 session + 假队列，不连库不连 Redis。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    TaskQueueUnavailableError,
)
from app.models.async_task import AsyncTask
from app.models.user import User
from app.services import task_service


class FakeSession:
    def __init__(self) -> None:
        self.rows: dict[int, AsyncTask] = {}
        self.added: list[AsyncTask] = []
        self.commits = 0
        self.refreshed: list[AsyncTask] = []

    def add(self, instance: AsyncTask) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        for row in self.added:
            if row.id is None:
                row.id = 21
            row.created_at = datetime.now(timezone.utc)
            self.rows[row.id] = row

    def refresh(self, instance: AsyncTask) -> None:
        self.refreshed.append(instance)
        if instance.id is None:
            instance.id = 21
        if instance.created_at is None:
            instance.created_at = datetime.now(timezone.utc)

    def get(self, entity: type, pk: int):
        return self.rows.get(pk) if entity is AsyncTask else None


class FakeQueue:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))
        if self.error is not None:
            raise self.error


def _user(user_id: int = 1, *, role: str = "student") -> User:
    user = User(
        username=f"student_{user_id}",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    return user


def test_create_task_unknown_name_raises_422() -> None:
    with pytest.raises(InvalidParamError):
        task_service.create_task(
            FakeSession(),
            owner=_user(),
            name="no.such.task",
            payload={},
            queue=FakeQueue(),
        )


def test_create_task_persists_pending_and_enqueues() -> None:
    session, queue = FakeSession(), FakeQueue()
    task = task_service.create_task(
        session,
        owner=_user(),
        name="demo.sleep",
        payload={"seconds": 0},
        queue=queue,
    )
    assert task.id == 21
    assert task.status == "pending"
    assert task.user_id == 1
    assert queue.calls == [("demo.sleep", 21)]
    assert session.commits == 1


def test_create_task_enqueue_failure_marks_failed_and_raises() -> None:
    session = FakeSession()
    with pytest.raises(TaskQueueUnavailableError):
        task_service.create_task(
            session,
            owner=_user(),
            name="demo.sleep",
            payload={"seconds": 0},
            queue=FakeQueue(error=OSError("redis down")),
        )
    row = session.added[0]
    assert row.status == "failed"
    assert row.error == "任务入队失败"
    assert row.finished_at is not None
    assert session.commits == 2


def test_submit_demo_defaults_to_five_seconds() -> None:
    task = task_service.submit_demo(
        FakeSession(), owner=_user(), seconds=5, fail=False, queue=FakeQueue()
    )
    assert task.name == "demo.sleep"
    assert task.payload == {"seconds": 5, "fail": False}


def test_get_task_returns_own_task() -> None:
    session = FakeSession()
    task = task_service.submit_demo(
        session, owner=_user(), seconds=1, fail=False, queue=FakeQueue()
    )
    assert (
        task_service.get_task(session, task_id=21, viewer=_user(1)) is task
    )


def test_get_task_other_user_raises_403() -> None:
    session = FakeSession()
    task_service.submit_demo(
        session, owner=_user(1), seconds=1, fail=False, queue=FakeQueue()
    )
    with pytest.raises(ForbiddenError):
        task_service.get_task(session, task_id=21, viewer=_user(2))


def test_get_task_missing_raises_404() -> None:
    with pytest.raises(NotFoundError):
        task_service.get_task(FakeSession(), task_id=99, viewer=_user())


def test_demo_task_name_matches_registry() -> None:
    from app.tasks.registry import get_handler

    assert get_handler(task_service.TASK_DEMO_SLEEP) is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_service.py -q`
Expected: FAIL，`ModuleNotFoundError: app.services.task_service`

- [ ] **Step 3: 实现服务**

`backend/app/services/task_service.py`：

```python
"""S2-7 异步任务服务：提交（先落库再入队）、查询与权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    TaskQueueUnavailableError,
)
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.user import User
from app.tasks.demo import TASK_DEMO_SLEEP
from app.tasks.queue import TaskQueue
from app.tasks.registry import get_handler


def create_task(
    session: Session,
    *,
    owner: User,
    name: str,
    payload: dict[str, Any],
    queue: TaskQueue,
) -> AsyncTask:
    if get_handler(name) is None:
        raise InvalidParamError(f"未知任务类型：{name}")
    task = AsyncTask(
        user_id=owner.id,
        name=name,
        status=TaskStatus.PENDING.value,
        payload=payload,
        attempts=0,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    try:
        queue.enqueue(name, task.id)
    except Exception as exc:
        # 入队失败不能留下永远 pending 的幽灵任务
        task.status = TaskStatus.FAILED.value
        task.error = "任务入队失败"
        task.finished_at = datetime.now(timezone.utc)
        session.commit()
        raise TaskQueueUnavailableError() from exc
    return task


def submit_demo(
    session: Session,
    *,
    owner: User,
    seconds: int,
    fail: bool,
    queue: TaskQueue,
) -> AsyncTask:
    return create_task(
        session,
        owner=owner,
        name=TASK_DEMO_SLEEP,
        payload={"seconds": seconds, "fail": fail},
        queue=queue,
    )


def get_task(session: Session, *, task_id: int, viewer: User) -> AsyncTask:
    task = session.get(AsyncTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    if task.user_id != viewer.id:
        raise ForbiddenError("无权访问该任务")
    return task
```

- [ ] **Step 4: 运行服务测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_service.py -q`
Expected: `8 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/task_service.py backend/tests/test_task_service.py
git commit -m "feat(s2-7): 任务提交与查询服务"
```

---

### Task 4: 执行器（状态机 / 重试）与 Worker 入口

**Files:**
- Create: `backend/app/tasks/runner.py`
- Create: `backend/app/tasks/worker.py`
- Test: `backend/tests/test_task_runner.py`

**Interfaces:**
- Consumes: `new_session()`、`get_settings()`、`get_handler()`、`AsyncTask`、`TaskStatus`
- Produces: `TaskOutcome(status: str, retry_in: float | None)`、`execute_task(task_id: int, job_try: int) -> TaskOutcome`、`run_task(ctx, task_id)`（ARQ 协程）、`WorkerSettings`（供 `arq app.tasks.worker.WorkerSettings`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_task_runner.py`：

```python
"""S2-7 执行器：状态机、重试退避、幂等（假 session，不连库）。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.async_task import AsyncTask
from app.tasks import runner
from app.tasks import registry


class FakeSession:
    def __init__(self, task: AsyncTask | None) -> None:
        self.task = task
        self.commits = 0
        self.rollbacks = 0

    def get(self, entity: type, pk: int):
        return self.task

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeSessionCtx:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.closed = False

    def __enter__(self) -> FakeSession:
        return self.session

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


def _task(*, status: str = "pending", name: str = "demo.sleep") -> AsyncTask:
    task = AsyncTask(
        user_id=1,
        name=name,
        status=status,
        payload={"seconds": 0},
        attempts=0,
    )
    task.id = 5
    return task


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    ctx = FakeSessionCtx(FakeSession(_task()))
    monkeypatch.setattr(runner, "new_session", lambda: ctx)
    monkeypatch.setattr(runner, "get_handler", lambda name: registry.get_handler(name))
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(task_max_tries=3, task_retry_base_seconds=2.0),
    )
    return ctx.session


def test_execute_success_sets_terminal_fields(session: FakeSession) -> None:
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "succeeded"
    assert outcome.retry_in is None
    task = session.task
    assert task.status == "succeeded"
    assert task.attempts == 1
    assert task.started_at is not None
    assert task.finished_at is not None
    assert task.result == {"slept": 0}


def test_execute_terminal_task_skips_handler(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.task.status = "succeeded"
    called: list[int] = []
    monkeypatch.setattr(runner, "get_handler", lambda name: called.append(1) or None)
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "succeeded"
    assert called == []


def test_execute_missing_task_returns_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeSessionCtx(FakeSession(None))
    monkeypatch.setattr(runner, "new_session", lambda: ctx)
    assert runner.execute_task(99, 1).status == "missing"


def test_execute_unknown_name_fails(session: FakeSession) -> None:
    session.task.name = "no.such.task"
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "failed"
    assert "未知任务类型" in session.task.error


def test_execute_first_failure_returns_to_pending_with_delay(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("第一次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    outcome = runner.execute_task(5, 1)
    assert outcome.status == "pending"
    assert outcome.retry_in == 2.0
    assert session.task.attempts == 1
    assert "第 1 次失败" in session.task.error
    assert session.task.finished_at is None


def test_execute_second_failure_doubles_delay(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("第二次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    assert runner.execute_task(5, 2).retry_in == 4.0


def test_execute_last_attempt_marks_failed(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session_, payload):  # noqa: ANN001
        raise RuntimeError("最后一次炸")

    monkeypatch.setattr(runner, "get_handler", lambda name: boom)
    outcome = runner.execute_task(5, 3)
    assert outcome.status == "failed"
    assert outcome.retry_in is None
    assert session.task.status == "failed"
    assert session.task.attempts == 3
    assert session.task.finished_at is not None
    assert "第 3 次失败" in session.task.error


def test_execute_success_clears_previous_error(session: FakeSession) -> None:
    session.task.error = "上次失败"
    runner.execute_task(5, 1)
    assert session.task.error is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_runner.py -q`
Expected: FAIL，`ModuleNotFoundError: app.tasks.runner`

- [ ] **Step 3: 实现执行器**

`backend/app/tasks/runner.py`：

```python
"""任务执行器（S2-7，同步）：状态机 + 重试决策。

放在 worker 之外，是为了不装 ARQ 也能单测状态流转；
worker.py 只负责把结果翻译成 ARQ 的 Retry。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import new_session
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.tasks.registry import TaskHandler, get_handler

logger = logging.getLogger(__name__)

_TERMINAL = {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value}


@dataclass(slots=True)
class TaskOutcome:
    status: str
    retry_in: float | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def execute_task(task_id: int, job_try: int) -> TaskOutcome:
    """执行一次任务尝试；返回状态与（可选）重试延迟秒数。"""
    with new_session() as session:
        task = session.get(AsyncTask, task_id)
        if task is None:
            logger.warning("task_missing", extra={"task_id": task_id})
            return TaskOutcome(status="missing")
        if task.status in _TERMINAL:
            return TaskOutcome(status=task.status)

        handler = get_handler(task.name)
        if handler is None:
            return _fail(session, task, f"未知任务类型：{task.name}")

        task.status = TaskStatus.RUNNING.value
        task.attempts = job_try
        if task.started_at is None:
            task.started_at = _now()
        session.commit()
        logger.info(
            "task_started",
            extra={"task_id": task.id, "task_name": task.name, "attempts": job_try},
        )

        try:
            result = handler(session, task.payload or {})
        except Exception as exc:
            # 处理函数可能改了一半数据：回滚后再写失败状态
            session.rollback()
            task = session.get(AsyncTask, task_id)
            if task is None:
                return TaskOutcome(status="missing")
            settings = get_settings()
            message = f"第 {job_try} 次失败：{exc}"
            if job_try < settings.task_max_tries:
                task.status = TaskStatus.PENDING.value
                task.error = message
                session.commit()
                delay = settings.task_retry_base_seconds * 2 ** (job_try - 1)
                logger.warning(
                    "task_retry",
                    extra={
                        "task_id": task.id,
                        "task_name": task.name,
                        "attempts": job_try,
                        "delay": delay,
                    },
                )
                return TaskOutcome(status=TaskStatus.PENDING.value, retry_in=delay)
            return _fail(session, task, message)

        task.status = TaskStatus.SUCCEEDED.value
        task.result = result
        task.error = None
        task.finished_at = _now()
        session.commit()
        logger.info(
            "task_succeeded",
            extra={"task_id": task.id, "task_name": task.name, "attempts": job_try},
        )
        return TaskOutcome(status=TaskStatus.SUCCEEDED.value)


def _fail(session: Session, task: AsyncTask, message: str) -> TaskOutcome:
    task.status = TaskStatus.FAILED.value
    task.error = message
    task.finished_at = _now()
    session.commit()
    logger.error(
        "task_failed",
        extra={"task_id": task.id, "task_name": task.name, "error": message},
    )
    return TaskOutcome(status=TaskStatus.FAILED.value)
```

- [ ] **Step 4: 运行执行器测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_task_runner.py -q`
Expected: `8 passed`

- [ ] **Step 5: Worker 入口**

`backend/app/tasks/worker.py`：

```python
"""ARQ Worker 入口（S2-7）。

启动（backend/ 目录下）：
    ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings

同步处理函数在线程池里跑，避免阻塞 Worker 的事件循环。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from arq import Retry
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.tasks.runner import execute_task

logger = logging.getLogger(__name__)


async def _on_startup(ctx: dict[str, Any]) -> None:
    setup_logging(get_settings().log_level)


async def run_task(ctx: dict[str, Any], task_id: int) -> str:
    job_try = int(ctx.get("job_try", 1))
    outcome = await asyncio.to_thread(execute_task, task_id, job_try)
    if outcome.retry_in is not None:
        raise Retry(defer=outcome.retry_in)
    return outcome.status


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [run_task]
    redis_settings = _redis_settings()
    on_startup = _on_startup
    max_tries = get_settings().task_max_tries
    job_timeout = get_settings().task_job_timeout_seconds
    keep_result = get_settings().task_result_keep_seconds
    health_check_interval = 30
```

- [ ] **Step 6: Worker 可导入验证**

Run: `cd backend && ../.venv/Scripts/python.exe -c "from app.tasks.worker import WorkerSettings; print(WorkerSettings.functions, WorkerSettings.max_tries, WorkerSettings.job_timeout)"`
Expected: `[<function run_task at ...>] 3 300`

- [ ] **Step 7: 提交**

```bash
git add backend/app/tasks/runner.py backend/app/tasks/worker.py backend/tests/test_task_runner.py
git commit -m "feat(s2-7): 任务执行器与 ARQ Worker 入口"
```

---

### Task 5: 接口与全量回归

**Files:**
- Create: `backend/app/schemas/tasks.py`
- Create: `backend/app/api/v1/tasks.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_tasks_api.py`

**Interfaces:**
- Consumes: `task_service.submit_demo/get_task`、`get_task_queue()`、`require_role("student")`、`get_current_user`
- Produces: `POST /api/v1/tasks/demo`（202）、`GET /api/v1/tasks/{task_id}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_tasks_api.py`：

```python
"""S2-7 任务接口：TestClient + 依赖覆盖，不连库不连 Redis。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.async_task import AsyncTask
from app.models.user import User
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user
        self.rows: dict[int, AsyncTask] = {}
        self.added: list[AsyncTask] = []

    def scalar(self, statement: object):
        return self.user

    def get(self, entity: type, pk: int):
        return self.rows.get(pk) if entity is AsyncTask else None

    def add(self, instance: AsyncTask) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        for row in self.added:
            if row.id is None:
                row.id = 31
            row.created_at = datetime.now(timezone.utc)
            self.rows[row.id] = row

    def rollback(self) -> None:
        pass

    def refresh(self, instance: AsyncTask) -> None:
        if instance.id is None:
            instance.id = 31
        if instance.created_at is None:
            instance.created_at = datetime.now(timezone.utc)


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))


def _user(user_id: int = 1, *, role: str = "student") -> User:
    user = User(
        username=f"student_{user_id}",
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    return user


def _task(*, owner_id: int = 1, status: str = "running") -> AsyncTask:
    task = AsyncTask(
        user_id=owner_id,
        name="demo.sleep",
        status=status,
        payload={"seconds": 5, "fail": False},
        attempts=1,
    )
    task.id = 31
    task.created_at = datetime.now(timezone.utc)
    task.started_at = datetime.now(timezone.utc)
    return task


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession, queue: FakeQueue | None = None) -> FakeQueue:
    fake_queue = queue or FakeQueue()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: fake_queue
    return fake_queue


def test_submit_demo_returns_202_pending(client: TestClient) -> None:
    user = _user()
    queue = _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/tasks/demo", json={"seconds": 5}, headers=_headers(user)
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["status"] == "pending"
    assert resp.json()["data"]["name"] == "demo.sleep"
    assert queue.calls == [("demo.sleep", 31)]


def test_get_task_returns_detail(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user)
    session.rows[31] = _task()
    _wire(session)
    resp = client.get("/api/v1/tasks/31", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "running"
    assert data["attempts"] == 1
    assert data["payload"] == {"seconds": 5, "fail": False}


def test_get_other_task_returns_403(client: TestClient) -> None:
    user = _user(2)
    session = FakeSession(user=user)
    session.rows[31] = _task(owner_id=1)
    _wire(session)
    resp = client.get("/api/v1/tasks/31", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_missing_task_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.get("/api/v1/tasks/99", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_submit_requires_token(client: TestClient) -> None:
    _wire(FakeSession())
    resp = client.post("/api/v1/tasks/demo", json={"seconds": 5})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_submit_forbidden_for_teacher(client: TestClient) -> None:
    user = _user(role="teacher")
    _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/tasks/demo", json={"seconds": 5}, headers=_headers(user)
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_submit_invalid_seconds_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/tasks/demo", json={"seconds": 0}, headers=_headers(user)
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tasks_api.py -q`
Expected: FAIL（404/405，路由未注册）

- [ ] **Step 3: 出入参模型**

`backend/app/schemas/tasks.py`：

```python
"""S2-7 异步任务出入参。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DemoTaskIn(BaseModel):
    seconds: int = Field(default=5, ge=1, le=10)
    fail: bool = False


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    created_at: datetime


class TaskDetailOut(TaskOut):
    attempts: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
```

- [ ] **Step 4: 路由**

`backend/app/api/v1/tasks.py`：

```python
"""S2-7 异步任务接口：提交 demo 任务 + 轮询状态。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.tasks import DemoTaskIn, TaskDetailOut, TaskOut
from app.services import task_service
from app.tasks.queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/demo",
    status_code=202,
    response_model=Envelope[TaskOut],
    summary="提交演示任务（验收用）",
)
def submit_demo(
    payload: DemoTaskIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    task = task_service.submit_demo(
        session,
        owner=current_user,
        seconds=payload.seconds,
        fail=payload.fail,
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get(
    "/{task_id}",
    response_model=Envelope[TaskDetailOut],
    summary="查询任务状态",
)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[TaskDetailOut]:
    task = task_service.get_task(session, task_id=task_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=TaskDetailOut.model_validate(task))
```

`backend/app/api/router.py` 改为：

```python
from app.api.v1 import auth, files, notes, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(notes.router)
api_router.include_router(files.router)
api_router.include_router(tasks.router)
```

- [ ] **Step 5: 运行接口测试与全量**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_tasks_api.py -q`
Expected: `7 passed`

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `401 passed, 1 warning`（368 + 33）

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/tasks.py backend/app/api/v1/tasks.py backend/app/api/router.py backend/tests/test_tasks_api.py
git commit -m "feat(s2-7): 任务提交与状态查询接口"
```

---

### Task 6: 真实 Redis + Worker + Postgres 验收

**Files:** 无代码改动；产出验收证据（贴进最终回复与 plan 执行记录）

**Interfaces:**
- Consumes: Task 1–5 全部产物
- Produces: 真实运行证据（状态时序、重试次数、越权）

- [ ] **Step 1: 起服务**

```bash
# 终端 A（backend/）
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
# 终端 B（backend/），后台任务
cd backend && ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
```

Expected：Worker 打印 `Starting worker for 1 functions: run_task`，无 `TimeoutError`（若报错先检查 `REDIS_URL` 是否为 `127.0.0.1`）

- [ ] **Step 2: 注册/登录 student**

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"task_a","password":"test-pass-123","nickname":"任务A","role":"student"}'
TOKEN_A=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"task_a","password":"test-pass-123"}' | ./.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
```

- [ ] **Step 3: 成功任务（睡 5 秒）**

```bash
curl -s -w '\nHTTP=%{http_code}\n' -X POST localhost:8000/api/v1/tasks/demo \
  -H "Authorization: Bearer $TOKEN_A" -H 'Content-Type: application/json' -d '{"seconds":5}'
curl -s localhost:8000/api/v1/tasks/1 -H "Authorization: Bearer $TOKEN_A"
```

Expected：POST `HTTP=202`、`status=pending`；紧接 GET 可能 `pending` 或 `running`；1–2s 后再 GET 应 `running`（`attempts=1`、`started_at` 非空）

- [ ] **Step 4: 轮询到成功**

```bash
for i in 1 2 3 4 5 6 7 8; do curl -s localhost:8000/api/v1/tasks/1 -H "Authorization: Bearer $TOKEN_A"; echo; sleep 1; done
```

Expected：某次出现 `"status":"succeeded"`、`"result":{"slept":5}`、`finished_at` 非空

- [ ] **Step 5: 失败任务与重试**

```bash
curl -s -X POST localhost:8000/api/v1/tasks/demo -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' -d '{"seconds":1,"fail":true}'
# 每 2 秒查一次，约 10 秒后收敛
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select id, status, attempts, error, started_at, finished_at from async_tasks order by id;"
```

Expected：`attempts=3`、`status=failed`、`error` 含「第 3 次失败」；`started_at` 只写一次

- [ ] **Step 6: 越权**

```bash
# 注册 task_b 并登录，然后
curl -s -w '\nHTTP=%{http_code}\n' localhost:8000/api/v1/tasks/1 -H "Authorization: Bearer $TOKEN_B"
```

Expected：`HTTP=403` + `40300`「无权访问该任务」

- [ ] **Step 7: Worker 日志核对**

Expected：`task_started` / `task_retry` / `task_failed` / `task_succeeded` 各出现，日志只有 id/name/attempts，无 payload 正文

- [ ] **Step 8: 清理**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "delete from async_tasks; delete from users where username like 'task\_%';"
# 停掉 uvicorn 与 arq 后台任务
```

- [ ] **Step 9: 全量 pytest**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `401 passed, 1 warning`

---

### Task 7: 文档同步与提交

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/SCHEMA.md`
- Modify: `AGENTS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/PROGRESS.md`
- Modify: `README.md`
- Modify: `docs/spec/s2-7-task-framework.md`（状态行）
- Modify: `docs/plan/s2-7-task-framework.md`（执行记录）

**Interfaces:** 无代码接口变化

- [ ] **Step 1: API.md**

- §0 第 25 行 TODO 替换为轮询约定：提交返回 `202` + 任务 `id`；客户端每 1–2s `GET /api/v1/tasks/{id}`，`status ∈ {succeeded, failed}` 停止；不在本卡提供 SSE。
- 在 §2.5 新增「异步任务」：`POST /api/v1/tasks/demo`（student，202，`seconds` 1–10 / `fail`）、`GET /api/v1/tasks/{id}`（仅创建者，404/403，字段列表）。
- §12 增加缺口行：任务取消/重跑/列表、Worker 心跳回收 running、SSE 推送（S3-5）。

- [ ] **Step 2: SCHEMA.md**

- 新增 `async_tasks` 表段（字段同 spec §4、CHECK、两个索引、`attempts` 语义）。
- §10 枚举补 `async_tasks.status`：`pending/running/succeeded/failed`（S2-7 定稿）。

- [ ] **Step 3: AGENTS.md**

- §9.2 后端追加：异步任务必须经 `task_service.create_task`（先落库再入队）；处理函数不 commit；重试由 runner 决策；Worker 用 `127.0.0.1` 的 Redis。
- §9.6 追加锚点：`backend/app/tasks/{registry,runner,queue,worker}.py + services/task_service.py`。
- §3 目录说明不变（`tasks/` 已在）。

- [ ] **Step 4: DECISIONS.md**

新增 D-027（ARQ、DB 状态表、3 次/指数退避、demo 端点、owner-only、入队失败落 failed、同步 handler 线程池、`127.0.0.1` 的 Windows 原因、结果保留策略），含实测证据与限制。

- [ ] **Step 5: PROGRESS.md**

状态行改 S2-7 完成、下一步 S2-8；勾选 S2-7；遗留表新增（running 心跳回收、无取消/列表、demo 端口、ARQ 单队列）；追加 2026-10-26 S2-7 日志（拍板、验收证据、偏差、文档同步）。

- [ ] **Step 6: README.md**

「日常启动」的 ② 后补 ③：

```powershell
# ③ 异步 Worker（S2-7 起；不启动则任务一直 pending）
cd E:\BiShe-AIStudy\study-agent\backend
arq app.tasks.worker.WorkerSettings
```

- [ ] **Step 7: spec/plan 状态与执行记录**

- spec 状态行改「已实现并验收（日期；pytest 398/398 + 真实 Worker 证据）」。
- plan 写执行记录：版本、commit 列表、pytest 数字、状态时序实测、重试实测、偏差。

- [ ] **Step 8: 文档提交**

```bash
git add docs/ AGENTS.md README.md
git commit -m "docs(s2-7): 异步任务契约、决策与进度同步"
```

---

## Self-Review

- 覆盖 spec：提交入口（Task 3/5）、状态机与重试（Task 4）、DB 表与迁移（Task 1）、轮询接口（Task 5）、demo 任务（Task 2）、Worker 命令（Task 4 + README Task 7）、配置/异常（Task 1）、文档（Task 7）、真实验收（Task 6）。
- 无占位符：每个新建文件都给了完整代码；测试给出了完整断言。
- 类型一致性：`TaskOutcome.retry_in`、`execute_task(task_id, job_try)`、`enqueue(name, task_id)`、`submit_demo(..., seconds, fail, queue)` 在 Task 3/4/5 之间一致。
- 已知取舍：`create_task` 的 `queue` 为位置外的关键字参数，测试注入假队列；Worker 的 `max_tries` 只来自 `WorkerSettings`，不在 enqueue 里传（ARQ 0.28 限制）。
## 执行记录

**安装版本**：`arq==0.28.0`、`redis==5.3.1`（华为云镜像；arq 依赖解析出的 redis 版本）。实测 ARQ 0.28 的 `enqueue_job` 不接受 `_max_tries`/`_job_timeout`，重试与超时只配 `WorkerSettings`。

**提交列表**

1. `0cc4dbe feat(s2-7): 异步任务表与队列配置`
2. `8986838 feat(s2-7): 任务注册表、演示任务与 ARQ 队列适配器`
3. `29e83d0 feat(s2-7): 任务提交与查询服务`
4. `bbea232 feat(s2-7): 任务执行器与 ARQ Worker 入口`
5. `1a5c3db fix(s2-7): Worker 启动时配置结构化日志`
6. `595562c feat(s2-7): 任务提交与状态查询接口`
7. `docs(s2-7): 异步任务契约、决策与进度同步`

**pytest**：注册表+队列 `10 passed`；服务 `8 passed`；执行器 `8 passed`；接口 `7 passed`；全量 **401 passed, 1 warning**（368 + 33）。

**真实 Redis + Worker + Postgres 验收（实测输出）**

| 步骤 | 实测 |
|---|---|
| 迁移 | `Running upgrade 0003_s2_5 -> 0004_s2_7`；`alembic check` → `No new upgrade operations detected.` |
| 表结构 | `async_tasks` 12 列、`ck_async_tasks_status`、`fk_async_tasks_user_id`、`ix_async_tasks_status`、`ix_async_tasks_user_id_created_at` 全部就位 |
| Worker 启动 | `Starting worker for 1 functions: run_task`、`redis_version=7.4.11`（Windows 无信号处理问题） |
| 提交（5s） | `HTTP=202`、`id=1`、`status=pending`、`attempts=0` |
| 轮询 | 立即 GET → `pending`（attempts=0）；+1s → `running`（attempts=1、started_at 14:56:32.418）；约 5s 后 → `succeeded`（`result={"slept":5}`、finished_at 14:56:37.426） |
| 失败重试 | `fail=true` → `attempts=3`、`status=failed`、error=「第 3 次失败：演示任务按请求失败」；ARQ 日志「retrying job in 2.00s」「retrying job in 4.00s」；started_at 只写一次（14:56:52.044），finished_at 14:57:01.222 |
| 越权 | B 查 A 的 task 1 → `HTTP=403`、`40300「无权访问该任务」` |
| 日志 | 首轮 INFO 被根 logger WARNING 吞掉；加 `on_startup=setup_logging` 后出现 JSON：`task_started`（task_id=3、task_name=demo.sleep、attempts=1）、`task_succeeded`；失败路径 `task_retry`/`task_failed` 只含 id/name/attempts，无 payload 正文 |
| 清理 | `async_tasks=0`、`users=0` |

**与 plan 的偏差**

1. 新增 `backend/app/tasks/__init__.py`：注册表靠 import 副作用填充，只 import `runner` 时不会加载 `demo`，`demo.sleep` 会被判「未知任务类型」；包初始化显式 `import demo` 解决。已回填 Task 2 文件清单。
2. `runner` 日志 `extra={"name": ...}` 与 `LogRecord.name` 冲突抛 `KeyError`，全部改 `task_name`（代码块已回填）。
3. Worker 没配日志时根 logger 是 WARNING，`task_started`/`task_succeeded` 不出现；补 `on_startup` 调 `setup_logging`（追加 `fix(s2-7)` 提交，代码块已回填）。
4. `REDIS_URL` 从 `localhost` 改 `127.0.0.1`：ARQ 实测 `TimeoutError`（Windows IPv6 优先，Docker 只发 IPv4），默认值/`.env.example`/本地 `.env` 三处同步。
5. `WorkerSettings.max_tries/job_timeout` 只能放 Settings（ARQ 0.28 契约），plan 里已按此实现。

**遗留**：见 D-027 与 PROGRESS 遗留 18–21。
