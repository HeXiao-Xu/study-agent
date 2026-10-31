# S3-4 Prompt 版本管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 QA Prompt 存入 `prompt_templates`，提供不可变版本与管理接口，启用后下一次问答立即使用新内容。

**Architecture:** 迁移建表并种子 `qa/v1`；`prompt_service` 负责版本/激活；`prompt_builder` 抽出 Jinja2 文本渲染入口，`answer_question` 接受可选模板；`scripts/ask.py` 从库读 active 后传入。上下文组装沿用 S1-6。

**Tech Stack:** Python 3.11、SQLAlchemy 2.0、Alembic、Pydantic v2、Jinja2、FastAPI、pytest；不新增依赖。

**Spec:** `docs/spec/s3-4-prompt-management.md`

## Global Constraints

- 不加依赖；不改历史迁移；不加前端；不改 rewrite/kp_align、检索、SSE。
- 表：`prompt_templates`；`UNIQUE(name, version)`；部分唯一索引 `uq_prompt_templates_active_name WHERE is_active`。
- 版本行不可变；仅 admin 可写；`created_by` 取当前 admin；`updated_at` 在启用时刷新。
- Prompt 渲染必须 Jinja2 `StrictUndefined`；缺变量抛 `PromptTemplateError`，禁止静默空串。
- 生产链路（`scripts/ask.py`、后续 S3-5）只读库；`qa_v1.md` 仅单测/兼容缺省。
- 测试禁止真实外部调用；pytest 全绿才提交；Conventional Commits 带 `(s3-4)`；`git push` 由用户执行。
- 真实数字必须来自实跑，不伪造。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/models/prompt_template.py` | 新建 | `PromptTemplate` ORM 与约束 |
| `backend/app/models/__init__.py` | 修改 | 注册模型供 Alembic 发现 |
| `backend/alembic/versions/0006_s3_4_prompt_templates.py` | 新建 | 建表、索引、种子 `qa/v1` |
| `backend/app/ai/rag/prompt_builder.py` | 修改 | 抽出 `render_prompt_text`，文件版复用 |
| `backend/app/ai/rag/answerer.py` | 修改 | 可选 `prompt_template` |
| `backend/app/services/prompt_service.py` | 新建 | active 读取、版本创建、激活、列表 |
| `backend/app/schemas/prompt.py` | 新建 | 出入参 |
| `backend/app/api/v1/admin.py` | 修改 | 三个 admin 接口 |
| `scripts/ask.py` | 修改 | 从库取 active，传入 answerer，打印版本 |
| `backend/tests/test_prompt_model.py` | 新建 | 表字段/索引 2 条 |
| `backend/tests/test_prompt_builder.py` | 修改 | 文本渲染/缺变量 2 条 |
| `backend/tests/test_answerer.py` | 修改 | 自定义模板/缺变量 2 条 |
| `backend/tests/test_prompt_service.py` | 新建 | 服务 12 条 |
| `backend/tests/test_prompt_admin_api.py` | 新建 | 接口 8 条 |

---

### Task 1: 表、迁移与种子

**Files:**
- Create: `backend/app/models/prompt_template.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0006_s3_4_prompt_templates.py`
- Test: `backend/tests/test_prompt_model.py`

**Interfaces:**
- Produces: `PromptTemplate`（字段见下）；迁移 revision `0006_s3_4`，down_revision `0005_s2_8`；种子 `qa/v1`。
- 后续任务用：`PromptTemplate.name/version/content/variables_json/model_hint/is_active/created_by/created_at/updated_at`。

- [ ] **Step 1: 写失败的模型测试**

`backend/tests/test_prompt_model.py`：

```python
"""S3-4 prompt_templates 模型契约（不连库）。"""
from __future__ import annotations

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.prompt_template import PromptTemplate


def test_prompt_template_columns_contract() -> None:
    table = PromptTemplate.__table__
    expected = {
        "id",
        "name",
        "version",
        "content",
        "variables_json",
        "model_hint",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert expected <= set(table.c.keys())
    assert table.c.id.primary_key is True
    assert table.c.name.nullable is False
    assert table.c.version.nullable is False
    assert table.c.content.nullable is False
    assert table.c.variables_json.nullable is True
    assert isinstance(table.c.variables_json.type, JSONB)
    assert table.c.model_hint.nullable is True
    assert table.c.is_active.nullable is False
    assert table.c.created_by.nullable is True
    assert table.c.created_at.nullable is False
    assert table.c.updated_at.nullable is False


def test_prompt_template_indexes_and_unique() -> None:
    table = PromptTemplate.__table__
    index_names = {index.name for index in table.indexes}
    assert "uq_prompt_templates_active_name" in index_names
    assert "ix_prompt_templates_name_created_at" in index_names
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_prompt_templates_name_version" in unique_names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_model.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.models.prompt_template`。

- [ ] **Step 3: 实现模型**

`backend/app/models/prompt_template.py`：

```python
"""S3-4 Prompt 模板版本：SCHEMA §8.3。

版本行不可变；is_active 由部分唯一索引保证每个 name 最多一条。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "name", "version", name="uq_prompt_templates_name_version"
        ),
        Index(
            "uq_prompt_templates_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_prompt_templates_name_created_at", "name", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    model_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_prompt_templates_created_by"),
        nullable=True,
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

`backend/app/models/__init__.py` 加导入与 `__all__`：

```python
from app.models.prompt_template import PromptTemplate
```

```python
    "PromptTemplate",
```

- [ ] **Step 4: 写迁移与种子**

`backend/alembic/versions/0006_s3_4_prompt_templates.py`：

```python
"""S3-4 prompt_templates 表与 qa/v1 种子

Revision ID: 0006_s3_4
Revises: 0005_s2_8
Create Date: 2026-10-31
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_s3_4"
down_revision = "0005_s2_8"
branch_labels = None
depends_on = None

QA_V1_CONTENT = """你是该学生的私人学习助理。请严格按以下规则回答：
1. 只能依据【参考资料】回答；资料中没有的内容，明确说"你的资料里没有相关内容"。
2. 每个来自资料的结论后必须标注引用编号，如 [1][2]；编号必须对应参考资料。
3. 若你要补充资料之外的通用知识，必须另起一段并加前缀"【补充说明｜非你的资料】"。
4. 数学推导分步骤写，公式用 LaTeX（行内 $...$，独立 $$...$$）。
5. 不要编造页码、题号、数据。

【参考资料】
{{ context }}

【学生提问】{{ question }}
"""


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("variables_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_hint", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
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
            ["created_by"], ["users.id"], name="fk_prompt_templates_created_by"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        sa.UniqueConstraint(
            "name", "version", name="uq_prompt_templates_name_version"
        ),
    )
    op.create_index(
        "uq_prompt_templates_active_name",
        "prompt_templates",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_prompt_templates_name_created_at",
        "prompt_templates",
        ["name", "created_at"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO prompt_templates
                (name, version, content, variables_json, model_hint,
                 is_active, created_by, created_at, updated_at)
            VALUES
                (:name, :version, :content, CAST(:variables AS jsonb), NULL,
                 true, NULL, now(), now())
            """
        ).bindparams(
            name="qa",
            version="v1",
            content=QA_V1_CONTENT,
            variables=json.dumps(["context", "question"], ensure_ascii=False),
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_templates_name_created_at", table_name="prompt_templates"
    )
    op.drop_index(
        "uq_prompt_templates_active_name", table_name="prompt_templates"
    )
    op.drop_table("prompt_templates")
```

- [ ] **Step 5: 跑模型测试与迁移**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_model.py -q`
Expected: 2 passed。

Run: `cd study-agent/backend && ..\.venv\Scripts\alembic.exe upgrade head`
Expected: 输出 `Running upgrade 0005_s2_8 -> 0006_s3_4`，退出 0。

Run SQL 确认种子：

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,name,version,is_active,variables_json,created_by from prompt_templates;"
```

Expected: 一行 `qa | v1 | t | ["context", "question"] |`（created_by 空）。

- [ ] **Step 6: 全套测试**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **612 passed, 1 warning**。

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/prompt_template.py backend/app/models/__init__.py backend/alembic/versions/0006_s3_4_prompt_templates.py backend/tests/test_prompt_model.py
git commit -m "feat(s3-4): prompt_templates 表、迁移与 qa/v1 种子"
```

---

### Task 2: 文本渲染与 answerer 自定义模板

**Files:**
- Modify: `backend/app/ai/rag/prompt_builder.py`
- Modify: `backend/app/ai/rag/answerer.py`
- Test: `backend/tests/test_prompt_builder.py`
- Test: `backend/tests/test_answerer.py`

**Interfaces:**
- Produces: `render_prompt_text(template_text: str, *, context: str, question: str) -> str`；`answer_question(..., prompt_template: str | None = None)`。
- 兼容：`render_prompt(context, question, *, template_path=None)` 签名与行为不变；`prompt_template=None` 仍读 `qa_v1.md`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_prompt_builder.py` 的 import 中加 `render_prompt_text`，末尾加：

```python
def test_render_prompt_text_renders_context_and_question() -> None:
    rendered = render_prompt_text(
        "规则A\n资料：{{ context }}\n问：{{ question }}",
        context="[1] 正文",
        question="怎么用？",
    )

    assert rendered.startswith("规则A")
    assert "[1] 正文" in rendered
    assert "怎么用？" in rendered


def test_render_prompt_text_missing_variable_raises() -> None:
    with pytest.raises(PromptTemplateError):
        render_prompt_text(
            "{{ context }} / {{ missing }}",
            context="ctx",
            question="q",
        )
```

在 `backend/tests/test_answerer.py` 末尾加：

```python
def test_answer_question_uses_custom_prompt_template(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["自定义回答[1]"])

    result = answer_question(
        object(),
        "问题",
        user_id=1,
        llm_client=fake,
        prompt_template="CUSTOM-RULE\n资料：{{ context }}\n问：{{ question }}",
    )

    assert result.refused is False
    prompt = fake.calls[0][0].content
    assert "CUSTOM-RULE" in prompt
    assert "错位相减法：乘公比" in prompt
    assert "问题" in prompt


def test_answer_question_custom_template_missing_variable_raises(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["不应调用"])

    with pytest.raises(PromptTemplateError):
        answer_question(
            object(),
            "问题",
            user_id=1,
            llm_client=fake,
            prompt_template="{{ context }} / {{ missing }}",
        )

    assert fake.calls == []
```

`test_answerer.py` 需要导入 `PromptTemplateError`：

```python
from app.ai.rag.prompt_builder import PromptTemplateError
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_builder.py backend/tests/test_answerer.py -q`
Expected: FAIL —— `ImportError: cannot import name 'render_prompt_text'` 或 `unexpected keyword argument 'prompt_template'`。

- [ ] **Step 3: 实现文本渲染**

`prompt_builder.py` 在 `render_prompt` 前加：

```python
def render_prompt_text(
    template_text: str,
    *,
    context: str,
    question: str,
) -> str:
    if not template_text.strip():
        raise PromptTemplateError("Prompt 模板为空")
    env = Environment(undefined=StrictUndefined, autoescape=False)
    try:
        template = env.from_string(template_text)
        return template.render(context=context, question=question)
    except Exception as exc:
        raise PromptTemplateError("Prompt 模板渲染失败") from exc
```

把现有 `render_prompt` 替换为：

```python
def render_prompt(
    context: str,
    question: str,
    *,
    template_path: Path | None = None,
) -> str:
    path = PROMPT_PATH if template_path is None else template_path
    if not path.is_file():
        raise PromptTemplateError(f"Prompt 模板不存在：{path}")
    try:
        template_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptTemplateError(f"Prompt 模板读取失败：{path}") from exc
    return render_prompt_text(template_text, context=context, question=question)
```

- [ ] **Step 4: 实现 answerer 参数**

`answerer.py` import 加 `render_prompt_text`；`answer_question` 签名在 `llm_client` 后加 `prompt_template: str | None = None`；把 `prompt = render_prompt(built.text, question)` 改为：

```python
    if prompt_template is None:
        prompt = render_prompt(built.text, question)
    else:
        prompt = render_prompt_text(
            prompt_template,
            context=built.text,
            question=question,
        )
```

- [ ] **Step 5: 跑测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_builder.py backend/tests/test_answerer.py -q`
Expected: 全部通过（新增 4 条）。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **616 passed, 1 warning**。

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/rag/prompt_builder.py backend/app/ai/rag/answerer.py backend/tests/test_prompt_builder.py backend/tests/test_answerer.py
git commit -m "feat(s3-4): Jinja2 文本渲染与 answerer 自定义模板"
```

---

### Task 3: prompt_service 版本与激活

**Files:**
- Create: `backend/app/services/prompt_service.py`
- Test: `backend/tests/test_prompt_service.py`

**Interfaces:**
- Consumes: `PromptTemplate`、`InvalidParamError`、`NotFoundError`、`ConflictError`、`PromptTemplateError`。
- Produces:
  - `QA_PROMPT_NAME = "qa"`
  - `get_active_prompt(session, *, name=QA_PROMPT_NAME) -> PromptTemplate`
  - `list_prompts(session, *, name: str | None = None) -> list[PromptTemplate]`
  - `create_prompt_version(session, *, name, content, version=None, variables_json=None, model_hint=None, created_by=None, activate=False) -> PromptTemplate`
  - `activate_prompt(session, prompt_id: int) -> PromptTemplate`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_prompt_service.py`：

```python
"""S3-4 Prompt 服务：FakeSession，不连库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ai.rag.prompt_builder import PromptTemplateError
from app.core.exceptions import (
    ConflictError,
    InvalidParamError,
    NotFoundError,
)
from app.models.prompt_template import PromptTemplate
from app.services import prompt_service


class FakeScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def all(self) -> list[object]:
        return list(self._items)

    def first(self) -> object | None:
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object] | None = None,
        scalars_results: list[list[object]] | None = None,
        get_results: dict[int, object] | None = None,
    ) -> None:
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.get_results = dict(get_results or {})
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self.scalars_results.pop(0))

    def get(self, entity: type, pk: int) -> object | None:
        return self.get_results.get(pk)

    def add(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100 + len(self.added)  # type: ignore[attr-defined]
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, instance: object) -> None:
        return None


def _prompt(
    prompt_id: int,
    version: str,
    *,
    active: bool = False,
    name: str = "qa",
) -> PromptTemplate:
    now = datetime.now(timezone.utc)
    prompt = PromptTemplate(
        name=name,
        version=version,
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        model_hint=None,
        is_active=active,
        created_by=1,
        created_at=now,
        updated_at=now,
    )
    prompt.id = prompt_id
    return prompt


def test_create_prompt_auto_version() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="新模板 {{ context }} {{ question }}",
        created_by=1,
    )

    assert prompt.version == "v2"
    assert prompt.is_active is False
    assert session.commits == 1


def test_create_prompt_explicit_version() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="模板",
        version="v9",
        created_by=1,
    )

    assert prompt.version == "v9"


def test_create_prompt_duplicate_version_conflict() -> None:
    session = FakeSession(scalar_results=[7])

    with pytest.raises(ConflictError):
        prompt_service.create_prompt_version(
            session,
            name="qa",
            content="模板",
            version="v1",
        )


def test_create_prompt_rejects_invalid_name() -> None:
    with pytest.raises(InvalidParamError):
        prompt_service.create_prompt_version(
            FakeSession(),
            name="QA Prompt",
            content="模板",
        )


def test_create_prompt_rejects_blank_content() -> None:
    with pytest.raises(InvalidParamError):
        prompt_service.create_prompt_version(
            FakeSession(),
            name="qa",
            content="   ",
        )


def test_create_prompt_with_activate_switches_old() -> None:
    old = _prompt(1, "v1", active=True)
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"], [old]],
    )

    new = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="v2 {{ context }} {{ question }}",
        activate=True,
        created_by=1,
    )

    assert old.is_active is False
    assert new.is_active is True
    assert session.commits == 1


def test_activate_prompt_unknown_raises() -> None:
    with pytest.raises(NotFoundError):
        prompt_service.activate_prompt(FakeSession(get_results={}), 99)


def test_activate_prompt_switches_exclusive() -> None:
    old = _prompt(1, "v1", active=True)
    target = _prompt(2, "v2", active=False)
    session = FakeSession(
        get_results={2: target},
        scalars_results=[[old, target]],
    )

    result = prompt_service.activate_prompt(session, 2)

    assert result is target
    assert target.is_active is True
    assert old.is_active is False
    assert session.commits == 1


def test_list_prompts_returns_rows() -> None:
    session = FakeSession(scalars_results=[[_prompt(2, "v2"), _prompt(1, "v1")]])

    rows = prompt_service.list_prompts(session, name="qa")

    assert [row.version for row in rows] == ["v2", "v1"]


def test_get_active_prompt_returns_active() -> None:
    active = _prompt(1, "v1", active=True)
    session = FakeSession(scalars_results=[[active]])

    assert prompt_service.get_active_prompt(session) is active


def test_get_active_prompt_missing_raises() -> None:
    with pytest.raises(PromptTemplateError):
        prompt_service.get_active_prompt(FakeSession(scalars_results=[[]]))


def test_create_prompt_records_author_and_variables() -> None:
    session = FakeSession(
        scalar_results=[None],
        scalars_results=[["v1"]],
    )

    prompt = prompt_service.create_prompt_version(
        session,
        name="qa",
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        created_by=7,
    )

    assert prompt.created_by == 7
    assert prompt.variables_json == ["context", "question"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.services.prompt_service`。

- [ ] **Step 3: 实现服务**

`backend/app/services/prompt_service.py`：

```python
"""S3-4 Prompt 版本服务：读取 active、创建不可变版本、激活。

Prompt 内容/渲染在 ai/rag；本层只做 DB 状态与版本规则。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.prompt_builder import PromptTemplateError
from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.prompt_template import PromptTemplate

QA_PROMPT_NAME = "qa"
MAX_CONTENT_CHARS = 20000
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def _clean_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise InvalidParamError("Prompt name 必须匹配 ^[a-z][a-z0-9_]{0,63}$")
    return name


def _clean_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version):
        raise InvalidParamError("Prompt version 必须匹配 ^[A-Za-z0-9._-]{1,32}$")
    return version


def _clean_content(content: str) -> str:
    clean = content.strip()
    if not clean:
        raise InvalidParamError("Prompt content 不能为空")
    if len(clean) > MAX_CONTENT_CHARS:
        raise InvalidParamError(f"Prompt content 不能超过 {MAX_CONTENT_CHARS} 字")
    return clean


def _clean_variables(variables: list[str] | None) -> list[str] | None:
    if variables is None:
        return None
    cleaned = [item.strip() for item in variables]
    if any(not item for item in cleaned):
        raise InvalidParamError("Prompt variables 不能包含空字符串")
    return cleaned


def _next_version(session: Session, name: str) -> str:
    versions = session.scalars(
        select(PromptTemplate.version).where(PromptTemplate.name == name)
    ).all()
    used = set(versions)
    numbers = [
        int(match.group(1))
        for version in used
        if (match := re.fullmatch(r"v(\d+)", version))
    ]
    candidate = max(numbers, default=0) + 1
    while f"v{candidate}" in used:
        candidate += 1
    return f"v{candidate}"


def get_active_prompt(
    session: Session, *, name: str = QA_PROMPT_NAME
) -> PromptTemplate:
    prompt = session.scalars(
        select(PromptTemplate).where(
            PromptTemplate.name == name,
            PromptTemplate.is_active.is_(True),
        )
    ).first()
    if prompt is None:
        raise PromptTemplateError(f"Prompt 未启用：{name}")
    return prompt


def list_prompts(
    session: Session, *, name: str | None = None
) -> list[PromptTemplate]:
    statement = select(PromptTemplate).order_by(
        PromptTemplate.created_at.desc(), PromptTemplate.id.desc()
    )
    if name is not None:
        statement = statement.where(PromptTemplate.name == _clean_name(name))
    return list(session.scalars(statement).all())


def create_prompt_version(
    session: Session,
    *,
    name: str,
    content: str,
    version: str | None = None,
    variables_json: list[str] | None = None,
    model_hint: str | None = None,
    created_by: int | None = None,
    activate: bool = False,
) -> PromptTemplate:
    clean_name = _clean_name(name)
    clean_content = _clean_content(content)
    clean_variables = _clean_variables(variables_json)
    clean_hint = model_hint.strip() if model_hint else None
    if clean_hint is not None and len(clean_hint) > 100:
        raise InvalidParamError("Prompt model_hint 不能超过 100 字")

    if version is None:
        clean_version = _next_version(session, clean_name)
    else:
        clean_version = _clean_version(version)
        exists = session.scalar(
            select(PromptTemplate.id).where(
                PromptTemplate.name == clean_name,
                PromptTemplate.version == clean_version,
            )
        )
        if exists is not None:
            raise ConflictError("Prompt 版本已存在")

    if activate:
        rows = session.scalars(
            select(PromptTemplate).where(PromptTemplate.name == clean_name)
        ).all()
        for row in rows:
            row.is_active = False

    prompt = PromptTemplate(
        name=clean_name,
        version=clean_version,
        content=clean_content,
        variables_json=clean_variables,
        model_hint=clean_hint,
        is_active=activate,
        created_by=created_by,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def activate_prompt(session: Session, prompt_id: int) -> PromptTemplate:
    target = session.get(PromptTemplate, prompt_id)
    if target is None:
        raise NotFoundError("Prompt 版本不存在")

    rows = session.scalars(
        select(PromptTemplate).where(PromptTemplate.name == target.name)
    ).all()
    for row in rows:
        row.is_active = row.id == target.id
    target.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(target)
    return target
```

- [ ] **Step 4: 跑测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_service.py -q`
Expected: 12 passed。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **628 passed, 1 warning**。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/prompt_service.py backend/tests/test_prompt_service.py
git commit -m "feat(s3-4): Prompt 版本服务与激活逻辑"
```

---

### Task 4: 管理接口

**Files:**
- Create: `backend/app/schemas/prompt.py`
- Modify: `backend/app/api/v1/admin.py`
- Test: `backend/tests/test_prompt_admin_api.py`

**Interfaces:**
- Consumes: `prompt_service.list_prompts/create_prompt_version/activate_prompt`。
- Produces: `GET /api/v1/admin/prompts`、`POST /api/v1/admin/prompts`（201）、`PUT /api/v1/admin/prompts/{id}/activate`。

- [ ] **Step 1: 写出参/入参**

`backend/app/schemas/prompt.py`：

```python
"""S3-4 Prompt 管理出入参（API.md §11）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
VERSION_PATTERN = r"^[A-Za-z0-9._-]{1,32}$"


class PromptCreate(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    content: str = Field(min_length=1, max_length=20000)
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)
    variables_json: list[str] | None = None
    model_hint: str | None = Field(default=None, max_length=100)
    activate: bool = False

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content 不能为空")
        return value

    @field_validator("variables_json")
    @classmethod
    def _variables_not_blank(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("variables_json 不能包含空字符串")
        return value


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    content: str
    variables_json: list[str] | None
    model_hint: str | None
    is_active: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: 写失败接口测试**

`backend/tests/test_prompt_admin_api.py`：

```python
"""S3-4 Prompt 管理接口：TestClient + FakeSession/服务替身。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.prompt_template import PromptTemplate
from app.models.user import User
from app.services import prompt_service


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")


def _user(user_id: int = 1, *, role: str = "admin", username: str = "admin_1") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade=None,
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _prompt(
    prompt_id: int, version: str, *, active: bool = False
) -> PromptTemplate:
    now = datetime.now(timezone.utc)
    prompt = PromptTemplate(
        name="qa",
        version=version,
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        model_hint=None,
        is_active=active,
        created_by=1,
        created_at=now,
        updated_at=now,
    )
    prompt.id = prompt_id
    return prompt


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


def test_list_prompts_requires_admin(client: TestClient) -> None:
    teacher = _user(2, role="teacher", username="teacher_1")
    _override(FakeSession(user=teacher))

    resp = client.get("/api/v1/admin/prompts", headers=_headers(teacher))

    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_prompts_requires_token(client: TestClient) -> None:
    _override(FakeSession())

    resp = client.get("/api/v1/admin/prompts")

    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_list_prompts_returns_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "list_prompts",
        lambda session, *, name: [_prompt(2, "v2"), _prompt(1, "v1", active=True)],
    )

    resp = client.get("/api/v1/admin/prompts?name=qa", headers=_headers(admin))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [item["version"] for item in data] == ["v2", "v1"]
    assert data[1]["is_active"] is True


def test_create_prompt_returns_201(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    captured: dict[str, object] = {}

    def fake_create(session, **kwargs):
        captured.update(kwargs)
        return _prompt(2, "v2", active=True)

    monkeypatch.setattr(prompt_service, "create_prompt_version", fake_create)

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={
            "name": "qa",
            "content": "模板 {{ context }} {{ question }}",
            "version": "v2",
            "variables_json": ["context", "question"],
            "activate": True,
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["version"] == "v2"
    assert captured["created_by"] == admin.id
    assert captured["activate"] is True


def test_create_prompt_duplicate_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, **kwargs):
        raise ConflictError("Prompt 版本已存在")

    monkeypatch.setattr(prompt_service, "create_prompt_version", fail)

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={"name": "qa", "content": "模板", "version": "v1"},
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_create_prompt_invalid_body_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "create_prompt_version",
        lambda session, **kwargs: pytest.fail("service 不应被调用"),
    )

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={"name": "qa", "content": "   "},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_activate_prompt_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "activate_prompt",
        lambda session, prompt_id: _prompt(prompt_id, "v2", active=True),
    )

    resp = client.put(
        "/api/v1/admin/prompts/2/activate", headers=_headers(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is True


def test_activate_prompt_unknown_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, prompt_id):
        raise NotFoundError("Prompt 版本不存在")

    monkeypatch.setattr(prompt_service, "activate_prompt", fail)

    resp = client.put(
        "/api/v1/admin/prompts/99/activate", headers=_headers(admin)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 40400
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_admin_api.py -q`
Expected: FAIL —— 接口 404 或响应结构不符。

- [ ] **Step 4: 实现路由**

`backend/app/api/v1/admin.py` 导入：

```python
from app.schemas.prompt import PromptCreate, PromptTemplateOut
from app.services import prompt_service
```

文件末尾加：

```python
@router.get(
    "/prompts",
    response_model=Envelope[list[PromptTemplateOut]],
    summary="查询 Prompt 版本历史",
)
def list_prompt_templates(
    name: str | None = None,
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[list[PromptTemplateOut]]:
    rows = prompt_service.list_prompts(session, name=name)
    data = [PromptTemplateOut.model_validate(row) for row in rows]
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post(
    "/prompts",
    status_code=201,
    response_model=Envelope[PromptTemplateOut],
    summary="新建 Prompt 版本（不可变）",
)
def create_prompt_template(
    payload: PromptCreate,
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[PromptTemplateOut]:
    prompt = prompt_service.create_prompt_version(
        session,
        name=payload.name,
        content=payload.content,
        version=payload.version,
        variables_json=payload.variables_json,
        model_hint=payload.model_hint,
        created_by=current_user.id,
        activate=payload.activate,
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=PromptTemplateOut.model_validate(prompt),
    )


@router.put(
    "/prompts/{prompt_id}/activate",
    response_model=Envelope[PromptTemplateOut],
    summary="启用指定 Prompt 版本",
)
def activate_prompt_template(
    prompt_id: int = Path(..., ge=1, description="Prompt 版本 id"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[PromptTemplateOut]:
    prompt = prompt_service.activate_prompt(session, prompt_id)
    return Envelope(
        trace_id=get_trace_id(),
        data=PromptTemplateOut.model_validate(prompt),
    )
```

- [ ] **Step 5: 跑接口测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_prompt_admin_api.py -q`
Expected: 8 passed。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **636 passed, 1 warning**。

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/prompt.py backend/app/api/v1/admin.py backend/tests/test_prompt_admin_api.py
git commit -m "feat(s3-4): Prompt 版本管理接口"
```

---

### Task 5: 脚本接入、真实验收与文档

**Files:**
- Modify: `scripts/ask.py`
- Modify: `docs/API.md`、`docs/SCHEMA.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-4-prompt-management.md`、`docs/plan/s3-4-prompt-management.md`
- 不改：前端、`.env.example`（无新配置）

**Interfaces:**
- Consumes: `prompt_service.get_active_prompt`、`answer_question(prompt_template=...)`。
- Produces: `scripts/ask.py` 输出 `Prompt：qa/vN`，问答立即使用库中 active。

- [ ] **Step 1: 改 ask.py**

导入加：

```python
from app.services import prompt_service
```

`_print_result` 签名加 `prompt_label: str | None = None`，在统计前打印：

```python
    if prompt_label:
        print(f"\nPrompt：{prompt_label}")
```

`_ask_one` 的 `with new_session() as session:` 内改为：

```python
            active = prompt_service.get_active_prompt(
                session, name=prompt_service.QA_PROMPT_NAME
            )
            result = answer_question(
                session,
                question,
                user_id=user_id,
                top_k=top_k,
                threshold=threshold,
                prompt_template=active.content,
            )
            _print_result(
                question,
                result,
                debug=debug,
                prompt_label=f"{active.name}/{active.version}",
            )
```

- [ ] **Step 2: 语法与基线**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m py_compile scripts/ask.py`
Expected: 退出 0。

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/ask.py --user-id 18 "错位相减法怎么用" 2>&1 | Select-Object -Last 12`
Expected: 正常回答，末尾出现 `Prompt：qa/v1`。

- [ ] **Step 3: 通过真实 HTTP 建 v2 并启用**

临时脚本 `.s34_accept.py`（验收后删除）：

```python
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.core.db import new_session
from app.core.security import create_access_token
from app.main import app
from app.models.prompt_template import PromptTemplate
from app.models.user import User

with new_session() as session:
    admin = session.scalars(
        select(User).where(User.username == "prompt_admin_tmp")
    ).first()
    if admin is None:
        admin = User(
            username="prompt_admin_tmp",
            password_hash="tmp",
            nickname="临时 Prompt 管理员",
            role="admin",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
    token = create_access_token(user_id=admin.id, role="admin").token
    v1 = session.scalars(
        select(PromptTemplate).where(
            PromptTemplate.name == "qa", PromptTemplate.version == "v1"
        )
    ).first()
    v1_content = v1.content

client = TestClient(app)
headers = {"Authorization": f"Bearer {token}"}
v2_content = v1_content + "\n\n回答末尾必须写【PROMPT-V2】。"
resp = client.post(
    "/api/v1/admin/prompts",
    headers=headers,
    json={
        "name": "qa",
        "content": v2_content,
        "variables_json": ["context", "question"],
        "activate": True,
    },
)
resp.raise_for_status()
print(json.dumps(resp.json()["data"], ensure_ascii=False))
```

Run:

```bash
cd study-agent
.\.venv\Scripts\python.exe .s34_accept.py
```

Expected: 201；返回 `version` 为 `v2`、`is_active=true`。记录返回的 `v2 id`。

- [ ] **Step 4: 验证立即生效**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/ask.py --user-id 18 "错位相减法怎么用" 2>&1 | Select-Object -Last 14`
Expected: 回答末尾有【PROMPT-V2】，并打印 `Prompt：qa/v2`。

- [ ] **Step 5: 查历史并切回 v1**

新建 `.s34_activate.py`（不要重复执行 Step 3 的创建段，避免多建版本）：

```python
import sys
from datetime import datetime, timezone

sys.path.insert(0, "backend")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import new_session
from app.core.security import create_access_token
from app.main import app
from app.models.user import User

with new_session() as session:
    admin = session.scalars(
        select(User).where(User.username == "prompt_admin_tmp")
    ).first()
    token = create_access_token(user_id=admin.id, role="admin").token

client = TestClient(app)
headers = {"Authorization": f"Bearer {token}"}
resp = client.get("/api/v1/admin/prompts?name=qa", headers=headers)
resp.raise_for_status()
rows = resp.json()["data"]
print([(row["version"], row["is_active"]) for row in rows])
v1_id = next(row["id"] for row in rows if row["version"] == "v1")
resp = client.put(f"/api/v1/admin/prompts/{v1_id}/activate", headers=headers)
resp.raise_for_status()
print(resp.json()["data"]["version"], resp.json()["data"]["is_active"])
```

Run: `.\.venv\Scripts\python.exe .s34_activate.py`
Expected: 历史含 `('v2', False)` 与 `('v1', True)`；激活返回 `v1 true`。

- [ ] **Step 6: 再次问答确认标记消失**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/ask.py --user-id 18 "错位相减法怎么用" 2>&1 | Select-Object -Last 14`
Expected: 无【PROMPT-V2】，`Prompt：qa/v1`。

- [ ] **Step 7: 清理临时管理员**

新建 `.s34_cleanup.py`：

```python
import sys

sys.path.insert(0, "backend")

from sqlalchemy import delete, select, update

from app.core.db import new_session
from app.models.prompt_template import PromptTemplate
from app.models.user import User

with new_session() as session:
    admin = session.scalars(
        select(User).where(User.username == "prompt_admin_tmp")
    ).first()
    if admin is not None:
        session.execute(
            update(PromptTemplate)
            .where(PromptTemplate.created_by == admin.id)
            .values(created_by=None)
        )
        session.execute(delete(User).where(User.id == admin.id))
        session.commit()
```

Run: `.\.venv\Scripts\python.exe .s34_cleanup.py`
Expected: 退出 0；`select count(*) from users where username='prompt_admin_tmp'` 为 0。删除 `.s34_accept.py`、`.s34_activate.py`、`.s34_cleanup.py`；v2 保留为 inactive 历史。

- [ ] **Step 8: 全套测试**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **636 passed, 1 warning**。

- [ ] **Step 9: 文档同步**

- `docs/API.md` §11 加 `GET/POST /admin/prompts`、`PUT /admin/prompts/{id}/activate`（权限、入出参、错误）。
- `docs/SCHEMA.md` §8.3 补 `created_at/updated_at`、唯一/部分唯一索引、FK。
- `docs/DECISIONS.md` 追加 **D-038**：表/不可变版本/active 唯一/种子/读取链路/校验/实测。
- `docs/PROGRESS.md`：状态改 S3-4 完成、勾选 S3-4、下一步 S3-5、变更日志与遗留问题（无删除接口、无审核、无缓存、rewrite/kp 未迁）。
- `AGENTS.md` §9.2 加 Prompt 管理约束；§9.6 加「Prompt 模板样例」锚点。
- `docs/AI协作开发实施计划.md` 勾选 S3-4。
- `docs/spec/s3-4-prompt-management.md` 补实测小节与实施记录（§12）。
- `docs/plan/s3-4-prompt-management.md` 填 Execution Record。
- 不改 API.md 其它接口/SCHEMA 其它表/前端。

- [ ] **Step 10: 提交**

```bash
git add scripts/ask.py docs/API.md docs/SCHEMA.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md docs/AI协作开发实施计划.md docs/spec/s3-4-prompt-management.md docs/plan/s3-4-prompt-management.md
git commit -m "docs(s3-4): Prompt 版本管理验收记录与文档同步"
```

---

## Self-Review

- **Spec coverage**：表/迁移/种子 §4/§8 → Task 1；Jinja2 文本渲染与 answerer §5 → Task 2；服务 §6 → Task 3；接口 §7 → Task 4；脚本/验收 §10 → Task 5；限制 §11 → 文档。
- **类型一致性**：`PromptTemplate` 字段在 Task 1 定义，Task 3/4 使用；`render_prompt_text` Task 2 定义，Task 2/5 使用；`create_prompt_version` 的 `version/created_by/activate` 与 API 传参一致；`PromptTemplateOut` 与 ORM 字段一致。
- **占位扫描**：无 TBD/TODO；未用“类似 Task N”；测试/实现代码均给出。
- **风险**：真实 v2 标记依赖 LLM 遵循末尾指令；若未出现，检查模板是否真的 active（`Prompt：qa/v2`）并原样记录，不改判定。迁移种子内容与 `qa_v1.md` 重复，后续若改文件不会同步；以库为准。

## Execution Record

- 执行方式：本会话内联执行（用户确认 plan 后）。
- 提交：`3a7aaad` → `a8b097a` → `4282bc4` → `8193ada` → `226a65f`（修复）→ `b1345e9`；未 push。
- 结果：全量 **636 passed, 1 warning**（基线 610）；`qa/v1` 种子、Jinja2 渲染、service、admin 三接口、ask.py 均落地。
- 偏差 1：迁移 cwd 是 `backend/`，命令改为 `cd study-agent/backend && ..\.venv\Scripts\alembic.exe upgrade head`。
- 偏差 2：首次真实激活触发部分唯一索引冲突；service 改为“全部停用 → flush → 启用目标”，并给 `test_activate_prompt_switches_exclusive` 加 flush 断言；契约不变。
- 验收：v1 基线 → v2 标记出现 → 切回 v1 标记消失；历史 v1 active / v2 inactive；临时 admin 清理；详见 spec §12。