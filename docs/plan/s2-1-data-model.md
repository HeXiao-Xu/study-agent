# S2-1 数据模型与迁移（第一批）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `users / user_relations / subjects / knowledge_points / knowledge_edges` 五张表交付 ORM 模型与可正反执行的 Alembic 迁移 `0002_s2_1`。

**Architecture:** 一个模型文件对应一张表，枚举值集中在 `app/models/enums.py` 并由 `in_check()` 生成 CHECK 文本；迁移文件是独立快照（不 import 应用常量），upgrade 按被引用顺序建表，downgrade 逆序删表。测试只断言 SQLAlchemy metadata（不连库），真实 DDL 由 alembic + psql 验收命令覆盖。

**Tech Stack:** Python 3.11 + SQLAlchemy 2.1.5（Declarative 2.0 风格）+ Alembic 1.20.0 + pgvector 0.5.1 + PostgreSQL 16。

**Spec:** `docs/spec/s2-1-data-model.md`（本计划的每个决策都能在 spec §4/§5/§6 找到出处）

## Global Constraints

- 主键统一 `BIGINT GENERATED ALWAYS AS IDENTITY`（`sa.Identity(always=True)`），与 `note_chunks` 一致。
- 向量维度固定 `VECTOR(1024)`；HNSW 参数固定 `vector_cosine_ops, m=16, ef_construction=64`。
- 枚举一律 `TEXT + CHECK`，**禁止** `postgresql.ENUM`；值唯一来源 `app/models/enums.py`。
- 时间列 `TIMESTAMPTZ NOT NULL DEFAULT now()`；`updated_at` 额外带 SQLAlchemy `onupdate=func.now()`。
- 约束命名：`uq_<表>_<列...>`、`ck_<表>_<规则>`、`ix_<表>_<列>`、`fk_<表>_<列>`。
- 外键默认 `NO ACTION`，不写 `ondelete`。
- 禁止修改已提交的 `0001_create_note_chunks.py`；禁止新增依赖；禁止建 API/种子数据/`note_chunks` 外键。
- 测试数据用「测试用户_1」式明显假数据；不写真实姓名/学校。
- 所有命令在 Windows Git Bash 下执行，仓库根 `E:\BiShe-AIStudy\study-agent`。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/models/enums.py` | 3 个 StrEnum + `in_check()` | 新建 |
| `backend/app/models/user.py` | `users` 表 | 新建 |
| `backend/app/models/user_relation.py` | `user_relations` 表 | 新建 |
| `backend/app/models/subject.py` | `subjects` 表 | 新建 |
| `backend/app/models/knowledge_point.py` | `knowledge_points` 表 | 新建 |
| `backend/app/models/knowledge_edge.py` | `knowledge_edges` 表 | 新建 |
| `backend/app/models/__init__.py` | 注册全部模型供 Alembic 发现 | 修改 |
| `backend/alembic/versions/0002_s2_1_business_tables.py` | 迁移 | 新建 |
| `backend/tests/test_models_s2_1.py` | 枚举 + 5 表契约测试 | 新建 |
| `scripts/smoke.py` | `REQUIRED_TABLES` 填 5 张表 | 修改 |
| `docs/{SCHEMA,AGENTS,DECISIONS,PROGRESS}.md` | 契约与进度同步 | 修改 |

---

### Task 1: 枚举常量与 `in_check()`

**Files:**
- Create: `backend/app/models/enums.py`
- Test: `backend/tests/test_models_s2_1.py`

**Interfaces:**
- Produces: `UserRole`（`student/teacher/parent/admin`）、`EdgeRelation`（`prerequisite/related/confusable/contains`）、`EdgeSource`（`ai/manual`）、`in_check(column: str, values: Iterable[str]) -> str`。Task 2 的模型与 Task 3 的迁移都依赖这些值。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_models_s2_1.py`，先只放枚举测试：

```python
"""S2-1 模型契约测试：枚举值、5 张表的字段/约束/索引与 SCHEMA + spec §4 一致。"""
from __future__ import annotations

from app.models.enums import EdgeRelation, EdgeSource, UserRole, in_check


def test_user_role_values_match_schema() -> None:
    assert {r.value for r in UserRole} == {"student", "teacher", "parent", "admin"}


def test_edge_relation_values_match_schema() -> None:
    assert {r.value for r in EdgeRelation} == {
        "prerequisite",
        "related",
        "confusable",
        "contains",
    }


def test_edge_source_values_match_schema() -> None:
    assert {r.value for r in EdgeSource} == {"ai", "manual"}


def test_in_check_renders_sql_in_list() -> None:
    assert in_check("role", UserRole) == (
        "role IN ('student', 'teacher', 'parent', 'admin')"
    )
    assert in_check("source", EdgeSource) == "source IN ('ai', 'manual')"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_models_s2_1.py -q`
Expected: `ModuleNotFoundError: No module named 'app.models.enums'`

- [ ] **Step 3: 实现 `enums.py`**

```python
"""S2-1 枚举常量：值集的唯一来源（SCHEMA §10；CHECK 文本由 in_check 生成）。

为什么不用 PostgreSQL ENUM：改值集需要 ALTER TYPE，加值不可回滚，downgrade
就变成不可执行；TEXT + CHECK 可以用 DROP/ADD CONSTRAINT 对称回退。
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"


class EdgeRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    CONFUSABLE = "confusable"
    CONTAINS = "contains"


class EdgeSource(StrEnum):
    AI = "ai"
    MANUAL = "manual"


def in_check(column: str, values: Iterable[str]) -> str:
    """渲染 `<column> IN ('a', 'b')`；StrEnum 成员经 f-string 取到值本身。"""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_models_s2_1.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/enums.py backend/tests/test_models_s2_1.py
git commit -m "feat(s2-1): 枚举常量与 CHECK 文本生成器"
```

---

### Task 2: 五个 ORM 模型

**Files:**
- Create: `backend/app/models/user.py`、`user_relation.py`、`subject.py`、`knowledge_point.py`、`knowledge_edge.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_s2_1.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `UserRole / EdgeRelation / EdgeSource / in_check`。
- Produces: `User / UserRelation / Subject / KnowledgePoint / KnowledgeEdge` 五个类，均由 `app.models.__init__` 导出；表名 `users / user_relations / subjects / knowledge_points / knowledge_edges`。

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_models_s2_1.py` 顶部 import 改为：

```python
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

import app.models as models_pkg
from app.models import (
    Base,
    KnowledgeEdge,
    KnowledgePoint,
    Subject,
    User,
    UserRelation,
)
from app.models.enums import EdgeRelation, EdgeSource, UserRole, in_check
```

在文件末尾追加：

```python
_MODELS = (User, UserRelation, Subject, KnowledgePoint, KnowledgeEdge)

_EXPECTED_COLUMNS: dict[str, set[str]] = {
    "users": {
        "id", "username", "password_hash", "nickname", "grade", "role",
        "created_at", "updated_at",
    },
    "user_relations": {"id", "teacher_id", "student_id", "created_at", "updated_at"},
    "subjects": {"id", "name", "code", "stage", "config_json", "created_at", "updated_at"},
    "knowledge_points": {
        "id", "subject_id", "parent_id", "name", "code", "level", "description",
        "exam_weight", "embedding", "order_no", "created_at", "updated_at",
    },
    "knowledge_edges": {
        "id", "src_kp_id", "dst_kp_id", "relation", "weight", "source",
        "created_at", "updated_at",
    },
}

_NULLABLE: dict[str, set[str]] = {
    "users": {"grade"},
    "user_relations": set(),
    "subjects": {"config_json"},
    "knowledge_points": {"parent_id", "description", "exam_weight", "embedding"},
    "knowledge_edges": {"weight"},
}


def _checks(model: type[Base]) -> dict[str, str]:
    return {
        c.name: str(c.sqltext)
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint)
    }


def _uniques(model: type[Base]) -> dict[str, tuple[str, ...]]:
    return {
        c.name: tuple(col.name for col in c.columns)
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }


def _indexes(model: type[Base]) -> dict[str, object]:
    return {i.name: i for i in model.__table__.indexes}


def _foreign_keys(model: type[Base]) -> dict[str, str]:
    return {fk.parent.name: fk.target_fullname for fk in model.__table__.foreign_keys}


def test_table_names_and_columns() -> None:
    for model in _MODELS:
        assert model.__tablename__ in _EXPECTED_COLUMNS
        assert set(model.__table__.columns.keys()) == _EXPECTED_COLUMNS[model.__tablename__]


def test_nullable_flags() -> None:
    for model in _MODELS:
        table = _EXPECTED_COLUMNS[model.__tablename__] - _NULLABLE[model.__tablename__]
        for name in table:
            assert model.__table__.columns[name].nullable is False, (model.__tablename__, name)
        for name in _NULLABLE[model.__tablename__]:
            assert model.__table__.columns[name].nullable is True, (model.__tablename__, name)


def test_primary_keys_are_bigint_identity() -> None:
    for model in _MODELS:
        pk = model.__table__.primary_key.columns["id"]
        assert isinstance(pk.type, BigInteger)
        assert isinstance(pk.identity, Identity)
        assert pk.identity.always is True


def test_timestamp_columns_default_and_onupdate() -> None:
    for model in _MODELS:
        created = model.__table__.columns["created_at"]
        updated = model.__table__.columns["updated_at"]
        assert isinstance(created.type, DateTime) and created.type.timezone is True
        assert str(created.server_default.arg) == "now()"
        assert isinstance(updated.type, DateTime) and updated.type.timezone is True
        assert str(updated.server_default.arg) == "now()"
        assert str(updated.onupdate.arg) == "now()"


def test_users_constraints() -> None:
    assert _uniques(User) == {"uq_users_username": ("username",)}
    assert _checks(User)["ck_users_role"] == in_check("role", UserRole)


def test_user_relations_constraints() -> None:
    assert _uniques(UserRelation) == {
        "uq_user_relations_teacher_student": ("teacher_id", "student_id")
    }
    assert "ck_user_relations_not_self" in _checks(UserRelation)
    assert _foreign_keys(UserRelation) == {
        "teacher_id": "users.id",
        "student_id": "users.id",
    }
    assert tuple(_indexes(UserRelation)["ix_user_relations_student_id"].columns.keys()) == (
        "student_id",
    )


def test_subjects_constraints() -> None:
    assert _uniques(Subject) == {"uq_subjects_code": ("code",)}
    stage = Subject.__table__.columns["stage"]
    assert str(stage.server_default.arg) == "'高中'"
    assert isinstance(Subject.__table__.columns["config_json"].type, JSONB)


def test_knowledge_points_constraints() -> None:
    assert _uniques(KnowledgePoint) == {
        "uq_knowledge_points_subject_code": ("subject_id", "code")
    }
    assert _checks(KnowledgePoint)["ck_knowledge_points_level"] == (
        "level >= 1 AND level <= 4"
    )
    assert _foreign_keys(KnowledgePoint) == {
        "subject_id": "subjects.id",
        "parent_id": "knowledge_points.id",
    }
    cols = KnowledgePoint.__table__.columns
    assert isinstance(cols["level"].type, SmallInteger)
    assert isinstance(cols["embedding"].type, Vector)
    assert cols["embedding"].type.dim == 1024
    assert isinstance(cols["exam_weight"].type, Numeric)
    assert isinstance(cols["order_no"].type, Integer)
    assert str(cols["order_no"].server_default.arg) == "0"


def test_knowledge_points_indexes() -> None:
    indexes = _indexes(KnowledgePoint)
    assert tuple(indexes["ix_knowledge_points_subject_id"].columns.keys()) == ("subject_id",)
    assert tuple(indexes["ix_knowledge_points_parent_id"].columns.keys()) == ("parent_id",)
    hnsw = indexes["ix_knowledge_points_embedding_hnsw"].dialect_options["postgresql"]
    assert hnsw["using"] == "hnsw"
    assert hnsw["ops"] == {"embedding": "vector_cosine_ops"}
    assert hnsw["with"] == {"m": 16, "ef_construction": 64}


def test_knowledge_edges_constraints() -> None:
    assert _uniques(KnowledgeEdge) == {
        "uq_knowledge_edges_src_dst_relation": ("src_kp_id", "dst_kp_id", "relation")
    }
    checks = _checks(KnowledgeEdge)
    assert checks["ck_knowledge_edges_relation"] == in_check("relation", EdgeRelation)
    assert checks["ck_knowledge_edges_source"] == in_check("source", EdgeSource)
    assert "ck_knowledge_edges_not_self" in checks
    assert _foreign_keys(KnowledgeEdge) == {
        "src_kp_id": "knowledge_points.id",
        "dst_kp_id": "knowledge_points.id",
    }
    assert tuple(_indexes(KnowledgeEdge)["ix_knowledge_edges_dst_kp_id"].columns.keys()) == (
        "dst_kp_id",
    )
    assert isinstance(KnowledgeEdge.__table__.columns["weight"].type, Numeric)


def test_models_registered_in_package() -> None:
    for name in (
        "User",
        "UserRelation",
        "Subject",
        "KnowledgePoint",
        "KnowledgeEdge",
    ):
        assert name in models_pkg.__all__
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_models_s2_1.py -q`
Expected: `ImportError: cannot import name 'KnowledgeEdge' from 'app.models'`

- [ ] **Step 3: 写五个模型**

`backend/app/models/user.py`：

```python
"""users ORM 模型：SCHEMA §2.1 + 本卡补的 updated_at（spec §4.1）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import UserRole, in_check


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint(in_check("role", UserRole), name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    nickname: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'student'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`backend/app/models/user_relation.py`：

```python
"""user_relations ORM 模型：老师/家长绑定学生（SCHEMA §2.2，spec §4.2）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRelation(Base):
    __tablename__ = "user_relations"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "student_id", name="uq_user_relations_teacher_student"
        ),
        CheckConstraint("teacher_id <> student_id", name="ck_user_relations_not_self"),
        Index("ix_user_relations_student_id", "student_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_user_relations_teacher_id"),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_user_relations_student_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`backend/app/models/subject.py`：

```python
"""subjects ORM 模型：学科字典（SCHEMA §2.3，spec §4.3）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("code", name="uq_subjects_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'高中'")
    )
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`backend/app/models/knowledge_point.py`：

```python
"""knowledge_points ORM 模型：知识点树（SCHEMA §3.1，spec §4.4）。

embedding 本卡只建列不填（S2-10 知识点对齐时写入）。
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
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.db import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("subject_id", "code", name="uq_knowledge_points_subject_code"),
        CheckConstraint("level >= 1 AND level <= 4", name="ck_knowledge_points_level"),
        Index("ix_knowledge_points_subject_id", "subject_id"),
        Index("ix_knowledge_points_parent_id", "parent_id"),
        Index(
            "ix_knowledge_points_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("subjects.id", name="fk_knowledge_points_subject_id"),
        nullable=False,
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_points_parent_id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_weight: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    order_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`backend/app/models/knowledge_edge.py`：

```python
"""knowledge_edges ORM 模型：知识点关系边（SCHEMA §3.2，spec §4.5）。"""
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
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import EdgeRelation, EdgeSource, in_check


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint(
            "src_kp_id", "dst_kp_id", "relation", name="uq_knowledge_edges_src_dst_relation"
        ),
        CheckConstraint(
            in_check("relation", EdgeRelation), name="ck_knowledge_edges_relation"
        ),
        CheckConstraint(in_check("source", EdgeSource), name="ck_knowledge_edges_source"),
        CheckConstraint("src_kp_id <> dst_kp_id", name="ck_knowledge_edges_not_self"),
        Index("ix_knowledge_edges_dst_kp_id", "dst_kp_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    src_kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_edges_src_kp_id"),
        nullable=False,
    )
    dst_kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_knowledge_edges_dst_kp_id"),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

`backend/app/models/__init__.py` 全量替换：

```python
"""模型包：显式导入供 Alembic target_metadata 发现。"""
from app.core.db import Base
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.note_chunk import NoteChunk
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation

__all__ = [
    "Base",
    "KnowledgeEdge",
    "KnowledgePoint",
    "NoteChunk",
    "Subject",
    "User",
    "UserRelation",
]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_models_s2_1.py -q`
Expected: `15 passed`

若 `test_users_constraints` 报 CHECK 文本不一致，检查 `in_check` 的引号与逗号空格（必须 `'a', 'b'` 形式），不要放宽断言。

- [ ] **Step 5: 回归旧模型测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_note_chunk_model.py -q`
Expected: `5 passed`（`note_chunks` 未被改动）

- [ ] **Step 6: 提交**

```bash
git add backend/app/models backend/tests/test_models_s2_1.py
git commit -m "feat(s2-1): 五张业务表 ORM 模型与契约测试"
```

---

### Task 3: Alembic 迁移 `0002_s2_1` 与正反执行

**Files:**
- Create: `backend/alembic/versions/0002_s2_1_business_tables.py`

**Interfaces:**
- Consumes: 无（迁移是独立 DDL 快照，硬编码枚举值，不 import 应用常量）。
- Produces: revision `0002_s2_1`，`down_revision="0001_s1_3"`；`alembic upgrade head` 后 5 表及其索引/约束存在。

- [ ] **Step 1: 写迁移文件**

```python
"""S2-1 第一批业务表：users / user_relations / subjects / knowledge_points / knowledge_edges

Revision ID: 0002_s2_1
Revises: 0001_s1_3
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0002_s2_1"
down_revision = "0001_s1_3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("grade", sa.Text(), nullable=True),
        sa.Column(
            "role", sa.Text(), server_default=sa.text("'student'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(
            "role IN ('student', 'teacher', 'parent', 'admin')", name="ck_users_role"
        ),
    )

    op.create_table(
        "user_relations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["users.id"], name="fk_user_relations_teacher_id"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"], name="fk_user_relations_student_id"
        ),
        sa.UniqueConstraint(
            "teacher_id", "student_id", name="uq_user_relations_teacher_student"
        ),
        sa.CheckConstraint(
            "teacher_id <> student_id", name="ck_user_relations_not_self"
        ),
    )
    op.create_index(
        "ix_user_relations_student_id", "user_relations", ["student_id"]
    )

    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column(
            "stage", sa.Text(), server_default=sa.text("'高中'"), nullable=False
        ),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_subjects_code"),
    )

    op.create_table(
        "knowledge_points",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("exam_weight", sa.Numeric(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("order_no", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_knowledge_points_subject_id"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["knowledge_points.id"],
            name="fk_knowledge_points_parent_id",
        ),
        sa.UniqueConstraint(
            "subject_id", "code", name="uq_knowledge_points_subject_code"
        ),
        sa.CheckConstraint(
            "level >= 1 AND level <= 4", name="ck_knowledge_points_level"
        ),
    )
    op.create_index("ix_knowledge_points_subject_id", "knowledge_points", ["subject_id"])
    op.create_index("ix_knowledge_points_parent_id", "knowledge_points", ["parent_id"])
    op.create_index(
        "ix_knowledge_points_embedding_hnsw",
        "knowledge_points",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("src_kp_id", sa.BigInteger(), nullable=False),
        sa.Column("dst_kp_id", sa.BigInteger(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["src_kp_id"], ["knowledge_points.id"], name="fk_knowledge_edges_src_kp_id"
        ),
        sa.ForeignKeyConstraint(
            ["dst_kp_id"], ["knowledge_points.id"], name="fk_knowledge_edges_dst_kp_id"
        ),
        sa.UniqueConstraint(
            "src_kp_id",
            "dst_kp_id",
            "relation",
            name="uq_knowledge_edges_src_dst_relation",
        ),
        sa.CheckConstraint(
            "relation IN ('prerequisite', 'related', 'confusable', 'contains')",
            name="ck_knowledge_edges_relation",
        ),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name="ck_knowledge_edges_source"
        ),
        sa.CheckConstraint("src_kp_id <> dst_kp_id", name="ck_knowledge_edges_not_self"),
    )
    op.create_index("ix_knowledge_edges_dst_kp_id", "knowledge_edges", ["dst_kp_id"])


def downgrade() -> None:
    op.drop_table("knowledge_edges")
    op.drop_table("knowledge_points")
    op.drop_table("subjects")
    op.drop_table("user_relations")
    op.drop_table("users")
```

- [ ] **Step 2: 前滚**

Run:
```bash
cd backend
../.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: `Running upgrade 0001_s1_3 -> 0002_s2_1`

- [ ] **Step 3: 核对表结构**

Run:
```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "\d users"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d user_relations"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d subjects"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d knowledge_points"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d knowledge_edges"
```
Expected: 每张表字段齐全；`knowledge_points` 出现 `embedding | vector(1024)`、`ix_knowledge_points_embedding_hnsw`（hnsw）、`fk_knowledge_points_parent_id`、`ck_knowledge_points_level`；`users.role` 有默认 `'student'::text` 与 `ck_users_role`。

- [ ] **Step 4: 回退**

Run:
```bash
cd backend
../.venv/Scripts/python.exe -m alembic downgrade -1
docker exec study-agent-postgres psql -U study -d study_agent -c "\dt"
```
Expected: 回到 `0001_s1_3`；5 张新表消失，`note_chunks` 与 `alembic_version` 仍在。

- [ ] **Step 5: 再次前滚**

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head`
Expected: 再次 `0001_s1_3 -> 0002_s2_1`，无报错（证明迁移可重复执行于同一库）。

- [ ] **Step 6: 提交**

```bash
git add backend/alembic/versions/0002_s2_1_business_tables.py
git commit -m "feat(s2-1): 第一批业务表迁移与索引"
```

---

### Task 4: 约束负向验证 + smoke 维护

**Files:**
- Modify: `scripts/smoke.py:42`

**Interfaces:**
- Produces: `REQUIRED_TABLES` 含 5 张表，`scripts/smoke.py` 第 7 项检查变成「核心表 5/5 在位」。

- [ ] **Step 1: psql 事务内逐条制造违规并确认被拒绝**

Run（每条单独执行，观察报错后 `ROLLBACK`；`BEGIN` 保证不污染库）：
```bash
docker exec -i study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO users(username, password_hash, nickname, role)
VALUES ('测试用户_1', 'x', '测试用户_1', 'hacker');
ROLLBACK;
SQL
```
Expected: `ERROR: new row for relation "users" violates check constraint "ck_users_role"`

```bash
docker exec -i study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO users(username, password_hash, nickname) VALUES ('测试用户_2', 'x', '测试用户_2');
INSERT INTO users(username, password_hash, nickname) VALUES ('测试用户_2', 'x', '测试用户_2');
ROLLBACK;
SQL
```
Expected: 第二条报 `duplicate key value violates unique constraint "uq_users_username"`

```bash
docker exec -i study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO subjects(name, code) VALUES ('测试学科', 'test_math');
INSERT INTO knowledge_points(subject_id, name, code, level)
  SELECT id, '测试知识点_1', 'TEST-001', 1 FROM subjects WHERE code = 'test_math';
INSERT INTO knowledge_points(subject_id, name, code, level)
  SELECT id, '测试知识点_2', 'TEST-002', 1 FROM subjects WHERE code = 'test_math';
INSERT INTO knowledge_edges(src_kp_id, dst_kp_id, relation, source)
  SELECT a.id, a.id, 'related', 'manual' FROM knowledge_points a WHERE a.code = 'TEST-001';
ROLLBACK;
SQL
```
Expected: 自环边报 `violates check constraint "ck_knowledge_edges_not_self"`

```bash
docker exec -i study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO subjects(name, code) VALUES ('测试学科', 'test_math');
INSERT INTO knowledge_points(subject_id, name, code, level)
  SELECT id, '测试知识点_1', 'TEST-001', 1 FROM subjects WHERE code = 'test_math';
DELETE FROM subjects WHERE code = 'test_math';
ROLLBACK;
SQL
```
Expected: `violates foreign key constraint "fk_knowledge_points_subject_id"`

```bash
docker exec -i study-agent-postgres psql -U study -d study_agent <<'SQL'
BEGIN;
INSERT INTO subjects(name, code) VALUES ('测试学科', 'test_math');
INSERT INTO knowledge_points(subject_id, name, code, level)
  SELECT id, '测试知识点_1', 'TEST-001', 5 FROM subjects WHERE code = 'test_math';
ROLLBACK;
SQL
```
Expected: `violates check constraint "ck_knowledge_points_level"`

- [ ] **Step 2: 确认库内无残留**

Run:
```bash
docker exec study-agent-postgres psql -U study -d study_agent \
  -c "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM subjects) AS subjects, (SELECT count(*) FROM knowledge_points) AS kp, (SELECT count(*) FROM knowledge_edges) AS edges;"
```
Expected: `0 | 0 | 0 | 0`

- [ ] **Step 3: 更新 `scripts/smoke.py` 的 `REQUIRED_TABLES`**

把第 42 行 `REQUIRED_TABLES: list[str] = []` 改为：

```python
REQUIRED_TABLES: list[str] = [
    "users",
    "user_relations",
    "subjects",
    "knowledge_points",
    "knowledge_edges",
    "note_chunks",
]
```

- [ ] **Step 4: 跑冒烟**

Run: `cd .. && .venv/Scripts/python.exe scripts/smoke.py`
Expected: 第 7 项 `PASS 核心表 6/6 在位`；整体退出码 0（前端 dev 未启动记 SKIP）。

- [ ] **Step 5: 提交**

```bash
git add scripts/smoke.py
git commit -m "chore(s2-1): smoke 核心表清单纳入第一批业务表"
```

---

### Task 5: 文档同步与全量回归

**Files:**
- Modify: `docs/SCHEMA.md`、`docs/AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`

- [ ] **Step 1: 更新 `docs/SCHEMA.md`**

按 spec §10 逐条改：

1. §0「数组字段」行：由 `TEXT[] / BIGINT[]（⚠ TEXT[] vs JSONB 在 S2-1 定）` 改为 `TEXT[] / BIGINT[]（✅ S2-1 定稿：原生数组；标签检索用 GIN，不转 JSONB）`。
2. §2.1 users 表末追加一行：`| updated_at | TIMESTAMPTZ | 否 | now() | 应用层 onupdate 维护（S2-1 补） | — |`。
3. §2.2 user_relations 表追加 `created_at`/`updated_at` 两行；索引列补 `idx(student_id) ✅`；表下加一行注记：`> S2-1 新增 ck_user_relations_not_self：禁止 teacher_id = student_id。`
4. §2.3 subjects 追加 `created_at`/`updated_at` 两行。
5. §3.1 knowledge_points 追加 `created_at`/`updated_at`；`level` 索引列补 `CHECK 1..4 ✅`；表下注记 embedding HNSW 已随 S2-1 建立、本卡不填数据。
6. §3.2 knowledge_edges 追加 `created_at`/`updated_at`；表下注记 `ck_knowledge_edges_not_self`。
7. §4.3 note_chunks 表下注记改为：`> S1-3 建表时 notes/users/files 尚未建；外键统一延后到 S2-5 建 notes/files 时补（S2-1 复核后调整，83 行存量数据 user_id=1 无对应用户）。`
8. §10.1 行改为：`| 10.1 | users.role | student / teacher / parent / admin ✅（S2-1 以 CHECK 落库定稿） | SCHEMA §2.1 + user_relations 与 /admin/usage 推断 |`

- [ ] **Step 2: 更新 `docs/AGENTS.md`**

1. §4「编码规范」末尾加一条：`- 枚举一律 TEXT + CHECK（不用 PostgreSQL ENUM）：值集常量放 app/models/enums.py，CHECK 文本由 in_check() 生成（D-021）`。
2. §9.6「一致性锚点」在「后端路由样例」之前加一条：`- 后端模型样例：backend/app/models/user.py（BIGINT IDENTITY 主键、TEXT+CHECK 枚举、created_at/updated_at + onupdate、uq_/ck_/ix_/fk_ 命名；枚举常量见同目录 enums.py）`。

- [ ] **Step 3: 更新 `docs/DECISIONS.md`**

在 D-020 之后追加（内容照 spec §2.3 写，含 4 条决策与代价）：

```markdown
## D-021 S2-1 数据模型与迁移实现决策（spec §2/§3/§5 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-1-data-model.md）
- 决策 1（表数 7 → 5）：任务卡的 roles/user_roles 在 SCHEMA 中不存在；契约按 users.role 单列枚举，API.md 与 S2-2/S2-3 任务卡亦按单角色设计。按 AGENTS §8 以 SCHEMA 为准，不建这两张表。
- 决策 2（认证路线）：fastapi-users 的 SQLAlchemy 适配器 async 专用（AsyncSession + asyncpg），且要求 email/hashed_password 等字段，与同步 psycopg 栈和 SCHEMA 冲突；S2-2 改用 FastAPI 官方安全示例（pwdlib/bcrypt + PyJWT）。
- 决策 3（枚举 TEXT + CHECK）：PG ENUM 加值不可回滚，downgrade 会失效；TEXT + CHECK 可对称回退，且与 note_chunks.chunk_type 风格一致。代价是失去 PG enum 的类型安全，由 Pydantic + CHECK 双层兜底。
- 决策 4（note_chunks 外键延后 S2-5）：存量 83 行 user_id=1 无 users 行，现在加 FK 必失败；S2-5 建 notes/files 时统一补。
- 验证：pytest 全绿；alembic upgrade/downgrade 往返通过；5 条负向约束实测被拒绝（详见 PROGRESS 2026-10-26）。
```

- [ ] **Step 4: 更新 `docs/PROGRESS.md`**

1. 「当前状态」：阶段改为「阶段 2（基础框架，M1）」；最近完成改为 S2-1；下一步改为 S2-2 认证。
2. 任务清单 `S2-1` 打 `[x]`。
3. 「遗留问题」#1 的状态改为「S2-1 已逐条结案（spec §3）」。
4. 变更日志新增 `### 2026-10-26（S2-1）` 段，写清交付、实测证据（pytest 数字、5 表、负向验证结果）、已知事项与文档同步。

- [ ] **Step 5: 全量回归**

Run:
```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```
Expected: 现有 191 + 新增 15 = `206 passed`（若数字不同，以实际为准并如实记录，不允许改测试凑数）。

- [ ] **Step 6: 提交**

```bash
git add docs/
git commit -m "docs(s2-1): 数据模型契约、决策与进度同步"
```

- [ ] **Step 7: 核对工作区**

Run: `git status --short && git log --oneline -6`
Expected: 工作区干净（`.env`、DOCX 样张等本就 ignored）；最近 5 个提交为 S2-1 的 5 个 commit。

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §2.1 做（5 表/枚举/模型/迁移/测试/文档/smoke） | Task 1–5 |
| §2.3 偏离 4 条 | Task 1（枚举）、Task 3（迁移）、Task 5（DECISIONS/PROGRESS） |
| §3 契约复核（时间列/索引/数组/role） | Task 2（模型）、Task 5（SCHEMA） |
| §4 逐表字段/可空性/约束 | Task 2 代码 + `test_nullable_flags` 等断言 |
| §5 枚举与 TEXT+CHECK | Task 1 + `test_*_constraints` |
| §6.2 迁移顺序/降级 | Task 3 Step 2–5 |
| §6.3 时间列口径 | `test_timestamp_columns_default_and_onupdate` |
| §7 错误处理（9 种场景） | Task 4 Step 1 的 5 条负向验证 + 唯一约束由模型断言覆盖 |
| §8 测试 8 条 | `test_models_s2_1.py` 全文件 |
| §9 验收命令 | Task 3/4/5 的 Run 块 |
| §10 文档同步 | Task 5 |
| §11 风险 | 迁移独立快照、不指定 id、NO ACTION |

**2. Placeholder scan**：无 TBD/TODO；每个代码步骤给出完整文件内容；文档步骤给出精确改动点与替换文本。

**3. Type consistency**：`in_check(column, values)` 在 Task 1 定义、Task 2 使用；模型类名 `User/UserRelation/Subject/KnowledgePoint/KnowledgeEdge` 在 Task 2、测试、Task 5 锚点中一致；约束名在模型、迁移、验收命令中逐字一致（`ck_users_role`、`uq_knowledge_points_subject_code`、`ix_knowledge_points_embedding_hnsw` 等）。

## 执行记录

（2026-10-26 实施完成）

- **Task 1**：`enums.py` + 4 条枚举测试 → `4 passed`；commit `eb75348`。
- **Task 2**：5 个模型 + `__init__` 注册 + 15 条契约测试 → `15 passed`；旧模型回归 `test_note_chunk_model.py` 6 passed；commit `b2eecc2`。
- **Task 3**：`0002_s2_1_business_tables.py` → `alembic upgrade head` 输出 `Running upgrade 0001_s1_3 -> 0002_s2_1`；5 表 `\d` 核对通过（users / user_relations / subjects / knowledge_points / knowledge_edges 字段、默认值、UNIQUE、CHECK、FK、HNSW 全部符合 spec §4）；`downgrade -1` 后仅剩 `alembic_version` + `note_chunks`（83 行保留）；再次 `upgrade head` 通过；commit `70d82bb`。
- **Task 4**：5 条负向约束实测报错原文——`violates check constraint "ck_users_role"`、`duplicate key value violates unique constraint "uq_users_username"`、`violates check constraint "ck_knowledge_edges_not_self"`、`violates foreign key constraint "fk_knowledge_points_subject_id"`、`violates check constraint "ck_knowledge_points_level"`；残留检查 0/0/0/0；`smoke.py` 核心表 6/6、退出码 0（临时起了 uvicorn 跑通 /health 后已停止）；commit `aecfd9e`。
- **Task 5**：文档同步；全量回归 `206 passed, 1 warning`；spec 中 5/5 → 6/6 的笔误已在实施前修正。
- 偏离计划：无。未引入依赖、未改 `0001`、未动 `note_chunks`。