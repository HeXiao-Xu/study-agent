# S4-1 题库与试卷切题 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建 `questions` / `question_kps` 两表，打通「上传试卷 → 规则预切题 → 逐题 LLM 结构化 → 两道闸判重 → 自动挂知识点 → 落库」，并交付可人工审题（编辑/合并/拆分）的前端两页。

**Architecture:** `ai/extract/splitter.py` 用纯函数定题号边界（确定性，防串题）；`ai/extract/question_extractor.py` 一套 prompt 同时支持单题与整卷兜底；`services/question_service.py` 是唯一业务入口（规范化、判重、对齐、CRUD）；`tasks/question_extract.py` 编排任务并对单题失败降级；路由只做 Pydantic → service → Envelope。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、pgvector、Jinja2、pytest；Vue 3 + TS + Element Plus + Vitest。

**Spec:** `docs/spec/s4-1-question-bank.md`（执行时与 spec 一起读）

## Global Constraints

- 不新增第三方依赖；不新增表以外的迁移动作（唯一新迁移 `0009_s4_1`）。
- 题库是**公共语料**（`AGENTS.md §4` 的 user_id 例外）：读接口只要有登录即可；写接口限创建者 / teacher / admin。
- LLM、Embedding 调用只能走 `app/ai/` 适配器；日志由适配器写 `llm_call_logs`。
- 题干哈希与向量判重**两道闸都不可取消**；`stem_hash` 唯一约束由迁移保证，代码只依赖它。
- 知识点对齐公式固定 `0.6*cos + 0.3*keyword + 0.1*prior`，阈值 `AUTO_THRESHOLD=0.75`，直接复用 `ai/align/scoring.py`，禁止复制常量。
- 路由函数 ≤30 行；业务逻辑在 service；出入参一律 Pydantic；`AppError` 子类，不手拼错误 JSON。
- 列表接口一律 `page_params / sort_params / paginate_query / apply_sort`；禁止手写 limit/offset 与字符串 order_by。
- 外部依赖（LLM / Embedding / 对象存储 / 队列）在测试里全部 mock，测试套件禁止真实外部调用。
- `pytest` 全绿是提交前提；提交信息 Conventional Commits 且带 `(s4-1)`；`git push` 由用户执行。
- 测试数据必须真实：验收卷是**本人自编**，文档与论文里如实标注，不得冒充真题（`AGENTS §6`）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/models/enums.py` | 修改 | 新增 `QuestionOrigin` / `QuestionType` |
| `backend/app/models/question.py` | 新建 | `questions` ORM（含 `stem_hash` 唯一约束、HNSW、GIN tags） |
| `backend/app/models/question_kp.py` | 新建 | `question_kps` 复合主键关联表 |
| `backend/app/models/__init__.py` | 修改 | 显式导入两个新模型（Alembic metadata） |
| `backend/alembic/versions/0009_s4_1_questions.py` | 新建 | 建两表 + 索引 + CHECK |
| `backend/app/ai/align/scoring.py` | 修改 | 上提 `cosine` / `ancestor_names`（供题库复用） |
| `backend/app/services/kp_align_service.py` | 修改 | 改调上诉两个函数，删除私有副本 |
| `backend/app/ai/json_utils.py` | 新建 | `loads_json_object`（严格 JSON，容错代码块包裹） |
| `backend/app/ai/align/extractor.py` | 修改 | 改用 `loads_json_object`，删除私有 `_loads_json` |
| `backend/app/ai/extract/__init__.py` | 新建 | 导出 `split_questions` / `extract_questions` |
| `backend/app/ai/extract/splitter.py` | 新建 | 卷头清理 + 大题/题号预切 + 声明题数 + 兜底判定（纯函数） |
| `backend/app/ai/extract/question_extractor.py` | 新建 | 单题/整块统一 schema，严格 JSON + Pydantic + 2 次重试 |
| `backend/app/ai/prompts/question_extract_v1.md` | 新建 | 抽取 prompt（Jinja2） |
| `backend/app/schemas/question.py` | 新建 | 全部出入参 Pydantic 模型 |
| `backend/app/services/question_service.py` | 新建 | 规范化/哈希/判重/对齐/CRUD/列表（唯一入口） |
| `backend/app/services/file_service.py` | 修改 | 放宽 `parse=False` 的文件类型（允许 PDF/DOCX） |
| `backend/app/tasks/question_extract.py` | 新建 | `question.extract` 任务编排 |
| `backend/app/tasks/__init__.py` | 修改 | 注册表副作用导入 |
| `backend/app/api/v1/questions.py` | 新建 | 9 个接口 |
| `backend/app/api/router.py` | 修改 | 挂载 questions 路由 |
| `backend/tests/test_question_model.py` | 新建 | 表结构/约束/索引断言 |
| `backend/tests/test_align_scoring.py` | 修改 | `cosine` / `ancestor_names` 用例 |
| `backend/tests/test_question_splitter.py` | 新建 | 14 条切题规则用例 |
| `backend/tests/test_question_service.py` | 新建 | 14 条服务用例 |
| `backend/tests/test_question_extractor.py` | 新建 | 8 条抽取用例 |
| `backend/tests/test_question_task.py` | 新建 | 6 条任务用例 |
| `backend/tests/test_questions_api.py` | 新建 | 10 条接口用例 |
| `backend/tests/test_file_service.py` | 修改 | `parse=False` 允许 PDF/DOCX |
| `scripts/make_s4_1_exam_paper.py` | 新建 | 生成 20 题验收卷 DOCX |
| `backend/tests/test_make_exam_paper.py` | 新建 | 验收数据结构断言（8+4+8=20，每题有答案） |
| `web/src/types/questions.ts`、`web/src/types/tasks.ts` | 新建 | 前端类型 |
| `web/src/api/questions.ts`、`web/src/api/tasks.ts` | 新建 | 接口封装（只经 `http.ts`） |
| `web/src/views/questions/ImportView.vue` | 新建 | 上传 + 轮询 + 统计 |
| `web/src/views/questions/ReviewView.vue` | 新建 | 题库列表 + 审题编辑 + 合并/拆分 |
| `web/src/views/questions/__tests__/ReviewView.spec.ts` | 新建 | 6 条组件用例 |
| `web/src/router/index.ts`、`web/src/layouts/nav.ts` | 修改 | 新增 `/questions`、`/questions/import` 与导航项 |
| `docs/*` | 修改 | API/PROGRESS/DECISIONS/AGENTS/实施计划 |

---

### Task 1: 枚举 + 两表模型 + 迁移 0009

**Files:**
- Modify: `backend/app/models/enums.py`
- Create: `backend/app/models/question.py`, `backend/app/models/question_kp.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0009_s4_1_questions.py`
- Test: `backend/tests/test_question_model.py`

**Interfaces:**
- Produces: `QuestionOrigin{TEXTBOOK,EXAM,MOCK,UPLOAD,AI}`、`QuestionType{SINGLE=("单选"),MULTIPLE=("多选"),BLANK=("填空"),SOLUTION=("解答")}`、`Question`、`QuestionKp`。

- [ ] **Step 1: 写失败测试**

```python
"""S4-1 题库表结构：约束与索引是判重/检索的前提，必须由迁移固化。"""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.models import Base
from app.models.question import Question
from app.models.question_kp import QuestionKp


def test_questions_has_stem_hash_and_unique() -> None:
    table = Base.metadata.tables["questions"]
    assert "stem_hash" in table.columns
    assert table.columns["stem_hash"].nullable is False
    uniques = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert any(set(c.columns.keys()) == {"subject_id", "stem_hash"} for c in uniques)


def test_questions_check_constraints_cover_enums() -> None:
    checks = " ".join(
        str(c.sqltext) for c in Base.metadata.tables["questions"].constraints
        if type(c).__name__ == "CheckConstraint"
    )
    assert "origin IN" in checks and "'upload'" in checks
    assert "qtype IN" in checks and "'单选'" in checks
    assert "difficulty >= 1" in checks


def test_questions_indexes() -> None:
    indexes = Base.metadata.tables["questions"].indexes
    names = {ix.name for ix in indexes}
    assert {"ix_questions_subject_id", "ix_questions_origin", "ix_questions_qtype",
            "ix_questions_tags", "ix_questions_embedding_hnsw"} <= names
    hnsw = next(ix for ix in indexes if ix.name == "ix_questions_embedding_hnsw")
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


def test_question_kps_composite_pk_and_cascade() -> None:
    table = Base.metadata.tables["question_kps"]
    assert list(table.primary_key.columns.keys()) == ["question_id", "kp_id"]
    for fk in table.foreign_keys:
        assert fk.ondelete == "CASCADE"
    assert {ix.name for ix in table.indexes} == {"ix_question_kps_kp_id"}


def test_question_defaults() -> None:
    question = Question(subject_id=1, stem_md="测试题干内容", stem_hash="h", qtype="单选", difficulty=3)
    assert question.verified is None or question.verified is False
    assert QuestionKp(question_id=1, kp_id=2).weight is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_model.py -v`
Expected: FAIL（`ModuleNotFoundError: app.models.question`）

- [ ] **Step 3: 加枚举**

`backend/app/models/enums.py` 末尾（`in_check` 之前）追加：

```python
class QuestionOrigin(StrEnum):
    """questions.origin：题目来源（SCHEMA §5.1）。"""

    TEXTBOOK = "textbook"
    EXAM = "exam"
    MOCK = "mock"
    UPLOAD = "upload"
    AI = "ai"


class QuestionType(StrEnum):
    """questions.qtype：题型。用中文值，与卷面/前端展示一致。"""

    SINGLE = "单选"
    MULTIPLE = "多选"
    BLANK = "填空"
    SOLUTION = "解答"
```

- [ ] **Step 4: 写 `models/question.py`**

```python
"""questions ORM 模型：题库（SCHEMA §5.1，spec §7）。

stem_hash 是判重第一道闸：迁移里建 UNIQUE(subject_id, stem_hash)，
service 只依赖该约束，不自己保证唯一（并发下只有 DB 约束可信）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import QuestionOrigin, QuestionType, in_check

_ORIGINS = [item.value for item in QuestionOrigin]
_QTYPES = [item.value for item in QuestionType]


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("subject_id", "stem_hash", name="uq_questions_subject_stem_hash"),
        CheckConstraint(in_check("origin", _ORIGINS), name="ck_questions_origin"),
        CheckConstraint(in_check("qtype", _QTYPES), name="ck_questions_qtype"),
        CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_questions_difficulty"),
        Index("ix_questions_subject_id", "subject_id"),
        Index("ix_questions_origin", "origin"),
        Index("ix_questions_qtype", "qtype"),
        Index("ix_questions_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_questions_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", name="fk_questions_subject_id"), nullable=False
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'upload'"))
    source_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("files.id", name="fk_questions_source_file_id"), nullable=True
    )
    stem_md: Mapped[str] = mapped_column(Text, nullable=False)
    stem_latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    stem_hash: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    answer_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    qtype: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_questions_created_by"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

注意：`test_question_defaults` 里 `verified`/`difficulty` 是 server_default，Python 侧为 `None`，该用例只断言不炸，不依赖具体值。

- [ ] **Step 5: 写 `models/question_kp.py`**

```python
"""question_kps ORM 模型：题目↔知识点（SCHEMA §5.2，spec §7）。

weight 存对齐打分的原始分（0–1），人工指定固定 1.0；
不叫 confidence，避免与 note_kps.confidence 的语义（LLM 自信度）混淆。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from sqlalchemy import text


class QuestionKp(Base):
    __tablename__ = "question_kps"
    __table_args__ = (Index("ix_question_kps_kp_id", "kp_id"),)

    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("questions.id", name="fk_question_kps_question_id", ondelete="CASCADE"),
        primary_key=True,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_question_kps_kp_id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
```

- [ ] **Step 6: 注册模型**

`backend/app/models/__init__.py`：在 `from app.models.prompt_template import PromptTemplate` 前插入两行 import，并在 `__all__` 中按字母序加入 `"Question"`、`"QuestionKp"`。

- [ ] **Step 7: 写迁移 `0009_s4_1_questions.py`**

```python
"""S4-1 questions / question_kps 表

Revision ID: 0009_s4_1
Revises: 0008_s3_7
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0009_s4_1"
down_revision = "0008_s3_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.Text(), server_default=sa.text("'upload'"), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column("stem_md", sa.Text(), nullable=False),
        sa.Column("stem_latex", sa.Text(), nullable=True),
        sa.Column("stem_hash", sa.Text(), nullable=False),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answer_md", sa.Text(), nullable=True),
        sa.Column("analysis_md", sa.Text(), nullable=True),
        sa.Column("qtype", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "origin IN ('textbook', 'exam', 'mock', 'upload', 'ai')", name="ck_questions_origin"
        ),
        sa.CheckConstraint(
            "qtype IN ('单选', '多选', '填空', '解答')", name="ck_questions_qtype"
        ),
        sa.CheckConstraint("difficulty >= 1 AND difficulty <= 5", name="ck_questions_difficulty"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], name="fk_questions_subject_id"),
        sa.ForeignKeyConstraint(["source_file_id"], ["files.id"], name="fk_questions_source_file_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_questions_created_by"),
        sa.PrimaryKeyConstraint("id", name="pk_questions"),
        sa.UniqueConstraint("subject_id", "stem_hash", name="uq_questions_subject_stem_hash"),
    )
    op.create_index("ix_questions_subject_id", "questions", ["subject_id"])
    op.create_index("ix_questions_origin", "questions", ["origin"])
    op.create_index("ix_questions_qtype", "questions", ["qtype"])
    op.create_index("ix_questions_tags", "questions", ["tags"], postgresql_using="gin")
    op.create_index(
        "ix_questions_embedding_hnsw",
        "questions",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "question_kps",
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("weight", sa.Numeric(8, 6), nullable=True),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name="fk_question_kps_question_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"], ["knowledge_points.id"], name="fk_question_kps_kp_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("question_id", "kp_id", name="pk_question_kps"),
    )
    op.create_index("ix_question_kps_kp_id", "question_kps", ["kp_id"])


def downgrade() -> None:
    op.drop_index("ix_question_kps_kp_id", table_name="question_kps")
    op.drop_table("question_kps")
    op.drop_index("ix_questions_tags", table_name="questions")
    op.drop_index("ix_questions_qtype", table_name="questions")
    op.drop_index("ix_questions_origin", table_name="questions")
    op.drop_index("ix_questions_subject_id", table_name="questions")
    op.drop_table("questions")
```

> 索引名必须与 `models/question.py` 的 `__table_args__` 完全一致（`alembic check` 不报差异）。`embedding` 直接用 `Vector(1024)`，与 `0002_s2_1` 的写法一致。

- [ ] **Step 8: 跑模型测试**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_model.py -v`
Expected: PASS（5 passed）

- [ ] **Step 9: 真库升降级验证**

Run:
```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic downgrade -1
..\.venv\Scripts\python.exe -m alembic upgrade head
```
Expected: 三次都成功；`downgrade` 后 `\dt` 里没有 `questions`/`question_kps`。

- [ ] **Step 10: 全量回归 + 提交**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest -q`
Expected: 既有 770 条全绿

```bash
git add backend/app/models backend/alembic/versions/0009_s4_1_questions.py backend/tests/test_question_model.py
git commit -m "feat(s4-1): 新增 questions/question_kps 表与迁移 0009"
```

---

### Task 2: 上提 `cosine` / `ancestor_names` 到打分模块

题库判重与知识点对齐都要这两个函数。`kp_align_service` 里已有私有副本（`_cosine` / `_ancestor_names`），**上提到 `ai/align/scoring.py` 复用，不复制**（AGENTS §2.1 的复用原则）。

**Files:**
- Modify: `backend/app/ai/align/scoring.py`
- Modify: `backend/app/services/kp_align_service.py`
- Test: `backend/tests/test_align_scoring.py`

**Interfaces:**
- Produces: `cosine(left: Sequence[float], right: Sequence[float]) -> float`、`ancestor_names(node: object, by_id: Mapping[int, object]) -> list[str]`（由近到远）。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_align_scoring.py` 末尾追加：

```python
def test_cosine_identical_and_orthogonal() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_guards_empty_and_mismatch() -> None:
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 2.0], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_clamped_to_unit_interval() -> None:
    assert 0.0 <= cosine([3.0, 4.0], [3.0, 4.0]) <= 1.0


class _Node:
    def __init__(self, node_id: int, name: str, parent_id: int | None) -> None:
        self.id = node_id
        self.name = name
        self.parent_id = parent_id


def test_ancestor_names_walks_to_root() -> None:
    nodes = {1: _Node(1, "函数", None), 2: _Node(2, "单调性", 1), 3: _Node(3, "最值", 2)}
    assert ancestor_names(nodes[3], nodes) == ["单调性", "函数"]
    assert ancestor_names(nodes[1], nodes) == []


def test_ancestor_names_stops_on_cycle() -> None:
    nodes = {1: _Node(1, "A", 2), 2: _Node(2, "B", 1)}
    assert len(ancestor_names(nodes[1], nodes)) <= 2
```

顶部 import 改为：

```python
from app.ai.align.scoring import ancestor_names, cosine
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_align_scoring.py -v -k "cosine or ancestor"`
Expected: FAIL（`ImportError: cannot import name 'cosine'`）

- [ ] **Step 3: 在 `scoring.py` 追加两个纯函数**

`backend/app/ai/align/scoring.py` 顶部补 `import math` 与 `from collections.abc import Mapping, Sequence`，文件末尾追加：

```python
def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度，clamp 到 [0, 1]；维度不符/空/零向量一律 0。

    clamp 的原因：向量库返回的 cos 偶尔 >1（浮点误差），
    下游 0.6*cos+0.3*keyword+0.1*prior 的权重和就超过 1 了。
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / norm))


def ancestor_names(node: object, by_id: Mapping[int, object]) -> list[str]:
    """沿 parent_id 上溯，返回由近到远的祖先名；guard 10 层防脏数据成环。"""
    names: list[str] = []
    parent_id = getattr(node, "parent_id", None)
    guard = 0
    while parent_id is not None and parent_id in by_id and guard < 10:
        parent = by_id[parent_id]
        names.append(parent.name)
        parent_id = getattr(parent, "parent_id", None)
        guard += 1
    return names
```

- [ ] **Step 4: 改 `kp_align_service.py` 调用上提版本**

删除文件末尾的 `_ancestor_names` 与 `_cosine` 两个函数；把两处调用改为 `ancestor_names(...)` / `cosine(...)`；import 处改为：

```python
from app.ai.align.scoring import (
    AUTO_THRESHOLD,
    PENDING_THRESHOLD,
    Candidate,
    ancestor_names,
    classify,
    combine,
    cosine,
    keyword_score,
    tree_prior,
)
```

（保留原有其它 import；`math` 若不再被使用则删除该行，`ruff` 会报未使用。）

- [ ] **Step 5: 跑全部打分与对齐测试**

Run:
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_align_scoring.py tests/test_align_service.py tests/test_align_extractor.py tests/test_align_task.py tests/test_align_api.py -q
```
Expected: 全绿（含新增 5 条）

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/align/scoring.py backend/app/services/kp_align_service.py backend/tests/test_align_scoring.py
git commit -m "refactor(s4-1): cosine/ancestor_names 上提到打分模块供题库复用"
```

---

### Task 3: 切题规则 `ai/extract/splitter.py`（纯函数，TDD 重点）

**Files:**
- Create: `backend/app/ai/extract/__init__.py`, `backend/app/ai/extract/splitter.py`
- Test: `backend/tests/test_question_splitter.py`

**Interfaces:**
- Produces: `QuestionBlock(index:int, text:str, section_qtype:str|None, section_index:int)`、`SplitResult(blocks, detected_count, expected_count, degraded, warnings)`、`split_questions(text: str) -> SplitResult`。

**与 spec §4.2 的两处简化（执行时按本节为准，事后回填 spec）：**
1. **不再用「卷头关键词白名单」逐行删除**，而是「首个题号之前的行整段丢弃」。卷头永远不是题干，丢弃比白名单匹配更彻底，也不会误删含"某中学"的题目正文（正文在首题号之后，天然不受影响）。
2. **页码/答题卡行全局剔除**，因为它们可能出现在任意两题之间（分页处），不是只在卷尾。

- [ ] **Step 1: 写 14 条失败测试**

```python
"""S4-1 切题规则：边界正确性直接决定题库质量，规则全部在这里钉死。"""
from __future__ import annotations

from app.ai.extract.splitter import split_questions


def paper(*lines: str) -> str:
    return "\n".join(lines)


def test_splits_three_number_styles() -> None:
    text = paper("一、选择题（本题共 3 小题）", "1. 甲题", "A. 1 B. 2", "2、乙题", "3．丙题")
    result = split_questions(text)
    assert [block.index for block in result.blocks] == [1, 2, 3]
    assert result.blocks[1].text.startswith("2、乙题")
    assert result.blocks[2].section_qtype == "单选"
    assert result.expected_count == 3
    assert result.degraded is False


def test_decimal_line_does_not_split() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 解方程：", "1.5 是解吗？")
    result = split_questions(text)
    assert result.detected_count == 1
    assert "1.5 是解吗？" in result.blocks[0].text


def test_sub_questions_are_kept_inside_block() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 已知 f(x)=x²。", "（1）求 f(1)；", "（2）求 f(2)。")
    result = split_questions(text)
    assert result.detected_count == 1
    assert "（2）求 f(2)。" in result.blocks[0].text


def test_paren_numbering_is_not_a_question_start() -> None:
    text = paper("三、解答题（本题共 1 小题）", "1. 求证：", "1) 先证充分性", "2) 再证必要性")
    result = split_questions(text)
    assert result.detected_count == 1


def test_section_headers_carry_qtype_and_count() -> None:
    text = paper(
        "一、选择题（本题共 2 小题，每小题 5 分）",
        "1. 甲乙",
        "2. 丙丁",
        "二、填空题（本题共 1 小题）",
        "3. 填空甲",
    )
    result = split_questions(text)
    assert result.expected_count == 3
    assert result.blocks[0].section_qtype == "单选"
    assert result.blocks[2].section_qtype == "填空"
    assert result.blocks[2].section_index == 1
    assert result.degraded is False


def test_expected_count_sums_sections() -> None:
    text = paper(
        "一、选择题（本题共 8 小题）",
        *[f"{i}. 选择{i}" for i in range(1, 9)],
        "二、填空题（本题共 4 小题）",
        *[f"{i}. 填空{i}" for i in range(9, 13)],
    )
    result = split_questions(text)
    assert result.expected_count == 12
    assert result.detected_count == 12
    assert result.degraded is False


def test_number_gap_warns_but_keeps_block() -> None:
    text = paper("一、选择题（本题共 3 小题）", "1. 甲", "2. 乙", "4. 丁")
    result = split_questions(text)
    assert result.detected_count == 3
    assert "4. 丁" in result.blocks[2].text
    assert any("跳号" in warning for warning in result.warnings)
    assert result.degraded is False


def test_preamble_headers_never_reach_stem() -> None:
    text = paper(
        "某市第二中学 2026 学年度期末试卷",
        "姓名：______ 班级：______ 考号：______",
        "一、选择题（本题共 1 小题）",
        "1. 甲题",
    )
    result = split_questions(text)
    assert "姓名" not in result.blocks[0].text
    assert result.blocks[0].text.startswith("1. 甲题")


def test_school_name_inside_stem_is_kept() -> None:
    text = paper(
        "三、解答题（本题共 1 小题）",
        "1. 某中学组织研学，已知参加人数为 200，求比例。",
    )
    assert "某中学" in split_questions(text).blocks[0].text


def test_footer_between_questions_is_stripped() -> None:
    text = paper(
        "一、选择题（本题共 2 小题）",
        "1. 甲题",
        "第 1 页 共 4 页",
        "2. 乙题",
    )
    result = split_questions(text)
    assert result.detected_count == 2
    assert "第 1 页" not in result.blocks[0].text
    assert "第 1 页" not in result.blocks[1].text


def test_no_question_number_degrades() -> None:
    result = split_questions(paper("这是一段没有题号的文本。", "第二段。"))
    assert result.blocks == []
    assert result.degraded is True


def test_count_mismatch_degrades() -> None:
    text = paper("一、选择题（本题共 5 小题）", "1. 甲", "2. 乙", "3. 丙", "4. 丁")
    result = split_questions(text)
    assert result.detected_count == 4
    assert result.degraded is True
    assert any("声明" in warning for warning in result.warnings)


def test_empty_text_degrades() -> None:
    result = split_questions("   ")
    assert result.blocks == []
    assert result.degraded is True


def test_two_digit_numbers_are_single_questions() -> None:
    text = paper(
        "一、选择题（本题共 11 小题）",
        *[f"{index}. 第{index}题" for index in range(1, 12)],
    )
    result = split_questions(text)
    assert result.detected_count == 11
    assert result.blocks[9].text.startswith("10. 第10题")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_splitter.py -v`
Expected: FAIL（`ModuleNotFoundError: app.ai.extract`）

- [ ] **Step 3: 写 `splitter.py`**

```python
"""S4-1 试卷切题：纯函数，无 IO / DB / LLM。

边界为什么用规则而不是让 LLM 直接切：LLM 整卷输出会漏题、串题，
且一次失败就要重跑整卷。规则先给出确定的题号边界，LLM 只负责单题结构化；
规则失手时才退化成整卷一遍（degraded=True 显式暴露）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 大题标题：「一、选择题」；也认「二. 填空题」
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*(选择题|多选题|填空题|解答题|判断题|计算题|证明题)")
# 声明题数：「共 8 小题」；兼容「(共8小题)」
COUNT_RE = re.compile(r"(\d+)\s*小题")
# 主题号：行首的 1. / 1、/ 1．（后面必须跟非空白，避免把「3.」空行当题干）
QNUM_RE = re.compile(r"^\s*(\d{1,2})\s*[.．、]\s*\S")
# 小问编号：（1） (1) 1) ①~⑩ —— 一律不切
SUBQ_RE = re.compile(r"^\s*(?:[（(]\s*\d+\s*[）)]|\d+\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩])")
# 页脚/答题卡：可能出现在任意两题之间，全局剔除
FOOTER_RE = re.compile(r"第\s*\d+\s*页|共\s*\d+\s*页|答题卡")

_QTYPE_HINTS = {
    "选择题": "单选",
    "多选题": "多选",
    "填空题": "填空",
    "解答题": "解答",
    "判断题": "解答",
    "计算题": "解答",
    "证明题": "解答",
}


@dataclass(frozen=True)
class QuestionBlock:
    index: int
    text: str
    section_qtype: str | None
    section_index: int


@dataclass(frozen=True)
class SplitResult:
    blocks: list[QuestionBlock] = field(default_factory=list)
    detected_count: int = 0
    expected_count: int | None = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Section:
    qtype: str | None
    declared: int | None
    lines: list[str]


def split_questions(text: str) -> SplitResult:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    if not any(line.strip() for line in lines):
        return SplitResult(degraded=True, warnings=["文本为空，无法切题"])

    sections = _sections(lines)
    declared_values = [section.declared for section in sections if section.declared]
    expected_count = sum(declared_values) if declared_values else None

    blocks: list[QuestionBlock] = []
    warnings: list[str] = []
    for section_index, section in enumerate(sections):
        blocks.extend(
            _split_section(
                section,
                offset=len(blocks),
                section_index=section_index,
                warnings=warnings,
            )
        )

    degraded = False
    if expected_count is not None and len(blocks) != expected_count:
        degraded = True
        warnings.append(f"切出 {len(blocks)} 题，卷面声明 {expected_count} 题")
    if expected_count is None and len(sections) <= 1 and len(blocks) < 3:
        degraded = True
    return SplitResult(
        blocks=blocks,
        detected_count=len(blocks),
        expected_count=expected_count,
        degraded=degraded,
        warnings=warnings,
    )


def _sections(lines: list[str]) -> list[_Section]:
    """按大题标题切段；无大题标题时全文当一段（qtype/declared 为 None）。"""
    if not any(SECTION_RE.match(line) for line in lines):
        return [_Section(qtype=None, declared=None, lines=lines)]

    sections: list[_Section] = []
    qtype: str | None = None
    declared: int | None = None
    body: list[str] = []
    started = False
    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            sections.append(_Section(qtype=qtype, declared=declared, lines=body))
            count = COUNT_RE.search(line)
            qtype = _QTYPE_HINTS.get(match.group(1))
            declared = int(count.group(1)) if count else None
            body = []
            started = True
            continue
        if not started:
            continue  # 首个大题标题之前是卷头，直接丢弃
        body.append(line)
    sections.append(_Section(qtype=qtype, declared=declared, lines=body))
    return [section for section in sections if section.lines]


def _split_section(
    section: _Section,
    *,
    offset: int,
    section_index: int,
    warnings: list[str],
) -> list[QuestionBlock]:
    blocks: list[QuestionBlock] = []
    current: list[str] | None = None
    current_no: int | None = None
    for line in section.lines:
        if FOOTER_RE.search(line):
            continue
        number = _question_number(line)
        if number is not None and _starts_question(number, current_no, section.declared, len(blocks)):
            if current is not None:
                blocks.append(_block(current, offset + len(blocks) + 1, section, section_index))
            if current_no is not None and number != current_no + 1:
                warnings.append(f"题号跳号：{current_no} → {number}")
            current, current_no = [line], number
            continue
        if current is not None:
            current.append(line)
        # current 为 None 说明还在首题号之前，属于引言/说明，丢弃
    if current is not None:
        blocks.append(_block(current, offset + len(blocks) + 1, section, section_index))
    return blocks


def _block(lines: list[str], index: int, section: _Section, section_index: int) -> QuestionBlock:
    return QuestionBlock(
        index=index,
        text="\n".join(lines).strip(),
        section_qtype=section.qtype,
        section_index=section_index,
    )


def _question_number(line: str) -> int | None:
    if SUBQ_RE.match(line):
        return None
    match = QNUM_RE.match(line)
    return int(match.group(1)) if match else None


def _starts_question(
    number: int, current_no: int | None, declared: int | None, found: int
) -> bool:
    """新题判定：题号必须递增；有声明题数时切够就停（防解答题内部的列表编号）。"""
    if current_no is None:
        return True
    if number <= current_no:
        return False
    if declared is not None:
        return found < declared
    return number == current_no + 1
```

- [ ] **Step 4: 写 `ai/extract/__init__.py`**

```python
"""S4-1 试卷切题门面：splitter 出边界，question_extractor 出结构化结果。"""
from app.ai.extract.splitter import QuestionBlock, SplitResult, split_questions

__all__ = ["QuestionBlock", "SplitResult", "split_questions"]
```

- [ ] **Step 5: 跑测试至全绿**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_splitter.py -v`
Expected: 14 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/extract backend/tests/test_question_splitter.py
git commit -m "feat(s4-1): 试卷切题规则 splitter（题号边界+声明题数+兜底判定）"
```

---

### Task 4: 严格 JSON 上提 + 服务基础（规范化 / 判重 / 对齐 / 新建）

**Files:**
- Create: `backend/app/ai/json_utils.py`
- Modify: `backend/app/ai/align/extractor.py`
- Create: `backend/app/services/question_service.py`
- Test: `backend/tests/test_question_service.py`

**Interfaces:**
- Produces: `loads_json_object(text) -> dict`；`TASK_QUESTION_EXTRACT = "question.extract"`；`normalize_stem`、`compute_stem_hash`、`embedding_text`、`check_duplicate`、`align_knowledge_points`、`ensure_can_edit`、`create_question`、`_persist_question`。

- [ ] **Step 1: 上提 `loads_json_object`**

新建 `backend/app/ai/json_utils.py`：

```python
"""结构化输出的宽松取 JSON：模型常把 JSON 包在 ```json 里或加解说词。

只做「定位第一个 { 到最后一个 }」这一件事，字段校验交给 Pydantic ——
解析层容错、校验层严格，两层职责不混。
"""
from __future__ import annotations

import json


def loads_json_object(text: str) -> dict:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(clean[start : end + 1])
```

`backend/app/ai/align/extractor.py`：删除文件末尾的 `_loads_json`，把 `AlignOutput.model_validate(_loads_json(response.text))` 改成 `loads_json_object(response.text)`，import 处补 `from app.ai.json_utils import loads_json_object`，并删掉不再使用的 `import json`。

- [ ] **Step 2: 校验上提没破坏对齐链路**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_align_extractor.py tests/test_align_task.py -q`
Expected: 全绿

- [ ] **Step 3: 写服务基础测试（12 条）**

```python
"""S4-1 题库服务：判重两道闸、对齐阈值、权限、事务边界。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, ForbiddenError
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.subject import Subject
from app.models.user import User
from app.schemas.question import QuestionCreateIn
from app.services import question_service


class FakeSession:
    """按调用顺序喂 scalar/scalars 结果：服务里的查询是确定的，顺序断言最直观。"""

    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self._next_id = 100

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [1.0, 0.0]
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        return [self.vector for _ in texts]


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(username=f"{role}_q", password_hash="hash", nickname="测试用户_1", grade="高一", role=role)
    user.id = user_id
    return user


def _kp(kp_id: int, name: str, *, level: int = 2, parent_id: int | None = None,
        embedding: list[float] | None = None) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1, name=name, code=f"kp.{kp_id}", level=level,
        parent_id=parent_id, embedding=embedding or [1.0, 0.0],
    )
    kp.id = kp_id
    return kp


def test_normalize_stem_strips_number_and_spaces() -> None:
    assert question_service.normalize_stem("  12． 已知  函数 f(x)  ") == "已知函数f(x)"


def test_normalize_stem_fullwidth_equals_halfwidth() -> None:
    left = question_service.compute_stem_hash("1. 已知（a，b），求 a+b。")
    right = question_service.compute_stem_hash("已知(a,b),求a+b")
    assert left == right


def test_stem_hash_changes_when_number_changes() -> None:
    assert question_service.compute_stem_hash("1. 求 2+3") != question_service.compute_stem_hash("1. 求 2+4")


def test_check_duplicate_hits_by_hash_first() -> None:
    existing = Question(subject_id=1, stem_md="已知函数", stem_hash="h", qtype="填空", difficulty=3)
    existing.id = 7
    session = FakeSession(scalar_results=[existing])
    hit = question_service.check_duplicate(session, subject_id=1, stem_hash="h", vec=[1.0, 0.0])
    assert hit is existing


def test_check_duplicate_falls_back_to_vector() -> None:
    near = Question(subject_id=1, stem_md="已知函数 f(x)", stem_hash="other", qtype="填空", difficulty=3)
    near.id = 8
    near.embedding = [1.0, 0.0]
    session = FakeSession(scalar_results=[None, near])
    hit = question_service.check_duplicate(session, subject_id=1, stem_hash="new", vec=[1.0, 0.0])
    assert hit is near


def test_check_duplicate_returns_none_when_far() -> None:
    far = Question(subject_id=1, stem_md="无关", stem_hash="other", qtype="填空", difficulty=3)
    far.id = 9
    far.embedding = [0.0, 1.0]
    session = FakeSession(scalar_results=[None, far])
    assert question_service.check_duplicate(session, subject_id=1, stem_hash="new", vec=[1.0, 0.0]) is None


def test_align_keeps_only_high_score() -> None:
    related = _kp(1, "函数的单调性")
    unrelated = _kp(2, "立体几何", embedding=[0.0, 1.0])
    session = FakeSession(scalars_results=[[related, unrelated]])
    links = question_service.align_knowledge_points(
        session, subject_id=1, text="已知函数的单调性，求最值", kp_names=["函数的单调性"], vec=[1.0, 0.0]
    )
    assert [kp_id for kp_id, _ in links] == [1]
    assert links[0][1] >= Decimal("0.75")


def test_align_limits_to_three_links() -> None:
    kps = [_kp(index, "函数的单调性") for index in range(1, 6)]
    session = FakeSession(scalars_results=[kps])
    links = question_service.align_knowledge_points(
        session, subject_id=1, text="函数的单调性", kp_names=["函数的单调性"], vec=[1.0, 0.0]
    )
    assert len(links) == 3


def test_create_question_raises_conflict_on_duplicate() -> None:
    existing = Question(subject_id=1, stem_md="已知", stem_hash="dup", qtype="填空", difficulty=3)
    existing.id = 11
    session = FakeSession(
        objects={(Subject, 1): Subject(name="数学"), (Question, 11): existing},
        scalar_results=[existing],
    )
    payload = QuestionCreateIn(subject_id=1, stem_md="1. 已知", qtype="填空", difficulty=3)
    with pytest.raises(ConflictError):
        question_service.create_question(session, payload=payload, creator=_user(), embedder=FakeEmbedder())
    assert session.commits == 0


def test_create_question_persists_and_links_manual_kps() -> None:
    subject = Subject(name="数学")
    session = FakeSession(
        objects={(Subject, 1): subject},
        scalar_results=[None, None],
        scalars_results=[[7]],
    )
    payload = QuestionCreateIn(subject_id=1, stem_md="1. 已知函数 f(x)=x²，求 f(1)。",
                               qtype="解答", difficulty=2, kp_ids=[7])
    question = question_service.create_question(
        session, payload=payload, creator=_user(), embedder=FakeEmbedder()
    )
    assert question.stem_hash == question_service.compute_stem_hash(payload.stem_md)
    assert question.embedding == [1.0, 0.0]
    links = [row for row in session.added if isinstance(row, QuestionKp)]
    assert [(row.kp_id, row.weight) for row in links] == [(7, Decimal("1.000000"))]
    assert session.commits == 1


def test_ensure_can_edit_rejects_other_students_question() -> None:
    question = Question(subject_id=1, stem_md="已知", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 5
    question.created_by = 99
    with pytest.raises(ForbiddenError):
        question_service.ensure_can_edit(question, _user(role="student", user_id=1))


def test_ensure_can_edit_allows_teacher() -> None:
    question = Question(subject_id=1, stem_md="已知", stem_hash="h", qtype="填空", difficulty=3)
    question.created_by = 99
    question_service.ensure_can_edit(question, _user(role="teacher", user_id=1))
```

- [ ] **Step 4: 写服务基础实现**

`backend/app/services/question_service.py`（本任务只落到「新建」，编辑类函数在 Task 6 补齐）：

```python
"""S4-1 题库服务：规范化、两道闸判重、知识点对齐、CRUD 的唯一入口。

为什么不把判重放路由：切题任务与手动新增都必须走同一条判重链路，
放路由就会出现「任务绕过判重」的第二条写题路径。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.align.scoring import AUTO_THRESHOLD, ancestor_names, combine, cosine, keyword_score, tree_prior
from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.enums import UserRole
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.subject import Subject
from app.models.user import User
from app.schemas.question import QuestionCreateIn

TASK_QUESTION_EXTRACT = "question.extract"

DUPLICATE_COS_THRESHOLD = 0.92
ALIGN_TOP_K = 10
ALIGN_MAX_LINKS = 3
MANUAL_WEIGHT = Decimal("1.000000")
MAX_STEM_CHARS = 2000

_QUESTION_NO_PREFIX = re.compile(r"^\s*\d{1,2}\s*[.．、]\s*")
_EDGE_PUNCT = "，。；：、,.！？!?；:"
_LATEX_NOISE = re.compile(r"\$+|\\")


def normalize_stem(text: str) -> str:
    """去题号前缀 → NFKC 全角转半角 → 去空白 → 去首尾标点。

    不删数字、不删 LaTeX 反斜杠：它们是题干语义的一部分，
    归一化只抹平排版差异（空格/全角标点/题号）。
    """
    raw = _QUESTION_NO_PREFIX.sub("", (text or "").strip())
    half = unicodedata.normalize("NFKC", raw)
    no_space = re.sub(r"\s+", "", half)
    return no_space.strip(_EDGE_PUNCT)


def compute_stem_hash(text: str) -> str:
    return hashlib.sha256(normalize_stem(text).encode("utf-8")).hexdigest()


def embedding_text(stem_md: str) -> str:
    """向量化前去掉 LaTeX 定界符与反斜杠：$x$ 与 x 语义相同，留着只会稀释语义。"""
    return _LATEX_NOISE.sub(" ", (stem_md or ""))[:MAX_STEM_CHARS].strip()


def check_duplicate(
    session: Session, *, subject_id: int, stem_hash: str, vec: list[float] | None = None
) -> Question | None:
    """两道闸：哈希唯一（改标点仍命中）→ 向量余弦 ≥0.92（改数字/换语序仍命中）。"""
    hit = session.scalar(
        select(Question).where(Question.subject_id == subject_id, Question.stem_hash == stem_hash)
    )
    if hit is not None:
        return hit
    if not vec:
        return None
    nearest = session.scalar(
        select(Question)
        .where(Question.subject_id == subject_id, Question.embedding.is_not(None))
        .order_by(Question.embedding.cosine_distance(vec))
        .limit(1)
    )
    if nearest is not None and cosine(vec, list(nearest.embedding or [])) >= DUPLICATE_COS_THRESHOLD:
        return nearest
    return None


def align_knowledge_points(
    session: Session,
    *,
    subject_id: int,
    text: str,
    kp_names: list[str],
    vec: list[float],
    top_k: int = ALIGN_TOP_K,
    limit: int = ALIGN_MAX_LINKS,
) -> list[tuple[int, Decimal]]:
    """复用 S2-10 公式；LLM 的 kp_names 只当关键词信号，绝不直接落库。"""
    rows = [
        row
        for row in session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.subject_id == subject_id).order_by(KnowledgePoint.id)
        )
        if row.embedding is not None
    ]
    if not rows or not vec:
        return []
    by_id = {row.id: row for row in rows}
    anchors = " ".join(kp_names)
    ranked = sorted(rows, key=lambda row: cosine(vec, list(row.embedding or [])), reverse=True)[:top_k]
    picked: list[tuple[int, Decimal]] = []
    for row in ranked:
        score = combine(
            cosine(vec, list(row.embedding or [])),
            max(keyword_score(row.name, text), keyword_score(row.name, anchors)),
            tree_prior(row.level, ancestor_names(row, by_id), list(kp_names), text[:200]),
        )
        if score >= AUTO_THRESHOLD:
            picked.append((row.id, Decimal(str(round(score, 6)))))
    picked.sort(key=lambda item: item[1], reverse=True)
    return picked[:limit]


def ensure_can_edit(question: Question, viewer: User) -> None:
    """教师/管理员可改公共题库；学生只能改自己导入的题。"""
    if viewer.role in {UserRole.TEACHER.value, UserRole.ADMIN.value}:
        return
    if question.created_by is not None and question.created_by == viewer.id:
        return
    raise ForbiddenError("只能修改自己创建的题目")


def _ensure_subject(session: Session, subject_id: int) -> None:
    if session.get(Subject, subject_id) is None:
        raise NotFoundError("学科不存在")


def _ensure_kps_exist(session: Session, kp_ids: list[int]) -> None:
    if not kp_ids:
        return
    found = {row for row in session.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(kp_ids)))}
    missing = sorted(set(kp_ids) - found)
    if missing:
        raise NotFoundError(f"知识点不存在：{missing}")


def _persist_question(
    session: Session,
    *,
    subject_id: int,
    origin: str,
    source_file_id: int | None,
    stem_md: str,
    options_json: list[dict] | None,
    answer_md: str | None,
    analysis_md: str | None,
    qtype: str,
    difficulty: int,
    tags: list[str] | None,
    verified: bool,
    embedding: list[float],
    created_by: int | None,
    links: list[tuple[int, Decimal]],
) -> Question:
    """建题 + 挂知识点；只 flush 不 commit（单题/批量两条路径共用）。"""
    question = Question(
        subject_id=subject_id,
        origin=origin,
        source_file_id=source_file_id,
        stem_md=stem_md,
        stem_hash=compute_stem_hash(stem_md),
        options_json=options_json,
        answer_md=answer_md,
        analysis_md=analysis_md,
        qtype=qtype,
        difficulty=difficulty,
        tags=tags,
        verified=verified,
        embedding=embedding,
        created_by=created_by,
    )
    session.add(question)
    session.flush()
    for kp_id, weight in links:
        session.add(QuestionKp(question_id=question.id, kp_id=kp_id, weight=weight))
    session.flush()
    return question


def _options_json_of(payload: QuestionCreateIn) -> list[dict] | None:
    return [option.model_dump() for option in payload.options] if payload.options else None


def create_question(
    session: Session, *, payload: QuestionCreateIn, creator: User, embedder: EmbeddingClient | None = None
) -> Question:
    """手动新增：判重命中直接 409（人工重复录入没有任何合理场景）。"""
    _ensure_subject(session, payload.subject_id)
    client = embedder or get_embedding_client()
    vec = client.encode([embedding_text(payload.stem_md)])[0]
    if check_duplicate(
        session, subject_id=payload.subject_id, stem_hash=compute_stem_hash(payload.stem_md), vec=vec
    ) is not None:
        raise ConflictError("题目已存在（题库里已有同一道题）")
    _ensure_kps_exist(session, payload.kp_ids)
    question = _persist_question(
        session,
        subject_id=payload.subject_id,
        origin=payload.origin,
        source_file_id=None,
        stem_md=payload.stem_md,
        options_json=_options_json_of(payload),
        answer_md=payload.answer_md,
        analysis_md=payload.analysis_md,
        qtype=payload.qtype,
        difficulty=payload.difficulty,
        tags=payload.tags,
        verified=False,
        embedding=vec,
        created_by=creator.id,
        links=[(kp_id, MANUAL_WEIGHT) for kp_id in payload.kp_ids],
    )
    session.commit()
    return question
```

同时先建最小 `backend/app/schemas/question.py`（Task 9 再补出参与列表模型）：

```python
"""S4-1 题库出入参：字段与 SCHEMA §5.1 一一对应。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_QType = Literal["单选", "多选", "填空", "解答"]
_Origin = Literal["textbook", "exam", "mock", "upload", "ai"]


class OptionIn(BaseModel):
    key: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


class QuestionCreateIn(BaseModel):
    subject_id: int
    stem_md: str = Field(min_length=5)
    options: list[OptionIn] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: _QType
    difficulty: int = Field(ge=1, le=5)
    kp_ids: list[int] = Field(default_factory=list)
    origin: _Origin = "upload"
    tags: list[str] | None = None
```

- [ ] **Step 5: 跑服务测试**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py -v`
Expected: 12 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/json_utils.py backend/app/ai/align/extractor.py \
  backend/app/services/question_service.py backend/app/schemas/question.py \
  backend/tests/test_question_service.py
git commit -m "feat(s4-1): 题库服务基础（规范化/两道闸判重/知识点对齐/新建）"
```

---

### Task 5: 结构化抽取 `ai/extract/question_extractor.py` + prompt

**Files:**
- Create: `backend/app/ai/prompts/question_extract_v1.md`
- Create: `backend/app/ai/extract/question_extractor.py`
- Modify: `backend/app/ai/extract/__init__.py`
- Test: `backend/tests/test_question_extractor.py`

**Interfaces:**
- Produces: `ExtractedOption`、`ExtractedQuestion`、`ExtractResult(questions, truncated)`、`extract_questions(*, question_text, mode="single", subject_name="高中数学", section_qtype=None, expected_count=None, llm_client=None, max_retries=2) -> ExtractResult`、`QuestionExtractError`。

- [ ] **Step 1: 写 8 条失败测试**

```python
"""S4-1 单题结构化抽取：一套 schema 覆盖单题与整卷，非法输出必须重试。"""
from __future__ import annotations

import json

import pytest

from app.ai.extract import question_extractor
from app.ai.extract.question_extractor import QuestionExtractError, extract_questions


class FakeLLM:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0
        self.scenes: list[str] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        from app.ai.llm import LLMResponse

        self.calls += 1
        self.scenes.append(scene)
        text = self.texts.pop(0) if self.texts else self.texts[-1]
        return LLMResponse(text=text, model="fake-llm", total_tokens=10)


def single(**overrides) -> str:
    payload = {
        "stem_md": "已知函数 $f(x)=x^2$，求 $f(1)$。",
        "options": None,
        "answer_md": "1",
        "analysis_md": "代入即可。",
        "qtype": "解答",
        "difficulty": 2,
        "kp_names": ["函数的单调性"],
        "answer_source": "paper",
    }
    payload.update(overrides)
    return json.dumps({"questions": [payload]}, ensure_ascii=False)


CHOICE = {
    "stem_md": "已知集合 A={1,2}，B={2,3}，则 A∩B=（ ）",
    "options": [{"key": "A", "text": "{1}"}, {"key": "B", "text": "{2}"}],
    "answer_md": "B",
    "analysis_md": None,
    "qtype": "单选",
    "difficulty": 1,
    "kp_names": ["集合的运算"],
    "answer_source": "paper",
}


def test_parses_single_question() -> None:
    result = extract_questions(question_text="1. 已知函数...", llm_client=FakeLLM(single()))
    assert len(result.questions) == 1
    assert result.questions[0].stem_md.startswith("已知函数")
    assert result.questions[0].answer_source == "paper"
    assert result.truncated is False


def test_parses_block_mode_multiple() -> None:
    text = json.dumps({"questions": [CHOICE, CHOICE]}, ensure_ascii=False)
    result = extract_questions(
        question_text="整卷原文", mode="block", expected_count=2, llm_client=FakeLLM(text)
    )
    assert len(result.questions) == 2


def test_choice_with_single_option_retries_then_succeeds() -> None:
    broken = json.dumps({"questions": [{**CHOICE, "options": [{"key": "A", "text": "x"}]}]}, ensure_ascii=False)
    good = json.dumps({"questions": [CHOICE]}, ensure_ascii=False)
    client = FakeLLM(broken, good)
    result = extract_questions(question_text="1. 选择题", llm_client=client)
    assert client.calls == 2
    assert len(result.questions) == 1


def test_answer_letter_outside_options_retries() -> None:
    broken = json.dumps({"questions": [{**CHOICE, "answer_md": "E"}]}, ensure_ascii=False)
    good = json.dumps({"questions": [CHOICE]}, ensure_ascii=False)
    client = FakeLLM(broken, good)
    assert len(extract_questions(question_text="1. 选择题", llm_client=client).questions) == 1
    assert client.calls == 2


def test_options_on_blank_question_retries() -> None:
    broken = json.dumps({"questions": [{"stem_md": "填空题干内容", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}],
                                        "answer_md": "1", "analysis_md": None, "qtype": "填空",
                                        "difficulty": 2, "kp_names": [], "answer_source": "paper"}]}, ensure_ascii=False)
    client = FakeLLM(broken, single(qtype="填空", answer_md="2", options=None))
    assert len(extract_questions(question_text="1. 填空", llm_client=client).questions) == 1
    assert client.calls == 2


def test_three_invalid_attempts_raise() -> None:
    client = FakeLLM("<html>不是 JSON</html>", "<html>还是不是</html>", "{}")
    with pytest.raises(QuestionExtractError):
        extract_questions(question_text="1. 题", llm_client=client)
    assert client.calls == 3


def test_single_mode_with_two_questions_retries() -> None:
    two = json.dumps({"questions": [CHOICE, CHOICE]}, ensure_ascii=False)
    client = FakeLLM(two, single())
    result = extract_questions(question_text="1. 题", llm_client=client)
    assert client.calls == 2
    assert len(result.questions) == 1


def test_block_mode_truncates_to_expected_count() -> None:
    text = json.dumps({"questions": [CHOICE, CHOICE, CHOICE]}, ensure_ascii=False)
    result = extract_questions(
        question_text="整卷", mode="block", expected_count=2, llm_client=FakeLLM(text)
    )
    assert len(result.questions) == 2
    assert result.truncated is True
    assert question_extractor.SCENE == "gen"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_extractor.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 prompt `ai/prompts/question_extract_v1.md`**

```markdown
你是高中数学试卷切题与结构化专家。请把下面的卷面原文转成 JSON。

【学科】{{ subject_name }}
{% if section_qtype %}【本大题卷面题型】{{ section_qtype }}{% endif %}
{% if expected_count %}【本题区应有题数】{{ expected_count }}{% endif %}

【规则】
1. 只输出 JSON，不要任何解释，不要 Markdown 代码块。
2. 顶层结构固定为：{"questions": [ {...}, ... ]}。
3. 每题字段：
   - stem_md：题干，不含选项、不含答案、不含"解："。行内公式用 $...$，独立公式用 $$...$$。
   - options：选择题选项数组 [{"key":"A","text":"..."}]；填空与解答题必须为 null。
   - answer_md：答案。卷面自带就照抄并置 answer_source="paper"；卷面没有就自己给出并置 answer_source="ai"；无法给出用 null 且 answer_source="none"。
   - analysis_md：解析，可照抄卷面，也可简要写步骤；没有就 null。
   - qtype：单选 | 多选 | 填空 | 解答（以题目实际为准，可以纠正卷面大题的题型提示）。
   - difficulty：1–5 的整数，1 最易、5 最难。
   - kp_names：本题考查的知识点名称数组，用高中数学通用叫法（如"函数的单调性"、"等差数列的通项"）。
   - answer_source：paper | ai | none。
4. 禁止臆造题号、分值、页码、考试时间。
5. 禁止合并或拆分题目：一道题一条记录。
{% if mode == "single" %}
6. 输入是单道题，questions 长度必须为 1。
{% else %}
6. 输入是整卷文本，请按题号切分成多道题，总数应接近 {{ expected_count }} 条。
{% endif %}

【卷面原文】
{{ question_text }}
```

- [ ] **Step 4: 写 `question_extractor.py`**

```python
"""S4-1 单题结构化：一套 prompt + 一套 schema 覆盖单题与整卷兜底两种模式。

为什么统一返回数组：整卷兜底时一次要给多条；单题模式断言长度为 1 即可，
不需要维护第二套 prompt 与第二个 Pydantic 模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "question_extract_v1.md"
SCENE = "gen"
MAX_RETRIES = 2
_ANSWER_KEYS_LIMIT = 4


class QuestionExtractError(Exception):
    """抽取最终失败（含重试耗尽）；任务层据此计入 failed_items。"""


class ExtractedOption(BaseModel):
    key: str = Field(min_length=1, max_length=_ANSWER_KEYS_LIMIT)
    text: str = Field(min_length=1)


class ExtractedQuestion(BaseModel):
    stem_md: str
    options: list[ExtractedOption] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: Literal["单选", "多选", "填空", "解答"]
    difficulty: int = Field(ge=1, le=5)
    kp_names: list[str] = Field(default_factory=list)
    answer_source: Literal["paper", "ai", "none"] = "none"

    @model_validator(mode="after")
    def _validate_shape(self) -> "ExtractedQuestion":
        if len(self.stem_md.strip()) < 5:
            raise ValueError("题干过短")
        if self.qtype in {"单选", "多选"}:
            options = self.options or []
            if len(options) < 2:
                raise ValueError("选择题至少需要 2 个选项")
            keys = [option.key for option in options]
            if len(set(keys)) != len(keys):
                raise ValueError("选项 key 重复")
            answer = (self.answer_md or "").strip().upper().replace(" ", "")
            if answer:
                if any(char not in keys for char in answer):
                    raise ValueError("答案字母不在选项内")
                if self.qtype == "单选" and len(answer) != 1:
                    raise ValueError("单选题答案只能是 1 个字母")
                if len(set(answer)) != len(answer):
                    raise ValueError("多选题答案字母重复")
        elif self.options:
            raise ValueError("填空/解答题不应有选项")
        return self


class ExtractOutput(BaseModel):
    questions: list[ExtractedQuestion] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractResult:
    questions: list[ExtractedQuestion]
    truncated: bool = False


def render_prompt(
    *,
    mode: str,
    subject_name: str,
    section_qtype: str | None,
    expected_count: int | None,
    question_text: str,
) -> str:
    if not PROMPT_PATH.is_file():
        raise QuestionExtractError(f"Prompt 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(
            mode=mode,
            subject_name=subject_name,
            section_qtype=section_qtype,
            expected_count=expected_count,
            question_text=question_text,
        )
    except QuestionExtractError:
        raise
    except Exception as exc:
        raise QuestionExtractError(f"Prompt 渲染失败：{exc}") from exc


def extract_questions(
    *,
    question_text: str,
    mode: str = "single",
    subject_name: str = "高中数学",
    section_qtype: str | None = None,
    expected_count: int | None = None,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> ExtractResult:
    if not (question_text or "").strip():
        raise QuestionExtractError("题目文本为空")
    if mode not in {"single", "block"}:
        raise QuestionExtractError(f"未知模式：{mode}")
    client = llm_client or get_llm_client()
    prompt = render_prompt(
        mode=mode,
        subject_name=subject_name,
        section_qtype=section_qtype,
        expected_count=expected_count,
        question_text=question_text,
    )
    messages = [LLMMessage(role="user", content=prompt)]
    max_tokens = 2048 if mode == "block" else 1500
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        response = client.chat(messages, temperature=0.0, max_tokens=max_tokens, scene=SCENE)
        try:
            output = ExtractOutput.model_validate(loads_json_object(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            continue
        items = output.questions
        if not items:
            last_error = ValueError("模型未返回任何题目")
            continue
        if mode == "single":
            if len(items) != 1:
                last_error = ValueError(f"单题模式返回了 {len(items)} 条")
                continue
            return ExtractResult(questions=items)
        if expected_count is not None:
            if len(items) > expected_count:
                return ExtractResult(questions=items[:expected_count], truncated=True)
            return ExtractResult(questions=items)
        return ExtractResult(questions=items)
    raise QuestionExtractError(f"题目抽取失败（已重试 {max_retries} 次）：{last_error}")
```

`backend/app/ai/extract/__init__.py` 改为：

```python
"""S4-1 试卷切题门面：splitter 出边界，question_extractor 出结构化结果。"""
from app.ai.extract.question_extractor import (
    ExtractedOption,
    ExtractedQuestion,
    ExtractResult,
    QuestionExtractError,
    extract_questions,
)
from app.ai.extract.splitter import QuestionBlock, SplitResult, split_questions

__all__ = [
    "ExtractResult",
    "ExtractedOption",
    "ExtractedQuestion",
    "QuestionBlock",
    "QuestionExtractError",
    "SplitResult",
    "extract_questions",
    "split_questions",
]
```

- [ ] **Step 5: 跑抽取测试**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_extractor.py -v`
Expected: 8 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/extract backend/app/ai/prompts/question_extract_v1.md backend/tests/test_question_extractor.py
git commit -m "feat(s4-1): 单题结构化抽取器与 question_extract_v1 prompt"
```

---

### Task 6: 服务写操作（编辑 / 拆分 / 合并 / 删除）

**Files:**
- Modify: `backend/app/services/question_service.py`
- Modify: `backend/app/schemas/question.py`（加 `QuestionUpdateIn`、`QuestionSplitIn`、`QuestionMergeIn`）
- Modify: `backend/tests/test_question_service.py`

**Interfaces:**
- Produces: `update_question`、`split_question`、`merge_questions`、`delete_question`、`_load_question`、`_replace_links`、`_ensure_not_referenced`。

- [ ] **Step 1: 追加 4 条失败测试**

在 `backend/tests/test_question_service.py` 末尾追加：

```python
def test_update_question_recomputes_hash_and_embedding() -> None:
    question = Question(subject_id=1, stem_md="1. 旧题干内容", stem_hash="old", qtype="填空", difficulty=3)
    question.id = 3
    question.created_by = 1
    question.embedding = [0.0, 1.0]
    session = FakeSession(objects={(Question, 3): question}, scalar_results=[None], scalars_results=[[], []])
    updated = question_service.update_question(
        session,
        question_id=3,
        payload=QuestionUpdateIn(stem_md="1. 新题干内容"),
        viewer=_user(user_id=1),
        embedder=FakeEmbedder(),
    )
    assert updated.stem_md == "1. 新题干内容"
    assert updated.stem_hash == question_service.compute_stem_hash("1. 新题干内容")
    assert updated.embedding == [1.0, 0.0]
    assert session.commits == 1


def test_delete_question_clears_links() -> None:
    question = Question(subject_id=1, stem_md="题干", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 4
    question.created_by = 1
    link = QuestionKp(question_id=4, kp_id=9, weight=Decimal("1.0"))
    session = FakeSession(objects={(Question, 4): question}, scalars_results=[[link]])
    question_service.delete_question(session, question_id=4, viewer=_user(user_id=1))
    assert link in session.deleted
    assert question in session.deleted
    assert session.commits == 1


def test_merge_rejects_cross_subject() -> None:
    left = Question(subject_id=1, stem_md="甲题目内容", stem_hash="a", qtype="填空", difficulty=3)
    left.id = 1
    right = Question(subject_id=2, stem_md="乙题目内容", stem_hash="b", qtype="填空", difficulty=3)
    right.id = 2
    session = FakeSession(objects={(Question, 1): left, (Question, 2): right})
    with pytest.raises(InvalidParamError):
        question_service.merge_questions(
            session, ids=[1, 2], viewer=_user(role="teacher"), embedder=FakeEmbedder()
        )


def test_split_rejects_missing_marker() -> None:
    question = Question(subject_id=1, stem_md="1. 甲题 2. 乙题", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 5
    question.created_by = 1
    session = FakeSession(objects={(Question, 5): question})
    with pytest.raises(InvalidParamError):
        question_service.split_question(
            session, question_id=5, split_at="3.", viewer=_user(user_id=1), embedder=FakeEmbedder()
        )
```

顶部 import 追加：`from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError`（补齐 `InvalidParamError`）与 `from app.schemas.question import QuestionMergeIn, QuestionSplitIn, QuestionUpdateIn`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py -v -k "update or delete or merge or split"`
Expected: FAIL（`AttributeError: module ... has no attribute 'update_question'`）

- [ ] **Step 3: 补 schema**

`backend/app/schemas/question.py` 追加：

```python
class QuestionUpdateIn(BaseModel):
    """部分更新：出现在 model_fields_set 里的字段才生效；kp_ids=[] 表示清空关联。"""

    stem_md: str | None = Field(default=None, min_length=5)
    options: list[OptionIn] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: _QType | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    kp_ids: list[int] | None = None
    origin: _Origin | None = None
    tags: list[str] | None = None
    verified: bool | None = None


class QuestionSplitIn(BaseModel):
    split_at: str = Field(min_length=1, max_length=50, description="题干中出现、作为第二题起点开头的标记")


class QuestionMergeIn(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=10)
```

- [ ] **Step 4: 补服务实现**

`backend/app/services/question_service.py`：import 区补 `from sqlalchemy import inspect, text`（合并进现有 `from sqlalchemy import select`）与 `InvalidParamError`（合并进 `core.exceptions` 那行），末尾追加：

```python
def _load_question(session: Session, question_id: int) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    return question


def _replace_links(session: Session, question_id: int, links: list[tuple[int, Decimal]]) -> None:
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    for kp_id, weight in links:
        session.add(QuestionKp(question_id=question_id, kp_id=kp_id, weight=weight))
    session.flush()


def _mistakes_table_exists(session: Session) -> bool:
    """S4-2 建 mistakes 表后自动生效；S4-1 阶段表不存在则无条件放行（spec D-15）。"""
    try:
        return inspect(session.get_bind()).has_table("mistakes")
    except Exception:  # noqa: BLE001 —— 拿不到连接时按“表不存在”处理，不阻塞题库操作
        return False


def _ensure_not_referenced(session: Session, question_ids: list[int]) -> None:
    if not _mistakes_table_exists(session):
        return
    row = session.execute(
        text("SELECT 1 FROM mistakes WHERE question_id = ANY(:ids) LIMIT 1"),
        {"ids": question_ids},
    ).first()
    if row is not None:
        raise ConflictError("题目已被错题本引用，不能删除、合并或拆分")


def _replace_stem(
    session: Session, question: Question, stem_md: str, *, embedder: EmbeddingClient | None = None
) -> None:
    new_hash = compute_stem_hash(stem_md)
    duplicate = check_duplicate(session, subject_id=question.subject_id, stem_hash=new_hash, vec=None)
    if duplicate is not None and duplicate.id != question.id:
        raise ConflictError("题目已存在（题库里已有同一道题）")
    vec = (embedder or get_embedding_client()).encode([embedding_text(stem_md)])[0]
    question.stem_md = stem_md
    question.stem_hash = new_hash
    question.embedding = vec
    _replace_links(
        session,
        question.id,
        align_knowledge_points(
            session, subject_id=question.subject_id, text=stem_md, kp_names=[], vec=vec
        ),
    )


def update_question(
    session: Session,
    *,
    question_id: int,
    payload: QuestionUpdateIn,
    viewer: User,
    embedder: EmbeddingClient | None = None,
) -> Question:
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    fields = payload.model_fields_set

    if "stem_md" in fields and payload.stem_md is not None:
        if normalize_stem(payload.stem_md) != normalize_stem(question.stem_md):
            _replace_stem(session, question, payload.stem_md, embedder=embedder)
    if "options" in fields:
        question.options_json = (
            [option.model_dump() for option in payload.options] if payload.options else None
        )
    for name in ("answer_md", "analysis_md", "qtype", "difficulty", "origin", "tags", "verified"):
        if name in fields:
            setattr(question, name, getattr(payload, name))
    if "kp_ids" in fields and payload.kp_ids is not None:
        _ensure_kps_exist(session, payload.kp_ids)
        _replace_links(session, question.id, [(kp_id, MANUAL_WEIGHT) for kp_id in payload.kp_ids])
    session.commit()
    return question


def split_question(
    session: Session,
    *,
    question_id: int,
    split_at: str,
    viewer: User,
    embedder: EmbeddingClient | None = None,
) -> list[Question]:
    """把一道题按标记切成两道：AI 把两题串一起时的人工兜底。"""
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    marker = (split_at or "").strip()
    if not marker:
        raise InvalidParamError("split_at 不能为空")
    position = question.stem_md.find(marker)
    if position <= 0:
        raise InvalidParamError(f"题干中找不到可作为切分点的标记：{marker}")
    left = question.stem_md[:position].strip()
    right = question.stem_md[position:].strip()
    if len(normalize_stem(left)) < 5 or len(normalize_stem(right)) < 5:
        raise InvalidParamError("切分后任一半少于 5 个字，拒绝拆分")
    _ensure_not_referenced(session, [question_id])

    client = embedder or get_embedding_client()
    vectors = client.encode([embedding_text(left), embedding_text(right)])
    created: list[Question] = []
    for stem, vec in zip((left, right), vectors):
        if check_duplicate(
            session, subject_id=question.subject_id, stem_hash=compute_stem_hash(stem), vec=vec
        ) is not None:
            raise ConflictError("拆分出的题目已存在于题库")
        created.append(
            _persist_question(
                session,
                subject_id=question.subject_id,
                origin=question.origin,
                source_file_id=question.source_file_id,
                stem_md=stem,
                options_json=question.options_json,
                answer_md=question.answer_md,
                analysis_md=question.analysis_md,
                qtype=question.qtype,
                difficulty=question.difficulty,
                tags=list(question.tags) if question.tags else None,
                verified=bool(question.verified),
                embedding=vec,
                created_by=question.created_by,
                links=align_knowledge_points(
                    session, subject_id=question.subject_id, text=stem, kp_names=[], vec=vec
                ),
            )
        )
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    session.delete(question)
    session.commit()
    return created


def merge_questions(
    session: Session, *, ids: list[int], viewer: User, embedder: EmbeddingClient | None = None
) -> Question:
    """按 id 升序拼接：顺序影响题干可读性，必须确定，不能依赖入参顺序。"""
    unique_ids = sorted({int(item) for item in ids})
    if len(unique_ids) < 2:
        raise InvalidParamError("合并至少需要 2 道题")
    questions = [_load_question(session, item) for item in unique_ids]
    for question in questions:
        ensure_can_edit(question, viewer)
    if len({question.subject_id for question in questions}) != 1:
        raise InvalidParamError("只能合并同一学科的题目")
    _ensure_not_referenced(session, unique_ids)

    stem = "\n\n".join(question.stem_md for question in questions)
    answer = "\n\n".join(q.answer_md for q in questions if q.answer_md) or None
    analysis = "\n\n".join(q.analysis_md for q in questions if q.analysis_md) or None
    first = questions[0]
    vec = (embedder or get_embedding_client()).encode([embedding_text(stem)])[0]
    if check_duplicate(
        session, subject_id=first.subject_id, stem_hash=compute_stem_hash(stem), vec=vec
    ) is not None:
        raise ConflictError("合并后的题目已存在于题库")

    merged = _persist_question(
        session,
        subject_id=first.subject_id,
        origin=first.origin,
        source_file_id=first.source_file_id,
        stem_md=stem,
        options_json=None,
        answer_md=answer,
        analysis_md=analysis,
        qtype=first.qtype,
        difficulty=max(question.difficulty for question in questions),
        tags=None,
        verified=all(bool(question.verified) for question in questions),
        embedding=vec,
        created_by=first.created_by,
        links=align_knowledge_points(
            session, subject_id=first.subject_id, text=stem, kp_names=[], vec=vec
        ),
    )
    for question in questions:
        for row in list(
            session.scalars(select(QuestionKp).where(QuestionKp.question_id == question.id))
        ):
            session.delete(row)
        session.delete(question)
    session.commit()
    return merged


def delete_question(session: Session, *, question_id: int, viewer: User) -> None:
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    _ensure_not_referenced(session, [question_id])
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    session.delete(question)
    session.commit()
```

- [ ] **Step 5: 跑服务测试全绿**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py -v`
Expected: 16 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/question_service.py backend/app/schemas/question.py backend/tests/test_question_service.py
git commit -m "feat(s4-1): 题库编辑/拆分/合并/删除（权限+引用保护+硬删级联）"
```

---

### Task 7: 切题任务 `tasks/question_extract.py`

**Files:**
- Create: `backend/app/tasks/question_extract.py`
- Modify: `backend/app/tasks/__init__.py`（注册表副作用导入）
- Modify: `backend/app/services/question_service.py`（加 `create_extracted_question`）
- Test: `backend/tests/test_question_task.py`

**Interfaces:**
- Produces: `question_extract_task(session, payload)`，`payload = {"file_id": int, "subject_id": int, "origin": str, "created_by": int}`；返回 `{file_id, subject_id, detected_count, expected_count, created, duplicated, failed_items, degraded, warnings, elapsed_ms}`；`create_extracted_question(...) -> tuple[Question, bool]`。

- [ ] **Step 1: 写 6 条失败测试**

```python
"""S4-1 切题任务：部分成功、幂等、扫描件与越权失败路径。"""
from __future__ import annotations

import pytest

from app.ai.extract import ExtractedQuestion, ExtractResult
from app.ai.extract.question_extractor import QuestionExtractError
from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.models.file import File
from app.models.question import Question
from app.services import question_service
from app.tasks import question_extract


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self._next_id = 500

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def encode(self, texts, *, on_batch=None):
        return [[1.0, 0.0] for _ in texts]


class FakeStorage:
    def download_to(self, key: str, handle) -> None:
        handle.write(b"%PDF-1.4 fake")


def _file(file_id: int = 7, owner: int = 1, name: str = "试卷.pdf") -> File:
    record = File(user_id=owner, filename=name, mime="application/pdf", size=10,
                  sha256="a" * 64, storage_path="uploads/1/x.pdf", parse_status="done")
    record.id = file_id
    return record


def _extracted(stem: str = "已知函数 $f(x)=x$，求 $f(1)$。") -> ExtractedQuestion:
    return ExtractedQuestion(
        stem_md=stem, qtype="解答", difficulty=2, answer_md="1", answer_source="paper"
    )


def _payload(**overrides):
    payload = {"file_id": 7, "subject_id": 1, "origin": "upload", "created_by": 1}
    payload.update(overrides)
    return payload


TWENTY = "\n".join(
    ["一、选择题（本题共 20 小题）"] + [f"{index}. 第{index}题题干内容" for index in range(1, 21)]
)


def test_creates_all_questions(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(
        question_extract, "extract_questions", lambda **kwargs: ExtractResult(questions=[_extracted()])
    )
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["detected_count"] == 20
    assert result["created"] == 20
    assert result["duplicated"] == 0
    assert result["failed_items"] == []
    assert session.commits == 0  # 由 runner 统一提交


def test_reimport_marks_all_duplicated(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(
        question_extract, "extract_questions", lambda **kwargs: ExtractResult(questions=[_extracted()])
    )
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    existing = Question(subject_id=1, stem_md="已知函数", stem_hash="dup", qtype="解答", difficulty=2)
    existing.id = 99
    monkeypatch.setattr(question_service, "check_duplicate", lambda *args, **kwargs: existing)
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["created"] == 0
    assert result["duplicated"] == 20


def test_single_block_failure_is_reported(monkeypatch) -> None:
    text = "\n".join(
        ["一、选择题（本题共 3 小题）", "1. 坏题", "2. 好题甲", "3. 好题乙"]
    )
    monkeypatch.setattr(question_extract, "_load_text", lambda file: text)

    def fake_extract(**kwargs):
        if "坏题" in kwargs["question_text"]:
            raise QuestionExtractError("校验失败：选择题选项少于 2 项")
        return ExtractResult(questions=[_extracted()])

    monkeypatch.setattr(question_extract, "extract_questions", fake_extract)
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["created"] == 2
    assert [item["index"] for item in result["failed_items"]] == [1]
    assert "选项少于" in result["failed_items"][0]["reason"]


def test_scanned_pdf_fails(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        question_extract,
        "parse_document",
        lambda path: ParsedDocument(
            source=str(path), parser="pymupdf", is_scanned=True, degraded_reason="无文本", blocks=[]
        ),
    )
    session = FakeSession(objects={(File, 7): _file()})
    with pytest.raises(InvalidParamError) as excinfo:
        question_extract.question_extract_task(session, _payload())
    assert "扫描" in str(excinfo.value)


def test_file_owner_mismatch_fails() -> None:
    session = FakeSession(objects={(File, 7): _file(owner=2)})
    with pytest.raises(ForbiddenError):
        question_extract.question_extract_task(session, _payload(created_by=1))


def test_no_question_text_fails(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: "没有任何题号的说明文字")
    session = FakeSession(objects={(File, 7): _file()})
    with pytest.raises(InvalidParamError):
        question_extract.question_extract_task(session, _payload())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_task.py -v`
Expected: FAIL（`ModuleNotFoundError: app.tasks.question_extract`）

- [ ] **Step 3: 服务加 `create_extracted_question`**

`backend/app/services/question_service.py` 追加（import 区补 `from app.ai.extract.question_extractor import ExtractedQuestion` 与 `QuestionOrigin`，合并进 `models.enums` 那行）：

```python
def create_extracted_question(
    session: Session,
    *,
    extracted: ExtractedQuestion,
    subject_id: int,
    origin: str,
    created_by: int | None,
    source_file_id: int | None,
    vec: list[float],
) -> tuple[Question, bool]:
    """任务专用：返回 (题目, 是否命中重复)。不 commit —— 整卷由一个事务提交。

    重复题直接返回库里那道，不修改它：重复导入只补缺口，不覆盖人工修正。
    """
    if origin not in {item.value for item in QuestionOrigin}:
        raise InvalidParamError(f"非法的题目来源：{origin}")
    duplicate = check_duplicate(
        session, subject_id=subject_id, stem_hash=compute_stem_hash(extracted.stem_md), vec=vec
    )
    if duplicate is not None:
        return duplicate, True
    question = _persist_question(
        session,
        subject_id=subject_id,
        origin=origin,
        source_file_id=source_file_id,
        stem_md=extracted.stem_md,
        options_json=(
            [option.model_dump() for option in extracted.options] if extracted.options else None
        ),
        answer_md=extracted.answer_md,
        analysis_md=extracted.analysis_md,
        qtype=extracted.qtype,
        difficulty=extracted.difficulty,
        tags=None,
        verified=extracted.answer_source == "paper",
        embedding=vec,
        created_by=created_by,
        links=align_knowledge_points(
            session,
            subject_id=subject_id,
            text=extracted.stem_md,
            kp_names=extracted.kp_names,
            vec=vec,
        ),
    )
    return question, False
```

- [ ] **Step 4: 写任务处理函数**

```python
"""S4-1 试卷切题任务：下载 → 解析 → 规则切题 → 逐题抽取 → 判重落库。

为什么不自行 commit：题目是整卷一个事务，半卷落库比零题更难收拾；
runner 统一提交/回滚，失败即全卷不落（单题失败走 failed_items，不算整卷失败）。
"""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.embedding import get_embedding_client
from app.ai.extract import ExtractResult, ExtractedQuestion, extract_questions, split_questions
from app.ai.llm import get_llm_client
from app.ai.parse import parse_document
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.models.file import File
from app.services import question_service
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_QUESTION_EXTRACT = question_service.TASK_QUESTION_EXTRACT
_SUPPORTED_SUFFIXES = {".pdf", ".docx"}
_MAX_REASON_CHARS = 200


@register(TASK_QUESTION_EXTRACT)
def question_extract_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    file_id = int(payload["file_id"])
    subject_id = int(payload["subject_id"])
    origin = str(payload.get("origin") or "upload")
    owner_id = payload.get("created_by")

    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if owner_id is not None and file.user_id != int(owner_id):
        raise ForbiddenError("文件不属于当前用户")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise InvalidParamError(f"仅支持 PDF/DOCX 试卷，当前为 {suffix or '（无扩展名）'}")

    text = _load_text(file)
    split = split_questions(text)
    if not split.blocks:
        raise InvalidParamError("未识别到任何题目：" + "；".join(split.warnings))

    llm = get_llm_client()
    mode = "block" if split.degraded else "single"
    warnings = list(split.warnings)
    items: list[ExtractedQuestion] = []
    failed_items: list[dict[str, Any]] = []
    for block in split.blocks:
        try:
            result: ExtractResult = extract_questions(
                question_text=block.text,
                mode=mode,
                section_qtype=block.section_qtype,
                expected_count=split.expected_count if split.degraded else 1,
                llm_client=llm,
            )
        except Exception as exc:  # noqa: BLE001 —— 单题失败不该让整卷白切
            failed_items.append(
                {"index": block.index, "reason": str(exc)[:_MAX_REASON_CHARS]}
            )
            logger.warning(
                "question_extract_block_failed", extra={"file_id": file_id, "index": block.index}
            )
            continue
        if result.truncated:
            warnings.append(f"第 {block.index} 题区返回条数超过预期，已截断")
        items.extend(result.questions)

    if not items:
        raise InvalidParamError("全部题目抽取失败：" + "；".join(warnings))

    embedder = get_embedding_client()
    vectors = embedder.encode([question_service.embedding_text(item.stem_md) for item in items])

    created = duplicated = 0
    for extracted, vec in zip(items, vectors):
        _, is_duplicate = question_service.create_extracted_question(
            session,
            extracted=extracted,
            subject_id=subject_id,
            origin=origin,
            created_by=file.user_id,
            source_file_id=file.id,
            vec=vec,
        )
        if is_duplicate:
            duplicated += 1
        else:
            created += 1

    result_payload = {
        "file_id": file.id,
        "subject_id": subject_id,
        "detected_count": split.detected_count,
        "expected_count": split.expected_count,
        "created": created,
        "duplicated": duplicated,
        "failed_items": failed_items,
        "degraded": split.degraded,
        "warnings": warnings,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    logger.info("question_extract_done", extra={"file_id": file.id, "created": created})
    return result_payload


def _load_text(file: File) -> str:
    suffix = Path(file.filename).suffix.lower()
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(handle.name)
    try:
        with handle:
            get_storage().download_to(file.storage_path, handle)
        document = parse_document(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as exc:  # Windows 上解析器可能仍持有句柄
            logger.warning(
                "question_extract_tmp_cleanup_failed",
                extra={"file_id": file.id, "error": str(exc)},
            )
    if document.is_scanned:
        raise InvalidParamError("扫描版 PDF：无可抽取文本（拍照识别将在 S4-2 支持）")
    text = "\n".join(block.text.strip() for block in document.blocks if block.text.strip())
    if not text.strip():
        raise InvalidParamError("未解析出可用文本")
    return text
```

`backend/app/tasks/__init__.py`：按现有风格追加 `from app.tasks import question_extract  # noqa: F401`（保持注册表副作用）。若该文件用的是 `from app.tasks import xxx` 的清单式写法，则照抄既有那一行的模式加一项。

- [ ] **Step 5: 跑任务测试**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_task.py tests/test_task_registry.py -v`
Expected: 6 passed + 注册表测试仍绿

- [ ] **Step 6: 提交**

```bash
git add backend/app/tasks backend/app/services/question_service.py backend/tests/test_question_task.py
git commit -m "feat(s4-1): question.extract 任务编排（部分成功+幂等+扫描件失败）"
```

---

### Task 8: 放宽 `parse=False` 的文件类型（试卷原件的通道）

`POST /questions/import` 要能上传 PDF/DOCX 又不触发 `parse.document`。当前 `upload_file` 在 `parse=False` 时只放行图片（`该文件不是图片`），必须放开——否则试卷走不了这条路。

**Files:**
- Modify: `backend/app/services/file_service.py`
- Test: `backend/tests/test_file_service.py`

**Interfaces:**
- Produces: `allows_parse_flag(parse: bool, mime: str) -> bool`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_file_service.py` 末尾追加（import 区补 `allows_parse_flag`）：

```python
def test_parse_flag_allows_images_and_documents() -> None:
    assert allows_parse_flag(True, "text/markdown") is True
    assert allows_parse_flag(False, "image/png") is True
    assert allows_parse_flag(False, "application/pdf") is True
    assert allows_parse_flag(
        False,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ) is True


def test_parse_flag_still_rejects_plain_text_passthrough() -> None:
    assert allows_parse_flag(False, "text/markdown") is False
    assert allows_parse_flag(False, "text/plain") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_file_service.py -v -k parse_flag`
Expected: FAIL（`ImportError: cannot import name 'allows_parse_flag'`）

- [ ] **Step 3: 改 `file_service.py`**

在 `TYPE_TABLE` 定义之后补常量与函数：

```python
# parse=False 的合法类型：图片（编辑器插图）+ 需要保存原件但自行处理的任务（试卷切题）
_PASSTHROUGH_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def allows_parse_flag(parse: bool, mime: str) -> bool:
    """parse=False 表示“只存原件、不入队 parse.document”。

    S2-6 只允许图片；S4-1 起试卷原件也走这条通道（切题由 question.extract 负责）。
    """
    return parse or mime.startswith("image/") or mime in _PASSTHROUGH_MIMES
```

把 `upload_file` 内的守卫：

```python
    if not parse and not mime.startswith("image/"):
        raise InvalidParamError("该文件不是图片")
```

替换为：

```python
    if not allows_parse_flag(parse, mime):
        raise InvalidParamError("该文件既不是图片，也不是可入库的文档（PDF/DOCX）")
```

- [ ] **Step 4: 跑文件相关全部测试**

Run:
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_file_service.py tests/test_files_api.py tests/test_question_task.py -q
```
Expected: 全绿（含新增 2 条；S2-6 回归不受影响）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/file_service.py backend/tests/test_file_service.py
git commit -m "feat(s4-1): parse=false 放行 PDF/DOCX 试卷原件"
```

---

### Task 9: 读接口服务 + schemas + 9 个路由

**Files:**
- Modify: `backend/app/schemas/question.py`（补齐出参）
- Modify: `backend/app/services/question_service.py`（列表/详情）
- Create: `backend/app/api/v1/questions.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_questions_api.py`

**Interfaces:**
- Produces: `QuestionFilters`、`build_questions_query`、`list_questions(session, *, filters, page, sort) -> PageData[QuestionSummaryOut]`、`get_question_detail(session, *, question_id) -> QuestionDetailOut`、`ensure_subject_exists(session, subject_id)`。

- [ ] **Step 1: 补齐出参 schema**

`backend/app/schemas/question.py` 追加（顶部补 `from datetime import datetime`、`from decimal import Decimal`、`from pydantic import ConfigDict`）：

```python
class KpRefOut(BaseModel):
    kp_id: int
    kp_name: str
    kp_code: str
    weight: Decimal | None = None


class QuestionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    qtype: str
    difficulty: int
    origin: str
    verified: bool
    stem_md: str
    source_file_id: int | None = None
    created_by: int | None = None
    created_at: datetime
    kp_names: list[str] = Field(default_factory=list)


class QuestionDetailOut(QuestionSummaryOut):
    options_json: list[dict] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    stem_latex: str | None = None
    tags: list[str] | None = None
    kps: list[KpRefOut] = Field(default_factory=list)
```

- [ ] **Step 2: 补读服务**

`backend/app/services/question_service.py`：顶部补 import

```python
from dataclasses import dataclass

from sqlalchemy import Select, exists, select

from app.schemas.common import PageData
from app.schemas.question import QuestionDetailOut, QuestionSummaryOut, KpRefOut
from app.services.note_service import escape_like
from app.utils.pagination import PageParams, SortParams, apply_sort, paginate_query
```

文件末尾追加：

```python
@dataclass(frozen=True)
class QuestionFilters:
    subject_id: int | None = None
    qtype: str | None = None
    kp_id: int | None = None
    origin: str | None = None
    created_by: int | None = None
    verified: bool | None = None
    keyword: str | None = None
    source_file_id: int | None = None


SORTABLE = {
    "created_at": Question.created_at,
    "id": Question.id,
    "difficulty": Question.difficulty,
}


def ensure_subject_exists(session: Session, subject_id: int) -> None:
    _ensure_subject(session, subject_id)


def build_questions_query(*, filters: QuestionFilters) -> Select:
    """题库是公共语料，不按 user_id 过滤（SCHEMA §5.1 的口径）。

    kp_id 用 EXISTS 而不是 join：join 会让一题多知识点时出现重复行，
    count 也跟着翻倍。
    """
    stmt = select(Question)
    if filters.subject_id is not None:
        stmt = stmt.where(Question.subject_id == filters.subject_id)
    if filters.qtype:
        stmt = stmt.where(Question.qtype == filters.qtype)
    if filters.origin:
        stmt = stmt.where(Question.origin == filters.origin)
    if filters.created_by is not None:
        stmt = stmt.where(Question.created_by == filters.created_by)
    if filters.source_file_id is not None:
        stmt = stmt.where(Question.source_file_id == filters.source_file_id)
    if filters.verified is not None:
        stmt = stmt.where(Question.verified.is_(filters.verified))
    if filters.keyword:
        pattern = f"%{escape_like(filters.keyword)}%"
        stmt = stmt.where(Question.stem_md.ilike(pattern, escape="\\"))
    if filters.kp_id is not None:
        stmt = stmt.where(
            exists().where(
                QuestionKp.question_id == Question.id, QuestionKp.kp_id == filters.kp_id
            )
        )
    return stmt


def _attach_kp_names(session: Session, items: list[QuestionSummaryOut]) -> None:
    """一页一次 IN 批查，避免逐题查库（AGENTS §4 禁止循环查库）。"""
    ids = [item.id for item in items]
    if not ids:
        return
    rows = session.execute(
        select(QuestionKp.question_id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(QuestionKp.question_id.in_(ids))
        .order_by(QuestionKp.weight.desc())
    ).all()
    grouped: dict[int, list[str]] = {}
    for question_id, name in rows:
        grouped.setdefault(question_id, []).append(name)
    for item in items:
        item.kp_names = grouped.get(item.id, [])


def list_questions(
    session: Session, *, filters: QuestionFilters, page: PageParams, sort: SortParams
) -> PageData[QuestionSummaryOut]:
    stmt = apply_sort(
        build_questions_query(filters=filters),
        sort_by=sort.sort_by,
        order=sort.order,
        allowed=SORTABLE,
        default_sort="created_at",
    )
    data = paginate_query(session, stmt, page, item_model=QuestionSummaryOut)
    _attach_kp_names(session, data.items)
    return data


def get_question_detail(session: Session, *, question_id: int) -> QuestionDetailOut:
    question = _load_question(session, question_id)
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.code,
            QuestionKp.weight,
        )
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc())
    ).all()
    detail = QuestionDetailOut.model_validate(question)
    detail.kps = [
        KpRefOut(kp_id=row[0], kp_name=row[1], kp_code=row[2], weight=row[3]) for row in rows
    ]
    return detail
```

- [ ] **Step 3: 跑既有服务测试，确认没被打断**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_question_service.py tests/test_question_task.py -q`
Expected: 全绿

- [ ] **Step 4: 写路由 `api/v1/questions.py`**

```python
"""S4-1 题库接口：导入试卷（异步）、列表、详情、新增、编辑、拆分、合并、删除。

路由只做「参数校验 → service → Envelope」；权限与业务规则都在 question_service。
`/import` 必须声明在 `/{question_id}` 之前，否则会被路径参数吞掉。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import AppError, ForbiddenError
from app.core.storage import ObjectStorage, get_storage
from app.models.enums import QuestionOrigin
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.question import (
    QuestionCreateIn,
    QuestionDetailOut,
    QuestionMergeIn,
    QuestionSplitIn,
    QuestionSummaryOut,
    QuestionUpdateIn,
)
from app.schemas.tasks import TaskOut
from app.services import file_service, question_service, task_service
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/questions", tags=["questions"])

_SUPPORTED_SUFFIXES = {".pdf", ".docx"}


@router.post(
    "/import", status_code=202, response_model=Envelope[TaskOut], summary="导入试卷并异步切题"
)
def import_questions(
    file: UploadFile | None = File(default=None, description="PDF 或 DOCX 试卷"),
    subject_id: int = Query(..., description="学科 id"),
    origin: str = Query("upload", description="题目来源：textbook/exam/mock/upload"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    if file is None or not file.filename:
        raise AppError("请求缺少 file 字段", code=40000, http_status=400)
    if Path(file.filename).suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise AppError("仅支持 PDF 或 DOCX 试卷", code=40000, http_status=400)
    if origin not in {item.value for item in QuestionOrigin}:
        raise AppError(f"非法的题目来源：{origin}", code=40000, http_status=400)
    if current_user.role == "student" and origin != QuestionOrigin.UPLOAD.value:
        raise ForbiddenError("学生导入的题目只能记为学生上传")
    question_service.ensure_subject_exists(session, subject_id)
    record, _ = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage, parse=False
    )
    task = task_service.create_task(
        session,
        owner=current_user,
        name=question_service.TASK_QUESTION_EXTRACT,
        payload={
            "file_id": record.id,
            "subject_id": subject_id,
            "origin": origin,
            "created_by": current_user.id,
        },
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get("", response_model=Envelope[PageData[QuestionSummaryOut]], summary="题目列表（公共题库）")
def list_questions(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    subject_id: int | None = Query(None, description="学科 id"),
    qtype: str | None = Query(None, description="单选/多选/填空/解答"),
    kp_id: int | None = Query(None, description="只出挂了该知识点的题"),
    origin: str | None = Query(None, description="题目来源"),
    mine: bool = Query(False, description="只看自己导入的题"),
    verified: bool | None = Query(None, description="答案是否来自卷面"),
    keyword: str | None = Query(None, description="题干关键词"),
    source_file_id: int | None = Query(None, description="按导入的试卷筛选"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[QuestionSummaryOut]]:
    filters = question_service.QuestionFilters(
        subject_id=subject_id,
        qtype=qtype,
        kp_id=kp_id,
        origin=origin,
        created_by=current_user.id if mine else None,
        verified=verified,
        keyword=keyword,
        source_file_id=source_file_id,
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=question_service.list_questions(session, filters=filters, page=params, sort=sort),
    )


@router.get("/{question_id}", response_model=Envelope[QuestionDetailOut], summary="题目详情")
def get_question(
    question_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    detail = question_service.get_question_detail(session, question_id=question_id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.post("", status_code=201, response_model=Envelope[QuestionDetailOut], summary="手动新增题目")
def create_question(
    payload: QuestionCreateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    if current_user.role == "student" and payload.origin != QuestionOrigin.UPLOAD.value:
        raise ForbiddenError("学生录入的题目只能记为学生上传")
    question = question_service.create_question(session, payload=payload, creator=current_user)
    detail = question_service.get_question_detail(session, question_id=question.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.patch("/{question_id}", response_model=Envelope[QuestionDetailOut], summary="编辑题目")
def update_question(
    question_id: int,
    payload: QuestionUpdateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    question = question_service.update_question(
        session, question_id=question_id, payload=payload, viewer=current_user
    )
    detail = question_service.get_question_detail(session, question_id=question.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.post(
    "/{question_id}/split",
    response_model=Envelope[list[QuestionDetailOut]],
    summary="按标记把一题切成两题",
)
def split_question(
    question_id: int,
    payload: QuestionSplitIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[list[QuestionDetailOut]]:
    created = question_service.split_question(
        session, question_id=question_id, split_at=payload.split_at, viewer=current_user
    )
    data = [
        question_service.get_question_detail(session, question_id=item.id) for item in created
    ]
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/merge", response_model=Envelope[QuestionDetailOut], summary="合并多道题为一道")
def merge_questions(
    payload: QuestionMergeIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    merged = question_service.merge_questions(
        session, ids=payload.ids, viewer=current_user
    )
    detail = question_service.get_question_detail(session, question_id=merged.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.delete("/{question_id}", status_code=204, summary="删除题目")
def delete_question(
    question_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> None:
    question_service.delete_question(session, question_id=question_id, viewer=current_user)
```

> 注意 `POST /questions/merge` 与 `POST /questions/{question_id}/split` 的路径形状不同（merge 没有 id），不会冲突；`/merge` 也放在 `/{question_id}` 之后没问题，因为方法是 POST，而 `/{question_id}` 是 GET。若后续新增 `POST /{question_id}` 再调整顺序。

`backend/app/api/router.py`：import 行加 `questions`，并 `api_router.include_router(questions.router)`（放在 `kp` 之后）。

- [ ] **Step 5: 写 10 条接口测试**

```python
"""S4-1 题库接口：路由层只验状态码/壳结构/权限闸门。

业务规则（判重、阈值、引用保护）在 service 层用 FakeSession 测过，
这里只 monkeypatch service，避免把同一规则测两遍。
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.main import app
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.question import KpRefOut, QuestionDetailOut, QuestionSummaryOut
from app.services import file_service, question_service, task_service
from app.tasks.queue import get_task_queue


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.enqueued.append((name, task_id))


class FakeStorage:
    def download_to(self, key, handle) -> None:  # pragma: no cover - 路由测试不下载
        raise AssertionError("路由测试不应触发下载")


class FakeSession:
    def __init__(self, *, subject: Subject | None = None) -> None:
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0

    def get(self, entity, pk):
        if entity is Subject:
            return self.subject
        return None

    def add(self, instance) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(username=f"{role}_api", password_hash="hash", nickname="测试用户_1",
                grade="高一", role=role)
    user.id = user_id
    return user


def _summary(question_id: int = 1) -> QuestionSummaryOut:
    return QuestionSummaryOut(
        id=question_id, subject_id=1, qtype="单选", difficulty=2, origin="upload",
        verified=True, stem_md="已知函数 f(x)=x²，求 f(1)。",
        created_at=datetime.now(timezone.utc), kp_names=["函数的单调性"],
    )


def _detail(question_id: int = 1) -> QuestionDetailOut:
    return QuestionDetailOut(
        **_summary(question_id).model_dump(),
        options_json=[{"key": "A", "text": "1"}],
        answer_md="A",
        kps=[KpRefOut(kp_id=3, kp_name="函数的单调性", kp_code="kp.3")],
    )


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _client(*, session=None, user=None, role: str = "student") -> TestClient:
    app.dependency_overrides[get_db] = lambda: session or FakeSession()
    app.dependency_overrides[get_current_user] = lambda: user or _user(role=role)
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()
    return TestClient(app)


def test_import_returns_202_and_enqueues_extract(monkeypatch) -> None:
    record = SimpleNamespace(id=9, filename="试卷.pdf")
    monkeypatch.setattr(file_service, "upload_file", lambda *args, **kwargs: (record, False))
    task = SimpleNamespace(id=5, name="question.extract", status="pending",
                           created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(task_service, "create_task", lambda *args, **kwargs: task)
    client = _client(session=FakeSession(subject=Subject(name="数学")))
    response = client.post(
        "/api/v1/questions/import?subject_id=1",
        files={"file": ("试卷.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["data"]["name"] == "question.extract"


def test_import_student_cannot_use_exam_origin() -> None:
    client = _client(role="student")
    response = client.post(
        "/api/v1/questions/import?subject_id=1&origin=exam",
        files={"file": ("试卷.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_list_returns_page_shell(monkeypatch) -> None:
    monkeypatch.setattr(
        question_service, "list_questions",
        lambda *args, **kwargs: PageData(items=[_summary()], total=1, page=1, page_size=20),
    )
    response = _client().get("/api/v1/questions")
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["kp_names"] == ["函数的单调性"]


def test_list_mine_filters_by_current_user(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list(session, *, filters, page, sort):
        captured["created_by"] = filters.created_by
        return PageData(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(question_service, "list_questions", fake_list)
    _client(user=_user(user_id=42)).get("/api/v1/questions?mine=true")
    assert captured["created_by"] == 42


def test_detail_includes_kps(monkeypatch) -> None:
    monkeypatch.setattr(question_service, "get_question_detail", lambda *a, **k: _detail())
    response = _client().get("/api/v1/questions/1")
    assert response.status_code == 200
    assert response.json()["data"]["kps"][0]["kp_name"] == "函数的单调性"


def test_create_returns_201(monkeypatch) -> None:
    monkeypatch.setattr(
        question_service, "create_question", lambda *a, **k: SimpleNamespace(id=11)
    )
    monkeypatch.setattr(question_service, "get_question_detail", lambda *a, **k: _detail(11))
    response = _client().post(
        "/api/v1/questions",
        json={"subject_id": 1, "stem_md": "已知函数 f(x)=x²，求 f(1)。", "qtype": "解答", "difficulty": 2},
    )
    assert response.status_code == 201
    assert response.json()["data"]["id"] == 11


def test_create_duplicate_returns_409(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ConflictError("题目已存在")

    monkeypatch.setattr(question_service, "create_question", boom)
    response = _client().post(
        "/api/v1/questions",
        json={"subject_id": 1, "stem_md": "已知函数 f(x)=x²，求 f(1)。", "qtype": "解答", "difficulty": 2},
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40900


def test_update_other_student_question_returns_403(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ForbiddenError("只能修改自己创建的题目")

    monkeypatch.setattr(question_service, "update_question", boom)
    response = _client().patch("/api/v1/questions/1", json={"difficulty": 4})
    assert response.status_code == 403


def test_merge_cross_subject_returns_400(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise InvalidParamError("只能合并同一学科的题目")

    monkeypatch.setattr(question_service, "merge_questions", boom)
    response = _client(role="teacher").post("/api/v1/questions/merge", json={"ids": [1, 2]})
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_delete_referenced_returns_409(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ConflictError("题目已被错题本引用")

    monkeypatch.setattr(question_service, "delete_question", boom)
    response = _client().delete("/api/v1/questions/1")
    assert response.status_code == 409
```

> `InvalidParamError` 的 HTTP 状态是 **422**（`CODE_VALIDATION`，见 `core/exceptions.py`），所以第 9 条断言 422 而不是 400。spec §6 里“合并 subject 不同 → 400”应按实现统一为 422，事后回填 spec。

- [ ] **Step 6: 跑接口测试**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_questions_api.py -v`
Expected: 10 passed

- [ ] **Step 7: 全量回归**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿（新增约 66 条）

- [ ] **Step 8: 提交**

```bash
git add backend/app/api/v1/questions.py backend/app/api/router.py backend/app/schemas/question.py \
  backend/app/services/question_service.py backend/tests/test_questions_api.py
git commit -m "feat(s4-1): 题库 9 个接口（导入/列表/详情/增改/拆分/合并/删除）"
```

---

### Task 10: 前端类型/API/路由 + 导入页

**Files:**
- Create: `web/src/types/questions.ts`, `web/src/types/tasks.ts`
- Create: `web/src/api/questions.ts`, `web/src/api/tasks.ts`
- Create: `web/src/views/questions/ImportView.vue`
- Modify: `web/src/router/index.ts`, `web/src/layouts/nav.ts`

**Interfaces:**
- Produces: `importQuestions / listQuestions / getQuestion / createQuestion / updateQuestion / splitQuestion / mergeQuestions / deleteQuestion`、`getTask`；路由 `/questions`、`/questions/import`；导航项 `questions`。

- [ ] **Step 1: 写类型**

`web/src/types/questions.ts`：

```ts
/** S4-1 题库类型：字段与后端 schemas/question.py 一一对应。 */
export type QuestionType = '单选' | '多选' | '填空' | '解答'
export type QuestionOrigin = 'textbook' | 'exam' | 'mock' | 'upload' | 'ai'

export interface QuestionOption {
  key: string
  text: string
}

export interface KpRef {
  kp_id: number
  kp_name: string
  kp_code: string
  weight: number | null
}

export interface QuestionSummary {
  id: number
  subject_id: number
  qtype: QuestionType
  difficulty: number
  origin: QuestionOrigin
  verified: boolean
  stem_md: string
  source_file_id: number | null
  created_by: number | null
  created_at: string
  kp_names: string[]
}

export interface QuestionDetail extends QuestionSummary {
  options_json: QuestionOption[] | null
  answer_md: string | null
  analysis_md: string | null
  stem_latex: string | null
  tags: string[] | null
  kps: KpRef[]
}

export interface QuestionListParams {
  page?: number
  page_size?: number
  subject_id?: number
  qtype?: QuestionType
  kp_id?: number
  origin?: QuestionOrigin
  mine?: boolean
  verified?: boolean
  keyword?: string
  source_file_id?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}

export interface QuestionCreatePayload {
  subject_id: number
  stem_md: string
  options?: QuestionOption[] | null
  answer_md?: string | null
  analysis_md?: string | null
  qtype: QuestionType
  difficulty: number
  kp_ids?: number[]
  origin?: QuestionOrigin
  tags?: string[] | null
}

export type QuestionUpdatePayload = Partial<Omit<QuestionCreatePayload, 'subject_id'>> & {
  verified?: boolean
}
```

`web/src/types/tasks.ts`：

```ts
/** S2-7 任务类型 + S4-1 切题任务结果。 */
export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface TaskOut {
  id: number
  name: string
  status: TaskStatus
  created_at: string
}

export interface ExtractFailedItem {
  index: number
  reason: string
}

export interface ExtractTaskResult {
  file_id: number
  subject_id: number
  detected_count: number
  expected_count: number | null
  created: number
  duplicated: number
  failed_items: ExtractFailedItem[]
  degraded: boolean
  warnings: string[]
  elapsed_ms: number
}

export interface TaskDetail extends TaskOut {
  attempts: number
  payload: Record<string, unknown>
  result: ExtractTaskResult | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}
```

- [ ] **Step 2: 写 API 封装**

`web/src/api/tasks.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { TaskDetail } from '@/types/tasks'

export async function getTask(id: number): Promise<TaskDetail> {
  const resp = await http.get<ApiEnvelope<TaskDetail>>(`${API_PREFIX}/tasks/${id}`)
  return resp.data.data
}
```

`web/src/api/questions.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  QuestionCreatePayload,
  QuestionDetail,
  QuestionListParams,
  QuestionSummary,
  QuestionUpdatePayload,
} from '@/types/questions'
import type { TaskOut } from '@/types/tasks'

export async function importQuestions(
  file: File,
  subjectId: number,
  origin = 'upload',
): Promise<TaskOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<TaskOut>>(`${API_PREFIX}/questions/import`, form, {
    params: { subject_id: subjectId, origin },
    timeout: 120_000,
  })
  return resp.data.data
}

export async function listQuestions(
  params: QuestionListParams,
): Promise<PageData<QuestionSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<QuestionSummary>>>(`${API_PREFIX}/questions`, {
    params,
  })
  return resp.data.data
}

export async function getQuestion(id: number): Promise<QuestionDetail> {
  const resp = await http.get<ApiEnvelope<QuestionDetail>>(`${API_PREFIX}/questions/${id}`)
  return resp.data.data
}

export async function createQuestion(payload: QuestionCreatePayload): Promise<QuestionDetail> {
  const resp = await http.post<ApiEnvelope<QuestionDetail>>(`${API_PREFIX}/questions`, payload)
  return resp.data.data
}

export async function updateQuestion(
  id: number,
  payload: QuestionUpdatePayload,
): Promise<QuestionDetail> {
  const resp = await http.patch<ApiEnvelope<QuestionDetail>>(
    `${API_PREFIX}/questions/${id}`,
    payload,
  )
  return resp.data.data
}

export async function splitQuestion(id: number, splitAt: string): Promise<QuestionDetail[]> {
  const resp = await http.post<ApiEnvelope<QuestionDetail[]>>(
    `${API_PREFIX}/questions/${id}/split`,
    { split_at: splitAt },
  )
  return resp.data.data
}

export async function mergeQuestions(ids: number[]): Promise<QuestionDetail> {
  const resp = await http.post<ApiEnvelope<QuestionDetail>>(
    `${API_PREFIX}/questions/merge`,
    { ids },
  )
  return resp.data.data
}

export async function deleteQuestion(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/questions/${id}`)
}
```

- [ ] **Step 3: 加路由与导航**

`web/src/router/index.ts` 在 `knowledge` 之后插入：

```ts
        {
          path: 'questions',
          name: 'questions',
          component: () => import('@/views/questions/ReviewView.vue'),
          meta: { title: '题库', nav: 'questions' },
        },
        {
          path: 'questions/import',
          name: 'question-import',
          component: () => import('@/views/questions/ImportView.vue'),
          meta: { title: '导入试卷', nav: 'questions' },
        },
```

`web/src/layouts/nav.ts` 改为（序号顺延，现有测试未硬编码序号）：

```ts
export const NAV_ITEMS: NavItem[] = [
  { index: '01', label: '笔记', name: 'notes', path: '/notes' },
  { index: '02', label: '文件', name: 'files', path: '/files' },
  { index: '03', label: '知识库', name: 'knowledge', path: '/knowledge' },
  { index: '04', label: '题库', name: 'questions', path: '/questions' },
  { index: '05', label: '智能问答', name: 'qa', path: '/qa' },
  { index: '06', label: '错题本', name: 'mistakes', path: '/mistakes' },
  { index: '07', label: '复习计划', name: 'plan', path: '/plan' },
]
```

- [ ] **Step 4: 写 `ImportView.vue`**

```vue
<script setup lang="ts">
/** S4-1 导入试卷：上传 → 轮询任务 → 展示统计（无题级进度，只显示已用时）。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import { importQuestions } from '@/api/questions'
import { getTask } from '@/api/tasks'
import { listSubjects } from '@/api/kp'
import type { SubjectOut } from '@/types/kp'
import type { ExtractTaskResult, TaskDetail } from '@/types/tasks'

const router = useRouter()
const subjects = ref<SubjectOut[]>([])
const subjectId = ref<number | null>(null)
const origin = ref('upload')
const file = ref<File | null>(null)
const task = ref<TaskDetail | null>(null)
const elapsed = ref(0)
const submitting = ref(false)
let timer: number | undefined

const result = computed<ExtractTaskResult | null>(() => task.value?.result ?? null)
const running = computed(
  () => task.value?.status === 'pending' || task.value?.status === 'running',
)
const failedItems = computed(() => result.value?.failed_items ?? [])

function stopPolling(): void {
  if (timer !== undefined) {
    window.clearInterval(timer)
    timer = undefined
  }
}

function onExceed(): void {
  ElMessage.warning('一次只能导入一份试卷')
}

function onFileChange(uploadFile: UploadFile): void {
  file.value = (uploadFile.raw as File | undefined) ?? null
}

async function poll(taskId: number): Promise<void> {
  try {
    const detail = await getTask(taskId)
    task.value = detail
    if (detail.status === 'succeeded' || detail.status === 'failed') stopPolling()
  } catch {
    stopPolling()
  }
}

async function submit(): Promise<void> {
  if (!file.value || !subjectId.value) {
    ElMessage.warning('请选择学科并上传试卷')
    return
  }
  submitting.value = true
  elapsed.value = 0
  try {
    task.value = await importQuestions(file.value, subjectId.value, origin.value)
    const startedAt = Date.now()
    stopPolling()
    timer = window.setInterval(() => {
      elapsed.value = Math.round((Date.now() - startedAt) / 1000)
      if (task.value) void poll(task.value.id)
    }, 1500)
  } finally {
    submitting.value = false
  }
}

function goReview(): void {
  const fileId = result.value?.file_id
  router.push({ path: '/questions', query: fileId ? { source_file_id: String(fileId) } : {} })
}

onMounted(async () => {
  subjects.value = await listSubjects()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="import-view">
    <PageHeader title="导入试卷" description="上传 PDF 或 DOCX 试卷，系统自动切题并入库。" />

    <el-card shadow="never" class="import-view__card">
      <el-form label-width="88px">
        <el-form-item label="学科">
          <el-select v-model="subjectId" placeholder="选择学科" style="width: 220px">
            <el-option
              v-for="subject in subjects"
              :key="subject.id"
              :label="subject.name"
              :value="subject.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="题目来源">
          <el-radio-group v-model="origin">
            <el-radio value="upload">学生上传</el-radio>
            <el-radio value="exam">考试卷</el-radio>
            <el-radio value="mock">模拟卷</el-radio>
            <el-radio value="textbook">教材</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="试卷文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".pdf,.docx"
            :on-change="onFileChange"
            :on-exceed="onExceed"
          >
            <el-button>选择文件</el-button>
            <template #tip>
              <div class="import-view__tip">仅支持 PDF / DOCX；扫描件与拍照识别将在 S4-2 支持。</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">开始切题</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="task" shadow="never" class="import-view__card">
      <template #header>
        <span>切题任务 #{{ task.id }}</span>
      </template>
      <el-alert
        v-if="running"
        type="info"
        :closable="false"
        show-icon
        :title="`切题中… 已用时 ${elapsed}s（20 题通常 60–90s）`"
      />
      <el-alert
        v-else-if="task.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        :title="`切题失败：${task.error ?? '未知原因'}`"
      />
      <template v-else>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="识别题数">{{ result?.detected_count }}</el-descriptions-item>
          <el-descriptions-item label="新增">{{ result?.created }}</el-descriptions-item>
          <el-descriptions-item label="重复跳过">{{ result?.duplicated }}</el-descriptions-item>
          <el-descriptions-item label="卷面声明">{{ result?.expected_count ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="降级切题">{{ result?.degraded ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ Math.round((result?.elapsed_ms ?? 0) / 1000) }}s
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="failedItems.length"
          class="import-view__alert"
          type="warning"
          :closable="false"
          show-icon
          title="部分题目未能自动切出，请人工补录"
        >
          <div v-for="item in failedItems" :key="item.index">
            第 {{ item.index }} 题：{{ item.reason }}
          </div>
        </el-alert>
        <el-alert
          v-for="warning in result?.warnings ?? []"
          :key="warning"
          class="import-view__alert"
          type="warning"
          :closable="false"
          :title="warning"
        />

        <el-button type="primary" @click="goReview">去审题</el-button>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.import-view__card {
  margin-bottom: 16px;
}
.import-view__tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.import-view__alert {
  margin: 12px 0;
}
</style>
```

> `SubjectOut` 字段以 `web/src/types/kp.ts` 为准（至少含 `id`/`name`）；若实际字段名不同，按该文件改模板里的 `subject.id` / `subject.name`。

- [ ] **Step 5: 类型检查 + 构建**

Run:
```powershell
cd web
npm run build
```
Expected: 构建通过（新增两个视图被路由按需加载）

- [ ] **Step 6: 提交**

```bash
git add web/src/types/questions.ts web/src/types/tasks.ts web/src/api/questions.ts \
  web/src/api/tasks.ts web/src/views/questions/ImportView.vue web/src/router/index.ts web/src/layouts/nav.ts
git commit -m "feat(s4-1): 前端题库 API/路由/导航与导入试卷页"
```

---

### Task 11: 审题页 `ReviewView.vue`

**Files:**
- Create: `web/src/views/questions/ReviewView.vue`
- Create: `web/src/views/questions/__tests__/ReviewView.spec.ts`

**Interfaces:**
- Consumes: `listQuestions / getQuestion / updateQuestion / splitQuestion / mergeQuestions / deleteQuestion`、`getKpTree`。
- Produces: 路由名 `questions` 的页面组件。

- [ ] **Step 1: 写 6 条失败测试**

```ts
/** S4-1 审题页：列表、详情、保存、拆分、公式渲染、越权只读。 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewView from '@/views/questions/ReviewView.vue'
import { getQuestion, listQuestions, splitQuestion, updateQuestion } from '@/api/questions'
import { getKpTree } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/questions', () => ({
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
  updateQuestion: vi.fn(),
  splitQuestion: vi.fn(),
  mergeQuestions: vi.fn(),
  deleteQuestion: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ getKpTree: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

const SUMMARY = {
  id: 1,
  subject_id: 1,
  qtype: '解答' as const,
  difficulty: 2,
  origin: 'upload' as const,
  verified: true,
  stem_md: '已知函数 $f(x)=x^2$，求 $f(1)$。',
  source_file_id: 3,
  created_by: 1,
  created_at: '2026-11-02T00:00:00Z',
  kp_names: ['函数的单调性'],
}

const DETAIL = {
  ...SUMMARY,
  options_json: null,
  answer_md: '1',
  analysis_md: null,
  stem_latex: null,
  tags: null,
  kps: [{ kp_id: 3, kp_name: '函数的单调性', kp_code: 'kp.3', weight: 0.8 }],
}

function makeWrapper(createdBy = 1, role = 'student') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = { id: 1, role } as never
  return mount(ReviewView, {
    global: {
      plugins: [ElementPlus, pinia],
      stubs: { MdPreview: { props: ['modelValue'], template: '<div class="md">{{ modelValue }}</div>' } },
    },
  })
}

describe('ReviewView', () => {
  beforeEach(() => {
    vi.mocked(listQuestions).mockResolvedValue({ items: [{ ...SUMMARY, created_by: 1 }], total: 1, page: 1, page_size: 20 })
    vi.mocked(getQuestion).mockResolvedValue(DETAIL)
    vi.mocked(getKpTree).mockResolvedValue({ nodes: [] } as never)
    vi.mocked(updateQuestion).mockResolvedValue(DETAIL)
    vi.mocked(splitQuestion).mockResolvedValue([DETAIL, DETAIL])
  })

  it('renders question list', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    expect(wrapper.text()).toContain('已知函数')
  })

  it('loads detail when a row is clicked', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(getQuestion).toHaveBeenCalledWith(1)
  })

  it('saves stem edits through PATCH', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    const stem = wrapper.find('[data-test="stem"]')
    await stem.setValue('已知函数 $f(x)=x^2$，求 $f(2)$。')
    await wrapper.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(updateQuestion).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ stem_md: '已知函数 $f(x)=x^2$，求 $f(2)$。' }),
    )
  })

  it('splits with the given marker', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="split-at"]').setValue('2.')
    await wrapper.find('[data-test="split"]').trigger('click')
    await flushPromises()
    expect(splitQuestion).toHaveBeenCalledWith(1, '2.')
  })

  it('renders formulas through the markdown preview', async () => {
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.md').text()).toContain('$f(x)=x^2$')
  })

  it('disables editing for other students questions', async () => {
    vi.mocked(listQuestions).mockResolvedValue({ items: [{ ...SUMMARY, created_by: 99 }], total: 1, page: 1, page_size: 20 })
    const wrapper = makeWrapper()
    await flushPromises()
    await wrapper.find('[data-test="row-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="save"]').attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test -- ReviewView`
Expected: FAIL（找不到 `@/views/questions/ReviewView.vue`）

- [ ] **Step 3: 写 `ReviewView.vue`**

```vue
<script setup lang="ts">
/** S4-1 审题页：左侧题库列表，右侧单题编辑；支持新增、合并、拆分、删除。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

import PageHeader from '@/components/common/PageHeader.vue'
import {
  deleteQuestion,
  getQuestion,
  listQuestions,
  mergeQuestions,
  splitQuestion,
  updateQuestion,
} from '@/api/questions'
import { getKpTree } from '@/api/kp'
import { useAuthStore } from '@/stores/auth'
import type { QuestionDetail, QuestionOption, QuestionSummary, QuestionType } from '@/types/questions'
import type { KpNode } from '@/types/kp'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const rows = ref<QuestionSummary[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const loading = ref(false)
const detail = ref<QuestionDetail | null>(null)
const splitAt = ref('')
const kpOptions = ref<{ id: number; label: string }[]>([])
const selection = ref<number[]>([])

const form = reactive({
  stem_md: '',
  qtype: '解答' as QuestionType,
  difficulty: 3,
  answer_md: '',
  analysis_md: '',
  options: [] as QuestionOption[],
  kp_ids: [] as number[],
})

const canEdit = computed(() => {
  const user = auth.user
  if (!user || !detail.value) return false
  return user.role === 'teacher' || user.role === 'admin' || detail.value.created_by === user.id
})

function flattenKps(nodes: KpNode[], prefix = ''): { id: number; label: string }[] {
  const out: { id: number; label: string }[] = []
  for (const node of nodes) {
    out.push({ id: node.id, label: `${prefix}${node.name}` })
    const children = (node as unknown as { children?: KpNode[] }).children ?? []
    if (children.length) out.push(...flattenKps(children, `${prefix}${node.name} / `))
  }
  return out
}

async function loadList(): Promise<void> {
  loading.value = true
  try {
    const data = await listQuestions({
      page: page.value,
      page_size: 20,
      keyword: keyword.value || undefined,
      source_file_id: route.query.source_file_id
        ? Number(route.query.source_file_id)
        : undefined,
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function openQuestion(id: number): Promise<void> {
  const data = await getQuestion(id)
  detail.value = data
  form.stem_md = data.stem_md
  form.qtype = data.qtype
  form.difficulty = data.difficulty
  form.answer_md = data.answer_md ?? ''
  form.analysis_md = data.analysis_md ?? ''
  form.options = data.options_json ? [...data.options_json] : []
  form.kp_ids = data.kps.map((item) => item.kp_id)
  splitAt.value = ''
  if (!kpOptions.value.length) {
    const tree = await getKpTree(String(data.subject_id))
    kpOptions.value = flattenKps((tree as unknown as { nodes?: KpNode[] }).nodes ?? [])
  }
}

async function save(): Promise<void> {
  if (!detail.value) return
  const updated = await updateQuestion(detail.value.id, {
    stem_md: form.stem_md,
    qtype: form.qtype,
    difficulty: form.difficulty,
    answer_md: form.answer_md || null,
    analysis_md: form.analysis_md || null,
    options: form.options.length ? form.options : null,
    kp_ids: form.kp_ids,
  })
  detail.value = updated
  ElMessage.success('已保存')
  await loadList()
}

async function split(): Promise<void> {
  if (!detail.value || !splitAt.value.trim()) {
    ElMessage.warning('请填写切分标记（第二道题开头的文字）')
    return
  }
  const created = await splitQuestion(detail.value.id, splitAt.value.trim())
  ElMessage.success(`已拆成 ${created.length} 道题`)
  detail.value = created[0] ?? null
  await loadList()
}

async function merge(): Promise<void> {
  if (selection.value.length < 2) {
    ElMessage.warning('请至少勾选 2 道题')
    return
  }
  const merged = await mergeQuestions(selection.value)
  ElMessage.success(`已合并为题目 #${merged.id}`)
  selection.value = []
  await loadList()
  await openQuestion(merged.id)
}

async function remove(): Promise<void> {
  if (!detail.value) return
  await ElMessageBox.confirm('删除后不可恢复，确认删除这道题？', '确认删除', { type: 'warning' })
  await deleteQuestion(detail.value.id)
  ElMessage.success('已删除')
  detail.value = null
  await loadList()
}

function addOption(): void {
  const nextKey = String.fromCharCode(65 + form.options.length)
  form.options.push({ key: nextKey, text: '' })
}

function createNew(): void {
  detail.value = null
  form.stem_md = ''
  form.qtype = '解答'
  form.difficulty = 3
  form.answer_md = ''
  form.analysis_md = ''
  form.options = []
  form.kp_ids = []
  router.push({ path: '/questions' })
}

onMounted(loadList)
</script>

<template>
  <div class="review-view">
    <PageHeader title="题库" description="AI 切题后逐题核对：可直接用 / 需小改 / 需重录。">
      <template #extra>
        <el-button @click="router.push('/questions/import')">导入试卷</el-button>
      </template>
    </PageHeader>

    <div class="review-view__body">
      <el-card shadow="never" class="review-view__list">
        <div class="review-view__toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索题干"
            clearable
            @keyup.enter="loadList"
          />
          <el-button :disabled="selection.length < 2" data-test="merge" @click="merge">
            合并所选（{{ selection.length }}）
          </el-button>
          <el-button data-test="new" @click="createNew">新增</el-button>
        </div>
        <el-table
          v-loading="loading"
          :data="rows"
          height="620"
          @selection-change="(rows: QuestionSummary[]) => (selection = rows.map((row) => row.id))"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="id" label="ID" width="64" />
          <el-table-column prop="qtype" label="题型" width="72" />
          <el-table-column prop="difficulty" label="难度" width="64" />
          <el-table-column label="题干" min-width="220">
            <template #default="{ row }">
              <span :data-test="`row-${row.id}`" class="review-view__stem" @click="openQuestion(row.id)">
                {{ row.stem_md.slice(0, 40) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="知识点" min-width="120">
            <template #default="{ row }">
              <el-tag v-for="name in row.kp_names" :key="name" size="small">{{ name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="答案" width="72">
            <template #default="{ row }">
              <el-tag :type="row.verified ? 'success' : 'warning'" size="small">
                {{ row.verified ? '卷面' : 'AI/无' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="page"
          :total="total"
          :page-size="20"
          layout="prev, pager, next"
          @current-change="loadList"
        />
      </el-card>

      <el-card v-if="detail" shadow="never" class="review-view__detail">
        <template #header>
          <span>题目 #{{ detail.id }}</span>
          <span class="review-view__hint">（题干含公式请用 $...$）</span>
        </template>

        <el-form label-width="72px">
          <el-form-item label="题干">
            <el-input v-model="form.stem_md" data-test="stem" type="textarea" :rows="6" />
          </el-form-item>
          <el-form-item label="预览">
            <MdPreview :model-value="form.stem_md" preview-theme="github" />
          </el-form-item>
          <el-form-item label="题型">
            <el-select v-model="form.qtype" style="width: 140px">
              <el-option label="单选" value="单选" />
              <el-option label="多选" value="多选" />
              <el-option label="填空" value="填空" />
              <el-option label="解答" value="解答" />
            </el-select>
          </el-form-item>
          <el-form-item label="难度">
            <el-rate v-model="form.difficulty" :max="5" />
          </el-form-item>
          <el-form-item v-if="form.qtype === '单选' || form.qtype === '多选'" label="选项">
            <div v-for="(option, index) in form.options" :key="index" class="review-view__option">
              <el-input v-model="option.key" style="width: 60px" />
              <el-input v-model="option.text" />
            </div>
            <el-button size="small" @click="addOption">增加选项</el-button>
          </el-form-item>
          <el-form-item label="答案">
            <el-input v-model="form.answer_md" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="解析">
            <el-input v-model="form.analysis_md" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="知识点">
            <el-select v-model="form.kp_ids" multiple filterable style="width: 100%">
              <el-option
                v-for="option in kpOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" data-test="save" :disabled="!canEdit" @click="save">
              保存
            </el-button>
            <el-button danger :disabled="!canEdit" @click="remove">删除</el-button>
          </el-form-item>
        </el-form>

        <el-divider content-position="left">拆分 / 合并</el-divider>
        <el-input
          v-model="splitAt"
          data-test="split-at"
          placeholder="切分标记：第二道题开头的文字，例如 2."
          style="max-width: 320px"
          :disabled="!canEdit"
        />
        <el-button data-test="split" :disabled="!canEdit" @click="split">拆分</el-button>
        <p class="review-view__hint">
          合并请在左侧勾选 2–10 道题后点「合并所选」；合并与拆分都会硬删原题，操作不可撤销。
        </p>
      </el-card>
      <el-card v-else shadow="never" class="review-view__detail">
        <el-empty description="点击左侧题干预览开始审题" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.review-view__body {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
  gap: 16px;
}
.review-view__toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.review-view__stem {
  cursor: pointer;
  color: var(--el-color-primary);
}
.review-view__hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 8px;
}
.review-view__option {
  display: flex;
  gap: 8px;
  width: 100%;
  margin-bottom: 6px;
}
</style>
```

> `KpNode` 与 `getKpTree` 的参数以 `web/src/types/kp.ts` / `api/kp.ts` 为准：树根字段若不是 `nodes`，把 `flattenKps(...)` 的取值改成实际字段名（如 `tree.children`）。`getKpTree` 若需要学科 code 而不是 id，按 `pages` 现有调用方式改。

- [ ] **Step 4: 跑前端测试**

Run: `cd web && npm run test -- ReviewView`
Expected: 6 passed

- [ ] **Step 5: 全量前端测试 + 构建**

Run:
```powershell
cd web
npm run test
npm run build
```
Expected: 全绿（约 120 条）、构建成功

- [ ] **Step 6: 提交**

```bash
git add web/src/views/questions
git commit -m "feat(s4-1): 审题页（编辑/拆分/合并/删除/公式预览）与 6 条组件测试"
```

---

### Task 12: 验收卷生成脚本（自编 20 题）

**Files:**
- Create: `scripts/make_s4_1_exam_paper.py`
- Create: `backend/tests/test_make_exam_paper.py`
- Modify: `backend/app/ai/prompts/question_extract_v1.md`（补一条：卷面含【答案】段落时 stem 必须剔除）

**Interfaces:**
- Produces: `QUESTIONS: list[dict]`（20 条）、`build_document() -> Document`、CLI `python scripts/make_s4_1_exam_paper.py [输出路径]`。

- [ ] **Step 1: 写数据结构测试**

```python
"""S4-1 验收卷的数据结构：20 题、题号连续、每题有答案。

这是自编卷（非真题），测试只保证结构与文档一致，不保证题目难度分布。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from make_s4_1_exam_paper import QUESTIONS  # noqa: E402


def test_twenty_questions_with_continuous_numbers() -> None:
    assert [item["no"] for item in QUESTIONS] == list(range(1, 21))


def test_section_split_8_4_8() -> None:
    choice = [item for item in QUESTIONS if item.get("options")]
    blank = [item for item in QUESTIONS if not item.get("options") and item["no"] <= 12]
    solution = [item for item in QUESTIONS if not item.get("options") and item["no"] > 12]
    assert (len(choice), len(blank), len(solution)) == (8, 4, 8)


def test_every_question_has_answer_and_analysis() -> None:
    for item in QUESTIONS:
        assert item["answer"].strip(), item["no"]
        assert item["analysis"].strip(), item["no"]


def test_stems_do_not_start_with_digit() -> None:
    """题号由渲染器加，题干自带数字会让切题器把题干当新题。"""
    for item in QUESTIONS:
        assert not item["stem"].lstrip()[:1].isdigit(), item["no"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_make_exam_paper.py -v`
Expected: FAIL（`ModuleNotFoundError: make_s4_1_exam_paper`）

- [ ] **Step 3: 写脚本**

```python
"""生成 S4-1 验收用的 20 题高中数学卷（本人自编，非真实考试卷）。

为什么用纯文本 + Unicode 上下标而不是 Word 公式对象：`DocxParser` 抽的是纯文本，
OMML 公式会抽成空串；用 x²、√3 这类写法既能被抽出，也能被 KaTeX 正确渲染。
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt

DEFAULT_TARGET = (
    Path(__file__).resolve().parents[1] / ".." / "测试数据" / "高中数学试卷-高二期末综合卷（20题）.docx"
)

QUESTIONS: list[dict] = [
    {"no": 1, "stem": "已知集合 A={1,2,3}，B={2,3,4}，则 A∩B=（ ）",
     "options": ["A. {1}", "B. {2,3}", "C. {1,4}", "D. {1,2,3,4}"],
     "answer": "B", "analysis": "交集取两集合的公共元素，即 2 与 3。"},
    {"no": 2, "stem": "函数 f(x)=x²-4x+3 的最小值是（ ）",
     "options": ["A. -1", "B. 0", "C. 1", "D. 3"],
     "answer": "A", "analysis": "f(x)=(x-2)²-1，故最小值为 -1。"},
    {"no": 3, "stem": "等差数列 {aₙ} 中 a₁=2，公差 d=3，则 a₅=（ ）",
     "options": ["A. 11", "B. 12", "C. 14", "D. 17"],
     "answer": "C", "analysis": "a₅=a₁+4d=2+12=14。"},
    {"no": 4, "stem": "已知 sinα=3/5，且 α 为第一象限角，则 cosα=（ ）",
     "options": ["A. 4/5", "B. -4/5", "C. 3/4", "D. -3/4"],
     "answer": "A", "analysis": "第一象限余弦为正，cosα=√(1-9/25)=4/5。"},
    {"no": 5, "stem": "不等式 x²-5x+6<0 的解集是（ ）",
     "options": ["A. (2,3)", "B. (-∞,2)∪(3,+∞)", "C. (1,6)", "D. 空集"],
     "answer": "A", "analysis": "x²-5x+6=(x-2)(x-3)<0，解为 2<x<3。"},
    {"no": 6, "stem": "函数 f(x)=log₂(x-1) 的定义域是（ ）",
     "options": ["A. (0,+∞)", "B. (1,+∞)", "C. [1,+∞)", "D. 全体实数"],
     "answer": "B", "analysis": "真数 x-1>0，即 x>1。"},
    {"no": 7, "stem": "已知向量 a=(1,2)，b=(x,4)，且 a∥b，则 x=（ ）",
     "options": ["A. 1", "B. 2", "C. 4", "D. 8"],
     "answer": "B", "analysis": "平行则 1×4-2×x=0，得 x=2。"},
    {"no": 8, "stem": "从 5 名同学中选 2 人参加比赛，不同的选法有（ ）",
     "options": ["A. 5 种", "B. 10 种", "C. 20 种", "D. 25 种"],
     "answer": "B", "analysis": "C(5,2)=10。"},
    {"no": 9, "stem": "已知等比数列 {aₙ} 中 a₁=1，公比 q=2，则 a₄= ______。",
     "options": None, "answer": "8", "analysis": "a₄=a₁q³=1×2³=8。"},
    {"no": 10, "stem": "若 f(x)=x³-3x，则 f'(1)= ______。",
     "options": None, "answer": "0", "analysis": "f'(x)=3x²-3，f'(1)=0。"},
    {"no": 11, "stem": "圆 x²+y²-2x=0 的圆心坐标是 ______。",
     "options": None, "answer": "(1,0)", "analysis": "配方得 (x-1)²+y²=1，圆心 (1,0)。"},
    {"no": 12, "stem": "已知 tanα=2，则 sin2α= ______。",
     "options": None, "answer": "4/5", "analysis": "sin2α=2tanα/(1+tan²α)=4/5。"},
    {"no": 13, "stem": "已知函数 f(x)=x²-2x+3。（1）求 f(x) 图象的对称轴；（2）求 f(x) 在区间 [0,3] 上的最大值与最小值。",
     "options": None, "answer": "对称轴 x=1；最小值 2，最大值 6",
     "analysis": "f(x)=(x-1)²+2，对称轴 x=1；区间 [0,3] 上 f(1)=2 最小，f(3)=6 最大。"},
    {"no": 14, "stem": "已知等差数列 {aₙ} 中 a₂=5，a₆=17。（1）求通项公式；（2）求前 10 项和 S₁₀。",
     "options": None, "answer": "aₙ=3n-1；S₁₀=155",
     "analysis": "4d=12 得 d=3，a₁=2，aₙ=3n-1；S₁₀=10×2+45×3=155。"},
    {"no": 15, "stem": "已知 sinα=4/5，α∈(π/2, π)，求 sin(α+π/6) 的值。",
     "options": None, "answer": "(4√3-3)/10",
     "analysis": "cosα=-3/5；sin(α+π/6)=sinαcos(π/6)+cosαsin(π/6)=(4√3-3)/10。"},
    {"no": 16, "stem": "已知函数 f(x)=x³-3x²+2。（1）求 f'(x)；（2）求 f(x) 的极值。",
     "options": None, "answer": "f'(x)=3x²-6x；极大值 2，极小值 -2",
     "analysis": "f'(x)=3x(x-2)，x=0 处极大值 f(0)=2，x=2 处极小值 f(2)=-2。"},
    {"no": 17, "stem": "已知直线 l: y=x+1 与圆 C: x²+y²=4 相交于 A、B 两点，求弦长 |AB|。",
     "options": None, "answer": "√14",
     "analysis": "圆心到直线距离 d=1/√2，|AB|=2√(4-1/2)=√14。"},
    {"no": 18, "stem": "某校高一年级共有 300 人，用分层抽样抽取 30 人，其中男生 18 人，估计该校高一男生人数。",
     "options": None, "answer": "180 人",
     "analysis": "抽样比 30/300=1/10，男生 18÷(1/10)=180。"},
    {"no": 19, "stem": "数列 {aₙ} 满足 a₁=1，aₙ₊₁=2aₙ+1。（1）求证 {aₙ+1} 是等比数列；（2）求 aₙ。",
     "options": None, "answer": "aₙ+1=2ⁿ，即 aₙ=2ⁿ-1",
     "analysis": "(aₙ₊₁+1)/(aₙ+1)=2，首项 2，故 aₙ+1=2ⁿ。"},
    {"no": 20, "stem": "已知函数 f(x)=ln x-x+1。（1）求 f(x) 的单调区间；（2）证明 f(x)≤0。",
     "options": None, "answer": "增区间 (0,1)，减区间 (1,+∞)；最大值 f(1)=0，故 f(x)≤0",
     "analysis": "f'(x)=1/x-1=(1-x)/x，x=1 处取最大值 0。"},
]

_SECTIONS = (
    ("一、选择题（本题共 8 小题，每小题 5 分，共 40 分）", 0, 8),
    ("二、填空题（本题共 4 小题，每小题 5 分，共 20 分）", 8, 12),
    ("三、解答题（本题共 8 小题，共 90 分。解答应写出文字说明、证明过程或演算步骤）", 12, 20),
)


def _write_question(document: Document, item: dict) -> None:
    document.add_paragraph(f"{item['no']}. {item['stem']}")
    if item.get("options"):
        document.add_paragraph("    ".join(item["options"]))
    document.add_paragraph(f"【答案】{item['answer']}　【解析】{item['analysis']}")


def build_document() -> Document:
    document = Document()
    title = document.add_paragraph("高二数学期末综合卷（自编 20 题）")
    title.runs[0].font.size = Pt(16)
    document.add_paragraph("说明：本卷为毕业设计验收自编卷，非真实考试卷；答案与解析随题给出。")
    for heading, start, end in _SECTIONS:
        document.add_paragraph(heading)
        for item in QUESTIONS[start:end]:
            _write_question(document, item)
    return document


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    build_document().save(target)
    print(f"已生成 {len(QUESTIONS)} 题：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: prompt 补一条规则**

`backend/app/ai/prompts/question_extract_v1.md` 在规则 4 的下一行插入：

```markdown
5. 若原文含"【答案】…【解析】…"段落：stem_md 必须剔除该段落，答案写进 answer_md、解析写进 analysis_md，并置 answer_source="paper"。
```

并把原规则 5、6 的序号顺延为 6、7。

- [ ] **Step 5: 跑数据结构测试并生成真实文件**

Run:
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_make_exam_paper.py -v
cd ..
..\.venv\Scripts\python.exe scripts\make_s4_1_exam_paper.py
```
Expected: 4 passed；终端打印 `已生成 20 题：...测试数据\高中数学试卷-高二期末综合卷（20题）.docx`，文件存在（用资源管理器确认）

- [ ] **Step 6: 提交脚本（不提交 docx 到 backend）**

```bash
git add scripts/make_s4_1_exam_paper.py backend/tests/test_make_exam_paper.py \
  backend/app/ai/prompts/question_extract_v1.md
git commit -m "test(s4-1): 自编 20 题验收卷生成脚本与结构测试"
```

---

### Task 13: 真实验收 + 文档同步

**Files:**
- Modify: `docs/API.md`、`docs/PROGRESS.md`、`docs/DECISIONS.md`、`docs/AGENTS.md`、`docs/AI协作开发实施计划.md`、`docs/spec/s4-1-question-bank.md`

- [ ] **Step 1: 起依赖与两个进程**

```powershell
cd deploy
docker compose up -d postgres redis minio
cd ..\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# 另开一个终端
cd backend
..\.venv\Scripts\python.exe -m arq app.tasks.worker.WorkerSettings
# 再开一个终端
cd web
npm run dev
```

- [ ] **Step 2: 逐条跑验收（**数字必须来自实测，禁止编造**）**

| # | 操作 | 通过标准 | 实测记录 |
|---|---|---|---|
| 1 | student 登录 → `/questions/import` → 选学科 → 上传 `高中数学试卷-高二期末综合卷（20题）.docx` | 任务成功，`detected_count=20` | |
| 2 | 记录 `created / duplicated / failed_items / elapsed_ms` | `created≥20`，`failed_items` 为空或如实记录 | |
| 3 | 打开审题页逐题核对（公式渲染、答案与原卷一致） | “可直接用”≥80% | ___ / 20 |
| 4 | 抽 5 题看 `kps[]` | 每题至少 1 个知识点且合理 | ___ / 5 |
| 5 | 再导入同一份卷子 | `created=0, duplicated=20` | |
| 6 | 手动删 1 题后重新导入 | `created=1` | |
| 7 | 编辑 1 题题干/答案 → 刷新 | 修改保留，`stem_hash` 与向量已重算（复查详情 `kps` 有变化） | |
| 8 | 合并 2 题、拆分 1 题 | 返回新题，列表刷新后原题消失 | |
| 9 | 删除 1 道无引用题 | 204，`question_kps` 无残留（`SELECT count(*) FROM question_kps WHERE question_id=...`） | |
| 10 | 传图片 `.png` 到导入接口 | 400/40000，提示仅支持 PDF/DOCX | |
| 11 | 传扫描版 PDF（无文本层） | 任务 failed，`error` 含“扫描” | |

把上表实测值填进 `docs/PROGRESS.md` 的 S4-1 条目。

- [ ] **Step 3: `docs/API.md` 新增 §5.5**

在 `## 6. 错题本` 之前插入 `## 5.5 题库与试卷切题（S4-1 定稿）`，按 spec §6 的 9 个接口逐条写：路径、权限、同步/异步、入参、出参、错误码。同时把 §3 `POST /api/v1/files` 的 `parse` 参数说明改为：

```markdown
`parse`：是否入队文档解析。`true`（默认）走 `parse.document`；`false` 表示只存原件——允许图片（编辑器插图）与 PDF/DOCX（试卷原件，切题由 `question.extract` 负责）。
```

- [ ] **Step 4: `docs/PROGRESS.md`**

- 状态表里把 S4-1 标 `[x]`，贴上 Step 2 的实测数字（识别题数、created/duplicated/耗时、人工核对三档计数、知识点抽查结果）。
- 变更日志补一条：`questions/question_kps` 表、切题链路、9 个接口、前端两页。
- 遗留问题补：`ai/ocr` 多模态待 S4-2；审题页知识点选择器待 S4-9 换成树形多选；`m1-framework-done` 仍缺 20 条真实笔记。

- [ ] **Step 5: `docs/DECISIONS.md`**

新增三条（编号接现有序列）：

1. **题库为公共语料**：`questions` 不带 `user_id`，读对所有登录用户开放，写限创建者/teacher/admin。理由：题目本身不含个人信息，重复存储没有意义；数据隔离清单（S2-3）只覆盖学生私有数据。
2. **`questions.stem_hash` 契约变更**：原 SCHEMA §5.1 缺判重键，S4-1 增补 `stem_hash` + `UNIQUE(subject_id, stem_hash)`；判重两道闸（哈希 → 余弦 0.92）。
3. **切题任务允许部分成功**：单题 3 次重试仍失败只进 `result.failed_items`，任务仍 `succeeded`。理由：整卷白切比缺 1 题代价大；缺口通过 `failed_items` + 前端黄条显式暴露。

- [ ] **Step 6: `docs/AGENTS.md`**

- §9.2 增补一条「题库与切题（S4-1）」：`services/question_service.py` 是唯一入口；判重两道闸不可拆；对齐复用 S2-10 公式、阈值 0.75、每题最多 3 个；切题任务不自行 commit、单题失败进 `failed_items`；删除/合并/拆分硬删且 `mistakes` 引用检查用 `has_table` 守卫（S4-2 自动生效）；`parse=false` 仅放行图片与 PDF/DOCX。
- §9.6 增补锚点「题库样例」：`models/question.py` + `models/question_kp.py` + `services/question_service.py` + `api/v1/questions.py` + `ai/extract/{splitter,question_extractor}.py` + `tasks/question_extract.py`（纯函数切题 → 单题结构化 → 两道闸判重 → 0.75 对齐；任务不提交）。

- [ ] **Step 7: 实施计划勾选**

`docs/AI协作开发实施计划.md` 第 14 章把 S4-1 勾选为完成，备注实测数字。

- [ ] **Step 8: 回填 spec 的 3 处偏差**

在 `docs/spec/s4-1-question-bank.md` 里改：

1. §4.2 步骤 4「卷头清理」→ 改为「首个题号之前整段丢弃」；步骤 7「卷尾清理」→ 改为「页码/答题卡行全局剔除」。
2. §6 `POST /questions/merge` 的错误码：`400/40000` → `422/42200`（`InvalidParamError` 的既定 HTTP 状态）。
3. §8 测试计划里「单题模式返回 2 条 → 截断为 1 并记 warning」→ 改为「触发重试」（与 §5.1 一致）。

- [ ] **Step 9: 全量回归**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
cd ..\web
npm run test
npm run build
```
Expected: 后端全绿（新增约 70 条）、前端全绿（约 120 条）、构建成功

- [ ] **Step 10: 最终提交**

```bash
git add docs web backend scripts
git commit -m "docs(s4-1): 题库接口定稿、进度与决策同步，实测验收记录"
```

---

## 与 spec 的偏差汇总（执行完请按 Task 13 Step 8 回填）

| # | spec 原文 | 计划做法 | 原因 |
|---|---|---|---|
| 1 | §4.2 用卷头关键词白名单逐行删除 | 首个题号之前整段丢弃 + 页码行全局剔除 | 更彻底且零误删风险（白名单可能误删正文里的"某中学"） |
| 2 | §6 合并跨学科 → `400/40000` | `422/42200` | 仓库既有 `InvalidParamError` 就是 422，改常量会波及其他接口 |
| 3 | §8 单题模式多返回 → 截断并 warning | 触发重试，仍不为 1 才算失败 | 与 §5.1「视为失败并重试」一致，§8 那条是笔误 |

## 完成后的自检清单

- [ ] `questions` / `question_kps` 两表在真库建好，`alembic downgrade -1` 能干净回退
- [ ] 20 题验收卷真实跑通，`PROGRESS.md` 里的每个数字都能在任务 `result` 或数据库里复现
- [ ] package 里没有新增依赖（`git diff requirements.txt package.json` 为空）
- [ ] 所有新测试都不触网（`pytest -q` 在断网下也能过）
- [ ] `docs/API.md` §5.5 与实际 `response_model` 一致
- [ ] 提交信息符合 Conventional Commits 且带 `(s4-1)`
- [ ] 没有把自编卷说成真题（文档、论文、口头汇报口径一致）