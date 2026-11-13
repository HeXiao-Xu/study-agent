# S5-4 在线作答与判分 → 掌握度回写 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 学生能在已保存的试卷上作答、自动保存、断点续答、交卷判分，交卷后掌握度按 S4-7 公式回写、错题自动进错题本。

**Architecture:** 新增 `answers` 表（迁移 `0015_s5_4`）；`schemas/answer.py` 定义出入参；`services/answer_service.py` 分三层——判分纯函数（单选/多选自动、填空/解答自评）→ 草稿读取/自动保存（upsert）→ 交卷编排（单事务：answers + mastery + mistakes + papers.status）；路由挂 `api/v1/papers.py` 的 3 个试卷作用域接口；前端新增 `/papers/:id/take` 单页，组卷页保存后加「开始作答」。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Pydantic v2 / Alembic / PostgreSQL 16；Vue 3 + TS + Element Plus + Vitest；复用 S4-7 `mastery_service.record_attempts`、S4-2 `mistake_service`、S5-2 `paper_plan_service.get_paper`、S5-3 KaTeX 渲染组件 `MathText`。

**Spec:** `docs/spec/s5-4-paper-take.md`

## Global Constraints

- 用户已拍板 8 项：3 个试卷作用域接口；交卷前必须全部自评；错题口径「非满分且有作答」；不自动触发错因诊断；响应给每 kp before/after；已提交只读 + 409；**填空也自评**（偏离任务卡「客观题自动判分」，单选/多选仍自动）；单页 + 题号面板 + 自动保存。
- 判分题类：自动 = `单选` / `多选`；自评 = `填空` / `解答`，`self_rated ∈ {0, 0.5, 1}`。
- 交卷是**单事务**：失败整体回滚；`papers.status` 变 `已提交`；不自动入队 LLM。
- `answers.score` 用 `NUMERIC(6,2)`（半对产生 0.5，是「分数用整数」的明确例外）；`mastery` / `stability` 仍走 S4-7 的 Decimal 定型。
- 权限：仅 `student` 且本人；错误复用 `NotFoundError 404`、`ForbiddenError 403`、`ConflictError 409`、`InvalidParamError 422`，不新增错误类型。
- 不新增环境变量、不新增第三方依赖。
- 数据集测试禁止连真库/真 LLM；后端单测全 fake，前端全 mock API。
- 每个 Task 结束跑对应测试并 commit；Conventional Commits 带任务号 `s5-4`。
- 任务卡写「20 题卷」，真实库组不出 20 题（S5-2 实测 19 道可用）；验收按实际可组题量，**如实记录**，不造数据。

---

### Task 1: `answers` 模型与迁移 `0015_s5_4`

**Files:**
- Create: `backend/app/models/answer.py`
- Create: `backend/alembic/versions/0015_s5_4.py`
- Create: `backend/tests/test_answers_migration.py`
- Modify: `backend/tests/test_papers_migration.py`（链头断言）
- Modify: `docs/SCHEMA.md §6.2`

**Interfaces:**
- Produces: `app.models.answer.Answer`，表 `answers`，列 `id/user_id/question_id/paper_id/user_answer_md/is_correct/score/self_rated/time_spent_sec/created_at`；迁移 revision `0015_s5_4`，down_revision `0014_s5_2`。

- [ ] **Step 1: 写迁移契约测试（红）**

`backend/tests/test_answers_migration.py`：

```python
"""S5-4 answers 契约：列、CHECK、部分唯一索引、迁移链头。"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric

from app.models.answer import Answer

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_answer_columns_match_schema():
    assert set(Answer.__table__.columns.keys()) == {
        "id",
        "user_id",
        "question_id",
        "paper_id",
        "user_answer_md",
        "is_correct",
        "score",
        "self_rated",
        "time_spent_sec",
        "created_at",
    }


def test_score_and_self_rated_precision():
    score = Answer.__table__.columns["score"].type
    rated = Answer.__table__.columns["self_rated"].type
    assert isinstance(score, Numeric) and (score.precision, score.scale) == (6, 2)
    assert isinstance(rated, Numeric) and (rated.precision, rated.scale) == (2, 1)


def test_foreign_keys_and_indexes():
    targets = {
        name: {fk.target_fullname for fk in column.foreign_keys}
        for name, column in Answer.__table__.columns.items()
        if column.foreign_keys
    }
    assert targets == {
        "user_id": {"users.id"},
        "question_id": {"questions.id"},
        "paper_id": {"papers.id"},
    }
    indexes = {index.name: index for index in Answer.__table__.indexes}
    assert "ix_answers_user_question" in indexes
    assert "ix_answers_paper_id" in indexes
    partial = indexes["uq_answers_user_paper_question"]
    assert partial.unique is True
    assert str(partial.dialect_options["postgresql"]["where"]) == "paper_id IS NOT NULL"


def test_checks_present():
    names = {constraint.name for constraint in Answer.__table__.constraints}
    assert {"ck_answers_score_nonneg", "ck_answers_self_rated", "ck_answers_time_nonneg"} <= names


def test_migration_chain_head_is_s5_4():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0015_s5_4"
```

同时把 `backend/tests/test_papers_migration.py` 末尾断言由 `"0014_s5_2"` 改为 `"0015_s5_4"`，函数名改为 `test_migration_chain_head_is_s5_4`。

- [ ] **Step 2: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answers_migration.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.models.answer'`。

- [ ] **Step 3: 写模型**

`backend/app/models/answer.py`：

```python
"""作答（SCHEMA §6.2）。

一行 = 学生对一道题的一次作答；`paper_id` 非空时同卷同题只保留一行（自动保存 upsert），
`paper_id` 为空留给后续非试卷练习。草稿行 `is_correct/score/self_rated` 为 NULL，
交卷时一次写齐。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint("score IS NULL OR score >= 0", name="ck_answers_score_nonneg"),
        CheckConstraint(
            "self_rated IS NULL OR self_rated IN (0, 0.5, 1)",
            name="ck_answers_self_rated",
        ),
        CheckConstraint(
            "time_spent_sec IS NULL OR time_spent_sec >= 0",
            name="ck_answers_time_nonneg",
        ),
        Index("ix_answers_user_question", "user_id", "question_id"),
        Index("ix_answers_paper_id", "paper_id"),
        Index(
            "uq_answers_user_paper_question",
            "user_id",
            "paper_id",
            "question_id",
            unique=True,
            postgresql_where=text("paper_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_answers_user_id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_answers_question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    paper_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("papers.id", name="fk_answers_paper_id", ondelete="CASCADE"),
        nullable=True,
    )
    user_answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    self_rated: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    time_spent_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: 写迁移**

`backend/alembic/versions/0015_s5_4.py`：

```python
"""S5-4 在线作答：answers 表（SCHEMA §6.2）。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_s5_4"
down_revision = "0014_s5_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=True),
        sa.Column("user_answer_md", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Numeric(6, 2), nullable=True),
        sa.Column("self_rated", sa.Numeric(2, 1), nullable=True),
        sa.Column("time_spent_sec", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("score IS NULL OR score >= 0", name="ck_answers_score_nonneg"),
        sa.CheckConstraint(
            "self_rated IS NULL OR self_rated IN (0, 0.5, 1)",
            name="ck_answers_self_rated",
        ),
        sa.CheckConstraint(
            "time_spent_sec IS NULL OR time_spent_sec >= 0",
            name="ck_answers_time_nonneg",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_answers_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_answers_question_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name="fk_answers_paper_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_answers_user_question", "answers", ["user_id", "question_id"])
    op.create_index("ix_answers_paper_id", "answers", ["paper_id"])
    op.create_index(
        "uq_answers_user_paper_question",
        "answers",
        ["user_id", "paper_id", "question_id"],
        unique=True,
        postgresql_where=sa.text("paper_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_answers_user_paper_question", table_name="answers")
    op.drop_index("ix_answers_paper_id", table_name="answers")
    op.drop_index("ix_answers_user_question", table_name="answers")
    op.drop_table("answers")
```

- [ ] **Step 5: 跑测试确认绿**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answers_migration.py tests/test_papers_migration.py -q
```

Expected: `9 passed`（新文件 5 + papers 6 中改动 1 条，具体以实际为准）。

- [ ] **Step 6: 真实库升级/回退验证**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic downgrade -1
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m alembic current
```

Expected: `0015_s5_4 (head)`；第二次 upgrade 成功说明 downgrade 干净。随后用 psql 或 Python 检查：

```bash
../.venv/Scripts/python.exe - <<'PY'
import sqlalchemy as sa
from app.core.config import get_settings
engine = sa.create_engine(get_settings().database_url)
with engine.connect() as conn:
    cols = conn.execute(sa.text(
        "select column_name, data_type, numeric_precision, numeric_scale from information_schema.columns "
        "where table_name='answers' order by ordinal_position"
    )).all()
    print(*cols, sep="\n")
    idx = conn.execute(sa.text(
        "select indexname, indexdef from pg_indexes where tablename='answers'"
    )).all()
    print(*idx, sep="\n")
PY
```

Expected: 10 列、`score numeric(6,2)`、`uq_answers_user_paper_question ... WHERE (paper_id IS NOT NULL)`。

- [ ] **Step 7: 同步 SCHEMA**

先把 `docs/SCHEMA.md §6.2 answers` 表里 `score` 一行由 `NUMERIC` 改为 `NUMERIC(6,2)`，再在表下补：

```markdown
> S5-4 落地：`score` 定为 `NUMERIC(6,2)`（半对会产生 2.50，是「分数用整数」的明确例外）；`self_rated` CHECK `(0, 0.5, 1)`；`ck_answers_score_nonneg` / `ck_answers_time_nonneg`；外键 `users.id CASCADE`、`questions.id RESTRICT`、`papers.id CASCADE`；部分唯一索引 `uq_answers_user_paper_question(user_id, paper_id, question_id) WHERE paper_id IS NOT NULL` 支撑自动保存 upsert；迁移 `0015_s5_4`。`paper_id IS NULL` 的非试卷练习不参与唯一（留给后续卡）。
```

并在 `§6.1 papers` 的 S5-2 备注后补一句：

```markdown
> 交卷（S5-4）：`POST /papers/{id}/submit` 成功后 `status` 由 `草稿/已生成` 变 `已提交`；已提交只读，重复交卷 409。
```

- [ ] **Step 8: Commit**

```bash
cd E:/BiShe-AIStudy/study-agent
git add backend/app/models/answer.py backend/alembic/versions/0015_s5_4.py \
  backend/tests/test_answers_migration.py backend/tests/test_papers_migration.py docs/SCHEMA.md
git commit -m "feat(s5-4): answers 表与迁移 0015"
```

---

### Task 2: 判分纯函数与出入参 schema

**Files:**
- Create: `backend/app/schemas/answer.py`
- Create: `backend/app/services/answer_service.py`（本任务只写纯函数部分，文件后续任务继续扩展）
- Create: `backend/tests/test_answer_service.py`（本任务先写判分用例）

**Interfaces:**
- Produces:
  - `schemas/answer.py`：`AnswerSaveIn`、`AnswerSubmitItemIn`、`AnswerSubmitIn`、`PaperBriefOut`、`AnswerRowOut`、`PaperAnswersOut`、`GradedItemOut`、`MasteryDeltaOut`、`PaperSubmitOut`
  - `answer_service.normalize_choice(text: str | None) -> frozenset[str]`
  - `answer_service.grade_objective(qtype: str, answer_md: str | None, user_answer_md: str | None) -> bool`
  - `answer_service.validate_self_rated(value: float | None) -> float`（非法 422；空由调用方决定）
  - `answer_service.grade_item(item: PaperItemOut, answer: AnswerInput) -> GradedItem`（自评缺失抛 `ConflictError`）
  - `answer_service.build_answer_map(items: Sequence[PaperItemOut], payload_items: Sequence[AnswerSubmitItemIn]) -> dict[int, AnswerInput]`（缺/重/卷外 422）
  - `answer_service.missing_self_ratings(items, answers) -> list[int]`
  - `answer_service.grade_paper(items, answers) -> list[GradedItem]`
  - `answer_service.AUTO_QTYPES = ("单选", "多选")`、`SELF_RATED_QTYPES = ("填空", "解答")`

- [ ] **Step 1: 写判分测试（红）**

`backend/tests/test_answer_service.py`：

```python
"""S5-4 判分纯函数：单选/多选自动、填空/解答自评、覆盖校验。"""
from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError, InvalidParamError
from app.schemas.answer import AnswerSubmitItemIn
from app.schemas.paper import OptionOut, PaperItemOut
from app.services import answer_service
from app.services.answer_service import AnswerInput


def _item(
    question_id: int = 501,
    *,
    qtype: str = "单选",
    answer: str | None = "A",
    score: int = 3,
    kp_ids: list[int] | None = None,
) -> PaperItemOut:
    return PaperItemOut(
        question_id=question_id,
        qtype=qtype,
        difficulty=3,
        score=score,
        kp_ids=kp_ids if kp_ids is not None else [117],
        parts=None,
        subject_id=7,
        stem_md="题干",
        options=[OptionOut(key="A", text="A"), OptionOut(key="B", text="B")],
        answer_md=answer,
        analysis_md=None,
        verified=True,
        origin="exam",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", {"A"}),
        ("Ａ", {"A"}),
        ("A,C", {"A", "C"}),
        ("c a", {"A", "C"}),
        ("CA", {"A", "C"}),
        (None, set()),
        ("", set()),
    ],
)
def test_normalize_choice(raw, expected):
    assert answer_service.normalize_choice(raw) == frozenset(expected)


def test_single_choice_auto_grade():
    assert answer_service.grade_objective("单选", "A", "a") is True
    assert answer_service.grade_objective("单选", "A", "B") is False
    assert answer_service.grade_objective("单选", "A", "AB") is False
    assert answer_service.grade_objective("单选", "A", None) is False


def test_multiple_choice_auto_grade_order_insensitive():
    assert answer_service.grade_objective("多选", "AC", "CA") is True
    assert answer_service.grade_objective("多选", "AC", "A,C") is True
    assert answer_service.grade_objective("多选", "AC", "A") is False
    assert answer_service.grade_objective("多选", "AC", "ABC") is False
    assert answer_service.grade_objective("多选", "AC", "") is False


def test_grade_objective_item_scores_full_or_zero():
    correct = answer_service.grade_item(_item(), AnswerInput(question_id=501, user_answer_md="a"))
    assert correct.is_correct is True
    assert float(correct.score) == 3.0
    assert correct.self_rated == 1.0
    wrong = answer_service.grade_item(_item(), AnswerInput(question_id=501, user_answer_md="B"))
    assert wrong.is_correct is False
    assert float(wrong.score) == 0.0
    assert wrong.self_rated == 0.0


def test_self_rated_item_half_credit():
    item = _item(qtype="解答", answer="x=1", score=8)
    graded = answer_service.grade_item(
        item, AnswerInput(question_id=501, user_answer_md="x=1", self_rated=0.5)
    )
    assert float(graded.score) == 4.0
    assert graded.is_correct is False
    assert graded.self_rated == 0.5


def test_self_rated_missing_is_conflict():
    with pytest.raises(ConflictError):
        answer_service.grade_item(_item(qtype="填空"), AnswerInput(question_id=501, user_answer_md="1"))


@pytest.mark.parametrize("value", [0.7, -0.5, 2.0])
def test_self_rated_illegal_value_422(value):
    with pytest.raises(InvalidParamError):
        answer_service.validate_self_rated(value)


@pytest.mark.parametrize("value", [0, 0.5, 1, 0.0, 1.0])
def test_self_rated_allowed_values(value):
    assert answer_service.validate_self_rated(value) == float(value)


def test_build_answer_map_rejects_duplicate_and_unknown():
    items = [_item(501), _item(502)]
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(
            items,
            [
                AnswerSubmitItemIn(question_id=501),
                AnswerSubmitItemIn(question_id=501),
            ],
        )
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(items, [AnswerSubmitItemIn(question_id=999)])


def test_build_answer_map_requires_every_question():
    items = [_item(501), _item(502)]
    with pytest.raises(InvalidParamError):
        answer_service.build_answer_map(items, [AnswerSubmitItemIn(question_id=501)])


def test_build_answer_map_keeps_self_rating_and_time():
    items = [_item(501, qtype="解答", score=8)]
    mapping = answer_service.build_answer_map(
        items,
        [AnswerSubmitItemIn(question_id=501, user_answer_md="x=1", self_rated=0.5, time_spent_sec=42)],
    )
    assert mapping[501].self_rated == 0.5
    assert mapping[501].time_spent_sec == 42


def test_missing_self_ratings_lists_blank_and_solution_only():
    items = [_item(501, qtype="单选"), _item(502, qtype="填空"), _item(503, qtype="解答", score=8)]
    answers = {
        501: AnswerInput(question_id=501, user_answer_md="A"),
        502: AnswerInput(question_id=502, user_answer_md="1"),
        503: AnswerInput(question_id=503, user_answer_md="x=1", self_rated=1.0),
    }
    assert answer_service.missing_self_ratings(items, answers) == [502]


def test_grade_paper_sums_and_keeps_order():
    items = [_item(501, qtype="单选", score=3), _item(502, qtype="解答", score=8)]
    answers = {
        501: AnswerInput(question_id=501, user_answer_md="A"),
        502: AnswerInput(question_id=502, user_answer_md="x=1", self_rated=0.5),
    }
    graded = answer_service.grade_paper(items, answers)
    assert [row.question_id for row in graded] == [501, 502]
    assert answer_service.total_score(graded) == 7.0
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answer_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.schemas.answer'`。

- [ ] **Step 3: 写 schema**

`backend/app/schemas/answer.py`：

```python
"""S5-4 作答接口出入参（API.md §8）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

ALLOWED_SELF_RATINGS = (0.0, 0.5, 1.0)


class AnswerSaveIn(BaseModel):
    """PUT 自动保存：不判分，只存草稿。"""

    user_answer_md: str | None = Field(default=None, max_length=20000)
    time_spent_sec: int | None = Field(default=None, ge=0, le=86400)


class AnswerSubmitItemIn(AnswerSaveIn):
    question_id: int = Field(gt=0)
    self_rated: float | None = None

    @field_validator("self_rated")
    @classmethod
    def _check_self_rated(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if float(value) not in ALLOWED_SELF_RATINGS:
            raise ValueError("自评只能是 0、0.5 或 1")
        return float(value)


class AnswerSubmitIn(BaseModel):
    items: list[AnswerSubmitItemIn] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def _reject_duplicates(cls, value: list[AnswerSubmitItemIn]) -> list[AnswerSubmitItemIn]:
        ids = [item.question_id for item in value]
        if len(set(ids)) != len(ids):
            raise ValueError("items 里的 question_id 不能重复")
        return value


class PaperBriefOut(BaseModel):
    id: int
    title: str
    status: str
    total_score: int


class AnswerRowOut(BaseModel):
    question_id: int
    user_answer_md: str | None
    self_rated: float | None
    is_correct: bool | None
    score: float | None
    time_spent_sec: int | None
    saved: bool


class PaperAnswersOut(BaseModel):
    paper: PaperBriefOut
    items: list[AnswerRowOut]
    submitted: bool
    earned_score: float | None


class GradedItemOut(BaseModel):
    question_id: int
    qtype: str
    is_correct: bool
    score: float
    self_rated: float | None
    user_answer_md: str | None


class MasteryDeltaOut(BaseModel):
    kp_id: int
    kp_name: str
    mastery_before: float | None
    mastery_after: float
    attempts_delta: int


class PaperSubmitOut(BaseModel):
    paper_id: int
    score: float
    total_score: int
    correct_count: int
    question_count: int
    elapsed_sec: int
    items: list[GradedItemOut]
    mastery: list[MasteryDeltaOut]
    mistake_question_ids: list[int]
    missing_question_ids: list[int]
```

- [ ] **Step 4: 写判分纯函数**

`backend/app/services/answer_service.py` 开头（后续任务追加 DB 用例，文件顶部 import 先按最终需要写全，避免来回改）：

```python
"""S5-4 在线作答：判分 → 草稿保存 → 交卷回写（API.md §8）。

判分口径（spec §4）：
- 单选/多选：答案字母集合归一化后比较，顺序/分隔符/全角/大小写不敏感；
- 填空/解答：学生自评 0/0.5/1，得分 = 题分 × 自评；
- 客观题 `self_rated` 只作为「是否满分」的派生值（1.0/0.0），不参与计分。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError, NotFoundError
from app.models.answer import Answer
from app.models.enums import PaperStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.paper import Paper
from app.schemas.answer import (
    AnswerRowOut,
    AnswerSaveIn,
    AnswerSubmitIn,
    AnswerSubmitItemIn,
    GradedItemOut,
    MasteryDeltaOut,
    PaperAnswersOut,
    PaperBriefOut,
    PaperSubmitOut,
)
from app.schemas.paper import PaperItemOut
from app.services import mastery_service, mistake_service, paper_plan_service

AUTO_QTYPES = ("单选", "多选")
SELF_RATED_QTYPES = ("填空", "解答")
ALLOWED_SELF_RATINGS = (0.0, 0.5, 1.0)
_CHOICE_RE = re.compile(r"[A-H]")


@dataclass(frozen=True, slots=True)
class AnswerInput:
    question_id: int
    user_answer_md: str | None = None
    self_rated: float | None = None
    time_spent_sec: int | None = None


@dataclass(frozen=True, slots=True)
class GradedItem:
    question_id: int
    qtype: str
    is_correct: bool
    score: Decimal
    self_rated: float | None
    user_answer_md: str | None
    item_score: int
    difficulty: int
    kp_ids: tuple[int, ...]


def normalize_choice(text: str | None) -> frozenset[str]:
    """题面/答案字母归一化：全角→半角、大写、只留 A-H。"""
    if not text:
        return frozenset()
    return frozenset(_CHOICE_RE.findall(unicodedata.normalize("NFKC", text).upper()))


def grade_objective(
    qtype: str, answer_md: str | None, user_answer_md: str | None
) -> bool:
    expected = normalize_choice(answer_md)
    actual = normalize_choice(user_answer_md)
    if not expected or not actual:
        return False
    if qtype == "单选":
        return len(expected) == 1 and actual == expected
    return actual == expected


def validate_self_rated(value: float | None) -> float:
    if value is None:
        raise ConflictError("填空/解答题必须自评")
    normalized = float(value)
    if normalized not in ALLOWED_SELF_RATINGS:
        raise InvalidParamError("自评只能是 0、0.5 或 1")
    return normalized


def grade_item(item: PaperItemOut, answer: AnswerInput) -> GradedItem:
    if item.qtype in AUTO_QTYPES:
        correct = grade_objective(item.qtype, item.answer_md, answer.user_answer_md)
        score = Decimal(item.score) if correct else Decimal("0")
        rated = 1.0 if correct else 0.0
    else:
        rated = validate_self_rated(answer.self_rated)
        score = (Decimal(item.score) * Decimal(str(rated))).quantize(Decimal("0.01"))
        correct = rated == 1.0
    return GradedItem(
        question_id=item.question_id,
        qtype=item.qtype,
        is_correct=correct,
        score=score,
        self_rated=rated,
        user_answer_md=answer.user_answer_md,
        item_score=item.score,
        difficulty=item.difficulty,
        kp_ids=tuple(item.kp_ids),
    )


def build_answer_map(
    items: Sequence[PaperItemOut], payload_items: Sequence[AnswerSubmitItemIn]
) -> dict[int, AnswerInput]:
    expected = {item.question_id for item in items}
    mapping: dict[int, AnswerInput] = {}
    for payload in payload_items:
        if payload.question_id not in expected:
            raise InvalidParamError(f"题目 {payload.question_id} 不属于该试卷")
        if payload.question_id in mapping:
            raise InvalidParamError(f"题目 {payload.question_id} 重复提交")
        mapping[payload.question_id] = AnswerInput(
            question_id=payload.question_id,
            user_answer_md=payload.user_answer_md,
            self_rated=payload.self_rated,
            time_spent_sec=payload.time_spent_sec,
        )
    missing = [item.question_id for item in items if item.question_id not in mapping]
    if missing:
        raise InvalidParamError(f"缺少题目 {missing[0]} 的作答")
    return mapping


def missing_self_ratings(
    items: Sequence[PaperItemOut], answers: Mapping[int, AnswerInput]
) -> list[int]:
    missing: list[int] = []
    for item in items:
        if item.qtype not in SELF_RATED_QTYPES:
            continue
        answer = answers.get(item.question_id)
        if answer is None or answer.self_rated is None:
            missing.append(item.question_id)
    return missing


def grade_paper(
    items: Sequence[PaperItemOut], answers: Mapping[int, AnswerInput]
) -> list[GradedItem]:
    return [grade_item(item, answers[item.question_id]) for item in items]


def total_score(graded: Sequence[GradedItem]) -> float:
    return round(sum(float(row.score) for row in graded), 2)
```

（`Counter/update/pg_insert/...` 等 import 是后续任务用的；本任务先跑纯函数测试。）

- [ ] **Step 5: 跑测试确认绿**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answer_service.py -q
```

Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
cd E:/BiShe-AIStudy/study-agent
git add backend/app/schemas/answer.py backend/app/services/answer_service.py backend/tests/test_answer_service.py
git commit -m "feat(s5-4): 作答判分纯函数与出入参"
```
---

### Task 3: 草稿读写与交卷编排（单事务）

**Files:**
- Modify: `backend/app/services/answer_service.py`（追加 DB 用例）
- Modify: `backend/app/services/mistake_service.py`（新增 `record_wrong_answer`）
- Modify: `backend/tests/test_answer_service.py`（追加编排用例）
- Modify: `backend/tests/test_mistake_service.py`（追加 2 条）

**Interfaces:**
- Consumes: Task 1 `Answer`、Task 2 判分纯函数、`mastery_service.record_attempts`、`paper_plan_service.get_paper`。
- Produces:
  - `mistake_service.record_wrong_answer(session, *, user_id: int, question_id: int, my_answer_md: str | None, correct_answer_md: str | None = None) -> Mistake`（**不 commit**、不入队）
  - `answer_service.get_answers(session, *, user_id: int, paper_id: int) -> PaperAnswersOut`
  - `answer_service.save_answer(session, *, user_id: int, paper_id: int, question_id: int, payload: AnswerSaveIn) -> AnswerRowOut`
  - `answer_service.submit_paper(session, *, user_id: int, paper_id: int, payload: AnswerSubmitIn, now: datetime | None = None) -> PaperSubmitOut`

- [ ] **Step 1: 写错题回写测试（红）**

在 `backend/tests/test_mistake_service.py` 末尾追加：

```python
def test_record_wrong_answer_creates_without_commit():
    from app.models.mistake import Mistake
    from app.services import mistake_service

    session = FakeSession()

    mistake = mistake_service.record_wrong_answer(
        session, user_id=50, question_id=65, my_answer_md="B", correct_answer_md="C"
    )

    assert isinstance(mistake, Mistake)
    assert mistake.status == "待订正"
    assert mistake.correct_streak == 0
    assert mistake.my_answer_md == "B"
    assert mistake.correct_answer_md == "C"
    assert session.commits == 0
    assert session.added == [mistake]


def test_record_wrong_answer_resets_existing_without_commit():
    from app.models.mistake import Mistake
    from app.services import mistake_service

    existing = Mistake(
        user_id=50,
        question_id=65,
        my_answer_md="old",
        correct_answer_md="old",
        status="已掌握",
        correct_streak=3,
    )
    existing.id = 9
    session = FakeSession(scalar_results=[existing])

    mistake = mistake_service.record_wrong_answer(
        session, user_id=50, question_id=65, my_answer_md="new", correct_answer_md="C"
    )

    assert mistake is existing
    assert mistake.status == "待订正"
    assert mistake.correct_streak == 0
    assert mistake.my_answer_md == "new"
    assert mistake.correct_answer_md == "C"
    assert session.commits == 0
    assert session.added == []
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_mistake_service.py -q -k record_wrong_answer
```

Expected: FAIL `AttributeError: module ... has no attribute 'record_wrong_answer'`。

- [ ] **Step 3: 实现 `record_wrong_answer`**

在 `backend/app/services/mistake_service.py` 的 `create_from_question` 之后加：

```python
def record_wrong_answer(
    session: Session,
    *,
    user_id: int,
    question_id: int,
    my_answer_md: str | None,
    correct_answer_md: str | None = None,
) -> Mistake:
    """交卷回写用：同题复用并重置，只 flush 不 commit、不触发错因诊断。

    与 `create_from_question` 的区别：不做权限/题目存在校验（调用方已经读过卷面），
    不 commit（交卷要和 answers/mastery/papers 同一事务），也不入队诊断（S5-4 D4）。
    并发双交卷由 papers 行锁串行化，所以这里不需要 IntegrityError 兜底。
    """
    existing = session.scalar(
        select(Mistake).where(
            Mistake.user_id == user_id, Mistake.question_id == question_id
        )
    )
    if existing is not None:
        _reset_reentry(existing, my_answer_md=my_answer_md, answer=correct_answer_md)
        session.flush()
        return existing
    mistake = Mistake(
        user_id=user_id,
        question_id=question_id,
        my_answer_md=my_answer_md,
        correct_answer_md=correct_answer_md,
        status=MistakeStatus.TODO.value,
        correct_streak=0,
    )
    session.add(mistake)
    session.flush()
    return mistake
```

- [ ] **Step 4: 跑错题测试确认绿**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_mistake_service.py -q
```

Expected: 全绿（含既有用例）。

- [ ] **Step 5: 写编排测试（红）**

在 `backend/tests/test_answer_service.py` 末尾追加（含 FakeSession 与数据构造）：

```python
from datetime import datetime, timezone
from decimal import Decimal

from app.models.answer import Answer
from app.models.enums import PaperStatus
from app.models.knowledge_point import KnowledgePoint
from app.models.mastery import Mastery
from app.models.paper import Paper
from app.schemas.answer import AnswerSaveIn, AnswerSubmitIn, AnswerSubmitItemIn
from app.schemas.paper import PaperDetailOut

NOW = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None):
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.scalar_statements = []
        self.execute_statements = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def execute(self, statement):
        self.execute_statements.append(statement)
        return _Result()

    def add(self, instance):
        self.added.append(instance)

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _paper_row(*, status: str = "草稿", user_id: int = 50) -> Paper:
    paper = Paper(
        user_id=user_id,
        title="验收卷",
        constraint_json={},
        question_ids=[501, 502],
        total_score=11,
        duration_min=60,
        status=status,
        generated_by="manual",
    )
    paper.id = 8
    paper.created_at = NOW
    return paper


def _detail(items=None, *, status: str = "草稿") -> PaperDetailOut:
    rows = items if items is not None else [
        _item(501, qtype="单选", answer="A", score=3, kp_ids=[117]),
        _item(502, qtype="解答", answer="x=1", score=8, kp_ids=[117, 118]),
    ]
    return PaperDetailOut(
        id=8,
        title="验收卷",
        status=status,
        total_score=11,
        duration_min=60,
        question_ids=[item.question_id for item in rows],
        created_at=NOW,
        constraint_json={},
        items=rows,
        missing_question_ids=[],
    )


def _mastery(kp_id: int, value: str, *, attempts: int = 1) -> Mastery:
    row = Mastery(
        user_id=50,
        kp_id=kp_id,
        mastery=Decimal(value),
        attempts=attempts,
        correct_cnt=1,
        stability=Decimal("3.60"),
    )
    row.id = kp_id
    return row


def _submit_payload() -> AnswerSubmitIn:
    return AnswerSubmitIn(
        items=[
            AnswerSubmitItemIn(question_id=501, user_answer_md="A", time_spent_sec=20),
            AnswerSubmitItemIn(
                question_id=502, user_answer_md="x=1", self_rated=0.5, time_spent_sec=40
            ),
        ]
    )


def test_submit_paper_orchestrates_single_transaction(monkeypatch):
    paper = _paper_row()
    session = FakeSession(
        scalar_results=[paper],
        scalars_results=[
            [_mastery(117, "0.4")],
            [_mastery(117, "0.45"), _mastery(118, "0.058")],
            [KnowledgePoint(id=117, name="函数"), KnowledgePoint(id=118, name="导数")],
        ],
    )
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail())
    attempts: list[dict] = []
    monkeypatch.setattr(
        answer_service.mastery_service,
        "record_attempts",
        lambda *a, **k: attempts.append(k) or [],
    )
    mistakes: list[dict] = []
    monkeypatch.setattr(
        answer_service.mistake_service,
        "record_wrong_answer",
        lambda *a, **k: mistakes.append(k) or object(),
    )

    out = answer_service.submit_paper(
        session, user_id=50, paper_id=8, payload=_submit_payload(), now=NOW
    )

    assert out.paper_id == 8
    assert out.score == 7.0
    assert out.total_score == 11
    assert out.correct_count == 1
    assert out.question_count == 2
    assert out.elapsed_sec == 60
    assert out.mistake_question_ids == [502]
    assert [row.question_id for row in out.items] == [501, 502]
    assert out.items[1].self_rated == 0.5
    assert [(row.kp_id, row.mastery_before, row.mastery_after, row.attempts_delta) for row in out.mastery] == [
        (117, 0.4, 0.45, 2),
        (118, None, 0.058, 1),
    ]
    assert [call["s"] for call in attempts] == [1.0, 0.5]
    assert [call["difficulty"] for call in attempts] == [3, 3]
    assert attempts[0]["kp_ids"] == [117]
    assert attempts[1]["kp_ids"] == [117, 118]
    assert mistakes == [
        {"user_id": 50, "question_id": 502, "my_answer_md": "x=1", "correct_answer_md": "x=1"}
    ]
    assert paper.status == PaperStatus.SUBMITTED.value
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.execute_statements) == 2
    assert "FOR UPDATE" in str(session.scalar_statements[0]).upper()


def test_submit_paper_refuses_already_submitted(monkeypatch):
    paper = _paper_row(status="已提交")
    session = FakeSession(scalar_results=[paper])
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(status="已提交"))

    with pytest.raises(ConflictError):
        answer_service.submit_paper(session, user_id=50, paper_id=8, payload=_submit_payload(), now=NOW)

    assert session.commits == 0
    assert session.execute_statements == []


def test_submit_paper_requires_self_ratings(monkeypatch):
    paper = _paper_row()
    session = FakeSession(scalar_results=[paper])
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail())
    payload = AnswerSubmitIn(
        items=[
            AnswerSubmitItemIn(question_id=501, user_answer_md="A"),
            AnswerSubmitItemIn(question_id=502, user_answer_md="x=1"),
        ]
    )

    with pytest.raises(ConflictError) as excinfo:
        answer_service.submit_paper(session, user_id=50, paper_id=8, payload=payload, now=NOW)

    assert "还有 1 道题未自评" in str(excinfo.value)
    assert session.commits == 0


def test_submit_paper_blank_answer_skips_mistake(monkeypatch):
    paper = _paper_row()
    session = FakeSession(
        scalar_results=[paper],
        scalars_results=[[], [], [KnowledgePoint(id=117, name="函数")]],
    )
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail())
    attempts: list[dict] = []
    monkeypatch.setattr(
        answer_service.mastery_service,
        "record_attempts",
        lambda *a, **k: attempts.append(k) or [],
    )
    mistakes: list[dict] = []
    monkeypatch.setattr(
        answer_service.mistake_service,
        "record_wrong_answer",
        lambda *a, **k: mistakes.append(k) or object(),
    )
    payload = AnswerSubmitIn(
        items=[
            AnswerSubmitItemIn(question_id=501, user_answer_md=None),
            AnswerSubmitItemIn(question_id=502, user_answer_md=None, self_rated=0),
        ]
    )

    out = answer_service.submit_paper(session, user_id=50, paper_id=8, payload=payload, now=NOW)

    assert out.score == 0.0
    assert out.mistake_question_ids == []
    assert mistakes == []
    assert [call["s"] for call in attempts] == [0.0, 0.0]


def test_get_answers_resumes_in_paper_order(monkeypatch):
    session = FakeSession(
        scalars_results=[
            [Answer(user_id=50, question_id=502, paper_id=8, user_answer_md="x=1", time_spent_sec=40)]
        ]
    )
    monkeypatch.setattr(answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail())

    out = answer_service.get_answers(session, user_id=50, paper_id=8)

    assert [row.question_id for row in out.items] == [501, 502]
    assert out.items[0].saved is False and out.items[0].user_answer_md is None
    assert out.items[1].saved is True and out.items[1].time_spent_sec == 40
    assert out.submitted is False
    assert out.earned_score is None


def test_get_answers_returns_earned_score_when_submitted(monkeypatch):
    session = FakeSession(
        scalars_results=[
            [
                Answer(question_id=501, user_answer_md="A", is_correct=True, score=Decimal("3"), self_rated=Decimal("1")),
                Answer(question_id=502, user_answer_md="x=1", is_correct=False, score=Decimal("4"), self_rated=Decimal("0.5")),
            ]
        ]
    )
    monkeypatch.setattr(
        answer_service.paper_plan_service, "get_paper", lambda *a, **k: _detail(status="已提交")
    )

    out = answer_service.get_answers(session, user_id=50, paper_id=8)

    assert out.submitted is True
    assert out.earned_score == 7.0


def test_save_answer_upserts_without_grading():
    paper = _paper_row()
    saved = Answer(user_id=50, question_id=501, paper_id=8, user_answer_md="B", time_spent_sec=12)
    session = FakeSession(
        objects={(Paper, 8): paper},
        scalar_results=[saved],
    )

    out = answer_service.save_answer(
        session, user_id=50, paper_id=8, question_id=501,
        payload=AnswerSaveIn(user_answer_md="B", time_spent_sec=12),
    )

    assert out.question_id == 501
    assert out.user_answer_md == "B"
    assert out.saved is True
    assert out.is_correct is None and out.score is None
    assert len(session.execute_statements) == 1
    compiled = str(session.execute_statements[0].compile(compile_kwargs={"literal_binds": False}))
    assert "ON CONFLICT" in compiled.upper()


def test_save_answer_rejects_submitted_paper():
    paper = _paper_row(status="已提交")
    session = FakeSession(objects={(Paper, 8): paper})

    with pytest.raises(ConflictError):
        answer_service.save_answer(
            session, user_id=50, paper_id=8, question_id=501, payload=AnswerSaveIn(user_answer_md="A")
        )

    assert session.execute_statements == []


def test_save_answer_rejects_question_outside_paper():
    paper = _paper_row()
    session = FakeSession(objects={(Paper, 8): paper})

    with pytest.raises(InvalidParamError):
        answer_service.save_answer(
            session, user_id=50, paper_id=8, question_id=999, payload=AnswerSaveIn(user_answer_md="A")
        )
```

- [ ] **Step 6: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answer_service.py -q -k "submit or get_answers or save_answer"
```

Expected: `AttributeError: module ... has no attribute 'submit_paper'`。

- [ ] **Step 7: 实现 DB 用例**

在 `backend/app/services/answer_service.py` 末尾追加：

```python
def _paper_brief(detail) -> PaperBriefOut:
    return PaperBriefOut(
        id=detail.id, title=detail.title, status=detail.status, total_score=detail.total_score
    )


def _answer_row(question_id: int, row: Answer | None) -> AnswerRowOut:
    return AnswerRowOut(
        question_id=question_id,
        user_answer_md=row.user_answer_md if row else None,
        self_rated=float(row.self_rated) if row and row.self_rated is not None else None,
        is_correct=row.is_correct if row else None,
        score=float(row.score) if row and row.score is not None else None,
        time_spent_sec=row.time_spent_sec if row else None,
        saved=row is not None,
    )


def get_answers(session: Session, *, user_id: int, paper_id: int) -> PaperAnswersOut:
    """续答读取：卷面顺序 + 未答占位；已交卷时附总分。"""
    detail = paper_plan_service.get_paper(session, user_id=user_id, paper_id=paper_id)
    rows = list(
        session.scalars(
            select(Answer).where(Answer.user_id == user_id, Answer.paper_id == paper_id)
        )
    )
    by_question = {row.question_id: row for row in rows}
    items = [
        _answer_row(item.question_id, by_question.get(item.question_id))
        for item in detail.items
    ]
    submitted = detail.status == PaperStatus.SUBMITTED.value
    earned = (
        round(sum(float(row.score or 0) for row in rows), 2) if submitted else None
    )
    return PaperAnswersOut(
        paper=_paper_brief(detail), items=items, submitted=submitted, earned_score=earned
    )


def save_answer(
    session: Session,
    *,
    user_id: int,
    paper_id: int,
    question_id: int,
    payload: AnswerSaveIn,
) -> AnswerRowOut:
    """自动保存：只写草稿，不判分；依赖部分唯一索引 upsert。"""
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    if paper.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，不能再修改答案")
    if question_id not in [int(qid) for qid in paper.question_ids]:
        raise InvalidParamError("题目不属于该试卷")
    statement = (
        pg_insert(Answer)
        .values(
            user_id=user_id,
            paper_id=paper_id,
            question_id=question_id,
            user_answer_md=payload.user_answer_md,
            time_spent_sec=payload.time_spent_sec,
        )
        .on_conflict_do_update(
            index_elements=[Answer.user_id, Answer.paper_id, Answer.question_id],
            index_where=Answer.paper_id.is_not(None),
            set_={
                "user_answer_md": payload.user_answer_md,
                "time_spent_sec": payload.time_spent_sec,
            },
        )
    )
    session.execute(statement)
    session.flush()
    row = session.scalar(
        select(Answer).where(
            Answer.user_id == user_id,
            Answer.paper_id == paper_id,
            Answer.question_id == question_id,
        )
    )
    return _answer_row(question_id, row)


def _mastery_deltas(
    *,
    before: Mapping[int, Mastery],
    after: Mapping[int, Mastery],
    names: Mapping[int, str],
    touched: Counter[int],
) -> list[MasteryDeltaOut]:
    deltas: list[MasteryDeltaOut] = []
    for kp_id in sorted(touched):
        row = after.get(kp_id)
        if row is None:
            continue
        deltas.append(
            MasteryDeltaOut(
                kp_id=kp_id,
                kp_name=names.get(kp_id, ""),
                mastery_before=(
                    float(before[kp_id].mastery) if kp_id in before else None
                ),
                mastery_after=float(row.mastery),
                attempts_delta=touched[kp_id],
            )
        )
    return deltas


def submit_paper(
    session: Session,
    *,
    user_id: int,
    paper_id: int,
    payload: AnswerSubmitIn,
    now: datetime | None = None,
) -> PaperSubmitOut:
    """交卷：判分 → answers upsert → mastery → 错题 → 试卷状态，一次 commit。"""
    moment = now or datetime.now(timezone.utc)
    paper = session.scalar(
        select(Paper).where(Paper.id == paper_id).with_for_update()
    )
    if paper is None:
        raise NotFoundError("试卷不存在")
    if paper.user_id != user_id:
        raise ForbiddenError("无权访问该试卷")
    if paper.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，请勿重复交卷")

    detail = paper_plan_service.get_paper(session, user_id=user_id, paper_id=paper_id)
    if detail.status == PaperStatus.SUBMITTED.value:
        raise ConflictError("试卷已提交，请勿重复交卷")
    answers = build_answer_map(detail.items, payload.items)
    missing = missing_self_ratings(detail.items, answers)
    if missing:
        raise ConflictError(f"还有 {len(missing)} 道题未自评")
    graded = grade_paper(detail.items, answers)

    touched: Counter[int] = Counter()
    for row in graded:
        for kp_id in row.kp_ids:
            touched[kp_id] += 1
    before_rows = (
        {
            row.kp_id: row
            for row in session.scalars(
                select(Mastery).where(
                    Mastery.user_id == user_id, Mastery.kp_id.in_(list(touched))
                )
            )
        }
        if touched
        else {}
    )

    for row in graded:
        session.execute(
            pg_insert(Answer)
            .values(
                user_id=user_id,
                paper_id=paper_id,
                question_id=row.question_id,
                user_answer_md=row.user_answer_md,
                is_correct=row.is_correct,
                score=row.score,
                self_rated=Decimal(str(row.self_rated)) if row.self_rated is not None else None,
                time_spent_sec=answers[row.question_id].time_spent_sec,
            )
            .on_conflict_do_update(
                index_elements=[Answer.user_id, Answer.paper_id, Answer.question_id],
                index_where=Answer.paper_id.is_not(None),
                set_={
                    "user_answer_md": row.user_answer_md,
                    "is_correct": row.is_correct,
                    "score": row.score,
                    "self_rated": (
                        Decimal(str(row.self_rated)) if row.self_rated is not None else None
                    ),
                    "time_spent_sec": answers[row.question_id].time_spent_sec,
                },
            )
        )
        if row.kp_ids:
            mastery_service.record_attempts(
                session,
                user_id=user_id,
                kp_ids=list(row.kp_ids),
                s=float(row.self_rated),
                difficulty=row.difficulty,
                now=moment,
            )

    after_rows = (
        {
            row.kp_id: row
            for row in session.scalars(
                select(Mastery).where(
                    Mastery.user_id == user_id, Mastery.kp_id.in_(list(touched))
                )
            )
        }
        if touched
        else {}
    )
    names = (
        {
            kp.id: kp.name
            for kp in session.scalars(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(list(touched)))
            )
        }
        if touched
        else {}
    )

    mistake_ids: list[int] = []
    for row, item in zip(graded, detail.items):
        answered = bool((row.user_answer_md or "").strip())
        if row.score < row.item_score and answered:
            mistake_service.record_wrong_answer(
                session,
                user_id=user_id,
                question_id=row.question_id,
                my_answer_md=row.user_answer_md,
                correct_answer_md=item.answer_md,
            )
            mistake_ids.append(row.question_id)

    paper.status = PaperStatus.SUBMITTED.value
    result = PaperSubmitOut(
        paper_id=paper_id,
        score=total_score(graded),
        total_score=detail.total_score,
        correct_count=sum(1 for row in graded if row.is_correct),
        question_count=len(graded),
        elapsed_sec=sum(answer.time_spent_sec or 0 for answer in answers.values()),
        items=[
            GradedItemOut(
                question_id=row.question_id,
                qtype=row.qtype,
                is_correct=row.is_correct,
                score=float(row.score),
                self_rated=row.self_rated,
                user_answer_md=row.user_answer_md,
            )
            for row in graded
        ],
        mastery=_mastery_deltas(
            before=before_rows,
            after=after_rows,
            names=names,
            touched=touched,
        ),
        mistake_question_ids=mistake_ids,
        missing_question_ids=list(detail.missing_question_ids),
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result
```

> 说明：不需要 `update`——试卷状态用行锁 + ORM 赋值，不再发条件 UPDATE。

- [ ] **Step 8: 跑编排测试确认绿**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answer_service.py tests/test_mistake_service.py -q
```

Expected: 全绿。若 `test_submit_paper_orchestrates_single_transaction` 因 `KnowledgePoint(id=...)` 不接受 `id` 构造失败，改为先构造再赋值 `kp.id = 117`（项目模型惯例）。

- [ ] **Step 9: Commit**

```bash
cd E:/BiShe-AIStudy/study-agent
git add backend/app/services/answer_service.py backend/app/services/mistake_service.py \
  backend/tests/test_answer_service.py backend/tests/test_mistake_service.py
git commit -m "feat(s5-4): 草稿读写与交卷单事务编排"
```

---

### Task 4: 3 个接口 + API.md 契约

**Files:**
- Modify: `backend/app/api/v1/papers.py`
- Create: `backend/tests/test_answers_api.py`
- Modify: `docs/API.md §8`

**Interfaces:**
- Produces:
  - `GET /api/v1/papers/{paper_id}/answers` → `Envelope[PaperAnswersOut]`
  - `PUT /api/v1/papers/{paper_id}/answers/{question_id}` → `Envelope[AnswerRowOut]`
  - `POST /api/v1/papers/{paper_id}/submit` → `Envelope[PaperSubmitOut]`

- [ ] **Step 1: 写接口测试（红）**

`backend/tests/test_answers_api.py`：

```python
"""S5-4 作答接口：鉴权、入参校验、错误码与 Envelope。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.answer import (
    AnswerRowOut,
    MasteryDeltaOut,
    PaperAnswersOut,
    PaperBriefOut,
    PaperSubmitOut,
)
from app.services import answer_service


def _user(role: str = "student") -> User:
    user = User(username="student_s54", nickname="小五", grade="高二", role=role, password_hash="x")
    user.id = 50
    return user


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class FakeAuthSession:
    """只服务 get_current_user 的回表；业务 service 已被 monkeypatch。"""

    def __init__(self, user: User) -> None:
        self.user = user

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.user if model is User else None

    def close(self) -> None:
        return None


def _client(user: User | None = None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeAuthSession(user or _user())
    client = TestClient(app)
    if user is not None:
        token = create_access_token(user_id=user.id, role=user.role).token
        client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _answers_out() -> PaperAnswersOut:
    return PaperAnswersOut(
        paper=PaperBriefOut(id=8, title="验收卷", status="草稿", total_score=11),
        items=[
            AnswerRowOut(
                question_id=501, user_answer_md="A", self_rated=None, is_correct=None,
                score=None, time_spent_sec=20, saved=True,
            )
        ],
        submitted=False,
        earned_score=None,
    )


def _submit_out() -> PaperSubmitOut:
    return PaperSubmitOut(
        paper_id=8, score=7.0, total_score=11, correct_count=1, question_count=2,
        elapsed_sec=60,
        items=[],
        mastery=[MasteryDeltaOut(kp_id=117, kp_name="函数", mastery_before=0.4, mastery_after=0.45, attempts_delta=1)],
        mistake_question_ids=[502],
        missing_question_ids=[],
    )


def test_answers_require_login_returns_401():
    response = _client().get("/api/v1/papers/8/answers")
    assert response.status_code == 401


def test_get_answers_returns_envelope(monkeypatch):
    monkeypatch.setattr(answer_service, "get_answers", lambda *a, **k: _answers_out())
    response = _client(_user()).get("/api/v1/papers/8/answers")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["paper"]["id"] == 8
    assert body["data"]["items"][0]["saved"] is True


def test_get_answers_forbidden_returns_403(monkeypatch):
    def _boom(*a, **k):
        raise ForbiddenError("无权访问该试卷")

    monkeypatch.setattr(answer_service, "get_answers", _boom)
    response = _client(_user()).get("/api/v1/papers/8/answers")
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_get_answers_missing_returns_404(monkeypatch):
    def _boom(*a, **k):
        raise NotFoundError("试卷不存在")

    monkeypatch.setattr(answer_service, "get_answers", _boom)
    response = _client(_user()).get("/api/v1/papers/999/answers")
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_put_answer_autosaves(monkeypatch):
    captured: dict[str, object] = {}

    def _save(session, **kwargs):
        captured.update(kwargs)
        return _answers_out().items[0]

    monkeypatch.setattr(answer_service, "save_answer", _save)
    response = _client(_user()).put(
        "/api/v1/papers/8/answers/501",
        json={"user_answer_md": "A", "time_spent_sec": 20},
    )

    assert response.status_code == 200
    assert response.json()["data"]["question_id"] == 501
    assert captured["paper_id"] == 8
    assert captured["question_id"] == 501
    assert captured["payload"].user_answer_md == "A"


def test_put_answer_rejects_negative_time_422():
    response = _client(_user()).put(
        "/api/v1/papers/8/answers/501",
        json={"user_answer_md": "A", "time_spent_sec": -1},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_put_answer_submitted_409(monkeypatch):
    def _boom(*a, **k):
        raise ConflictError("试卷已提交，不能再修改答案")

    monkeypatch.setattr(answer_service, "save_answer", _boom)
    response = _client(_user()).put(
        "/api/v1/papers/8/answers/501", json={"user_answer_md": "A"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40900


def test_submit_paper_returns_summary(monkeypatch):
    monkeypatch.setattr(answer_service, "submit_paper", lambda *a, **k: _submit_out())
    response = _client(_user()).post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501, "user_answer_md": "A", "time_spent_sec": 20}]},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["score"] == 7.0
    assert body["mastery"][0]["kp_name"] == "函数"
    assert body["mistake_question_ids"] == [502]


def test_submit_paper_rejects_duplicate_question_ids_422():
    response = _client(_user()).post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501}, {"question_id": 501}]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_submit_paper_rejects_bad_self_rating_422():
    response = _client(_user()).post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501, "self_rated": 0.7}]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_submit_paper_unrated_409(monkeypatch):
    def _boom(*a, **k):
        raise ConflictError("还有 1 道题未自评")

    monkeypatch.setattr(answer_service, "submit_paper", _boom)
    response = _client(_user()).post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 502, "user_answer_md": "x=1"}]},
    )
    assert response.status_code == 409
    assert "还有 1 道题未自评" in response.json()["message"]


def test_submit_paper_requires_student_role(monkeypatch):
    monkeypatch.setattr(answer_service, "submit_paper", lambda *a, **k: _submit_out())
    response = _client(_user(role="teacher")).post(
        "/api/v1/papers/8/submit", json={"items": [{"question_id": 501}]}
    )
    assert response.status_code == 403
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answers_api.py -q
```

Expected: 除 401 外全部 404/405（路由不存在）。

- [ ] **Step 3: 加路由**

`backend/app/api/v1/papers.py`：import 区补

```python
from app.schemas.answer import AnswerRowOut, AnswerSaveIn, AnswerSubmitIn, PaperAnswersOut, PaperSubmitOut
from app.services import answer_service, paper_plan_service, pdf_service
```

在 `read_paper` 之前加（顺序不敏感，但放 `export.pdf` 后面便于阅读）：

```python
@router.get("/{paper_id}/answers", response_model=Envelope[PaperAnswersOut])
def read_paper_answers(
    paper_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperAnswersOut]:
    """续答：卷面顺序 + 已保存草稿；已交卷附总分。"""
    data = answer_service.get_answers(session, user_id=user.id, paper_id=paper_id)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.put(
    "/{paper_id}/answers/{question_id}", response_model=Envelope[AnswerRowOut]
)
def save_paper_answer(
    paper_id: int,
    question_id: int,
    payload: AnswerSaveIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[AnswerRowOut]:
    """自动保存单题草稿，不判分。"""
    data = answer_service.save_answer(
        session,
        user_id=user.id,
        paper_id=paper_id,
        question_id=question_id,
        payload=payload,
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/{paper_id}/submit", response_model=Envelope[PaperSubmitOut])
def submit_paper(
    paper_id: int,
    payload: AnswerSubmitIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperSubmitOut]:
    """交卷：判分 + 掌握度回写 + 错题入库，单事务。"""
    data = answer_service.submit_paper(
        session,
        user_id=user.id,
        paper_id=paper_id,
        payload=payload,
        now=datetime.now(timezone.utc),
    )
    return Envelope(trace_id=get_trace_id(), data=data)
```

- [ ] **Step 4: 跑接口测试确认绿**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answers_api.py tests/test_answer_service.py tests/test_pdf_api.py -q
```

Expected: 全绿（路由顺序不影响 `/{paper_id}`）。

- [ ] **Step 5: 改 API.md**

把 `docs/API.md §8` 的 `### POST /api/v1/answers` 整段（含 TODO）替换为：

```markdown
### GET /api/v1/papers/{id}/answers
- 权限：student（本人）；不存在 404/40400，别人的 403/40300
- 类型：同步
- 出参 `Envelope[PaperAnswersOut]`：`paper {id,title,status,total_score}` + `items`（按卷面顺序，未答也占位 `saved=false`）+ `submitted` + `earned_score`（未交卷为 null）
- 说明：支持中断续答；题目被硬删则跳过，不 500（与 `GET /papers/{id}` 一致）

### PUT /api/v1/papers/{id}/answers/{question_id}
- 权限：student（本人）
- 入参：`{"user_answer_md": "AC", "time_spent_sec": 48}`；`user_answer_md` 可 null（清除）、≤20000 字；`time_spent_sec` 0–86400 可 null
- 行为：只存草稿不判分（`is_correct/score/self_rated` 保持 NULL），同卷同题 upsert
- 错误：试卷不存在 404/40400、别人的 403/40300、已提交 409/40900、题目不在卷内 422/42200

### POST /api/v1/papers/{id}/submit
- 权限：student（本人）
- 入参：`{"items": [{"question_id": 501, "user_answer_md": "A", "self_rated": null, "time_spent_sec": 32}]}`；必须覆盖卷内每道现存题一次，题号重复/卷外 422/42200
- 判分：单选/多选自动（字母集合归一化，顺序/全半角/大小写不敏感）；**填空/解答必须自评 0/0.5/1**，`score = 题分 × 自评`
- 行为（单事务）：写 `answers` → 按知识点 `mastery` 回写（S4-7 公式）→ 非满分且有作答的题写入错题本（复用并重置，不自动诊断）→ `papers.status='已提交'`
- 出参 `Envelope[PaperSubmitOut]`：`score/total_score/correct_count/question_count/elapsed_sec/items/mastery/mistake_question_ids/missing_question_ids`；`mastery` 每项 `{kp_id,kp_name,mastery_before,mastery_after,attempts_delta}`，无既有行时 `mastery_before=null`（未评估）
- 错误：不存在 404、别人的 403、已提交 409/40900、填空/解答未自评 409/40900（消息「还有 N 道题未自评」）、`self_rated` 非法 422/42200
- 说明：交卷后只读；重复交卷/再自动保存 409，不重复累计掌握度
```

- [ ] **Step 6: 跑后端相关测试并提交**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_answers_api.py tests/test_answer_service.py tests/test_papers_api.py -q
cd E:/BiShe-AIStudy/study-agent
git add backend/app/api/v1/papers.py backend/tests/test_answers_api.py docs/API.md
git commit -m "feat(s5-4): 续答/自动保存/交卷 3 个接口与契约"
```

---

### Task 5: 前端作答页 `Take.vue` + 组卷页入口

**Files:**
- Modify: `web/src/types/papers.ts`
- Modify: `web/src/api/papers.ts`
- Modify: `web/src/router/index.ts`
- Create: `web/src/views/papers/Take.vue`
- Create: `web/src/views/papers/Take.spec.ts`
- Modify: `web/src/views/papers/Generate.vue`
- Modify: `web/src/views/papers/Generate.spec.ts`
- Modify: `web/src/api/papers.spec.ts`

**Interfaces:**
- Produces（types）：
  ```ts
  export interface PaperAnswerRow { question_id: number; user_answer_md: string | null; self_rated: number | null; is_correct: boolean | null; score: number | null; time_spent_sec: number | null; saved: boolean }
  export interface PaperAnswers { paper: { id: number; title: string; status: PaperStatus; total_score: number }; items: PaperAnswerRow[]; submitted: boolean; earned_score: number | null }
  export interface PaperAnswerPayload { user_answer_md: string | null; time_spent_sec: number | null }
  export interface PaperSubmitItem { question_id: number; user_answer_md: string | null; self_rated: number | null; time_spent_sec: number | null }
  export interface PaperSubmitPayload { items: PaperSubmitItem[] }
  export interface MasteryDelta { kp_id: number; kp_name: string; mastery_before: number | null; mastery_after: number; attempts_delta: number }
  export interface PaperSubmitItemResult { question_id: number; qtype: string; is_correct: boolean; score: number; self_rated: number | null; user_answer_md: string | null }
  export interface PaperSubmitResult { paper_id: number; score: number; total_score: number; correct_count: number; question_count: number; elapsed_sec: number; items: PaperSubmitItemResult[]; mastery: MasteryDelta[]; mistake_question_ids: number[]; missing_question_ids: number[] }
  ```
- Produces（api）：`getPaperAnswers(id)`、`savePaperAnswer(id, questionId, payload)`、`submitPaper(id, payload)`。
- 路由：`/papers/:id/take`，name `paper-take`。

- [ ] **Step 1: 写前端测试（红）**

`web/src/api/papers.spec.ts` 追加：

```ts
  it('loads saved answers for resume', async () => {
    http.get.mockResolvedValue(envelope({ submitted: false }))
    await getPaperAnswers(8)
    expect(http.get).toHaveBeenCalledWith('/api/v1/papers/8/answers')
  })

  it('auto-saves one answer with time spent', async () => {
    http.put = vi.fn().mockResolvedValue(envelope({ question_id: 501 }))
    await savePaperAnswer(8, 501, { user_answer_md: 'A', time_spent_sec: 12 })
    expect(http.put).toHaveBeenCalledWith('/api/v1/papers/8/answers/501', {
      user_answer_md: 'A',
      time_spent_sec: 12,
    })
  })

  it('submits the whole paper', async () => {
    http.post.mockResolvedValue(envelope({ paper_id: 8, score: 7 }))
    const result = await submitPaper(8, {
      items: [{ question_id: 501, user_answer_md: 'A', self_rated: null, time_spent_sec: 12 }],
    })
    expect(http.post.mock.calls[0]![0]).toBe('/api/v1/papers/8/submit')
    expect(result.score).toBe(7)
  })
```

并把文件顶部 hoisted `http` 与 import 补上 `put`、`getPaperAnswers`、`savePaperAnswer`、`submitPaper`；`beforeEach` 里 `http.put.mockReset()`。注意 `papers api` 现有 import 行：

```ts
import {
  exportPaperPdf,
  generatePaper,
  getPaper,
  getPaperAnswers,
  replacePaperItem,
  savePaper,
  savePaperAnswer,
  submitPaper,
} from './papers'
```

`web/src/views/papers/Take.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  PaperAnswerRow,
  PaperAnswers,
  PaperDetail,
  PaperItem,
  PaperSubmitResult,
} from '@/types/papers'

const papers = vi.hoisted(() => ({
  getPaper: vi.fn(),
  getPaperAnswers: vi.fn(),
  savePaperAnswer: vi.fn(),
  submitPaper: vi.fn(),
}))
vi.mock('@/api/papers', () => papers)

const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '8' } }),
  useRouter: () => router,
}))

vi.mock('@/components/common/MathText.vue', () => ({
  default: { props: ['text'], template: '<span class="math-text">{{ text }}</span>' },
}))

import Take from './Take.vue'

function item(overrides: Partial<PaperItem> = {}): PaperItem {
  return {
    question_id: 501,
    qtype: '解答',
    difficulty: 3,
    score: 8,
    kp_ids: [117],
    parts: null,
    subject_id: 7,
    stem_md: '解方程 $x+1=2$',
    options: [],
    answer_md: 'x=1',
    analysis_md: '移项即可',
    verified: true,
    origin: 'exam',
    ...overrides,
  }
}

function detail(items: PaperItem[] = [item()]): PaperDetail {
  return {
    id: 8,
    title: '验收卷',
    status: '草稿',
    total_score: 8,
    duration_min: 60,
    question_ids: items.map((row) => row.question_id),
    created_at: '2026-11-13T08:00:00+00:00',
    constraint_json: {},
    items,
    missing_question_ids: [],
  }
}

function row(overrides: Partial<PaperAnswerRow> = {}): PaperAnswerRow {
  return {
    question_id: 501,
    user_answer_md: null,
    self_rated: null,
    is_correct: null,
    score: null,
    time_spent_sec: null,
    saved: false,
    ...overrides,
  }
}

function answers(overrides: Partial<PaperAnswers> = {}): PaperAnswers {
  return {
    paper: { id: 8, title: '验收卷', status: '草稿', total_score: 8 },
    items: [row()],
    submitted: false,
    earned_score: null,
    ...overrides,
  }
}

function submitResult(overrides: Partial<PaperSubmitResult> = {}): PaperSubmitResult {
  return {
    paper_id: 8,
    score: 8,
    total_score: 8,
    correct_count: 1,
    question_count: 1,
    elapsed_sec: 30,
    items: [
      {
        question_id: 501,
        qtype: '解答',
        is_correct: true,
        score: 8,
        self_rated: 1,
        user_answer_md: 'x=1',
      },
    ],
    mastery: [
      {
        kp_id: 117,
        kp_name: '函数',
        mastery_before: null,
        mastery_after: 0.117,
        attempts_delta: 1,
      },
    ],
    mistake_question_ids: [],
    missing_question_ids: [],
    ...overrides,
  }
}

async function mountTake() {
  const wrapper = mount(Take, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

async function waitAutosave() {
  await new Promise((resolve) => setTimeout(resolve, 900))
  await flushPromises()
}

beforeEach(() => {
  papers.getPaper.mockReset()
  papers.getPaperAnswers.mockReset()
  papers.savePaperAnswer.mockReset()
  papers.submitPaper.mockReset()
  router.push.mockReset()
  papers.getPaper.mockResolvedValue(detail())
  papers.getPaperAnswers.mockResolvedValue(answers())
  papers.savePaperAnswer.mockResolvedValue(row({ saved: true, user_answer_md: 'x=1' }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
})

describe('Take', () => {
  it('renders the paper and first question', async () => {
    const wrapper = await mountTake()
    expect(wrapper.text()).toContain('验收卷')
    expect(wrapper.find('[data-testid="current-stem"]').text()).toContain('解方程')
    expect(wrapper.find('[data-testid="take-progress"]').text()).toContain('0 / 1')
  })

  it('auto-saves a draft answer after typing', async () => {
    const wrapper = await mountTake()
    await wrapper.find('[data-testid="answer-input"] textarea').setValue('x=1')
    await waitAutosave()
    expect(papers.savePaperAnswer).toHaveBeenCalledWith(8, 501, {
      user_answer_md: 'x=1',
      time_spent_sec: expect.any(Number),
    })
  })

  it('blocks submit until every self-rated question is rated', async () => {
    const wrapper = await mountTake()
    const button = wrapper.find('[data-testid="submit-button"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('还有 1 道题未自评')
    expect(papers.submitPaper).not.toHaveBeenCalled()
  })

  it('submits and shows score plus mastery delta', async () => {
    papers.submitPaper.mockResolvedValue(submitResult())
    const wrapper = await mountTake()
    await wrapper.find('[data-testid="self-rated-1"] input').setValue(true)
    await flushPromises()
    await wrapper.find('[data-testid="submit-button"]').trigger('click')
    await flushPromises()

    expect(papers.submitPaper).toHaveBeenCalledWith(8, {
      items: [
        {
          question_id: 501,
          user_answer_md: null,
          self_rated: 1,
          time_spent_sec: expect.any(Number),
        },
      ],
    })
    expect(wrapper.find('[data-testid="submit-summary"]').text()).toContain('8 / 8')
    expect(wrapper.find('[data-testid="mastery-delta"]').text()).toContain('未评估')
    expect(wrapper.find('[data-testid="mastery-delta"]').text()).toContain('0.117')
  })

  it('restores a saved draft on resume', async () => {
    papers.getPaperAnswers.mockResolvedValue(
      answers({ items: [row({ user_answer_md: 'x=1', time_spent_sec: 12, saved: true })] }),
    )
    const wrapper = await mountTake()
    expect(
      (wrapper.find('[data-testid="answer-input"] textarea').element as HTMLTextAreaElement).value,
    ).toBe('x=1')
    expect(wrapper.find('[data-testid="save-status"]').exists()).toBe(false)
  })

  it('shows a read-only review after submission', async () => {
    papers.getPaperAnswers.mockResolvedValue(
      answers({
        submitted: true,
        earned_score: 8,
        items: [row({ user_answer_md: 'x=1', self_rated: 1, is_correct: true, score: 8, saved: true })],
      }),
    )
    const wrapper = await mountTake()
    expect(wrapper.find('[data-testid="submitted-banner"]').text()).toContain('已提交')
    expect(wrapper.find('[data-testid="submit-button"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="graded-result"]').text()).toContain('得分 8 / 8')
    expect(
      (wrapper.find('[data-testid="answer-input"] textarea').element as HTMLTextAreaElement)
        .disabled,
    ).toBe(true)
  })
})
```

`web/src/views/papers/Generate.spec.ts`：顶部加 router mock（与 Take 相同），并在保存成功后点「开始作答」：

```ts
  it('navigates to the take page after saving', async () => {
    papers.generatePaper.mockResolvedValue(preview())
    papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
    const wrapper = await mountView()
    await generate(wrapper)
    await wrapper.find('[data-testid="save-button"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="take-button"]').trigger('click')
    expect(router.push).toHaveBeenCalledWith('/papers/7/take')
  })
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd E:/BiShe-AIStudy/study-agent/web
npm run test:run -- src/api/papers.spec.ts src/views/papers/Take.spec.ts src/views/papers/Generate.spec.ts
```

Expected: `Take.vue` 不存在 / `getPaperAnswers is not a function` 等失败。

- [ ] **Step 3: 加类型与 API**

`web/src/types/papers.ts` 末尾追加 Step Interfaces 里的 8 个 interface。

`web/src/api/papers.ts` 追加：

```ts
export async function getPaperAnswers(id: number): Promise<PaperAnswers> {
  const resp = await http.get<ApiEnvelope<PaperAnswers>>(`${API_PREFIX}/papers/${id}/answers`)
  return resp.data.data
}

export async function savePaperAnswer(
  id: number,
  questionId: number,
  payload: PaperAnswerPayload,
): Promise<PaperAnswerRow> {
  const resp = await http.put<ApiEnvelope<PaperAnswerRow>>(
    `${API_PREFIX}/papers/${id}/answers/${questionId}`,
    payload,
  )
  return resp.data.data
}

export async function submitPaper(
  id: number,
  payload: PaperSubmitPayload,
): Promise<PaperSubmitResult> {
  const resp = await http.post<ApiEnvelope<PaperSubmitResult>>(
    `${API_PREFIX}/papers/${id}/submit`,
    payload,
  )
  return resp.data.data
}
```

import 区补类型 `PaperAnswerPayload, PaperAnswerRow, PaperAnswers, PaperSubmitPayload, PaperSubmitResult`。注意 `http` 需要支持 `put`——`http.ts` 是 axios 实例，已有。

- [ ] **Step 4: 加路由**

`web/src/router/index.ts` 在 `papers/generate` 后加：

```ts
        {
          path: 'papers/:id/take',
          name: 'paper-take',
          component: () => import('@/views/papers/Take.vue'),
          meta: { title: '在线作答', nav: 'papers', roles: ['student'] },
        },
```

- [ ] **Step 5: 写 `Take.vue`**

`web/src/views/papers/Take.vue`（完整文件）：

```vue
<script setup lang="ts">
/** S5-4 在线作答：单页 + 题号面板 + 自动保存 + 交卷成绩/掌握度回显。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import MathText from '@/components/common/MathText.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import {
  getPaper,
  getPaperAnswers,
  savePaperAnswer,
  submitPaper,
} from '@/api/papers'
import type {
  PaperAnswerRow,
  PaperDetail,
  PaperSubmitResult,
} from '@/types/papers'

const SELF_RATED_QTYPES = ['填空', '解答']
const AUTOSAVE_MS = 800

interface LocalAnswer {
  user_answer_md: string
  self_rated: number | null
}

const route = useRoute()
const router = useRouter()
const paperId = computed(() => Number(route.params.id))

const detail = ref<PaperDetail | null>(null)
const loading = ref(true)
const submitting = ref(false)
const submitted = ref(false)
const currentIndex = ref(0)
const savedAt = ref('')
const saveState = ref<'idle' | 'saving' | 'error'>('idle')
const earnedScore = ref(0)
const summary = ref<PaperSubmitResult | null>(null)
const answers = reactive<Record<number, LocalAnswer>>({})
const elapsedByQuestion = reactive<Record<number, number>>({})
const graded = reactive<Record<number, PaperAnswerRow>>({})
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let ticker: ReturnType<typeof setInterval> | null = null

const items = computed(() => detail.value?.items ?? [])
const current = computed(() => items.value[currentIndex.value] ?? null)
const canEdit = computed(() => !submitted.value)
const answeredCount = computed(
  () =>
    items.value.filter((item) => (answers[item.question_id]?.user_answer_md ?? '').trim().length > 0)
      .length,
)
const unratedCount = computed(
  () =>
    items.value.filter(
      (item) =>
        isSelfRated(item.qtype) && answers[item.question_id]?.self_rated == null,
    ).length,
)
const totalSeconds = computed(() =>
  Object.values(elapsedByQuestion).reduce((sum, value) => sum + value, 0),
)
const timerText = computed(() => {
  const total = totalSeconds.value
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
})
const scoreText = computed(() => {
  const total = detail.value?.total_score ?? 0
  if (summary.value) return `${summary.value.score} / ${summary.value.total_score}`
  return `${earnedScore.value} / ${total}`
})

const currentAnswerText = computed({
  get: () => {
    const questionId = current.value?.question_id
    return questionId ? (answers[questionId]?.user_answer_md ?? '') : ''
  },
  set: (value: string) => {
    const item = current.value
    if (!item || !canEdit.value) return
    answers[item.question_id] = {
      user_answer_md: value,
      self_rated: answers[item.question_id]?.self_rated ?? null,
    }
    onAnswerChange()
  },
})

const currentSelfRated = computed(() => {
  const questionId = current.value?.question_id
  return questionId ? (answers[questionId]?.self_rated ?? null) : null
})

const currentGraded = computed(() => {
  const questionId = current.value?.question_id
  return questionId ? (graded[questionId] ?? null) : null
})

function isSelfRated(qtype: string): boolean {
  return SELF_RATED_QTYPES.includes(qtype)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [paper, answerData] = await Promise.all([
      getPaper(paperId.value),
      getPaperAnswers(paperId.value),
    ])
    detail.value = paper
    submitted.value = answerData.submitted
    earnedScore.value = answerData.earned_score ?? 0
    for (const item of paper.items) {
      answers[item.question_id] = { user_answer_md: '', self_rated: null }
      elapsedByQuestion[item.question_id] = 0
    }
    for (const row of answerData.items) {
      answers[row.question_id] = {
        user_answer_md: row.user_answer_md ?? '',
        self_rated: row.self_rated,
      }
      elapsedByQuestion[row.question_id] = row.time_spent_sec ?? 0
      graded[row.question_id] = row
    }
  } finally {
    loading.value = false
  }
}

function onAnswerChange(): void {
  const item = current.value
  if (item) scheduleSave(item.question_id)
}

function singleValue(questionId: number): string {
  return answers[questionId]?.user_answer_md ?? ''
}

function onSingleChange(value: unknown): void {
  const item = current.value
  if (!item) return
  answers[item.question_id] = {
    user_answer_md: String(value ?? ''),
    self_rated: answers[item.question_id]?.self_rated ?? null,
  }
  scheduleSave(item.question_id)
}

function multiValue(questionId: number): string[] {
  return (answers[questionId]?.user_answer_md ?? '').split('').filter(Boolean)
}

function onMultiChange(value: unknown): void {
  const item = current.value
  if (!item) return
  const list = Array.isArray(value) ? value.map(String) : []
  answers[item.question_id] = {
    user_answer_md: [...list].sort().join(''),
    self_rated: answers[item.question_id]?.self_rated ?? null,
  }
  scheduleSave(item.question_id)
}

function onSelfRate(value: unknown): void {
  const item = current.value
  if (!item) return
  answers[item.question_id] = {
    user_answer_md: answers[item.question_id]?.user_answer_md ?? '',
    self_rated: Number(value),
  }
  scheduleSave(item.question_id)
}

function scheduleSave(questionId: number): void {
  if (!canEdit.value) return
  const existing = timers.get(questionId)
  if (existing) clearTimeout(existing)
  timers.set(
    questionId,
    setTimeout(() => {
      timers.delete(questionId)
      void save(questionId)
    }, AUTOSAVE_MS),
  )
}

async function save(questionId: number): Promise<void> {
  if (!canEdit.value) return
  saveState.value = 'saving'
  try {
    const row = await savePaperAnswer(paperId.value, questionId, {
      user_answer_md: answers[questionId]?.user_answer_md || null,
      time_spent_sec: elapsedByQuestion[questionId] ?? 0,
    })
    graded[questionId] = row
    savedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    saveState.value = 'idle'
  } catch {
    saveState.value = 'error'
  }
}

async function flushSaves(): Promise<void> {
  const pending = [...timers.keys()]
  for (const questionId of pending) {
    const timer = timers.get(questionId)
    if (timer) clearTimeout(timer)
    timers.delete(questionId)
    await save(questionId)
  }
}

async function switchTo(index: number): Promise<void> {
  if (index < 0 || index >= items.value.length) return
  await flushSaves()
  currentIndex.value = index
}

async function onSubmit(): Promise<void> {
  if (!detail.value || submitting.value || submitted.value) return
  if (unratedCount.value > 0) {
    ElMessage.warning(`还有 ${unratedCount.value} 道题未自评`)
    return
  }
  const unanswered = items.value.length - answeredCount.value
  try {
    await ElMessageBox.confirm(
      unanswered > 0 ? `还有 ${unanswered} 道题未作答，确定交卷？` : '确认交卷？交卷后不可修改。',
      '确认交卷',
      { confirmButtonText: '交卷', cancelButtonText: '再检查一下', type: 'warning' },
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    await flushSaves()
    const result = await submitPaper(paperId.value, {
      items: items.value.map((item) => ({
        question_id: item.question_id,
        user_answer_md: answers[item.question_id]?.user_answer_md || null,
        self_rated: isSelfRated(item.qtype)
          ? (answers[item.question_id]?.self_rated ?? null)
          : null,
        time_spent_sec: elapsedByQuestion[item.question_id] ?? 0,
      })),
    })
    summary.value = result
    submitted.value = true
    earnedScore.value = result.score
    for (const row of result.items) {
      graded[row.question_id] = {
        question_id: row.question_id,
        user_answer_md: row.user_answer_md,
        self_rated: row.self_rated,
        is_correct: row.is_correct,
        score: row.score,
        time_spent_sec: elapsedByQuestion[row.question_id] ?? null,
        saved: true,
      }
    }
    ElMessage.success(`交卷成功，得分 ${result.score} / ${result.total_score}`)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await load()
  ticker = setInterval(() => {
    const questionId = current.value?.question_id
    if (!questionId || submitted.value) return
    elapsedByQuestion[questionId] = (elapsedByQuestion[questionId] ?? 0) + 1
  }, 1000)
})

onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
})
</script>

<template>
  <section v-loading="loading" class="paper-take">
    <PageHeader
      :title="detail?.title ?? '在线作答'"
      description="作答会自动保存；填空/解答请自评，交卷后掌握度与错题本同步更新。"
    />

    <el-alert
      v-if="submitted"
      type="success"
      :closable="false"
      data-testid="submitted-banner"
      class="submitted-banner"
    >
      已提交，得分 {{ scoreText }}
    </el-alert>

    <div class="take-meta">
      <span data-testid="take-progress">已答 {{ answeredCount }} / {{ items.length }}</span>
      <span data-testid="take-timer">用时 {{ timerText }}</span>
      <span v-if="!submitted && saveState === 'saving'" class="save-state">保存中…</span>
      <span v-else-if="!submitted && savedAt" class="save-state" data-testid="save-status">
        已保存 {{ savedAt }}
      </span>
      <span v-else-if="!submitted && saveState === 'error'" class="save-state error">
        保存失败，请检查网络
      </span>
    </div>

    <div class="take-body">
      <el-card v-if="current" class="question-card">
        <template #header>
          <div class="question-head">
            <span data-testid="current-index">第 {{ currentIndex + 1 }} 题</span>
            <el-tag size="small">{{ current.qtype }}</el-tag>
            <span>{{ current.score }} 分</span>
            <span class="difficulty">难度 {{ current.difficulty }}</span>
          </div>
        </template>

        <div class="stem" data-testid="current-stem">
          <MathText :text="current.stem_md" />
        </div>

        <el-radio-group
          v-if="current.qtype === '单选'"
          class="choice-group"
          :model-value="singleValue(current.question_id)"
          :disabled="!canEdit"
          @update:model-value="onSingleChange"
        >
          <el-radio
            v-for="option in current.options"
            :key="option.key"
            :value="option.key"
            :data-testid="`option-${option.key}`"
          >
            {{ option.key }}. <MathText :text="option.text" />
          </el-radio>
        </el-radio-group>

        <el-checkbox-group
          v-else-if="current.qtype === '多选'"
          class="choice-group"
          :model-value="multiValue(current.question_id)"
          :disabled="!canEdit"
          @update:model-value="onMultiChange"
        >
          <el-checkbox
            v-for="option in current.options"
            :key="option.key"
            :value="option.key"
            :data-testid="`option-${option.key}`"
          >
            {{ option.key }}. <MathText :text="option.text" />
          </el-checkbox>
        </el-checkbox-group>

        <el-input
          v-else-if="current.qtype === '填空'"
          v-model="currentAnswerText"
          :disabled="!canEdit"
          data-testid="answer-input"
          placeholder="填写答案"
          @input="onAnswerChange"
        />

        <el-input
          v-else
          v-model="currentAnswerText"
          type="textarea"
          :rows="5"
          :disabled="!canEdit"
          data-testid="answer-input"
          placeholder="写出解答过程"
          @input="onAnswerChange"
        />

        <div v-if="isSelfRated(current.qtype)" class="self-rated">
          <span class="self-rated-label">自评：</span>
          <el-radio-group
            :model-value="currentSelfRated ?? undefined"
            :disabled="!canEdit"
            @update:model-value="onSelfRate"
          >
            <el-radio :value="1" data-testid="self-rated-1">对</el-radio>
            <el-radio :value="0.5" data-testid="self-rated-0.5">半对</el-radio>
            <el-radio :value="0" data-testid="self-rated-0">错</el-radio>
          </el-radio-group>
        </div>

        <div v-if="submitted && currentGraded" class="graded" data-testid="graded-result">
          <p>
            得分 {{ currentGraded?.score }} / {{ current.score }}
            <el-tag v-if="currentGraded?.is_correct" type="success" size="small">
              正确
            </el-tag>
          </p>
          <p v-if="current.answer_md">
            正确答案：<MathText :text="current.answer_md" />
          </p>
          <p v-if="current.analysis_md">解析：<MathText :text="current.analysis_md" /></p>
        </div>
      </el-card>

      <aside class="palette">
        <button
          v-for="(item, index) in items"
          :key="item.question_id"
          type="button"
          class="palette-item"
          :class="{
            active: index === currentIndex,
            answered: (answers[item.question_id]?.user_answer_md ?? '').trim().length > 0,
          }"
          :data-testid="`question-nav-${item.question_id}`"
          @click="switchTo(index)"
        >
          {{ index + 1 }}
        </button>
      </aside>
    </div>

    <div class="take-actions">
      <el-button :disabled="currentIndex === 0" data-testid="prev-button" @click="switchTo(currentIndex - 1)">
        上一题
      </el-button>
      <el-button
        :disabled="currentIndex >= items.length - 1"
        data-testid="next-button"
        @click="switchTo(currentIndex + 1)"
      >
        下一题
      </el-button>
      <el-button
        v-if="!submitted"
        type="primary"
        :loading="submitting"
        :disabled="unratedCount > 0"
        data-testid="submit-button"
        @click="onSubmit"
      >
        交卷
      </el-button>
      <span v-if="!submitted && unratedCount > 0" class="hint">
        还有 {{ unratedCount }} 道题未自评
      </span>
    </div>

    <el-card v-if="summary" class="summary" data-testid="submit-summary">
      <template #header>交卷结果</template>
      <p data-testid="summary-score">
        {{ summary.score }} / {{ summary.total_score }}（正确 {{ summary.correct_count }} /
        {{ summary.question_count }}）
      </p>
      <ul class="mastery-list">
        <li v-for="delta in summary.mastery" :key="delta.kp_id" data-testid="mastery-delta">
          {{ delta.kp_name || `知识点 #${delta.kp_id}` }}：
          {{ delta.mastery_before === null ? '未评估' : delta.mastery_before }} →
          {{ delta.mastery_after }}（本次 {{ delta.attempts_delta }} 次）
        </li>
      </ul>
      <p v-if="summary.mistake_question_ids.length">
        错题已入库 {{ summary.mistake_question_ids.length }} 道
      </p>
      <el-button data-testid="goto-mistakes" @click="router.push('/mistakes')">去错题本</el-button>
      <el-button @click="router.push('/papers/generate')">返回组卷</el-button>
    </el-card>
  </section>
</template>

<style scoped>
.paper-take {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.submitted-banner {
  margin-bottom: 8px;
}

.take-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  align-items: center;
  color: #606266;
  font-size: 14px;
}

.save-state.error {
  color: #f56c6c;
}

.take-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px;
  gap: 16px;
  align-items: start;
}

.question-head {
  display: flex;
  gap: 12px;
  align-items: center;
}

.difficulty {
  color: #909399;
  font-size: 12px;
}

.stem {
  margin-bottom: 16px;
  line-height: 1.8;
}

.choice-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-rated {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.self-rated-label {
  color: #606266;
}

.graded {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px dashed #dcdfe6;
  line-height: 1.8;
}

.palette {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}

.palette-item {
  height: 32px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
}

.palette-item.answered {
  background: #ecf5ff;
  border-color: #409eff;
}

.palette-item.active {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}

.take-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hint {
  color: #e6a23c;
  font-size: 13px;
}

.summary {
  margin-top: 8px;
}

.mastery-list {
  margin: 8px 0;
  padding-left: 20px;
  line-height: 1.8;
}

@media (max-width: 900px) {
  .take-body {
    grid-template-columns: 1fr;
  }

  .palette {
    grid-template-columns: repeat(8, 1fr);
  }
}
</style>
```

- [ ] **Step 6: 组卷页加入口**

`web/src/views/papers/Generate.vue`：
- `import { useRouter } from 'vue-router'`，`const router = useRouter()`；
- 保存成功处已有 `savedPaperId.value = paper.id`；
- 模板导出按钮后加：

```html
          <el-button v-if="savedPaperId" data-testid="take-button" @click="router.push(`/papers/${savedPaperId}/take`)">
            开始作答
          </el-button>
```

`Generate.spec.ts` 顶部加与 Take 相同的 `vi.mock('vue-router', ...)`，并追加 Step 1 的导航测试。

- [ ] **Step 7: 跑前端测试与构建**

```bash
cd E:/BiShe-AIStudy/study-agent/web
npm run test:run -- src/api/papers.spec.ts src/views/papers/Take.spec.ts src/views/papers/Generate.spec.ts
npm run test:run
npm run build
```

Expected: 三个文件全绿；全量 285+10 左右 passed；build 退出 0。

- [ ] **Step 8: Commit**

```bash
cd E:/BiShe-AIStudy/study-agent
git add web/src/types/papers.ts web/src/api/papers.ts web/src/api/papers.spec.ts \
  web/src/router/index.ts web/src/views/papers/Take.vue web/src/views/papers/Take.spec.ts \
  web/src/views/papers/Generate.vue web/src/views/papers/Generate.spec.ts
git commit -m "feat(s5-4): 在线作答页与组卷页开始作答入口"
```

---

### Task 6: 真机验收（真实库 + 真浏览器）

**Files:**
- Create: `E:/BiShe-AIStudy/.sdd/s5-4/take_check.py`
- Create: `E:/BiShe-AIStudy/.sdd/s5-4/check_take.cjs`
- Create: `E:/BiShe-AIStudy/.sdd/s5-4/acceptance-evidence.md`
- Create: `E:/BiShe-AIStudy/.sdd/s5-4/token.txt`（脚本生成）

**Interfaces:**
- Consumes: Task 1–5 全部；后端 8000、前端 5173、Chrome CDP 9222。
- Produces: `.sdd/s5-4/accept.json`、`browser.json`、截图、证据文档。

- [ ] **Step 1: 起服务并造 token**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
# 另开一个终端
cd E:/BiShe-AIStudy/study-agent/web
npm run dev
# 再一个：token
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
from app.core.security import create_access_token
out = Path("E:/BiShe-AIStudy/.sdd/s5-4")
out.mkdir(parents=True, exist_ok=True)
(out / "token.txt").write_text(create_access_token(user_id=50, role="student").token, encoding="utf-8")
print("token written")
PY
```

- [ ] **Step 2: 写并跑真实库验收脚本**

`E:/BiShe-AIStudy/.sdd/s5-4/take_check.py`：

```python
"""S5-4 真机验收：生成/保存 → 自动保存 → 续答 → 交卷 → 库内核对。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.answer import Answer
from app.models.mastery import Mastery
from app.models.mistake import Mistake
from app.models.paper import Paper
from app.services.mastery_service import effective_k, next_mastery

BASE = "http://127.0.0.1:8000/api/v1"
OUT = Path(__file__).resolve().parent
TOKEN = (OUT / "token.txt").read_text(encoding="utf-8").strip()
client = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {TOKEN}"})
engine = create_engine(get_settings().database_url)


def generate_and_save() -> int:
    preview = client.post(
        f"{BASE}/papers/generate",
        json={
            "kp_ids": [117, 128, 133],
            "total_questions": 19,
            "qtype_ratio": {"单选": 5 / 19, "填空": 4 / 19, "解答": 10 / 19},
            "difficulty_dist": {"2": 0.4, "3": 0.5, "4": 0.1},
            "total_score": 60,
            "exclude_recent_days": 0,
            "seed": 20261113,
        },
    ).json()["data"]
    assert preview["items"], "候选为空"
    saved = client.post(
        f"{BASE}/papers",
        json={
            "title": "S5-4 验收卷",
            "constraint": preview["constraint"],
            "question_ids": [item["question_id"] for item in preview["items"]],
            "duration_min": preview["constraint"]["duration_min"],
        },
    )
    assert saved.status_code == 201, saved.text
    return saved.json()["data"]["id"]


def wrong_answer(item: dict) -> str | None:
    if item["qtype"] == "单选":
        options = [option["key"] for option in item["options"]]
        return next((key for key in options if key != item["answer_md"]), options[0])
    if item["qtype"] == "多选":
        return item["answer_md"][:1]
    return "学生作答"


def build_payload(paper_id: int) -> tuple[list[dict], dict[int, dict]]:
    detail = client.get(f"{BASE}/papers/{paper_id}").json()["data"]
    draft = client.get(f"{BASE}/papers/{paper_id}/answers").json()["data"]
    assert draft["submitted"] is False
    assert all(row["saved"] is False for row in draft["items"])

    items: list[dict] = []
    for index, item in enumerate(detail["items"]):
        self_rated = [1, 0.5, 0][index % 3] if item["qtype"] in ("填空", "解答") else None
        answer: str | None
        if item["qtype"] in ("填空", "解答"):
            answer = f"作答 {item['question_id']}"
        elif index % 2 == 0:
            answer = item["answer_md"]
        else:
            answer = wrong_answer(item)
        row = {
            "question_id": item["question_id"],
            "user_answer_md": answer,
            "self_rated": self_rated,
            "time_spent_sec": 10 + index,
        }
        items.append(row)
        saved = client.put(
            f"{BASE}/papers/{paper_id}/answers/{item['question_id']}",
            json={"user_answer_md": answer, "time_spent_sec": 10 + index},
        )
        assert saved.status_code == 200, saved.text
    resumed = client.get(f"{BASE}/papers/{paper_id}/answers").json()["data"]
    assert len(resumed["items"]) == len(detail["items"])
    assert all(row["saved"] for row in resumed["items"])
    assert all(row["time_spent_sec"] for row in resumed["items"])
    return items, {item["question_id"]: item for item in detail["items"]}


def mastery_snapshot(question_items: dict[int, dict]) -> dict[int, float]:
    """只带出 float（Session 关闭后 ORM 行会 detached）。"""
    touched = sorted({kp for item in question_items.values() for kp in item["kp_ids"]})
    with Session(engine) as session:
        return {
            row.kp_id: float(row.mastery)
            for row in session.scalars(
                select(Mastery).where(Mastery.user_id == 50, Mastery.kp_id.in_(touched))
            )
        }


def main() -> None:
    paper_id = generate_and_save()
    items, by_question = build_payload(paper_id)
    before = mastery_snapshot(by_question)

    submitted = client.post(f"{BASE}/papers/{paper_id}/submit", json={"items": items})
    assert submitted.status_code == 200, submitted.text
    summary = submitted.json()["data"]
    assert summary["mistake_question_ids"], "至少应有错题入库"

    repeat = client.post(f"{BASE}/papers/{paper_id}/submit", json={"items": items})
    assert repeat.status_code == 409, repeat.text
    late_save = client.put(
        f"{BASE}/papers/{paper_id}/answers/{items[0]['question_id']}",
        json={"user_answer_md": "late"},
    )
    assert late_save.status_code == 409, late_save.text

    with Session(engine) as session:
        paper_status = session.get(Paper, paper_id).status
        answer_rows = list(
            session.scalars(select(Answer).where(Answer.paper_id == paper_id))
        )
        mistake_rows = list(
            session.scalars(
                select(Mistake).where(
                    Mistake.user_id == 50,
                    Mistake.question_id.in_([row["question_id"] for row in items]),
                )
            )
        )
        graded = {
            row.question_id: {
                "is_correct": row.is_correct,
                "score": float(row.score or 0),
                "user_answer_md": row.user_answer_md,
                "self_rated": float(row.self_rated) if row.self_rated is not None else None,
            }
            for row in answer_rows
        }
        mistake_status = sorted({row.status for row in mistake_rows})
    assert paper_status == "已提交"
    assert len(graded) == len(items)
    for row in graded.values():
        assert row["is_correct"] is not None and row["score"] is not None
        assert row["self_rated"] is not None
    assert sum(1 for row in graded.values() if row["is_correct"]) == summary["correct_count"]
    expected_errors = [
        question_id
        for question_id, row in graded.items()
        if row["score"] < by_question[question_id]["score"]
        and (row["user_answer_md"] or "").strip()
    ]
    assert sorted(expected_errors) == sorted(summary["mistake_question_ids"])
    assert mistake_status == ["待订正"]

    checked: list[dict] = []
    for delta in summary["mastery"]:
        kp_id = delta["kp_id"]
        row = next((item for item in by_question.values() if kp_id in item["kp_ids"]), None)
        assert row is not None
        hits = [
            item
            for item in by_question.values()
            if kp_id in item["kp_ids"]
        ]
        if len(hits) != 1:
            checked.append({"kp_id": kp_id, "skipped": "multi_touch", "delta": delta})
            continue
        hit = hits[0]
        s = next(item["self_rated"] for item in items if item["question_id"] == hit["question_id"]) \
            if hit["qtype"] in ("填空", "解答") else (
                1.0 if graded[hit["question_id"]]["is_correct"] else 0.0
            )
        before_value = before.get(kp_id, 0.0)
        expected = next_mastery(before_value, float(s), effective_k(hit["difficulty"]))
        assert abs(delta["mastery_after"] - expected) <= 0.001, (delta, expected)
        checked.append({"kp_id": kp_id, "s": s, "expected": expected, "delta": delta})

    report = {
        "paper_id": paper_id,
        "requested_questions": 19,
        "actual_questions": len(items),
        "qtypes": {qtype: sum(1 for row in by_question.values() if row["qtype"] == qtype)
                   for qtype in ("单选", "多选", "填空", "解答")},
        "summary": summary,
        "db": {
            "paper_status": paper_status,
            "answer_rows": len(graded),
            "mistake_rows": len(mistake_rows),
            "mistake_status": mistake_status,
            "mastery_checked": checked,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "accept.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

运行：

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe E:/BiShe-AIStudy/.sdd/s5-4/take_check.py > E:/BiShe-AIStudy/.sdd/s5-4/take_check.log 2>&1
tail -80 E:/BiShe-AIStudy/.sdd/s5-4/take_check.log
```

Expected：`accept.json` 生成；`paper_status=已提交`、`answer_rows = actual_questions`、`mistake_rows > 0`、`mastery_checked` 里每个单次命中的 kp 手算值一致。**若真实库只组出 N<19 题，记录 `actual_questions` 并如实写进证据**（任务卡 20 题不可行的证据）。

- [ ] **Step 3: 浏览器验收**

先用 API 造一张 **2 道解答题**的小卷（保证「未自评拦截」必现），把 id 与题号写入 `browser-paper.json`：

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe - <<'PY'
import json
from pathlib import Path
import httpx

token = Path("E:/BiShe-AIStudy/.sdd/s5-4/token.txt").read_text(encoding="utf-8").strip()
client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"})
preview = client.post(
    "http://127.0.0.1:8000/api/v1/papers/generate",
    json={
        "kp_ids": [117, 128, 133],
        "total_questions": 2,
        "qtype_ratio": {"解答": 1.0},
        "difficulty_dist": {"3": 1.0},
        "total_score": 16,
        "exclude_recent_days": 0,
        "seed": 77,
    },
).json()["data"]
assert len(preview["items"]) == 2, preview["items"]
saved = client.post(
    "http://127.0.0.1:8000/api/v1/papers",
    json={"title": "S5-4 浏览器验收卷", "constraint": preview["constraint"],
          "question_ids": [item["question_id"] for item in preview["items"]]},
)
paper_id = saved.json()["data"]["id"]
payload = {
    "paper_id": paper_id,
    "question_ids": [item["question_id"] for item in preview["items"]],
}
Path("E:/BiShe-AIStudy/.sdd/s5-4/browser-paper.json").write_text(
    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
)
print("paper", payload)
PY
```

起 headless Chrome（沿用 S5-3 命令）：

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new \
  --remote-debugging-port=9222 --user-data-dir=/tmp/s54-chrome --no-first-run --disable-gpu about:blank
```

`E:/BiShe-AIStudy/.sdd/s5-4/check_take.cjs`：

```javascript
// 真浏览器：2 道解答题 → 作答自动保存 → 未自评禁止交卷 → 自评后交卷 → 成绩/掌握度
const fs = require('node:fs')
const path = require('node:path')

const OUT = __dirname
const TOKEN = fs.readFileSync(path.join(OUT, 'token.txt'), 'utf8').trim()
const PAPER = JSON.parse(fs.readFileSync(path.join(OUT, 'browser-paper.json'), 'utf8'))
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const log = (...args) => console.log(new Date().toISOString().slice(11, 19), ...args)

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
    new Promise((resolve, reject) => {
      const current = ++id
      const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 30000)
      pending.set(current, (message) => {
        clearTimeout(timer)
        resolve(message)
      })
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
  const click = (testid) =>
    evaluate(`document.querySelector('[data-testid="${testid}"]')?.click(); 'ok'`)
  const fillTextarea = (value) =>
    evaluate(`(() => {
      const textarea = document.querySelector('[data-testid="answer-input"] textarea')
      if (!textarea) return false
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(textarea, ${JSON.stringify(value)})
      textarea.dispatchEvent(new Event('input', { bubbles: true }))
      return true
    })()`)
  const rate = (testid) =>
    evaluate(`(() => {
      const input = document.querySelector('[data-testid="${testid}"] input')
      if (!input) return false
      input.click()
      return true
    })()`)

  await new Promise((resolve) => ws.addEventListener('open', resolve))
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: 'http://localhost:5173/papers/generate' })
  await sleep(2000)
  await evaluate(`localStorage.setItem('study-agent-token', ${JSON.stringify(TOKEN)}); 'ok'`)
  await send('Page.navigate', { url: `http://localhost:5173/papers/${PAPER.paper_id}/take` })
  await sleep(4000)
  log('url', await evaluate('location.href'))
  log('title', await evaluate(`document.body.innerText.slice(0, 80)`))

  const filled = await fillTextarea('第一题作答 x=1')
  log('filled', filled)
  await sleep(2500)
  const savedText = await evaluate(
    `document.querySelector('[data-testid="save-status"]')?.textContent ?? ''`,
  )
  log('saved', savedText)

  const beforeRating = await evaluate(`(() => {
    const button = document.querySelector('[data-testid="submit-button"]')
    return { disabled: button?.disabled ?? null, hint: document.body.innerText.includes('未自评') }
  })()`)
  log('before rating', beforeRating)

  await rate('self-rated-1')
  await click(`question-nav-${PAPER.question_ids[1]}`)
  await sleep(600)
  await rate('self-rated-1')
  await sleep(1500)
  const afterRating = await evaluate(
    `document.querySelector('[data-testid="submit-button"]')?.disabled ?? null`,
  )
  log('submit disabled after rating', afterRating)

  await click('submit-button')
  await sleep(1200)
  await evaluate(`(() => {
    const confirm = [...document.querySelectorAll('.el-message-box__btns button')]
      .find((button) => button.textContent.includes('交卷'))
    confirm?.click()
    return Boolean(confirm)
  })()`)
  await sleep(3000)
  const summary = await evaluate(
    `document.querySelector('[data-testid="submit-summary"]')?.innerText ?? ''`,
  )
  const banner = await evaluate(
    `document.querySelector('[data-testid="submitted-banner"]')?.innerText ?? ''`,
  )
  log('banner', banner)
  log('summary', summary)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(path.join(OUT, 'take-summary.png'), Buffer.from(shot.result.data, 'base64'))
  const report = { paperId: PAPER.paper_id, savedText, beforeRating, afterRating, banner, summary }
  fs.writeFileSync(path.join(OUT, 'browser.json'), JSON.stringify(report, null, 2))
  if (!savedText.includes('已保存')) throw new Error('自动保存未生效')
  if (beforeRating.disabled !== true || beforeRating.hint !== true) {
    throw new Error('未自评没有拦住交卷')
  }
  if (afterRating !== false) throw new Error('自评后交卷按钮仍禁用')
  if (!banner.includes('已提交')) throw new Error('交卷未成功')
  if (!summary.includes('→')) throw new Error('掌握度变化未展示')
}

main().then(() => process.exit(0)).catch((error) => {
  console.error('ERR', error.message)
  process.exit(1)
})
```

运行：

```bash
cd E:/BiShe-AIStudy/.sdd/s5-4 && node check_take.cjs
```

Expected：`filled=true`、`savedText` 含「已保存」、`beforeRating {disabled:true,hint:true}`、`afterRating=false`、banner 含「已提交」、summary 含「→」。

- [ ] **Step 4: 写证据文档**

`.sdd/s5-4/acceptance-evidence.md` 必须包含（数字全部来自实际输出）：
1. 环境：后端 8000 / 前端 5173 / Chrome headless / Playwright 版本（S5-3 已装）/ 依赖服务 3/3。
2. 真实卷：请求 19 题 → 实际题数/题型分布（如实）、总分；`answer_rows`、`mistake_rows`、`mastery_checked` 手算对照表。
3. 交卷汇总：score/total、correct_count、elapsed、mistake ids。
4. 幂等/只读：重复交卷 409、交卷后 PUT 409。
5. 浏览器：自动保存文本、未自评拦截、交卷 banner、summary 文本、截图 `take-summary.png`。
6. 全量回归数字（Task 7 补）。
7. 已知问题：任务卡 20 题组不出；填空自评主观；已提交不可重做；自动保存失败只保内存。

- [ ] **Step 5: Commit（证据不入 git）**

`.sdd/` 在仓库外，不提交；本任务无代码提交。若验收中发现代码缺陷，回到对应 Task 修 TDD 后单独 commit，并在此记录修复提交号。

---

### Task 7: 文档同步与全量回归

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`（D-061）
- Modify: `AGENTS.md`（§9.2 作答口径、§9.6 锚点）
- Modify: `docs/AI协作开发实施计划.md`（S5-4 勾选）
- 可能 Modify: `docs/spec/s5-4-paper-take.md` / `docs/plan/s5-4-paper-take.md`（实现中偏离时）

- [ ] **Step 1: PROGRESS**

- 头部阶段行：阶段 5 加 S5-4。
- 「最近完成」改 S5-4，S5-3 降为「上一完成」，S5-2 降为「更早」。
- 「关键口径」加 S5-4 段：

```markdown
- 关键口径（S5-4）：作答是**试卷作用域**的 3 个同步接口——`GET /papers/{id}/answers` 续答、`PUT /papers/{id}/answers/{question_id}` 自动保存（部分唯一索引 upsert、不判分）、`POST /papers/{id}/submit` 交卷；交卷**单事务**串行 `answers upsert → record_attempts（S4-7 公式）→ 错题 upsert（非满分且有作答）→ papers.status=已提交`，失败整体回滚；判分**单选/多选自动**（字母集合归一化，全半角/大小写/顺序不敏感），**填空/解答学生自评 0/0.5/1**（用户 D-061 明确选择，偏离任务卡「客观题自动判分」字面口径）；半对产生 `NUMERIC(6,2)` 小数分；交卷响应给每 kp `mastery_before/after`（无行=null 未评估）；不自动触发错因诊断；已提交只读，重复交卷/再保存 409；前端 `/papers/:id/take` 单页 + 题号面板 + 800ms 自动保存 + 每题计时
- 验收（S5-4，真实库 + 真浏览器）：「任务卡 20 题」真实库组不出，按实际 N 题成卷（如实记录）；交卷后 `answers` 行数=N、`is_correct/score/self_rated` 符合判分、`papers.status=已提交`、`mastery` 单次命中 kp 与 `next_mastery` 手算一致、错题行数=非满分且有作答数且状态 `待订正`；重复交卷 409、交卷后 PUT 409；浏览器自动保存/未自评拦截/成绩与掌握度面板实测。详见 `.sdd/s5-4/acceptance-evidence.md`
```

- 变更日志加 `### 2026-11-13（S5-4）`，写交付文件、测试数字、验收数字。
- 实施计划 S5-4 勾选。

- [ ] **Step 2: DECISIONS D-061**

追加：

```markdown
## D-061 在线作答与掌握度回写（S5-4）

- 背景：S5-2 只把卷子存下来，S5-3 只能导出 PDF；学生不能在系统里做卷，掌握度也拿不到新作答事件。
- 决策 1（接口）：试卷作用域 3 接口（续答 GET / 自动保存 PUT / 交卷 POST），权限与状态校验只写一处；`answers.paper_id` 非空时 `uq(user_id,paper_id,question_id)` 部分唯一，自动保存走 `INSERT ... ON CONFLICT`。
- 决策 2（判分）：单选/多选自动；填空/解答学生自评 0/0.5/1。用户明确选择「填空也自评」，偏离任务卡「客观题自动判分」字面口径；好处是不误判 LaTeX/多空填空，代价是主观虚报。
- 决策 3（交卷事务）：先 `SELECT ... FOR UPDATE` 锁 papers 行，再判分、写 answers、逐题 `record_attempts`、错题 upsert，最后一次 commit；双交卷被行锁串行化，后到者读 `已提交` 409。失败整体回滚，不出现「答了但掌握度没动」。
- 决策 4（错题）：`score < 题分` 且作答去空白非空才入库；新增 `mistake_service.record_wrong_answer`（复用并重置、只 flush 不 commit、不触发诊断）。空白未答只扣掌握度，不算错题。
- 决策 5（小数分）：半对产生 `2.50` 这类分值，`answers.score` 用 `NUMERIC(6,2)`，是「分数用整数」约定的明确例外；掌握度仍用 Decimal 定型到 3/2 位。
- 决策 6（反馈）：交卷响应给每 kp `{kp_id,kp_name,mastery_before,mastery_after,attempts_delta}`，无既有行时 `mastery_before=null`（未评估，不冒充 0）；不落库快照。
- 决策 7（只读）：已提交卷 GET 可看，PUT/交卷 409；不做重新作答，避免掌握度重复累计（S5-7 再议）。
- 验证：见验收证据与 PROGRESS；任务卡「20 题卷」受真实题库限制，按实际题量验收并如实记录。
```

- [ ] **Step 3: AGENTS**

§9.2 末尾加一条 bullet：

```markdown
- 在线作答（S5-4）：`services/answer_service.py` 是唯一入口；判分纯函数（单选/多选字母集合归一化；填空/解答自评 0/0.5/1，`score=题分×自评`）与 DB 用例分离；自动保存用部分唯一索引 `uq_answers_user_paper_question` + `INSERT ... ON CONFLICT DO UPDATE`，只写草稿不判分；交卷**单事务**：`SELECT ... FOR UPDATE` 锁 papers → answers upsert → `mastery_service.record_attempts`（复用 S4-7，不重复实现公式）→ `mistake_service.record_wrong_answer`（非满分且有作答、只 flush 不 commit、不自动诊断）→ `papers.status=已提交`；已提交只读，PUT/交卷 409；`answers.score` 为 `NUMERIC(6,2)`（半对例外）
```

§9.6 锚点加：

```markdown
- 作答样例：backend/app/models/answer.py + backend/app/services/answer_service.py + backend/app/api/v1/papers.py（3 个试卷作用域接口；判分纯函数；自动保存 upsert；交卷单事务 + 行锁；错题复用重置；已提交只读）
```

- [ ] **Step 4: 全量回归**

```bash
cd E:/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
```

Expected：后端 ≥1329 passed（S5-3 基线 1315 + 新增）、前端 ≥295 passed、build 0。把实际数字写回 PROGRESS/变更日志/证据文档，**不写预期数字**。

- [ ] **Step 5: 清理与提交**

```bash
cd E:/BiShe-AIStudy/study-agent
rm -f backend/tmp*.pdf
git status --short
git add docs/PROGRESS.md docs/DECISIONS.md AGENTS.md "docs/AI协作开发实施计划.md"
git commit -m "docs(s5-4): 在线作答验收记录与口径定稿（D-061）"
```

若实现过程中改了 spec/plan（偏离需先报告用户同意），一并加入同次或单独 `docs(s5-4):` 提交。

- [ ] **Step 6: 汇报**

给用户：交付文件清单、3 接口契约、实测测试数字、真机数字（题数缺口如实）、已知边界、提交列表；提醒 `git push` 由用户执行。

---

## Self-Review

- **Spec 覆盖**：D1 接口=Task4；D2 自评=Task2/3；D3 错题=Task3；D4 不诊断=Task3/4；D5 before/after=Task3；D6 只读 409=Task3/4/5；D7 填空自评=Task2；D8 单页=Task5；迁移/SCHEMA=Task1；API.md=Task4；验收=Task6；文档=Task7。
- **类型一致性**：`AnswerInput/GradedItem` 只在 service 内部；API 输出统一 `*Out` Pydantic；前端类型镜像后端字段名（snake_case）。
- **测试**：后端纯函数 13 + 编排 9 + 接口 12；前端 API 3 + Take 6 + Generate 1。
- **风险**：`Take.vue` 使用 `answers[qid]` 索引；模板里避免 TS 非空断言（改用 computed/处理函数），若 `vue-tsc` 因 `noUncheckedIndexedAccess` 报错，用 `?? { user_answer_md:'', self_rated:null }` 兜底，不关严格模式。
