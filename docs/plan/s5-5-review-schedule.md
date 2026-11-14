# S5-5 复习调度 + 每日清单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `review_items` 表、按 S4-7 掌握度生成每日复习清单的 service、5 个学生接口、独立 APScheduler 进程，并用连续 7 天模拟验收清单随掌握度合理变化。

**Architecture:** 一 kp 一条待办行（`UNIQUE(user_id,kp_id)`）；service 先算候选/优先级，再在 35 分钟上限内装填，装不下的顺延到次日；API 只做参数校验/Envelope/提交事务；调度器是独立进程，用 PG advisory lock 防多实例重复，逐用户 refresh + commit。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、PostgreSQL 16、APScheduler 3.11.3、pytest。

**Spec:** `docs/spec/s5-5-review-schedule.md`

## Global Constraints

- 只做后端；不改前端、不超过 S5-5 范围。
- 时区统一 `Asia/Shanghai`，所有“今天”用本地日界；`now` 一律 aware UTC。
- 每日清单硬上限默认 **35 分钟**（`REVIEW_DAILY_MINUTES`，10–120），弱项不豁免上限。
- `review_items` 一 kp 一行，`UNIQUE(user_id,kp_id)`；不加 `status`，done/skip 都写 `done_at`，later 改 `due_at` 到次日 00:00。
- done/skip **不写掌握度**；掌握度只由真实作答更新。
- 5 个接口全部 `student`，仅本人数据；越权/不存在统一 404/40400。
- 新依赖仅 APScheduler（已批准，`apscheduler==3.11.3`）。
- service 不 commit；API 路由/调度器统一提交。
- 新增/修改的测试必须先红后绿；不删已有测试。
- 文档先改 `SCHEMA.md`/`API.md` 再写代码（AGENTS §9.1）。
- 本轮不生成 `ref_type=note` 的复习项。

---

### Task 1: `review_items` 表、枚举、迁移 `0016_s5_5`

**Files:**
- Create: `backend/app/models/review_item.py`
- Modify: `backend/app/models/enums.py`（末尾加 `ReviewRefType`）
- Modify: `backend/app/models/__init__.py`（导入/`__all__` 加 `ReviewItem`）
- Create: `backend/alembic/versions/0016_s5_5.py`
- Modify: `backend/tests/test_answers_migration.py:61-64`
- Modify: `backend/tests/test_papers_migration.py:61-64`
- Test: `backend/tests/test_review_migration.py`
- Modify: `docs/SCHEMA.md §6.4`

**Interfaces:**
- Consumes: `Base`、`in_check()`、`ReviewRefType`
- Produces: ORM `ReviewItem`，表 `review_items`；迁移 head `0016_s5_5`

- [ ] **Step 1: 写迁移契约测试（先红）**

创建 `backend/tests/test_review_migration.py`：

```python
"""S5-5 review_items 契约：列、CHECK、唯一键、索引、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric

from app.models.review_item import ReviewItem

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_review_item_columns_match_schema():
    assert set(ReviewItem.__table__.columns.keys()) == {
        "id",
        "user_id",
        "kp_id",
        "ref_type",
        "ref_id",
        "due_at",
        "interval_days",
        "priority",
        "done_at",
    }


def test_review_item_constraints_and_unique():
    names = {constraint.name for constraint in ReviewItem.__table__.constraints}
    assert "uq_review_items_user_kp" in names
    assert "ck_review_items_ref_type" in names
    assert "ck_review_items_interval" in names
    assert "ck_review_items_priority" in names


def test_review_item_priority_precision():
    priority = ReviewItem.__table__.columns["priority"].type
    assert isinstance(priority, Numeric)
    assert (priority.precision, priority.scale) == (5, 4)


def test_review_item_foreign_keys_and_indexes():
    targets = {
        name: {fk.target_fullname for fk in column.foreign_keys}
        for name, column in ReviewItem.__table__.columns.items()
        if column.foreign_keys
    }
    assert targets == {
        "user_id": {"users.id"},
        "kp_id": {"knowledge_points.id"},
    }
    indexes = {index.name for index in ReviewItem.__table__.indexes}
    assert indexes == {
        "ix_review_items_user_due",
        "ix_review_items_user_done",
    }


def test_migration_chain_head_is_s5_5():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0016_s5_5"
```

同时把 `test_answers_migration.py` 与 `test_papers_migration.py` 的链头测试改成：

```python
def test_migration_chain_head_is_s5_5():
    ...
    assert script.get_current_head() == "0016_s5_5"
```

- [ ] **Step 2: 跑测试确认红**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_migration.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.models.review_item'`（或 head 断言失败）。

- [ ] **Step 3: 建枚举与 ORM 模型**

在 `backend/app/models/enums.py` 末尾追加：

```python
class ReviewRefType(StrEnum):
    """review_items.ref_type：复习项指向的资源类型（SCHEMA §6.4/§10.11）。"""

    NOTE = "note"
    QUESTION = "question"
    MISTAKE = "mistake"


REVIEW_REF_TYPES: tuple[str, ...] = tuple(item.value for item in ReviewRefType)
```

创建 `backend/app/models/review_item.py`：

```python
"""复习清单项（SCHEMA §6.4，S5-5）。

一 kp 一条待办：唯一键保证刷新幂等；ref_id 是多态引用，故意不建外键，
资源被硬删后仍保留行，由接口给 ref_available=false。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import REVIEW_REF_TYPES, in_check


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_review_items_user_kp"),
        CheckConstraint(in_check("ref_type", REVIEW_REF_TYPES), name="ck_review_items_ref_type"),
        CheckConstraint(
            "interval_days >= 1 AND interval_days <= 30",
            name="ck_review_items_interval",
        ),
        CheckConstraint(
            "priority IS NULL OR (priority >= 0 AND priority <= 1)",
            name="ck_review_items_priority",
        ),
        Index("ix_review_items_user_due", "user_id", "due_at"),
        Index("ix_review_items_user_done", "user_id", "done_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_review_items_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "knowledge_points.id", name="fk_review_items_kp_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

在 `backend/app/models/__init__.py` 加：

```python
from app.models.review_item import ReviewItem
```

并在 `__all__` 末尾加 `"ReviewItem"`。

- [ ] **Step 4: 写迁移 `0016_s5_5`**

创建 `backend/alembic/versions/0016_s5_5.py`：

```python
"""S5-5 复习清单：review_items 表（SCHEMA §6.4）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_s5_5"
down_revision = "0015_s5_4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Numeric(5, 4), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ref_type IN ('note', 'question', 'mistake')",
            name="ck_review_items_ref_type",
        ),
        sa.CheckConstraint(
            "interval_days >= 1 AND interval_days <= 30",
            name="ck_review_items_interval",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR (priority >= 0 AND priority <= 1)",
            name="ck_review_items_priority",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_review_items_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"],
            ["knowledge_points.id"],
            name="fk_review_items_kp_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "kp_id", name="uq_review_items_user_kp"),
    )
    op.create_index("ix_review_items_user_due", "review_items", ["user_id", "due_at"])
    op.create_index("ix_review_items_user_done", "review_items", ["user_id", "done_at"])


def downgrade() -> None:
    op.drop_index("ix_review_items_user_done", table_name="review_items")
    op.drop_index("ix_review_items_user_due", table_name="review_items")
    op.drop_table("review_items")
```

- [ ] **Step 5: 更新 SCHEMA §6.4**

把 `docs/SCHEMA.md` 的 `### 6.4 review_items` 表后补：

```markdown
> S5-5 落地口径：**唯一键 `uq_review_items_user_kp (user_id, kp_id)`**——一 kp 一条待办，刷新幂等；`interval_days` CHECK 1–30；`priority` NUMERIC(5,4) CHECK 0–1；`ref_id` 是多态引用（question/mistake），**故意不加外键**，资源被硬删后保留行并由接口返回 `ref_available=false`；不加 `status`：done/skip 都写 `done_at`，later 只改 `due_at` 到次日 00:00。
```

- [ ] **Step 6: 跑迁移测试与真实迁移**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_migration.py tests/test_answers_migration.py tests/test_papers_migration.py -q
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic current
```

Expected: 全部 passed；`alembic current` 输出 `0016_s5_5 (head)`。

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/review_item.py backend/app/models/enums.py backend/app/models/__init__.py \
  backend/alembic/versions/0016_s5_5.py backend/tests/test_review_migration.py \
  backend/tests/test_answers_migration.py backend/tests/test_papers_migration.py \
  docs/SCHEMA.md
git commit -m "feat(s5-5): review_items 表与迁移 0016"
```

---

### Task 2: 调度纯函数与常量

**Files:**
- Create: `backend/app/services/review_service.py`（本步只放常量/数据类/纯函数）
- Test: `backend/tests/test_review_service.py`

**Interfaces:**
- Consumes: `decayed_mastery`、`review_interval_days`（`app.services.mastery_service`）
- Produces:
  - `local_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, date]`
  - `overdue_days(due_at: datetime, now: datetime) -> float`
  - `overdue_ratio(due_at, now, interval_days) -> float`
  - `review_priority(mastery_t: float, overdue: float, exam_weight: float | None) -> float`
  - `estimated_minutes(ref_type: str, difficulty: int) -> int`
  - `is_candidate(mastery_t: float, due_at: datetime, *, next_start: datetime) -> bool`
  - `select_capped(plans: Sequence[ItemPlan], cap_minutes: int) -> tuple[list[ItemPlan], list[ItemPlan]]`
  - dataclasses `MasterySnapshot`、`RefChoice`、`ItemPlan`、`ReviewRowSnapshot`、`RefDetail`

- [ ] **Step 1: 写纯函数测试（先红）**

创建 `backend/tests/test_review_service.py`，先写以下内容：

```python
"""S5-5 复习调度纯函数：边界、优先级、时长、装填。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import review_service
from app.services.review_service import ItemPlan

TZ = ZoneInfo("Asia/Shanghai")


def _plan(kp_id: int, *, priority: float, mastery_t: float, minutes: int) -> ItemPlan:
    return ItemPlan(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        ref_type="question",
        ref_id=kp_id * 10,
        due_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
        interval_days=2,
        priority=priority,
        estimated_minutes=minutes,
        mastery=mastery_t,
        mastery_t=mastery_t,
        stability=2.0,
        attempts=1,
        overdue_days=0.0,
        low_mastery=mastery_t < 0.4,
    )


def test_local_bounds_uses_local_midnight():
    now = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)  # 北京 08:30
    start, next_start, local_date = review_service.local_bounds(now, TZ)
    assert local_date == date(2026, 11, 14)
    assert start == datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)
    assert next_start == datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)


def test_overdue_days_and_ratio():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    due = now - timedelta(days=2)
    assert review_service.overdue_days(due, now) == pytest.approx(2.0)
    assert review_service.overdue_ratio(due, now, 4) == pytest.approx(0.5)
    assert review_service.overdue_ratio(now + timedelta(days=1), now, 4) == 0.0
    assert review_service.overdue_ratio(due, now, 1) == 1.0


def test_review_priority_formula_and_weight_fallback():
    assert review_service.review_priority(0.0, 1.0, 1.0) == 1.0
    assert review_service.review_priority(1.0, 0.0, 0.5) == 0.1
    assert review_service.review_priority(0.5, 0.0, None) == pytest.approx(0.35)
    assert review_service.review_priority(0.2, 0.7, 1.0) == pytest.approx(0.81)


def test_estimated_minutes_scales_with_difficulty():
    assert review_service.estimated_minutes("question", 3) == 6
    assert review_service.estimated_minutes("mistake", 3) == 7
    assert review_service.estimated_minutes("note", 3) == 6
    assert review_service.estimated_minutes("question", 99) == 8


def test_is_candidate_low_mastery_even_before_due():
    next_start = datetime(2026, 11, 15, tzinfo=timezone.utc)
    due_future = datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert review_service.is_candidate(0.39, due_future, next_start=next_start) is True
    assert review_service.is_candidate(0.4, due_future, next_start=next_start) is False
    assert review_service.is_candidate(0.9, next_start, next_start=next_start) is True


def test_select_capped_takes_priority_order_and_defers_rest():
    plans = [
        _plan(1, priority=0.2, mastery_t=0.8, minutes=6),
        _plan(2, priority=0.9, mastery_t=0.2, minutes=6),
        _plan(3, priority=0.5, mastery_t=0.5, minutes=6),
    ]
    selected, deferred = review_service.select_capped(plans, 12)
    assert [item.kp_id for item in selected] == [2, 3]
    assert [item.kp_id for item in deferred] == [1]
    assert sum(item.estimated_minutes for item in selected) == 12


def test_select_capped_keeps_one_even_if_over_cap():
    plans = [_plan(1, priority=0.9, mastery_t=0.2, minutes=9)]
    selected, deferred = review_service.select_capped(plans, 5)
    assert [item.kp_id for item in selected] == [1]
    assert deferred == []


def test_select_capped_tie_breaks_by_mastery_then_kp_id():
    plans = [
        _plan(2, priority=0.5, mastery_t=0.5, minutes=5),
        _plan(1, priority=0.5, mastery_t=0.5, minutes=5),
    ]
    selected, _ = review_service.select_capped(plans, 35)
    assert [item.kp_id for item in selected] == [1, 2]
```

- [ ] **Step 2: 跑测试确认红**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_service.py -q
```

Expected: `ImportError` / `NameError`，`review_service` 尚未实现。

- [ ] **Step 3: 实现常量、数据类与纯函数**

创建 `backend/app/services/review_service.py`：

```python
"""S5-5 复习调度（spec §4）。

前半部分是纯函数，便于手推与单测；DB 用例在 Task 3 补。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.models.enums import ReviewRefType
from app.services.mastery_service import decayed_mastery, review_interval_days

LOW_MASTERY = 0.4
DEFAULT_CAP_MINUTES = 35
ESTIMATE_BASE_MINUTES: dict[str, int] = {
    ReviewRefType.NOTE.value: 3,
    ReviewRefType.QUESTION.value: 3,
    ReviewRefType.MISTAKE.value: 4,
}
ACTION_DONE = "done"
ACTION_SKIP = "skip"
ACTION_LATER = "later"


@dataclass(frozen=True, slots=True)
class MasterySnapshot:
    kp_id: int
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RefChoice:
    ref_type: str
    ref_id: int
    difficulty: int


@dataclass(frozen=True, slots=True)
class ItemPlan:
    kp_id: int
    kp_name: str
    subject_id: int
    ref_type: str
    ref_id: int
    due_at: datetime
    interval_days: int
    priority: float
    estimated_minutes: int
    mastery: float
    mastery_t: float
    stability: float
    attempts: int
    overdue_days: float
    low_mastery: bool


@dataclass(frozen=True, slots=True)
class RefDetail:
    title: str | None
    available: bool
    difficulty: int


@dataclass(frozen=True, slots=True)
class ReviewRowSnapshot:
    item: object
    kp_name: str
    subject_id: int
    exam_weight: float | None
    mastery: float
    stability: float
    attempts: int
    last_practice_at: datetime | None


def _timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().review_timezone)


def local_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, date]:
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    next_start = start + timedelta(days=1)
    return start.astimezone(timezone.utc), next_start.astimezone(timezone.utc), local.date()


def overdue_days(due_at: datetime, now: datetime) -> float:
    return round(max(0.0, (now - due_at).total_seconds() / 86400.0), 2)


def overdue_ratio(due_at: datetime, now: datetime, interval_days: int) -> float:
    days = max(0.0, (now - due_at).total_seconds() / 86400.0)
    return round(min(1.0, days / max(1, interval_days)), 4)


def review_priority(mastery_t: float, overdue: float, exam_weight: float | None) -> float:
    weight = 0.5 if exam_weight is None else float(exam_weight)
    raw = 0.5 * (1.0 - mastery_t) + 0.3 * overdue + 0.2 * weight
    return round(min(1.0, max(0.0, raw)), 4)


def estimated_minutes(ref_type: str, difficulty: int) -> int:
    safe_difficulty = min(5, max(1, int(difficulty)))
    return ESTIMATE_BASE_MINUTES.get(ref_type, 3) + safe_difficulty


def is_candidate(mastery_t: float, due_at: datetime, *, next_start: datetime) -> bool:
    return mastery_t < LOW_MASTERY or due_at < next_start


def _sort_key(plan: ItemPlan) -> tuple[float, float, int]:
    return (-plan.priority, plan.mastery_t, plan.kp_id)


def select_capped(
    plans: Sequence[ItemPlan], cap_minutes: int
) -> tuple[list[ItemPlan], list[ItemPlan]]:
    selected: list[ItemPlan] = []
    deferred: list[ItemPlan] = []
    total = 0
    for plan in sorted(plans, key=_sort_key):
        if not selected or total + plan.estimated_minutes <= cap_minutes:
            selected.append(plan)
            total += plan.estimated_minutes
        else:
            deferred.append(plan)
    return selected, deferred
```

> `review_interval_days` 在 Task 3 用到；本步 import 不影响纯测试。若 lint 报未使用，放在 Task 3 再加回。

- [ ] **Step 4: 跑纯函数测试**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_service.py -q
```

Expected: 8 passed。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/review_service.py backend/tests/test_review_service.py
git commit -m "feat(s5-5): 复习调度纯函数与装填"
```

---

### Task 3: `review_service` DB 用例与配置

**Files:**
- Modify: `backend/app/services/review_service.py`（追加 DB 用例）
- Modify: `backend/app/core/config.py`（`review_timezone` / `review_daily_minutes`）
- Modify: `.env.example`
- Test: `backend/tests/test_review_service.py`（追加 service 用例）

**Interfaces:**
- Consumes: `ReviewItem`、`Mastery`、`KnowledgePoint`、`Question`、`QuestionKp`、`Mistake`
- Produces:
  - `refresh_user(session, *, user_id, now=None) -> ReviewTodayOut`
  - `get_today(session, *, user_id, now=None) -> ReviewTodayOut`
  - `mark_item(session, *, user_id, item_id, action, now=None) -> ReviewItemOut`
  - 私有 `_load_mastery_snapshots`、`_load_ref_choices`、`_load_items`、`_load_today_snapshots`、`_load_item_snapshot`、`_ref_details`、`_upsert_item`、`_item_out`、`_empty_today`

- [ ] **Step 1: 写 service 测试（先红）**

在 `backend/tests/test_review_service.py` 追加：

```python
from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services.review_service import (
    ItemPlan,
    MasterySnapshot,
    RefChoice,
    ReviewRowSnapshot,
)


class FakeSession:
    def __init__(self, *, scalar=None):
        self.scalar_value = scalar
        self.flushed = 0
        self.upserts = []

    def scalar(self, stmt):
        return self.scalar_value

    def flush(self):
        self.flushed += 1


def _snapshot(kp_id: int = 117, *, mastery=0.2, stability=2.0, last_practice=None, weight=0.8):
    return MasterySnapshot(
        kp_id=kp_id,
        kp_name=f"知识点{kp_id}",
        subject_id=7,
        exam_weight=weight,
        mastery=mastery,
        stability=stability,
        attempts=2,
        last_practice_at=last_practice,
        due_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
    )


def test_refresh_user_creates_plan_and_does_not_commit(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    snapshots = [_snapshot()]
    refs = {117: RefChoice(ref_type="question", ref_id=501, difficulty=3)}
    upserts = []
    session = FakeSession()

    monkeypatch.setattr(review_service, "_load_mastery_snapshots", lambda s, *a, **k: snapshots)
    monkeypatch.setattr(review_service, "_load_ref_choices", lambda s, *a, **k: refs)
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {})
    monkeypatch.setattr(
        review_service,
        "_upsert_item",
        lambda s, **kw: upserts.append(kw),
    )
    monkeypatch.setattr(
        review_service,
        "get_today",
        lambda s, *a, **k: ReviewTodayOut(
            date="2026-11-14",
            timezone="Asia/Shanghai",
            items=[],
            item_count=0,
            total_minutes=0,
            cap_minutes=35,
            truncated_count=None,
        ),
    )

    result = review_service.refresh_user(session, user_id=50, now=now)

    assert result.item_count == 0
    assert len(upserts) == 1
    assert upserts[0]["plan"].kp_id == 117
    assert upserts[0]["clear_done"] is False
    assert session.flushed == 1


def test_refresh_user_skips_item_done_today(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    done_today = SimpleNamespace(done_at=datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc))
    session = FakeSession()
    monkeypatch.setattr(
        review_service, "_load_mastery_snapshots", lambda s, uid: [_snapshot()]
    )
    monkeypatch.setattr(
        review_service,
        "_load_ref_choices",
        lambda s, *a, **k: {117: RefChoice("question", 501, 3)},
    )
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {117: done_today})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: None)
    monkeypatch.setattr(
        review_service,
        "get_today",
        lambda s, *a, **k: ReviewTodayOut(
            date="2026-11-14",
            timezone="Asia/Shanghai",
            items=[],
            item_count=0,
            total_minutes=0,
            cap_minutes=35,
            truncated_count=None,
        ),
    )

    review_service.refresh_user(session, user_id=50, now=now)

    assert session.upserts == []


def test_refresh_user_reactivates_done_yesterday(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    old = SimpleNamespace(done_at=datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc))
    upserts = []
    session = FakeSession()
    monkeypatch.setattr(
        review_service, "_load_mastery_snapshots", lambda s, uid: [_snapshot()]
    )
    monkeypatch.setattr(
        review_service,
        "_load_ref_choices",
        lambda s, *a, **k: {117: RefChoice("question", 501, 3)},
    )
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {117: old})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: upserts.append(kw))
    monkeypatch.setattr(
        review_service,
        "get_today",
        lambda s, *a, **k: ReviewTodayOut(
            date="2026-11-14",
            timezone="Asia/Shanghai",
            items=[],
            item_count=0,
            total_minutes=0,
            cap_minutes=35,
            truncated_count=None,
        ),
    )

    review_service.refresh_user(session, user_id=50, now=now)

    assert upserts[0]["clear_done"] is True


def test_refresh_user_skips_candidate_without_ref(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    session = FakeSession()
    monkeypatch.setattr(
        review_service, "_load_mastery_snapshots", lambda s, uid: [_snapshot()]
    )
    monkeypatch.setattr(review_service, "_load_ref_choices", lambda s, *a, **k: {})
    monkeypatch.setattr(review_service, "_load_items", lambda s, *a, **k: {})
    monkeypatch.setattr(review_service, "_upsert_item", lambda s, **kw: None)
    monkeypatch.setattr(
        review_service,
        "get_today",
        lambda s, *a, **k: ReviewTodayOut(
            date="2026-11-14",
            timezone="Asia/Shanghai",
            items=[],
            item_count=0,
            total_minutes=0,
            cap_minutes=35,
            truncated_count=None,
        ),
    )

    review_service.refresh_user(session, user_id=50, now=now)

    assert session.flushed == 1


def test_get_today_returns_empty_without_mastery(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(review_service, "_load_today_snapshots", lambda s, *a, **k: [])
    result = review_service.get_today(
        session, user_id=50, now=datetime(2026, 11, 14, tzinfo=timezone.utc)
    )
    assert result.items == []
    assert result.item_count == 0


def test_get_today_builds_item_with_ref_detail(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id=9,
        kp_id=117,
        ref_type="question",
        ref_id=501,
        interval_days=2,
        due_at=now,
        done_at=None,
    )
    snapshot = ReviewRowSnapshot(
        item=item,
        kp_name="函数",
        subject_id=7,
        exam_weight=1.0,
        mastery=0.5,
        stability=2.0,
        attempts=2,
        last_practice_at=None,
    )
    monkeypatch.setattr(
        review_service, "_load_today_snapshots", lambda s, *a, **k: [snapshot]
    )
    monkeypatch.setattr(
        review_service,
        "_ref_details",
        lambda s, *a, **k: {("question", 501): review_service.RefDetail("题干", True, 3)},
    )

    result = review_service.get_today(FakeSession(), user_id=50, now=now)

    assert result.item_count == 1
    assert result.items[0].ref_title == "题干"
    assert result.items[0].priority > 0


def test_mark_item_done_writes_done_at(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id=9,
        user_id=50,
        kp_id=117,
        ref_type="question",
        ref_id=501,
        interval_days=2,
        done_at=None,
        due_at=now,
    )
    session = FakeSession(scalar=item)
    snapshot = ReviewRowSnapshot(
        item=item,
        kp_name="函数",
        subject_id=7,
        exam_weight=1.0,
        mastery=0.2,
        stability=2.0,
        attempts=2,
        last_practice_at=None,
    )
    monkeypatch.setattr(
        review_service, "_load_item_snapshot", lambda s, *a, **k: snapshot
    )
    monkeypatch.setattr(
        review_service,
        "_ref_details",
        lambda s, *a, **k: {("question", 501): review_service.RefDetail("题干", True, 3)},
    )

    result = review_service.mark_item(
        session, user_id=50, item_id=9, action="done", now=now
    )

    assert item.done_at == now
    assert isinstance(result, ReviewItemOut)
    assert session.flushed == 1


def test_mark_item_rejects_completed_and_missing(monkeypatch):
    now = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    completed = SimpleNamespace(id=9, user_id=50, done_at=now, due_at=now)
    monkeypatch.setattr(
        review_service, "_load_item_snapshot", lambda s, *a, **k: None
    )
    with pytest.raises(ConflictError, match="已完成"):
        review_service.mark_item(
            FakeSession(scalar=completed), user_id=50, item_id=9, action="done", now=now
        )
    with pytest.raises(NotFoundError, match="不存在"):
        review_service.mark_item(
            FakeSession(scalar=None), user_id=50, item_id=99, action="done", now=now
        )
```

- [ ] **Step 2: 跑测试确认红**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_service.py -q
```

Expected: `ImportError: cannot import name 'ReviewTodayOut'` / `AttributeError`。

- [ ] **Step 3: 写 schema `schemas/review.py`**

创建 `backend/app/schemas/review.py`：

```python
"""S5-5 复习清单出入参（API.md §9）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReviewItemOut(BaseModel):
    id: int
    kp_id: int
    kp_name: str
    subject_id: int
    ref_type: str
    ref_id: int
    ref_title: str | None = None
    ref_available: bool
    due_at: datetime
    interval_days: int = Field(ge=1, le=30)
    priority: float = Field(ge=0, le=1)
    estimated_minutes: int = Field(ge=1)
    mastery: float = Field(ge=0, le=1)
    mastery_t: float = Field(ge=0, le=1)
    stability: float = Field(gt=0)
    attempts: int = Field(ge=0)
    overdue_days: float = Field(ge=0)
    low_mastery: bool
    done_at: datetime | None = None


class ReviewTodayOut(BaseModel):
    date: str
    timezone: str
    items: list[ReviewItemOut]
    item_count: int = Field(ge=0)
    total_minutes: int = Field(ge=0)
    cap_minutes: int = Field(ge=1)
    truncated_count: int | None = Field(default=None, ge=0)
```

- [ ] **Step 4: 在 service 追加 DB 用例**

在 `backend/app/services/review_service.py` 顶部补齐 imports：

```python
from decimal import Decimal

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.review_item import ReviewItem
from app.schemas.review import ReviewItemOut, ReviewTodayOut
```

追加以下函数（完整实现）：

```python
def _load_mastery_snapshots(session: Session, user_id: int) -> list[MasterySnapshot]:
    rows = session.execute(
        select(
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == Mastery.kp_id)
        .where(Mastery.user_id == user_id)
    ).all()
    return [
        MasterySnapshot(
            kp_id=mastery.kp_id,
            kp_name=name,
            subject_id=subject_id,
            exam_weight=float(exam_weight) if exam_weight is not None else None,
            mastery=float(mastery.mastery),
            stability=float(mastery.stability),
            attempts=mastery.attempts,
            last_practice_at=mastery.last_practice_at,
            due_at=mastery.due_at,
        )
        for mastery, name, subject_id, exam_weight in rows
    ]


def _summary(text_md: str | None) -> str | None:
    if not text_md:
        return None
    collapsed = " ".join(text_md.split())
    return collapsed[:120] or None


def _load_ref_choices(
    session: Session, *, user_id: int, kp_ids: Sequence[int]
) -> dict[int, RefChoice]:
    unique_kp_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_kp_ids:
        return {}
    chosen: dict[int, RefChoice] = {}

    mistake_rows = session.execute(
        select(Mistake.id, QuestionKp.kp_id, Question.difficulty)
        .join(Question, Question.id == Mistake.question_id)
        .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
        .where(
            Mistake.user_id == user_id,
            Mistake.status.in_(["待订正", "已订正"]),
            QuestionKp.kp_id.in_(unique_kp_ids),
        )
        .order_by(
            case((Mistake.status == "待订正", 0), else_=1),
            func.coalesce(Mistake.last_review_at, Mistake.created_at).desc(),
            Mistake.id.desc(),
        )
    ).all()
    for mistake_id, kp_id, difficulty in mistake_rows:
        chosen.setdefault(
            kp_id,
            RefChoice(ReviewRefType.MISTAKE.value, int(mistake_id), int(difficulty or 3)),
        )

    missing = [kp_id for kp_id in unique_kp_ids if kp_id not in chosen]
    if missing:
        question_rows = session.execute(
            select(QuestionKp.kp_id, Question.id, Question.difficulty)
            .join(Question, Question.id == QuestionKp.question_id)
            .where(QuestionKp.kp_id.in_(missing))
            .order_by(
                QuestionKp.kp_id.asc(),
                QuestionKp.weight.desc().nulls_last(),
                Question.difficulty.asc(),
                Question.id.asc(),
            )
        ).all()
        for kp_id, question_id, difficulty in question_rows:
            chosen.setdefault(
                kp_id,
                RefChoice(ReviewRefType.QUESTION.value, int(question_id), int(difficulty or 3)),
            )
    return chosen


def _load_items(session: Session, user_id: int) -> dict[int, ReviewItem]:
    return {
        row.kp_id: row
        for row in session.scalars(
            select(ReviewItem).where(ReviewItem.user_id == user_id)
        )
    }


def _upsert_item(
    session: Session,
    *,
    user_id: int,
    plan: ItemPlan,
    clear_done: bool,
) -> None:
    values = {
        "user_id": user_id,
        "kp_id": plan.kp_id,
        "ref_type": plan.ref_type,
        "ref_id": plan.ref_id,
        "due_at": plan.due_at,
        "interval_days": plan.interval_days,
        "priority": Decimal(str(plan.priority)),
    }
    set_values = {
        "ref_type": plan.ref_type,
        "ref_id": plan.ref_id,
        "due_at": plan.due_at,
        "interval_days": plan.interval_days,
        "priority": Decimal(str(plan.priority)),
    }
    if clear_done:
        values["done_at"] = None
        set_values["done_at"] = None
    stmt = (
        pg_insert(ReviewItem)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["user_id", "kp_id"],
            set_=set_values,
        )
    )
    session.execute(stmt)


def _load_today_snapshots(
    session: Session, *, user_id: int, next_start: datetime
) -> list[ReviewRowSnapshot]:
    rows = session.execute(
        select(
            ReviewItem,
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == ReviewItem.kp_id)
        .outerjoin(
            Mastery,
            and_(Mastery.user_id == ReviewItem.user_id, Mastery.kp_id == ReviewItem.kp_id),
        )
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.done_at.is_(None),
            ReviewItem.due_at < next_start,
        )
    ).all()
    return [
        ReviewRowSnapshot(
            item=item,
            kp_name=name,
            subject_id=subject_id,
            exam_weight=float(exam_weight) if exam_weight is not None else None,
            mastery=float(mastery.mastery) if mastery is not None else 0.0,
            stability=float(mastery.stability) if mastery is not None else 2.0,
            attempts=mastery.attempts if mastery is not None else 0,
            last_practice_at=mastery.last_practice_at if mastery is not None else None,
        )
        for item, mastery, name, subject_id, exam_weight in rows
    ]


def _load_item_snapshot(
    session: Session, *, user_id: int, item_id: int
) -> ReviewRowSnapshot | None:
    row = session.execute(
        select(
            ReviewItem,
            Mastery,
            KnowledgePoint.name,
            KnowledgePoint.subject_id,
            KnowledgePoint.exam_weight,
        )
        .join(KnowledgePoint, KnowledgePoint.id == ReviewItem.kp_id)
        .outerjoin(
            Mastery,
            and_(Mastery.user_id == ReviewItem.user_id, Mastery.kp_id == ReviewItem.kp_id),
        )
        .where(ReviewItem.id == item_id, ReviewItem.user_id == user_id)
    ).first()
    if row is None:
        return None
    item, mastery, name, subject_id, exam_weight = row
    return ReviewRowSnapshot(
        item=item,
        kp_name=name,
        subject_id=subject_id,
        exam_weight=float(exam_weight) if exam_weight is not None else None,
        mastery=float(mastery.mastery) if mastery is not None else 0.0,
        stability=float(mastery.stability) if mastery is not None else 2.0,
        attempts=mastery.attempts if mastery is not None else 0,
        last_practice_at=mastery.last_practice_at if mastery is not None else None,
    )


def _ref_details(
    session: Session, *, user_id: int, rows: Sequence[ReviewRowSnapshot]
) -> dict[tuple[str, int], RefDetail]:
    details: dict[tuple[str, int], RefDetail] = {}
    question_ids = [
        row.item.ref_id for row in rows if row.item.ref_type == ReviewRefType.QUESTION
    ]
    mistake_ids = [
        row.item.ref_id for row in rows if row.item.ref_type == ReviewRefType.MISTAKE
    ]
    if question_ids:
        for question_id, stem_md, difficulty in session.execute(
            select(Question.id, Question.stem_md, Question.difficulty).where(
                Question.id.in_(question_ids)
            )
        ).all():
            details[(ReviewRefType.QUESTION.value, int(question_id))] = RefDetail(
                _summary(stem_md), True, int(difficulty or 3)
            )
    if mistake_ids:
        for mistake_id, stem_md, difficulty in session.execute(
            select(Mistake.id, Question.stem_md, Question.difficulty)
            .join(Question, Question.id == Mistake.question_id)
            .where(Mistake.id.in_(mistake_ids), Mistake.user_id == user_id)
        ).all():
            details[(ReviewRefType.MISTAKE.value, int(mistake_id))] = RefDetail(
                _summary(stem_md), True, int(difficulty or 3)
            )
    for row in rows:
        key = (row.item.ref_type, row.item.ref_id)
        details.setdefault(key, RefDetail(None, False, 3))
    return details


def _item_out(
    row: ReviewRowSnapshot, detail: RefDetail, *, now: datetime
) -> ReviewItemOut:
    days = 0.0
    if row.last_practice_at is not None:
        days = max(0.0, (now - row.last_practice_at).total_seconds() / 86400.0)
    mastery_t = decayed_mastery(row.mastery, row.stability, days=days)
    item = row.item
    overdue = overdue_ratio(item.due_at, now, item.interval_days)
    return ReviewItemOut(
        id=item.id,
        kp_id=item.kp_id,
        kp_name=row.kp_name,
        subject_id=row.subject_id,
        ref_type=item.ref_type,
        ref_id=item.ref_id,
        ref_title=detail.title,
        ref_available=detail.available,
        due_at=item.due_at,
        interval_days=item.interval_days,
        priority=review_priority(mastery_t, overdue, row.exam_weight),
        estimated_minutes=estimated_minutes(item.ref_type, detail.difficulty),
        mastery=round(row.mastery, 3),
        mastery_t=mastery_t,
        stability=round(row.stability, 2),
        attempts=row.attempts,
        overdue_days=overdue_days(item.due_at, now),
        low_mastery=mastery_t < LOW_MASTERY,
        done_at=item.done_at,
    )


def _empty_today(now: datetime, tz: ZoneInfo) -> ReviewTodayOut:
    _, _, local_date = local_bounds(now, tz)
    return ReviewTodayOut(
        date=local_date.isoformat(),
        timezone=str(tz),
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=get_settings().review_daily_minutes,
        truncated_count=None,
    )


def get_today(
    session: Session, *, user_id: int, now: datetime | None = None
) -> ReviewTodayOut:
    moment = now or datetime.now(timezone.utc)
    tz = _timezone()
    _, next_start, local_date = local_bounds(moment, tz)
    rows = _load_today_snapshots(session, user_id=user_id, next_start=next_start)
    details = _ref_details(session, user_id=user_id, rows=rows)
    items = [
        _item_out(row, details[(row.item.ref_type, row.item.ref_id)], now=moment)
        for row in rows
    ]
    items.sort(key=lambda item: (-item.priority, item.mastery_t, item.kp_id))
    return ReviewTodayOut(
        date=local_date.isoformat(),
        timezone=str(tz),
        items=items,
        item_count=len(items),
        total_minutes=sum(item.estimated_minutes for item in items),
        cap_minutes=get_settings().review_daily_minutes,
        truncated_count=None,
    )


def refresh_user(
    session: Session, *, user_id: int, now: datetime | None = None
) -> ReviewTodayOut:
    moment = now or datetime.now(timezone.utc)
    tz = _timezone()
    day_start, next_start, _ = local_bounds(moment, tz)
    snapshots = _load_mastery_snapshots(session, user_id)
    if not snapshots:
        return _empty_today(moment, tz)

    plans: list[ItemPlan] = []
    refs = _load_ref_choices(
        session, user_id=user_id, kp_ids=[snap.kp_id for snap in snapshots]
    )
    for snap in snapshots:
        days = 0.0
        if snap.last_practice_at is not None:
            days = max(0.0, (moment - snap.last_practice_at).total_seconds() / 86400.0)
        mastery_t = decayed_mastery(snap.mastery, snap.stability, days=days)
        due = snap.due_at or moment
        if not is_candidate(mastery_t, due, next_start=next_start):
            continue
        ref = refs.get(snap.kp_id)
        if ref is None:
            continue
        low = mastery_t < LOW_MASTERY
        effective_due = day_start if low and due >= next_start else due
        interval = review_interval_days(snap.stability, mastery_t)
        plans.append(
            ItemPlan(
                kp_id=snap.kp_id,
                kp_name=snap.kp_name,
                subject_id=snap.subject_id,
                ref_type=ref.ref_type,
                ref_id=ref.ref_id,
                due_at=effective_due,
                interval_days=interval,
                priority=review_priority(
                    mastery_t,
                    overdue_ratio(effective_due, moment, interval),
                    snap.exam_weight,
                ),
                estimated_minutes=estimated_minutes(ref.ref_type, ref.difficulty),
                mastery=snap.mastery,
                mastery_t=mastery_t,
                stability=snap.stability,
                attempts=snap.attempts,
                overdue_days=overdue_days(effective_due, moment),
                low_mastery=low,
            )
        )

    existing = _load_items(session, user_id)
    eligible: list[ItemPlan] = []
    for plan in plans:
        row = existing.get(plan.kp_id)
        if row is not None and row.done_at is not None and row.done_at >= day_start:
            continue
        eligible.append(plan)

    selected, deferred = select_capped(eligible, get_settings().review_daily_minutes)
    selected_ids = {plan.kp_id for plan in selected}
    for plan in eligible:
        row = existing.get(plan.kp_id)
        clear_done = bool(row is not None and row.done_at is not None)
        deferred_plan = plan.kp_id not in selected_ids
        if deferred_plan:
            plan = replace(plan, due_at=next_start)
        _upsert_item(session, user_id=user_id, plan=plan, clear_done=clear_done)
    session.flush()
    today = get_today(session, user_id=user_id, now=moment)
    return today.model_copy(update={"truncated_count": len(deferred)})


def mark_item(
    session: Session,
    *,
    user_id: int,
    item_id: int,
    action: str,
    now: datetime | None = None,
) -> ReviewItemOut:
    if action not in {ACTION_DONE, ACTION_SKIP, ACTION_LATER}:
        from app.core.exceptions import InvalidParamError

        raise InvalidParamError("未知复习操作")
    item = session.scalar(
        select(ReviewItem).where(ReviewItem.id == item_id, ReviewItem.user_id == user_id)
    )
    if item is None:
        raise NotFoundError("复习项不存在")
    if item.done_at is not None:
        raise ConflictError("该复习项已完成")
    moment = now or datetime.now(timezone.utc)
    _, next_start, _ = local_bounds(moment, _timezone())
    if action == ACTION_LATER:
        item.due_at = next_start
    else:
        item.done_at = moment
    session.flush()
    snapshot = _load_item_snapshot(session, user_id=user_id, item_id=item_id)
    if snapshot is None:
        raise NotFoundError("复习项不存在")
    detail = _ref_details(session, user_id=user_id, rows=[snapshot])[
        (snapshot.item.ref_type, snapshot.item.ref_id)
    ]
    return _item_out(snapshot, detail, now=moment)
```

`MasterySnapshot` 的 `due_at` 由 `_load_mastery_snapshots` 填 `mastery.due_at`；为空时用 `moment` 兜底。

- [ ] **Step 5: 加配置**

在 `backend/app/core/config.py` 的 PDF 配置后追加：

```python
    # --- 复习调度（S5-5）---
    review_timezone: str = "Asia/Shanghai"
    review_daily_minutes: int = Field(default=35, ge=10, le=120)
```

在 `.env.example` 的 PDF 段后追加：

```bash
# --- S5-5 复习调度 ---
REVIEW_TIMEZONE=Asia/Shanghai
REVIEW_DAILY_MINUTES=35
```

- [ ] **Step 6: 跑 service 测试**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_service.py -q
```

Expected: 纯函数 8 + service 8 全部 passed。

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/review_service.py backend/app/schemas/review.py \
  backend/app/core/config.py .env.example backend/tests/test_review_service.py
git commit -m "feat(s5-5): 复习清单 service 与配置"
```

---

### Task 4: 5 个复习接口 + API.md

**Files:**
- Create: `backend/app/api/v1/review.py`
- Modify: `backend/app/api/router.py`
- Modify: `docs/API.md §9`
- Test: `backend/tests/test_review_api.py`

**Interfaces:**
- Consumes: `review_service.get_today/refresh_user/mark_item`、`require_role("student")`
- Produces: `GET /api/v1/review/today`、`POST /api/v1/review/refresh`、`POST /api/v1/review/items/{id}/done|skip|later`

- [ ] **Step 1: 写 API 测试（先红）**

创建 `backend/tests/test_review_api.py`：

```python
"""S5-5 复习接口：5 个路由、权限、404/409、Envelope。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.main import app
from app.models.user import User
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services import review_service


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _user(role="student") -> User:
    return User(id=50, username="s5_5_test", password_hash="x", role=role, nickname="测试")


def _today() -> ReviewTodayOut:
    return ReviewTodayOut(
        date="2026-11-14",
        timezone="Asia/Shanghai",
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=35,
        truncated_count=None,
    )


def _item() -> ReviewItemOut:
    return ReviewItemOut(
        id=9,
        kp_id=117,
        kp_name="函数",
        subject_id=7,
        ref_type="question",
        ref_id=501,
        ref_title="题干",
        ref_available=True,
        due_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
        interval_days=2,
        priority=0.7,
        estimated_minutes=6,
        mastery=0.2,
        mastery_t=0.2,
        stability=2.0,
        attempts=1,
        overdue_days=0.0,
        low_mastery=True,
        done_at=None,
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_today_envelope(client, monkeypatch):
    monkeypatch.setattr(review_service, "get_today", lambda *a, **k: _today())
    response = client.get("/api/v1/review/today")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["item_count"] == 0


def test_refresh_commits(client, monkeypatch):
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(review_service, "refresh_user", lambda *a, **k: _today())
    response = client.post("/api/v1/review/refresh")
    assert response.status_code == 200
    assert session.commits == 1


def test_done_skip_later_return_item(client, monkeypatch):
    monkeypatch.setattr(review_service, "mark_item", lambda *a, **k: _item())
    for action in ("done", "skip", "later"):
        response = client.post(f"/api/v1/review/items/9/{action}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == 9


def test_actions_map_errors(client, monkeypatch):
    def raise_conflict(*args, **kwargs):
        raise ConflictError("该复习项已完成")

    monkeypatch.setattr(review_service, "mark_item", raise_conflict)
    assert client.post("/api/v1/review/items/9/done").status_code == 409

    def raise_missing(*args, **kwargs):
        raise NotFoundError("复习项不存在")

    monkeypatch.setattr(review_service, "mark_item", raise_missing)
    assert client.post("/api/v1/review/items/9/later").status_code == 404


def test_requires_login(monkeypatch):
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        assert test_client.get("/api/v1/review/today").status_code == 401


def test_forbidden_for_teacher(monkeypatch):
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _user("teacher")
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/review/today")
    assert response.status_code == 403
    app.dependency_overrides.clear()
```

- [ ] **Step 2: 跑测试确认红**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_api.py -q
```

Expected: 404（路由未注册）。

- [ ] **Step 3: 写路由**

创建 `backend/app/api/v1/review.py`：

```python
"""S5-5 复习清单接口（API.md §9）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.review import ReviewItemOut, ReviewTodayOut
from app.services import review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/today", response_model=Envelope[ReviewTodayOut], summary="今日复习清单")
def get_today(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewTodayOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=review_service.get_today(session, user_id=current_user.id),
    )


@router.post("/refresh", response_model=Envelope[ReviewTodayOut], summary="刷新今日清单")
def refresh(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewTodayOut]:
    data = review_service.refresh_user(session, user_id=current_user.id)
    session.commit()
    return Envelope(trace_id=get_trace_id(), data=data)


def _mark(
    item_id: int, action: str, current_user: User, session: Session
) -> Envelope[ReviewItemOut]:
    data = review_service.mark_item(
        session, user_id=current_user.id, item_id=item_id, action=action
    )
    session.commit()
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/items/{item_id}/done", response_model=Envelope[ReviewItemOut], summary="完成复习项")
def done(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "done", current_user, session)


@router.post("/items/{item_id}/skip", response_model=Envelope[ReviewItemOut], summary="跳过复习项")
def skip(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "skip", current_user, session)


@router.post("/items/{item_id}/later", response_model=Envelope[ReviewItemOut], summary="稍后复习")
def later(
    item_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReviewItemOut]:
    return _mark(item_id, "later", current_user, session)
```

在 `backend/app/api/router.py` 的 import 元组加 `review`，并加：

```python
api_router.include_router(review.router)
```

- [ ] **Step 4: 更新 API.md §9**

把 `GET /api/v1/review/today` 的占位段替换为：

```markdown
### GET /api/v1/review/today
- 权限：student
- 类型：同步、只读（不隐式生成；前端进入页面先调 `POST /review/refresh`）
- 出参：

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | date | string | 本地日期 `YYYY-MM-DD` |
  | timezone | string | 生效时区 |
  | items | array | 复习项，按 priority 降序、mastery_t 升序、kp_id 升序 |
  | item_count | int | 项数 |
  | total_minutes | int | 预估总分钟 |
  | cap_minutes | int | 当前上限（默认 35） |
  | truncated_count | int? | GET 恒 null；refresh 返回实际顺延数 |

  `items[]`：`{id,kp_id,kp_name,subject_id,ref_type,ref_id,ref_title,ref_available,due_at,interval_days,priority,estimated_minutes,mastery,mastery_t,stability,attempts,overdue_days,low_mastery,done_at}`。
- 说明：`ref_type` 为 `question` 或 `mistake`；`ref_available=false` 表示资源已被删除。空清单 200。

### POST /api/v1/review/refresh
- 权限：student
- 类型：同步；按当前用户重算并提交
- 出参：同 `GET /review/today`，`truncated_count` 为本次实际顺延到明天的条数
- 行为：幂等；当天已完成（done/skip）的项不重开；无掌握度行返回空清单

### POST /api/v1/review/items/{item_id}/done
### POST /api/v1/review/items/{item_id}/skip
### POST /api/v1/review/items/{item_id}/later
- 权限：student，仅本人
- 类型：同步
- 出参：更新后的 `ReviewItemOut`
- 错误：404/40400「复习项不存在」；409/40900「该复习项已完成」；403/40300 非 student
- 说明：done/skip 只写 `done_at`，不改掌握度；later 只把 `due_at` 顺延到次日 00:00
```

- [ ] **Step 5: 跑 API 测试**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_api.py -q
```

Expected: 6 passed。

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/v1/review.py backend/app/api/router.py backend/tests/test_review_api.py docs/API.md
git commit -m "feat(s5-5): 复习清单 5 个接口"
```

---

### Task 5: 独立调度器、配置与依赖

**Files:**
- Create: `backend/app/scheduler.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_review_scheduler.py`

**Interfaces:**
- Consumes: `review_service.refresh_user`、`get_session_factory`
- Produces: `generate_daily(*, now=None, session_factory=None) -> dict[str,int]`；`main(argv=None)`；`python -m app.scheduler [--once]`

- [ ] **Step 1: 写调度器测试（先红）**

创建 `backend/tests/test_review_scheduler.py`：

```python
"""S5-5 调度器：advisory lock、逐用户提交、单用户失败隔离。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text

from app import scheduler
from app.schemas.review import ReviewTodayOut


class FakeSession:
    def __init__(self, *, locked=True, user_ids=None):
        self.locked = locked
        self.user_ids = user_ids or []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def scalar(self, stmt, params=None):
        self.calls.append(("scalar", str(stmt)))
        return self.locked

    def scalars(self, stmt):
        self.calls.append(("scalars", str(stmt)))
        return list(self.user_ids)

    def execute(self, stmt, params=None):
        self.calls.append(("execute", str(stmt)))
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = FakeSession(locked=True, user_ids=[50, 51])
        self.sessions.append(session)
        return session


def _empty_today() -> ReviewTodayOut:
    return ReviewTodayOut(
        date="2026-11-14",
        timezone="Asia/Shanghai",
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=35,
        truncated_count=None,
    )


def test_generate_daily_skips_when_lock_not_acquired():
    factory = lambda: FakeSession(locked=False, user_ids=[50])
    result = scheduler.generate_daily(session_factory=factory)
    assert result["users"] == 0
    assert result["items"] == 0
    assert result["failed"] == 0


def test_generate_daily_isolates_user_failures(monkeypatch):
    factory = FakeFactory()
    calls = []

    def fake_refresh(session, *, user_id, now=None):
        calls.append(user_id)
        if user_id == 51:
            raise RuntimeError("boom")
        return _empty_today()

    monkeypatch.setattr(scheduler.review_service, "refresh_user", fake_refresh)
    result = scheduler.generate_daily(session_factory=factory)
    assert result == {"users": 2, "items": 0, "failed": 1}
    assert calls == [50, 51]
    assert factory.sessions[2].rollbacks == 1
```

- [ ] **Step 2: 跑测试确认红**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_scheduler.py -q
```

Expected: `ImportError: cannot import name 'scheduler'`。

- [ ] **Step 3: 实现 scheduler**

创建 `backend/app/scheduler.py`：

```python
"""S5-5 复习清单定时生成（独立进程）。

启动：cd backend && python -m app.scheduler
一次：python -m app.scheduler --once
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import setup_logging
from app.models.mastery import Mastery
from app.services import review_service

logger = logging.getLogger(__name__)

LOCK_KEY = 5505


def _try_lock(session) -> bool:
    return bool(session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}))


def _unlock(session) -> None:
    session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})


def generate_daily(*, now: datetime | None = None, session_factory=None) -> dict[str, int]:
    factory = session_factory or get_session_factory()
    users = 0
    items = 0
    failed = 0
    with factory() as lock_session:
        if not _try_lock(lock_session):
            logger.info("review_daily_skipped_locked")
            return {"users": 0, "items": 0, "failed": 0}
        try:
            user_ids = list(
                lock_session.scalars(
                    select(Mastery.user_id).distinct().order_by(Mastery.user_id)
                )
            )
            for user_id in user_ids:
                users += 1
                with factory() as session:
                    try:
                        result = review_service.refresh_user(session, user_id=int(user_id), now=now)
                        session.commit()
                        items += result.item_count
                    except Exception:
                        session.rollback()
                        failed += 1
                        logger.exception("review_daily_user_failed user_id=%s", user_id)
        finally:
            _unlock(lock_session)
            lock_session.commit()
    return {"users": users, "items": items, "failed": failed}


def main(argv: list[str] | None = None) -> None:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(description="S5-5 复习清单调度器")
    parser.add_argument("--once", action="store_true", help="只生成一次后退出")
    args = parser.parse_args(argv)
    if args.once:
        print(json.dumps(generate_daily(), ensure_ascii=False))
        return
    tz = ZoneInfo(get_settings().review_timezone)
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        generate_daily,
        CronTrigger(hour=0, minute=5, timezone=tz),
        id="review_daily",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("review_scheduler_started timezone=%s", tz)
    scheduler.start()


if __name__ == "__main__":
    main()
```

`user_ids` 必须一次查询取全部，不在循环里查库（AGENTS §4）。

- [ ] **Step 4: 加依赖并安装**

在 `backend/requirements.txt` 末尾追加：

```text
# --- S5-5 复习调度（APScheduler；2026-11-14 用户批准）---
apscheduler==3.11.3
```

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pip install apscheduler==3.11.3 -i https://repo.huaweicloud.com/repository/pypi/simple --timeout 30
../.venv/Scripts/python.exe -m pip show apscheduler | head -3
```

Expected: `Version: 3.11.3`。

- [ ] **Step 5: 跑调度器测试与 `--once`**

Run:

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_review_scheduler.py -q
../.venv/Scripts/python.exe -m app.scheduler --once
```

Expected: 2 passed；`--once` 输出 JSON（无 mastery 用户时 `{"users": 0, "items": 0, "failed": 0}` 或真实用户数）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/scheduler.py backend/requirements.txt backend/tests/test_review_scheduler.py
git commit -m "feat(s5-5): APScheduler 每日复习清单调度"
```

---

### Task 6: 7 天模拟真机验收

**Files:**
- Create: `.sdd/s5-5/review_check.py`
- Create: `.sdd/s5-5/acceptance-evidence.md`
- 不改仓库代码（验收脚本在 `.sdd/`，不进 git）

**Interfaces:**
- Consumes: 后端 8000、真实库、`review_service.refresh_user/get_today/mark_item`、`mastery_service.record_attempts`
- Produces: 7 天清单变化证据 + 真实 HTTP 结果

- [ ] **Step 1: 启动后端并建专用账号**

Run（背景作业）：

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

注册并登录取 token：

```bash
mkdir -p E:/BiShe-AIStudy/.sdd/s5-5
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"s5_5_accept_20261114","password":"review-pass-123","nickname":"S5-5验收","role":"student"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"s5_5_accept_20261114","password":"review-pass-123"}' \
  > E:/BiShe-AIStudy/.sdd/s5-5/login.json
```

Expected: `login.json` 的 `data.access_token` 与 `data.user.id` 存在；脚本从该文件读取，不写死账号 id/密码。

- [ ] **Step 2: 写 7 天模拟脚本**

创建 `.sdd/s5-5/review_check.py`，内容如下（完整可执行）：

```python
"""S5-5 连续 7 天模拟：作答 → 刷新 → 完成/稍后 → 断言清单变化。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import mastery_service, review_service

TZ = ZoneInfo("Asia/Shanghai")
OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000/api/v1"
LOGIN = json.loads((OUT / "login.json").read_text(encoding="utf-8"))["data"]
TOKEN = LOGIN["access_token"]
USER_ID = int(LOGIN["user"]["id"])
engine = create_engine(get_settings().database_url)
client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {TOKEN}"})

KP_IDS = [117, 128, 133, 139]
DIFFICULTIES = {117: 2, 128: 3, 133: 4, 139: 3}


def day_at(offset: int) -> datetime:
    """本地 offset 天的 00:00，转 UTC；-6 表示 6 天前。"""
    now = datetime.now(TZ)
    local = datetime.combine(now.date() + timedelta(days=offset), datetime.min.time(), TZ)
    return local.astimezone(timezone.utc)


def main() -> None:
    days: list[dict[str, object]] = []
    for offset in range(-6, 1):
        day = day_at(offset)
        with Session(engine) as db:
            for index, kp_id in enumerate(KP_IDS):
                mastery_service.record_attempts(
                    db,
                    user_id=USER_ID,
                    kp_ids=[kp_id],
                    s=[0.0, 0.5, 1.0][(offset + index) % 3],
                    difficulty=DIFFICULTIES[kp_id],
                    now=day,
                )
            db.commit()

        with Session(engine) as db:
            today = review_service.refresh_user(db, user_id=USER_ID, now=day)
            db.commit()

        assert today.total_minutes <= today.cap_minutes
        record = {
            "day": day.date().isoformat(),
            "item_count": today.item_count,
            "items": [(item.kp_id, item.priority, item.mastery_t) for item in today.items],
            "total_minutes": today.total_minutes,
            "truncated": today.truncated_count,
        }
        days.append(record)

        if today.items:
            first = today.items[0]
            action = "later" if offset % 2 == 0 else "done"
            with Session(engine) as db:
                review_service.mark_item(
                    db, user_id=USER_ID, item_id=first.id, action=action, now=day
                )
                db.commit()
            with Session(engine) as db:
                again = review_service.refresh_user(db, user_id=USER_ID, now=day)
                db.commit()
            assert all(item.id != first.id for item in again.items)

    refreshed = client.post(f"{BASE}/review/refresh")
    refreshed.raise_for_status()
    http_today = refreshed.json()["data"]
    assert http_today["total_minutes"] <= http_today["cap_minutes"]

    got = client.get(f"{BASE}/review/today")
    got.raise_for_status()
    http_get = got.json()["data"]
    assert [item["id"] for item in http_today["items"]] == [
        item["id"] for item in http_get["items"]
    ]

    report = {"user_id": USER_ID, "days": days, "http_today": http_today}
    (OUT / "accept.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 跑 7 天模拟并核对**

Run:

```bash
cd backend
PYTHONPATH=. ../.venv/Scripts/python.exe E:/BiShe-AIStudy/.sdd/s5-5/review_check.py
```

Expected: 7 天都有记录；每天 `total_minutes <= 35`；done/later 后同日 refresh 不返回该项；HTTP refresh 与 GET 顺序一致。

- [ ] **Step 4: 真 HTTP 与 scheduler `--once`**

```bash
cd backend
../.venv/Scripts/python.exe -m app.scheduler --once
TOKEN=$(../.venv/Scripts/python.exe -c "import json; print(json.load(open('E:/BiShe-AIStudy/.sdd/s5-5/login.json'))['data']['access_token'])")
curl -s http://127.0.0.1:8000/api/v1/review/refresh -X POST -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/v1/review/today -H "Authorization: Bearer $TOKEN"
```

用专用 token 依次验证：refresh 幂等、GET 只读、done 重复 409、later 后 `due_at` 为次日 00:00、scheduler 不新增重复行。

- [ ] **Step 5: 写证据**

`.sdd/s5-5/acceptance-evidence.md` 记录：环境、专用账号、7 天表（日期/项数/总分钟/截断/完成或稍后）、真实 HTTP 结果、库内行数与唯一键、异常与修复。数字必须来自 `accept.json`。

### Task 7: 文档同步与全量回归

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`（追加 D-062）
- Modify: `docs/AI协作开发实施计划.md`（S5-5 勾选）
- Modify: `AGENTS.md`（§9.2 条目、§9.6 锚点）
- Modify: `docs/SCHEMA.md` / `docs/API.md`（若 Task 1/4 未完全同步）
- Modify: `.sdd/s5-5/acceptance-evidence.md`

- [ ] **Step 1: 全量回归**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
```

Expected: 后端全绿（S5-4 基线 1373 + 本卡新增）；前端仍 **296 passed / 46 files**，build 退出 0。

- [ ] **Step 2: 更新 PROGRESS**

- 阶段行加 S5-5。
- “最近完成”写 S5-5：表/迁移 `0016_s5_5`、`review_service`、5 接口、scheduler；贴真实测试数。
- 增加「关键口径（S5-5）」：一 kp 一行、35 分钟上限、弱项不豁免、done/skip 不改掌握度、GET 只读、advisory lock。
- 增加「验收（S5-5）」：7 天模拟实际数字、HTTP 结果。
- 待办勾选 `[x] S5-5 ...`，下一步改 S5-6。
- 变更日志加 `### 2026-11-14（S5-5）`。

- [ ] **Step 3: 追加 D-062**

在 `docs/DECISIONS.md` 末尾写 S5-5 决策：一 kp 一行、错题优先回退题目、硬上限 35 分钟、done/skip 不写掌握度、无 status、GET 只读、独立 scheduler + advisory lock、APScheduler 版本、note 未启用、ref 无外键。

- [ ] **Step 4: 更新 AGENTS 与计划**

- `AGENTS.md §9.2` 加「复习调度（S5-5）」条目，写清 `review_service` 唯一入口、35 分钟上限、done/skip 语义、scheduler 锁、GET 只读。
- `AGENTS.md §9.6` 在 PDF 导出样例前加「复习清单样例」。
- `docs/AI协作开发实施计划.md` 的 S5-5 复选框改 `[x]`。

- [ ] **Step 5: 清理与提交**

```bash
git status --short
git add docs/PROGRESS.md docs/DECISIONS.md docs/AI协作开发实施计划.md AGENTS.md docs/SCHEMA.md docs/API.md
git commit -m "docs(s5-5): 复习调度验收记录与口径定稿（D-062）"
```

- [ ] **Step 6: 报告**

汇报：提交列表、测试数、7 天模拟结果、真实 HTTP、已知边界；提醒用户 `git push` 由本人执行。

---

## Self-Review

- **Spec coverage**：§1 目标 → Task 2/3/4/5；§3 数据模型 → Task 1；§4 算法 → Task 2/3；§5 接口 → Task 4；§6 调度 → Task 5；§7 文件 → 各 Task；§8 测试 → 各 Task；§9 验收 → Task 6；§10 边界 → Task 7 文档；§11 文档 → Task 7。
- **Placeholder scan**：无 TBD/TODO；Task 6 的账号 id/token 从 `.sdd/s5-5/login.json` 读取，不写死。
- **Type consistency**：`MasterySnapshot` 含 `due_at`；`ItemPlan`/`ReviewRowSnapshot`/`RefDetail` 字段在 Task 2 定义、Task 3 使用一致；`ReviewTodayOut.truncated_count` GET 为 null、refresh 为 int。
- **Known gap**：无。