# S4-7 掌握度模型 + 更新服务 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把方案 §6.6 的简化掌握度模型落成「纯函数内核 + `mastery` 表 + 两个接口」，并挂到错题复习动作上，最后把 S4-6 图谱配色从错题数换成真实掌握度。

**Architecture:** 公式全部写成无副作用的纯函数（`MasteryState` 不可变 dataclass），DB 层只做「读行 → 纯函数 → 写回」；挂载点在 `mistake_service.record_review`（同事务）；`recompute` 用一次 SQL 取全量错题事件流后按时间回放、覆盖式重建。

**Tech Stack:** Python 3.11 + SQLAlchemy 2.0 + Alembic + Pydantic v2；Vue 3 + TS（只改配色）；Vitest。

**Spec:** `docs/spec/s4-7-mastery.md`

## Global Constraints

- 工作目录：后端命令在 `study-agent/backend` 下执行（解释器 `../.venv/Scripts/python.exe`），前端在 `study-agent/web` 下执行。
- 公式常量一字不改：`K0=0.35`、初始 `S=2.0`、答对 `S×1.8`（上限 60）、答错 `S×0.5`（下限 1）、`s∈{0,0.5,1}`、`interval=clamp(round(S·M_t),1,30)`。
- 精度：`mastery` 3 位小数、`stability` 2 位小数，**入表前就用 `Decimal` 定型**，不要靠 PG 隐式转换。
- 初始 `M=0`，**懒创建**：没有作答事件就没有行；「无行 = 未评估」，前端显示灰色。
- 只有 `s >= 1` 才 `correct_cnt += 1`；`s = 0.5` 时 `S` 不变（方案只定义了答对/答错两条）。
- 一个用例一个事务：`record_attempts` 不 commit（由 `record_review` 统一提交），`recompute_user` 自带 commit。
- 禁止 N+1：回放前一次 SQL 取事件流；重建一次 `DELETE` + 批量 `INSERT`。
- 不新建 `answers` / `review_items`；不引入新依赖；不改历史迁移。
- 每次提交前：后端 `pytest -q`、前端 `npm run test:run -- --pool=threads`；前端改动还要 `npm run build`。
- 提交信息 Conventional Commits 带任务号（`feat(s4-7): ...`）；用户负责 `git push`。

---

### Task 1: 纯函数内核（无表、无 IO）

**Files:**
- Create: `backend/app/services/mastery_service.py`
- Create: `backend/tests/test_mastery.py`

**Interfaces:**
- Produces（后续任务全部依赖这些名字）：
  - `MasteryState(mastery: float, attempts: int, correct_cnt: int, stability: float, last_practice_at: datetime | None, due_at: datetime | None)` —— `@dataclass(frozen=True, slots=True)`
  - `NEW_STATE: MasteryState`
  - `effective_k(difficulty: int) -> float`
  - `next_mastery(mastery: float, s: float, k: float) -> float`
  - `next_stability(stability: float, s: float) -> float`
  - `decayed_mastery(mastery: float, stability: float, *, days: float) -> float`
  - `review_interval_days(stability: float, mastery_t: float) -> int`
  - `next_state(state: MasteryState, *, s: float, difficulty: int, now: datetime) -> MasteryState`
  - 常量：`K0`、`INITIAL_STABILITY`、`STABILITY_GROW`、`STABILITY_SHRINK`、`STABILITY_MAX`、`STABILITY_MIN`、`INTERVAL_MIN_DAYS`、`INTERVAL_MAX_DAYS`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_mastery.py`：

```python
"""S4-7 掌握度公式内核（方案 §6.6）：答对提升、答错下降、遗忘衰减、间隔变长。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.mastery_service import (
    INTERVAL_MAX_DAYS,
    INTERVAL_MIN_DAYS,
    K0,
    NEW_STATE,
    STABILITY_MAX,
    STABILITY_MIN,
    MasteryState,
    decayed_mastery,
    effective_k,
    next_mastery,
    next_stability,
    next_state,
    review_interval_days,
)

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def test_effective_k_divides_by_difficulty() -> None:
    assert K0 == 0.35
    assert effective_k(1) == pytest.approx(0.35)
    assert effective_k(3) == pytest.approx(0.1167, abs=1e-4)
    assert effective_k(5) == pytest.approx(0.07)


def test_effective_k_clamps_out_of_range_difficulty() -> None:
    # questions.difficulty 有 CHECK 1..5，但历史/脏数据不应让公式炸掉
    assert effective_k(0) == pytest.approx(0.35)
    assert effective_k(99) == pytest.approx(0.07)


def test_first_correct_raises_mastery_from_zero() -> None:
    """场景 1：答对提升（d=3 → K_eff=0.35/3）。"""
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    assert state.mastery == pytest.approx(0.117)
    assert state.attempts == 1
    assert state.correct_cnt == 1
    assert state.stability == pytest.approx(3.6)
    assert state.last_practice_at == NOW
    assert state.due_at > NOW


def test_second_correct_raises_again() -> None:
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=1))
    assert state.mastery == pytest.approx(0.220)


def test_wrong_answer_lowers_mastery() -> None:
    """场景 2：答错下降。"""
    state = MasteryState(
        mastery=0.5, attempts=3, correct_cnt=2, stability=5.0,
        last_practice_at=NOW, due_at=NOW,
    )
    after = next_state(state, s=0.0, difficulty=3, now=NOW + timedelta(days=2))
    assert after.mastery == pytest.approx(0.442)
    assert after.stability == pytest.approx(2.5)


def test_mastery_never_goes_negative() -> None:
    state = MasteryState(
        mastery=0.05, attempts=1, correct_cnt=0, stability=2.0,
        last_practice_at=NOW, due_at=NOW,
    )
    assert next_state(state, s=0.0, difficulty=3, now=NOW).mastery == pytest.approx(0.044)
    assert next_mastery(0.0, 0.0, 0.35) == 0.0


def test_mastery_caps_at_one() -> None:
    assert next_mastery(1.0, 1.0, 0.35) == 1.0
    assert next_mastery(0.99, 1.0, 0.35) <= 1.0


def test_decay_after_ten_days() -> None:
    """场景 3：长时间不练衰减。"""
    assert decayed_mastery(0.8, 10.0, days=10.0) == pytest.approx(0.294)
    assert decayed_mastery(0.8, 10.0, days=0.0) == pytest.approx(0.8)
    assert decayed_mastery(0.8, 10.0, days=-5.0) == pytest.approx(0.8)


def test_stability_growth_and_shrink_bounds() -> None:
    assert next_stability(2.0, 1.0) == pytest.approx(3.6)
    assert next_stability(40.0, 1.0) == pytest.approx(STABILITY_MAX)
    assert next_stability(2.0, 0.0) == pytest.approx(1.0)
    assert next_stability(1.2, 0.0) == pytest.approx(STABILITY_MIN)


def test_half_correct_keeps_stability_and_does_not_count() -> None:
    state = MasteryState(
        mastery=0.4, attempts=2, correct_cnt=1, stability=5.0,
        last_practice_at=NOW, due_at=NOW,
    )
    after = next_state(state, s=0.5, difficulty=2, now=NOW)
    assert after.stability == pytest.approx(5.0)
    assert after.correct_cnt == 1
    assert after.mastery == pytest.approx(0.575)


def test_interval_grows_with_repeated_success() -> None:
    """场景 4：连续答对间隔变长。"""
    state = NEW_STATE
    intervals = []
    for day in range(5):
        state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=day))
        intervals.append((state.due_at - state.last_practice_at).days)
    assert state.mastery == pytest.approx(0.462)
    assert state.stability == pytest.approx(37.79)
    assert intervals[0] == 1
    assert intervals[-1] == 17
    assert intervals == sorted(intervals)


def test_review_interval_clamps() -> None:
    assert review_interval_days(2.0, 0.0) == INTERVAL_MIN_DAYS
    assert review_interval_days(60.0, 1.0) == INTERVAL_MAX_DAYS
    assert review_interval_days(37.79, 0.462) == 17
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_mastery.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.mastery_service'`

- [ ] **Step 3: 实现纯函数内核**

创建 `backend/app/services/mastery_service.py`（本步只写公式，DB 部分 Task 3 再补）：

```python
"""S4-7 掌握度模型（方案 §6.6）。

公式定位是「参考 SM-2 / FSRS 的工程化简化」：参数是工程取值，不是拟合结果。
本模块前半部分全是纯函数，便于单测与手推；DB 用例在文件末尾。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

K0 = 0.35
"""单次作答的基础更新幅度；难题带来更小的更新（避免一题定生死）。"""

INITIAL_STABILITY = 2.0
STABILITY_GROW = 1.8
STABILITY_SHRINK = 0.5
STABILITY_MAX = 60.0
STABILITY_MIN = 1.0

INTERVAL_MIN_DAYS = 1
INTERVAL_MAX_DAYS = 30

MASTERY_PRECISION = 3
STABILITY_PRECISION = 2


@dataclass(frozen=True, slots=True)
class MasteryState:
    """掌握度的一次快照；不可变，方便「读 → 算 → 写」而不共享状态。"""

    mastery: float
    attempts: int
    correct_cnt: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


NEW_STATE = MasteryState(
    mastery=0.0,
    attempts=0,
    correct_cnt=0,
    stability=INITIAL_STABILITY,
    last_practice_at=None,
    due_at=None,
)


def effective_k(difficulty: int) -> float:
    """K_eff = K0 / difficulty；难度越界按 1..5 收敛，不让脏数据把公式炸掉。"""
    safe = min(5, max(1, int(difficulty)))
    return K0 / safe


def next_mastery(mastery: float, s: float, k: float) -> float:
    """M ← clamp(M + K_eff·(s − M), 0, 1)。"""
    updated = mastery + k * (s - mastery)
    return round(min(1.0, max(0.0, updated)), MASTERY_PRECISION)


def next_stability(stability: float, s: float) -> float:
    """答对放大间隔、答错缩短；半对（s=0.5）方案没定义，按「不增不减」处理。"""
    if s >= 1.0:
        return round(min(STABILITY_MAX, stability * STABILITY_GROW), STABILITY_PRECISION)
    if s <= 0.0:
        return round(max(STABILITY_MIN, stability * STABILITY_SHRINK), STABILITY_PRECISION)
    return round(stability, STABILITY_PRECISION)


def decayed_mastery(mastery: float, stability: float, *, days: float) -> float:
    """M_t = M·exp(−Δt/S)；未来时间/负间隔按 0 天处理（时钟回拨不该抬高掌握度）。"""
    if days <= 0:
        return round(mastery, MASTERY_PRECISION)
    safe_stability = max(stability, 0.01)
    return round(mastery * math.exp(-days / safe_stability), MASTERY_PRECISION)


def review_interval_days(stability: float, mastery_t: float) -> int:
    """interval = clamp(round(S·M_t), 1, 30) 天。"""
    raw = int(round(stability * mastery_t))
    return max(INTERVAL_MIN_DAYS, min(INTERVAL_MAX_DAYS, raw))


def next_state(
    state: MasteryState, *, s: float, difficulty: int, now: datetime
) -> MasteryState:
    """一次作答后的新状态；刚作答时 Δt=0，到期间隔用当前 M 而不是衰减后的值。"""
    mastery = next_mastery(state.mastery, s, effective_k(difficulty))
    stability = next_stability(state.stability, s)
    due_at = now + timedelta(days=review_interval_days(stability, mastery))
    return MasteryState(
        mastery=mastery,
        attempts=state.attempts + 1,
        correct_cnt=state.correct_cnt + (1 if s >= 1.0 else 0),
        stability=stability,
        last_practice_at=now,
        due_at=due_at,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_mastery.py -q`
Expected: `13 passed`

- [ ] **Step 5: 提交**

```bash
cd study-agent && git add backend/app/services/mastery_service.py backend/tests/test_mastery.py
git commit -m "feat(s4-7): 掌握度公式纯函数内核"
```

---

### Task 2: `mastery` 表 + 迁移 + SCHEMA 口径

**Files:**
- Create: `backend/app/models/mastery.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0013_s4_7.py`
- Modify: `docs/SCHEMA.md`（§6.3 补三处口径备注）

**Interfaces:**
- Produces: `from app.models.mastery import Mastery`；表 `mastery`，列 `id / user_id / kp_id / mastery / attempts / correct_cnt / stability / last_practice_at / due_at / updated_at`；约束 `uq_mastery_user_kp`、`ix_mastery_user_due`
- Consumes: Task 1 无依赖

- [ ] **Step 1: 写模型**

创建 `backend/app/models/mastery.py`：

```python
"""掌握度（SCHEMA §6.3）。

一行 = 一个用户对一个知识点的掌握状态；没有行代表「未评估」，不是 0 掌握。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Mastery(Base):
    __tablename__ = "mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_mastery_user_kp"),
        Index("ix_mastery_user_due", "user_id", "due_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_mastery_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "knowledge_points.id", name="fk_mastery_kp_id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    mastery: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    correct_cnt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    stability: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("2")
    )
    last_practice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

在 `backend/app/models/__init__.py` 里按字母序插入 import 与 `__all__` 项：

```python
from app.models.mastery import Mastery
```

```python
    "Mastery",
```

- [ ] **Step 2: 写迁移**

创建 `backend/alembic/versions/0013_s4_7.py`：

```python
"""S4-7 掌握度：mastery 表（SCHEMA §6.3）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_s4_7"
down_revision = "0012_s4_5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mastery",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("mastery", sa.Numeric(4, 3), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_cnt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stability", sa.Numeric(6, 2), nullable=False, server_default="2"),
        sa.Column("last_practice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_mastery_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"],
            ["knowledge_points.id"],
            name="fk_mastery_kp_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "kp_id", name="uq_mastery_user_kp"),
    )
    op.create_index("ix_mastery_user_due", "mastery", ["user_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_mastery_user_due", table_name="mastery")
    op.drop_table("mastery")
```

- [ ] **Step 3: 真机建表**

Run:

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic heads
```

Expected: `0013_s4_7 (head)`；无报错。

- [ ] **Step 4: 查表结构证明约束都在**

Run:

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -c "
from sqlalchemy import text
from app.core.db import new_session
s = new_session()
print('列:', s.execute(text(\"select column_name, data_type, numeric_precision, numeric_scale, is_nullable from information_schema.columns where table_name='mastery' order by ordinal_position\")).all())
print('约束:', s.execute(text(\"select conname, contype from pg_constraint where conrelid='mastery'::regclass order by conname\")).all())
print('索引:', s.execute(text(\"select indexname from pg_indexes where tablename='mastery' order by 1\")).all())
s.close()"
```

Expected：10 列；`uq_mastery_user_kp`（contype `u`）、`fk_mastery_user_id` / `fk_mastery_kp_id`（`f`）、PK；索引 `ix_mastery_user_due`。

- [ ] **Step 5: SCHEMA.md 补口径**

在 `docs/SCHEMA.md` §6.3 表格后面的两行备注（`> 读取时按时间折算…`）之后追加：

```markdown
> S4-7 补三处此前未定死的口径：① `stability` 精度固定 `NUMERIC(6,2)`（要存到 60.00 且连续 ×1.8）；② `mastery` 初始值 = **0**，首次作答从零学，不引入"基础先验"；③ **懒创建**——没有作答事件就没有行，「无行」对外语义是**未评估**，不是 0 掌握。`mastery` / `stability` 写入前用 `Decimal` 定型到 3 / 2 位，不靠 PG 隐式转换。
```

- [ ] **Step 6: 跑全量测试（确认没碰坏别处）**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `1172 passed, 1 warning`（基线 1159 + Task 1 的 13）

- [ ] **Step 7: 提交**

```bash
cd study-agent && git add backend/app/models/mastery.py backend/app/models/__init__.py backend/alembic/versions/0013_s4_7.py docs/SCHEMA.md
git commit -m "feat(s4-7): mastery 表与迁移 0013"
```

---

### Task 3: 用例 + 挂载点 + 两条接口

**Files:**
- Modify: `backend/app/services/mastery_service.py`（追加 DB 用例）
- Modify: `backend/app/services/mistake_service.py:378-395`（`record_review` 挂载）
- Modify: `backend/app/schemas/kp.py`（追加 3 个模型）
- Create: `backend/app/api/v1/mastery.py`
- Modify: `backend/app/api/router.py`
- Modify: `docs/API.md`（§4.6 新增两条）
- Modify: `backend/tests/test_mastery.py`（追加用例测试）

**Interfaces:**
- Consumes: Task 1 的纯函数；Task 2 的 `Mastery`
- Produces:
  - `record_attempts(session, *, user_id: int, kp_ids: Sequence[int], s: float, difficulty: int, now: datetime | None = None) -> list[Mastery]`（**不 commit**）
  - `recompute_user(session, *, user_id: int, now: datetime | None = None) -> RecomputeResult`（**自带 commit**）
  - `list_mastery(session, *, user_id: int, subject_id: int | None, page: PageParams, sort: SortParams) -> MasteryPage`
  - `RecomputeResult(events_replayed: int, rows_built: int, skipped_no_kp: int)`
  - schema：`MasteryOut` / `MasteryPage` / `MasteryRecomputeOut`
  - HTTP：`POST /api/v1/kp/mastery/recompute`、`GET /api/v1/kp/mastery`

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_mastery.py` 末尾追加：

```python
# --------------------------------------------------------------------------
# DB 用例：全部用 FakeSession（真实 SQL 只验 WHERE，不连库）
# --------------------------------------------------------------------------
from app.models.enums import MistakeStatus  # noqa: E402
from app.models.mastery import Mastery  # noqa: E402
from app.models.mistake import Mistake  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.services import mastery_service  # noqa: E402
from app.utils.pagination import PageParams, SortParams  # noqa: E402


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeMasterySession:
    """按「先 get → 再 scalars 查已有行」的顺序喂结果。"""

    def __init__(
        self,
        *,
        objects: dict | None = None,
        existing: list[Mastery] | None = None,
        rows: list[tuple] | None = None,
        scalar_result: int | None = 0,
    ) -> None:
        self.objects = objects or {}
        self.existing = existing or []
        self.rows = rows or []
        self.scalar_result = scalar_result
        self.added: list[Mastery] = []
        self.commits = 0
        self.statements: list[object] = []
        self._next_id = 700

    def get(self, entity, pk):  # noqa: ANN001, ANN201
        return self.objects.get((entity, pk))

    def scalars(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return iter(self.existing)

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return _Rows(self.rows)

    def scalar(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return self.scalar_result

    def add(self, instance) -> None:  # noqa: ANN001
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def _mastery_row(kp_id: int, *, mastery: float, attempts: int = 1, correct: int = 1) -> Mastery:
    row = Mastery(
        user_id=50,
        kp_id=kp_id,
        mastery=Decimal(str(mastery)),
        attempts=attempts,
        correct_cnt=correct,
        stability=Decimal("3.60"),
        last_practice_at=NOW,
        due_at=NOW + timedelta(days=1),
    )
    row.id = 900 + kp_id
    return row


def test_record_attempts_creates_row_lazily() -> None:
    session = FakeMasterySession()
    rows = mastery_service.record_attempts(
        session, user_id=50, kp_ids=[3], s=1.0, difficulty=3, now=NOW
    )
    assert len(rows) == 1
    assert rows[0].kp_id == 3
    assert float(rows[0].mastery) == pytest.approx(0.117)
    assert rows[0].attempts == 1
    assert rows[0].correct_cnt == 1
    assert session.commits == 0  # 由调用方 commit


def test_record_attempts_updates_existing_row() -> None:
    existing = _mastery_row(3, mastery=0.5)
    session = FakeMasterySession(existing=[existing])
    mastery_service.record_attempts(
        session, user_id=50, kp_ids=[3], s=0.0, difficulty=3, now=NOW
    )
    assert float(existing.mastery) == pytest.approx(0.442)
    assert existing.attempts == 2
    assert existing.correct_cnt == 1
    assert session.added == []


def test_record_attempts_skips_empty_kp_list() -> None:
    session = FakeMasterySession()
    assert mastery_service.record_attempts(
        session, user_id=50, kp_ids=[], s=1.0, difficulty=3, now=NOW
    ) == []


def test_recompute_user_replays_in_time_order() -> None:
    earlier = NOW - timedelta(days=3)
    later = NOW - timedelta(days=1)
    session = FakeMasterySession(
        rows=[
            # 故意乱序：先给晚的、再给早的，验证按 event_at 回放
            (1, MistakeStatus.MASTERED.value, later, 3, 7),
            (2, MistakeStatus.TODO.value, earlier, 3, 7),
        ],
        scalar_result=2,
    )
    result = mastery_service.recompute_user(session, user_id=50, now=NOW)
    assert result.events_replayed == 2
    assert result.rows_built == 1
    assert result.skipped_no_kp == 0
    assert session.commits == 1
    assert len(session.added) == 1
    # 先错(s=0, M 停在 0) 后对(s=1, M=0.117)
    assert float(session.added[0].mastery) == pytest.approx(0.117)
    assert session.added[0].attempts == 2


def test_recompute_user_counts_mistakes_without_kp() -> None:
    session = FakeMasterySession(rows=[], scalar_result=31)
    result = mastery_service.recompute_user(session, user_id=50, now=NOW)
    assert (result.events_replayed, result.rows_built, result.skipped_no_kp) == (0, 0, 31)


def test_recompute_user_is_idempotent() -> None:
    rows = [(1, MistakeStatus.CORRECTED.value, NOW, 3, 7)]
    first = FakeMasterySession(rows=rows, scalar_result=1)
    once = mastery_service.recompute_user(first, user_id=50, now=NOW)
    second = FakeMasterySession(rows=rows, scalar_result=1)
    twice = mastery_service.recompute_user(second, user_id=50, now=NOW)
    assert once == twice
    assert float(first.added[0].mastery) == pytest.approx(float(second.added[0].mastery))


def test_recompute_user_deletes_previous_rows() -> None:
    session = FakeMasterySession(rows=[(1, MistakeStatus.TODO.value, NOW, 2, 7)], scalar_result=1)
    mastery_service.recompute_user(session, user_id=50, now=NOW)
    sql = " ".join(str(stmt) for stmt in session.statements)
    assert "DELETE FROM mastery" in sql
    assert "mastery.user_id" in sql


def test_record_review_updates_mastery_for_question_kps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钩子：复习一次 → 掌握度按该题知识点各更新一次。"""
    from app.services import mistake_service

    mistake = Mistake(
        user_id=50,
        question_id=65,
        status=MistakeStatus.TODO.value,
        correct_streak=0,
        my_answer_md="1",
        correct_answer_md="2",
    )
    mistake.id = 12
    question = Question(
        subject_id=7, stem_md="题干", stem_hash="h" * 64, qtype="解答题", difficulty=3
    )
    question.id = 65
    question.options_json = None

    class _HookSession(FakeMasterySession):
        pass

    session = _HookSession(
        objects={(Mistake, 12): mistake, (Question, 65): question},
        rows=[(3,), (4,)],
    )
    captured: dict[str, object] = {}

    def fake_record(session_, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mastery_service, "record_attempts", fake_record)
    mistake_service.record_review(session, user_id=50, mistake_id=12, correct=True)
    assert captured["kp_ids"] == [3, 4]
    assert captured["s"] == 1.0
    assert captured["difficulty"] == 3
    assert captured["user_id"] == 50


def test_record_review_without_kp_does_not_touch_mastery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mistake_service

    mistake = Mistake(
        user_id=50,
        question_id=65,
        status=MistakeStatus.TODO.value,
        correct_streak=0,
        my_answer_md="1",
        correct_answer_md="2",
    )
    mistake.id = 12
    question = Question(
        subject_id=7, stem_md="题干", stem_hash="h" * 64, qtype="解答题", difficulty=3
    )
    question.id = 65
    question.options_json = None
    session = FakeMasterySession(
        objects={(Mistake, 12): mistake, (Question, 65): question}, rows=[]
    )
    called: list[str] = []
    monkeypatch.setattr(
        mastery_service, "record_attempts", lambda *a, **k: called.append("x")
    )
    mistake_service.record_review(session, user_id=50, mistake_id=12, correct=False)
    assert called == []
```

同时补 `from decimal import Decimal` 到文件顶部 import 区（`datetime` 已 import `timedelta`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_mastery.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.mastery_service' has no attribute 'record_attempts'`，且 `ModuleNotFoundError: app.models.mastery`（若 Task 2 未跑）

- [ ] **Step 3: 实现 DB 用例**

本步先把文件顶部 import 区改成下面这一整块（替换 Task 1 写的那两行 import），再在文件末尾追加下面的 DB 用例。文件顶部最终形态：

```python
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover
    from app.models.mastery import Mastery

    from app.schemas.kp import MasteryPage
    from app.utils.pagination import PageParams, SortParams
```

然后在文件末尾追加：

```python
# --------------------------------------------------------------------------
# DB 用例：读行 → 纯函数 → 写回
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecomputeResult:
    events_replayed: int
    rows_built: int
    skipped_no_kp: int


STATUS_TO_S: dict[str, float] = {
    "待订正": 0.0,
    "已订正": 0.5,
    "已掌握": 1.0,
}
"""回放口径：错题状态折算成一次作答结果（spec §3.2）。"""


def _to_state(row: "Mastery") -> MasteryState:
    return MasteryState(
        mastery=float(row.mastery),
        attempts=row.attempts,
        correct_cnt=row.correct_cnt,
        stability=float(row.stability),
        last_practice_at=row.last_practice_at,
        due_at=row.due_at,
    )


def _apply(row: "Mastery", state: MasteryState) -> None:
    row.mastery = Decimal(str(state.mastery))
    row.attempts = state.attempts
    row.correct_cnt = state.correct_cnt
    row.stability = Decimal(str(state.stability))
    row.last_practice_at = state.last_practice_at
    row.due_at = state.due_at


def record_attempts(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    s: float,
    difficulty: int,
    now: datetime | None = None,
) -> list["Mastery"]:
    """一次作答更新多个知识点；缺行则懒创建。**不 commit**，由调用方统一提交。"""
    from app.models.mastery import Mastery

    unique_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_ids:
        return []
    moment = now or datetime.now(timezone.utc)
    existing = {
        row.kp_id: row
        for row in session.scalars(
            select(Mastery).where(
                Mastery.user_id == user_id, Mastery.kp_id.in_(unique_ids)
            )
        )
    }
    updated: list[Mastery] = []
    for kp_id in unique_ids:
        row = existing.get(kp_id)
        if row is None:
            row = Mastery(
                user_id=user_id,
                kp_id=kp_id,
                mastery=Decimal(str(NEW_STATE.mastery)),
                attempts=0,
                correct_cnt=0,
                stability=Decimal(str(NEW_STATE.stability)),
            )
            session.add(row)
            state = NEW_STATE
        else:
            state = _to_state(row)
        _apply(row, next_state(state, s=s, difficulty=difficulty, now=moment))
        updated.append(row)
    session.flush()
    return updated


def recompute_user(
    session: Session, *, user_id: int, now: datetime | None = None
) -> RecomputeResult:
    """按时间序回放本人错题事件，覆盖式重建掌握度（幂等）。"""
    from app.models.mastery import Mastery
    from app.models.mistake import Mistake
    from app.models.question import Question
    from app.models.question_kp import QuestionKp

    event_at = func.coalesce(Mistake.last_review_at, Mistake.created_at)
    rows = session.execute(
        select(
            Mistake.id,
            Mistake.status,
            event_at.label("event_at"),
            Question.difficulty,
            QuestionKp.kp_id,
        )
        .join(Question, Question.id == Mistake.question_id)
        .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
        .where(Mistake.user_id == user_id)
    ).all()
    total_mistakes = int(
        session.scalar(
            select(func.count()).select_from(Mistake).where(Mistake.user_id == user_id)
        )
        or 0
    )
    states: dict[int, MasteryState] = {}
    ordered = sorted(rows, key=lambda row: (row[2], row[0], row[4]))
    for _mistake_id, status, moment, difficulty, kp_id in ordered:
        state = states.get(kp_id, NEW_STATE)
        states[kp_id] = next_state(
            state,
            s=STATUS_TO_S.get(status, 0.0),
            difficulty=int(difficulty or 3),
            now=moment,
        )
    session.execute(delete(Mastery).where(Mastery.user_id == user_id))
    for kp_id, state in sorted(states.items()):
        row = Mastery(user_id=user_id, kp_id=kp_id, mastery=Decimal("0"), attempts=0, correct_cnt=0, stability=Decimal("2"))
        _apply(row, state)
        session.add(row)
    session.commit()
    replayed_ids = {row[0] for row in ordered}
    return RecomputeResult(
        events_replayed=len(ordered),
        rows_built=len(states),
        skipped_no_kp=max(0, total_mistakes - len(replayed_ids)),
    )


SORTABLE = {
    "mastery": "mastery",
    "due_at": "due_at",
    "attempts": "attempts",
    "kp_id": "kp_id",
}


def list_mastery(
    session: Session,
    *,
    user_id: int,
    subject_id: int | None,
    page: "PageParams",
    sort: "SortParams",
) -> "MasteryPage":
    """本人已评估的掌握度；`mastery_t` 按当前时间折算。"""
    from fastapi_pagination import Params
    from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa

    from app.models.knowledge_point import KnowledgePoint
    from app.models.mastery import Mastery
    from app.schemas.kp import MasteryOut, MasteryPage
    from app.utils.pagination import apply_sort

    columns = {
        "mastery": Mastery.mastery,
        "due_at": Mastery.due_at,
        "attempts": Mastery.attempts,
        "kp_id": Mastery.kp_id,
    }
    stmt = (
        select(Mastery, KnowledgePoint.name, KnowledgePoint.subject_id)
        .join(KnowledgePoint, KnowledgePoint.id == Mastery.kp_id)
        .where(Mastery.user_id == user_id)
    )
    if subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    # 默认「最薄弱优先」，显式传 sort 才用调用方的方向
    stmt = apply_sort(
        stmt,
        sort_by=sort.sort_by or "mastery",
        order=sort.order if sort.sort_by else "asc",
        allowed=columns,
        default_sort="mastery",
    )
    stmt = stmt.order_by(Mastery.kp_id.asc())
    data = paginate_sa(
        session, stmt, params=Params(page=page.page, size=page.page_size)
    )
    now = datetime.now(timezone.utc)
    items: list[MasteryOut] = []
    for row, kp_name, kp_subject_id in data.items:
        days = 0.0
        if row.last_practice_at is not None:
            delta = now - row.last_practice_at
            days = max(0.0, delta.total_seconds() / 86400.0)
        items.append(
            MasteryOut(
                kp_id=row.kp_id,
                kp_name=kp_name,
                subject_id=kp_subject_id,
                mastery=float(row.mastery),
                mastery_t=decayed_mastery(
                    float(row.mastery), float(row.stability), days=days
                ),
                attempts=row.attempts,
                correct_cnt=row.correct_cnt,
                stability=float(row.stability),
                last_practice_at=row.last_practice_at,
                due_at=row.due_at,
            )
        )
    return MasteryPage(
        items=items, total=data.total, page=data.page, page_size=data.size
    )
```

- [ ] **Step 4: 补 schema**

在 `backend/app/schemas/kp.py` 末尾追加：

```python
class MasteryOut(BaseModel):
    """一条掌握度；`mastery` 是库存原值，`mastery_t` 是按当前时间折算的有效值。"""

    kp_id: int
    kp_name: str
    subject_id: int
    mastery: float
    mastery_t: float
    attempts: int
    correct_cnt: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


class MasteryPage(BaseModel):
    items: list[MasteryOut]
    total: int
    page: int
    page_size: int


class MasteryRecomputeOut(BaseModel):
    events_replayed: int
    rows_built: int
    skipped_no_kp: int
```

- [ ] **Step 5: 挂载到 `record_review`**

`backend/app/services/mistake_service.py`：在 `record_review` 里把 `mistake.last_review_at = datetime.now(timezone.utc)` 改成先取一个 `now`，再插钩子。整段改成：

```python
def record_review(
    session: Session, *, user_id: int, mistake_id: int, correct: bool
) -> MistakeDetailOut:
    """复习结果驱动状态机（spec §6.1）：连续答对 MASTERY_STREAK 次算掌握。

    S4-7 起同事务更新掌握度：答对 s=1、答错 s=0，一次复习更新该题挂的全部知识点。
    """
    mistake = _load_owned(session, user_id=user_id, mistake_id=mistake_id)
    now = datetime.now(timezone.utc)
    if correct:
        mistake.correct_streak += 1
        mistake.status = (
            MistakeStatus.MASTERED.value
            if mistake.correct_streak >= MASTERY_STREAK
            else MistakeStatus.CORRECTED.value
        )
    else:
        mistake.correct_streak = 0
        mistake.status = MistakeStatus.TODO.value
    mistake.last_review_at = now
    _update_mastery(session, user_id=user_id, mistake=mistake, correct=correct, now=now)
    _commit(session)
    return _detail(session, mistake=mistake)


def _update_mastery(
    session: Session, *, user_id: int, mistake: Mistake, correct: bool, now: datetime
) -> None:
    """没有挂知识点的题不写掌握度（不猜）；写失败让整个复习回滚，避免状态不一致。"""
    kp_ids = [
        int(row[0])
        for row in session.execute(
            select(QuestionKp.kp_id).where(QuestionKp.question_id == mistake.question_id)
        ).all()
    ]
    if not kp_ids:
        return
    question = session.get(Question, mistake.question_id)
    mastery_service.record_attempts(
        session,
        user_id=user_id,
        kp_ids=kp_ids,
        s=1.0 if correct else 0.0,
        difficulty=int(question.difficulty) if question is not None else 3,
        now=now,
    )
```

文件顶部补 `from app.services import mastery_service`（注意循环导入：`mastery_service` 不 import `mistake_service`，安全）。

- [ ] **Step 6: 写路由**

创建 `backend/app/api/v1/mastery.py`：

```python
"""S4-7 掌握度接口：本人重算 + 本人列表（API.md §4.6）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.kp import MasteryPage, MasteryRecomputeOut
from app.services import mastery_service
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/kp/mastery", tags=["mastery"])


@router.post(
    "/recompute", response_model=Envelope[MasteryRecomputeOut], summary="重算掌握度"
)
def recompute_mastery(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[MasteryRecomputeOut]:
    result = mastery_service.recompute_user(session, user_id=current_user.id)
    return Envelope(
        trace_id=get_trace_id(),
        data=MasteryRecomputeOut(
            events_replayed=result.events_replayed,
            rows_built=result.rows_built,
            skipped_no_kp=result.skipped_no_kp,
        ),
    )


@router.get("", response_model=Envelope[MasteryPage], summary="我的掌握度")
def list_my_mastery(
    subject_id: int | None = Query(None, ge=1, description="学科 id"),
    page: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[MasteryPage]:
    return Envelope(
        trace_id=get_trace_id(),
        data=mastery_service.list_mastery(
            session,
            user_id=current_user.id,
            subject_id=subject_id,
            page=page,
            sort=sort,
        ),
    )
```

在 `backend/app/api/router.py` 里加：

```python
from app.api.v1 import (
    admin, auth, files, kp, mastery, mistakes, notes, qa, questions, retrieval, tasks,
)
```

```python
api_router.include_router(mastery.router)
```

- [ ] **Step 7: 跑测试**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_mastery.py -q`
Expected: `21 passed`

如有导入路径错误，按报错改 import（只改路径，不改逻辑）。

- [ ] **Step 8: 补接口层测试**

在 `backend/tests/test_mastery.py` 末尾追加：

```python
def _client(user):  # noqa: ANN001, ANN202
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app

    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else 0

        def flush(self) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: _Session()
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_token(user)}"})
    return client


def _token(user) -> str:  # noqa: ANN001, ANN202
    from app.core.security import create_access_token

    return create_access_token(user_id=user.id, role=user.role).token


def _user(role: str = "student"):  # noqa: ANN001, ANN202
    from app.models.user import User

    user = User(
        username=f"{role}_s47", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


def test_mastery_api_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/kp/mastery").status_code == 401
        assert client.post("/api/v1/kp/mastery/recompute").status_code == 401


def test_mastery_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/kp/mastery").status_code == 403
        assert client.post("/api/v1/kp/mastery/recompute").status_code == 403
    finally:
        from app.main import app

        app.dependency_overrides.clear()


def test_recompute_api_forwards_user(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    captured: dict[str, int] = {}

    def fake_recompute(session, *, user_id):  # noqa: ANN001, ANN202
        captured["user_id"] = user_id
        return mastery_service.RecomputeResult(
            events_replayed=44, rows_built=13, skipped_no_kp=31
        )

    monkeypatch.setattr(mastery_service, "recompute_user", fake_recompute)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/kp/mastery/recompute")
        assert resp.status_code == 200
        assert resp.json()["data"] == {
            "events_replayed": 44,
            "rows_built": 13,
            "skipped_no_kp": 31,
        }
        assert captured == {"user_id": 50}
    finally:
        app.dependency_overrides.clear()


def test_list_mastery_api_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app
    from app.models.user import User
    from app.schemas.kp import MasteryPage

    captured: dict[str, object] = {}

    def fake_list(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return MasteryPage(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(mastery_service, "list_mastery", fake_list)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/kp/mastery?subject_id=7&sort=due_at&order=asc")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0
        assert captured["subject_id"] == 7
        assert captured["user_id"] == 50
        assert captured["sort"].sort_by == "due_at"
    finally:
        app.dependency_overrides.clear()
```

`User` 需要在文件顶部 import 区补 `from app.models.user import User`（若上面 DB 段已 import 则不重复）。

- [ ] **Step 9: 跑测试 + 全量**

Run:

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_mastery.py -q
../.venv/Scripts/python.exe -m pytest -q
```

Expected: `tests/test_mastery.py` 25 passed；全量 `1184 passed, 1 warning`（基线 1159 + 25）

- [ ] **Step 10: 补 API.md**

在 `docs/API.md` §4.5 之后新增 §4.6（内容与 spec §3.2 一致，含入参/出参/错误码）。同时在 §4.5 的 `GET /api/v1/kp/graph/snapshot` 出参示例的节点里加 `"mastery": 0.42`，备注加一句「`mastery` 为折算后的有效掌握度 `M_t`，无行 = `null`（未评估）」。

- [ ] **Step 11: 提交**

```bash
cd study-agent && git add backend/app/services/mastery_service.py backend/app/services/mistake_service.py backend/app/schemas/kp.py backend/app/api/v1/mastery.py backend/app/api/router.py backend/tests/test_mastery.py docs/API.md
git commit -m "feat(s4-7): 掌握度用例、错题复习挂载与两条接口"
```

---

### Task 4: 图谱接入掌握度 + 前端换色

**Files:**
- Modify: `backend/app/services/graph_service.py`（`snapshot` 补 mastery）
- Modify: `backend/app/schemas/kp.py`（`GraphSnapshotNode` 加 `mastery`）
- Modify: `backend/tests/test_graph_snapshot.py`
- Modify: `web/src/types/graph.ts`
- Modify: `web/src/views/kp/useGraphData.ts`
- Modify: `web/src/views/kp/Graph.vue`
- Modify: `web/src/views/kp/useGraphData.spec.ts`
- Modify: `web/src/views/kp/Graph.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `decayed_mastery`；Task 2 的 `Mastery`
- Produces: `GraphSnapshotNode.mastery: float | null`；`nodeColor(mastery: number | null): string`（签名从 `mistake_count` 改为 `mastery`）

- [ ] **Step 1: 后端补字段（先写测试）**

在 `backend/tests/test_graph_snapshot.py` 追加：

```python
def test_snapshot_attaches_decayed_mastery() -> None:
    session = _session(mistake_rows=[(2, 3)])
    session.mastery_rows = [(2, 0.8, 10.0, NOW - timedelta(days=10))]
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    by_id = {node.id: node for node in out.nodes}
    assert by_id[2].mastery == pytest.approx(0.294)  # 0.8·exp(-10/10)
    assert by_id[1].mastery is None  # 没有行 = 未评估


def test_snapshot_ignores_other_users_mastery() -> None:
    session = _session()
    session.mastery_rows = []
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert all(node.mastery is None for node in out.nodes)
    assert "mastery.user_id" in session.mastery_sql
```

`FakeSnapshotSession` 需要补两个属性：`mastery_rows`（默认 `[]`）与 `mastery_sql`（记录该查询编译后的 SQL）。在 `__init__` 里加 `self.mastery_rows = []`、`self.mastery_sql = ""`；`execute` 分派时按 SQL 里是否含 `"mastery"` 返回 `_Rows(self.mastery_rows)` 并把编译 SQL 记进 `self.mastery_sql`（其余仍返回 `self.mistake_rows`）。文件顶部补 `timedelta`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_snapshot.py -q`
Expected: FAIL —— `AttributeError: 'GraphSnapshotNode' object has no attribute 'mastery'` 或 `TypeError: ... unexpected keyword`

- [ ] **Step 3: 实现**

`backend/app/schemas/kp.py` 的 `GraphSnapshotNode` 加字段：

```python
    mastery: float | None = None
```

`backend/app/services/graph_service.py` 在 `snapshot` 之前加：

```python
def _mastery_map(
    session: Session, *, user_id: int, kp_ids: Sequence[int]
) -> dict[int, float]:
    """当前用户在这些知识点上的有效掌握度 M_t（无行不出现 → 前端显示未评估）。"""
    from app.models.mastery import Mastery

    if not kp_ids:
        return {}
    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(
            Mastery.kp_id, Mastery.mastery, Mastery.stability, Mastery.last_practice_at
        ).where(Mastery.user_id == user_id, Mastery.kp_id.in_(list(kp_ids)))
    ).all()
    mastered: dict[int, float] = {}
    for kp_id, mastery, stability, last_practice_at in rows:
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (now - last_practice_at).total_seconds() / 86400.0)
        mastered[int(kp_id)] = mastery_service.decayed_mastery(
            float(mastery), float(stability), days=days
        )
    return mastered
```

在 `snapshot` 里 `counts = _mistake_counts(...)` 之后加：

```python
    mastered = _mastery_map(session, user_id=user_id, kp_ids=node_ids)
```

节点构造里加：

```python
                mastery=mastered.get(node.id),
```

顶部 import 补 `from datetime import datetime, timezone`（若未 import）与 `from app.services import mastery_service`（注意 `graph_service` 与 `mastery_service` 无循环依赖）。

- [ ] **Step 4: 跑测试**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_snapshot.py -q && ../.venv/Scripts/python.exe -m pytest -q`
Expected: snapshot 12 passed；全量 `1186 passed, 1 warning`

- [ ] **Step 5: 前端类型与配色（先写测试）**

`web/src/views/kp/useGraphData.spec.ts`：把 `nodeColor` 的用例整块替换为

```ts
describe('nodeColor', () => {
  it('按掌握度分档，未评估为灰', () => {
    expect(nodeColor(null)).toBe('#9aa4b2')
    expect(nodeColor(0)).toBe('#e5484d')
    expect(nodeColor(0.39)).toBe('#e5484d')
    expect(nodeColor(0.4)).toBe('#f0b429')
    expect(nodeColor(0.69)).toBe('#f0b429')
    expect(nodeColor(0.7)).toBe('#22c55e')
    expect(nodeColor(1)).toBe('#22c55e')
  })

  it('masteryLabel 给出可读文案', () => {
    expect(masteryLabel(null)).toBe('未评估')
    expect(masteryLabel(0.42)).toBe('掌握度 0.42')
  })
})
```

import 行加 `masteryLabel`；`buildOption` 的用例里节点 fixture 增加 `mastery`（`node()` 工厂补 `mastery: opts.mastery ?? null` 字段），并把颜色断言从错题数改为掌握度：

```ts
    const nodes = [node(3, '单调性', { exam_weight: 1, mastery: 0.2 })]
```
```ts
    expect(series.data[0]).toMatchObject({
      id: '3',
      name: '单调性',
      symbolSize: 30,
      itemStyle: { color: '#e5484d' },
    })
```

`web/src/types/graph.ts` 的 `GraphSnapshotNode` 接口加字段：

```ts
  mastery: number | null
```

`web/src/views/kp/useGraphData.spec.ts` 的 `node()` 工厂补一行（放在 `mistake_count` 之后）：

```ts
    mastery: opts.mastery ?? null,
```

`web/src/views/kp/Graph.spec.ts` 的 fixture 也要补：`node()` 工厂加 `mastery: 0.5,`；`snapshot()` 里手写的两个节点对象（`高中数学` / `函数`）各加 `mastery: null,`；`detail` 常量不动。

- [ ] **Step 6: 跑前端测试确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/useGraphData.spec.ts`
Expected: FAIL —— `masteryLabel is not a function` / 颜色断言不符

- [ ] **Step 7: 实现配色**

`web/src/views/kp/useGraphData.ts`：

```ts
export const COLOR_UNRATED = '#9aa4b2'
export const COLOR_LOW = '#e5484d'
export const COLOR_MID = '#f0b429'
export const COLOR_HIGH = '#22c55e'

/** 掌握度分档（S4-7）：<0.4 红、0.4–0.7 黄、≥0.7 绿；null = 未评估。 */
export function nodeColor(mastery: number | null): string {
  if (mastery === null) return COLOR_UNRATED
  if (mastery < 0.4) return COLOR_LOW
  if (mastery < 0.7) return COLOR_MID
  return COLOR_HIGH
}

export function masteryLabel(mastery: number | null): string {
  return mastery === null ? '未评估' : `掌握度 ${mastery.toFixed(2)}`
}
```

`buildOption` 的 `data` 里把 `itemStyle: { color: nodeColor(node.mistake_count) }` 改成 `nodeColor(node.mastery)`，并加 `mastery: node.mastery`（给 tooltip 用）。

`web/src/views/kp/Graph.vue`：
- 页头 `description` 改成「力导向知识图谱：节点大小=考纲权重，颜色=掌握度（灰=未评估，红<0.4，黄 0.4–0.7，绿≥0.7）。」
- tooltip 改成：

```ts
    tooltip: {
      confine: true,
      formatter: (params: { dataType?: string; data?: { name?: string; mastery?: number | null } }) =>
        params.dataType === 'node'
          ? `${params.data?.name ?? ''}\n${masteryLabel(params.data?.mastery ?? null)}`
          : '',
    },
```

（`masteryLabel` 从 `./useGraphData` import；模板与其它逻辑不动。）

- [ ] **Step 8: 跑前端测试 + 构建**

Run:

```bash
cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/useGraphData.spec.ts src/views/kp/Graph.spec.ts
npm run test:run -- --pool=threads
npm run build
```

Expected: 两个 spec 全绿；全量 `226 passed / 39 files`（基线 225，`nodeColor` 用例拆分多一条）；build 退出 0。

- [ ] **Step 9: 提交**

```bash
cd study-agent && git add backend/app/services/graph_service.py backend/app/schemas/kp.py backend/tests/test_graph_snapshot.py web/src/types/graph.ts web/src/views/kp/useGraphData.ts web/src/views/kp/Graph.vue web/src/views/kp/useGraphData.spec.ts web/src/views/kp/Graph.spec.ts
git commit -m "feat(s4-7): 图谱节点接入掌握度并按掌握度配色"
```

---

### Task 5: 7 天模拟脚本 + 真机验收 + 文档 + 合并

**Files:**
- Create: `backend/scripts/mastery_sim.py`
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-050）、`README.md`
- Create: `.sdd/s4-7/acceptance-evidence.md`、`.sdd/s4-7/progress.md`

- [ ] **Step 1: 写模拟脚本**

创建 `backend/scripts/mastery_sim.py`：

```python
"""S4-7 掌握度模型：7 天作答模拟 + 参数敏感性扫描（答辩材料）。

只调用纯函数，不连库、不调 LLM。用法：
    python scripts/mastery_sim.py
    python scripts/mastery_sim.py --k0 0.35 --grow 1.8
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from app.services import mastery_service as ms

PATTERN = [True, False, True, True, False, True, True]
"""7 天作答模式：对/错/对/对/错/对/对。故意第二天就错一次，好看出下降。"""


def simulate_week(*, difficulty: int = 3, k0: float = ms.K0, grow: float = ms.STABILITY_GROW) -> list[str]:
    original_k0, original_grow = ms.K0, ms.STABILITY_GROW
    ms.K0, ms.STABILITY_GROW = k0, grow
    try:
        start = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
        state = ms.NEW_STATE
        lines = [
            "天  结果  M      S       M_t(当日)  interval",
        ]
        for index, correct in enumerate(PATTERN):
            day = start + timedelta(days=index)
            state = ms.next_state(
                state,
                s=1.0 if correct else 0.0,
                difficulty=difficulty,
                now=day,
            )
            interval = (state.due_at - state.last_practice_at).days if state.due_at else 0
            lines.append(
                f"{index + 1:>2}  {'对' if correct else '错':<4}  "
                f"{state.mastery:<6.3f} {state.stability:<6.2f} "
                f"{state.mastery:<9.3f} {interval:>3} 天"
            )
        return lines
    finally:
        ms.K0, ms.STABILITY_GROW = original_k0, original_grow


def sensitivity_grid() -> list[str]:
    """K0 × 对倍率 的 3×3 扫描：看「连对 5 次后的 M 与 interval」是否稳健。"""
    lines = ["", "敏感性扫描（d=3，连对 5 次后的 M / interval 天）", "K0\\倍率  " + "  ".join(f"{g:<10.1f}" for g in (1.5, 1.8, 2.1))]
    for k0 in (0.25, 0.35, 0.45):
        cells = []
        for grow in (1.5, 1.8, 2.1):
            original_k0, original_grow = ms.K0, ms.STABILITY_GROW
            ms.K0, ms.STABILITY_GROW = k0, grow
            try:
                state = ms.NEW_STATE
                start = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
                for day in range(5):
                    state = ms.next_state(state, s=1.0, difficulty=3, now=start + timedelta(days=day))
            finally:
                ms.K0, ms.STABILITY_GROW = original_k0, original_grow
            interval = (state.due_at - state.last_practice_at).days if state.due_at else 0
            cells.append(f"{state.mastery:.3f}/{interval:<4}")
        lines.append(f"{k0:<8.2f} " + "  ".join(cells))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="掌握度模型模拟器")
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--k0", type=float, default=ms.K0)
    parser.add_argument("--grow", type=float, default=ms.STABILITY_GROW)
    args = parser.parse_args()
    print("\n".join(simulate_week(difficulty=args.difficulty, k0=args.k0, grow=args.grow)))
    print("\n".join(sensitivity_grid()))


if __name__ == "__main__":
    main()
```

> `ms.K0` 每次调用现取，别在模块顶部 `from ... import K0` 拷一份，否则参数扫描改不生效。

- [ ] **Step 2: 跑脚本**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe scripts/mastery_sim.py`
Expected: 打印 7 行表格 + 3×3 敏感性表格；连对 5 次那行附近 `M≈0.462`、`interval=17`（`K0=0.35` 列）。

把完整输出存 `.sdd/s4-7/mastery_sim.txt`。

- [ ] **Step 3: 启动服务真机验收**

```bash
# 终端 A
cd study-agent/backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8032
# 终端 B
cd study-agent/web && npm run dev
```

按 spec §7 逐条跑（学生 `s43_accept_20261103` / `accept-pass-2026`）：

1. `POST /api/v1/kp/mastery/recompute` → 记录 `events_replayed` / `rows_built` / `skipped_no_kp`；再跑一次比对结果一致
2. `GET /api/v1/kp/mastery` → 记录行数、`mastery` / `mastery_t` / `due_at - last_practice_at`
3. 找一条 `difficulty=3` 且挂了知识点的错题，`POST /api/v1/mistakes/{id}/review {"correct": true}` → 再查 `GET /kp/mastery` 看从 0 涨到 0.117
4. 再 `{"correct": false}` → 看跌到 0.103、`stability` 1.80
5. `/graph` 页面看节点颜色分四档、tooltip 有掌握度
6. 教师账号打 `GET /kp/mastery` → 403

任何一条不符合都要停下来报告，不要改验收口径。

- [ ] **Step 4: 写证据与进度文档**

`.sdd/s4-7/acceptance-evidence.md`：环境、账号、spec §7 六条实测数字（贴 JSON 片段）、敏感性表格、未验证项。

`.sdd/s4-7/progress.md`：与 plan 的偏离、遇到的坑、遗留项。

- [ ] **Step 5: 更新文档三件套**

- `docs/PROGRESS.md`：S4-7 打勾、最近完成、关键口径（公式与参数来源、挂载点、懒创建、图谱换色）、验收段贴实测数字、下一步改 S4-8
- `docs/DECISIONS.md`：新增 `## D-050 掌握度模型与更新服务（S4-7）`，覆盖：参数是工程取值不是拟合、挂载在错题复习、懒创建、recompute 回放语义、图谱换色、失效边界
- `README.md`：加一段「掌握度怎么看 / 怎么重算」

- [ ] **Step 6: 全量回归**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent/web && npm run test:run -- --pool=threads
cd study-agent/web && npm run build
```

Expected: 后端 1186 passed；前端 226 passed / 39 files；build 退出 0。

- [ ] **Step 7: 提交 + ff-merge**

```bash
cd study-agent && git add backend/scripts/mastery_sim.py docs README.md
git commit -m "docs(s4-7): 模拟脚本、验收证据与文档同步"
git checkout main && git merge --ff-only feature/s4-7-mastery && git branch -d feature/s4-7-mastery
# 不 push（用户自己推）
```

---

## 风险与回退

- `record_review` 改坏会让 S4-2 的复习链路整体失败 → 钩子写成独立 `_update_mastery`，出错应让请求 500 回滚（数据一致性优先），不要 try/except 吞掉。
- 若真实数据里错题没有 `question_kps`（当前 44 条里只有 13 条有），`recompute` 的 `rows_built` 会小于错题数——这是正确行为，`skipped_no_kp` 就是为此存在。
- `mastery_sim.py` 通过改写模块常量做敏感性扫描，属于"脚本里的权宜"；如果以后要并发调用，应改成传参版本（本卡不需要）。
- 前端 `nodeColor` 签名变更会让 `buildOption` 的颜色来源整体切换；若验收发现"页面全灰"，先查 `GET /kp/mastery` 是否有行（学生账号要先 `recompute` 或复习一次）。
- 若 `paginate_sa` 对 `select(Mastery, name, subject_id)` 的 count 报错（多实体查询），回退方案：改成 `select(Mastery).options(joinedload)` 或先查 `Mastery` 再 `IN` 批查名字（与 `graph_service._edge_names` 同款），**这是唯一预判到的技术风险**，遇到再报。