# S5-6 学习报告（雷达 / 热力 / 趋势 + 周报）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `GET /reports/mastery` 的模块雷达/知识点 Treemap/多日趋势，以及 `POST /reports/weekly` 的严格数字校验 LLM 周报；不新增报告表，只扩 `llm_call_logs.scene` CHECK。

**Architecture:** `services/report_service.py` 负责窗口、模块均值、热力节点、趋势、周报统计和数字校验；`ai/report/weekly_report.py` 负责 Prompt 渲染、LLM 调用与重试；API 只做参数/权限/Envelope。雷达/热力是当前 `M_t` 快照，趋势按 UTC 日界补零；周报同步生成、不落库。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、PostgreSQL 16、Jinja2、pytest。

**Spec:** `docs/spec/s5-6-report-weekly.md`

## Global Constraints

- 只做后端；不改前端、不做 `/reports` 页面（S5-7）。
- 范围 `7d|30d|90d`，默认 `30d`；雷达/热力为当前快照，范围只影响趋势。
- 所有日界/补零用 **UTC**；与 S4-8 `/stats/overview` 一致，不复用 S5-5 本地日界。
- 不新增报告表；周报同步、不缓存、不落库；空数据返回 `generated_by="empty"`，不调 LLM。
- 新增 `llm_call_logs.scene='report'`，迁移 `0017_s5_6`；不加列、不改旧迁移。
- 周报数字校验：只允许使用输入 `stats` 中的数字 + 周期日期分量 + 天数；重试最多 2 次；失败 500/50000。
- 不编造「复习完成率 / 薄弱点变化」；`reviews_done` 只反映当前 `review_items.done_at` 快照。
- 所有查询显式 `user_id`；service 不 commit；路由/调用方统一提交。
- 新代码先照 `stats_service.py`/`mistake_analyzer.py` 锚点；不新增依赖。
- 外部 LLM 在 pytest 中必须 mock；测试不发起真实网络调用。
- 先改 `docs/API.md`/`docs/SCHEMA.md`，再写代码；每个任务先红后绿，完成即提交。

---

### Task 1: 契约、`report` scene 与迁移 `0017_s5_6`

**Files:**
- Modify: `docs/API.md` §9（替换 `GET /reports/mastery` 占位，新增 `POST /reports/weekly`）
- Modify: `docs/SCHEMA.md` §8.4（`llm_call_logs.scene` 值集补 `report`）
- Modify: `backend/app/models/enums.py:59-69`
- Create: `backend/alembic/versions/0017_s5_6.py`
- Modify: `backend/tests/test_answers_migration.py:61-64`
- Modify: `backend/tests/test_papers_migration.py:61-64`
- Modify: `backend/tests/test_review_migration.py:60-63`
- Test: `backend/tests/test_report_migration.py`

**Interfaces:**
- Consumes: `in_check()`、`LLMCallLog` 现有模型、迁移 head `0016_s5_5`
- Produces: `LLMCallScene.REPORT = "report"`；迁移 head `0017_s5_6`；API/SCHEMA 契约

- [ ] **Step 1: 先改契约文档**

把 `docs/API.md §9` 的占位内容替换为 spec §4.1/§4.2 的两段接口契约，至少包含：
- `GET /api/v1/reports/mastery`：入参 `range`、出参 `ReportOverviewOut` 的 JSON 示例、口径/错误码。
- `POST /api/v1/reports/weekly`：无请求体、同步、`generated_by=llm|empty`、`validation` 字段、500/50000 错误。
- 明确「UTC 日界」「雷达/热力当前快照」「reviews_done 当前快照」「数字校验失败不返回报告」。

在 `docs/SCHEMA.md §8.4` 的 `llm_call_logs.scene` 说明中追加 `report`，并注明由 `0017_s5_6` 扩展 CHECK。

- [ ] **Step 2: 写迁移/枚举契约测试（先红）**

创建 `backend/tests/test_report_migration.py`：

```python
"""S5-6 report scene 契约：枚举、CHECK、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.enums import LLMCallScene, in_check
from app.models.llm_call_log import LLMCallLog

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_llm_call_scene_has_report():
    assert LLMCallScene.REPORT.value == "report"
    assert "report" in in_check("scene", LLMCallScene)


def test_llm_call_log_check_includes_report():
    constraint = next(
        item
        for item in LLMCallLog.__table__.constraints
        if item.name == "ck_llm_call_logs_scene"
    )
    assert "report" in str(constraint.sqltext)


def test_migration_chain_head_is_s5_6():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0017_s5_6"
```

- [ ] **Step 3: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_migration.py -q
```
Expected: FAIL（`LLMCallScene.REPORT` 不存在，head 仍是 `0016_s5_5`）。

- [ ] **Step 4: 实现枚举与迁移**

`backend/app/models/enums.py` 的 `LLMCallScene` 末尾追加：

```python
    REPORT = "report"
```

创建 `backend/alembic/versions/0017_s5_6.py`：

```python
"""S5-6 学习报告：llm_call_logs.scene 增加 report。"""
from __future__ import annotations

from alembic import op

revision = "0017_s5_6"
down_revision = "0016_s5_5"
branch_labels = None
depends_on = None

SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent', 'report')"
)
OLD_SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent')"
)


def upgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", SCENE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", OLD_SCENE_CHECK)
```

把三个旧 head 测试的期望从 `0016_s5_5` 改为 `0017_s5_6`（函数名可改为 `..._is_s5_6`），不要删除测试。

- [ ] **Step 5: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_migration.py tests/test_answers_migration.py tests/test_papers_migration.py tests/test_review_migration.py -q
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd study-agent
git add docs/API.md docs/SCHEMA.md backend/app/models/enums.py backend/alembic/versions/0017_s5_6.py backend/tests/test_report_migration.py backend/tests/test_answers_migration.py backend/tests/test_papers_migration.py backend/tests/test_review_migration.py
git commit -m "feat(s5-6): report scene 与迁移 0017"
```

---

### Task 2: 出参 schema、UTC 窗口与趋势补零

**Files:**
- Create: `backend/app/schemas/report.py`
- Create: `backend/app/services/report_service.py`
- Test: `backend/tests/test_report_service.py`

**Interfaces:**
- Consumes: `stats_service.build_window/fill_days`、`InvalidParamError`
- Produces: `ReportRangeOut`、`ReportModuleOut`、`ReportHeatmapNodeOut`、`ReportSubjectOut`、`ReportTrendPointOut`、`ReportOverviewOut`、`WeeklyPeriodOut`、`WeeklyTotalsOut`、`WeeklyMasteryOut`、`WeeklyStatsOut`、`NumberValidationOut`、`WeeklyReportOut`；`report_service.build_window`、`fill_days`、`build_trend`

- [ ] **Step 1: 写窗口/趋势测试（先红）**

创建 `backend/tests/test_report_service.py`：

```python
"""S5-6 报告 service：窗口、趋势补零、模块/热力、周报统计、数字校验。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError
from app.services import report_service

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)


def test_build_window_30d_has_thirty_utc_days():
    window = report_service.build_window("30d", now=NOW)
    assert window.key == "30d"
    assert window.days == 30
    assert len(window.dates) == 30
    assert window.dates[0] == date(2026, 10, 16)
    assert window.dates[-1] == date(2026, 11, 14)
    assert window.start == datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    assert window.end == NOW


def test_build_window_rejects_unknown_range():
    with pytest.raises(InvalidParamError) as exc:
        report_service.build_window("365d", now=NOW)
    assert "365d" in str(exc.value)


def test_build_trend_fills_zero_and_computes_net():
    dates = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)]
    points = report_service.build_trend(
        dates,
        new_notes={date(2026, 11, 12): 2},
        reviews_done={date(2026, 11, 13): 1},
        new_mistakes={date(2026, 11, 13): 3},
        mastered_mistakes={date(2026, 11, 13): 1},
    )
    assert [(p.date, p.new_notes, p.reviews_done, p.new_mistakes,
             p.mastered_mistakes, p.mistakes_net) for p in points] == [
        (date(2026, 11, 12), 2, 0, 0, 0, 0),
        (date(2026, 11, 13), 0, 1, 3, 1, 2),
        (date(2026, 11, 14), 0, 0, 0, 0, 0),
    ]
```

- [ ] **Step 2: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: FAIL（`report_service`/schema 不存在）。

- [ ] **Step 3: 创建 schema**

创建 `backend/app/schemas/report.py`：

```python
"""S5-6 学习报告出参（API.md §9）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportRangeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    from_: date = Field(alias="from")
    to: date


class ReportModuleOut(BaseModel):
    kp_id: int
    kp_name: str
    exam_weight: float | None = None
    kp_count: int
    assessed_count: int
    mastery: float | None = None


class ReportHeatmapNodeOut(BaseModel):
    kp_id: int
    kp_name: str
    parent_id: int | None = None
    level: int
    exam_weight: float | None = None
    mastery: float | None = None
    mastery_t: float | None = None
    color_value: float | None = None
    assessed: bool


class ReportSubjectOut(BaseModel):
    subject_id: int
    subject_name: str
    modules: list[ReportModuleOut]
    heatmap: list[ReportHeatmapNodeOut]


class ReportTrendPointOut(BaseModel):
    date: date
    new_notes: int
    reviews_done: int
    new_mistakes: int
    mastered_mistakes: int
    mistakes_net: int


class ReportOverviewOut(BaseModel):
    range: ReportRangeOut
    subjects: list[ReportSubjectOut]
    trend: list[ReportTrendPointOut]


class WeeklyPeriodOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    days: int


class WeeklyTotalsOut(BaseModel):
    new_notes: int
    reviews_done: int
    new_mistakes: int
    mastered_mistakes: int
    mistakes_net: int


class WeeklyWeakModuleOut(BaseModel):
    subject_id: int
    kp_id: int
    kp_name: str
    mastery: float


class WeeklyWeakKpOut(BaseModel):
    subject_id: int
    kp_id: int
    kp_name: str
    level: int
    mastery: float


class WeeklyMasteryOut(BaseModel):
    assessed_kp_count: int
    avg_mastery: float | None = None
    weak_modules: list[WeeklyWeakModuleOut]
    weak_kps: list[WeeklyWeakKpOut]


class WeeklyStatsOut(BaseModel):
    totals: WeeklyTotalsOut
    active_days: int
    mastery: WeeklyMasteryOut
    trend: list[ReportTrendPointOut]


class NumberValidationOut(BaseModel):
    ok: bool
    attempts: int
    checked_numbers: list[str]
    invalid_numbers: list[str]


class WeeklyReportOut(BaseModel):
    period: WeeklyPeriodOut
    generated_by: Literal["llm", "empty"]
    report_md: str
    stats: WeeklyStatsOut
    validation: NumberValidationOut
```

- [ ] **Step 4: 写 service 的窗口/趋势最小实现**

创建 `backend/app/services/report_service.py`：

```python
"""S5-6 学习报告：窗口聚合、模块雷达、热力节点、趋势与周报统计。

纯函数与 DB 用例分开；本模块不 commit，由路由/调用方提交。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone

from app.schemas.report import ReportRangeOut, ReportTrendPointOut
from app.services import stats_service

RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"

Window = stats_service.Window


def build_window(range_key: str, *, now: datetime | None = None) -> Window:
    return stats_service.build_window(range_key, now=now)


def fill_days(rows: Mapping[date, int], dates: Sequence[date]) -> list[tuple[date, int]]:
    return stats_service.fill_days(rows, dates)


def build_trend(
    dates: Sequence[date],
    *,
    new_notes: Mapping[date, int],
    reviews_done: Mapping[date, int],
    new_mistakes: Mapping[date, int],
    mastered_mistakes: Mapping[date, int],
) -> list[ReportTrendPointOut]:
    points: list[ReportTrendPointOut] = []
    for day in dates:
        nn = int(new_notes.get(day, 0))
        rd = int(reviews_done.get(day, 0))
        nm = int(new_mistakes.get(day, 0))
        mm = int(mastered_mistakes.get(day, 0))
        points.append(
            ReportTrendPointOut(
                date=day,
                new_notes=nn,
                reviews_done=rd,
                new_mistakes=nm,
                mastered_mistakes=mm,
                mistakes_net=nm - mm,
            )
        )
    return points
```

- [ ] **Step 5: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: 3 tests PASS。

- [ ] **Step 6: 提交**

```bash
cd study-agent
git add backend/app/schemas/report.py backend/app/services/report_service.py backend/tests/test_report_service.py
git commit -m "feat(s5-6): 报告 schema 与 UTC 趋势补零"
```

---

### Task 3: 模块雷达、热力节点与 `GET` 聚合 service

**Files:**
- Modify: `backend/app/services/report_service.py`
- Modify: `backend/tests/test_report_service.py`

**Interfaces:**
- Consumes: `KnowledgePoint`、`Subject`、`Mastery`、`Note`、`ReviewItem`、`Mistake`、`mastery_service.decayed_mastery`
- Produces: `KpNode`、`build_subjects(nodes, subjects, mastery_raw, mastery_t)`、`get_overview(session, *, user_id, range_key=..., now=None)`

- [ ] **Step 1: 写模块/热力/GET 测试（先红）**

在 `tests/test_report_service.py` 追加：

```python
from app.services.report_service import KpNode, build_subjects, get_overview


def _nodes():
    return [
        KpNode(115, 7, None, "集合", 2, 0.8),
        KpNode(200, 7, 115, "集合运算", 3, 0.5),
        KpNode(201, 7, 200, "交集", 4, 0.3),
        KpNode(116, 7, None, "函数", 2, 1.0),
    ]


def test_build_subjects_radar_average_and_null():
    out = build_subjects(
        _nodes(),
        [(7, "高中数学")],
        mastery_raw={200: 0.6},
        mastery_t={200: 0.5},
    )
    assert len(out) == 1
    assert [m.kp_id for m in out[0].modules] == [115, 116]
    first = out[0].modules[0]
    assert (first.kp_count, first.assessed_count, first.mastery) == (3, 1, 0.5)
    assert out[0].modules[1].mastery is None
    assert out[0].modules[1].assessed_count == 0


def test_build_subjects_heatmap_parent_color_and_null():
    out = build_subjects(
        _nodes(),
        [(7, "高中数学")],
        mastery_raw={200: 0.6},
        mastery_t={200: 0.5},
    )
    by_id = {node.kp_id: node for node in out[0].heatmap}
    assert by_id[115].parent_id is None
    assert by_id[200].parent_id == 115
    assert by_id[201].parent_id == 200
    assert by_id[200].color_value == 0.5
    assert by_id[201].mastery is None
    assert by_id[201].color_value is None
    assert by_id[201].assessed is False


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeReportSession:
    """按 SQL 表名回放数据库行；不执行 WHERE。"""

    def __init__(self, *, nodes, subjects, mastery, notes=(), reviews=(),
                 mistakes=(), mastered=()):
        self.nodes = nodes
        self.subjects = subjects
        self.mastery = mastery
        self.notes = notes
        self.reviews = reviews
        self.mistakes = mistakes
        self.mastered = mastered
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "knowledge_points" in sql:
            return _Rows(self.nodes)
        if "subjects" in sql:
            return _Rows(self.subjects)
        if "mastery" in sql:
            return _Rows(self.mastery)
        if "review_items" in sql:
            return _Rows(self.reviews)
        if "notes" in sql:
            return _Rows(self.notes)
        if "last_review_at" in sql:
            return _Rows(self.mastered)
        if "mistakes" in sql:
            return _Rows(self.mistakes)
        raise AssertionError(f"未分派的查询：{sql}")


def test_get_overview_builds_trend_and_filters_user():
    from decimal import Decimal

    session = FakeReportSession(
        nodes=[
            (115, 7, None, "集合", 2, Decimal("0.8")),
            (200, 7, 115, "集合运算", 3, Decimal("0.5")),
        ],
        subjects=[(7, "高中数学")],
        mastery=[(200, Decimal("0.6"), Decimal("2"), NOW)],
        notes=[(date(2026, 11, 12), 2)],
        reviews=[(date(2026, 11, 12), 1)],
        mistakes=[(date(2026, 11, 13), 3)],
        mastered=[(date(2026, 11, 13), 1)],
    )
    out = get_overview(session, user_id=50, range_key="7d", now=NOW)
    assert out.range.key == "7d"
    assert len(out.trend) == 7
    assert out.trend[-2].date == date(2026, 11, 13)
    assert out.trend[-2].new_mistakes == 3
    assert out.trend[-2].mastered_mistakes == 1
    assert out.subjects[0].modules[0].mastery == 0.6
    compiled = " || ".join(
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        for stmt in session.statements
    )
    assert "notes.user_id = 50" in compiled
    assert "review_items.user_id = 50" in compiled
    assert "mistakes.user_id = 50" in compiled
    assert "mastery.user_id = 50" in compiled
```

- [ ] **Step 2: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: FAIL（`KpNode`/`build_subjects`/`get_overview` 不存在）。

- [ ] **Step 3: 加节点/聚合/查询实现**

在 `report_service.py` 追加 imports 与代码：

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, func, literal_column, select
from sqlalchemy.orm import Session

from app.models.enums import MistakeStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.note import Note
from app.models.review_item import ReviewItem
from app.models.subject import Subject
from app.schemas.report import (
    ReportHeatmapNodeOut,
    ReportModuleOut,
    ReportOverviewOut,
    ReportSubjectOut,
)
from app.services import mastery_service


@dataclass(frozen=True, slots=True)
class KpNode:
    kp_id: int
    subject_id: int
    parent_id: int | None
    name: str
    level: int
    exam_weight: float | None = None


def _utc_day(column: Any) -> Any:
    return func.date_trunc(literal_column("'day'"), column).cast(Date)


def _module_of(node: KpNode, by_id: dict[int, KpNode]) -> int | None:
    current: KpNode | None = node
    while current is not None and current.level > 2:
        current = by_id.get(current.parent_id) if current.parent_id else None
    return current.kp_id if current is not None and current.level == 2 else None


def build_subjects(
    nodes: Sequence[KpNode],
    subjects: Sequence[tuple[int, str]],
    *,
    mastery_raw: Mapping[int, float],
    mastery_t: Mapping[int, float],
) -> list[ReportSubjectOut]:
    by_id = {node.kp_id: node for node in nodes}
    module_counts: dict[int, list[int]] = {}
    module_sums: dict[int, float] = {}
    heatmap_by_subject: dict[int, list[ReportHeatmapNodeOut]] = {}

    for node in nodes:
        module_id = _module_of(node, by_id)
        if module_id is None:
            continue
        counts = module_counts.setdefault(module_id, [0, 0])
        counts[0] += 1
        if node.kp_id in mastery_t:
            counts[1] += 1
            module_sums[module_id] = module_sums.get(module_id, 0.0) + mastery_t[node.kp_id]
        heatmap_by_subject.setdefault(node.subject_id, []).append(
            ReportHeatmapNodeOut(
                kp_id=node.kp_id,
                kp_name=node.name,
                parent_id=None if node.level == 2 else node.parent_id,
                level=node.level,
                exam_weight=node.exam_weight,
                mastery=mastery_raw.get(node.kp_id),
                mastery_t=mastery_t.get(node.kp_id),
                color_value=(
                    round(1.0 - mastery_t[node.kp_id], 3)
                    if node.kp_id in mastery_t
                    else None
                ),
                assessed=node.kp_id in mastery_t,
            )
        )

    modules_by_subject: dict[int, list[ReportModuleOut]] = {}
    for node in nodes:
        if node.level != 2:
            continue
        total, assessed = module_counts.get(node.kp_id, [0, 0])
        modules_by_subject.setdefault(node.subject_id, []).append(
            ReportModuleOut(
                kp_id=node.kp_id,
                kp_name=node.name,
                exam_weight=node.exam_weight,
                kp_count=total,
                assessed_count=assessed,
                mastery=(
                    round(module_sums[node.kp_id] / assessed, 3)
                    if assessed
                    else None
                ),
            )
        )

    result: list[ReportSubjectOut] = []
    for subject_id, subject_name in sorted(subjects):
        modules = sorted(modules_by_subject.get(subject_id, []), key=lambda item: item.kp_id)
        heatmap = sorted(
            heatmap_by_subject.get(subject_id, []),
            key=lambda item: (item.level, item.kp_id),
        )
        if modules:
            result.append(
                ReportSubjectOut(
                    subject_id=subject_id,
                    subject_name=subject_name,
                    modules=modules,
                    heatmap=heatmap,
                )
            )
    return result


def _load_nodes(session: Session) -> list[KpNode]:
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.subject_id,
            KnowledgePoint.parent_id,
            KnowledgePoint.name,
            KnowledgePoint.level,
            KnowledgePoint.exam_weight,
        )
        .where(KnowledgePoint.level >= 2, KnowledgePoint.level <= 4)
        .order_by(KnowledgePoint.level.asc(), KnowledgePoint.id.asc())
    ).all()
    return [
        KpNode(
            kp_id=int(kp_id),
            subject_id=int(subject_id),
            parent_id=int(parent_id) if parent_id is not None else None,
            name=name,
            level=int(level),
            exam_weight=float(weight) if weight is not None else None,
        )
        for kp_id, subject_id, parent_id, name, level, weight in rows
    ]


def _load_mastery(session: Session, *, user_id: int) -> list[tuple]:
    return session.execute(
        select(
            Mastery.kp_id,
            Mastery.mastery,
            Mastery.stability,
            Mastery.last_practice_at,
        ).where(Mastery.user_id == user_id)
    ).all()


def _mastery_maps(rows: Sequence[tuple], *, now: datetime) -> tuple[dict[int, float], dict[int, float]]:
    raw: dict[int, float] = {}
    effective: dict[int, float] = {}
    for kp_id, mastery, stability, last_practice_at in rows:
        days = 0.0
        if last_practice_at is not None:
            days = max(0.0, (now - last_practice_at).total_seconds() / 86400.0)
        raw[int(kp_id)] = float(mastery)
        effective[int(kp_id)] = mastery_service.decayed_mastery(
            float(mastery), float(stability), days=days
        )
    return raw, effective


def _daily(session: Session, statement: Any) -> dict[date, int]:
    return {day: int(count) for day, count in session.execute(statement).all()}


def _load_trend(
    session: Session, *, user_id: int, window: Window
) -> list[ReportTrendPointOut]:
    notes = _daily(
        session,
        select(_utc_day(Note.created_at), func.count())
        .where(
            Note.user_id == user_id,
            Note.deleted_at.is_(None),
            Note.created_at >= window.start,
            Note.created_at <= window.end,
        )
        .group_by(_utc_day(Note.created_at)),
    )
    reviews = _daily(
        session,
        select(_utc_day(ReviewItem.done_at), func.count())
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.done_at.is_not(None),
            ReviewItem.done_at >= window.start,
            ReviewItem.done_at <= window.end,
        )
        .group_by(_utc_day(ReviewItem.done_at)),
    )
    mistakes = _daily(
        session,
        select(_utc_day(Mistake.created_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.created_at >= window.start,
            Mistake.created_at <= window.end,
        )
        .group_by(_utc_day(Mistake.created_at)),
    )
    mastered = _daily(
        session,
        select(_utc_day(Mistake.last_review_at), func.count())
        .where(
            Mistake.user_id == user_id,
            Mistake.status == MistakeStatus.MASTERED.value,
            Mistake.last_review_at.is_not(None),
            Mistake.last_review_at >= window.start,
            Mistake.last_review_at <= window.end,
        )
        .group_by(_utc_day(Mistake.last_review_at)),
    )
    return build_trend(
        window.dates,
        new_notes=notes,
        reviews_done=reviews,
        new_mistakes=mistakes,
        mastered_mistakes=mastered,
    )


def get_overview(
    session: Session,
    *,
    user_id: int,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> ReportOverviewOut:
    window = build_window(range_key, now=now)
    moment = window.end
    nodes = _load_nodes(session)
    subject_ids = sorted({node.subject_id for node in nodes})
    subject_rows = (
        session.execute(
            select(Subject.id, Subject.name)
            .where(Subject.id.in_(subject_ids))
            .order_by(Subject.id.asc())
        ).all()
        if subject_ids
        else []
    )
    subjects = [(int(sid), name) for sid, name in subject_rows]
    raw, effective = _mastery_maps(_load_mastery(session, user_id=user_id), now=moment)
    return ReportOverviewOut(
        range=ReportRangeOut(key=window.key, from_=window.dates[0], to=window.dates[-1]),
        subjects=build_subjects(nodes, subjects, mastery_raw=raw, mastery_t=effective),
        trend=_load_trend(session, user_id=user_id, window=window),
    )
```

注意：`_mastery_maps` 的 `NOW` 必须是从 `window.end` 传入；测试中的 `mastery.last_practice_at=NOW` 时 `M_t=0.6`。`Decimal` import 只用于类型/测试，若 lint 不用可删。

- [ ] **Step 4: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/report_service.py backend/tests/test_report_service.py
git commit -m "feat(s5-6): 模块雷达、热力节点与 GET 聚合"
```

---

### Task 4: 周报统计与数字校验纯函数

**Files:**
- Modify: `backend/app/services/report_service.py`
- Modify: `backend/tests/test_report_service.py`

**Interfaces:**
- Consumes: `_ReportContext`（Task 3 的查询）、`ReportOverviewOut`
- Produces: `NumberValidation`、`extract_numbers(text)`、`allowed_numbers(stats)`、`validate_numbers(text, stats)`、`build_weekly_stats(session, *, user_id, now=None)`、`EMPTY_REPORT_MD`

- [ ] **Step 1: 写数字校验/周报统计测试（先红）**

在 `tests/test_report_service.py` 追加：

```python
from app.services.report_service import (
    EMPTY_REPORT_MD,
    NumberValidation,
    allowed_numbers,
    build_weekly_stats,
    extract_numbers,
    validate_numbers,
)


def test_extract_numbers_ignores_markdown_list_markers():
    assert extract_numbers("1. 本周新增 3 条\n2) 复习 0 次") == ["3", "0"]


def test_extract_numbers_keeps_negative_and_decimal():
    assert extract_numbers("净增 -2，掌握度 0.351，日期 2026-11-14") == [
        "-2",
        "0.351",
        "2026",
        "11",
        "14",
    ]


def test_validate_numbers_allows_stats_and_date_parts():
    stats = {
        "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
        "totals": {"new_notes": 3, "mistakes_net": -2},
        "mastery": {"avg_mastery": 0.351},
    }
    result = validate_numbers("2026-11-14 新增 3 条，净增 -2，掌握度 0.351。", stats)
    assert result.ok is True
    assert result.invalid_numbers == []
    assert "3" in result.checked_numbers


def test_validate_numbers_rejects_invented_number():
    stats = {
        "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
        "totals": {"new_notes": 3},
    }
    result = validate_numbers("本周新增 999 条。", stats)
    assert result.ok is False
    assert result.invalid_numbers == ["999"]


def test_validate_numbers_rejects_report_without_numbers():
    result = validate_numbers("本周学习很认真。", {"totals": {"new_notes": 0}})
    assert result.ok is False


def test_allowed_numbers_includes_nested_values_and_dates():
    values = allowed_numbers(
        {"period": {"from": "2026-11-08", "days": 7}, "totals": {"new_notes": 3}}
    )
    assert {str(value) for value in values} >= {"2026", "11", "8", "7", "3"}


def test_build_weekly_stats_sums_and_weak_points():
    from decimal import Decimal

    session = FakeReportSession(
        nodes=[
            (115, 7, None, "集合", 2, Decimal("0.8")),
            (200, 7, 115, "集合运算", 3, Decimal("0.5")),
        ],
        subjects=[(7, "高中数学")],
        mastery=[(200, Decimal("0.6"), Decimal("2"), NOW)],
        notes=[(date(2026, 11, 12), 2)],
        reviews=[(date(2026, 11, 13), 1)],
        mistakes=[(date(2026, 11, 13), 3)],
        mastered=[],
    )
    out = build_weekly_stats(session, user_id=50, now=NOW)
    assert out.totals.new_notes == 2
    assert out.totals.reviews_done == 1
    assert out.totals.new_mistakes == 3
    assert out.totals.mistakes_net == 3
    assert out.active_days == 2
    assert out.mastery.assessed_kp_count == 1
    assert out.mastery.weak_modules[0].mastery == 0.6
    assert out.mastery.weak_kps[0].kp_id == 200
    assert len(out.trend) == 7
```

- [ ] **Step 2: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: FAIL（新符号不存在）。

- [ ] **Step 3: 实现统计与校验**

在 `report_service.py` 追加 imports：

```python
import re
from decimal import Decimal, InvalidOperation

from app.schemas.report import (
    NumberValidationOut,
    WeeklyMasteryOut,
    WeeklyPeriodOut,
    WeeklyReportOut,
    WeeklyStatsOut,
    WeeklyTotalsOut,
    WeeklyWeakKpOut,
    WeeklyWeakModuleOut,
)
```

追加代码：

```python
EMPTY_REPORT_MD = "本周暂无学习记录，先完成一次练习或复习再来查看周报。"
_NUMBER_RE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
_LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
WEAK_MODULE_LIMIT = 3
WEAK_KP_LIMIT = 5


@dataclass(frozen=True, slots=True)
class NumberValidation:
    checked_numbers: list[str]
    invalid_numbers: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.checked_numbers) and not self.invalid_numbers


def extract_numbers(text: str) -> list[str]:
    cleaned = _LIST_MARKER_RE.sub("", text)
    result: list[str] = []
    seen: set[str] = set()
    for token in _NUMBER_RE.findall(cleaned):
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _add_allowed(value: object, allowed: set[Decimal]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        allowed.add(Decimal(str(value)))
        return
    if isinstance(value, str):
        for match in _DATE_RE.finditer(value):
            for part in match.groups():
                allowed.add(Decimal(str(int(part))))
        return
    if isinstance(value, dict):
        for item in value.values():
            _add_allowed(item, allowed)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _add_allowed(item, allowed)


def allowed_numbers(stats: Mapping[str, object]) -> set[Decimal]:
    allowed: set[Decimal] = set()
    _add_allowed(stats, allowed)
    period = stats.get("period")
    if isinstance(period, dict):
        days = period.get("days")
        if isinstance(days, int):
            allowed.add(Decimal(days))
    return allowed


def _as_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def validate_numbers(text: str, stats: Mapping[str, object]) -> NumberValidation:
    checked = extract_numbers(text)
    allowed = allowed_numbers(stats)
    invalid: list[str] = []
    for token in checked:
        value = _as_decimal(token)
        if value is None or value not in allowed:
            invalid.append(token)
    return NumberValidation(checked_numbers=checked, invalid_numbers=invalid)


@dataclass(frozen=True, slots=True)
class _ReportContext:
    overview: ReportOverviewOut
    mastery_rows: list[tuple]


def _context(
    session: Session,
    *,
    user_id: int,
    range_key: str,
    now: datetime | None,
) -> _ReportContext:
    window = build_window(range_key, now=now)
    moment = window.end
    nodes = _load_nodes(session)
    subject_ids = sorted({node.subject_id for node in nodes})
    subject_rows = (
        session.execute(
            select(Subject.id, Subject.name)
            .where(Subject.id.in_(subject_ids))
            .order_by(Subject.id.asc())
        ).all()
        if subject_ids
        else []
    )
    mastery_rows = _load_mastery(session, user_id=user_id)
    raw, effective = _mastery_maps(mastery_rows, now=moment)
    overview = ReportOverviewOut(
        range=ReportRangeOut(key=window.key, from_=window.dates[0], to=window.dates[-1]),
        subjects=build_subjects(
            nodes, [(int(sid), name) for sid, name in subject_rows],
            mastery_raw=raw, mastery_t=effective,
        ),
        trend=_load_trend(session, user_id=user_id, window=window),
    )
    return _ReportContext(overview=overview, mastery_rows=mastery_rows)


def get_overview(
    session: Session,
    *,
    user_id: int,
    range_key: str = DEFAULT_RANGE,
    now: datetime | None = None,
) -> ReportOverviewOut:
    return _context(
        session, user_id=user_id, range_key=range_key, now=now
    ).overview
```

把 Task 3 的 `get_overview` 实现替换成上面的薄包装（避免重复查询逻辑）。

继续实现周报统计：

```python
def _weekly_stats(context: _ReportContext) -> WeeklyStatsOut:
    trend = context.overview.trend
    totals = WeeklyTotalsOut(
        new_notes=sum(point.new_notes for point in trend),
        reviews_done=sum(point.reviews_done for point in trend),
        new_mistakes=sum(point.new_mistakes for point in trend),
        mastered_mistakes=sum(point.mastered_mistakes for point in trend),
        mistakes_net=sum(point.mistakes_net for point in trend),
    )
    active_days = sum(
        1
        for point in trend
        if point.new_notes + point.reviews_done + point.new_mistakes
        + point.mastered_mistakes
        > 0
    )
    raw, effective = _mastery_maps(context.mastery_rows, now=datetime.now(timezone.utc))

    weak_modules: list[WeeklyWeakModuleOut] = []
    weak_kps: list[WeeklyWeakKpOut] = []
    for subject in context.overview.subjects:
        for module in subject.modules:
            if module.mastery is not None:
                weak_modules.append(
                    WeeklyWeakModuleOut(
                        subject_id=subject.subject_id,
                        kp_id=module.kp_id,
                        kp_name=module.kp_name,
                        mastery=module.mastery,
                    )
                )
        for node in subject.heatmap:
            if node.mastery_t is not None:
                weak_kps.append(
                    WeeklyWeakKpOut(
                        subject_id=subject.subject_id,
                        kp_id=node.kp_id,
                        kp_name=node.kp_name,
                        level=node.level,
                        mastery=node.mastery_t,
                    )
                )
    weak_modules.sort(key=lambda item: (item.mastery, item.kp_id))
    weak_kps.sort(key=lambda item: (item.mastery, item.kp_id))
    avg = (
        round(sum(effective.values()) / len(effective), 3)
        if effective
        else None
    )
    return WeeklyStatsOut(
        totals=totals,
        active_days=active_days,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=len(context.mastery_rows),
            avg_mastery=avg,
            weak_modules=weak_modules[:WEAK_MODULE_LIMIT],
            weak_kps=weak_kps[:WEAK_KP_LIMIT],
        ),
        trend=trend,
    )


def build_weekly_stats(
    session: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> WeeklyStatsOut:
    moment = now or datetime.now(timezone.utc)
    return _weekly_stats(
        _context(session, user_id=user_id, range_key="7d", now=moment)
    )
```

注意 `_weekly_stats` 里的 `datetime.now(timezone.utc)` 会让测试中 `NOW` 与当前时间不一致，导致 `M_t` 变化。改为 `_weekly_stats(context, *, now)`，由 `build_weekly_stats` 传 `moment`；测试用 `NOW`。这是必须的实现细节：

```python
def _weekly_stats(context: _ReportContext, *, now: datetime) -> WeeklyStatsOut:
    ...
    _raw, effective = _mastery_maps(context.mastery_rows, now=now)
```

`build_weekly_stats` 调 `_weekly_stats(context, now=moment)`。`raw` 未使用时可写成 `_raw, effective`。

- [ ] **Step 4: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py -q
```
Expected: 全部 PASS（含 Task 3 的 GET 测试）。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/report_service.py backend/tests/test_report_service.py
git commit -m "feat(s5-6): 周报统计与数字校验"
```

---

### Task 5: 周报 Prompt、LLM 适配器与生成用例

**Files:**
- Create: `backend/app/ai/report/__init__.py`
- Create: `backend/app/ai/report/weekly_report.py`
- Create: `backend/app/ai/prompts/weekly_report_v1.md`
- Modify: `backend/app/services/report_service.py`
- Test: `backend/tests/test_weekly_report.py`

**Interfaces:**
- Consumes: `LLMClient/LLMMessage/LLMError/get_llm_client`、Jinja2、`validate_numbers`
- Produces: `WeeklyReportContext`、`WeeklyReportResult`、`WeeklyReportError`、`render_prompt(context)`、`generate_weekly_report(context, *, validator, llm_client=None, max_retries=2)`；`report_service.ReportGenerationError`、`generate_weekly(session, *, user_id, now=None)`

- [ ] **Step 1: 写 Prompt/适配器/service 测试（先红）**

创建 `backend/tests/test_weekly_report.py`：

```python
"""S5-6 周报：Prompt 渲染、数字校验重试、失败包裹、空数据分支。"""
from __future__ import annotations

import pytest

from app.ai.llm import LLMClient, LLMError, LLMMessage, LLMResponse
from app.ai.report import weekly_report
from app.schemas.report import (
    NumberValidationOut,
    WeeklyMasteryOut,
    WeeklyPeriodOut,
    WeeklyReportOut,
    WeeklyStatsOut,
    WeeklyTotalsOut,
)
from app.services import report_service


STATS = {"period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
         "totals": {"new_notes": 3}}


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str]) -> None:
        super().__init__(model="fake-weekly")
        self.texts = texts
        self.calls: list[list[LLMMessage]] = []
        self.scenes: list[str] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append(list(messages))
        self.scenes.append(scene)
        return LLMResponse(text=self.texts.pop(0), model=self.model, total_tokens=10)


def _validator(text: str):
    tokens = report_service.extract_numbers(text)
    invalid = [token for token in tokens if token not in {"3", "2026", "11", "8", "14", "7"}]
    return tokens, invalid


def test_render_prompt_includes_stats_and_number_rule():
    context = weekly_report.WeeklyReportContext(stats=STATS)
    prompt = weekly_report.render_prompt(context)
    assert "new_notes" in prompt
    assert "只能使用" in prompt
    assert "2026-11-08" in prompt


def test_generate_weekly_report_retries_after_invalid_number():
    llm = FakeLLM(["本周新增 999 条。", "本周新增 3 条。"])
    result = weekly_report.generate_weekly_report(
        weekly_report.WeeklyReportContext(stats=STATS),
        validator=_validator,
        llm_client=llm,
    )
    assert result.text == "本周新增 3 条。"
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert llm.scenes == ["report", "report"]
    assert "999" in llm.calls[1][-1].content
    assert result.invalid_numbers == []


def test_generate_weekly_report_raises_after_retries_exhausted():
    llm = FakeLLM(["999", "999", "999"])
    with pytest.raises(weekly_report.WeeklyReportError):
        weekly_report.generate_weekly_report(
            weekly_report.WeeklyReportContext(stats=STATS),
            validator=_validator,
            llm_client=llm,
        )
    assert len(llm.calls) == 3


def test_generate_weekly_report_wraps_llm_error():
    class BrokenLLM(LLMClient):
        def __init__(self):
            super().__init__(model="broken")

        def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
            raise LLMError("network down")

    with pytest.raises(weekly_report.WeeklyReportError):
        weekly_report.generate_weekly_report(
            weekly_report.WeeklyReportContext(stats=STATS),
            validator=_validator,
            llm_client=BrokenLLM(),
        )


def test_generate_weekly_empty_returns_without_llm(monkeypatch):
    empty = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=0, reviews_done=0, new_mistakes=0,
            mastered_mistakes=0, mistakes_net=0,
        ),
        active_days=0,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0, avg_mastery=None,
            weak_modules=[], weak_kps=[],
        ),
        trend=[],
    )
    monkeypatch.setattr(report_service, "build_weekly_stats", lambda *a, **k: empty)
    out = report_service.generate_weekly(session=object(), user_id=62)
    assert out.generated_by == "empty"
    assert out.report_md == report_service.EMPTY_REPORT_MD
    assert out.validation == NumberValidationOut(
        ok=True, attempts=0, checked_numbers=[], invalid_numbers=[]
    )


def test_generate_weekly_uses_adapter(monkeypatch):
    stats = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=3, reviews_done=0, new_mistakes=0,
            mastered_mistakes=0, mistakes_net=0,
        ),
        active_days=1,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0, avg_mastery=None,
            weak_modules=[], weak_kps=[],
        ),
        trend=[],
    )
    monkeypatch.setattr(report_service, "build_weekly_stats", lambda *a, **k: stats)
    monkeypatch.setattr(
        weekly_report,
        "generate_weekly_report",
        lambda context, *, validator, llm_client=None: weekly_report.WeeklyReportResult(
            text="本周新增 3 条。", attempts=1,
            checked_numbers=["3"], invalid_numbers=[],
        ),
    )
    out = report_service.generate_weekly(session=object(), user_id=50)
    assert out.generated_by == "llm"
    assert out.report_md == "本周新增 3 条。"
    assert out.validation.ok is True
    assert out.validation.checked_numbers == ["3"]
```

- [ ] **Step 2: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_weekly_report.py -q
```
Expected: FAIL（模块/函数不存在）。

- [ ] **Step 3: 写 Prompt 文件**

创建 `backend/app/ai/prompts/weekly_report_v1.md`：

```markdown
你是高中学习周报撰写助手。你只能根据下面的【统计数据】写周报。

硬性规则：
1. 只能使用【统计数据】中出现的数字（阿拉伯数字）；不得计算、四舍五入、换算百分比、取平均或补全任何新数字。
2. 不得使用 Markdown 有序列表；不要输出 1. / 2. / 3. 这类序号。
3. 只用 Markdown，四个二级标题：## 本周概览、## 学习投入、## 薄弱点、## 下周建议。
4. 某项为 0 或空时，直接写 0 或「暂无」，不要推测原因或补造数据。
5. 不引用未提供的日期、排名、增长率、完成率；「完成复习」是当前快照，不得写成完整历史。
6. 建议必须具体、可执行，且不能包含新的数字。

【统计数据】
{{ stats_json }}
```

- [ ] **Step 4: 写适配器**

创建 `backend/app/ai/report/__init__.py`（空文件即可）。

创建 `backend/app/ai/report/weekly_report.py`：

```python
"""S5-6 周报适配器：Prompt 渲染 → LLM → 数字校验 → 最多 2 次重试。"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.ai.llm import LLMClient, LLMError, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)

SCENE = "report"
PROMPT_VERSION = "weekly_report_v1"
PROMPT_FILE = "weekly_report_v1.md"
MAX_RETRIES = 2
MAX_TOKENS = 1400
TEMPERATURE = 0.3

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class WeeklyReportError(Exception):
    """LLM 失败、Prompt 渲染失败或数字校验重试耗尽。"""


@dataclass(frozen=True, slots=True)
class WeeklyReportContext:
    stats: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WeeklyReportResult:
    text: str
    attempts: int
    checked_numbers: list[str]
    invalid_numbers: list[str]


NumberValidator = Callable[[str], tuple[list[str], list[str]]]


def render_prompt(context: WeeklyReportContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stats_json=json.dumps(
                context.stats, ensure_ascii=False, indent=2, sort_keys=True
            )
        )
    except Exception as exc:
        raise WeeklyReportError(f"prompt 渲染失败：{exc}") from exc


def generate_weekly_report(
    context: WeeklyReportContext,
    *,
    validator: NumberValidator,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> WeeklyReportResult:
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]
    last_invalid: list[str] = []
    attempts = 0

    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        try:
            response = client.chat(
                messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                scene=SCENE,
            )
        except LLMError as exc:
            raise WeeklyReportError(f"LLM 调用失败（第 {attempts} 次）") from exc

        checked, invalid = validator(response.text)
        if response.text.strip() and checked and not invalid:
            return WeeklyReportResult(
                text=response.text.strip(),
                attempts=attempts,
                checked_numbers=checked,
                invalid_numbers=[],
            )
        last_invalid = invalid or ["<no-numbers>"]
        if attempt < max_retries:
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "以下数字不在输入中："
                        + "、".join(last_invalid)
                        + "；只能使用输入中出现的数字，重新输出完整周报。"
                    ),
                )
            )

    logger.warning("weekly_report_validation_failed attempts=%s", attempts)
    raise WeeklyReportError(
        f"周报数字校验失败（已尝试 {attempts} 次）：{last_invalid}"
    )
```

- [ ] **Step 5: 在 service 加生成用例**

在 `report_service.py` 顶部加：

```python
from app.ai.report import weekly_report
from app.core.exceptions import CODE_INTERNAL, AppError
```

追加：

```python
class ReportGenerationError(AppError):
    def __init__(self, message: str = "周报生成失败") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


def _validation_tuple(text: str, stats: WeeklyStatsOut) -> tuple[list[str], list[str]]:
    result = validate_numbers(text, stats.model_dump(mode="json"))
    return result.checked_numbers, result.invalid_numbers


def generate_weekly(
    session: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> WeeklyReportOut:
    moment = now or datetime.now(timezone.utc)
    stats = build_weekly_stats(session, user_id=user_id, now=moment)
    period = WeeklyPeriodOut(
        from_=moment.date() - timedelta(days=6),
        to=moment.date(),
        days=7,
    )
    if (
        stats.totals.new_notes == 0
        and stats.totals.reviews_done == 0
        and stats.totals.new_mistakes == 0
        and stats.totals.mastered_mistakes == 0
        and stats.mastery.assessed_kp_count == 0
    ):
        return WeeklyReportOut(
            period=period,
            generated_by="empty",
            report_md=EMPTY_REPORT_MD,
            stats=stats,
            validation=NumberValidationOut(
                ok=True, attempts=0, checked_numbers=[], invalid_numbers=[]
            ),
        )

    context = weekly_report.WeeklyReportContext(stats=stats.model_dump(mode="json"))
    try:
        result = weekly_report.generate_weekly_report(
            context,
            validator=lambda text: _validation_tuple(text, stats),
        )
    except weekly_report.WeeklyReportError as exc:
        raise ReportGenerationError() from exc
    return WeeklyReportOut(
        period=period,
        generated_by="llm",
        report_md=result.text,
        stats=stats,
        validation=NumberValidationOut(
            ok=True,
            attempts=result.attempts,
            checked_numbers=result.checked_numbers,
            invalid_numbers=[],
        ),
    )
```

注意：空数据分支也用同一个 `moment` 计算 `period`，不要依赖 `stats.trend` 长度；`timedelta` 已在 imports 中。

- [ ] **Step 6: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py tests/test_weekly_report.py -q
```
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
cd study-agent
git add backend/app/ai/report backend/app/ai/prompts/weekly_report_v1.md backend/app/services/report_service.py backend/tests/test_weekly_report.py
git commit -m "feat(s5-6): 周报 Prompt、LLM 适配器与生成用例"
```

---

### Task 6: `GET /reports/mastery` 与 `POST /reports/weekly` 路由

**Files:**
- Create: `backend/app/api/v1/reports.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_reports_api.py`

**Interfaces:**
- Consumes: `report_service.get_overview/generate_weekly`、`require_role("student")`、`Envelope`、`get_trace_id`
- Produces: 两个 API；`api_router` 挂载 `/api/v1/reports`

- [ ] **Step 1: 写 API 测试（先红）**

创建 `backend/tests/test_reports_api.py`：

```python
"""S5-6 报告接口：权限、range 校验、service 透传、错误壳。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.report import (
    NumberValidationOut,
    ReportOverviewOut,
    ReportRangeOut,
    WeeklyMasteryOut,
    WeeklyPeriodOut,
    WeeklyReportOut,
    WeeklyStatsOut,
    WeeklyTotalsOut,
)
from app.services import report_service


def _user(role: str = "student") -> User:
    user = User(
        username=f"{role}_s56", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


def _client(user: User):
    class _Session:
        def get(self, model, pk):
            return user if model is User else None

        def scalar(self, statement):
            return user if "users" in str(statement) else None

        def flush(self):
            return None

    app.dependency_overrides[get_db] = lambda: _Session()
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _empty_overview() -> ReportOverviewOut:
    return ReportOverviewOut(
        range=ReportRangeOut(key="30d", from_=date(2026, 10, 16), to=date(2026, 11, 14)),
        subjects=[],
        trend=[],
    )


def _weekly() -> WeeklyReportOut:
    stats = WeeklyStatsOut(
        totals=WeeklyTotalsOut(
            new_notes=0, reviews_done=0, new_mistakes=0,
            mastered_mistakes=0, mistakes_net=0,
        ),
        active_days=0,
        mastery=WeeklyMasteryOut(
            assessed_kp_count=0, avg_mastery=None, weak_modules=[], weak_kps=[]
        ),
        trend=[],
    )
    return WeeklyReportOut(
        period=WeeklyPeriodOut(from_=date(2026, 11, 8), to=date(2026, 11, 14), days=7),
        generated_by="empty",
        report_md="本周暂无学习记录。",
        stats=stats,
        validation=NumberValidationOut(
            ok=True, attempts=0, checked_numbers=[], invalid_numbers=[]
        ),
    )


def test_reports_api_requires_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/reports/mastery").status_code == 401
        assert client.post("/api/v1/reports/weekly").status_code == 401


def test_reports_api_rejects_non_student() -> None:
    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/reports/mastery").status_code == 403
        assert client.post("/api/v1/reports/weekly").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_reports_api_rejects_unknown_range() -> None:
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/mastery?range=365d")
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200
    finally:
        app.dependency_overrides.clear()


def test_mastery_forwards_range_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_overview(session, **kwargs):
        captured.update(kwargs)
        return _empty_overview()

    monkeypatch.setattr(report_service, "get_overview", fake_overview)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/reports/mastery?range=7d")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50, "range_key": "7d"}
        assert data["range"]["from"] == "2026-10-16"
    finally:
        app.dependency_overrides.clear()


def test_mastery_defaults_to_30d(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_overview(session, **kwargs):
        captured.update(kwargs)
        return _empty_overview()

    monkeypatch.setattr(report_service, "get_overview", fake_overview)
    client = _client(_user())
    try:
        assert client.get("/api/v1/reports/mastery").status_code == 200
        assert captured["range_key"] == "30d"
    finally:
        app.dependency_overrides.clear()


def test_weekly_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_generate(session, **kwargs):
        captured.update(kwargs)
        return _weekly()

    monkeypatch.setattr(report_service, "generate_weekly", fake_generate)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/reports/weekly")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert captured == {"user_id": 50}
        assert data["generated_by"] == "empty"
        assert data["validation"]["ok"] is True
    finally:
        app.dependency_overrides.clear()


def test_weekly_generation_error_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate(session, **kwargs):
        raise report_service.ReportGenerationError()

    monkeypatch.setattr(report_service, "generate_weekly", fake_generate)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/reports/weekly")
        assert resp.status_code == 500
        assert resp.json()["code"] == 50000
        assert resp.json()["message"] == "周报生成失败"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: 跑测试确认红**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_reports_api.py -q
```
Expected: FAIL（404 / 模块不存在）。

- [ ] **Step 3: 写路由**

创建 `backend/app/api/v1/reports.py`：

```python
"""S5-6 学习报告：雷达/热力/趋势 + LLM 周报（API.md §9）。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.report import ReportOverviewOut, WeeklyReportOut
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/mastery", response_model=Envelope[ReportOverviewOut], summary="学习报告图表数据"
)
def report_mastery(
    range_: Literal["7d", "30d", "90d"] = Query(
        report_service.DEFAULT_RANGE, alias="range", description="趋势窗口"
    ),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[ReportOverviewOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=report_service.get_overview(
            session, user_id=current_user.id, range_key=range_
        ),
    )


@router.post(
    "/weekly", response_model=Envelope[WeeklyReportOut], summary="生成学习周报"
)
def generate_weekly(
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[WeeklyReportOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=report_service.generate_weekly(session, user_id=current_user.id),
    )
```

修改 `backend/app/api/router.py`：

```python
from app.api.v1 import (
    admin,
    auth,
    files,
    kp,
    mastery,
    mistakes,
    notes,
    papers,
    qa,
    questions,
    reports,
    retrieval,
    review,
    stats,
    tasks,
)
```

并在 `review` 后加：

```python
api_router.include_router(reports.router)
```

- [ ] **Step 4: 跑测试确认绿**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_reports_api.py -q
```
Expected: 全部 PASS。

- [ ] **Step 5: 跑相邻回归**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_report_service.py tests/test_weekly_report.py tests/test_report_migration.py tests/test_stats_api.py tests/test_stats_service.py -q
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd study-agent
git add backend/app/api/v1/reports.py backend/app/api/router.py backend/tests/test_reports_api.py
git commit -m "feat(s5-6): 学习报告两个接口"
```

---

### Task 7: 文档同步、真机验收与全量验证

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`（D-063）
- Modify: `docs/AGENTS.md` §9.2/§9.6
- Modify: `docs/AI协作开发实施计划.md` §S5-6 勾选
- Create: `.sdd/s5-6/acceptance-evidence.md`（不提交密钥/正文以外的敏感信息）

**Interfaces:**
- Consumes: 前 6 个任务的代码与测试
- Produces: 进度/决策/验收证据；迁移 head 0017；最终全量绿

- [ ] **Step 1: 迁移到 head 并跑全量测试**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic current
../.venv/Scripts/python.exe -m pytest -q
```
Expected: `0017_s5_6 (head)`；pytest 全绿（计数以实际输出为准，不得写未实测数字）。

- [ ] **Step 2: 启动 API 做真实 HTTP 验收**

Run:
```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```
用真实学生 user 50 登录拿 token（用现有测试/脚本的登录方式），执行：
```bash
curl -s "http://127.0.0.1:8000/api/v1/reports/mastery?range=30d" \
  -H "Authorization: Bearer $TOKEN"
```
检查：
- `trend` 30 个点、日期连续；
- 数学 `modules` 11 个；
- `heatmap` 节点数 = level2+3+4；
- 抽 1 个模块手算均值与接口一致；
- 未评估节点 `mastery_t=null`、`color_value=null`。

周报：
```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/reports/weekly" \
  -H "Authorization: Bearer $TOKEN"
```
检查：
- `generated_by=llm`、`report_md` 非空；
- 用 Python 脚本重新提取 `report_md` 数字，逐个在 `stats` 数值集合中命中；
- `validation.ok=true`、`invalid_numbers=[]`；
- 查 `llm_call_logs` 最近一条 `scene='report'` 成功记录（SELECT 只查 id/scene/status/latency_ms，不打印 Key/Prompt）。

空数据：用 user 62（或专用无数据学生）POST，确认 `generated_by=empty`、`attempts=0`，且没有新增 `scene='report'` 日志。

- [ ] **Step 3: 前端回归（不改前端）**

Run:
```bash
cd study-agent/web
npm run test:run
npm run build
```
Expected: `test:run` 全绿；build exit 0。若环境不允许跑前端，必须在证据里如实写「未跑」并说明原因，不能写通过。

- [ ] **Step 4: 写验收证据**

创建 `.sdd/s5-6/acceptance-evidence.md`，至少记录：
- 迁移 head 输出；
- 全量 pytest 实际计数与 warnings；
- GET 响应的 `range`/趋势长度/模块数/节点数/抽样手算；
- 周报全文（可截断到关键段）、独立数字校验脚本输出、`llm_call_logs` 查询结果；
- 空数据响应；
- 前端 test/build 输出（若跑）。

- [ ] **Step 5: 更新文档**

- `docs/PROGRESS.md`：S5-6 完成、测试计数、验收结论、已知边界（UTC、reviews_done 快照、无历史薄弱点变化、无报告表）。
- `docs/DECISIONS.md`：新增 D-063，记录 D1–D11 与数字校验/空数据策略。
- `docs/AGENTS.md` §9.2 增加「学习报告（S5-6）」条目，§9.6 增加报告锚点（`report_service` + `weekly_report` + `reports.py`）。
- `docs/AI协作开发实施计划.md` §S5-6：勾选已完成项。
- 若 API/SCHEMA 在 Task 1 已改，复核与实现一致；不一致以契约文档为准并修正实现，不反向改契约。

- [ ] **Step 6: 提交文档与证据**

```bash
cd study-agent
git add docs/PROGRESS.md docs/DECISIONS.md docs/AGENTS.md docs/AI协作开发实施计划.md .sdd/s5-6
git commit -m "docs(s5-6): 进度、决策与验收记录"
```

---

## 自审清单（写完计划后逐条核对）

- **Spec 覆盖**：API 两个端点 → Task 6；UTC 窗口/补零 → Task 2；雷达 → Task 3；热力 → Task 3；趋势 → Task 2/3；周报统计/数字校验 → Task 4；Prompt/重试/空数据 → Task 5；scene/迁移 → Task 1；文档/验收 → Task 7。
- **类型一致**：`ReportOverviewOut`/`WeeklyStatsOut`/`NumberValidationOut` 在 Task 2 定义，后续只使用不重命名；`build_subjects` 参数名 `mastery_raw/mastery_t` 前后一致；`generate_weekly_report` 的 `validator` 返回 `(checked, invalid)` 元组，service 的 `_validation_tuple` 与测试一致。
- **无占位**：本计划不含 TBD/TODO；每个 code step 有实际代码；测试命令给出可复制路径。
- **风险**：Task 5 的 `_weekly_stats` 必须显式传 `now`，否则测试时间漂移；Task 3 的 `_context` 重构成薄 `get_overview` 要保留 Task 3 的 FakeSession 分派顺序（`review_items` 在 `notes` 前，`last_review_at` 在 `mistakes` 前）。