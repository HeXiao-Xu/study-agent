# S5-2 组卷 API + 预览页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 S5-1 组卷内核接到 HTTP 与页面：落 `papers` 表，提供生成预览 / 换题 / 保存草稿 / 按 id 读回 4 个接口，前端单页完成「约束表单 → 预览换题 → 保存」。

**Architecture:** 纯函数内核（`paper_service`，S5-1，已交付）不动；新增 DB 层 `paper_plan_service` 负责「取候选 → 调内核 → 落库」，路由只做校验与 `Envelope`；前端新增 `views/papers/Generate.vue` 单页，预览状态放组件内，保存才落库。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic；PostgreSQL 16；Vue 3 + TS + Element Plus + Vitest。无新依赖。

**Spec:** `docs/spec/s5-2-paper-api.md`

## Global Constraints

- 不建 `answers` / `review_items`，不做 PDF（S5-3）、不做草稿列表（S5-7）、不做异步任务。
- 不加依赖、不加环境变量、不改已提交迁移（新迁移 `0014_s5_2`，`down_revision = "0013_s4_7"`）。
- 所有查询显式带 `user_id`（papers 是个人数据）；题库是公共语料，只读。
- 时间统一 UTC，`created_at` 用 `now()`；分数用整数。
- 枚举 TEXT + CHECK，值集放 `app/models/enums.py`，CHECK 由 `in_check()` 生成（D-021）。
- 业务错误抛 `AppError` 子类；路由里禁止手拼错误 JSON。
- 每个任务先写失败测试再实现（TDD），全绿才提交；提交信息含 `s5-2`。
- 命令位置：后端测试在 `study-agent/backend` 下用 `../.venv/Scripts/python.exe -m pytest …`；前端在 `study-agent/web` 下用 `npm run test:run -- <file>`。
- 禁止伪造验收数据（AGENTS §6）；真实题库不足就如实展示 shortage。

---

### Task 1: 契约文档 + papers 迁移 + ORM + 枚举

**Files:**
- Modify: `docs/API.md` §8（整节替换）
- Modify: `docs/SCHEMA.md` §6.1（`total_score` 类型 + 落地说明）
- Modify: `backend/app/models/enums.py`（`PaperStatus` / `PaperGeneratedBy` / 元组）
- Create: `backend/app/models/paper.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0014_s5_2.py`
- Test: `backend/tests/test_papers_migration.py`

**Interfaces:**
- Produces: `Paper` ORM（列见下）、`PaperStatus`/`PaperGeneratedBy` 枚举、`PAPER_STATUSES`/`PAPER_GENERATED_BY` 元组、迁移 head `0014_s5_2`。

- [ ] **Step 1: 先改契约文档（§9.1 契约先行）**

把 `docs/API.md` 的 `## 8. 组卷与作答` 一节整体替换为：

````markdown
## 8. 组卷与作答

> S5-2 定死：组卷是**同步接口**（纯函数 + 两次批量查询，毫秒级），不用异步任务。
> 生成与换题**不写库**；只有 `POST /papers` 保存草稿时落 `papers` 表。

### POST /api/v1/papers/generate
- 权限：student
- 类型：同步 200；**不写库**
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | kp_ids | int[] | 是 | 知识点覆盖清单（1–100，去重） |
  | total_questions | int | 是 | 题量（1–100） |
  | qtype_ratio | object | 是 | 题型配比，键 ∈ 单选/多选/填空/解答，值 ≥0 且至少一个 >0 |
  | difficulty_dist | object | 是 | 难度分布，键 ∈ 1–5，值 ≥0 且至少一个 >0 |
  | total_score | int | 是 | 目标总分（1–300） |
  | duration_min | int? | 否 | 时长，只回显/保存，不参与算法 |
  | exclude_recent_days | int | 否 | 默认 14；0–365 |
  | seed | int? | 否 | 不传则服务端随机并回显；同种子同候选集结果一致 |
  | kp_weights | object? | 否 | 键 ⊆ kp_ids，值 >0 |

- 出参：`constraint`（归一化回显，含 `score_by_qtype`）、`seed`、`ok`、`items[]`、`total_score`、`target_score`、`quota_by_*`、`counts_by_*`、`violations[]`、`warnings[]`。
- `items[]` 每项：`question_id / qtype / difficulty / score / kp_ids / parts / subject_id / stem_md / options / answer_md / analysis_md / verified / origin`。
- 题库不足：**200 + `ok=false`**，`violations` 逐条给出 QTYPE_SHORTAGE / DIFFICULTY_SHORTAGE / KP_SHORTAGE / TOTAL_SCORE_OUT_OF_TOLERANCE / NO_CANDIDATES；不抛 409。
- 备注：组卷为「约束满足 + 贪心打分」：掌握度 < 0.5 优先基础题、> 0.8 配难题、排除近 14 天做过的题（算法见 S5-1 spec）。

### POST /api/v1/papers/replace-item
- 权限：student；同步 200；无状态、**不写库**
- 入参：generate 的全部约束字段 + `selected_question_ids`（当前卷面全部题）+ `replace_question_id`
- 规则：候选池重建后剔除已选与原题；先挑「同题型 + 同难度」最高分，再退「同题型任意难度」；没有则 `{replaced:false, item:null, reason}`（200）
- 出参：`replaced`、`item`（null 或题目项）、`reason`

### POST /api/v1/papers
- 权限：student；201；保存草稿
- 入参：`title`（1–100）、`constraint`（同 generate 约束）、`question_ids`（1–100、去重、必须存在）、`duration_min?`
- 服务端：按 `question_ids` 重算 `total_score`；`status='草稿'`、`generated_by='manual'`
- 出参：`id`、`title`、`status`、`total_score`、`duration_min`、`question_ids`、`created_at`

### GET /api/v1/papers/{id}
- 权限：student（本人）；不存在 404/40400，别人的 403/40300
- 出参：papers 元信息 + `constraint_json` + `items[]`（按保存顺序）+ `missing_question_ids`（题目被硬删时跳过，`parts=null`）

### GET /api/v1/papers/{id}/export.pdf
- 权限：student
- 类型：同步（Playwright 渲染，S5-3 实现）
- 出参：PDF 下载

### POST /api/v1/answers
- 权限：student
- 类型：同步
- 说明：提交作答 → 回写掌握度（方案 6.6；S5-4 实现，入参/出参 TODO）
````

再改 `docs/SCHEMA.md` §6.1 表格里 `total_score` 一行与表后备注：

```markdown
| total_score | INTEGER | 否 | — | 总分（按题目分值表求和，整数） | — |
```

在 §6.1 表格后追加：

```markdown
> S5-2 落地：`total_score` 用 INTEGER 而非 NUMERIC——题分是整数（3/4/4/8），求和即整数，避免 Decimal 噪音（AGENTS §9.2）。索引 `ix_papers_user_id`；迁移 `0014_s5_2`。`question_ids` 的数组顺序就是卷面顺序。
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_papers_migration.py`：

```python
"""S5-2 papers 契约：列、CHECK、默认值、迁移链头。"""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.enums import (
    PAPER_GENERATED_BY,
    PAPER_STATUSES,
    PaperGeneratedBy,
    PaperStatus,
    in_check,
)
from app.models.paper import Paper

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_paper_columns_match_schema():
    columns = set(Paper.__table__.columns.keys())
    assert columns == {
        "id",
        "user_id",
        "title",
        "constraint_json",
        "question_ids",
        "total_score",
        "duration_min",
        "status",
        "generated_by",
        "created_at",
    }


def test_status_values_and_check():
    assert PAPER_STATUSES == ("草稿", "已生成", "已提交")
    assert in_check("status", PaperStatus) == "status IN ('草稿', '已生成', '已提交')"


def test_generated_by_values_and_check():
    assert PAPER_GENERATED_BY == ("manual", "ai_agent")
    assert in_check("generated_by", PaperGeneratedBy) == (
        "generated_by IN ('manual', 'ai_agent')"
    )


def test_defaults_are_draft_and_manual():
    assert Paper.__table__.columns["status"].server_default.arg == "草稿"
    assert Paper.__table__.columns["generated_by"].server_default.arg == "manual"


def test_user_fk_cascades_and_is_indexed():
    column = Paper.__table__.columns["user_id"]
    assert {fk.target_fullname for fk in column.foreign_keys} == {"users.id"}
    index_names = {index.name for index in Paper.__table__.indexes}
    assert "ix_papers_user_id" in index_names


def test_migration_chain_head_is_s5_2():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0014_s5_2"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_papers_migration.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.models.paper'`

- [ ] **Step 4: 加枚举**

在 `backend/app/models/enums.py` 末尾 `MISTAKE_STATUSES` 一行之后追加：

```python
class PaperStatus(StrEnum):
    """papers.status：草稿 → 已生成 → 已提交（SCHEMA §10.9）。"""

    DRAFT = "草稿"
    GENERATED = "已生成"
    SUBMITTED = "已提交"


class PaperGeneratedBy(StrEnum):
    """papers.generated_by：人工组卷 / Agent 组卷（SCHEMA §10.9）。"""

    MANUAL = "manual"
    AI_AGENT = "ai_agent"


PAPER_STATUSES: tuple[str, ...] = tuple(item.value for item in PaperStatus)
PAPER_GENERATED_BY: tuple[str, ...] = tuple(item.value for item in PaperGeneratedBy)
```

- [ ] **Step 5: 写 ORM**

`backend/app/models/paper.py`：

```python
"""papers ORM 模型：组卷结果（SCHEMA §6.1，S5-2）。

question_ids 存有序题目 id：卷面顺序就是数组顺序，换题/重排只改数组；
S5-4 的 answers 再按 (paper_id, question_id) 关联，不建中间表。
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PaperGeneratedBy, PaperStatus, in_check

_STATUSES = [item.value for item in PaperStatus]
_GENERATED_BY = [item.value for item in PaperGeneratedBy]


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(in_check("status", _STATUSES), name="ck_papers_status"),
        CheckConstraint(
            in_check("generated_by", _GENERATED_BY), name="ck_papers_generated_by"
        ),
        Index("ix_papers_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_papers_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    constraint_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    question_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PaperStatus.DRAFT.value
    )
    generated_by: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PaperGeneratedBy.MANUAL.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 6: 注册模型**

`backend/app/models/__init__.py` 的 import 段按字母序插 `from app.models.paper import Paper`（在 `Note` 之后、`PromptTemplate` 之前），并在 `__all__` 列表里对应位置加 `"Paper",`。

- [ ] **Step 7: 写迁移**

`backend/alembic/versions/0014_s5_2.py`：

```python
"""S5-2 组卷：papers 表（SCHEMA §6.1）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_s5_2"
down_revision = "0013_s4_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("constraint_json", postgresql.JSONB(), nullable=False),
        sa.Column("question_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="草稿"),
        sa.Column("generated_by", sa.Text(), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('草稿', '已生成', '已提交')", name="ck_papers_status"),
        sa.CheckConstraint(
            "generated_by IN ('manual', 'ai_agent')", name="ck_papers_generated_by"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_papers_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_papers_user_id", "papers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_papers_user_id", table_name="papers")
    op.drop_table("papers")
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_papers_migration.py -q`
Expected: PASS（6 passed）

- [ ] **Step 9: 真库验证迁移可升降级**

Run（PG 已在跑）：

```bash
cd study-agent/backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic downgrade -1
../.venv/Scripts/python.exe -m alembic upgrade head
```

Expected: 三条命令都退出 0；`\d papers` 能看到 10 列与两条 CHECK。

- [ ] **Step 10: 提交**

```bash
cd study-agent
git add docs/API.md docs/SCHEMA.md backend/app/models/enums.py backend/app/models/paper.py \
  backend/app/models/__init__.py backend/alembic/versions/0014_s5_2.py \
  backend/tests/test_papers_migration.py
git commit -m "feat(s5-2): papers 表、模型与迁移（0014_s5_2）"
```

---

### Task 2: 入参/出参 schema + 约束归一化 + 候选装载

**Files:**
- Create: `backend/app/schemas/paper.py`
- Create: `backend/app/services/paper_plan_service.py`
- Test: `backend/tests/test_paper_plan_service.py`

**Interfaces:**
- Consumes: `paper_service.PaperConstraints` / `CandidateQuestion`（S5-1）；`mastery_service.mastery_values`。
- Produces: `PaperGenerateIn` / `PaperReplaceIn` / `PaperSaveIn` / `PaperPreviewOut` 等 DTO；`build_constraints(payload) -> PaperConstraints`；`normalized_constraint(constraints) -> PaperConstraintOut`；`load_candidates(session, constraints, *, user_id, now) -> CandidateData`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_paper_plan_service.py` 第一段（后续任务继续往这个文件追加）：

```python
"""S5-2 组卷服务：约束归一化、候选装载、生成/换题/保存/读取（FakeSession，不连库）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.exceptions import InvalidParamError
from app.models.paper import Paper
from app.schemas.paper import PaperGenerateIn
from app.services import paper_plan_service

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


class FakeSession:
    """按调用顺序喂 execute 结果：服务查询顺序确定，顺序断言最直观。"""

    def __init__(self, *, results=None, paper=None) -> None:
        self.results = [list(rows) for rows in (results or [])]
        self.statements: list[object] = []
        self.added: list[object] = []
        self.committed = 0
        self.paper = paper

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper is not None and self.paper.id == pk else None
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        obj.id = 7
        obj.created_at = NOW


def make_payload(**overrides) -> PaperGenerateIn:  # noqa: ANN003
    data = {
        "kp_ids": [101],
        "total_questions": 2,
        "qtype_ratio": {"单选": 1.0},
        "difficulty_dist": {2: 1.0},
        "total_score": 6,
        "exclude_recent_days": 14,
        "seed": 7,
    }
    data.update(overrides)
    return PaperGenerateIn(**data)


def candidate_rows():
    """load_candidates 第一条 SQL 的行：(id, qtype, difficulty, verified, origin, kp_id, weight)。"""
    return [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (502, "单选", 2, False, "upload", 101, Decimal("0.800000")),
        (503, "解答", 3, True, "textbook", 101, Decimal("1.000000")),
    ]


def test_build_constraints_filters_zero_qtype_and_normalizes_seed():
    payload = make_payload(qtype_ratio={"单选": 0.5, "多选": 0.0, "解答": 0.5})
    constraints = paper_plan_service.build_constraints(payload)
    assert dict(constraints.qtype_ratio) == {"单选": 0.5, "解答": 0.5}
    assert constraints.seed == 7
    assert constraints.total_score_target == 6


def test_build_constraints_generates_seed_in_range():
    constraints = paper_plan_service.build_constraints(make_payload(seed=None))
    assert 0 <= constraints.seed <= 2**31 - 1


def test_generate_in_rejects_all_zero_qtype_ratio():
    # 零权重在 schema 层就被挡住，build_constraints 里那层过滤只是防御
    with pytest.raises(ValidationError, match="至少一个题型配比"):
        make_payload(qtype_ratio={"单选": 0})


def test_generate_in_rejects_kp_weight_outside_selection():
    with pytest.raises(ValidationError, match="kp_weights"):
        make_payload(kp_weights={999: 1.0})


def test_paper_save_in_rejects_duplicate_question_ids():
    from app.schemas.paper import PaperSaveIn

    with pytest.raises(ValidationError, match="重复"):
        PaperSaveIn(
            title="t",
            constraint=make_payload(),
            question_ids=[501, 501],
        )


def test_load_candidates_groups_multiple_kps_and_takes_latest_done():
    rows = [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (501, "单选", 2, True, "exam", 102, Decimal("0.600000")),
    ]
    old = NOW - timedelta(days=40)
    fresh = NOW - timedelta(days=3)
    session = FakeSession(
        results=[
            rows,
            [(501, old, fresh)],
            [],
        ]
    )
    constraints = paper_plan_service.build_constraints(make_payload(kp_ids=[101, 102]))
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert [item.question_id for item in data.candidates] == [501]
    assert dict(data.candidates[0].kp_weights) == {101: 1.0, 102: 0.6}
    assert data.candidates[0].last_done_at == fresh
    assert data.mastery_by_kp == {}


def test_load_candidates_empty_rows_yields_empty_pool():
    session = FakeSession(results=[[], [], []])
    constraints = paper_plan_service.build_constraints(make_payload())
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert data.candidates == ()
    assert data.mastery_by_kp == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.schemas.paper'`

- [ ] **Step 3: 写入参/出参 schema**

`backend/app/schemas/paper.py`：

```python
"""S5-2 组卷接口出入参（API.md §8）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import QuestionType

QTYPE_VALUES = tuple(item.value for item in QuestionType)
SEED_MAX = 2**31 - 1


class PaperConstraintIn(BaseModel):
    """generate / replace 共用约束（API.md §8）。"""

    kp_ids: list[int] = Field(min_length=1, max_length=100)
    total_questions: int = Field(ge=1, le=100)
    qtype_ratio: dict[str, float] = Field(min_length=1)
    difficulty_dist: dict[int, float] = Field(min_length=1)
    total_score: int = Field(ge=1, le=300)
    duration_min: int | None = Field(default=None, ge=1, le=1440)
    exclude_recent_days: int = Field(default=14, ge=0, le=365)
    seed: int | None = Field(default=None, ge=0, le=SEED_MAX)
    kp_weights: dict[int, float] | None = None

    @field_validator("kp_ids")
    @classmethod
    def _dedupe_kp_ids(cls, value: list[int]) -> list[int]:
        ordered: list[int] = []
        for kp_id in value:
            if kp_id not in ordered:
                ordered.append(kp_id)
        return ordered

    @field_validator("qtype_ratio")
    @classmethod
    def _validate_qtype_ratio(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = [qtype for qtype in value if qtype not in QTYPE_VALUES]
        if unknown:
            raise ValueError(f"qtype_ratio 含未知题型：{unknown}")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("qtype_ratio 的权重不能为负")
        return value

    @field_validator("difficulty_dist")
    @classmethod
    def _validate_difficulty(cls, value: dict[int, float]) -> dict[int, float]:
        unknown = [str(difficulty) for difficulty in value if difficulty not in range(1, 6)]
        if unknown:
            raise ValueError(f"difficulty_dist 含 1–5 之外的难度：{unknown}")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("difficulty_dist 的权重不能为负")
        return value

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> Self:
        if sum(self.qtype_ratio.values()) <= 0:
            raise ValueError("qtype_ratio 至少一个题型配比大于 0")
        if sum(self.difficulty_dist.values()) <= 0:
            raise ValueError("difficulty_dist 至少一个难度权重大于 0")
        if self.kp_weights is not None:
            outside = [kp_id for kp_id in self.kp_weights if kp_id not in self.kp_ids]
            if outside:
                raise ValueError(f"kp_weights 含不在 kp_ids 里的知识点：{outside}")
            if any(weight <= 0 for weight in self.kp_weights.values()):
                raise ValueError("kp_weights 的权重必须大于 0")
        return self


class PaperGenerateIn(PaperConstraintIn):
    """POST /papers/generate 入参：约束即入参。"""


class PaperReplaceIn(PaperConstraintIn):
    """POST /papers/replace-item 入参：约束平铺 + 卷面 + 要换掉的题。"""

    selected_question_ids: list[int] = Field(default_factory=list, max_length=100)
    replace_question_id: int = Field(ge=1)


class PaperSaveIn(BaseModel):
    """POST /papers 入参：保存草稿。"""

    title: str = Field(min_length=1, max_length=100)
    constraint: PaperConstraintIn
    question_ids: list[int] = Field(min_length=1, max_length=100)
    duration_min: int | None = Field(default=None, ge=1, le=1440)

    @field_validator("question_ids")
    @classmethod
    def _reject_duplicates(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("question_ids 不能重复")
        return value


class ScorePartsOut(BaseModel):
    difficulty_match: float
    mastery_match: float
    novelty: float
    quality: float
    total: float


class OptionOut(BaseModel):
    key: str
    text: str


class PaperItemOut(BaseModel):
    question_id: int
    qtype: str
    difficulty: int
    score: int
    kp_ids: list[int]
    parts: ScorePartsOut | None = None
    subject_id: int
    stem_md: str
    options: list[OptionOut]
    answer_md: str | None
    analysis_md: str | None
    verified: bool
    origin: str


class PaperConstraintOut(BaseModel):
    """归一化后的约束回显（分值表也回显，便于前端解释总分）。"""

    kp_ids: list[int]
    total_questions: int
    qtype_ratio: dict[str, float]
    difficulty_dist: dict[int, float]
    total_score: int
    duration_min: int | None
    exclude_recent_days: int
    seed: int
    kp_weights: dict[int, float]
    score_by_qtype: dict[str, int]


class PaperViolationOut(BaseModel):
    code: str
    message: str
    detail: dict[str, Any]


class PaperPreviewOut(BaseModel):
    constraint: PaperConstraintOut
    seed: int
    ok: bool
    items: list[PaperItemOut]
    total_score: int
    target_score: int
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    counts_by_qtype: dict[str, int]
    counts_by_difficulty: dict[int, int]
    counts_by_kp: dict[int, int]
    violations: list[PaperViolationOut]
    warnings: list[str]


class PaperReplaceOut(BaseModel):
    replaced: bool
    item: PaperItemOut | None = None
    reason: str | None = None


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    total_score: int
    duration_min: int | None
    question_ids: list[int]
    created_at: datetime


class PaperDetailOut(PaperOut):
    constraint_json: dict[str, Any]
    items: list[PaperItemOut]
    missing_question_ids: list[int]
```

- [ ] **Step 4: 写服务层第一段**

`backend/app/services/paper_plan_service.py`：

```python
"""S5-2 组卷服务：取候选、生成预览、换题、保存、读取（算法全部复用 paper_service）。"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.models.mistake import Mistake
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.schemas.paper import (
    OptionOut,
    PaperConstraintIn,
    PaperConstraintOut,
    PaperItemOut,
    PaperViolationOut,
    ScorePartsOut,
)
from app.services import mastery_service, paper_service
from app.services.paper_service import CandidateQuestion, PaperConstraints, PaperItem

SEED_MAX = 2**31 - 1


@dataclass(frozen=True, slots=True)
class CandidateData:
    candidates: tuple[CandidateQuestion, ...]
    mastery_by_kp: dict[int, float]


def build_constraints(payload: PaperConstraintIn) -> PaperConstraints:
    """把 DTO 归一化成内核约束；内核拒绝的入参统一翻成 422。"""
    qtype_ratio = {
        qtype: float(weight) for qtype, weight in payload.qtype_ratio.items() if weight > 0
    }
    if not qtype_ratio:
        raise InvalidParamError("qtype_ratio 至少一个题型配比大于 0")
    seed = payload.seed if payload.seed is not None else secrets.randbelow(SEED_MAX + 1)
    try:
        return PaperConstraints(
            kp_ids=tuple(payload.kp_ids),
            total_questions=payload.total_questions,
            qtype_ratio=qtype_ratio,
            difficulty_dist={int(key): float(value) for key, value in payload.difficulty_dist.items()},
            total_score_target=payload.total_score,
            kp_weights=(
                {int(key): float(value) for key, value in payload.kp_weights.items()}
                if payload.kp_weights
                else None
            ),
            exclude_recent_days=payload.exclude_recent_days,
            duration_min=payload.duration_min,
            seed=seed,
        )
    except paper_service.PaperPlanError as exc:
        raise InvalidParamError(str(exc)) from exc


def normalized_constraint(constraints: PaperConstraints) -> PaperConstraintOut:
    """权重归一化后回显；分值表一并回显，前端据此解释总分。"""

    def normalize(weights: Mapping[object, float]) -> dict[object, float]:
        total = sum(float(value) for value in weights.values())
        return {key: round(float(value) / total, 6) for key, value in weights.items()}

    return PaperConstraintOut(
        kp_ids=list(constraints.kp_ids),
        total_questions=constraints.total_questions,
        qtype_ratio={str(key): value for key, value in normalize(constraints.qtype_ratio).items()},
        difficulty_dist={int(key): value for key, value in normalize(constraints.difficulty_dist).items()},
        total_score=constraints.total_score_target,
        duration_min=constraints.duration_min,
        exclude_recent_days=constraints.exclude_recent_days,
        seed=constraints.seed,
        kp_weights=constraints.kp_weight_map,
        score_by_qtype=constraints.score_map,
    )


def load_candidates(
    session: Session,
    constraints: PaperConstraints,
    *,
    user_id: int,
    now: datetime,
) -> CandidateData:
    """三条批量查询：题目↔知识点、本人最近做过的题、本人掌握度。"""
    kp_ids = list(constraints.kp_ids)
    rows = session.execute(
        select(
            Question.id,
            Question.qtype,
            Question.difficulty,
            Question.verified,
            Question.origin,
            QuestionKp.kp_id,
            QuestionKp.weight,
        )
        .join(QuestionKp, QuestionKp.question_id == Question.id)
        .where(QuestionKp.kp_id.in_(kp_ids))
    ).all()
    grouped: dict[int, dict[str, object]] = {}
    for question_id, qtype, difficulty, verified, origin, kp_id, weight in rows:
        entry = grouped.setdefault(
            int(question_id),
            {
                "qtype": str(qtype),
                "difficulty": int(difficulty),
                "verified": bool(verified),
                "origin": str(origin),
                "kps": [],
            },
        )
        entry["kps"].append(
            (int(kp_id), float(weight) if weight is not None else 1.0)
        )
    last_done = _last_done_at(session, user_id=user_id, question_ids=list(grouped))
    candidates = tuple(
        CandidateQuestion(
            question_id=question_id,
            qtype=str(grouped[question_id]["qtype"]),
            difficulty=int(grouped[question_id]["difficulty"]),
            kp_weights=tuple(grouped[question_id]["kps"]),
            verified=bool(grouped[question_id]["verified"]),
            origin=str(grouped[question_id]["origin"]),
            last_done_at=last_done.get(question_id),
        )
        for question_id in sorted(grouped)
    )
    mastery_by_kp = mastery_service.mastery_values(
        session, user_id=user_id, kp_ids=constraints.kp_ids, now=now
    )
    return CandidateData(candidates=candidates, mastery_by_kp=mastery_by_kp)


def _last_done_at(
    session: Session, *, user_id: int, question_ids: Sequence[int]
) -> dict[int, datetime]:
    """本人每道题最近一次「做过」的时间 = max(last_review_at, created_at)。"""
    if not question_ids:
        return {}
    rows = session.execute(
        select(Mistake.question_id, Mistake.last_review_at, Mistake.created_at).where(
            Mistake.user_id == user_id, Mistake.question_id.in_(list(question_ids))
        )
    ).all()
    result: dict[int, datetime] = {}
    for question_id, last_review_at, created_at in rows:
        moment = last_review_at or created_at
        if moment is None:
            continue
        current = result.get(int(question_id))
        if current is None or moment > current:
            result[int(question_id)] = moment
    return result
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: PASS（7 passed）

- [ ] **Step 6: 提交**

```bash
cd study-agent
git add backend/app/schemas/paper.py backend/app/services/paper_plan_service.py backend/tests/test_paper_plan_service.py
git commit -m "feat(s5-2): 组卷 DTO、约束归一化与候选装载"
```

---

### Task 3: 生成预览 + 无状态换题

**Files:**
- Modify: `backend/app/services/paper_plan_service.py`（追加 `generate_preview` / `replace_item` / 明细装载）
- Test: `backend/tests/test_paper_plan_service.py`（追加用例）

**Interfaces:**
- Consumes: Task 2 的 `build_constraints` / `load_candidates` / `normalized_constraint`；`paper_service.prepare_pool` / `plan_paper` / `score_parts`。
- Produces: `generate_preview(session, payload: PaperGenerateIn, *, user_id, now) -> PaperPreviewOut`；`replace_item(session, payload: PaperReplaceIn, *, user_id, now) -> PaperReplaceOut`；`load_question_details(session, ids) -> dict[int, QuestionDetail]`；`kp_ids_by_question(session, ids) -> dict[int, list[int]]`。

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_paper_plan_service.py` 末尾追加：

```python
from app.schemas.paper import PaperReplaceIn  # noqa: E402


def detail_rows():
    """明细 SQL 的行：id, subject_id, qtype, difficulty, stem_md, options_json, answer_md, analysis_md, verified, origin。"""
    return [
        (501, 7, "单选", 2, "题干 501", [{"key": "A", "text": "选项 A"}], "答案 501", None, True, "exam"),
        (502, 7, "单选", 2, "题干 502", [], "答案 502", None, False, "upload"),
        (503, 7, "解答", 3, "题干 503", [], "答案 503", "解析 503", True, "textbook"),
        (504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock"),
    ]


def full_row_set():
    """一次 generate 的查询顺序：候选 → 错题时间 → 掌握度 → 明细。"""
    return [
        candidate_rows(),
        [],
        [(101, Decimal("0.200"), Decimal("2.00"), NOW - timedelta(days=30))],
        detail_rows(),
    ]


def test_generate_preview_ok_returns_items_with_stem_and_answers():
    session = FakeSession(results=full_row_set())
    preview = paper_plan_service.generate_preview(
        session, make_payload(), user_id=50, now=NOW
    )
    assert preview.ok is True
    assert len(preview.items) == 2
    assert preview.total_score == 6
    assert preview.items[0].stem_md.startswith("题干")
    assert preview.items[0].answer_md.startswith("答案")
    assert preview.constraint.seed == 7
    assert preview.constraint.score_by_qtype == {"单选": 3, "多选": 4, "填空": 4, "解答": 8}


def test_generate_preview_reports_shortage_without_raising():
    session = FakeSession(results=full_row_set())
    preview = paper_plan_service.generate_preview(
        session, make_payload(total_questions=4, total_score=12), user_id=50, now=NOW
    )
    assert preview.ok is False
    codes = {violation.code for violation in preview.violations}
    assert "QTYPE_SHORTAGE" in codes


def test_generate_preview_no_candidates_reports_no_candidates():
    rows = candidate_rows()
    session = FakeSession(results=[rows, [(501, NOW, NOW)], [], []])
    preview = paper_plan_service.generate_preview(
        session, make_payload(kp_ids=[101]), user_id=50, now=NOW
    )
    assert preview.ok is False
    assert preview.items == []
    assert preview.violations[0].code == "NO_CANDIDATES"


def test_replace_item_prefers_same_qtype_and_difficulty_highest_score():
    rows = candidate_rows() + [(504, "单选", 2, True, "mock", 101, Decimal("1.000000"))]
    session = FakeSession(
        results=[rows, [], [], [(504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock")]]
    )
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is True
    assert result.item is not None
    # 504（verified=True, exam/mock 质量分高）应压过 502（未核对）
    assert result.item.question_id == 504


def test_replace_item_falls_back_to_same_qtype_any_difficulty():
    rows = candidate_rows() + [(505, "单选", 4, True, "exam", 101, Decimal("1.000000"))]
    details = [(505, 7, "单选", 4, "题干 505", [], "答案 505", None, True, "exam")]
    session = FakeSession(results=[rows, [], [], details])
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501, 502],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is True
    assert result.item is not None
    assert result.item.question_id == 505  # 同题型里没有 d2 了，退到 d4 的 505


def test_replace_item_returns_reason_when_pool_exhausted():
    session = FakeSession(results=[candidate_rows(), [], [], []])
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501, 502, 503],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is False
    assert result.item is None
    assert result.reason == "没有可替换的候选题"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.paper_plan_service' has no attribute 'generate_preview'`

- [ ] **Step 3: 实现明细装载与两个入口**

先在文件顶部把 `PaperGenerateIn / PaperPreviewOut / PaperReplaceIn / PaperReplaceOut` 加进已有的 `app.schemas.paper` 导入块，再在文件末尾追加：


@dataclass(frozen=True, slots=True)
class QuestionDetail:
    question_id: int
    subject_id: int
    qtype: str
    difficulty: int
    stem_md: str
    options: tuple[dict[str, str], ...]
    answer_md: str | None
    analysis_md: str | None
    verified: bool
    origin: str


def load_question_details(
    session: Session, question_ids: Sequence[int]
) -> dict[int, QuestionDetail]:
    unique = list(dict.fromkeys(int(question_id) for question_id in question_ids))
    if not unique:
        return {}
    rows = session.execute(
        select(
            Question.id,
            Question.subject_id,
            Question.qtype,
            Question.difficulty,
            Question.stem_md,
            Question.options_json,
            Question.answer_md,
            Question.analysis_md,
            Question.verified,
            Question.origin,
        ).where(Question.id.in_(unique))
    ).all()
    details: dict[int, QuestionDetail] = {}
    for (
        question_id,
        subject_id,
        qtype,
        difficulty,
        stem_md,
        options_json,
        answer_md,
        analysis_md,
        verified,
        origin,
    ) in rows:
        options = tuple(
            {"key": str(item.get("key", "")), "text": str(item.get("text", ""))}
            for item in (options_json or [])
        )
        details[int(question_id)] = QuestionDetail(
            question_id=int(question_id),
            subject_id=int(subject_id),
            qtype=str(qtype),
            difficulty=int(difficulty),
            stem_md=str(stem_md),
            options=options,
            answer_md=answer_md,
            analysis_md=analysis_md,
            verified=bool(verified),
            origin=str(origin),
        )
    return details


def kp_ids_by_question(session: Session, question_ids: Sequence[int]) -> dict[int, list[int]]:
    unique = list(dict.fromkeys(int(question_id) for question_id in question_ids))
    if not unique:
        return {}
    rows = session.execute(
        select(QuestionKp.question_id, QuestionKp.kp_id)
        .where(QuestionKp.question_id.in_(unique))
        .order_by(QuestionKp.question_id, QuestionKp.kp_id)
    ).all()
    result: dict[int, list[int]] = {}
    for question_id, kp_id in rows:
        result.setdefault(int(question_id), []).append(int(kp_id))
    return result


def _item_out(
    item: PaperItem,
    detail: QuestionDetail,
    *,
    score: int | None = None,
    parts: ScorePartsOut | None = None,
) -> PaperItemOut:
    return PaperItemOut(
        question_id=item.question_id,
        qtype=item.qtype,
        difficulty=item.difficulty,
        score=item.score if score is None else score,
        kp_ids=list(item.kp_ids),
        parts=parts
        or ScorePartsOut(
            difficulty_match=item.parts.difficulty_match,
            mastery_match=item.parts.mastery_match,
            novelty=item.parts.novelty,
            quality=item.parts.quality,
            total=item.parts.total,
        ),
        subject_id=detail.subject_id,
        stem_md=detail.stem_md,
        options=[OptionOut(**option) for option in detail.options],
        answer_md=detail.answer_md,
        analysis_md=detail.analysis_md,
        verified=detail.verified,
        origin=detail.origin,
    )


def generate_preview(
    session: Session,
    payload: PaperGenerateIn,
    *,
    user_id: int,
    now: datetime,
) -> PaperPreviewOut:
    constraints = build_constraints(payload)
    data = load_candidates(session, constraints, user_id=user_id, now=now)
    try:
        plan = paper_service.plan_paper(
            constraints,
            data.candidates,
            mastery_by_kp=data.mastery_by_kp,
            now=now,
        )
    except paper_service.PaperPlanError as exc:
        raise InvalidParamError(str(exc)) from exc
    details = load_question_details(session, [item.question_id for item in plan.items])
    missing = [item.question_id for item in plan.items if item.question_id not in details]
    if missing:
        raise InvalidParamError(f"候选题已被删除，请重试：{missing[:10]}")
    return PaperPreviewOut(
        constraint=normalized_constraint(constraints),
        seed=plan.seed,
        ok=plan.ok,
        items=[_item_out(item, details[item.question_id]) for item in plan.items],
        total_score=plan.total_score,
        target_score=plan.target_score,
        quota_by_qtype=plan.quota_by_qtype,
        quota_by_difficulty=plan.quota_by_difficulty,
        quota_by_kp=plan.quota_by_kp,
        counts_by_qtype=plan.counts_by_qtype,
        counts_by_difficulty=plan.counts_by_difficulty,
        counts_by_kp=plan.counts_by_kp,
        violations=[
            PaperViolationOut(code=violation.code, message=violation.message, detail=violation.detail)
            for violation in plan.violations
        ],
        warnings=list(plan.warnings),
    )


def replace_item(
    session: Session,
    payload: PaperReplaceIn,
    *,
    user_id: int,
    now: datetime,
) -> PaperReplaceOut:
    constraints = build_constraints(payload)
    data = load_candidates(session, constraints, user_id=user_id, now=now)
    original = next(
        (
            candidate
            for candidate in data.candidates
            if candidate.question_id == payload.replace_question_id
        ),
        None,
    )
    if original is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="原题不在候选池中，无法判断题型与难度"
        )
    pool, _excluded_recent = paper_service.prepare_pool(
        constraints, data.candidates, now=now
    )
    excluded = set(payload.selected_question_ids) | {payload.replace_question_id}
    available = [candidate for candidate in pool if candidate.question_id not in excluded]
    scored = [
        (
            paper_service.score_parts(
                candidate=candidate,
                constraints=constraints,
                mastery_by_kp=data.mastery_by_kp,
                now=now,
            ),
            candidate,
        )
        for candidate in available
    ]
    scored.sort(key=lambda pair: (-pair[0].total, pair[1].question_id))

    chosen = next(
        (
            (parts, candidate)
            for parts, candidate in scored
            if candidate.qtype == original.qtype
            and candidate.difficulty == original.difficulty
        ),
        None,
    )
    if chosen is None:
        chosen = next(
            (
                (parts, candidate)
                for parts, candidate in scored
                if candidate.qtype == original.qtype
            ),
            None,
        )
    if chosen is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="没有可替换的候选题"
        )
    parts, candidate = chosen
    details = load_question_details(session, [candidate.question_id])
    detail = details.get(candidate.question_id)
    if detail is None:
        return PaperReplaceOut(
            replaced=False, item=None, reason="候选题已被删除，请重试"
        )
    item = PaperItem(
        question_id=candidate.question_id,
        qtype=candidate.qtype,
        difficulty=candidate.difficulty,
        score=int(constraints.score_map[candidate.qtype]),
        kp_ids=tuple(kp_id for kp_id, _weight in candidate.kp_weights),
        parts=parts,
    )
    return PaperReplaceOut(replaced=True, item=_item_out(item, detail), reason=None)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: PASS（13 passed）

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/paper_plan_service.py backend/tests/test_paper_plan_service.py
git commit -m "feat(s5-2): 生成预览与无状态换题"
```
---

### Task 4: 保存草稿 + 按 id 读取

**Files:**
- Modify: `backend/app/services/paper_plan_service.py`（追加 `save_draft` / `get_paper`）
- Test: `backend/tests/test_paper_plan_service.py`（追加用例）

**Interfaces:**
- Consumes: Task 2/3 的 `build_constraints` / `normalized_constraint` / `load_question_details` / `kp_ids_by_question`。
- Produces: `save_draft(session, payload: PaperSaveIn, *, user_id) -> PaperOut`；`get_paper(session, *, user_id, paper_id) -> PaperDetailOut`。

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_paper_plan_service.py` 末尾追加：

```python
from app.core.exceptions import ForbiddenError, NotFoundError  # noqa: E402
from app.schemas.paper import PaperSaveIn  # noqa: E402


def _stored_paper(**overrides):  # noqa: ANN003, ANN202
    paper = Paper(
        user_id=50,
        title="期中卷",
        constraint_json={"seed": 7},
        question_ids=[501, 502],
        total_score=11,
        duration_min=60,
        status="草稿",
        generated_by="manual",
    )
    paper.id = 7
    paper.created_at = NOW
    for key, value in overrides.items():
        setattr(paper, key, value)
    return paper


def test_save_draft_recomputes_total_and_forces_draft():
    session = FakeSession(results=[[(501, "单选"), (502, "解答")]])
    payload = PaperSaveIn(
        title="期中卷", constraint=make_payload(total_score=11), question_ids=[501, 502]
    )
    saved = paper_plan_service.save_draft(session, payload, user_id=50)
    assert saved.total_score == 11  # 3 + 8，与入参 total_score 无关
    assert saved.status == "草稿"
    assert session.committed == 1
    assert session.added[0].question_ids == [501, 502]
    assert session.added[0].user_id == 50


def test_save_draft_rejects_missing_question_ids_and_writes_nothing():
    session = FakeSession(results=[[(501, "单选")]])
    payload = PaperSaveIn(title="t", constraint=make_payload(), question_ids=[501, 999])
    with pytest.raises(InvalidParamError, match="999"):
        paper_plan_service.save_draft(session, payload, user_id=50)
    assert session.committed == 0
    assert session.added == []


def test_get_paper_returns_items_in_stored_order_and_reports_missing():
    session = FakeSession(
        results=[
            [(501, 7, "单选", 2, "题干 501", [], "答案 501", None, True, "exam")],
            [(501, 101)],
        ],
        paper=_stored_paper(),
    )
    detail = paper_plan_service.get_paper(session, user_id=50, paper_id=7)
    assert [item.question_id for item in detail.items] == [501]
    assert detail.missing_question_ids == [502]
    assert detail.items[0].parts is None
    assert detail.items[0].score == 3
    assert detail.items[0].kp_ids == [101]
    assert detail.constraint_json == {"seed": 7}


def test_get_paper_forbids_other_users():
    session = FakeSession(paper=_stored_paper())
    with pytest.raises(ForbiddenError):
        paper_plan_service.get_paper(session, user_id=51, paper_id=7)


def test_get_paper_raises_not_found():
    session = FakeSession(paper=None)
    with pytest.raises(NotFoundError):
        paper_plan_service.get_paper(session, user_id=50, paper_id=99)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.paper_plan_service' has no attribute 'save_draft'`

- [ ] **Step 3: 实现保存与读取**

在文件顶部补 `Paper, PaperDetailOut, PaperOut, PaperSaveIn` 的导入（`PaperOut` 等已在 Task 2 的 schema 导入块里则只补缺的），顶部导入区再加：

```python
from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.paper import Paper
```

在 `backend/app/services/paper_plan_service.py` 末尾追加：

```python
def save_draft(session: Session, payload: PaperSaveIn, *, user_id: int) -> PaperOut:
    """保存草稿：总分按题目分值表重算（不信任前端），一次事务提交。"""
    question_ids = list(payload.question_ids)
    rows = session.execute(
        select(Question.id, Question.qtype).where(Question.id.in_(question_ids))
    ).all()
    qtype_by_id = {int(question_id): str(qtype) for question_id, qtype in rows}
    missing = [question_id for question_id in question_ids if question_id not in qtype_by_id]
    if missing:
        raise InvalidParamError(f"题目不存在：{missing[:10]}")
    score_map = paper_service.DEFAULT_SCORE_BY_QTYPE
    total_score = sum(int(score_map[qtype_by_id[question_id]]) for question_id in question_ids)
    constraints = build_constraints(payload.constraint)
    paper = Paper(
        user_id=user_id,
        title=payload.title,
        constraint_json=normalized_constraint(constraints).model_dump(mode="json"),
        question_ids=question_ids,
        total_score=total_score,
        duration_min=payload.duration_min,
        status="草稿",
        generated_by="manual",
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return PaperOut.model_validate(paper)


def get_paper(session: Session, *, user_id: int, paper_id: int) -> PaperDetailOut:
    """读本人试卷：顺序按存库数组；题目被硬删则跳过并如实回报。"""
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    question_ids = [int(question_id) for question_id in paper.question_ids]
    details = load_question_details(session, question_ids)
    kp_map = kp_ids_by_question(
        session, [question_id for question_id in question_ids if question_id in details]
    )
    score_map = paper_service.DEFAULT_SCORE_BY_QTYPE
    items: list[PaperItemOut] = []
    for question_id in question_ids:
        detail = details.get(question_id)
        if detail is None:
            continue
        items.append(
            PaperItemOut(
                question_id=detail.question_id,
                qtype=detail.qtype,
                difficulty=detail.difficulty,
                score=int(score_map[detail.qtype]),
                kp_ids=kp_map.get(detail.question_id, []),
                parts=None,
                subject_id=detail.subject_id,
                stem_md=detail.stem_md,
                options=[OptionOut(**option) for option in detail.options],
                answer_md=detail.answer_md,
                analysis_md=detail.analysis_md,
                verified=detail.verified,
                origin=detail.origin,
            )
        )
    return PaperDetailOut(
        id=paper.id,
        title=paper.title,
        status=paper.status,
        total_score=paper.total_score,
        duration_min=paper.duration_min,
        question_ids=question_ids,
        created_at=paper.created_at,
        constraint_json=paper.constraint_json,
        items=items,
        missing_question_ids=[
            question_id for question_id in question_ids if question_id not in details
        ],
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper_plan_service.py -q`
Expected: PASS（18 passed）

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/paper_plan_service.py backend/tests/test_paper_plan_service.py
git commit -m "feat(s5-2): 保存草稿与按 id 读取试卷"
```

---

### Task 5: 4 个路由 + 路由注册 + 接口测试

**Files:**
- Create: `backend/app/api/v1/papers.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_papers_api.py`

**Interfaces:**
- Consumes: Task 3/4 的 `generate_preview` / `replace_item` / `save_draft` / `get_paper`。
- Produces: HTTP 契约（API.md §8）：`POST /papers/generate`、`POST /papers/replace-item`、`POST /papers`、`GET /papers/{id}`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_papers_api.py`：

```python
"""S5-2 组卷接口：权限、状态码、出参字段与归属隔离。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.paper import Paper
from app.models.user import User

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _user(role: str = "student", user_id: int = 50) -> User:
    user = User(
        username=f"{role}_s52", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = user_id
    return user


class FakeSession:
    """feed 顺序与 service 的查询顺序一致；scalar 只服务 get_current_user。"""

    def __init__(self, *, results=None, paper=None, user=None) -> None:
        self.results = [list(rows) for rows in (results or [])]
        self.paper = paper
        self.user = user
        self.added: list[object] = []
        self.committed = 0

    def execute(self, statement):  # noqa: ANN001, ANN201
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user if "users" in str(statement) else None

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper is not None and self.paper.id == pk else None
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        obj.id = 7
        obj.created_at = NOW


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session: FakeSession, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _payload(**overrides):  # noqa: ANN003, ANN202
    data = {
        "kp_ids": [101],
        "total_questions": 2,
        "qtype_ratio": {"单选": 1.0},
        "difficulty_dist": {"2": 1.0},
        "total_score": 6,
        "seed": 7,
    }
    data.update(overrides)
    return data


def _candidate_rows():  # noqa: ANN202
    return [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (502, "单选", 2, False, "upload", 101, Decimal("0.800000")),
        (503, "解答", 3, True, "textbook", 101, Decimal("1.000000")),
    ]


def _detail_rows():  # noqa: ANN202
    return [
        (501, 7, "单选", 2, "题干 501", [{"key": "A", "text": "选项 A"}], "答案 501", None, True, "exam"),
        (502, 7, "单选", 2, "题干 502", [], "答案 502", None, False, "upload"),
        (503, 7, "解答", 3, "题干 503", [], "答案 503", None, True, "textbook"),
    ]


def _generate_results():  # noqa: ANN202
    return [_candidate_rows(), [], [], _detail_rows()]


def _stored_paper() -> Paper:
    paper = Paper(
        user_id=50,
        title="期中卷",
        constraint_json={"seed": 7},
        question_ids=[501, 502],
        total_score=11,
        duration_min=60,
        status="草稿",
        generated_by="manual",
    )
    paper.id = 7
    paper.created_at = NOW
    return paper


def test_generate_requires_login():
    client = TestClient(app)
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_generate_forbids_teacher():
    client = _client(FakeSession(user=_user("teacher", 9)), _user("teacher", 9))
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_generate_returns_preview_with_items():
    student = _user()
    client = _client(FakeSession(results=_generate_results(), user=student), student)
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ok"] is True
    assert data["seed"] == 7
    assert data["constraint"]["score_by_qtype"] == {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
    assert len(data["items"]) == 2
    assert data["items"][0]["stem_md"].startswith("题干")
    assert data["items"][0]["parts"]["total"] > 0


def test_generate_rejects_empty_kp_ids():
    student = _user()
    client = _client(FakeSession(user=student), student)
    response = client.post("/api/v1/papers/generate", json=_payload(kp_ids=[]))
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_replace_item_returns_new_item():
    student = _user()
    rows = _candidate_rows()
    session = FakeSession(results=[rows, [], [], _detail_rows()], user=student)
    client = _client(session, student)
    body = _payload(
        selected_question_ids=[501, 502, 503], replace_question_id=501
    )
    response = client.post("/api/v1/papers/replace-item", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["replaced"] is False
    assert data["reason"] == "没有可替换的候选题"


def test_save_paper_returns_201_with_recomputed_score():
    student = _user()
    session = FakeSession(results=[[(501, "单选"), (502, "解答")]], user=student)
    client = _client(session, student)
    body = {"title": "期中卷", "constraint": _payload(total_score=11), "question_ids": [501, 502]}
    response = client.post("/api/v1/papers", json=body)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["id"] == 7
    assert data["total_score"] == 11
    assert data["status"] == "草稿"
    assert data["question_ids"] == [501, 502]


def test_save_paper_rejects_missing_question():
    student = _user()
    session = FakeSession(results=[[(501, "单选")]], user=student)
    client = _client(session, student)
    body = {"title": "t", "constraint": _payload(), "question_ids": [501, 999]}
    response = client.post("/api/v1/papers", json=body)
    assert response.status_code == 422
    assert "999" in response.json()["message"]


def test_get_paper_returns_items_and_missing_ids():
    student = _user()
    session = FakeSession(
        results=[
            [(501, 7, "单选", 2, "题干 501", [], "答案 501", None, True, "exam")],
            [(501, 101)],
        ],
        paper=_stored_paper(),
        user=student,
    )
    client = _client(session, student)
    response = client.get("/api/v1/papers/7")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 7
    assert data["items"][0]["question_id"] == 501
    assert data["missing_question_ids"] == [502]


def test_get_paper_forbids_other_user():
    student = _user()
    session = FakeSession(paper=_stored_paper(), user=student)
    client = _client(session, _user("student", 51))
    response = client.get("/api/v1/papers/7")
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_get_paper_returns_404_for_missing_id():
    student = _user()
    session = FakeSession(paper=None, user=student)
    client = _client(session, student)
    response = client.get("/api/v1/papers/999")
    assert response.status_code == 404
    assert response.json()["code"] == 40400
```

注意 `test_replace_item_returns_new_item` 需要「同题型同难度有备选」才 `replaced=true`，上面先覆盖「换不动」分支；再补一条成功分支：

```python
def test_replace_item_replaces_when_candidate_available():
    student = _user()
    rows = _candidate_rows() + [(504, "单选", 2, True, "mock", 101, Decimal("1.000000"))]
    details = [(504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock")]
    session = FakeSession(results=[rows, [], [], details], user=student)
    client = _client(session, student)
    body = _payload(selected_question_ids=[501], replace_question_id=501)
    response = client.post("/api/v1/papers/replace-item", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["replaced"] is True
    assert data["item"]["question_id"] == 504
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_papers_api.py -q`
Expected: FAIL —— 全部 404（路由未注册）

- [ ] **Step 3: 写路由**

`backend/app/api/v1/papers.py`：

```python
"""S5-2 组卷接口（API.md §8）：生成、换题、保存、读取。

路由只做「参数校验 → service → Envelope」；生成/换题不写库，保存才落 papers；
全部 student 且只碰本人数据（归属校验在 paper_plan_service）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.paper import (
    PaperDetailOut,
    PaperGenerateIn,
    PaperOut,
    PaperPreviewOut,
    PaperReplaceIn,
    PaperReplaceOut,
    PaperSaveIn,
)
from app.services import paper_plan_service

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post(
    "/generate", response_model=Envelope[PaperPreviewOut], summary="生成试卷预览"
)
def generate_paper(
    payload: PaperGenerateIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PaperPreviewOut]:
    preview = paper_plan_service.generate_preview(
        session,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    return Envelope(trace_id=get_trace_id(), data=preview)


@router.post(
    "/replace-item",
    response_model=Envelope[PaperReplaceOut],
    summary="换一题（无状态）",
)
def replace_paper_item(
    payload: PaperReplaceIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PaperReplaceOut]:
    result = paper_plan_service.replace_item(
        session,
        payload,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    return Envelope(trace_id=get_trace_id(), data=result)


@router.post("", status_code=201, response_model=Envelope[PaperOut], summary="保存草稿")
def save_paper(
    payload: PaperSaveIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PaperOut]:
    paper = paper_plan_service.save_draft(session, payload, user_id=current_user.id)
    return Envelope(trace_id=get_trace_id(), data=paper)


@router.get("/{paper_id}", response_model=Envelope[PaperDetailOut], summary="读取试卷")
def read_paper(
    paper_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PaperDetailOut]:
    detail = paper_plan_service.get_paper(
        session, user_id=current_user.id, paper_id=paper_id
    )
    return Envelope(trace_id=get_trace_id(), data=detail)
```

- [ ] **Step 4: 注册路由**

`backend/app/api/router.py`：import 列表加 `papers`（字母序在 `notes` 后、`qa` 前），并加一行：

```python
api_router.include_router(papers.router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_papers_api.py -q`
Expected: PASS（11 passed）

- [ ] **Step 6: 全量回归**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS（S5-1 基线 1263 + 新增，无失败）

- [ ] **Step 7: 提交**

```bash
cd study-agent
git add backend/app/api/v1/papers.py backend/app/api/router.py backend/tests/test_papers_api.py
git commit -m "feat(s5-2): 组卷四接口与路由注册"
```

---

### Task 6: 前端类型与 API 封装

**Files:**
- Create: `web/src/types/papers.ts`
- Create: `web/src/api/papers.ts`
- Test: `web/src/api/papers.spec.ts`

**Interfaces:**
- Produces: `generatePaper` / `replacePaperItem` / `savePaper` / `fetchPaper` 与 `PaperPreview` 等类型（Task 7 使用）。

- [ ] **Step 1: 写类型**

`web/src/types/papers.ts`：

```ts
/** S5-2 组卷：与 docs/API.md §8 出参一一对应。 */
export type PaperQuestionType = '单选' | '多选' | '填空' | '解答'

export interface PaperScoreParts {
  difficulty_match: number
  mastery_match: number
  novelty: number
  quality: number
  total: number
}

export interface PaperOption {
  key: string
  text: string
}

export interface PaperItem {
  question_id: number
  qtype: PaperQuestionType
  difficulty: number
  score: number
  kp_ids: number[]
  parts: PaperScoreParts | null
  subject_id: number
  stem_md: string
  options: PaperOption[]
  answer_md: string | null
  analysis_md: string | null
  verified: boolean
  origin: string
}

export interface PaperConstraintEcho {
  kp_ids: number[]
  total_questions: number
  qtype_ratio: Record<string, number>
  difficulty_dist: Record<string, number>
  total_score: number
  duration_min: number | null
  exclude_recent_days: number
  seed: number
  kp_weights: Record<string, number>
  score_by_qtype: Record<string, number>
}

export interface PaperViolation {
  code: string
  message: string
  detail: Record<string, unknown>
}

export interface PaperPreview {
  constraint: PaperConstraintEcho
  seed: number
  ok: boolean
  items: PaperItem[]
  total_score: number
  target_score: number
  quota_by_qtype: Record<string, number>
  quota_by_difficulty: Record<string, number>
  quota_by_kp: Record<string, number>
  counts_by_qtype: Record<string, number>
  counts_by_difficulty: Record<string, number>
  counts_by_kp: Record<string, number>
  violations: PaperViolation[]
  warnings: string[]
}

/** generate / replace / save 共用的约束载荷（JSON 里 difficulty 键是字符串）。 */
export interface PaperConstraintPayload {
  kp_ids: number[]
  total_questions: number
  qtype_ratio: Record<string, number>
  difficulty_dist: Record<string, number>
  total_score: number
  duration_min?: number | null
  exclude_recent_days?: number
  seed?: number
  kp_weights?: Record<string, number>
}

export type PaperGeneratePayload = PaperConstraintPayload

export interface PaperReplacePayload extends PaperConstraintPayload {
  selected_question_ids: number[]
  replace_question_id: number
}

export interface PaperReplaceResult {
  replaced: boolean
  item: PaperItem | null
  reason: string | null
}

export interface PaperSavePayload {
  title: string
  constraint: PaperConstraintPayload
  question_ids: number[]
  duration_min?: number | null
}

export interface PaperSummary {
  id: number
  title: string
  status: string
  total_score: number
  duration_min: number | null
  question_ids: number[]
  created_at: string
}

export interface PaperDetail extends PaperSummary {
  constraint_json: Record<string, unknown>
  items: PaperItem[]
  missing_question_ids: number[]
}
```

- [ ] **Step 2: 写失败测试**

`web/src/api/papers.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchPaper, generatePaper, replacePaperItem, savePaper } from './papers'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('@/api/http', () => ({
  API_PREFIX: '/api/v1',
  default: http,
}))

function envelope<T>(data: T) {
  return { data: { code: 0, message: 'ok', trace_id: 'trace-1', data } }
}

beforeEach(() => {
  http.get.mockReset()
  http.post.mockReset()
})

describe('papers api', () => {
  it('posts generate payload to /papers/generate', async () => {
    http.post.mockResolvedValue(envelope({ ok: true, items: [] }))
    const payload = {
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
    }
    const preview = await generatePaper(payload)
    expect(http.post).toHaveBeenCalledWith('/api/v1/papers/generate', payload)
    expect(preview).toEqual({ ok: true, items: [] })
  })

  it('posts replace payload to /papers/replace-item', async () => {
    http.post.mockResolvedValue(envelope({ replaced: false, item: null, reason: 'x' }))
    const payload = {
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
      selected_question_ids: [1, 2],
      replace_question_id: 1,
    }
    const result = await replacePaperItem(payload)
    expect(http.post).toHaveBeenCalledWith('/api/v1/papers/replace-item', payload)
    expect(result.reason).toBe('x')
  })

  it('posts save payload to /papers', async () => {
    http.post.mockResolvedValue(envelope({ id: 7, title: 't', status: '草稿' }))
    const payload = {
      title: 't',
      constraint: {
        kp_ids: [101],
        total_questions: 2,
        qtype_ratio: { 单选: 1 },
        difficulty_dist: { 2: 1 },
        total_score: 6,
      },
      question_ids: [1],
    }
    const paper = await savePaper(payload)
    expect(http.post).toHaveBeenCalledWith('/api/v1/papers', payload)
    expect(paper.id).toBe(7)
  })

  it('gets paper by id', async () => {
    http.get.mockResolvedValue(envelope({ id: 7, items: [], missing_question_ids: [] }))
    const detail = await fetchPaper(7)
    expect(http.get).toHaveBeenCalledWith('/api/v1/papers/7')
    expect(detail.id).toBe(7)
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd study-agent/web && npm run test:run -- src/api/papers.spec.ts`
Expected: FAIL —— `Cannot find module './papers'`

- [ ] **Step 4: 写封装**

`web/src/api/papers.ts`：

```ts
/** S5-2 组卷：4 个接口，只经 http.ts（拦截器统一带 token 与弹错）。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type {
  PaperDetail,
  PaperGeneratePayload,
  PaperPreview,
  PaperReplacePayload,
  PaperReplaceResult,
  PaperSavePayload,
  PaperSummary,
} from '@/types/papers'

export async function generatePaper(payload: PaperGeneratePayload): Promise<PaperPreview> {
  const resp = await http.post<ApiEnvelope<PaperPreview>>(
    `${API_PREFIX}/papers/generate`,
    payload,
  )
  return resp.data.data
}

export async function replacePaperItem(
  payload: PaperReplacePayload,
): Promise<PaperReplaceResult> {
  const resp = await http.post<ApiEnvelope<PaperReplaceResult>>(
    `${API_PREFIX}/papers/replace-item`,
    payload,
  )
  return resp.data.data
}

export async function savePaper(payload: PaperSavePayload): Promise<PaperSummary> {
  const resp = await http.post<ApiEnvelope<PaperSummary>>(`${API_PREFIX}/papers`, payload)
  return resp.data.data
}

export async function fetchPaper(paperId: number): Promise<PaperDetail> {
  const resp = await http.get<ApiEnvelope<PaperDetail>>(`${API_PREFIX}/papers/${paperId}`)
  return resp.data.data
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd study-agent/web && npm run test:run -- src/api/papers.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```bash
cd study-agent
git add web/src/types/papers.ts web/src/api/papers.ts web/src/api/papers.spec.ts
git commit -m "feat(s5-2): 前端组卷类型与 API 封装"
```

---

### Task 7: 前端页面 + 路由/导航 + 页面测试

**Files:**
- Create: `web/src/views/papers/Generate.vue`
- Create: `web/src/views/papers/Generate.spec.ts`
- Modify: `web/src/router/index.ts`（新增 `/papers/generate`）
- Modify: `web/src/layouts/nav.ts`（「组卷」）
- Modify: `web/src/layouts/MainLayout.spec.ts`（导航 9 → 10）

**Interfaces:**
- Consumes: Task 6 的 `generatePaper` / `replacePaperItem` / `savePaper` 与类型；`@/api/kp` 的 `listSubjects` / `getKpTree`；`@/components/common/{PageHeader,MathText}.vue`。
- Produces: 路由 `paper-generate`，导航项 `papers`。

- [ ] **Step 1: 写页面**

`web/src/views/papers/Generate.vue`：

```vue
<script setup lang="ts">
/** S5-2 组卷页：约束表单 → 生成预览 → 换题/删题/调序 → 保存为草稿（单页，不跳转）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import MathText from '@/components/common/MathText.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { getKpTree, listSubjects } from '@/api/kp'
import { generatePaper, replacePaperItem, savePaper } from '@/api/papers'
import type { KpNode, SubjectOut } from '@/types/kp'
import type {
  PaperConstraintPayload,
  PaperItem,
  PaperPreview,
  PaperQuestionType,
} from '@/types/papers'

const QTYPES: PaperQuestionType[] = ['单选', '多选', '填空', '解答']

interface TreeExpose {
  getCheckedKeys: (leafOnly?: boolean) => number[]
}

const subjects = ref<SubjectOut[]>([])
const subjectCode = ref('')
const kpTree = ref<KpNode[]>([])
const treeRef = ref<TreeExpose | null>(null)
const checkedKpIds = ref<number[]>([])
const loadingSubjects = ref(false)

const form = reactive({
  total_questions: 10,
  total_score: 60,
  duration_min: 60 as number | null,
  exclude_recent_days: 14,
  qtype_ratio: { 单选: 0.4, 多选: 0, 填空: 0.2, 解答: 0.4 } as Record<PaperQuestionType, number>,
  difficulty_dist: [0, 50, 50, 0, 0],
})

const preview = ref<PaperPreview | null>(null)
const generating = ref(false)
const saving = ref(false)
const replacingId = ref<number | null>(null)
const showAnswer = ref(false)

const items = computed<PaperItem[]>(() => preview.value?.items ?? [])
const displayTotal = computed(() => items.value.reduce((sum, item) => sum + item.score, 0))
const canSave = computed(() => items.value.length > 0 && !saving.value)

function onTreeCheck(_node: KpNode, info: { checkedKeys: number[] }): void {
  checkedKpIds.value = [...info.checkedKeys]
}

function setDifficulty(index: number, value: number): void {
  form.difficulty_dist[index] = value
}

async function loadSubjects(): Promise<void> {
  loadingSubjects.value = true
  try {
    subjects.value = await listSubjects()
    if (subjects.value.length && !subjectCode.value) {
      subjectCode.value = subjects.value[0]!.code
      await loadTree()
    }
  } finally {
    loadingSubjects.value = false
  }
}

async function loadTree(): Promise<void> {
  if (!subjectCode.value) return
  const tree = await getKpTree(subjectCode.value)
  kpTree.value = tree.nodes
  checkedKpIds.value = []
}

function onSubjectChange(): void {
  preview.value = null
  void loadTree()
}

/** 生成用载荷：从表单现算；换题/保存用 preview.constraint，保证与卷面同源。 */
function buildConstraint(): PaperConstraintPayload {
  if (checkedKpIds.value.length === 0) throw new Error('请至少选择 1 个知识点')
  const qtype_ratio: Record<string, number> = {}
  for (const qtype of QTYPES) {
    const weight = Number(form.qtype_ratio[qtype])
    if (weight > 0) qtype_ratio[qtype] = weight
  }
  if (Object.keys(qtype_ratio).length === 0) throw new Error('至少给一个题型配置配比')
  const difficulty_dist: Record<string, number> = {}
  form.difficulty_dist.forEach((value, index) => {
    if (value > 0) difficulty_dist[String(index + 1)] = value / 100
  })
  if (Object.keys(difficulty_dist).length === 0) throw new Error('至少给一个难度配置权重')
  return {
    kp_ids: [...checkedKpIds.value],
    total_questions: form.total_questions,
    qtype_ratio,
    difficulty_dist,
    total_score: form.total_score,
    duration_min: form.duration_min ?? null,
    exclude_recent_days: form.exclude_recent_days,
  }
}

function constraintFromPreview(): PaperConstraintPayload {
  const constraint = preview.value!.constraint
  return {
    kp_ids: [...constraint.kp_ids],
    total_questions: constraint.total_questions,
    qtype_ratio: { ...constraint.qtype_ratio },
    difficulty_dist: { ...constraint.difficulty_dist },
    total_score: constraint.total_score,
    duration_min: constraint.duration_min,
    exclude_recent_days: constraint.exclude_recent_days,
    seed: constraint.seed,
  }
}

async function onGenerate(): Promise<void> {
  let payload: PaperConstraintPayload
  try {
    payload = buildConstraint()
  } catch (error) {
    ElMessage.warning((error as Error).message)
    return
  }
  generating.value = true
  try {
    preview.value = await generatePaper(payload)
    if (!preview.value.ok) {
      ElMessage.warning(`题库不足，已出 ${preview.value.items.length} 题`)
    }
  } finally {
    generating.value = false
  }
}

async function onReplace(item: PaperItem): Promise<void> {
  if (!preview.value) return
  replacingId.value = item.question_id
  try {
    const result = await replacePaperItem({
      ...constraintFromPreview(),
      selected_question_ids: items.value.map((row) => row.question_id),
      replace_question_id: item.question_id,
    })
    if (!result.replaced || !result.item) {
      ElMessage.warning(result.reason ?? '没有可替换的候选题')
      return
    }
    const index = preview.value.items.findIndex((row) => row.question_id === item.question_id)
    if (index >= 0) preview.value.items.splice(index, 1, result.item)
  } finally {
    replacingId.value = null
  }
}

function onRemove(item: PaperItem): void {
  if (!preview.value) return
  preview.value.items = preview.value.items.filter((row) => row.question_id !== item.question_id)
}

function move(index: number, delta: number): void {
  if (!preview.value) return
  const list = preview.value.items
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const [row] = list.splice(index, 1)
  if (row) list.splice(target, 0, row)
}

async function onSave(): Promise<void> {
  if (!preview.value || items.value.length === 0) return
  const suggested = `${new Date().toISOString().slice(0, 10)} 组卷（${items.value.length} 题）`
  let title: string
  try {
    const result = await ElMessageBox.prompt('给这份卷子起个名字', '保存为草稿', {
      inputValue: suggested,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (value: string) => (value.trim().length > 0 ? true : '标题不能为空'),
    })
    title = result.value.trim()
  } catch {
    return
  }
  saving.value = true
  try {
    const paper = await savePaper({
      title,
      constraint: constraintFromPreview(),
      question_ids: items.value.map((row) => row.question_id),
      duration_min: preview.value.constraint.duration_min,
    })
    ElMessage.success(`已保存试卷 #${paper.id}`)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadSubjects()
})
</script>

<template>
  <section class="papers-generate">
    <PageHeader
      title="组卷"
      description="按知识点、题型与难度自动配卷；预览可换题、删题、调序，满意后保存为草稿。"
    />

    <el-form class="constraint-form" label-width="96px" @submit.prevent>
      <el-form-item label="学科">
        <el-select
          v-model="subjectCode"
          :loading="loadingSubjects"
          data-testid="subject-select"
          @change="onSubjectChange"
        >
          <el-option
            v-for="subject in subjects"
            :key="subject.code"
            :label="subject.name"
            :value="subject.code"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="知识点">
        <el-tree
          ref="treeRef"
          class="kp-tree"
          :data="kpTree"
          show-checkbox
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          data-testid="kp-tree"
          @check="onTreeCheck"
        />
      </el-form-item>

      <el-form-item label="题量">
        <el-input-number
          v-model="form.total_questions"
          :min="1"
          :max="100"
          data-testid="total-questions"
        />
        <span class="hint">道</span>
      </el-form-item>

      <el-form-item label="总分">
        <el-input-number
          v-model="form.total_score"
          :min="1"
          :max="300"
          data-testid="total-score"
        />
        <span class="hint">分（单选 3 / 多选 4 / 填空 4 / 解答 8，按题型固定）</span>
      </el-form-item>

      <el-form-item label="时长">
        <el-input-number v-model="form.duration_min" :min="1" :max="1440" />
        <span class="hint">分钟（可清空）</span>
      </el-form-item>

      <el-form-item label="题型配比">
        <div class="ratio-row">
          <label v-for="qtype in QTYPES" :key="qtype" class="ratio-item">
            <span>{{ qtype }}</span>
            <el-input-number
              v-model="form.qtype_ratio[qtype]"
              :min="0"
              :max="1"
              :step="0.1"
              :precision="1"
              size="small"
            />
          </label>
        </div>
        <span class="hint">0 表示不出该题型；至少一个大于 0</span>
      </el-form-item>

      <el-form-item label="难度分布">
        <div class="difficulty-grid">
          <div v-for="(value, index) in form.difficulty_dist" :key="index" class="difficulty-item">
            <span class="difficulty-label">d{{ index + 1 }}</span>
            <el-slider
              :model-value="value"
              :max="100"
              :step="10"
              size="small"
              @update:model-value="(next: number) => setDifficulty(index, next)"
            />
          </div>
        </div>
      </el-form-item>

      <el-form-item label="排除近期">
        <el-input-number v-model="form.exclude_recent_days" :min="0" :max="365" />
        <span class="hint">天内做过的题不选（默认 14 天）</span>
      </el-form-item>

      <el-form-item>
        <el-button
          type="primary"
          :loading="generating"
          data-testid="generate-button"
          @click="onGenerate"
        >
          生成试卷
        </el-button>
        <el-button v-if="preview" data-testid="regenerate-button" @click="onGenerate">
          重新生成
        </el-button>
      </el-form-item>
    </el-form>

    <section v-if="preview" class="preview" data-testid="preview">
      <header class="preview-head">
        <div class="preview-meta">
          <span
            class="badge"
            :class="preview.ok ? 'badge-ok' : 'badge-short'"
            data-testid="preview-status"
          >{{ preview.ok ? '约束已满足' : '题库不足' }}</span>
          <span class="score" data-testid="preview-total">总分 {{ displayTotal }} / {{ preview.target_score }}</span>
          <span class="seed">seed {{ preview.seed }}（同种子可复现）</span>
        </div>
        <div class="preview-actions">
          <el-switch v-model="showAnswer" active-text="显示答案" data-testid="answer-toggle" />
          <el-button
            :disabled="!canSave"
            :loading="saving"
            data-testid="save-button"
            @click="onSave"
          >
            保存为草稿
          </el-button>
        </div>
      </header>

      <el-alert
        v-if="preview.violations.length"
        class="violations"
        type="warning"
        :closable="false"
        title="题库不足明细"
      >
        <ul>
          <li
            v-for="violation in preview.violations"
            :key="violation.code + violation.message"
            data-testid="violation"
          >
            {{ violation.message }}
          </li>
        </ul>
        <p v-if="preview.warnings.length" class="hint">{{ preview.warnings.join('；') }}</p>
      </el-alert>

      <el-table :data="preview.items" border class="preview-table">
        <el-table-column label="#" width="52">
          <template #default="{ $index }">{{ $index + 1 }}</template>
        </el-table-column>
        <el-table-column label="题型" prop="qtype" width="72" />
        <el-table-column label="难度" width="64">
          <template #default="{ row }">d{{ row.difficulty }}</template>
        </el-table-column>
        <el-table-column label="知识点" width="120">
          <template #default="{ row }">{{ row.kp_ids.join(', ') }}</template>
        </el-table-column>
        <el-table-column label="分值" prop="score" width="64" />
        <el-table-column label="打分" width="88">
          <template #default="{ row }">{{ row.parts ? row.parts.total.toFixed(4) : '-' }}</template>
        </el-table-column>
        <el-table-column label="题干" min-width="320">
          <template #default="{ row }">
            <div class="stem"><MathText :text="row.stem_md" /></div>
            <ul v-if="row.options.length" class="options">
              <li v-for="option in row.options" :key="option.key">
                {{ option.key }}. {{ option.text }}
              </li>
            </ul>
            <div v-if="showAnswer" class="answers" data-testid="answer-text">
              <p>答案：<MathText :text="row.answer_md ?? '（无）'" /></p>
              <p v-if="row.analysis_md">解析：<MathText :text="row.analysis_md" /></p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="248">
          <template #default="{ row, $index }">
            <el-button
              size="small"
              :loading="replacingId === row.question_id"
              data-testid="replace-button"
              @click="onReplace(row)"
            >
              换一题
            </el-button>
            <el-button
              size="small"
              data-testid="move-up"
              :disabled="$index === 0"
              @click="move($index, -1)"
            >
              上移
            </el-button>
            <el-button
              size="small"
              data-testid="move-down"
              :disabled="$index === preview.items.length - 1"
              @click="move($index, 1)"
            >
              下移
            </el-button>
            <el-button size="small" type="danger" data-testid="remove-button" @click="onRemove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-empty
      v-else
      data-testid="empty-preview"
      description="尚未生成试卷：选好知识点与配比后点「生成试卷」"
    />
  </section>
</template>

<style scoped>
.papers-generate {
  padding: 24px;
}

.constraint-form {
  max-width: 880px;
}

.kp-tree {
  width: 100%;
  max-height: 240px;
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}

.ratio-row,
.difficulty-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  width: 100%;
}

.ratio-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.difficulty-item {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 220px;
}

.difficulty-label {
  width: 24px;
}

.hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.preview {
  margin-top: 24px;
}

.preview-head {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.preview-meta,
.preview-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.badge {
  padding: 2px 10px;
  font-size: 12px;
  border-radius: 999px;
}

.badge-ok {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}

.badge-short {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}

.seed {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.violations {
  margin-bottom: 12px;
}

.violations ul {
  margin: 0;
  padding-left: 18px;
}

.answers {
  margin-top: 6px;
  padding-top: 6px;
  color: var(--el-color-success);
  border-top: 1px dashed var(--el-border-color);
}

.options {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
}
</style>
```

- [ ] **Step 2: 写页面测试**

`web/src/views/papers/Generate.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PaperItem, PaperPreview } from '@/types/papers'

import Generate from './Generate.vue'

const papers = vi.hoisted(() => ({
  generatePaper: vi.fn(),
  replacePaperItem: vi.fn(),
  savePaper: vi.fn(),
}))
vi.mock('@/api/papers', () => papers)

const kpApi = vi.hoisted(() => ({ listSubjects: vi.fn(), getKpTree: vi.fn() }))
vi.mock('@/api/kp', () => kpApi)

vi.mock('@/components/common/MathText.vue', () => ({
  default: { props: ['text'], template: '<span class="math-text">{{ text }}</span>' },
}))

function item(overrides: Partial<PaperItem> = {}): PaperItem {
  return {
    question_id: 501,
    qtype: '单选',
    difficulty: 2,
    score: 3,
    kp_ids: [101],
    parts: { difficulty_match: 1, mastery_match: 0.8, novelty: 1, quality: 1, total: 0.95 },
    subject_id: 7,
    stem_md: '题干一',
    options: [{ key: 'A', text: '选项 A' }],
    answer_md: '答案一',
    analysis_md: null,
    verified: true,
    origin: 'exam',
    ...overrides,
  }
}

function preview(overrides: Partial<PaperPreview> = {}): PaperPreview {
  return {
    constraint: {
      kp_ids: [101],
      total_questions: 2,
      qtype_ratio: { 单选: 1 },
      difficulty_dist: { 2: 1 },
      total_score: 6,
      duration_min: 60,
      exclude_recent_days: 14,
      seed: 7,
      kp_weights: { 101: 1 },
      score_by_qtype: { 单选: 3, 多选: 4, 填空: 4, 解答: 8 },
    },
    seed: 7,
    ok: true,
    items: [item(), item({ question_id: 502, stem_md: '题干二' })],
    total_score: 6,
    target_score: 60,
    quota_by_qtype: { 单选: 2 },
    quota_by_difficulty: { 2: 2 },
    quota_by_kp: { 101: 2 },
    counts_by_qtype: { 单选: 2 },
    counts_by_difficulty: { 2: 2 },
    counts_by_kp: { 101: 2 },
    violations: [],
    warnings: [],
    ...overrides,
  }
}

async function mountView() {
  const wrapper = mount(Generate, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

async function selectKp(wrapper: ReturnType<typeof mount>) {
  const tree = wrapper.findComponent({ name: 'ElTree' })
  tree.vm.$emit('check', { id: 101 }, { checkedKeys: [101] })
  await flushPromises()
}

beforeEach(() => {
  papers.generatePaper.mockReset()
  papers.replacePaperItem.mockReset()
  papers.savePaper.mockReset()
  kpApi.listSubjects.mockReset()
  kpApi.getKpTree.mockReset()
  kpApi.listSubjects.mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  kpApi.getKpTree.mockResolvedValue({
    subject: { id: 7, name: '高中数学', code: 'math', stage: '高中' },
    nodes: [
      {
        id: 101,
        subject_id: 7,
        parent_id: null,
        name: '导数',
        code: 'MATH-D',
        level: 1,
        description: null,
        exam_weight: null,
        order_no: 1,
        children: [],
      },
    ],
  })
})

describe('Generate', () => {
  it('renders default form values', async () => {
    const wrapper = await mountView()
    const questions = wrapper.find('[data-testid="total-questions"] input')
    const score = wrapper.find('[data-testid="total-score"] input')
    expect((questions.element as HTMLInputElement).value).toBe('10')
    expect((score.element as HTMLInputElement).value).toBe('60')
  })

  it('warns and does not call the API without kp selection', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = await mountView()
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(papers.generatePaper).not.toHaveBeenCalled()
    expect(warning).toHaveBeenCalledWith('请至少选择 1 个知识点')
  })

  it('renders the preview and total after generating', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(papers.generatePaper).toHaveBeenCalledWith(
      expect.objectContaining({
        kp_ids: [101],
        total_questions: 10,
        total_score: 60,
        qtype_ratio: { 单选: 0.4, 填空: 0.2, 解答: 0.4 },
      }),
    )
    expect(wrapper.text()).toContain('题干一')
    expect(wrapper.find('[data-testid="preview-total"]').text()).toBe('总分 6 / 60')
  })

  it('shows shortage status and violation messages', async () => {
    papers.generatePaper.mockResolvedValue(
      preview({
        ok: false,
        items: [item()],
        violations: [{ code: 'QTYPE_SHORTAGE', message: '题型「解答」题量不足', detail: {} }],
      }),
    )
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="preview-status"]').text()).toBe('题库不足')
    expect(wrapper.find('[data-testid="violation"]').text()).toContain('题量不足')
  })

  it('replaces a single row', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.replacePaperItem.mockResolvedValue({
      replaced: true,
      item: item({ question_id: 999, stem_md: '换来的题' }),
      reason: null,
    })
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('[data-testid="replace-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(papers.replacePaperItem).toHaveBeenCalledWith(
      expect.objectContaining({
        selected_question_ids: [501, 502],
        replace_question_id: 501,
        seed: 7,
      }),
    )
    expect(wrapper.text()).toContain('换来的题')
    expect(wrapper.text()).not.toContain('题干一')
  })

  it('warns when replacement has no candidate', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    papers.generatePaper.mockResolvedValue(preview())
    papers.replacePaperItem.mockResolvedValue({
      replaced: false,
      item: null,
      reason: '没有可替换的候选题',
    })
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('[data-testid="replace-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(warning).toHaveBeenCalledWith('没有可替换的候选题')
  })

  it('removes a row and recomputes total', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('[data-testid="remove-button"]')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('题干一')
    expect(wrapper.find('[data-testid="preview-total"]').text()).toBe('总分 3 / 60')
  })

  it('moves rows and disables boundary buttons', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="move-up"]')[0]!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('[data-testid="move-down"]')[1]!.attributes('disabled')).toBeDefined()
    await wrapper.findAll('[data-testid="move-up"]')[1]!.trigger('click')
    await flushPromises()
    const firstRow = wrapper.findAll('.el-table__row')[0]!
    expect(firstRow.text()).toContain('题干二')
  })

  it('saves with the prompted title and current question order', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()
    expect(papers.savePaper).toHaveBeenCalledWith(
      expect.objectContaining({
        title: '我的卷',
        question_ids: [501, 502],
        constraint: expect.objectContaining({ seed: 7 }),
      }),
    )
  })

  it('disables save when the paper is empty', async () => {
    papers.generatePaper.mockResolvedValue(preview({ ok: false, items: [], total_score: 0 }))
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="save-button"]').attributes('disabled')).toBeDefined()
  })

  it('hides answers until the toggle is on', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    const wrapper = await mountView()
    await selectKp(wrapper)
    await wrapper.find('[data-testid="generate-button"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('答案一')
    const toggle = wrapper.findComponent({ name: 'ElSwitch' })
    toggle.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(wrapper.text()).toContain('答案一')
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd study-agent/web && npm run test:run -- src/views/papers/Generate.spec.ts`
Expected: FAIL —— `Failed to resolve import "@/views/papers/Generate.vue"`（文件不存在）

- [ ] **Step 4: 加路由**

`web/src/router/index.ts`，在 `questions/import` 路由之后插入：

```ts
        {
          path: 'papers/generate',
          name: 'paper-generate',
          component: () => import('@/views/papers/Generate.vue'),
          meta: { title: '组卷', nav: 'papers', roles: ['student'] },
        },
```

- [ ] **Step 5: 加导航**

`web/src/layouts/nav.ts` 在「题库」之后插入：

```ts
  { label: '组卷', name: 'papers', path: '/papers/generate' },
```

`web/src/layouts/MainLayout.spec.ts`：把 `toHaveLength(9)` 改成 `toHaveLength(10)`，并在断言链接文本的位置补一条：

```ts
    expect(links[3]!.text()).toBe('题库')
    expect(links[4]!.text()).toBe('组卷')
```

（若原测试用别的下标断言，按实际位置调整，保持「组卷」在「题库」之后。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd study-agent/web && npm run test:run -- src/views/papers/Generate.spec.ts src/layouts/MainLayout.spec.ts`
Expected: PASS（Generate 11 + MainLayout 全绿）

- [ ] **Step 7: 类型检查与构建**

Run: `cd study-agent/web && npm run build`
Expected: 退出 0（`vue-tsc -b` 无类型错误）

- [ ] **Step 8: 前端全量测试**

Run: `cd study-agent/web && npm run test:run`
Expected: PASS（S4-8 基线 244 + 新增 15 左右，无失败）

- [ ] **Step 9: 提交**

```bash
cd study-agent
git add web/src/views/papers/Generate.vue web/src/views/papers/Generate.spec.ts \
  web/src/router/index.ts web/src/layouts/nav.ts web/src/layouts/MainLayout.spec.ts
git commit -m "feat(s5-2): 组卷页与预览交互（换题/删题/调序/保存）"
```

---

### Task 8: 真机验收 + 文档同步 + 全量回归

**Files:**
- Create: `.sdd/s5-2/accept.py`、`.sdd/s5-2/check.cjs`、`.sdd/s5-2/acceptance-evidence.md`（仓库外，不进 git）
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-059）、`docs/AI协作开发实施计划.md`（S5-2 勾选）
- Modify: `docs/AGENTS.md` §9.6（组卷 API 锚点）

**Interfaces:**
- Consumes: Task 5 的 4 个接口、Task 7 的页面。
- Produces: 实测证据 + 文档定稿。

- [ ] **Step 1: 全量测试基线**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent/web && npm run test:run
```

Expected: 后端全绿（1263 + 新增 18 + 11 ≈ 1292）、前端全绿（244 + 15 ≈ 259），记录真实数字。

- [ ] **Step 2: 起真机环境**

```bash
# 1) 依赖服务（PG/Redis/MinIO）
cd study-agent/backend && ../.venv/Scripts/python.exe ../scripts/check_services.py   # 期望 3/3
# 2) 后端
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8032 --log-level warning
# 3) 前端（另开一个后台作业）
cd study-agent/web && npm run dev -- --port 5174 --strictPort
```

Token：优先复用 `.sdd/s4-8/student.token`；若 401，用
`cd study-agent/backend && ../.venv/Scripts/python.exe -c "from app.core.security import create_access_token; print(create_access_token(user_id=50, role='student').token)"`
重新签发（用户 50 是真实测试学生）。

- [ ] **Step 3: 写 API 验收脚本并跑**

`.sdd/s5-2/accept.py`（真 HTTP + 真实库；所有数字原样落盘）：

```python
"""S5-2 真机验收：shortage 路径、可行路径换 3 题、保存/读回、权限与参数错误。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8032/api/v1"
OUT_DIR = Path(__file__).resolve().parent          # .sdd/s5-2
REPO_ROOT = OUT_DIR.parents[1]                      # E:\BiShe-AIStudy
TOKEN = (REPO_ROOT / ".sdd" / "s4-8" / "student.token").read_text(encoding="utf-8").strip()

client = httpx.Client(base_url=BASE, timeout=30.0, headers={"Authorization": f"Bearer {TOKEN}"})


def call(method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {"raw": response.text}
    return response.status_code, body


def run() -> int:
    report: dict[str, object] = {"timestamp": datetime.now(timezone.utc).isoformat()}
    summary: list[str] = []

    # 1) 真实可用池测量（直接查库，避免拿接口结果反推）
    sys.path.insert(0, str(REPO_ROOT / "study-agent" / "backend"))
    from sqlalchemy import text as sql_text  # noqa: PLC0415

    from app.core.db import new_session  # noqa: PLC0415

    session = new_session()
    try:
        total_questions = session.execute(sql_text("select count(*) from questions")).scalar_one()
        with_kp = session.execute(
            sql_text("select count(distinct question_id) from question_kps")
        ).scalar_one()
        cutoff = datetime.now(timezone.utc).timestamp() - 14 * 86400
        usable = session.execute(
            sql_text(
                """
                select count(distinct q.id) from questions q
                join question_kps qk on qk.question_id = q.id
                where q.id not in (
                  select question_id from mistakes
                  where user_id = 50
                    and coalesce(last_review_at, created_at) >= to_timestamp(:cutoff)
                )
                """
            ),
            {"cutoff": cutoff},
        ).scalar_one()
        top_kps = session.execute(
            sql_text(
                """
                select qk.kp_id, count(*) as n from question_kps qk
                group by qk.kp_id order by n desc, qk.kp_id limit 5
                """
            )
        ).all()
    finally:
        session.close()
    report["bank"] = {
        "questions": total_questions,
        "with_kp": with_kp,
        "usable_after_recent": usable,
        "top_kps": [[int(kp_id), int(n)] for kp_id, n in top_kps],
    }
    summary.append(f"题库 {total_questions} 题，挂知识点 {with_kp}，可用 {usable}；高频 kp {report['bank']['top_kps']}")

    kp_ids = [int(kp_id) for kp_id, _ in top_kps]

    # 2) 任务卡原句：5 个知识点 + 20 题（真实库预期 shortage）
    status, body = call(
        "POST",
        "/papers/generate",
        json={
            "kp_ids": kp_ids,
            "total_questions": 20,
            "qtype_ratio": {"单选": 0.4, "填空": 0.2, "解答": 0.4},
            "difficulty_dist": {"1": 0.1, "2": 0.3, "3": 0.4, "4": 0.1, "5": 0.1},
            "total_score": 80,
        },
    )
    data = body.get("data") or {}
    report["scenario_20"] = {
        "status": status,
        "ok": data.get("ok"),
        "items": len(data.get("items") or []),
        "total_score": data.get("total_score"),
        "violations": [violation["code"] for violation in data.get("violations") or []],
    }
    summary.append(
        f"5kp+20题 → {status} ok={data.get('ok')} 实出 {len(data.get('items') or [])} 题，"
        f"violations={report['scenario_20']['violations']}"
    )

    # 3) 可行路径：10 题全知识点
    status, body = call(
        "POST",
        "/papers/generate",
        json={
            "kp_ids": kp_ids,
            "total_questions": 10,
            "qtype_ratio": {"单选": 0.4, "填空": 0.2, "解答": 0.4},
            "difficulty_dist": {"1": 0.1, "2": 0.3, "3": 0.4, "4": 0.1, "5": 0.1},
            "total_score": 50,
        },
    )
    preview = body.get("data") or {}
    report["scenario_feasible"] = {
        "status": status,
        "ok": preview.get("ok"),
        "items": len(preview.get("items") or []),
        "total_score": preview.get("total_score"),
        "seed": preview.get("seed"),
    }
    summary.append(
        f"可行卷 → {status} ok={preview.get('ok')} {len(preview.get('items') or [])} 题 / "
        f"{preview.get('total_score')} 分 seed={preview.get('seed')}"
    )

    # 4) 连续换 3 道（每次带当前卷面，防止换重）
    replaced: list[dict[str, object]] = []
    if preview.get("items"):
        constraint = preview.get("constraint") or {}
        selected = [row["question_id"] for row in preview["items"]]
        payload_base = {
            "kp_ids": constraint.get("kp_ids"),
            "total_questions": constraint.get("total_questions"),
            "qtype_ratio": constraint.get("qtype_ratio"),
            "difficulty_dist": constraint.get("difficulty_dist"),
            "total_score": constraint.get("total_score"),
            "seed": constraint.get("seed"),
        }
        for index in range(min(3, len(selected))):
            target = selected[index]
            status, body = call(
                "POST",
                "/papers/replace-item",
                json={
                    **payload_base,
                    "selected_question_ids": selected,
                    "replace_question_id": target,
                },
            )
            result = body.get("data") or {}
            entry = {
                "index": index,
                "replace": target,
                "status": status,
                "replaced": result.get("replaced"),
                "new_id": (result.get("item") or {}).get("question_id"),
                "reason": result.get("reason"),
            }
            replaced.append(entry)
            if result.get("replaced") and result.get("item"):
                selected[index] = result["item"]["question_id"]
        report["replaced"] = replaced
        summary.append(f"换题 3 次：{[entry['replaced'] for entry in replaced]}，卷面 id={selected}")

        # 5) 保存 + 读回
        status, body = call(
            "POST",
            "/papers",
            json={
                "title": "S5-2 真机验收卷",
                "constraint": payload_base,
                "question_ids": selected,
                "duration_min": 60,
            },
        )
        saved = body.get("data") or {}
        report["save"] = {
            "status": status,
            "id": saved.get("id"),
            "total_score": saved.get("total_score"),
            "status_text": saved.get("status"),
        }
        summary.append(f"保存 → {status} id={saved.get('id')} 总分={saved.get('total_score')}")
        if saved.get("id"):
            status, body = call("GET", f"/papers/{saved['id']}")
            detail = body.get("data") or {}
            report["read_back"] = {
                "status": status,
                "items": len(detail.get("items") or []),
                "missing": detail.get("missing_question_ids"),
                "same_order": [row["question_id"] for row in detail.get("items") or []] == selected,
            }
            summary.append(
                f"读回 → {status} {len(detail.get('items') or [])} 题，顺序一致="
                f"{report['read_back']['same_order']}，缺失={detail.get('missing_question_ids')}"
            )

    # 6) 权限与参数
    other = httpx.get(f"{BASE}/papers/{report.get('save', {}).get('id') or 1}")
    unauth = httpx.post(
        f"{BASE}/papers/generate",
        json={"kp_ids": kp_ids, "total_questions": 2, "qtype_ratio": {"单选": 1},
              "difficulty_dist": {"2": 1}, "total_score": 6},
    )
    bad = call("POST", "/papers/generate", json={
        "kp_ids": [], "total_questions": 0, "qtype_ratio": {}, "difficulty_dist": {},
        "total_score": 0,
    })
    report["auth"] = {
        "no_token": unauth.status_code,
        "invalid_body": [bad[0], bad[1].get("code")],
        "missing_paper": call("GET", "/papers/999999")[0],
    }
    summary.append(
        f"无 token={unauth.status_code}，非法入参={bad[0]}/{bad[1].get('code')}，"
        f"不存在试卷={report['auth']['missing_paper']}"
    )

    report["summary"] = summary
    (OUT_DIR / "accept.out.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
```

Run: `cd .sdd/s5-2 && ../../study-agent/.venv/Scripts/python.exe accept.py`
Expected: 脚本退出 0，打印真实测量（20 题卷必然 `ok=False` 含 shortage；可行卷 `ok=True`；换 3 次有 `replaced=true/false` 如实记录；保存/读回顺序一致；401/422/404 如约）。

- [ ] **Step 4: 浏览器验收（CDP，不引依赖）**

`.sdd/s5-2/check.cjs`（Chrome 以 `--remote-debugging-port=9222` 启动）：

```js
// 真浏览器：登录态 → /papers/generate → 勾知识点 → 生成 → 换 3 题 → 保存 → 截图
const fs = require('node:fs')

const path = require('node:path')
const TOKEN = fs
  .readFileSync(path.join(__dirname, '..', 's4-8', 'student.token'), 'utf8')
  .trim()
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json()
  const page = targets.find((target) => target.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message)
      pending.delete(message.id)
    }
  })
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const current = ++id
      pending.set(current, resolve)
      ws.send(JSON.stringify({ id: current, method, params }))
    })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    return result.result?.result?.value
  }

  await new Promise((resolve) => ws.addEventListener('open', resolve))
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: 'http://localhost:5174/papers/generate' })
  await sleep(1500)
  await evaluate(`localStorage.setItem('study-agent-token', ${JSON.stringify(TOKEN)}); 'ok'`)
  await send('Page.navigate', { url: 'http://localhost:5174/papers/generate' })
  await sleep(4000)

  // 勾第一个知识点（真实点击）
  await evaluate(`document.querySelector('.el-tree-node__checkbox').click(); 'ok'`)
  await sleep(300)
  await evaluate(`document.querySelector('[data-testid="generate-button"]').click(); 'ok'`)
  await sleep(3500)
  const previewText = await evaluate(
    `document.querySelector('[data-testid="preview"]')?.innerText ?? 'NO_PREVIEW'`,
  )
  const rowCount = await evaluate(`document.querySelectorAll('.el-table__row').length`)
  const statusText = await evaluate(
    `document.querySelector('[data-testid="preview-status"]')?.innerText ?? ''`,
  )
  const totalText = await evaluate(
    `document.querySelector('[data-testid="preview-total"]')?.innerText ?? ''`,
  )

  // 换 3 题（每点一次等请求回来）
  const replaceResults = []
  for (let index = 0; index < 3; index += 1) {
    const before = await evaluate(
      `document.querySelectorAll('.el-table__row')[${index}]?.innerText ?? ''`,
    )
    await evaluate(
      `document.querySelectorAll('[data-testid="replace-button"]')[${index}]?.click(); 'ok'`,
    )
    await sleep(1500)
    const after = await evaluate(
      `document.querySelectorAll('.el-table__row')[${index}]?.innerText ?? ''`,
    )
    replaceResults.push({ index, changed: before !== after && after !== '' })
  }

  // 保存（弹窗里填标题再确认）
  await evaluate(`document.querySelector('[data-testid="save-button"]').click(); 'ok'`)
  await sleep(800)
  await evaluate(`(() => {
    const input = document.querySelector('.el-message-box__input input')
    if (!input) return 'no-input'
    input.value = 'S5-2 浏览器验收卷'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    const confirm = [...document.querySelectorAll('.el-message-box__btns button')]
      .find((button) => button.textContent.includes('保存'))
    confirm?.click()
    return 'submitted'
  })()`)
  await sleep(2500)
  const afterSaveText = await evaluate(`document.body.innerText`)
  const savedHint = /已保存试卷 #(\d+)/.exec(afterSaveText)?.[0] ?? 'NO_SAVE_HINT'

  const shot = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync('papers-page.png', Buffer.from(shot.result.data, 'base64'))

  const report = {
    url: 'http://localhost:5174/papers/generate',
    rowCount,
    statusText,
    totalText,
    previewHasStem: previewText.includes('题干') || previewText.includes('d'),
    replaceResults,
    savedHint,
    screenshot: 'papers-page.png',
  }
  fs.writeFileSync('browser.json', JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  if (!rowCount || statusText === '') throw new Error('页面没有渲染出预览')
}

main()
```

Run（按 S4-8 的做法起 headless Chrome，再执行脚本）：

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu \
  --remote-debugging-port=9222 --user-data-dir=.sdd/s5-2/chrome-profile about:blank &
cd .sdd/s5-2 && node check.cjs
```

Expected: `rowCount > 0`、`replaceResults` 至少 1 条 `changed=true`、`savedHint` 为 `已保存试卷 #<id>`；截图 `papers-page.png` 人工看一眼。**任何一项没达到就如实写进证据，不许改测法假装通过。**

- [ ] **Step 5: 写验收证据**

`.sdd/s5-2/acceptance-evidence.md`，固定包含：

1. 环境与命令（uvicorn 端口、前端端口、token 来源、数据库）；
2. 真实题库测量（questions / with_kp / usable / top_kps 原始数字）；
3. 场景表：任务卡原句（5kp+20 题）→ 实际 `ok/items/violations`；可行卷 → `ok/items/total/seed`；
4. 换 3 题逐条结果（replaced、新 id、失败原因原话）；
5. 保存与读回（id、总分、顺序一致、缺失 id）；
6. 权限与参数（401/403/404/422 原始状态码）；
7. 浏览器证据（`browser.json` 摘要 + `papers-page.png`）；
8. 未覆盖与已知问题（浏览器 E2E 只测了主链路；`parts=null` 仅在读回接口出现；真实库题量不足导致 20 题卷必然 shortage）。

- [ ] **Step 6: 同步文档**

1. `docs/PROGRESS.md`：
   - 第 8 行阶段状态追加「阶段 5 S5-2 组卷 API + 预览页已交付」；
   - 「最近完成」改为 S5-2（S5-1 顺延为「上一完成」）；
   - 关键口径（S5-2）、验收（S5-2）各一条；
   - 「下一步」改为 S5-3 PDF 导出；
   - 任务清单 `- [ ] S5-2 组卷 API + 预览页` → `[x]`；
   - 待解决问题追加：草稿只创建不管理（改名/删除/列表留 S5-7）、`GET` 读回不含打分（parts=null）、真实库 20 题卷 shortage；
   - 变更日志插 `### 2026-11-13（S5-2）`。
2. `docs/DECISIONS.md` 追加 `## D-059 组卷接口与落库口径（S5-2）`：同步生成、生成不落库、无状态换题（同题型同难度降级）、shortage 200、4 接口、`total_score` INTEGER、`papers` 不扩展列。
3. `docs/AI协作开发实施计划.md`：`- [ ] S5-2 组卷 API + 预览页` → `[x]`。
4. `AGENTS.md` §9.6 在「组卷样例」后追加组卷 API 锚点：

```markdown
- 组卷 API 样例：backend/app/api/v1/papers.py + backend/app/services/paper_plan_service.py + backend/app/models/paper.py + web/src/views/papers/Generate.vue（同步 4 接口；生成/换题不落库，保存才写 papers；换题同题型同难度优先、再同题型任意难度、否则 `replaced=false`；`question_ids` 数组顺序即卷面顺序；总分服务端重算；读回缺题返 `missing_question_ids` 不 500；组卷页默认折叠答案）
```

- [ ] **Step 7: 最后再跑一遍全量**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent/web && npm run test:run && npm run build
```

Expected: 全绿；把真实数字写进 PROGRESS 与提交信息。

- [ ] **Step 8: 提交**

```bash
cd study-agent
git add docs/PROGRESS.md docs/DECISIONS.md docs/AI协作开发实施计划.md AGENTS.md
git commit -m "docs(s5-2): 组卷 API 验收记录与口径定稿（D-059）"
```

完成后向用户报告：测试数字、真机验收结论（含 shortage 与换题成功/失败的真实比例）、已知局限、提交列表；`git push` 由用户执行。
