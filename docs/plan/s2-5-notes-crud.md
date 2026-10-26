# S2-5 笔记表与 CRUD API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `notes` / `note_kps` / `files` 三张表并补齐 `note_chunks` 外键，交付笔记 CRUD（建/列表/详情/部分更新/软删），保存时自动派生 `content_text`，列表复用 S2-4 分页、详情/写操作复用 S2-3 权限，最后用真实 curl + psql 验收全流程。

**Architecture:** 路由（参数校验 + 壳）→ `note_service`（事务、权限、软删、`content_text`）→ SQLAlchemy；列表查询由 `build_notes_query` 生成，排序走白名单，分页走 `paginate_query`。表结构由 Alembic `0003` 迁移落地。

**Tech Stack:** Python 3.11 + FastAPI 0.143 + Pydantic 2.14 + SQLAlchemy 2.1 + Alembic + PostgreSQL 16 + Pytest（FakeSession，不连库）。

**Spec:** `docs/spec/s2-5-notes-crud.md`

## Global Constraints

- 不引入新依赖（`requirements.txt` 不变）。
- 迁移文件名 `0003_s2_5_note_tables.py`，`revision="0003_s2_5"`，`down_revision="0002_s2_1"`；**禁止改 0001/0002**。
- 写入前必须校验 `subject_id` 存在，不允许靠 FK 抛 500。
- 所有笔记查询必须带 `deleted_at IS NULL`（除软删本身）。
- 列表/详情权限与 S2-3 一致：详情 = 本人或已绑定家长/老师；写 = 仅本人且仅 `student`；admin 不绕过。
- `content_text` 不出现在任何响应里；`deleted_at` 也不返回。
- 排序白名单只允许 `created_at` / `updated_at` / `title`，默认 `created_at desc`。
- 测试不连 PostgreSQL、不发网络请求；FakeSession 模拟 `scalar` / `get` / `add` / `commit` / `refresh`。
- 命令在仓库根 `E:\BiShe-AIStudy\study-agent` 的 Git Bash 下执行（Python 用 `.venv/Scripts/python.exe`）。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/models/file.py` | `files` ORM | 新建 |
| `backend/app/models/note.py` | `notes` ORM | 新建 |
| `backend/app/models/note_kp.py` | `note_kps` ORM | 新建 |
| `backend/app/models/note_chunk.py` | 补 3 个外键 | 修改 |
| `backend/alembic/versions/0003_s2_5_note_tables.py` | 建表 + 清理孤儿 + 补 FK | 新建 |
| `backend/app/utils/markdown_text.py` | Markdown → 检索纯文本 | 新建 |
| `backend/app/schemas/notes.py` | 笔记出入参 | 新建 |
| `backend/app/services/note_service.py` | 业务：CRUD、软删、权限、查询构建 | 新建 |
| `backend/app/api/v1/notes.py` | 5 个路由 | 新建 |
| `backend/app/api/router.py` | 挂载 notes | 修改 |
| `backend/tests/test_markdown_text.py` | 纯文本派生 11 条 | 新建 |
| `backend/tests/test_note_service.py` | 服务 18 条 | 新建 |
| `backend/tests/test_notes_api.py` | 接口 13 条 | 新建 |
| `docs/API.md` / `docs/SCHEMA.md` / `AGENTS.md` / `docs/DECISIONS.md` / `docs/PROGRESS.md` | 契约与进度 | 修改 |

---

### Task 1: 表结构（模型 + 迁移）

**Files:**
- Create: `backend/app/models/file.py`、`backend/app/models/note.py`、`backend/app/models/note_kp.py`
- Modify: `backend/app/models/note_chunk.py`
- Create: `backend/alembic/versions/0003_s2_5_note_tables.py`

**Interfaces:**
- Produces: `app.models.note.Note`、`app.models.file.File`、`app.models.note_kp.NoteKp`；数据库三张表与 `note_chunks` 三个外键。

- [ ] **Step 1: `app/models/file.py`**

```python
"""files ORM 模型：SCHEMA §4.1（S2-5 建表，S2-6 接上传）。

sha256 唯一性定「同用户唯一」：多租户下不同用户上传同一份文件互不可见，
同一用户重复上传才复用。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        CheckConstraint(
            "parse_status IN ('pending', 'done')", name="ck_files_parse_status"
        ),
        Index("ix_files_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_files_user_id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    parse_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 2: `app/models/note.py`**

```python
"""notes ORM 模型：SCHEMA §4.2（S2-5）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_user_id_subject_id", "user_id", "subject_id"),
        Index("ix_notes_tags_gin", "tags", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_notes_user_id"), nullable=False
    )
    subject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subjects.id", name="fk_notes_subject_id"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    folder: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("files.id", name="fk_notes_source_file_id"), nullable=True
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 3: `app/models/note_kp.py`**

```python
"""note_kps ORM 模型：SCHEMA §4.4（S2-5 只建表，对齐逻辑在 S2-10）。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NoteKp(Base):
    __tablename__ = "note_kps"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="ck_note_kps_source"),
        Index("ix_note_kps_kp_id", "kp_id"),
    )

    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", name="fk_note_kps_note_id", ondelete="CASCADE"),
        primary_key=True,
    )
    kp_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_points.id", name="fk_note_kps_kp_id"),
        primary_key=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
```

- [ ] **Step 4: `note_chunk.py` 补外键**

把 `note_id` / `user_id` / `source_file_id` 三行改为：

```python
    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", name="fk_note_chunks_note_id_notes", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_note_chunks_user_id_users"),
        nullable=False,
    )
```

以及：

```python
    source_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("files.id", name="fk_note_chunks_source_file_id_files"),
        nullable=True,
    )
```

并在 import 中加入 `ForeignKey`（`from sqlalchemy import ForeignKey`）。

- [ ] **Step 5: 写迁移 `0003_s2_5_note_tables.py`**

```python
"""S2-5 笔记相关表：files / notes / note_kps + note_chunks 外键

Revision ID: 0003_s2_5
Revises: 0002_s2_1
Create Date: 2026-10-26

警告：补外键前会删除“无主” note_chunks（user_id 不在 users 或 note_id 不在 notes）。
本库的 83 行是 S1-3 实验残留（user_id=1、users 为空），删除后不可恢复；
新建库上该语句是 no-op。保留它们就只能造占位用户/笔记，等于把脏数据带进正式库。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_s2_5"
down_revision = "0002_s2_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "parse_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("parse_result_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_files_user_id"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        sa.CheckConstraint(
            "parse_status IN ('pending', 'done')", name="ck_files_parse_status"
        ),
    )
    op.create_index("ix_files_user_id", "files", ["user_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("folder", sa.Text(), nullable=True),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notes_user_id"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name="fk_notes_subject_id"
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["files.id"], name="fk_notes_source_file_id"
        ),
    )
    op.create_index(
        "ix_notes_user_id_subject_id", "notes", ["user_id", "subject_id"]
    )
    op.create_index("ix_notes_tags_gin", "notes", ["tags"], postgresql_using="gin")

    op.create_table(
        "note_kps",
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("kp_id", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], name="fk_note_kps_note_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["kp_id"], ["knowledge_points.id"], name="fk_note_kps_kp_id"
        ),
        sa.PrimaryKeyConstraint("note_id", "kp_id"),
        sa.CheckConstraint("source IN ('ai', 'manual')", name="ck_note_kps_source"),
    )
    op.create_index("ix_note_kps_kp_id", "note_kps", ["kp_id"])

    # 补外键前清理无主行（条件删除：新库上无行可删）
    op.execute(
        sa.text(
            "DELETE FROM note_chunks "
            "WHERE user_id NOT IN (SELECT id FROM users) "
            "   OR note_id NOT IN (SELECT id FROM notes)"
        )
    )

    op.create_foreign_key(
        "fk_note_chunks_note_id_notes",
        "note_chunks",
        "notes",
        ["note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_note_chunks_user_id_users", "note_chunks", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_note_chunks_source_file_id_files",
        "note_chunks",
        "files",
        ["source_file_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_note_chunks_source_file_id_files", "note_chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_note_chunks_user_id_users", "note_chunks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_note_chunks_note_id_notes", "note_chunks", type_="foreignkey"
    )
    op.drop_index("ix_note_kps_kp_id", table_name="note_kps")
    op.drop_table("note_kps")
    op.drop_index("ix_notes_tags_gin", table_name="notes")
    op.drop_index("ix_notes_user_id_subject_id", table_name="notes")
    op.drop_table("notes")
    op.drop_index("ix_files_user_id", table_name="files")
    op.drop_table("files")
```

- [ ] **Step 6: 执行迁移并核验**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m alembic upgrade head
cd ..
docker exec study-agent-postgres psql -U study -d study_agent -c "\d notes" -c "\d note_chunks" -c "select count(*) from note_chunks;"
```
Expected: `alembic` 输出 `Running upgrade 0002_s2_1 -> 0003_s2_5`；`\d notes` 列出三张表字段与索引；`note_chunks` 出现 3 个 FK；`count(*)` 为 **0**（孤儿已清）。

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```
Expected: `280 passed`（模型改动不破坏既有测试）。

- [ ] **Step 7: 提交**

```bash
git add backend/app/models backend/alembic/versions/0003_s2_5_note_tables.py
git commit -m "feat(s2-5): 笔记相关表结构与 note_chunks 外键"
```

---

### Task 2: `content_text` 派生（纯函数）

**Files:**
- Create: `backend/app/utils/markdown_text.py`
- Create: `backend/tests/test_markdown_text.py`

**Interfaces:**
- Produces: `app.utils.markdown_text.to_plain_text(markdown: str) -> str`。

- [ ] **Step 1: 先写测试 `tests/test_markdown_text.py`**

```python
"""S2-5 content_text 派生规则（spec §6）。"""
from __future__ import annotations

from app.utils.markdown_text import to_plain_text


def test_plain_text_unchanged() -> None:
    assert to_plain_text("函数单调性 复习") == "函数单调性 复习"


def test_inline_math_removed() -> None:
    assert to_plain_text("设 $x^2+1$ 为正") == "设 为正"


def test_display_math_removed() -> None:
    assert to_plain_text("公式\n$$\n\\\\frac{1}{2}\n$$\n结尾") == "公式 结尾"


def test_latex_brackets_removed() -> None:
    assert to_plain_text("设 \\(x>0\\) 且 \\[y=1\\]") == "设 且"


def test_link_text_kept() -> None:
    assert to_plain_text("见[单调性定义](https://example.com/a)") == "见单调性定义"


def test_image_alt_kept() -> None:
    assert to_plain_text("![函数图像](a.png)") == "函数图像"


def test_markdown_markers_removed() -> None:
    text = "# 标题\n> 引用\n- 列表项\n---\n| a | b |"
    assert to_plain_text(text) == "标题 引用 列表项 a b"


def test_emphasis_markers_removed() -> None:
    assert to_plain_text("**重点** 与 __补充__ 和 ~~删掉~~") == "重点 与 补充 和 删掉"


def test_inline_code_content_kept() -> None:
    assert to_plain_text("用 `user_id` 过滤") == "用 user_id 过滤"


def test_fenced_code_kept_with_dollar() -> None:
    text = "示例\n```python\nprice = $1\n```\n完"
    plain = to_plain_text(text)
    assert "price = $1" in plain
    assert plain.startswith("示例")


def test_whitespace_collapsed() -> None:
    assert to_plain_text("a\n\n\n b\t\tc ") == "a b c"
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_markdown_text.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.utils.markdown_text'`

- [ ] **Step 3: 实现 `app/utils/markdown_text.py`**

```python
"""S2-5 Markdown → 检索纯文本（spec §6）。

只服务检索，不追求渲染保真：公式符号搜不到且会污染关键词匹配，所以整段去掉；
代码块/行内代码先“冻结”，避免公式与强调规则把代码改坏。
"""
from __future__ import annotations

import re

_FENCED_CODE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_MATH_PATTERNS = (
    re.compile(r"\$\$(.+?)\$\$", re.S),
    re.compile(r"\\\[(.+?)\\\]", re.S),
    re.compile(r"\\\((.+?)\\\)", re.S),
    re.compile(r"\$(.+?)\$", re.S),
)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.M)
_HR = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
_TABLE_PIPE = re.compile(r"\|")
_EMPHASIS_PAIRS = (
    re.compile(r"\*\*(.+?)\*\*", re.S),
    re.compile(r"__(.+?)__", re.S),
    re.compile(r"~~(.+?)~~", re.S),
    re.compile(r"\*(.+?)\*", re.S),
    re.compile(r"(?<![\w])_([^_]+?)_(?![\w])", re.S),
)
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")


def to_plain_text(markdown: str) -> str:
    if not markdown:
        return ""
    stash: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        stash.append(match.group(1).strip())
        return f"\x00{len(stash) - 1}\x00"

    text = _FENCED_CODE.sub(stash_code, markdown)
    text = _INLINE_CODE.sub(stash_code, text)
    for pattern in _MATH_PATTERNS:
        text = pattern.sub(" ", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    for pattern in (_HEADING, _QUOTE, _LIST_MARKER, _HR):
        text = pattern.sub(" ", text)
    text = _TABLE_PIPE.sub(" ", text)
    for pattern in _EMPHASIS_PAIRS:
        text = pattern.sub(r"\1", text)
    text = _ESCAPE.sub(r"\1", text)

    def restore_code(match: re.Match[str]) -> str:
        return stash[int(match.group(1))]

    text = _PLACEHOLDER.sub(restore_code, text)
    return re.sub(r"\s+", " ", text).strip()
```

- [ ] **Step 4: 跑绿**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_markdown_text.py -q
```
Expected: `11 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/utils/markdown_text.py backend/tests/test_markdown_text.py
git commit -m "feat(s2-5): 笔记检索文本派生"
```

---

### Task 3: schema + service + 服务测试

**Files:**
- Create: `backend/app/schemas/notes.py`、`backend/app/services/note_service.py`
- Create: `backend/tests/test_note_service.py`

**Interfaces:**
- Consumes: `to_plain_text`、`ensure_student_access`、`apply_sort` / `paginate_query` / `PageParams` / `SortParams`。
- Produces: `NoteCreate` / `NoteUpdate` / `NoteSummary` / `NoteOut`；`note_service` 的 6 个函数与 `NOTE_SORT_FIELDS`。

- [ ] **Step 1: `app/schemas/notes.py`**

```python
"""S2-5 笔记出入参（API.md §2）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TAGS = 20
MAX_TAG_LENGTH = 30


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"单个标签不超过 {MAX_TAG_LENGTH} 字")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(min_length=1, max_length=200_000)
    subject_id: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    folder: str | None = Field(default=None, max_length=100)

    @field_validator("title", "content_md")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = Field(default=None, min_length=1, max_length=200_000)
    subject_id: int | None = Field(default=None, ge=1)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    folder: str | None = Field(default=None, max_length=100)

    @field_validator("title", "content_md")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("tags")
    @classmethod
    def _normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_tags(value)


class NoteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subject_id: int | None
    tags: list[str] | None
    folder: str | None
    created_at: datetime
    updated_at: datetime


class NoteOut(NoteSummary):
    content_md: str
    source_file_id: int | None
```

- [ ] **Step 2: `app/services/note_service.py`**

```python
"""S2-5 笔记业务（spec §5）。

一个用例一个事务；越权与不存在分开报：不存在 404，他人可读范围外 403。
写操作只认 owner，不再查家长/老师关系——谁改的必须可追溯。
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.core.permissions import ensure_student_access
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.notes import NoteCreate, NoteSummary, NoteUpdate
from app.utils.markdown_text import to_plain_text
from app.utils.pagination import PageParams, SortParams, apply_sort, paginate_query

NOTE_SORT_FIELDS: Mapping[str, Any] = {
    "created_at": Note.created_at,
    "updated_at": Note.updated_at,
    "title": Note.title,
}

_REQUIRED_FIELDS = ("title", "content_md")


def escape_like(term: str) -> str:
    """转义 LIKE 元字符：用户输入的 % 不能变成通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_notes_query(
    *,
    owner_id: int,
    subject_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Select:
    stmt = select(Note).where(Note.user_id == owner_id, Note.deleted_at.is_(None))
    if subject_id is not None:
        stmt = stmt.where(Note.subject_id == subject_id)
    if tag:
        # @> 能被 ix_notes_tags_gin 直接命中；= ANY(tags) 则容易退化成逐行判断
        stmt = stmt.where(Note.tags.contains([tag]))
    if q:
        pattern = f"%{escape_like(q)}%"
        stmt = stmt.where(
            or_(
                Note.title.ilike(pattern, escape="\\"),
                Note.content_text.ilike(pattern, escape="\\"),
            )
        )
    if created_from is not None:
        stmt = stmt.where(Note.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Note.created_at <= created_to)
    return stmt


def _ensure_subject_exists(session: Session, subject_id: int | None) -> None:
    if subject_id is None:
        return
    if session.get(Subject, subject_id) is None:
        raise InvalidParamError("学科不存在")


def _load_note(session: Session, note_id: int) -> Note:
    note = session.scalar(
        select(Note).where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    if note is None:
        raise NotFoundError("笔记不存在")
    return note


def create_note(session: Session, *, owner: User, payload: NoteCreate) -> Note:
    _ensure_subject_exists(session, payload.subject_id)
    note = Note(
        user_id=owner.id,
        subject_id=payload.subject_id,
        title=payload.title,
        content_md=payload.content_md,
        content_text=to_plain_text(payload.content_md),
        tags=payload.tags or None,
        folder=payload.folder,
    )
    session.add(note)
    _commit(session)
    session.refresh(note)
    return note


def list_notes(
    session: Session,
    *,
    owner: User,
    params: PageParams,
    sorting: SortParams,
    subject_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PageData[NoteSummary]:
    stmt = build_notes_query(
        owner_id=owner.id,
        subject_id=subject_id,
        tag=tag,
        q=q,
        created_from=created_from,
        created_to=created_to,
    )
    stmt = apply_sort(
        stmt,
        sort_by=sorting.sort_by,
        order=sorting.order,
        allowed=NOTE_SORT_FIELDS,
        default_sort="created_at",
    )
    return paginate_query(session, stmt, params, item_model=NoteSummary)


def get_note(session: Session, *, note_id: int, viewer: User) -> Note:
    note = _load_note(session, note_id)
    if note.user_id != viewer.id:
        ensure_student_access(session, viewer, note.user_id)
    return note


def update_note(
    session: Session, *, note_id: int, owner: User, payload: NoteUpdate
) -> Note:
    note = _load_note(session, note_id)
    if note.user_id != owner.id:
        raise ForbiddenError("无权修改该资源")
    data = payload.model_dump(exclude_unset=True)
    for field in _REQUIRED_FIELDS:
        if field in data and data[field] is None:
            raise InvalidParamError(f"{field} 不能为空")
    if "subject_id" in data:
        _ensure_subject_exists(session, data["subject_id"])
    if "content_md" in data:
        note.content_text = to_plain_text(data["content_md"])
    if "tags" in data:
        data["tags"] = data["tags"] or None
    for field, value in data.items():
        setattr(note, field, value)
    _commit(session)
    session.refresh(note)
    return note


def delete_note(session: Session, *, note_id: int, owner: User) -> None:
    note = _load_note(session, note_id)
    if note.user_id != owner.id:
        raise ForbiddenError("无权删除该资源")
    note.deleted_at = datetime.now(timezone.utc)
    _commit(session)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
```

- [ ] **Step 3: 写服务测试 `tests/test_note_service.py`**

```python
"""S2-5 笔记服务测试（spec §8.2）：FakeSession，不连数据库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation
from app.schemas.common import PageData
from app.schemas.notes import NoteCreate, NoteUpdate
from app.services import note_service
from app.utils.pagination import PageParams, SortParams


class FakeSession:
    def __init__(self, *, note: Note | None = None, relation: int | None = None,
                 subject: Subject | None = None) -> None:
        self.note = note
        self.relation = relation
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is Note:
            return self.note
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        if entity is Subject:
            return self.subject
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        now = datetime.now(timezone.utc)
        if getattr(instance, "id", None) is None:
            instance.id = 42
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        instance.updated_at = now


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_a") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _note(note_id: int = 1, *, owner_id: int = 1, **overrides) -> Note:
    now = datetime.now(timezone.utc)
    note = Note(
        user_id=owner_id,
        subject_id=None,
        title="函数单调性",
        content_md="原正文 $x$",
        content_text="原正文",
        tags=["函数"],
        folder=None,
        source_file_id=None,
    )
    note.id = note_id
    note.created_at = now
    note.updated_at = now
    note.deleted_at = None
    for key, value in overrides.items():
        setattr(note, key, value)
    return note


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    box: dict[str, object] = {}

    def fake_paginate(session, stmt, params, *, item_model):
        box["stmt"] = stmt
        box["params"] = params
        return PageData(
            items=[], total=0, page=params.page, page_size=params.page_size
        )

    monkeypatch.setattr(note_service, "paginate_query", fake_paginate)
    return box


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_create_note_derives_content_text_and_normalizes_tags() -> None:
    session = FakeSession()
    note = note_service.create_note(
        session,
        owner=_user(),
        payload=NoteCreate(
            title="一元二次", content_md="设 $x^2$ 有解", tags=[" 函数 ", "函数", "方程"]
        ),
    )
    assert note.user_id == 1
    assert note.content_text == "设 有解"
    assert note.tags == ["函数", "方程"]
    assert session.commits == 1


def test_create_note_accepts_subject_and_folder() -> None:
    session = FakeSession(subject=Subject(name="数学", code="math"))
    note = note_service.create_note(
        session,
        owner=_user(),
        payload=NoteCreate(
            title="函数", content_md="正文", subject_id=3, folder="必修一"
        ),
    )
    assert (note.subject_id, note.folder) == (3, "必修一")


def test_create_note_rejects_missing_subject() -> None:
    session = FakeSession(subject=None)
    with pytest.raises(InvalidParamError) as excinfo:
        note_service.create_note(
            session,
            owner=_user(),
            payload=NoteCreate(title="函数", content_md="正文", subject_id=3),
        )
    assert excinfo.value.code == 42200


def test_list_notes_filters_owner_and_soft_deleted(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams()
    )
    sql = _sql(captured["stmt"])
    assert "notes.user_id =" in sql
    assert "notes.deleted_at IS NULL" in sql


def test_list_notes_filters_by_tag(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams(), tag="函数"
    )
    sql = _sql(captured["stmt"])
    assert "notes.tags @>" in sql


def test_list_notes_escapes_like_wildcards(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams(), q="100%"
    )
    compiled = captured["stmt"].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    assert any("%100\\%%" in str(value) for value in compiled.params.values())


def test_list_notes_filters_by_time_range(captured: dict[str, object]) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, tzinfo=timezone.utc)
    note_service.list_notes(
        FakeSession(),
        owner=_user(),
        params=PageParams(),
        sorting=SortParams(),
        created_from=start,
        created_to=end,
    )
    sql = _sql(captured["stmt"])
    assert "notes.created_at >=" in sql
    assert "notes.created_at <=" in sql


def test_list_notes_defaults_to_created_at_desc(captured: dict[str, object]) -> None:
    note_service.list_notes(
        FakeSession(), owner=_user(), params=PageParams(), sorting=SortParams()
    )
    assert _sql(captured["stmt"]).rstrip().endswith("ORDER BY notes.created_at DESC")


def test_list_notes_rejects_unknown_sort_field(captured: dict[str, object]) -> None:
    with pytest.raises(InvalidParamError):
        note_service.list_notes(
            FakeSession(),
            owner=_user(),
            params=PageParams(),
            sorting=SortParams(sort_by="content_md"),
        )


def test_get_note_returns_own_note() -> None:
    note = _note()
    assert note_service.get_note(FakeSession(note=note), note_id=1, viewer=_user()) is note


def test_get_note_missing_returns_404() -> None:
    with pytest.raises(NotFoundError):
        note_service.get_note(FakeSession(note=None), note_id=1, viewer=_user())


def test_get_note_of_other_student_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1), relation=None)
    with pytest.raises(ForbiddenError):
        note_service.get_note(
            session, note_id=1, viewer=_user(2, username="student_b")
        )


def test_get_note_allows_bound_parent() -> None:
    note = _note(owner_id=1)
    session = FakeSession(note=note, relation=10)
    viewer = _user(3, role="parent", username="parent_1")
    assert note_service.get_note(session, note_id=1, viewer=viewer) is note


def test_update_note_title_only_keeps_content_text() -> None:
    note = _note()
    session = FakeSession(note=note)
    updated = note_service.update_note(
        session, note_id=1, owner=_user(), payload=NoteUpdate(title="新标题")
    )
    assert updated.title == "新标题"
    assert updated.content_text == "原正文"


def test_update_note_content_md_recomputes_content_text() -> None:
    note = _note()
    session = FakeSession(note=note)
    updated = note_service.update_note(
        session, note_id=1, owner=_user(), payload=NoteUpdate(content_md="新 $y$ 正文")
    )
    assert updated.content_md == "新 $y$ 正文"
    assert updated.content_text == "新 正文"


def test_update_note_of_other_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1))
    with pytest.raises(ForbiddenError):
        note_service.update_note(
            session, note_id=1, owner=_user(2, username="student_b"), payload=NoteUpdate(title="x")
        )


def test_delete_note_sets_deleted_at() -> None:
    note = _note()
    session = FakeSession(note=note)
    note_service.delete_note(session, note_id=1, owner=_user())
    assert note.deleted_at is not None
    assert session.commits == 1


def test_delete_note_of_other_returns_403() -> None:
    session = FakeSession(note=_note(owner_id=1))
    with pytest.raises(ForbiddenError):
        note_service.delete_note(session, note_id=1, owner=_user(2, username="student_b"))
```

- [ ] **Step 4: 跑服务测试**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_note_service.py -q
```
Expected: `18 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas/notes.py backend/app/services/note_service.py backend/tests/test_note_service.py
git commit -m "feat(s2-5): 笔记业务与查询构建"
```

---

### Task 4: 路由 + 接口测试 + 全量回归

**Files:**
- Create: `backend/app/api/v1/notes.py`、`backend/tests/test_notes_api.py`
- Modify: `backend/app/api/router.py`

**Interfaces:**
- Consumes: `note_service`、`page_params` / `sort_params`、`require_role` / `get_current_user`、`NoteCreate` / `NoteUpdate` / `NoteOut` / `NoteSummary`。

- [ ] **Step 1: `app/api/v1/notes.py`**

```python
"""S2-5 笔记 CRUD 接口（API.md §2）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.notes import NoteCreate, NoteOut, NoteSummary, NoteUpdate
from app.services import note_service
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", status_code=201, response_model=Envelope[NoteOut], summary="新建笔记")
def create_note(
    payload: NoteCreate,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.create_note(session, owner=current_user, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.get("", response_model=Envelope[PageData[NoteSummary]], summary="笔记列表（仅本人）")
def list_notes(
    params: PageParams = Depends(page_params),
    sorting: SortParams = Depends(sort_params),
    subject_id: int | None = Query(None, ge=1, description="学科筛选"),
    tag: str | None = Query(None, min_length=1, max_length=30, description="标签精确匹配"),
    q: str | None = Query(None, min_length=1, max_length=100, description="标题/正文关键词"),
    created_from: datetime | None = Query(None, description="创建时间下界（ISO-8601）"),
    created_to: datetime | None = Query(None, description="创建时间上界（ISO-8601）"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[NoteSummary]]:
    page = note_service.list_notes(
        session,
        owner=current_user,
        params=params,
        sorting=sorting,
        subject_id=subject_id,
        tag=tag,
        q=q,
        created_from=created_from,
        created_to=created_to,
    )
    return Envelope(trace_id=get_trace_id(), data=page)


@router.get("/{note_id}", response_model=Envelope[NoteOut], summary="笔记详情")
def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.get_note(session, note_id=note_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.patch("/{note_id}", response_model=Envelope[NoteOut], summary="部分更新笔记")
def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.update_note(
        session, note_id=note_id, owner=current_user, payload=payload
    )
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.delete("/{note_id}", status_code=204, response_model=None, summary="软删除笔记")
def delete_note(
    note_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> None:
    note_service.delete_note(session, note_id=note_id, owner=current_user)
```

- [ ] **Step 2: `app/api/router.py` 挂载**

```python
"""v1 路由汇总：只做 include，不写业务。"""
from fastapi import APIRouter

from app.api.v1 import auth, notes

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(notes.router)

__all__ = ["api_router"]
```

- [ ] **Step 3: 写接口测试 `tests/test_notes_api.py`**

```python
"""S2-5 笔记接口测试（spec §8.3）：TestClient + get_db 覆盖，不连库。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation
from app.schemas.common import PageData
from app.schemas.notes import NoteSummary
from app.services import note_service


class FakeSession:
    def __init__(
        self,
        *,
        user: User | None = None,
        note: Note | None = None,
        relation: int | None = None,
        subject: Subject | None = None,
    ) -> None:
        self.user = user
        self.note = note
        self.relation = relation
        self.subject = subject
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is Note:
            return self.note
        if entity is UserRelation:
            return self.relation
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        if entity is Subject:
            return self.subject
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        now = datetime.now(timezone.utc)
        if getattr(instance, "id", None) is None:
            instance.id = 42
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        instance.updated_at = now


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_a") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _note(note_id: int = 1, *, owner_id: int = 1) -> Note:
    now = datetime.now(timezone.utc)
    note = Note(
        user_id=owner_id,
        subject_id=None,
        title="函数单调性",
        content_md="正文 $x$",
        content_text="正文",
        tags=["函数"],
        folder=None,
        source_file_id=None,
    )
    note.id = note_id
    note.created_at = now
    note.updated_at = now
    note.deleted_at = None
    return note


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_create_note_returns_201(client: TestClient) -> None:
    session = FakeSession(user=_user())
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数单调性", "content_md": "设 $x$ 递增", "tags": ["函数"]},
        headers=_headers(_user()),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["id"] == 42
    assert data["title"] == "函数单调性"
    assert "content_text" not in data
    assert "deleted_at" not in data
    assert session.added[0].content_text == "设 递增"


def test_create_note_rejects_blank_title(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.post(
        "/api/v1/notes",
        json={"title": "   ", "content_md": "正文"},
        headers=_headers(_user()),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_create_note_forbidden_for_teacher(client: TestClient) -> None:
    session = FakeSession(user=_user(role="teacher", username="teacher_1"))
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数", "content_md": "正文"},
        headers=_headers(session.user),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_create_note_rejects_missing_subject(client: TestClient) -> None:
    session = FakeSession(user=_user(), subject=None)
    _override(session)
    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数", "content_md": "正文", "subject_id": 9},
        headers=_headers(session.user),
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == "学科不存在"


def test_list_notes_returns_page_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)

    def fake_paginate(session_, stmt, params, *, item_model):
        return PageData(
            items=[NoteSummary.model_validate(note)],
            total=1,
            page=params.page,
            page_size=params.page_size,
        )

    monkeypatch.setattr(note_service, "paginate_query", fake_paginate)
    resp = client.get("/api/v1/notes", headers=_headers(session.user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert data["items"][0]["title"] == "函数单调性"
    assert "content_md" not in data["items"][0]


def test_list_notes_rejects_unknown_sort(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = FakeSession(user=_user())
    _override(session)
    monkeypatch.setattr(note_service, "paginate_query", lambda *a, **k: None)
    resp = client.get("/api/v1/notes?sort_by=content_md", headers=_headers(session.user))
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_get_own_note_returns_detail(client: TestClient) -> None:
    session = FakeSession(user=_user(), note=_note())
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 200
    assert resp.json()["data"]["content_md"] == "正文 $x$"


def test_get_other_student_note_returns_403(client: TestClient) -> None:
    session = FakeSession(user=_user(2, username="student_b"), note=_note(owner_id=1))
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_note_allowed_for_bound_parent(client: TestClient) -> None:
    parent = _user(3, role="parent", username="parent_1")
    session = FakeSession(user=parent, note=_note(owner_id=1), relation=10)
    _override(session)
    resp = client.get("/api/v1/notes/1", headers=_headers(parent))
    assert resp.status_code == 200


def test_get_missing_note_returns_404(client: TestClient) -> None:
    session = FakeSession(user=_user(), note=None)
    _override(session)
    resp = client.get("/api/v1/notes/99", headers=_headers(session.user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_patch_note_updates_title(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)
    resp = client.patch(
        "/api/v1/notes/1", json={"title": "新标题"}, headers=_headers(session.user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "新标题"
    assert note.content_text == "正文"


def test_delete_note_returns_204_and_soft_deletes(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)
    resp = client.delete("/api/v1/notes/1", headers=_headers(session.user))
    assert resp.status_code == 204
    assert resp.content == b""
    assert note.deleted_at is not None


def test_notes_require_token(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.get("/api/v1/notes")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
```

- [ ] **Step 4: 跑接口测试 + 全量回归**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_notes_api.py -q
../.venv/Scripts/python.exe -m pytest -q
```
Expected: `13 passed`；全量 `322 passed, 1 warning`（280 + 11 + 18 + 13）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/v1/notes.py backend/app/api/router.py backend/tests/test_notes_api.py
git commit -m "feat(s2-5): 笔记 CRUD 接口"
```

---

### Task 5: 真实 curl 全流程验收

**Files:** 无代码改动（只跑验证；发现问题回改前序任务）。

- [ ] **Step 1: 启动服务**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```
（后台运行，验收完 `job_kill`）

- [ ] **Step 2: 注册 A、B 并拿 token**

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"note_a","password":"test-pass-123","nickname":"笔记A","role":"student"}'
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"note_b","password":"test-pass-123","nickname":"笔记B","role":"student"}'
# 分别登录，记录 TOKEN_A / TOKEN_B
```
Expected: 201；登录 `data.access_token` 非空。

- [ ] **Step 3: 建 → 查 → 越权**

```bash
curl -s -X POST localhost:8000/api/v1/notes -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' \
  -d '{"title":"函数单调性","content_md":"设 $x_1<x_2$ 则 $f(x_1)<f(x_2)$","tags":["函数","单调性"]}'
curl -s "localhost:8000/api/v1/notes?page=1&page_size=20" -H "Authorization: Bearer $TOKEN_A"
curl -s localhost:8000/api/v1/notes/1 -H "Authorization: Bearer $TOKEN_A"
curl -s localhost:8000/api/v1/notes/1 -H "Authorization: Bearer $TOKEN_B"
```
Expected: 201（`content_md` 保留 LaTeX，无 `content_text`）；列表 `total=1`；A 详情 200；**B 详情 403/40300**（S2-3 的真实接口证据）。

- [ ] **Step 4: 筛选 + 排序**

```bash
curl -s "localhost:8000/api/v1/notes?q=单调性" -H "Authorization: Bearer $TOKEN_A"
curl -s "localhost:8000/api/v1/notes?tag=函数" -H "Authorization: Bearer $TOKEN_A"
curl -s "localhost:8000/api/v1/notes?sort_by=title&order=asc" -H "Authorization: Bearer $TOKEN_A"
curl -s "localhost:8000/api/v1/notes?sort_by=content_md" -H "Authorization: Bearer $TOKEN_A"
```
Expected: q/tag 命中 1 条；排序生效；非白名单 → 422/42200。

- [ ] **Step 5: 改 → 核验 updated_at → 软删**

```bash
# 记录改前 updated_at
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select id, updated_at from notes where id=1;"
curl -s -X PATCH localhost:8000/api/v1/notes/1 -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' -d '{"title":"函数单调性（修订）","content_md":"新正文"}'
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select id, title, updated_at, content_text from notes where id=1;"
curl -s -X DELETE -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/notes/1 \
  -H "Authorization: Bearer $TOKEN_A"
curl -s "localhost:8000/api/v1/notes" -H "Authorization: Bearer $TOKEN_A"
curl -s localhost:8000/api/v1/notes/1 -H "Authorization: Bearer $TOKEN_A"
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select id, deleted_at is not null as deleted, updated_at from notes where id=1;"
```
Expected: PATCH 后 `updated_at` 变大、`content_text=新正文`；DELETE 204；列表 `total=0`；详情 404；数据库行仍在且 `deleted_at` 非空。

- [ ] **Step 6: 清理测试数据**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "delete from note_chunks where user_id in (select id from users where username like 'note_%');
   delete from notes where user_id in (select id from users where username like 'note_%');
   delete from users where username like 'note_%';"
```
Expected: 全部清理干净（`select count(*) from notes` = 0、`users` = 0）。

- [ ] **Step 7: 记录证据**

把 Step 2–6 的真实输出摘要写进 plan「执行记录」与 PROGRESS 变更日志（数字必须是实测，不允许编造）。

---

### Task 6: 文档同步与收尾

**Files:**
- Modify: `docs/API.md`（§2 五条接口定稿 + §12 TODO）
- Modify: `docs/SCHEMA.md`（§4.1 sha256 定稿、§4.3 外键说明）
- Modify: `AGENTS.md`（§9.6 笔记锚点）
- Modify: `docs/DECISIONS.md`（D-025）
- Modify: `docs/PROGRESS.md`（状态、清单、遗留、日志）
- Modify: `docs/plan/s2-5-notes-crud.md`（执行记录）

- [ ] **Step 1: API.md §2 重写**

按 spec §4 写五条接口（参数表、出参示例、错误码），删除「TODO（S2-5）」字样；§12 中笔记相关 TODO 行同步。

- [ ] **Step 2: SCHEMA.md**

- §4.1 `sha256` 行：`UNIQUE ⚠（全局/按用户，S2-6 定）` → `UNIQUE(user_id, sha256) ✅（S2-5 定稿：同用户唯一）`
- §4.3 下方引用：改为「S2-5 迁移 0003 已补 3 个外键（note_id/user_id/source_file_id）」并注明清理了 83 行孤儿
- §4 开头加一行：`> S2-5 迁移 0003 已建表：files / notes / note_kps（索引见迁移）`

- [ ] **Step 3: AGENTS.md §9.6 笔记锚点**

```markdown
- 笔记模块样例：backend/app/models/note.py + backend/app/services/note_service.py + backend/app/api/v1/notes.py（写时派生 content_text；软删 deleted_at 全查询过滤；`build_notes_query` 固定 user_id + deleted_at；排序走 S2-4 白名单；越权 403/不存在 404）
```

- [ ] **Step 4: DECISIONS.md 追加 D-025**

9 条决策（建表范围、孤儿清理、PATCH+204、权限、ILIKE、content_text 规则、subject 校验、tags 类型、列表 Summary）+ 验证（pytest 322、curl 全流程实际输出）+ 已知限制（spec §10）。

- [ ] **Step 5: PROGRESS.md**

1. 当前状态：最近完成 S2-5，下一步 S2-6；
2. 任务清单 S2-5 打 `[x]`；
3. 遗留表：q 是 ILIKE、软删无回收站、无家长视角列表、note_kps 未对齐、files 无上传接口（补 S2-6 前标记为依赖）；
4. 变更日志 `### 2026-10-26（S2-5）`：交付、决策、验收证据（pytest + curl 关键输出 + psql 核验）、已知限制、文档同步。

- [ ] **Step 6: 全量回归 + 工作区核对 + 提交**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd .. && git status --short && git log --oneline -4
```
Expected: `322 passed`；工作区仅剩文档；然后：

```bash
git add docs/ AGENTS.md
git commit -m "docs(s2-5): 笔记契约、决策与进度同步"
```

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §2.1 做（迁移/模型/schema/服务/工具/路由/测试/文档） | Task 1–6 |
| §2.3 决策 9 条 | Task 1–4 实现 + Task 6 记录 |
| §3 表结构（files/notes/note_kps/FK/索引） | Task 1 |
| §4 API 契约（5 接口、参数、错误） | Task 4 + Task 6 API.md |
| §5 函数契约 | Task 3 |
| §6 content_text 规则 | Task 2 |
| §7 权限矩阵 | Task 3–4（复用 S2-3） |
| §8 测试（11 + 18 + 13） | Task 2–4 |
| §9 curl 全流程 | Task 5 |
| §10 已知限制 | Task 6 Step 4–5 |
| §11 文档同步 | Task 6 |

**2. Placeholder scan**：无 TBD；每个代码步骤给出完整文件；curl 步骤给出具体命令与预期输出。

**3. Type consistency**：`NoteSummary` / `NoteOut` / `NoteCreate` / `NoteUpdate` 在 schema、service、route、test 中名称一致；`NOTE_SORT_FIELDS` 与 `apply_sort(allowed=...)` 一致；`PageParams` / `SortParams` 来自 S2-4；`ensure_student_access(session, viewer, student_id)` 位置参数与 S2-3 实现一致；`ForbiddenError` / `NotFoundError` / `InvalidParamError` 均来自 `app.core.exceptions`。

## 执行记录

（实施时回填：pytest 数字、curl 实测输出、commit 列表、与 plan 的偏差。）

**提交列表**

1. `13f2e17 feat(s2-5): 笔记相关表结构与 note_chunks 外键`
2. `0b8452c feat(s2-5): 笔记检索文本派生`
3. `ec1c11d feat(s2-5): 笔记业务与查询构建`
4. `9e848a6 feat(s2-5): 笔记 CRUD 接口`
5. `docs(s2-5): 笔记契约、决策与进度同步`

**Task 1 实测**

- `alembic upgrade head` → `Running upgrade 0002_s2_1 -> 0003_s2_5, S2-5 笔记相关表：files / notes / note_kps + note_chunks 外键`
- psql：`select count(*) from note_chunks` = **0**（迁移前 83，条件删除生效）；`note_chunks` 约束列表出现 `fk_note_chunks_note_id_notes` / `fk_note_chunks_user_id_users` / `fk_note_chunks_source_file_id_files`；`\d notes` 含 `ix_notes_tags_gin gin (tags)`、`ix_notes_user_id_subject_id`、三个 FK
- `pytest -q` = **280 passed, 1 warning**（建表不改行为）
- `alembic check` = `No new upgrade operations detected.`（模型与迁移一致）

**Task 2 实测**：先红（`ModuleNotFoundError: app.utils.markdown_text`）→ 实现后 **11 passed**。

**Task 3 实测**：**18 passed**。偏差：`Note.tags.any(tag)` 触发 SQLAlchemy 2.1 `SADeprecationWarning`（`ARRAY.Comparator.any() ... deprecated`），改用 `postgresql.ARRAY` + `Note.tags.contains([tag])`（编译为 `notes.tags @> %(tags_1)s::TEXT[]`），测试断言同步改为 `"notes.tags @>"`；模型 import 从通用 `sqlalchemy.ARRAY` 换成 `sqlalchemy.dialects.postgresql.ARRAY`。

**Task 4 实测**：接口 **13 passed**；全量 **322 passed, 1 warning**（280 + 42）。

**Task 5 实测（uvicorn + curl + psql，真实库）**

| 步骤 | 实测 |
|---|---|
| health / 注册 A、B | `200`；用户 id 6、7，`role=student` |
| 建笔记 | `201`，`data.content_md` 保留 `$x_1<x_2$` 原文，无 `content_text`；psql `content_text` = `设 则` |
| A 列表 | `total=1`，`data` 恰为 `{items,total,page,page_size}`，items 无正文 |
| B 读 A 的笔记 | **403 / 40300「无权访问该资源」**（S2-3 延迟的真实接口证据） |
| B 列表 | `total=0`（列表仅本人） |
| 筛选 | `q=单调性` 命中 1；`q=zzz` 0 条；`tag=函数` 命中；`subject_id=4` 命中新建的「二次函数」 |
| 排序 | `sort_by=title&order=asc` 200；`sort_by=content_md` → 422/42200「不支持的排序字段：content_md（可选：created_at, title, updated_at）」；`page_size=101` → 422/42200 |
| B 改 / 删 | 均 403/40300（「无权修改该资源」/「无权删除该资源」） |
| PATCH | 200；psql `updated_at` `14:20:58.345473` → `14:21:23.490902`，`created_at` 不变，`content_text` 重算为「修订后的正文」 |
| DELETE | `204` 无体；列表 `total=1`（另一条）；详情 `404/40400`；psql 行仍在且 `deleted_at` 非空 |
| 清理 | notes/users/subjects/note_chunks 计数均为 **0** |

**遗留**：见 D-025 与 PROGRESS 遗留 10–13。