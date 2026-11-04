# S4-8 错题统计看板 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `GET /api/v1/stats/overview` 一条聚合接口（状态/错因/知识点 TOP10+掌握度/按天趋势）+ 一个 `/stats` 页面（三张 ECharts 图 + 摘要卡 + 空态），并把阶段 4 收尾 tag 打上。

**Architecture:** 后端把「窗口计算 + 按天补零」做成纯函数，聚合全部走 SQL（9 条单行/分组聚合，无 N+1），Python 只做 DTO 组装；前端把「数据 → ECharts option」抽成纯函数（jsdom 无 canvas 也能测），页面只管请求与 range 切换。掌握度取色与图谱共用 `utils/masteryColor.ts`，避免两处硬编码同一组色值。

**Tech Stack:** Python 3.11 + SQLAlchemy 2.0 + Pydantic v2 + FastAPI；Vue 3 + TS + ECharts 6.1.0（现有依赖，不加新包）+ Vitest。

**Spec:** `docs/spec/s4-8-dashboard.md`

## Global Constraints

- 后端命令在 `study-agent/backend` 下执行，解释器 `../.venv/Scripts/python.exe`；前端在 `study-agent/web` 下执行。
- 接口只给 `student`，只查本人：每条 SQL 必须带 `Mistake.user_id == user_id`（`mastery` 查询同）。
- 窗口口径：`mistakes.created_at ∈ [今天-N+1 天的 00:00 UTC, 现在]`，`N ∈ {7,30,90}`，默认 `30d`；**全站 UTC**，不转本地时区。
- `by_status` 恒 3 行（顺序 `待订正 → 已订正 → 已掌握`）；`by_cause` 按 `count DESC, cause_type ASC`；`top_kps` 最多 10 条。
- `trend` 按天补零（7/30/90 个点）；`mastered` 是**回算累计**（含窗口前的已掌握数作起点），不是历史快照。
- `top_kps[].mastery` 为 S4-7 的折算 `M_t`，无行 = `null`。
- 禁止假数据：TOP 柱只有 5 根、趋势只有 1 个非零点，如实呈现并给解释性提示。
- 不加新依赖、不新增表、不改迁移（`alembic heads` 保持 `0013_s4_7`）。
- 提交前：后端 `pytest -q`、前端 `npm run test:run -- --pool=threads`、前端 `npm run build`。
- 提交信息 `feat(s4-8): ...` / `docs(s4-8): ...`；**不要 push**（用户自己推）。

---

### Task 1: 统计聚合服务 + schema

**Files:**
- Create: `backend/app/services/stats_service.py`
- Create: `backend/app/schemas/stats.py`
- Modify: `backend/app/services/mastery_service.py`（新增公开 `mastery_values`）
- Modify: `backend/app/services/graph_service.py`（`_mastery_map` 改为委托，去重复逻辑）
- Create: `backend/tests/test_stats_service.py`

**Interfaces:**
- Produces（Task 2 依赖）：
  - `RANGES: dict[str, int]`、`DEFAULT_RANGE = "30d"`、`TOP_KP_LIMIT = 10`
  - `Window(key: str, days: int, start: datetime, end: datetime, dates: list[date])`
  - `build_window(range_key: str, *, now: datetime | None = None) -> Window`
  - `fill_days(rows: Mapping[date, int], dates: Sequence[date]) -> list[tuple[date, int]]`
  - `overview(session, *, user_id: int, range_key: str = DEFAULT_RANGE, now: datetime | None = None) -> StatsOverviewOut`
  - `mastery_service.mastery_values(session, *, user_id: int, kp_ids: Sequence[int], now: datetime | None = None) -> dict[int, float]`
  - schemas：`StatsRangeOut / StatsSummaryOut / StatsStatusCountOut / StatsCauseCountOut / StatsTopKpOut / StatsTrendPointOut / StatsOverviewOut`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_stats_service.py`：

```python
"""S4-8 统计看板：窗口、补零、四维聚合、权限过滤（FakeSession 只验 SQL 口径）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.exceptions import InvalidParamError
from app.services import stats_service

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeStatsSession:
    """按 SQL 里的表名/函数名分派：假会话不执行 WHERE，只回放"数据库会给的行"。"""

    def __init__(
        self,
        *,
        status_rows: list[tuple] | None = None,
        cause_rows: list[tuple] | None = None,
        kp_rows: list[tuple] | None = None,
        new_rows: list[tuple] | None = None,
        mastered_rows: list[tuple] | None = None,
        mastery_rows: list[tuple] | None = None,
        analyzed: int = 0,
        with_kp: int = 0,
        mastery_count: int = 0,
    ) -> None:
        self.status_rows = status_rows or []
        self.cause_rows = cause_rows or []
        self.kp_rows = kp_rows or []
        self.new_rows = new_rows or []
        self.mastered_rows = mastered_rows or []
        self.mastery_rows = mastery_rows or []
        self.analyzed = analyzed
        self.with_kp = with_kp
        self.mastery_count = mastery_count
        self.statements: list[object] = []

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        sql = str(statement)
        if "FORMAT" in sql:  # pragma: no cover - 兜底，防止分派漏配
            raise AssertionError(f"未分派的 SQL: {sql}")
        if "mistake_analyses" in sql and "cause_type" in sql:
            return _Rows(self.cause_rows)
        if "knowledge_points" in sql:
            return _Rows(self.kp_rows)
        if "mastery" in sql:
            return _Rows(self.mastery_rows)
        if "date_trunc" in sql and "last_review_at" in sql:
            return _Rows(self.mastered_rows)
        if "date_trunc" in sql:
            return _Rows(self.new_rows)
        return _Rows(self.status_rows)

    def scalar(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        sql = str(statement)
        if "mistake_analyses" in sql:
            return self.analyzed
        if "question_kps" in sql:
            return self.with_kp
        if "mastery" in sql:
            return self.mastery_count
        raise AssertionError(f"未分派的 scalar: {sql}")


def test_build_window_30d_has_thirty_days() -> None:
    window = stats_service.build_window("30d", now=NOW)
    assert window.key == "30d"
    assert window.days == 30
    assert len(window.dates) == 30
    assert window.dates[-1] == date(2026, 11, 4)
    assert window.dates[0] == date(2026, 10, 6)
    assert window.start == datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
    assert window.end == NOW


def test_build_window_7d_and_90d_lengths() -> None:
    assert len(stats_service.build_window("7d", now=NOW).dates) == 7
    assert len(stats_service.build_window("90d", now=NOW).dates) == 90


def test_build_window_rejects_unknown_range() -> None:
    with pytest.raises(InvalidParamError) as exc:
        stats_service.build_window("365d", now=NOW)
    assert "365d" in str(exc.value)


def test_fill_days_pads_missing_days() -> None:
    dates = [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    assert stats_service.fill_days({date(2026, 11, 2): 5}, dates) == [
        (date(2026, 11, 1), 0),
        (date(2026, 11, 2), 5),
        (date(2026, 11, 3), 0),
    ]


def test_overview_builds_all_four_blocks() -> None:
    session = FakeStatsSession(
        status_rows=[("待订正", 33), ("已订正", 1)],
        cause_rows=[("概念不清", 11), ("计算失误", 6)],
        kp_rows=[(197, "同角三角函数基本关系", 1)],
        new_rows=[(date(2026, 11, 3), 34)],
        mastered_rows=[],
        mastery_rows=[(197, "0.144", "1.00", NOW)],
        analyzed=34,
        with_kp=3,
        mastery_count=5,
    )
    out = stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    assert out.range.key == "30d"
    assert out.range.from_ == date(2026, 10, 6)
    assert out.range.to == date(2026, 11, 4)
    assert out.summary.total == 34
    assert out.summary.pending == 33
    assert out.summary.corrected == 1
    assert out.summary.mastered == 0
    assert out.summary.analyzed == 34
    assert out.summary.with_kp == 3
    assert out.summary.mastery_rows == 5
    assert out.by_cause[0].cause_type == "概念不清"
    assert out.top_kps[0].kp_id == 197
    assert out.top_kps[0].mastery == pytest.approx(0.144)
    assert len(out.trend) == 30
    assert out.trend[-1].date == date(2026, 11, 4)


def test_overview_status_rows_always_three() -> None:
    session = FakeStatsSession(status_rows=[("待订正", 2)])
    out = stats_service.overview(session, user_id=50, range_key="7d", now=NOW)
    assert [(row.status, row.count) for row in out.by_status] == [
        ("待订正", 2),
        ("已订正", 0),
        ("已掌握", 0),
    ]


def test_overview_trend_pads_zero_and_accumulates_mastered() -> None:
    session = FakeStatsSession(
        new_rows=[(date(2026, 11, 3), 34)],
        mastered_rows=[(date(2026, 10, 1), 2), (date(2026, 11, 3), 1)],
    )
    out = stats_service.overview(session, user_id=50, range_key="7d", now=NOW)
    trend = [(point.date, point.new_mistakes, point.mastered) for point in out.trend]
    assert trend[0] == (date(2026, 10, 29), 0, 2)  # 窗口前的 2 条算进起点
    assert trend[-2] == (date(2026, 11, 3), 34, 3)
    assert trend[-1] == (date(2026, 11, 4), 0, 3)


def test_overview_top_kp_mastery_none_when_no_row() -> None:
    session = FakeStatsSession(kp_rows=[(120, "数列", 1)], mastery_rows=[])
    out = stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    assert out.top_kps[0].mastery is None


def test_overview_every_statement_filters_user() -> None:
    session = FakeStatsSession(status_rows=[("待订正", 1)])
    stats_service.overview(session, user_id=50, range_key="30d", now=NOW)
    compiled = " || ".join(
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        for stmt in session.statements
    )
    assert "mistakes.user_id = 50" in compiled
    assert "mastery.user_id = 50" in compiled
    assert "mistakes.created_at >=" in compiled


def test_mastery_values_returns_decayed_map() -> None:
    from app.services import mastery_service

    session = FakeStatsSession(
        mastery_rows=[(197, "0.800", "10.00", NOW - timedelta(days=10))]
    )
    values = mastery_service.mastery_values(session, user_id=50, kp_ids=[197], now=NOW)
    assert values[197] == pytest.approx(0.294)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_stats_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.stats_service'`

- [ ] **Step 3: 提炼 `mastery_values`**

在 `backend/app/services/mastery_service.py` 末尾追加：

```python
def mastery_values(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    now: datetime | None = None,
) -> dict[int, float]:
    """批量取有效掌握度 M_t；无行的知识点不出现在结果里（= 未评估）。"""
    from app.models.mastery import Mastery

    unique_ids = sorted({int(kp_id) for kp_id in kp_ids})
    if not unique_ids:
        return {}
    moment = now or datetime.now(timezone.utc)
    rows = session.execute(
        select(
            Mastery.kp_id, Mastery.mastery, Mastery.stability, Mastery.last_practice_at
        ).where(Mastery.user_id == user_id, Mastery.kp_id.in_(unique_ids))
    ).all()
    values: dict[int, float] = {}
    for kp_id, mastery, stability, last_practice_at in rows:
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (moment - last_practice_at).total_seconds() / 86400.0)
        values[int(kp_id)] = decayed_mastery(
            float(mastery), float(stability), days=days
        )
    return values
```

把 `backend/app/services/graph_service.py` 的 `_mastery_map` 整体替换为委托（签名与返回不变，S4-6 的测试继续有效）：

```python
def _mastery_map(
    session: Session,
    *,
    user_id: int,
    kp_ids: Sequence[int],
    now: datetime | None = None,
) -> dict[int, float]:
    """当前用户在这些知识点上的有效掌握度 M_t（委托 mastery_service，避免两份折算逻辑）。"""
    from app.services import mastery_service

    return mastery_service.mastery_values(
        session, user_id=user_id, kp_ids=kp_ids, now=now
    )
```

- [ ] **Step 4: 写 schema**

创建 `backend/app/schemas/stats.py`：

```python
"""S4-8 统计看板出参（API.md §4.7）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class StatsRangeOut(BaseModel):
    """窗口回显；`from` 是 Python 关键字，字段名用 `from_` + alias 输出成 `from`。"""

    key: str
    from_: date = Field(alias="from")
    to: date


class StatsSummaryOut(BaseModel):
    total: int
    pending: int
    corrected: int
    mastered: int
    analyzed: int
    with_kp: int
    mastery_rows: int


class StatsStatusCountOut(BaseModel):
    status: str
    count: int


class StatsCauseCountOut(BaseModel):
    cause_type: str
    count: int


class StatsTopKpOut(BaseModel):
    kp_id: int
    kp_name: str
    count: int
    mastery: float | None = None


class StatsTrendPointOut(BaseModel):
    date: date
    new_mistakes: int
    mastered: int


class StatsOverviewOut(BaseModel):
    range: StatsRangeOut
    summary: StatsSummaryOut
    by_status: list[StatsStatusCountOut]
    by_cause: list[StatsCauseCountOut]
    top_kps: list[StatsTopKpOut]
    trend: list[StatsTrendPointOut]
```

- [ ] **Step 5: 写服务**

创建 `backend/app/services/stats_service.py`：

```python
"""S4-8 错题统计看板：本人错题的窗口聚合（状态/错因/知识点/趋势）。

全部走 SQL 聚合（9 条单行或分组语句），Python 只做「按天补零 + DTO 组装」，
不允许逐行查库。窗口与补零是纯函数，可脱离数据库断言。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import Date, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.models.enums import MISTAKE_STATUSES, MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question_kp import QuestionKp
from app.schemas.stats import (
    StatsCauseCountOut,
    StatsOverviewOut,
    StatsRangeOut,
    StatsStatusCountOut,
    StatsSummaryOut,
    StatsTopKpOut,
    StatsTrendPointOut,
)
from app.services import mastery_service

RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"
TOP_KP_LIMIT = 10


@dataclass(frozen=True, slots=True)
class Window:
    key: str
    days: int
    start: datetime
    end: datetime
    dates: list[date]


def build_window(range_key: str, *, now: datetime | None = None) -> Window:
    """窗口 = 今天往前 N-1 天的 00:00 UTC ~ 现在；按天分桶用 UTC。"""
    if range_key not in RANGES:
        options = "、".join(RANGES)
        raise InvalidParamError(f"不支持的统计窗口：{range_key}（可选：{options}）")
    days = RANGES[range_key]
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    last_day = moment.date()
    dates = [last_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    start = datetime.combine(dates[0], time.min, tzinfo=timezone.utc)
    return Window(key=range_key, days=days, start=start, end=moment, dates=dates)


def fill_days(
    rows: Mapping[date, int], dates: Sequence[date]
) -> list[tuple[date, int]]:
    """缺的天补 0：折线不能断在没数据的那天。"""
    return [(day, int(rows.get(day, 0))) for day in dates]


def _day(column: Any) -> Any:
    return func.date_trunc("day", column).cast(Date)


def overview(
    session: Session,
    *,
    user_id: int,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> StatsOverviewOut:
    window = build_window(range_key, now=now)
    in_window = [
        Mistake.user_id == user_id,
        Mistake.created_at >= window.start,
        Mistake.created_at <= window.end,
    ]

    status_rows = session.execute(
        select(Mistake.status, func.count()).where(*in_window).group_by(Mistake.status)
    ).all()
    counts = {status: int(count) for status, count in status_rows}
    by_status = [
        StatsStatusCountOut(status=status, count=counts.get(status, 0))
        for status in MISTAKE_STATUSES
    ]
    analyzed = int(
        session.scalar(
            select(func.count(func.distinct(MistakeAnalysis.mistake_id)))
            .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
            .where(*in_window)
        )
        or 0
    )
    with_kp = int(
        session.scalar(
            select(func.count(func.distinct(Mistake.id)))
            .join(QuestionKp, QuestionKp.question_id == Mistake.question_id)
            .where(*in_window)
        )
        or 0
    )
    mastery_rows = int(
        session.scalar(
            select(func.count()).select_from(Mastery).where(Mastery.user_id == user_id)
        )
        or 0
    )

    cause_rows = session.execute(
        select(MistakeAnalysis.cause_type, func.count())
        .join(Mistake, Mistake.id == MistakeAnalysis.mistake_id)
        .where(*in_window)
        .group_by(MistakeAnalysis.cause_type)
        # 并列时不排序会让图例每次刷新都换位置
        .order_by(func.count().desc(), MistakeAnalysis.cause_type)
    ).all()

    kp_count = func.count(func.distinct(Mistake.id))
    kp_rows = session.execute(
        select(QuestionKp.kp_id, KnowledgePoint.name, kp_count)
        .join(Mistake, Mistake.question_id == QuestionKp.question_id)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(*in_window)
        .group_by(QuestionKp.kp_id, KnowledgePoint.name)
        .order_by(kp_count.desc(), QuestionKp.kp_id)
        .limit(TOP_KP_LIMIT)
    ).all()
    mastered = mastery_service.mastery_values(
        session,
        user_id=user_id,
        kp_ids=[int(kp_id) for kp_id, _name, _count in kp_rows],
        now=window.end,
    )

    new_rows = session.execute(
        select(_day(Mistake.created_at), func.count())
        .where(*in_window)
        .group_by(_day(Mistake.created_at))
    ).all()
    # 已掌握按天分组不取窗口：窗口开始前就掌握的那些要算进累计起点
    mastered_rows = session.execute(
        select(_day(Mistake.last_review_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.status == MistakeStatus.MASTERED.value,
            Mistake.last_review_at.is_not(None),
        )
        .group_by(_day(Mistake.last_review_at))
    ).all()
    daily_new = {day: int(count) for day, count in new_rows}
    daily_mastered = {day: int(count) for day, count in mastered_rows}
    running = sum(
        count for day, count in daily_mastered.items() if day < window.dates[0]
    )
    trend: list[StatsTrendPointOut] = []
    for day, new_mistakes in fill_days(daily_new, window.dates):
        running += daily_mastered.get(day, 0)
        trend.append(
            StatsTrendPointOut(
                date=day, new_mistakes=new_mistakes, mastered=running
            )
        )

    return StatsOverviewOut(
        range=StatsRangeOut(
            key=window.key, from_=window.dates[0], to=window.dates[-1]
        ),
        summary=StatsSummaryOut(
            total=sum(counts.values()),
            pending=counts.get(MistakeStatus.TODO.value, 0),
            corrected=counts.get(MistakeStatus.CORRECTED.value, 0),
            mastered=counts.get(MistakeStatus.MASTERED.value, 0),
            analyzed=analyzed,
            with_kp=with_kp,
            mastery_rows=mastery_rows,
        ),
        by_status=by_status,
        by_cause=[
            StatsCauseCountOut(cause_type=cause, count=int(count))
            for cause, count in cause_rows
        ],
        top_kps=[
            StatsTopKpOut(
                kp_id=int(kp_id),
                kp_name=name,
                count=int(count),
                mastery=mastered.get(int(kp_id)),
            )
            for kp_id, name, count in kp_rows
        ],
        trend=trend,
    )
```

- [ ] **Step 6: 跑测试**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_stats_service.py -q`
Expected: `11 passed`

若 `test_overview_every_statement_filters_user` 因 `mastery` 语句在 `mastery_values` 内且 `kp_ids` 为空而没生成（`top_kps` 为空时），把该用例的 `kp_rows` 补一条。若日期 cast 在编译 SQL 里表现为 `CAST(date_trunc(...) AS DATE)`（断言 `date_trunc` 仍成立），不用改断言。

- [ ] **Step 7: 回归（确认 graph 委托没破坏 S4-6）**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `1197 passed, 1 warning`（基线 1186 + 11）

- [ ] **Step 8: 提交**

```bash
cd study-agent && git add backend/app/services/stats_service.py backend/app/schemas/stats.py backend/app/services/mastery_service.py backend/app/services/graph_service.py backend/tests/test_stats_service.py
git commit -m "feat(s4-8): 统计看板聚合服务与出参 schema"
```

---

### Task 2: 路由 + 契约

**Files:**
- Create: `backend/app/api/v1/stats.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_stats_api.py`
- Modify: `docs/API.md`

**Interfaces:**
- Consumes: Task 1 的 `stats_service.overview` / `build_window` 与 `StatsOverviewOut`
- Produces: `GET /api/v1/stats/overview`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_stats_api.py`：

```python
"""S4-8 统计接口：权限、参数校验、透传与出参字段名。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.stats import (
    StatsOverviewOut,
    StatsRangeOut,
    StatsSummaryOut,
)
from app.services import stats_service


def _user(role: str = "student") -> User:
    user = User(
        username=f"{role}_s48", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


def _client(user: User):  # noqa: ANN202
    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else None

        def flush(self) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: _Session()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_stats_api_requires_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/stats/overview").status_code == 401


def test_stats_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/stats/overview").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_stats_api_rejects_unknown_range() -> None:
    client = _client(_user())
    try:
        resp = client.get("/api/v1/stats/overview?range=365d")
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200
    finally:
        app.dependency_overrides.clear()


def test_stats_api_forwards_range_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return StatsOverviewOut(
            range=StatsRangeOut(key="7d", from_=date(2026, 10, 29), to=date(2026, 11, 4)),
            summary=StatsSummaryOut(
                total=34,
                pending=33,
                corrected=1,
                mastered=0,
                analyzed=34,
                with_kp=3,
                mastery_rows=5,
            ),
            by_status=[],
            by_cause=[],
            top_kps=[],
            trend=[],
        )

    monkeypatch.setattr(stats_service, "overview", fake_overview)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/stats/overview?range=7d")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50, "range_key": "7d"}
        assert data["range"]["from"] == "2026-10-29"
        assert data["summary"]["total"] == 34
    finally:
        app.dependency_overrides.clear()


def test_stats_api_defaults_to_30d(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_overview(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return StatsOverviewOut(
            range=StatsRangeOut(key="30d", from_=date(2026, 10, 6), to=date(2026, 11, 4)),
            summary=StatsSummaryOut(
                total=0,
                pending=0,
                corrected=0,
                mastered=0,
                analyzed=0,
                with_kp=0,
                mastery_rows=0,
            ),
            by_status=[],
            by_cause=[],
            top_kps=[],
            trend=[],
        )

    monkeypatch.setattr(stats_service, "overview", fake_overview)
    client = _client(_user())
    try:
        assert client.get("/api/v1/stats/overview").status_code == 200
        assert captured["range_key"] == "30d"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_stats_api.py -q`
Expected: FAIL —— 404（路由未注册）

- [ ] **Step 3: 写路由并注册**

创建 `backend/app/api/v1/stats.py`：

```python
"""S4-8 统计看板接口（API.md §4.7）：本人错题四维聚合，只读。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.stats import StatsOverviewOut
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=Envelope[StatsOverviewOut], summary="错题统计看板")
def stats_overview(
    range_: Literal["7d", "30d", "90d"] = Query(
        stats_service.DEFAULT_RANGE, alias="range", description="统计窗口"
    ),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[StatsOverviewOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=stats_service.overview(
            session, user_id=current_user.id, range_key=range_
        ),
    )
```

`backend/app/api/router.py`：`from app.api.v1 import (...)` 里加 `stats`（保持字母序，放在 `retrieval` 之后、`tasks` 之前），并加 `api_router.include_router(stats.router)`。

- [ ] **Step 4: 跑测试**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_stats_api.py -q && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `5 passed`；全量 `1202 passed, 1 warning`

- [ ] **Step 5: 补 API.md**

在 `docs/API.md` 的「掌握度（S4-7）」小节之后新增（spec §3.1 的完整内容），并在 `GET /api/v1/mistakes/stats` 的备注末尾加一句：

```markdown
- 备注：看板（趋势/掌握度/解释性计数）走 `GET /api/v1/stats/overview`（S4-8），本接口保持「错题页三条小统计」的定位不变
```

- [ ] **Step 6: 提交**

```bash
cd study-agent && git add backend/app/api/v1/stats.py backend/app/api/router.py backend/tests/test_stats_api.py docs/API.md
git commit -m "feat(s4-8): 统计看板接口与 API 契约"
```

---

### Task 3: 前端类型、API、纯函数图表层

**Files:**
- Create: `web/src/types/stats.ts`
- Create: `web/src/api/stats.ts`
- Create: `web/src/utils/masteryColor.ts`
- Modify: `web/src/views/kp/useGraphData.ts`（`nodeColor` / `masteryLabel` 委托到 utils）
- Create: `web/src/views/stats/useStatsCharts.ts`
- Create: `web/src/views/stats/useStatsCharts.spec.ts`

**Interfaces:**
- Consumes: Task 2 的接口 JSON
- Produces:
  - `types`：`StatsRange / StatsRangeInfo / StatsSummary / StatsStatusCount / StatsCauseCount / StatsTopKp / StatsTrendPoint / StatsOverview`
  - `fetchStatsOverview(range?: StatsRange): Promise<StatsOverview>`
  - `utils/masteryColor`：`masteryColor(mastery: number | null): string`、`masteryLabel(mastery: number | null): string`、`COLOR_UNRATED / COLOR_LOW / COLOR_MID / COLOR_HIGH`
  - `views/stats/useStatsCharts`：`summaryCards(summary): { label: string; value: number }[]`、`causeOption(data): unknown`、`topKpOption(data): unknown`、`trendOption(data): unknown`、`hasMastered(data): boolean`、`UNKNOWN_CAUSE_COLOR`

- [ ] **Step 1: 写失败测试**

创建 `web/src/views/stats/useStatsCharts.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { StatsCauseCount, StatsSummary, StatsTopKp, StatsTrendPoint } from '@/types/stats'

import {
  UNKNOWN_CAUSE_COLOR,
  causeOption,
  hasMastered,
  summaryCards,
  topKpOption,
  trendOption,
} from './useStatsCharts'

const summary: StatsSummary = {
  total: 34,
  pending: 33,
  corrected: 1,
  mastered: 0,
  analyzed: 34,
  with_kp: 3,
  mastery_rows: 5,
}

describe('summaryCards', () => {
  it('四张卡按固定顺序', () => {
    expect(summaryCards(summary)).toEqual([
      { label: '错题总数', value: 34 },
      { label: '待订正', value: 33 },
      { label: '已订正', value: 1 },
      { label: '已掌握', value: 0 },
    ])
  })
})

describe('causeOption', () => {
  const data: StatsCauseCount[] = [
    { cause_type: '概念不清', count: 11 },
    { cause_type: 'unknown', count: 1 },
  ]

  it('把错因映射成饼图数据，unknown 用灰', () => {
    const option = causeOption(data) as {
      series: Array<{ data: Array<{ name: string; value: number; itemStyle: { color: string } }> }>
    }
    expect(option.series[0].data.map((item) => [item.name, item.value])).toEqual([
      ['概念不清', 11],
      ['unknown', 1],
    ])
    expect(option.series[0].data[1].itemStyle.color).toBe(UNKNOWN_CAUSE_COLOR)
    expect(option.series[0].data[0].itemStyle.color).not.toBe(UNKNOWN_CAUSE_COLOR)
  })

  it('空数组给出空数据而不是占位假数据', () => {
    const option = causeOption([]) as { series: Array<{ data: unknown[] }> }
    expect(option.series[0].data).toEqual([])
  })
})

describe('topKpOption', () => {
  it('按掌握度四档着色，null 走未评估灰', () => {
    const data: StatsTopKp[] = [
      { kp_id: 1, kp_name: '低', count: 2, mastery: 0.2 },
      { kp_id: 2, kp_name: '中', count: 1, mastery: 0.5 },
      { kp_id: 3, kp_name: '高', count: 1, mastery: 0.9 },
      { kp_id: 4, kp_name: '无', count: 1, mastery: null },
    ]
    const option = topKpOption(data) as {
      yAxis: { data: string[] }
      series: Array<{ data: Array<{ value: number; itemStyle: { color: string } }> }>
    }
    expect(option.yAxis.data).toEqual(['低', '中', '高', '无'])
    expect(option.series[0].data.map((item) => item.value)).toEqual([2, 1, 1, 1])
    expect(option.series[0].data.map((item) => item.itemStyle.color)).toEqual([
      '#e5484d',
      '#f0b429',
      '#22c55e',
      '#9aa4b2',
    ])
  })

  it('空数组不崩', () => {
    const option = topKpOption([]) as { yAxis: { data: string[] } }
    expect(option.yAxis.data).toEqual([])
  })
})

describe('trendOption', () => {
  const data: StatsTrendPoint[] = [
    { date: '2026-11-02', new_mistakes: 34, mastered: 0 },
    { date: '2026-11-03', new_mistakes: 0, mastered: 0 },
  ]

  it('补零后的数据直接成折线，日期只显示 MM-DD', () => {
    const option = trendOption(data) as {
      xAxis: { data: string[] }
      series: Array<{ name: string; data: number[] }>
    }
    expect(option.xAxis.data).toEqual(['11-02', '11-03'])
    expect(option.series[0]).toMatchObject({ data: [34, 0] })
  })

  it('已掌握全 0 时不画第二条线', () => {
    expect(hasMastered(data)).toBe(false)
    const option = trendOption(data) as { series: Array<{ name: string }> }
    expect(option.series).toHaveLength(1)
  })

  it('有已掌握时画累计线', () => {
    const withMastered: StatsTrendPoint[] = [
      { date: '2026-11-02', new_mistakes: 1, mastered: 2 },
    ]
    expect(hasMastered(withMastered)).toBe(true)
    const option = trendOption(withMastered) as { series: Array<{ name: string }> }
    expect(option.series).toHaveLength(2)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/stats/useStatsCharts.spec.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 写类型与 API**

创建 `web/src/types/stats.ts`：

```ts
/** S4-8 统计看板出参（docs/API.md §4.7）。 */
export type StatsRange = '7d' | '30d' | '90d'

export interface StatsRangeInfo {
  key: StatsRange
  from: string
  to: string
}

export interface StatsSummary {
  total: number
  pending: number
  corrected: number
  mastered: number
  analyzed: number
  with_kp: number
  mastery_rows: number
}

export interface StatsStatusCount {
  status: string
  count: number
}

export interface StatsCauseCount {
  cause_type: string
  count: number
}

export interface StatsTopKp {
  kp_id: number
  kp_name: string
  count: number
  mastery: number | null
}

export interface StatsTrendPoint {
  date: string
  new_mistakes: number
  mastered: number
}

export interface StatsOverview {
  range: StatsRangeInfo
  summary: StatsSummary
  by_status: StatsStatusCount[]
  by_cause: StatsCauseCount[]
  top_kps: StatsTopKp[]
  trend: StatsTrendPoint[]
}
```

创建 `web/src/api/stats.ts`：

```ts
/** S4-8 统计看板：只有一条聚合接口。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { StatsOverview, StatsRange } from '@/types/stats'

export async function fetchStatsOverview(range: StatsRange = '30d'): Promise<StatsOverview> {
  const resp = await http.get<ApiEnvelope<StatsOverview>>(`${API_PREFIX}/stats/overview`, {
    params: { range },
  })
  return resp.data.data
}
```

- [ ] **Step 4: 提炼掌握度取色**

创建 `web/src/utils/masteryColor.ts`：

```ts
/** 掌握度配色（S4-7 起统一口径）：图谱与统计看板共用，避免两处硬编码。 */
export const COLOR_UNRATED = '#9aa4b2'
export const COLOR_LOW = '#e5484d'
export const COLOR_MID = '#f0b429'
export const COLOR_HIGH = '#22c55e'

/** <0.4 红、0.4–0.7 黄、≥0.7 绿；null = 未评估（灰）。 */
export function masteryColor(mastery: number | null): string {
  if (mastery === null) return COLOR_UNRATED
  if (mastery < 0.4) return COLOR_LOW
  if (mastery < 0.7) return COLOR_MID
  return COLOR_HIGH
}

export function masteryLabel(mastery: number | null): string {
  return mastery === null ? '未评估' : `掌握度 ${mastery.toFixed(2)}`
}
```

`web/src/views/kp/useGraphData.ts`：删掉本地四色常量与两个函数体，改成 re-export 委托（保持既有 import 路径与测试断言不变）：

```ts
import {
  COLOR_HIGH,
  COLOR_LOW,
  COLOR_MID,
  COLOR_UNRATED,
  masteryColor,
  masteryLabel,
} from '@/utils/masteryColor'

export { COLOR_HIGH, COLOR_LOW, COLOR_MID, COLOR_UNRATED, masteryLabel }

/** 掌握度分档（S4-7）：实现见 utils/masteryColor，图谱侧继续用旧名字。 */
export function nodeColor(mastery: number | null): string {
  return masteryColor(mastery)
}
```

（`useGraphData.spec.ts` 里 `masteryLabel` 从 `./useGraphData` 导入仍然可用。）

- [ ] **Step 5: 写图表纯函数**

创建 `web/src/views/stats/useStatsCharts.ts`：

```ts
/**
 * 统计看板的纯函数层（S4-8）。
 *
 * 和 S4-6 的 useGraphData 同样的理由：jsdom 没有 canvas，页面级只能 mock ECharts；
 * 把「数据 → option」抽出来，补零、分档、空数组这些易错点才能被直接断言。
 */
import { masteryColor } from '@/utils/masteryColor'
import type {
  StatsCauseCount,
  StatsSummary,
  StatsTopKp,
  StatsTrendPoint,
} from '@/types/stats'

export const UNKNOWN_CAUSE_COLOR = '#9aa4b2'

const CAUSE_PALETTE = ['#e5484d', '#f0b429', '#3b82f6', '#8b5cf6', '#22c55e', '#f97316']

/** unknown 单独灰；其余按固定调色板取色，保证同名错因颜色稳定。 */
export function causeColor(causeType: string): string {
  if (causeType === 'unknown') return UNKNOWN_CAUSE_COLOR
  let hash = 0
  for (const char of causeType) hash = (hash * 31 + char.charCodeAt(0)) % 997
  return CAUSE_PALETTE[hash % CAUSE_PALETTE.length]
}

export function summaryCards(summary: StatsSummary): { label: string; value: number }[] {
  return [
    { label: '错题总数', value: summary.total },
    { label: '待订正', value: summary.pending },
    { label: '已订正', value: summary.corrected },
    { label: '已掌握', value: summary.mastered },
  ]
}

export function causeOption(data: StatsCauseCount[]): unknown {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条（{d}%）' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        data: data.map((item) => ({
          name: item.cause_type,
          value: item.count,
          itemStyle: { color: causeColor(item.cause_type) },
        })),
      },
    ],
  }
}

export function topKpOption(data: StatsTopKp[]): unknown {
  return {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: Array<{ name: string; value: number; dataIndex: number }>) => {
        const first = params[0]
        if (first === undefined) return ''
        const row = data[first.dataIndex]
        if (row === undefined) return ''
        const mastery = row.mastery === null ? '未评估' : row.mastery.toFixed(2)
        return `${row.kp_name}<br/>错题 ${row.count} 条 · 掌握度 ${mastery}`
      },
    },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: data.map((item) => item.kp_name), inverse: true },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        label: {
          show: true,
          position: 'right',
          formatter: (params: { dataIndex: number }) => {
            const row = data[params.dataIndex]
            if (row === undefined) return ''
            return row.mastery === null ? `${row.count}` : `${row.count} · ${row.mastery.toFixed(2)}`
          },
        },
        data: data.map((item) => ({
          value: item.count,
          itemStyle: { color: masteryColor(item.mastery) },
        })),
      },
    ],
  }
}

export function hasMastered(data: StatsTrendPoint[]): boolean {
  return data.some((point) => point.mastered > 0)
}

export function trendOption(data: StatsTrendPoint[]): unknown {
  const series: Array<Record<string, unknown>> = [
    {
      name: '新增错题',
      type: 'line',
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.12 },
      data: data.map((point) => point.new_mistakes),
    },
  ]
  if (hasMastered(data)) {
    series.push({
      name: '累计已掌握',
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { type: 'dashed' },
      data: data.map((point) => point.mastered),
    })
  }
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.map((point) => point.date.slice(5)),
    },
    yAxis: { type: 'value', minInterval: 1 },
    series,
  }
}
```

- [ ] **Step 6: 跑测试**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/stats/useStatsCharts.spec.ts src/views/kp/useGraphData.spec.ts`
Expected: stats `10 passed`；`useGraphData.spec.ts` 仍全绿（委托没改行为）

- [ ] **Step 7: 提交**

```bash
cd study-agent && git add web/src/types/stats.ts web/src/api/stats.ts web/src/utils/masteryColor.ts web/src/views/kp/useGraphData.ts web/src/views/stats/useStatsCharts.ts web/src/views/stats/useStatsCharts.spec.ts
git commit -m "feat(s4-8): 统计看板前端类型、API 与图表纯函数"
```

---

### Task 4: `/stats` 页面 + 路由导航 + 真机验收 + 文档 + tag

**Files:**
- Create: `web/src/views/stats/Stats.vue`
- Create: `web/src/views/stats/Stats.spec.ts`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/layouts/nav.ts`
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-051）、`README.md`
- Create: `.sdd/s4-8/acceptance-evidence.md`、`.sdd/s4-8/progress.md`

**Interfaces:**
- Consumes: `fetchStatsOverview`、`summaryCards/causeOption/topKpOption/trendOption/hasMastered`、`PageHeader`

- [ ] **Step 1: 写失败的页面测试**

创建 `web/src/views/stats/Stats.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { StatsOverview } from '@/types/stats'

import Stats from './Stats.vue'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
  }
  return { chart, init: vi.fn(() => chart), use: vi.fn() }
})

vi.mock('echarts/core', () => ({ use: charts.use, init: charts.init }))
vi.mock('echarts/charts', () => ({ PieChart: {}, BarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({ fetchStatsOverview: vi.fn() }))
vi.mock('@/api/stats', () => ({ fetchStatsOverview: api.fetchStatsOverview }))

function overview(overrides: Partial<StatsOverview> = {}): StatsOverview {
  return {
    range: { key: '30d', from: '2026-10-06', to: '2026-11-04' },
    summary: {
      total: 34,
      pending: 33,
      corrected: 1,
      mastered: 0,
      analyzed: 34,
      with_kp: 3,
      mastery_rows: 5,
    },
    by_status: [
      { status: '待订正', count: 33 },
      { status: '已订正', count: 1 },
      { status: '已掌握', count: 0 },
    ],
    by_cause: [
      { cause_type: '概念不清', count: 11 },
      { cause_type: 'unknown', count: 1 },
    ],
    top_kps: [{ kp_id: 197, kp_name: '同角三角函数基本关系', count: 1, mastery: 0.144 }],
    trend: [{ date: '2026-11-03', new_mistakes: 34, mastered: 0 }],
    ...overrides,
  }
}

function mountPage() {
  return mount(Stats, { global: { plugins: [ElementPlus] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchStatsOverview.mockResolvedValue(overview())
})

describe('Stats 页面', () => {
  it('首屏渲染四张摘要卡与解释性提示', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('错题总数')
    expect(text).toContain('34')
    expect(text).toContain('34 条')
    expect(text).toContain('3 条挂知识点')
    expect(text).toContain('其余 31 条错题没有关联知识点')
    expect(api.fetchStatsOverview).toHaveBeenCalledWith('30d')
  })

  it('切换窗口会重新请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="range-7d"]').trigger('click')
    await flushPromises()
    expect(api.fetchStatsOverview).toHaveBeenLastCalledWith('7d')
  })

  it('没有错题时给空态，不画假数据', async () => {
    api.fetchStatsOverview.mockResolvedValue(
      overview({
        summary: {
          total: 0,
          pending: 0,
          corrected: 0,
          mastered: 0,
          analyzed: 0,
          with_kp: 0,
          mastery_rows: 0,
        },
        by_status: [],
        by_cause: [],
        top_kps: [],
        trend: [],
      }),
    )
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('窗口内没有错题')
  })

  it('没有诊断时提示而不是空图', async () => {
    api.fetchStatsOverview.mockResolvedValue(overview({ by_cause: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有错因诊断')
  })

  it('没有挂知识点的错题时提示', async () => {
    api.fetchStatsOverview.mockResolvedValue(overview({ top_kps: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有错题挂上知识点')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/stats/Stats.spec.ts`
Expected: FAIL —— `Stats.vue` 不存在

- [ ] **Step 3: 写页面**

创建 `web/src/views/stats/Stats.vue`（`<script setup>` + 模板 + scoped 样式；三块画布各自一个 `ref`，图实例在 `onMounted` 里初始化，`onBeforeUnmount` 里 `dispose`）：

```vue
<script setup lang="ts">
/**
 * 错题统计看板（S4-8）。
 *
 * 页面只负责请求、range 切换与三块画布的 setOption；数据到 option 的映射全在
 * useStatsCharts 的纯函数里（jsdom 测不到 canvas，但能测 option）。
 */
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchStatsOverview } from '@/api/stats'
import PageHeader from '@/components/common/PageHeader.vue'
import type { StatsOverview, StatsRange } from '@/types/stats'

import {
  causeOption,
  hasMastered,
  summaryCards,
  topKpOption,
  trendOption,
} from './useStatsCharts'

echarts.use([
  PieChart,
  BarChart,
  LineChart,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  CanvasRenderer,
])

const RANGE_OPTIONS: { value: StatsRange; label: string }[] = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
]

const range = ref<StatsRange>('30d')
const data = ref<StatsOverview | null>(null)
const loading = ref(false)
const error = ref('')

const causeCanvas = ref<HTMLCanvasElement | null>(null)
const topKpCanvas = ref<HTMLCanvasElement | null>(null)
const trendCanvas = ref<HTMLCanvasElement | null>(null)
let causeChart: echarts.ECharts | null = null
let topKpChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const cards = computed(() => (data.value === null ? [] : summaryCards(data.value.summary)))
const missingKp = computed(() => {
  const current = data.value
  if (current === null) return 0
  return Math.max(0, current.summary.total - current.summary.with_kp)
})
const causeEmpty = computed(() => data.value !== null && data.value.by_cause.length === 0)
const topKpEmpty = computed(() => data.value !== null && data.value.top_kps.length === 0)
const totallyEmpty = computed(() => data.value !== null && data.value.summary.total === 0)
const masteredAllZero = computed(() => data.value !== null && !hasMastered(data.value.trend))

function render(): void {
  const current = data.value
  if (current === null) return
  causeChart?.setOption(causeOption(current.by_cause), true)
  topKpChart?.setOption(topKpOption(current.top_kps), true)
  trendChart?.setOption(trendOption(current.trend), true)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchStatsOverview(range.value)
    await nextTick()
    render()
  } catch {
    error.value = '统计数据加载失败，请重试'
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(range, load)

onMounted(async () => {
  await load()
  if (causeCanvas.value !== null) causeChart = echarts.init(causeCanvas.value)
  if (topKpCanvas.value !== null) topKpChart = echarts.init(topKpCanvas.value)
  if (trendCanvas.value !== null) trendChart = echarts.init(trendCanvas.value)
  render()
})

onBeforeUnmount(() => {
  causeChart?.dispose()
  topKpChart?.dispose()
  trendChart?.dispose()
  causeChart = null
  topKpChart = null
  trendChart = null
})
</script>

<template>
  <div class="stats-page">
    <PageHeader
      title="统计"
      description="本人错题的窗口汇总：状态分布、错因分布、知识点 TOP10（颜色=掌握度）与每日新增/累计已掌握趋势。"
    />

    <div class="stats-toolbar">
      <el-radio-group v-model="range" size="small">
        <el-radio-button
          v-for="item in RANGE_OPTIONS"
          :key="item.value"
          :value="item.value"
          :data-testid="`range-${item.value}`"
        >
          {{ item.label }}
        </el-radio-button>
      </el-radio-group>
      <span v-if="data !== null" class="stats-toolbar__range">
        {{ data.range.from }} ~ {{ data.range.to }}（UTC）
      </span>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" data-testid="stats-error" />
    <el-skeleton v-if="loading" :rows="4" animated />

    <template v-else-if="data !== null">
      <el-empty v-if="totallyEmpty" description="窗口内没有错题" data-testid="stats-empty" />

      <template v-else>
        <div class="stats-cards">
          <div v-for="card in cards" :key="card.label" class="stats-card">
            <div class="stats-card__value">{{ card.value }}</div>
            <div class="stats-card__label">{{ card.label }}</div>
          </div>
        </div>
        <p class="stats-note">
          {{ data.summary.total }} 条错题中 {{ data.summary.analyzed }} 条已诊断 ·
          {{ data.summary.with_kp }} 条挂知识点 · 掌握度 {{ data.summary.mastery_rows }} 个知识点有记录
        </p>

        <div class="stats-grid">
          <section class="stats-panel">
            <h3>错因分布</h3>
            <p v-if="causeEmpty" class="stats-panel__empty">还没有错因诊断</p>
            <div ref="causeCanvas" class="stats-canvas" data-testid="cause-chart" />
          </section>

          <section class="stats-panel">
            <h3>知识点 TOP10</h3>
            <p v-if="topKpEmpty" class="stats-panel__empty">还没有错题挂上知识点</p>
            <div ref="topKpCanvas" class="stats-canvas" data-testid="top-kp-chart" />
            <p v-if="missingKp > 0" class="stats-panel__empty">
              其余 {{ missingKp }} 条错题没有关联知识点，所以不出现在图上
            </p>
          </section>

          <section class="stats-panel stats-panel--wide">
            <h3>每日新增错题与累计已掌握</h3>
            <div ref="trendCanvas" class="stats-canvas" data-testid="trend-chart" />
            <p v-if="masteredAllZero" class="stats-panel__empty">窗口内暂无已掌握错题</p>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.stats-page { display: flex; flex-direction: column; gap: 16px; }
.stats-toolbar { display: flex; align-items: center; gap: 12px; }
.stats-toolbar__range { color: #667085; font-size: 12px; }
.stats-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.stats-card { padding: 16px; background: #fff; border: 1px solid #eaecf0; border-radius: 10px; }
.stats-card__value { font-size: 26px; font-weight: 600; color: #101828; }
.stats-card__label { margin-top: 4px; font-size: 12px; color: #667085; }
.stats-note { margin: 0; font-size: 12px; color: #667085; }
.stats-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.stats-panel { padding: 16px; background: #fff; border: 1px solid #eaecf0; border-radius: 10px; }
.stats-panel--wide { grid-column: 1 / -1; }
.stats-panel h3 { margin: 0 0 8px; font-size: 14px; color: #344054; }
.stats-panel__empty { margin: 8px 0 0; font-size: 12px; color: #98a2b3; }
.stats-canvas { width: 100%; height: 260px; }
</style>
```

- [ ] **Step 4: 路由与导航**

`web/src/router/index.ts`：在 `mistakes` 相关路由之后、`plan` 之前插入：

```ts
        {
          path: 'stats',
          name: 'stats',
          component: () => import('@/views/stats/Stats.vue'),
          meta: { title: '统计', nav: 'stats', roles: ['student'] },
        },
```

`web/src/layouts/nav.ts`：数组末尾追加

```ts
  { index: '09', label: '统计', name: 'stats', path: '/stats' },
```

（若 `MainLayout.spec.ts` 断言了导航项数量或列表，按实际新增项更新断言——这是真实的 UI 变更，不是为了让测试通过而改逻辑。）

- [ ] **Step 5: 跑前端测试 + 构建**

Run:

```bash
cd study-agent/web && npm run test:run -- --pool=threads src/views/stats/Stats.spec.ts
npm run test:run -- --pool=threads
npm run build
```

Expected: `Stats.spec.ts` 5 passed；全量 `236 passed / 41 files`（基线 226/39 + stats 10 条纯函数 + 5 条页面）；build 退出 0。

- [ ] **Step 6: 起服务真机验收**

```bash
# 后端
cd study-agent/backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8032
# 前端
cd study-agent/web && npm run dev
```

按 spec §7 六步跑（学生 `s43_accept_20261103` / `accept-pass-2026`），把每个数字抄进证据文件：

1. `GET /stats/overview` → `34 / 33 / 1 / 0 / 34 / 3 / 5`，`by_cause` 7 类合计 34，`top_kps` 5 条，`trend` 30 点只有 11-03 非零
2. 与 `GET /mistakes/stats` 交叉核对 total / by_cause / top_kps 一致
3. `range=7d` → 7 点；`range=90d` → 90 点
4. 教师 403；`range=abc` → 422/42200
5. `/stats` 页面三图渲染、range 切换、柱图下出现「其余 31 条错题…」
6. 空态：找空学生账号，**找不到就在证据里写「未验证」**，不编数据

任何一条对不上先停下来报告，不改验收口径。

- [ ] **Step 7: 写证据与文档**

- `.sdd/s4-8/acceptance-evidence.md`：环境、账号、spec §7 六条实测、交叉核对结果、未验证项
- `.sdd/s4-8/progress.md`：与 plan 的偏离（含 spec 里 SQL 条数从 5 补到 9 的原因）、坑、遗留
- `docs/PROGRESS.md`：S4-8 打勾、最近完成、S4-8 口径与实测数字、下一步 S5-1、阶段 4 完成说明
- `docs/DECISIONS.md`：D-051（新开接口不复用 `/mistakes/stats` 的理由、回算累计口径、UTC 分桶、TOP 柱少如实呈现、`mastery_values` 提炼）
- `README.md`：加「统计看板」一段（入口 `/stats`、三档窗口、数据限制）

- [ ] **Step 8: 全量回归**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent/web && npm run test:run -- --pool=threads && npm run build
```

Expected: 后端 `1202 passed, 1 warning`；前端 `236 passed / 41 files`；build 退出 0。

- [ ] **Step 9: 提交 + tag + ff-merge**

```bash
cd study-agent && git add backend web docs README.md
git commit -m "feat(s4-8): 统计看板页面、导航与文档同步"
git checkout main && git merge --ff-only feature/s4-8-dashboard && git branch -d feature/s4-8-dashboard
git tag -a m3-mistake-graph-done -m "阶段 4 收尾：错题诊断 + 知识图谱 + 掌握度 + 统计看板"
# 不 push（用户自己推，tag 用 git push --tags）
```

---

## 风险与回退

- `trendOption` 的 `formatter` 用了 ECharts 会传的参数对象；jsdom 里不会被调用，纯函数测试只断言 `data`/`series` 结构，**不测 formatter 文本**（避免测到 ECharts 内部约定）。
- `mastery_values` 提炼会动 `graph_service`：若 S4-6 测试因此变红，说明签名不一致，按原签名修正委托，不许改测试断言。
- `el-radio-button` 的 `value` prop 以仓库现有用法为准（`src/views/mistakes/MistakePickDialog.vue` 用的就是 `:value`），`data-testid` 打在按钮上。若 jsdom 里点击 label 没有触发 v-model（测试停在"没有重新请求"），改成 `wrapper.findAllComponents({ name: 'ElRadioButton' })[0].vm.$emit('update:modelValue', '7d')` 再 `flushPromises`——这是测试写法问题，不是页面 bug。
- 若 `trend` 只有 1 个点（`7d` 且当天无数据），ECharts 折线会退化成一个点——可接受，不额外补假点。
- tag 只在验收通过后打；若验收有未通过项，先不打 tag，如实报告。