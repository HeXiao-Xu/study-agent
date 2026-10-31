# S3-5 QA SSE + 会话落库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `POST /api/v1/qa/ask` 先落 user 消息、再逐 token SSE 输出，正常结束落 assistant 与 citations，并提供本人消息引用查询。

**Architecture:** LLM 层新增真实 `chat_stream`；answerer 拆成 `prepare_answer`（检索/阈值/上下文/Prompt）与 `stream_answer`（流式 LLM）；`qa_service` 编排会话、历史、改写、scope、落库与 SSE 事件；路由只做鉴权、参数和 `StreamingResponse`。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、httpx、tiktoken、pytest；不新增依赖。

**Spec:** `docs/spec/s3-5-qa-sse.md`

## Global Constraints

- 不改历史迁移；新迁移只能是 `0007_s3_5`，down_revision `0006_s3_4`。
- 不新增依赖；不加 Redis/缓存/限流；不改前端；不做会话列表/删除/重命名；不做 S3-6 引用校验重试、S3-7 调用日志。
- LLM/Embedding/Rerank 外部调用在测试中全部 mock；pytest 全绿才提交。
- 路由 ≤30 行；业务错误用 `AppError` 子类；DB 查询显式带 `user_id`；禁止循环查库。
- conversation_id 对外是十进制字符串，服务层转 int；message_id 对外是 int。
- SSE 事件顺序：`meta`（一次）→ `delta`（0..N）→ `done`（一次）；流中异常用 `error`，不再发 `done`。
- 断连保留 user 消息，不落 assistant；流正常结束才落 assistant + citations。
- 新增/改接口同步 `docs/API.md`，新增表同步 `docs/SCHEMA.md`；`deploy/README.md` 必须写 Nginx `proxy_buffering off`。
- Conventional Commits 带 `(s3-5)`；`git push` 由用户执行；真实数字必须来自实跑。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/models/enums.py` | 修改 | 加 `MessageRole` |
| `backend/app/models/conversation.py` | 新建 | `conversations` ORM |
| `backend/app/models/message.py` | 新建 | `messages` ORM + role CHECK |
| `backend/app/models/message_citation.py` | 新建 | `message_citations` ORM |
| `backend/app/models/__init__.py` | 修改 | 注册三个模型 |
| `backend/alembic/versions/0007_s3_5_conversations.py` | 新建 | 三表、索引、FK、CHECK |
| `backend/app/schemas/qa.py` | 新建 | 请求/scope/SSE data/引用出参 |
| `backend/app/ai/llm/base.py` | 修改 | `LLMStreamChunk` + 默认 `chat_stream` |
| `backend/app/ai/llm/openai_compat.py` | 修改 | 真实 SSE 解析、usage、重试边界 |
| `backend/app/ai/llm/__init__.py` | 修改 | 导出 `LLMStreamChunk` |
| `backend/app/ai/rag/answerer.py` | 修改 | `PreparedAnswer` + `prepare_answer` + `stream_answer` |
| `backend/app/services/qa_service.py` | 新建 | 会话/历史/改写/落库/SSE 编排 |
| `backend/app/api/v1/qa.py` | 新建 | 两个接口 + SSE 序列化 |
| `backend/app/api/router.py` | 修改 | include qa router |
| `backend/tests/test_qa_models.py` | 新建 | 模型契约 |
| `backend/tests/test_llm_stream.py` | 新建 | 流式适配器 |
| `backend/tests/test_answerer.py` | 修改 | prepare/stream |
| `backend/tests/test_qa_service.py` | 新建 | 会话/落库/断连 |
| `backend/tests/test_qa_api.py` | 新建 | SSE/鉴权/引用接口 |
| `docs/API.md`、`docs/SCHEMA.md`、`docs/PROGRESS.md`、`docs/DECISIONS.md`、`docs/AI协作开发实施计划.md`、`deploy/README.md` | 修改 | 契约、进度、决策、任务卡、Nginx |

---

### Task 1: 三张表、ORM 与迁移 `0007_s3_5`

**Files:**
- Modify: `backend/app/models/enums.py`
- Create: `backend/app/models/conversation.py`
- Create: `backend/app/models/message.py`
- Create: `backend/app/models/message_citation.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0007_s3_5_conversations.py`
- Test: `backend/tests/test_qa_models.py`

**Interfaces:**
- Produces: `Conversation(id,user_id,title,scope_json,created_at)`；`Message(id,conversation_id,role,content_md,token_usage,latency_ms,model,prompt_version,created_at)`；`MessageCitation(id,message_id,chunk_id,question_id,note_id,score,snippet,page_no,bbox_json,rank)`；`MessageRole` 枚举。
- 后续任务用：`Conversation.id/user_id/title/scope_json`；`Message.id/conversation_id/role/content_md/token_usage/latency_ms/model/prompt_version`；`MessageCitation.*`。

- [ ] **Step 1: 写失败的模型测试**

`backend/tests/test_qa_models.py`：

```python
"""S3-5 会话/消息/引用模型契约（不连库）。"""
from __future__ import annotations

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation


def test_conversation_columns_and_index() -> None:
    table = Conversation.__table__
    assert {
        "id",
        "user_id",
        "title",
        "scope_json",
        "created_at",
    } <= set(table.c.keys())
    assert table.c.id.primary_key is True
    assert table.c.user_id.nullable is False
    assert table.c.title.nullable is True
    assert isinstance(table.c.scope_json.type, JSONB)
    assert table.c.scope_json.nullable is True
    assert table.c.created_at.nullable is False
    assert any(index.name == "ix_conversations_user_id" for index in table.indexes)
    assert table.c.user_id.foreign_keys


def test_message_columns_role_check_and_index() -> None:
    table = Message.__table__
    assert {
        "id",
        "conversation_id",
        "role",
        "content_md",
        "token_usage",
        "latency_ms",
        "model",
        "prompt_version",
        "created_at",
    } <= set(table.c.keys())
    assert table.c.conversation_id.nullable is False
    assert table.c.role.nullable is False
    assert table.c.content_md.nullable is False
    assert isinstance(table.c.token_usage.type, JSONB)
    assert table.c.latency_ms.nullable is True
    assert table.c.model.nullable is True
    assert table.c.prompt_version.nullable is True
    assert any(index.name == "ix_messages_conversation_id" for index in table.indexes)
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_messages_role" in checks
    assert table.c.conversation_id.foreign_keys


def test_message_citation_columns_and_index() -> None:
    table = MessageCitation.__table__
    assert {
        "id",
        "message_id",
        "chunk_id",
        "question_id",
        "note_id",
        "score",
        "snippet",
        "page_no",
        "bbox_json",
        "rank",
    } <= set(table.c.keys())
    assert table.c.message_id.nullable is False
    assert table.c.chunk_id.nullable is True
    assert table.c.note_id.nullable is True
    assert table.c.score.nullable is True
    assert table.c.snippet.nullable is True
    assert table.c.page_no.nullable is True
    assert isinstance(table.c.bbox_json.type, JSONB)
    assert table.c.bbox_json.nullable is True
    assert table.c.rank.nullable is True
    assert any(
        index.name == "ix_message_citations_message_id" for index in table.indexes
    )
    assert table.c.message_id.foreign_keys
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_models.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.models.conversation`。

- [ ] **Step 3: 实现枚举与三个模型**

`backend/app/models/enums.py` 追加：

```python
class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
```

`backend/app/models/conversation.py`：

```python
"""S3-5 会话：SCHEMA §7.1。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_conversations_user_id"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

`backend/app/models/message.py`：

```python
"""S3-5 消息：SCHEMA §7.2。"""
from __future__ import annotations

from datetime import datetime

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import MessageRole, in_check


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(in_check("role", MessageRole), name="ck_messages_role"),
        Index("ix_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "conversations.id",
            name="fk_messages_conversation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    token_usage: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

`backend/app/models/message_citation.py`：

```python
"""S3-5 消息引用：SCHEMA §7.3。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (Index("ix_message_citations_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "messages.id",
            name="fk_message_citations_message_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`backend/app/models/__init__.py` 加：

```python
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation
```

并把 `"Conversation"`, `"Message"`, `"MessageCitation"` 加进 `__all__`。

- [ ] **Step 4: 写迁移**

`backend/alembic/versions/0007_s3_5_conversations.py`：

```python
"""S3-5 conversations/messages/message_citations

Revision ID: 0007_s3_5
Revises: 0006_s3_4
Create Date: 2026-10-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_s3_5"
down_revision = "0006_s3_4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "token_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_messages_role"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "message_citations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("question_id", sa.BigInteger(), nullable=True),
        sa.Column("note_id", sa.BigInteger(), nullable=True),
        sa.Column("score", sa.Numeric(6, 4), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column(
            "bbox_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_message_citations_message_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_citations"),
    )
    op.create_index(
        "ix_message_citations_message_id", "message_citations", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_citations_message_id", table_name="message_citations"
    )
    op.drop_table("message_citations")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
```

- [ ] **Step 5: 跑模型测试、迁移与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_models.py -q`
Expected: `3 passed`。

Run: `cd study-agent/backend && ..\.venv\Scripts\alembic.exe upgrade head`
Expected: 输出 `Running upgrade 0006_s3_4 -> 0007_s3_5`，退出 0。

Run SQL：

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "\dt conversations"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d messages"
docker exec study-agent-postgres psql -U study -d study_agent -c "\d message_citations"
```

Expected: 三表存在；`ck_messages_role`、两个 FK、三个索引可见；`conversations` 的 `user_id` FK 指向 `users.id`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **639 passed, 1 warning**（636 + 3）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/enums.py backend/app/models/conversation.py backend/app/models/message.py backend/app/models/message_citation.py backend/app/models/__init__.py backend/alembic/versions/0007_s3_5_conversations.py backend/tests/test_qa_models.py
git commit -m "feat(s3-5): conversations/messages/message_citations 表与迁移"
```

---

### Task 2: LLM `chat_stream` 与真实 SSE

**Files:**
- Modify: `backend/app/ai/llm/base.py`
- Modify: `backend/app/ai/llm/openai_compat.py`
- Modify: `backend/app/ai/llm/__init__.py`
- Test: `backend/tests/test_llm_stream.py`

**Interfaces:**
- Consumes: 现有 `LLMMessage`、`LLMResponse`、`LLMError`。
- Produces: `LLMStreamChunk(text: str = "", response: LLMResponse | None = None)`；`LLMClient.chat_stream(...) -> Iterator[LLMStreamChunk]`；`OpenAICompatibleLLMClient.chat_stream` 真实解析 SSE。
- 默认实现保证现有只实现 `chat()` 的 Fake/SDK 仍可被 `stream_answer` 使用。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_llm_stream.py`：

```python
"""S3-5 LLM 流式适配器：httpx.MockTransport，禁止真实网络。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.llm import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponse,
    LLMStreamChunk,
    OpenAICompatibleLLMClient,
)


def _sse(*chunks: dict) -> bytes:
    return b"".join(
        f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        for chunk in chunks
    ) + b"data: [DONE]\n\n"


def _client(handler, **kwargs) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


class FakeChatOnly(LLMClient):
    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        return LLMResponse(
            text="完整回答",
            model="fake",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
            latency_ms=3,
            cost_yuan=0.00001,
        )


def test_chat_stream_default_falls_back_to_one_chunk() -> None:
    chunks = list(FakeChatOnly(model="fake").chat_stream([LLMMessage("user", "问")]))

    assert chunks[0].text == "完整回答"
    assert chunks[0].response is None
    assert chunks[1].text == ""
    assert chunks[1].response is not None
    assert chunks[1].response.total_tokens == 14


def test_chat_stream_parses_deltas_and_usage() -> None:
    body = _sse(
        {"choices": [{"delta": {"content": "答"}}]},
        {"choices": [{"delta": {"content": "[1]"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=body)

    chunks = list(
        _client(handler).chat_stream(
            [LLMMessage("user", "问题")], temperature=0.1, max_tokens=200
        )
    )

    assert "".join(chunk.text for chunk in chunks) == "答[1]"
    final = chunks[-1].response
    assert final is not None
    assert final.model == "qwen-plus"
    assert final.prompt_tokens == 100
    assert final.completion_tokens == 20
    assert final.total_tokens == 120
    assert final.cost_yuan == pytest.approx(0.00012)
    payload = json.loads(captured[0].content)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 200


def test_chat_stream_estimates_usage_when_missing() -> None:
    body = _sse({"choices": [{"delta": {"content": "没有 usage"}}]})
    chunks = list(
        _client(lambda request: httpx.Response(200, content=body)).chat_stream(
            [LLMMessage("user", "问题")]
        )
    )

    final = chunks[-1].response
    assert final is not None
    assert final.prompt_tokens > 0
    assert final.completion_tokens > 0
    assert final.total_tokens == final.prompt_tokens + final.completion_tokens
    assert final.cost_yuan > 0


def test_chat_stream_retries_500_before_first_delta() -> None:
    calls = 0
    body = _sse({"choices": [{"delta": {"content": "答"}}]})

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(200, content=body)

    chunks = list(
        _client(handler).chat_stream([LLMMessage("user", "问题")])
    )

    assert calls == 2
    assert "".join(chunk.text for chunk in chunks) == "答"


def test_chat_stream_does_not_retry_after_delta() -> None:
    calls = 0
    body = (
        b'data: {"choices":[{"delta":{"content":"\xe7\xad\x94"}}]}\n\n'
        b"data: {broken-json}\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=body)

    stream = _client(handler).chat_stream([LLMMessage("user", "问题")])
    assert next(stream).text == "答"
    with pytest.raises(LLMError):
        next(stream)
    assert calls == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_stream.py -q`
Expected: FAIL —— `ImportError: cannot import name 'LLMStreamChunk'`。

- [ ] **Step 3: 实现 base 契约**

`backend/app/ai/llm/base.py`：

```python
"""S1-6 LLM 契约：Answerer 只依赖本文件，不直接依赖 httpx/厂商。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0


@dataclass(frozen=True)
class LLMStreamChunk:
    """流式片段：text 为增量；response 只在最后一块出现。"""

    text: str = ""
    response: LLMResponse | None = None


class LLMClient(ABC):
    def __init__(self, *, model: str) -> None:
        self.model = model
        self.usage_tokens = 0
        self.request_count = 0

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> LLMResponse:
        """发送一轮对话；网络重试由实现负责，逻辑重试由调用方负责。"""

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> Iterator[LLMStreamChunk]:
        """默认降级：不支持流式的 Client 只产出一次完整文本 + 最终响应。"""
        response = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            scene=scene,
        )
        if response.text:
            yield LLMStreamChunk(text=response.text)
        yield LLMStreamChunk(response=response)
```

- [ ] **Step 4: 实现 OpenAI 兼容 SSE**

修改 `backend/app/ai/llm/openai_compat.py`：把 `chat` 的 payload 构造抽成 `_build_payload`，并新增 `chat_stream`。

在 import 区加：

```python
from collections.abc import Iterator

import tiktoken
```

`chat` 内 payload 改为：

```python
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
```

新增方法（放在 `chat` 之后、`_post_with_retry` 之前）：

```python
    def _build_payload(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
        }
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> Iterator[LLMStreamChunk]:
        if not messages:
            raise ValueError("messages 不能为空")
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        started = time.perf_counter()
        texts: list[str] = []
        usage: dict[str, Any] | None = None
        emitted = False
        attempt = 0

        while True:
            try:
                with self._client.stream(
                    "POST",
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        status = response.status_code
                        raise LLMError(
                            f"LLM 流式请求失败：HTTP {status}",
                            status_code=status,
                            retryable=status in _RETRYABLE_STATUS,
                        )
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except ValueError as exc:
                            raise LLMError(
                                "LLM 流式返回非 JSON", retryable=False
                            ) from exc
                        if not isinstance(data, dict):
                            raise LLMError("LLM 流式块不是对象", retryable=False)
                        chunk_usage = data.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage
                        for choice in data.get("choices") or []:
                            if not isinstance(choice, dict):
                                continue
                            delta = choice.get("delta")
                            if not isinstance(delta, dict):
                                continue
                            content = delta.get("content")
                            if not isinstance(content, str) or not content:
                                continue
                            emitted = True
                            texts.append(content)
                            yield LLMStreamChunk(text=content)
                break
            except LLMError as exc:
                if emitted or attempt >= self._max_retries or not exc.retryable:
                    raise
                attempt += 1
                self._sleep(self._backoff(attempt - 1, None))
            except httpx.HTTPError as exc:
                if emitted or attempt >= self._max_retries:
                    raise LLMError(
                        f"LLM 流式网络错误（重试耗尽）：{type(exc).__name__}",
                        retryable=True,
                    ) from exc
                attempt += 1
                self._sleep(self._backoff(attempt - 1, None))

        text = "".join(texts)
        prompt_tokens, completion_tokens, total_tokens = self._stream_usage(
            usage, messages, text
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        cost = (
            prompt_tokens * self._price_in / 1_000_000
            + completion_tokens * self._price_out / 1_000_000
        )
        self.usage_tokens += total_tokens
        self.request_count += 1
        logger.info(
            "llm_call",
            extra={
                "scene": scene,
                "model": self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "cost_yuan": round(cost, 8),
                "stream": True,
            },
        )
        yield LLMStreamChunk(
            response=LLMResponse(
                text=text,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_yuan=cost,
            )
        )

    @staticmethod
    def _stream_usage(
        usage: dict[str, Any] | None,
        messages: list[LLMMessage],
        text: str,
    ) -> tuple[int, int, int]:
        if usage is not None:
            return OpenAICompatibleLLMClient._parse_usage({"usage": usage})
        encoding = tiktoken.get_encoding("cl100k_base")
        prompt_tokens = len(
            encoding.encode("\n".join(message.content for message in messages))
        )
        completion_tokens = len(encoding.encode(text))
        return prompt_tokens, completion_tokens, prompt_tokens + completion_tokens
```

- [ ] **Step 5: 导出契约**

`backend/app/ai/llm/__init__.py`：

```python
from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse, LLMStreamChunk
```

并把 `"LLMStreamChunk"` 加进 `__all__`。

- [ ] **Step 6: 跑测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_stream.py -q`
Expected: `5 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_llm.py backend/tests/test_answerer.py -q`
Expected: 全绿（`chat` 行为无回归）。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **644 passed, 1 warning**（639 + 5）。

- [ ] **Step 7: 提交**

```bash
git add backend/app/ai/llm/base.py backend/app/ai/llm/openai_compat.py backend/app/ai/llm/__init__.py backend/tests/test_llm_stream.py
git commit -m "feat(s3-5): LLM chat_stream 真实 SSE 与默认降级"
```

---

### Task 3: answerer 拆分 `prepare_answer` / `stream_answer`

**Files:**
- Modify: `backend/app/ai/rag/answerer.py`
- Test: `backend/tests/test_answerer.py`

**Interfaces:**
- Consumes: `LLMClient.chat_stream`、`LLMStreamChunk`、现有 `retrieve_hybrid_reranked`、`build_context`。
- Produces: `PreparedAnswer(retrieval,built,prompt,refused,retrieval_ms,top_score,degraded)`；`prepare_answer(...)`；`AnswerChunk(text,response)`；`stream_answer(prepared,*,llm_client=None)`。
- `answer_question` 签名增加可选 `scope`、`retrieval_query`，默认行为不变。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_answerer.py` 的 import 加：

```python
from app.ai.llm.base import LLMStreamChunk
from app.ai.rag.answerer import AnswerChunk, PreparedAnswer, prepare_answer, stream_answer
from app.ai.rag.retriever import RetrievalScope
```

末尾追加：

```python
class FakeStreamLLM(FakeLLM):
    def chat_stream(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append(messages)
        for text in self.texts:
            yield LLMStreamChunk(text=text)
        yield LLMStreamChunk(
            response=LLMResponse(
                text="".join(self.texts),
                model="fake",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                latency_ms=1,
                cost_yuan=0.00001,
            )
        )


def test_prepare_answer_refuses_no_context_without_llm(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([]))
    prepared = prepare_answer(object(), "问题", user_id=1)

    assert prepared.refused is not None
    assert prepared.refused.refusal_reason == "no_context"
    assert prepared.built is None
    assert prepared.prompt == ""


def test_prepare_answer_uses_scope_and_retrieval_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_retrieve(session, query, **kwargs):
        captured["query"] = query
        captured["scope"] = kwargs.get("scope")
        return _retrieval([_chunk()])

    monkeypatch.setattr(answerer, "retrieve_hybrid_reranked", fake_retrieve)
    scope = RetrievalScope(subject_id=7)
    prepared = prepare_answer(
        object(),
        "那它的前提呢？",
        user_id=1,
        scope=scope,
        retrieval_query="错位相减法的前提",
        prompt_template="C={{ context }} Q={{ question }}",
    )

    assert prepared.refused is None
    assert captured["query"] == "错位相减法的前提"
    assert captured["scope"] == scope
    assert "那它的前提呢？" in prepared.prompt
    assert "错位相减法：乘公比" in prepared.prompt


def test_stream_answer_yields_deltas_and_final_response() -> None:
    prepared = PreparedAnswer(
        retrieval=_retrieval([_chunk()]),
        built=None,  # 本测试不读 built，只验证流式协议
        prompt="prompt",
        refused=None,
        retrieval_ms=7,
        top_score=0.9,
        degraded=False,
    )
    # built=None 只在这里合法，因为 stream_answer 只用 prompt
    fake = FakeStreamLLM(["答", "[1]"])

    chunks = list(stream_answer(prepared, llm_client=fake))

    assert "".join(chunk.text for chunk in chunks) == "答[1]"
    assert chunks[-1].response is not None
    assert chunks[-1].response.total_tokens == 15
    assert fake.calls[0][0].content == "prompt"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_answerer.py -q`
Expected: FAIL —— `ImportError: cannot import name 'PreparedAnswer'`。

- [ ] **Step 3: 实现拆分**

在 `backend/app/ai/rag/answerer.py` 顶部 import 加：

```python
from collections.abc import Iterator

from app.ai.llm.base import LLMStreamChunk
from app.ai.rag.retriever import RetrievalScope
```

在 `AnswerResult` 后加：

```python
@dataclass(frozen=True)
class PreparedAnswer:
    retrieval: RetrievalResult
    built: BuiltContext | None
    prompt: str
    refused: AnswerResult | None
    retrieval_ms: int
    top_score: float | None
    degraded: bool


@dataclass(frozen=True)
class AnswerChunk:
    text: str = ""
    response: LLMResponse | None = None
```

新增 `prepare_answer`（放在 `answer_question` 前）：

```python
def prepare_answer(
    session: Session,
    question: str,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    scope: RetrievalScope | None = None,
    retrieval_query: str | None = None,
    prompt_template: str | None = None,
) -> PreparedAnswer:
    if not question.strip():
        raise ValueError("question 不能为空")
    settings = get_settings()
    threshold_value = settings.qa_refuse_threshold if threshold is None else threshold
    if not 0.0 <= threshold_value <= 1.0:
        raise ValueError("threshold 必须在 [0, 1]")

    query = (retrieval_query or question).strip()
    if not query:
        raise ValueError("retrieval_query 不能为空")

    retrieval_started = time.perf_counter()
    retrieval: RetrievalResult = retrieve_hybrid_reranked(
        session,
        query,
        user_id=user_id,
        top_k=top_k,
        client=embedding_client,
        rerank_client=rerank_client,
        scope=scope,
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    if not retrieval.reranked:
        return PreparedAnswer(
            retrieval=retrieval,
            built=None,
            prompt="",
            refused=_refused("no_context", retrieval_ms=retrieval_ms),
            retrieval_ms=retrieval_ms,
            top_score=None,
            degraded=False,
        )

    scores = [
        chunk.rerank_score
        for chunk in retrieval.reranked
        if chunk.rerank_score is not None
    ]
    top_score = max(scores) if scores else None
    degraded = bool(
        (retrieval.rerank_info and retrieval.rerank_info.fallback)
        or top_score is None
    )
    if not degraded and top_score is not None and top_score < threshold_value:
        return PreparedAnswer(
            retrieval=retrieval,
            built=None,
            prompt="",
            refused=_refused(
                "low_score",
                retrieval_ms=retrieval_ms,
                top_rerank_score=top_score,
            ),
            retrieval_ms=retrieval_ms,
            top_score=top_score,
            degraded=degraded,
        )

    built = build_context(
        retrieval.reranked,
        max_tokens=settings.qa_context_max_tokens,
    )
    if not built.items:
        return PreparedAnswer(
            retrieval=retrieval,
            built=None,
            prompt="",
            refused=_refused(
                "no_context",
                retrieval_ms=retrieval_ms,
                top_rerank_score=top_score,
                degraded=degraded,
            ),
            retrieval_ms=retrieval_ms,
            top_score=top_score,
            degraded=degraded,
        )

    if prompt_template is None:
        prompt = render_prompt(built.text, question)
    else:
        prompt = render_prompt_text(
            prompt_template,
            context=built.text,
            question=question,
        )
    return PreparedAnswer(
        retrieval=retrieval,
        built=built,
        prompt=prompt,
        refused=None,
        retrieval_ms=retrieval_ms,
        top_score=top_score,
        degraded=degraded,
    )


def stream_answer(
    prepared: PreparedAnswer,
    *,
    llm_client: LLMClient | None = None,
) -> Iterator[AnswerChunk]:
    if prepared.refused is not None:
        return
    client = llm_client if llm_client is not None else get_llm_client()
    messages = [LLMMessage(role="user", content=prepared.prompt)]
    for chunk in client.chat_stream(
        messages,
        temperature=get_settings().llm_temperature,
        max_tokens=get_settings().llm_max_output_tokens,
        scene="qa",
    ):
        if chunk.response is not None:
            yield AnswerChunk(response=chunk.response)
        elif chunk.text:
            yield AnswerChunk(text=chunk.text)
```

把 `answer_question` 改为调用 `prepare_answer`，完整实现如下（替换原函数体；引用校验/一次重试逻辑保持不变）：

```python
def answer_question(
    session: Session,
    question: str,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    llm_client: LLMClient | None = None,
    prompt_template: str | None = None,
    scope: RetrievalScope | None = None,
    retrieval_query: str | None = None,
) -> AnswerResult:
    prepared = prepare_answer(
        session,
        question,
        user_id=user_id,
        top_k=top_k,
        threshold=threshold,
        embedding_client=embedding_client,
        rerank_client=rerank_client,
        scope=scope,
        retrieval_query=retrieval_query,
        prompt_template=prompt_template,
    )
    if prepared.refused is not None:
        return prepared.refused
    assert prepared.built is not None

    settings = get_settings()
    client = llm_client if llm_client is not None else get_llm_client()
    messages = [LLMMessage(role="user", content=prepared.prompt)]
    first = _call_llm(
        client,
        messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms = first.latency_ms
    prompt_tokens = first.prompt_tokens
    completion_tokens = first.completion_tokens
    total_tokens = first.total_tokens
    cost_yuan = first.cost_yuan
    llm_calls = 1

    context_size = len(prepared.built.items)
    ok, indices = validate_citations(first.text, context_size=context_size)
    citation_retry_count = 0
    if ok:
        return AnswerResult(
            answer=first.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(prepared.built.items, indices),
            context_tokens=prepared.built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=prepared.retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=prepared.retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=prepared.degraded,
            top_rerank_score=prepared.top_score,
        )

    if settings.qa_citation_max_retries < 1:
        return _refused(
            "citation_invalid",
            retrieval_ms=prepared.retrieval_ms,
            context_tokens=prepared.built.tokens,
            top_rerank_score=prepared.top_score,
            degraded=prepared.degraded,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            llm_ms=llm_ms,
            cost_yuan=cost_yuan,
        )

    correction = (
        f"你上一次回答的引用编号不合法或缺失。本次可用的引用编号只有 "
        f"[1]..[{context_size}]。请重写回答，只使用这些编号；"
        "如果资料不足，直接回答“你的资料里没有相关内容”。"
        "不要解释校验过程，不要使用不存在的编号。"
    )
    retry_messages = messages + [
        LLMMessage(role="assistant", content=first.text or "(空回答)"),
        LLMMessage(role="user", content=correction),
    ]
    second = _call_llm(
        client,
        retry_messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms += second.latency_ms
    prompt_tokens += second.prompt_tokens
    completion_tokens += second.completion_tokens
    total_tokens += second.total_tokens
    cost_yuan += second.cost_yuan
    llm_calls += 1
    citation_retry_count = 1

    ok, indices = validate_citations(second.text, context_size=context_size)
    if ok:
        return AnswerResult(
            answer=second.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(prepared.built.items, indices),
            context_tokens=prepared.built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=prepared.retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=prepared.retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=prepared.degraded,
            top_rerank_score=prepared.top_score,
        )

    reason: RefusalReason = (
        "empty_answer" if not second.text.strip() else "citation_invalid"
    )
    return _refused(
        reason,
        retrieval_ms=prepared.retrieval_ms,
        context_tokens=prepared.built.tokens,
        top_rerank_score=prepared.top_score,
        degraded=prepared.degraded,
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        llm_ms=llm_ms,
        cost_yuan=cost_yuan,
    )
```

- [ ] **Step 4: 跑 answerer 与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_answerer.py -q`
Expected: 原 20 条 + 新 3 条全绿。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **647 passed, 1 warning**（644 + 3）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/ai/rag/answerer.py backend/tests/test_answerer.py
git commit -m "refactor(s3-5): answerer 拆出 prepare_answer 与 stream_answer"
```

---

### Task 4: `schemas/qa.py` 与 `qa_service.prepare_ask`

**Files:**
- Create: `backend/app/schemas/qa.py`
- Create: `backend/app/services/qa_service.py`（本任务只实现 prepare 半段）
- Test: `backend/tests/test_qa_service.py`

**Interfaces:**
- Produces: `QaScopeIn`、`QaAskRequest`、`QaCitationMeta`、`QaMetaData`、`QaDeltaData`、`QaDoneData`、`QaErrorData`、`QaMessageCitationOut`；`QaPlan`、`QaStreamEvent`、`prepare_ask(...)`。
- Consumes: `MessageRole` 常量、`Conversation/Message`、`rewrite_query`、`prompt_service.get_active_prompt`、`prepare_answer`。

- [ ] **Step 1: 写失败的 schema 与 prepare 测试**

`backend/tests/test_qa_service.py` 先放辅助与 prepare 测试（本任务结束要全绿）：

```python
"""S3-5 qa_service：FakeSession，不连库、不调外部 LLM。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.rag.answerer import PreparedAnswer
from app.ai.rag.prompt_builder import BuiltContext, Citation, ContextItem
from app.ai.rag.query_rewriter import HistoryTurn
from app.ai.rag.retriever import RetrievalResult
from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.qa import QaAskRequest, QaScopeIn
from app.services import qa_service
from app.services.query_rewrite import RewriteResult


class FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def all(self) -> list[object]:
        return list(self._rows)


class FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object | None] | None = None,
        scalars_results: list[list[object]] | None = None,
        execute_rows: list[list[tuple[object, object]]] | None = None,
    ) -> None:
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.execute_rows = list(execute_rows or [])
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> FakeResult:
        return FakeResult(self.scalars_results.pop(0))

    def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.execute_rows.pop(0))

    def add(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 100 + len(self.added)  # type: ignore[attr-defined]
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        self.added.append(instance)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1


def _scope() -> QaScopeIn:
    return QaScopeIn(subject_id=7, folder="函数", start_date=date(2026, 1, 1))


def _rewrite(*, intent: str = "note_query", reply: str | None = None) -> RewriteResult:
    return RewriteResult(
        intent=intent,  # type: ignore[arg-type]
        rewritten_query="改写后的问题",
        reply=reply,
        is_followup=True,
        degraded=False,
        cache_hit=False,
        llm_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_yuan=0.00001,
        latency_ms=2,
        error=None,
    )


def _citation(index: int = 1) -> Citation:
    return Citation(
        index=index,
        note_id=55,
        chunk_id=101,
        source_file_id=9,
        heading_path="数列/错位相减法",
        page_no=2,
        snippet="错位相减法正文",
        rerank_score=0.9,
    )


def _prepared() -> PreparedAnswer:
    item = ContextItem(citation=_citation(), content="错位相减法正文", tokens=10)
    built = BuiltContext(text="[1] 正文", items=[item], tokens=10, truncated=False)
    return PreparedAnswer(
        retrieval=RetrievalResult(
            query="改写后的问题",
            tsquery="错位",
            vector=[],
            fulltext=[],
            fused=[],
            reranked=[],
            elapsed_ms=5,
        ),
        built=built,
        prompt="rendered prompt",
        refused=None,
        retrieval_ms=5,
        top_score=0.9,
        degraded=False,
    )


def test_qa_ask_request_rejects_bad_conversation_id_and_blank_question() -> None:
    with pytest.raises(ValidationError):
        QaAskRequest(question="  ")
    with pytest.raises(ValidationError):
        QaAskRequest(question="问题", conversation_id="abc")
    with pytest.raises(ValidationError):
        QaAskRequest(question="问题", conversation_id="0")


def test_qa_scope_rejects_reversed_dates_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QaScopeIn(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        QaScopeIn(chunk_types=["note"])  # QA scope 不允许 chunk_types


def test_prepare_ask_creates_conversation_user_message_and_plan(monkeypatch) -> None:
    session = FakeSession(execute_rows=[[(55, "数列笔记")]])
    fake_rewrite = _rewrite()
    calls: dict[str, object] = {}

    def fake_rewrite_query(question, *, history, use_cache=True):
        calls["rewrite"] = (question, history)
        return fake_rewrite

    monkeypatch.setattr(qa_service, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v2", "content": "PROMPT"}
        )(),
    )

    def fake_prepare(session, question, **kwargs):
        calls["prepare"] = (question, kwargs)
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    plan = qa_service.prepare_ask(
        session,
        user_id=18,
        question="错位相减法怎么用",
        scope=_scope(),
        conversation_id=None,
    )

    assert plan.kind == "rag"
    assert plan.prompt_version == "qa/v2"
    assert plan.citations[0].title == "数列笔记"
    assert plan.citations[0].index == 1
    conversation = next(item for item in session.added if isinstance(item, Conversation))
    assert conversation.title == "错位相减法怎么用"
    assert conversation.scope_json == {
        "subject_id": 7,
        "folder": "函数",
        "start_date": "2026-01-01",
        "end_date": None,
    }
    user_message = next(item for item in session.added if isinstance(item, Message))
    assert user_message.role == "user"
    assert user_message.content_md == "错位相减法怎么用"
    assert session.commits == 1
    assert calls["rewrite"] == ("错位相减法怎么用", [])
    assert calls["prepare"][1]["retrieval_query"] == "改写后的问题"
    assert calls["prepare"][1]["scope"].subject_id == 7


def test_prepare_ask_inherits_stored_scope_and_passes_history(monkeypatch) -> None:
    conversation = Conversation(
        user_id=18,
        title="旧会话",
        scope_json={"subject_id": 3, "folder": None},
    )
    conversation.id = 12
    old_user = Message(conversation_id=12, role="user", content_md="上一问")
    old_user.id = 20
    old_assistant = Message(conversation_id=12, role="assistant", content_md="上一答")
    old_assistant.id = 21
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[old_assistant, old_user]],
        execute_rows=[[(55, "数列笔记")]],
    )
    calls: dict[str, object] = {}

    def fake_rewrite(question, *, history, use_cache=True):
        calls["history"] = history
        return _rewrite()

    monkeypatch.setattr(qa_service, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v1", "content": "PROMPT"}
        )(),
    )

    def fake_prepare(session, question, **kwargs):
        calls["scope"] = kwargs["scope"]
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    plan = qa_service.prepare_ask(
        session,
        user_id=18,
        question="追问",
        scope=None,
        conversation_id=12,
    )

    assert plan.conversation_id == 12
    assert calls["history"] == [
        HistoryTurn(role="user", content="上一问"),
        HistoryTurn(role="assistant", content="上一答"),
    ]
    assert calls["scope"].subject_id == 3


def test_prepare_ask_request_scope_overrides_stored(monkeypatch) -> None:
    conversation = Conversation(
        user_id=18, title="旧会话", scope_json={"subject_id": 3}
    )
    conversation.id = 12
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[]],
        execute_rows=[[]],
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        qa_service, "rewrite_query", lambda *a, **k: _rewrite()
    )
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda session, name="qa": type(
            "P", (), {"name": "qa", "version": "v1", "content": "PROMPT"}
        )(),
    )
    def fake_prepare(session, question, **kwargs):
        captured["scope"] = kwargs["scope"]
        return _prepared()

    monkeypatch.setattr(qa_service, "prepare_answer", fake_prepare)

    qa_service.prepare_ask(
        session,
        user_id=18,
        question="追问",
        scope=_scope(),
        conversation_id=12,
    )

    assert captured["scope"].subject_id == 7


def test_prepare_ask_missing_conversation_raises_404() -> None:
    session = FakeSession(scalar_results=[None])
    with pytest.raises(NotFoundError):
        qa_service.prepare_ask(
            session,
            user_id=18,
            question="问题",
            scope=None,
            conversation_id=999,
        )
```

另在 `backend/tests/test_qa_service.py` 末尾加 chitchat：

```python
def test_prepare_ask_chitchat_skips_prompt_and_retrieval(monkeypatch) -> None:
    session = FakeSession()
    monkeypatch.setattr(
        qa_service, "rewrite_query", lambda *a, **k: _rewrite(intent="chitchat", reply="你好")
    )
    monkeypatch.setattr(
        qa_service.prompt_service,
        "get_active_prompt",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("chitchat 不应查 Prompt")),
    )
    monkeypatch.setattr(
        qa_service,
        "prepare_answer",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("chitchat 不应检索")),
    )

    plan = qa_service.prepare_ask(
        session, user_id=18, question="你好", scope=None, conversation_id=None
    )

    assert plan.kind == "chitchat"
    assert plan.chitchat_reply == "你好"
    assert plan.prepared is None
    assert plan.citations == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.schemas.qa`。

- [ ] **Step 3: 实现 schemas**

`backend/app/schemas/qa.py`：

```python
"""S3-5 问答接口出入参（API.md §5）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QaScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: int | None = Field(None, ge=1)
    folder: str | None = Field(None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("folder")
    @classmethod
    def _strip_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _check_range(self) -> "QaScopeIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class QaAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    scope: QaScopeIn | None = None
    conversation_id: str | None = Field(
        None, pattern=r"^[1-9][0-9]{0,18}$"
    )

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("question 不能为空")
        return clean


class QaCitationMeta(BaseModel):
    index: int
    note_id: int
    chunk_id: int
    title: str | None = None
    heading_path: str | None = None
    page_no: int | None = None
    snippet: str


class QaMetaData(BaseModel):
    conversation_id: str
    user_message_id: int
    citations: list[QaCitationMeta]


class QaDeltaData(BaseModel):
    text: str


class QaDoneData(BaseModel):
    message_id: int
    conversation_id: str
    tokens: int
    latency_ms: int
    refused: bool


class QaErrorData(BaseModel):
    code: int
    message: str


class QaMessageCitationOut(BaseModel):
    id: int
    message_id: int
    chunk_id: int | None = None
    note_id: int | None = None
    question_id: int | None = None
    score: float | None = None
    snippet: str | None = None
    page_no: int | None = None
    bbox_json: dict[str, object] | None = None
    rank: int | None = None
```

- [ ] **Step 4: 实现 `qa_service.prepare_ask` 半段**

`backend/app/services/qa_service.py` 初始版本（本任务只到 prepare；`stream_events` 在 Task 5 加）：

```python
"""S3-5 问答流式服务：会话/历史/改写/检索/Prompt/落库编排。"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm import LLMClient, LLMResponse
from app.ai.llm.errors import LLMError
from app.ai.rag.answerer import (
    REFUSAL_TEXT,
    PreparedAnswer,
    extract_citation_indices,
    prepare_answer,
    stream_answer,
)
from app.ai.rag.prompt_builder import Citation, ContextItem
from app.ai.rag.query_rewriter import HistoryTurn
from app.ai.rag.retriever import RetrievalScope
from app.core.config import get_settings
from app.core.db import new_session
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation
from app.models.note import Note
from app.schemas.qa import QaScopeIn
from app.services import prompt_service
from app.services.query_rewrite import FALLBACK_REPLY, RewriteResult, rewrite_query

logger = logging.getLogger(__name__)
HISTORY_MESSAGES = 6


@dataclass(frozen=True)
class QaCitationMeta:
    index: int
    note_id: int
    chunk_id: int
    title: str | None
    heading_path: str | None
    page_no: int | None
    snippet: str


@dataclass(frozen=True)
class QaStreamEvent:
    event: Literal["meta", "delta", "done", "error"]
    data: dict[str, object]


@dataclass(frozen=True)
class QaPlan:
    user_id: int
    conversation_id: int
    user_message_id: int
    question: str
    kind: Literal["rag", "chitchat", "refused"]
    prepared: PreparedAnswer | None
    chitchat_reply: str | None
    citations: list[QaCitationMeta]
    prompt_version: str | None
    rewrite: RewriteResult | None
    started_at: float


def _retrieval_scope(scope: QaScopeIn | None) -> RetrievalScope | None:
    return RetrievalScope(**scope.model_dump()) if scope is not None else None


def _stored_scope(conversation: Conversation) -> QaScopeIn | None:
    if not conversation.scope_json:
        return None
    try:
        return QaScopeIn.model_validate(conversation.scope_json)
    except ValidationError:
        logger.warning(
            "qa_stored_scope_invalid",
            extra={"conversation_id": conversation.id},
        )
        return None


def _find_conversation(
    session: Session, *, user_id: int, conversation_id: int
) -> Conversation:
    conversation = session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise NotFoundError("会话不存在")
    return conversation


def _load_history(session: Session, *, conversation_id: int) -> list[HistoryTurn]:
    rows = session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role.in_(("user", "assistant")),
        )
        .order_by(Message.id.desc())
        .limit(HISTORY_MESSAGES)
    ).all()
    turns: list[HistoryTurn] = []
    for row in reversed(list(rows)):
        if row.role not in ("user", "assistant"):
            continue
        turns.append(HistoryTurn(role=row.role, content=row.content_md))
    return turns


def _add_message(
    session: Session,
    *,
    conversation_id: int,
    role: str,
    content: str,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content_md=content,
    )
    session.add(message)
    session.flush()
    return message


def _load_titles(
    session: Session, *, user_id: int, items: list[ContextItem]
) -> dict[int, str]:
    note_ids = sorted({item.citation.note_id for item in items})
    if not note_ids:
        return {}
    rows = session.execute(
        select(Note.id, Note.title).where(
            Note.user_id == user_id,
            Note.id.in_(note_ids),
        )
    ).all()
    return {int(row[0]): row[1] for row in rows}


def _citation_meta(
    citation: Citation, titles: dict[int, str]
) -> QaCitationMeta:
    return QaCitationMeta(
        index=citation.index,
        note_id=citation.note_id,
        chunk_id=citation.chunk_id,
        title=titles.get(citation.note_id),
        heading_path=citation.heading_path,
        page_no=citation.page_no,
        snippet=citation.snippet,
    )


def prepare_ask(
    session: Session,
    *,
    user_id: int,
    question: str,
    scope: QaScopeIn | None,
    conversation_id: int | None,
) -> QaPlan:
    started = time.perf_counter()
    clean = question.strip()
    if not clean:
        raise InvalidParamError("question 不能为空")

    if conversation_id is None:
        conversation = Conversation(
            user_id=user_id,
            title=" ".join(clean.split())[:50],
            scope_json=scope.model_dump(mode="json") if scope is not None else None,
        )
        session.add(conversation)
        session.flush()
        history: list[HistoryTurn] = []
        resolved_scope = scope
    else:
        conversation = _find_conversation(
            session, user_id=user_id, conversation_id=conversation_id
        )
        history = _load_history(session, conversation_id=conversation.id)
        resolved_scope = (
            scope if scope is not None else _stored_scope(conversation)
        )

    user_message = _add_message(
        session,
        conversation_id=conversation.id,
        role="user",
        content=clean,
    )
    session.commit()

    rewrite = rewrite_query(clean, history=history)
    if rewrite.intent == "chitchat":
        reply = rewrite.reply or FALLBACK_REPLY
        return QaPlan(
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            question=clean,
            kind="chitchat",
            prepared=None,
            chitchat_reply=reply,
            citations=[],
            prompt_version=None,
            rewrite=rewrite,
            started_at=started,
        )

    prompt = prompt_service.get_active_prompt(
        session, name=prompt_service.QA_PROMPT_NAME
    )
    prompt_version = f"{prompt.name}/{prompt.version}"
    prepared = prepare_answer(
        session,
        clean,
        user_id=user_id,
        scope=_retrieval_scope(resolved_scope),
        retrieval_query=rewrite.rewritten_query,
        prompt_template=prompt.content,
    )
    if prepared.refused is not None:
        return QaPlan(
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            question=clean,
            kind="refused",
            prepared=prepared,
            chitchat_reply=None,
            citations=[],
            prompt_version=prompt_version,
            rewrite=rewrite,
            started_at=started,
        )

    assert prepared.built is not None
    titles = _load_titles(session, user_id=user_id, items=prepared.built.items)
    citations = [
        _citation_meta(item.citation, titles) for item in prepared.built.items
    ]
    return QaPlan(
        user_id=user_id,
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        question=clean,
        kind="rag",
        prepared=prepared,
        chitchat_reply=None,
        citations=citations,
        prompt_version=prompt_version,
        rewrite=rewrite,
        started_at=started,
    )
```

注意：`_load_titles` 的 `items: list[object]` 在运行时要访问 `.citation`，测试传 `built.items`；后续可改为 `list[ContextItem]` 并 import，类型更准。

- [ ] **Step 5: 跑 service 测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`
Expected: 7 passed。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **654 passed, 1 warning**（647 + 7）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/qa.py backend/app/services/qa_service.py backend/tests/test_qa_service.py
git commit -m "feat(s3-5): QA 请求 schema 与会话准备服务"
```

---

### Task 5: `stream_events`、assistant/citations 落库与引用查询

**Files:**
- Modify: `backend/app/services/qa_service.py`
- Test: `backend/tests/test_qa_service.py`

**Interfaces:**
- Produces: `stream_events(plan,*,llm_client=None,session_factory=new_session)`；`get_message_citations(session,*,user_id,message_id)`。
- Consumes: `stream_answer`、`extract_citation_indices`、`MessageCitation`、`asdict`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_qa_service.py` 追加以下内容。先加 import：

```python
from dataclasses import replace

from app.ai.llm import LLMError, LLMResponse
from app.ai.rag.answerer import AnswerChunk, REFUSAL_TEXT
from app.models.message_citation import MessageCitation
```

辅助：

```python
def _plan(
    *,
    kind: str = "rag",
    prepared: PreparedAnswer | None = None,
    reply: str | None = None,
    prompt_version: str | None = "qa/v2",
) -> qa_service.QaPlan:
    return qa_service.QaPlan(
        user_id=18,
        conversation_id=12,
        user_message_id=30,
        question="问题",
        kind=kind,  # type: ignore[arg-type]
        prepared=prepared if prepared is not None else (_prepared() if kind != "chitchat" else None),
        chitchat_reply=reply,
        citations=[
            qa_service.QaCitationMeta(
                index=1,
                note_id=55,
                chunk_id=101,
                title="数列笔记",
                heading_path="数列/错位相减法",
                page_no=2,
                snippet="正文",
            )
        ],
        prompt_version=prompt_version,
        rewrite=_rewrite(),
        started_at=0.0,
    )


class FakeAssistantSession(FakeSession):
    def close(self) -> None:
        return None


def test_stream_events_rag_persists_assistant_and_citations(monkeypatch) -> None:
    final = LLMResponse(
        text="答[1]",
        model="qwen-plus",
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        latency_ms=5,
        cost_yuan=0.0001,
    )
    monkeypatch.setattr(
        qa_service,
        "stream_answer",
        lambda prepared, llm_client=None: iter(
            [AnswerChunk(text="答"), AnswerChunk(text="[1]"), AnswerChunk(response=final)]
        ),
    )
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(),
            llm_client=object(),
            session_factory=lambda: final_session,
        )
    )

    assert [event.event for event in events] == ["meta", "delta", "delta", "done"]
    assert events[0].data["conversation_id"] == "12"
    assert events[-1].data["refused"] is False
    assert events[-1].data["tokens"] == 135  # 120 answer + 15 rewrite
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.role == "assistant"
    assert assistant.content_md == "答[1]"
    assert assistant.prompt_version == "qa/v2"
    assert assistant.token_usage["total_tokens"] == 120
    assert assistant.token_usage["rewrite"]["total_tokens"] == 15
    citations = [
        item for item in final_session.added if isinstance(item, MessageCitation)
    ]
    assert len(citations) == 1
    assert citations[0].rank == 1
    assert citations[0].chunk_id == 101
    assert final_session.commits == 1


def test_stream_events_chitchat_persists_reply(monkeypatch) -> None:
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(
                kind="chitchat",
                prepared=None,
                reply="你好",
                prompt_version=None,
            ),
            session_factory=lambda: final_session,
        )
    )

    assert [event.event for event in events] == ["meta", "delta", "done"]
    assert events[1].data["text"] == "你好"
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == "你好"
    assert assistant.prompt_version is None


def test_stream_events_refused_persists_fixed_text(monkeypatch) -> None:
    prepared = _prepared()
    prepared = replace(prepared, refused=object(), built=None)  # type: ignore[arg-type]
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(kind="refused", prepared=prepared),
            session_factory=lambda: final_session,
        )
    )

    assert events[1].data["text"] == REFUSAL_TEXT
    assert events[-1].data["refused"] is True
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == REFUSAL_TEXT


def test_stream_events_llm_error_emits_error_and_no_assistant(monkeypatch) -> None:
    def boom(prepared, *, llm_client=None):
        raise LLMError("模拟失败")
        yield  # pragma: no cover

    monkeypatch.setattr(qa_service, "stream_answer", boom)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(), session_factory=lambda: final_session
        )
    )

    assert [event.event for event in events] == ["meta", "error"]
    assert events[-1].data["code"] == 50000
    assert not any(isinstance(item, Message) for item in final_session.added)


def test_stream_events_disconnect_does_not_persist_assistant(monkeypatch) -> None:
    closed: list[bool] = []

    class Stream:
        def __iter__(self):
            yield AnswerChunk(text="半截")
            raise GeneratorExit

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        qa_service, "stream_answer", lambda prepared, llm_client=None: Stream()
    )
    final_session = FakeAssistantSession()
    generator = qa_service.stream_events(
        _plan(), session_factory=lambda: final_session
    )
    assert next(generator).event == "meta"
    assert next(generator).event == "delta"
    with pytest.raises(StopIteration):
        next(generator)
    assert closed == [True]
    assert not any(isinstance(item, Message) for item in final_session.added)


def test_get_message_citations_returns_rows_and_404() -> None:
    message = Message(conversation_id=12, role="assistant", content_md="答")
    message.id = 31
    citation = MessageCitation(message_id=31, chunk_id=101, note_id=55, rank=1)
    citation.id = 99
    session = FakeSession(
        scalar_results=[message, None],
        scalars_results=[[citation], []],
    )

    rows = qa_service.get_message_citations(session, user_id=18, message_id=31)
    assert rows == [citation]

    with pytest.raises(NotFoundError):
        qa_service.get_message_citations(session, user_id=18, message_id=999)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.qa_service' has no attribute 'stream_events'`。

- [ ] **Step 3: 实现 `stream_events` 与落库**

在 `qa_service.py` 追加：

```python
def _usage_payload(response: LLMResponse | None) -> dict[str, object]:
    if response is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_yuan": 0.0,
        }
    return {
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
        "cost_yuan": response.cost_yuan,
    }


def _token_usage(
    response: LLMResponse | None, rewrite: RewriteResult | None
) -> dict[str, object]:
    payload = _usage_payload(response)
    payload["rewrite"] = (
        {
            "prompt_tokens": rewrite.prompt_tokens,
            "completion_tokens": rewrite.completion_tokens,
            "total_tokens": rewrite.total_tokens,
            "cost_yuan": rewrite.cost_yuan,
            "degraded": rewrite.degraded,
            "cache_hit": rewrite.cache_hit,
        }
        if rewrite is not None
        else None
    )
    return payload


def _total_tokens(
    response: LLMResponse | None, rewrite: RewriteResult | None
) -> int:
    return (response.total_tokens if response is not None else 0) + (
        rewrite.total_tokens if rewrite is not None else 0
    )


def _persist_assistant(
    *,
    session_factory: Callable[[], Session],
    plan: QaPlan,
    content: str,
    response: LLMResponse | None,
    citation_indices: list[int],
) -> Message:
    latency_ms = int((time.perf_counter() - plan.started_at) * 1000)
    session = session_factory()
    try:
        message = Message(
            conversation_id=plan.conversation_id,
            role="assistant",
            content_md=content,
            token_usage=_token_usage(response, plan.rewrite),
            latency_ms=latency_ms,
            model=(
                response.model
                if response is not None
                else get_settings().llm_model
            ),
            prompt_version=plan.prompt_version,
        )
        session.add(message)
        session.flush()
        if plan.prepared is not None and plan.prepared.built is not None:
            for index in citation_indices:
                citation = plan.prepared.built.items[index - 1].citation
                session.add(
                    MessageCitation(
                        message_id=message.id,
                        chunk_id=citation.chunk_id,
                        note_id=citation.note_id,
                        score=citation.rerank_score,
                        snippet=citation.snippet,
                        page_no=citation.page_no,
                        rank=index,
                    )
                )
        session.commit()
        return message
    finally:
        session.close()


def _valid_citation_indices(plan: QaPlan, text: str) -> list[int]:
    if plan.prepared is None or plan.prepared.built is None:
        return []
    size = len(plan.prepared.built.items)
    return [
        index
        for index in extract_citation_indices(text)
        if 1 <= index <= size
    ]


def _done_data(plan: QaPlan, message: Message, *, refused: bool, response: LLMResponse | None) -> dict[str, object]:
    return {
        "message_id": message.id,
        "conversation_id": str(plan.conversation_id),
        "tokens": _total_tokens(response, plan.rewrite),
        "latency_ms": int((time.perf_counter() - plan.started_at) * 1000),
        "refused": refused,
    }


def _error_event() -> QaStreamEvent:
    return QaStreamEvent(
        event="error",
        data={"code": 50000, "message": "生成失败"},
    )


def stream_events(
    plan: QaPlan,
    *,
    llm_client: LLMClient | None = None,
    session_factory: Callable[[], Session] = new_session,
) -> Iterator[QaStreamEvent]:
    yield QaStreamEvent(
        event="meta",
        data={
            "conversation_id": str(plan.conversation_id),
            "user_message_id": plan.user_message_id,
            "citations": [asdict(citation) for citation in plan.citations],
        },
    )

    if plan.kind == "chitchat":
        text = plan.chitchat_reply or FALLBACK_REPLY
        yield QaStreamEvent(event="delta", data={"text": text})
        try:
            message = _persist_assistant(
                session_factory=session_factory,
                plan=plan,
                content=text,
                response=None,
                citation_indices=[],
            )
        except Exception:
            logger.exception("qa_persist_chitchat_failed")
            yield _error_event()
            return
        yield QaStreamEvent(
            event="done",
            data=_done_data(plan, message, refused=False, response=None),
        )
        return

    if plan.kind == "refused":
        yield QaStreamEvent(event="delta", data={"text": REFUSAL_TEXT})
        try:
            message = _persist_assistant(
                session_factory=session_factory,
                plan=plan,
                content=REFUSAL_TEXT,
                response=None,
                citation_indices=[],
            )
        except Exception:
            logger.exception("qa_persist_refusal_failed")
            yield _error_event()
            return
        yield QaStreamEvent(
            event="done",
            data=_done_data(plan, message, refused=True, response=None),
        )
        return

    if plan.prepared is None:
        yield _error_event()
        return

    parts: list[str] = []
    final_response: LLMResponse | None = None
    stream = stream_answer(plan.prepared, llm_client=llm_client)
    try:
        for chunk in stream:
            if chunk.text:
                parts.append(chunk.text)
                yield QaStreamEvent(event="delta", data={"text": chunk.text})
            if chunk.response is not None:
                final_response = chunk.response
    except GeneratorExit:
        logger.info(
            "qa_stream_disconnected",
            extra={"conversation_id": plan.conversation_id},
        )
        return
    except LLMError:
        logger.warning(
            "qa_stream_llm_failed",
            extra={"conversation_id": plan.conversation_id},
        )
        yield _error_event()
        return
    except Exception:
        logger.exception(
            "qa_stream_failed",
            extra={"conversation_id": plan.conversation_id},
        )
        yield _error_event()
        return
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()

    answer_text = "".join(parts).strip()
    refused = not answer_text
    if refused:
        answer_text = REFUSAL_TEXT
        yield QaStreamEvent(event="delta", data={"text": REFUSAL_TEXT})
    indices = [] if refused else _valid_citation_indices(plan, answer_text)
    try:
        message = _persist_assistant(
            session_factory=session_factory,
            plan=plan,
            content=answer_text,
            response=final_response,
            citation_indices=indices,
        )
    except Exception:
        logger.exception("qa_persist_assistant_failed")
        yield _error_event()
        return

    yield QaStreamEvent(
        event="done",
        data=_done_data(
            plan,
            message,
            refused=refused,
            response=final_response,
        ),
    )


def get_message_citations(
    session: Session, *, user_id: int, message_id: int
) -> list[MessageCitation]:
    message = session.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.id == message_id,
            Conversation.user_id == user_id,
        )
    )
    if message is None:
        raise NotFoundError("消息不存在")
    return list(
        session.scalars(
            select(MessageCitation)
            .where(MessageCitation.message_id == message_id)
            .order_by(MessageCitation.rank.asc(), MessageCitation.id.asc())
        ).all()
    )
```

- [ ] **Step 4: 跑 service 测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`
Expected: `13 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **660 passed, 1 warning**（654 + 6）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/qa_service.py backend/tests/test_qa_service.py
git commit -m "feat(s3-5): SSE 事件、assistant/citations 落库与引用查询"
```

---

### Task 6: QA 路由、SSE 序列化与引用接口

**Files:**
- Create: `backend/app/api/v1/qa.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_qa_api.py`

**Interfaces:**
- Consumes: `require_role("student")`、`get_db`、`qa_service.prepare_ask/stream_events/get_message_citations`。
- Produces: `POST /api/v1/qa/ask`（SSE）、`GET /api/v1/qa/messages/{message_id}/citations`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_qa_api.py`：

```python
"""S3-5 QA 接口：TestClient + 依赖覆盖，不触库、不调外部 LLM。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.message_citation import MessageCitation
from app.models.user import User
from app.services import qa_service


class FakeSession:
    def __init__(self, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        from app.models.user import User as UserModel

        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is UserModel:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_1") -> User:
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


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _plan() -> qa_service.QaPlan:
    return qa_service.QaPlan(
        user_id=1,
        conversation_id=12,
        user_message_id=30,
        question="问题",
        kind="chitchat",
        prepared=None,
        chitchat_reply="你好",
        citations=[],
        prompt_version=None,
        rewrite=None,
        started_at=0.0,
    )


def _override_user(user: User) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(user)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        qa_service,
        "prepare_ask",
        lambda session, **kwargs: _plan(),
    )
    monkeypatch.setattr(
        qa_service,
        "stream_events",
        lambda plan, **kwargs: iter(
            [
                qa_service.QaStreamEvent(
                    event="meta",
                    data={
                        "conversation_id": "12",
                        "user_message_id": 30,
                        "citations": [],
                    },
                ),
                qa_service.QaStreamEvent(
                    event="delta", data={"text": "你好"}
                ),
                qa_service.QaStreamEvent(
                    event="done",
                    data={
                        "message_id": 31,
                        "conversation_id": "12",
                        "tokens": 15,
                        "latency_ms": 20,
                        "refused": False,
                    },
                ),
            ]
        ),
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_qa_ask_streams_sse_frames(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    with client.stream(
        "POST",
        "/api/v1/qa/ask",
        headers=_headers(user),
        json={"question": "你好"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())

    assert "event: meta" in body
    assert '"conversation_id":"12"' in body
    assert "event: delta" in body
    assert '"text":"你好"' in body
    assert "event: done" in body
    assert body.endswith("\n\n")


def test_qa_ask_requires_student(client: TestClient) -> None:
    teacher = _user(role="teacher", username="teacher_1")
    _override_user(teacher)
    response = client.post(
        "/api/v1/qa/ask",
        headers=_headers(teacher),
        json={"question": "问题"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_qa_ask_rejects_bad_request(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    for payload in (
        {"question": "  "},
        {"question": "问题", "conversation_id": "abc"},
        {"question": "问题", "scope": {"chunk_types": ["note"]}},
    ):
        response = client.post(
            "/api/v1/qa/ask", headers=_headers(user), json=payload
        )
        assert response.status_code == 422
        assert response.json()["code"] == 42200


def test_qa_ask_returns_404_for_missing_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "prepare_ask", missing)
    response = client.post(
        "/api/v1/qa/ask",
        headers=_headers(user),
        json={"question": "问题", "conversation_id": "999"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_get_message_citations_returns_own_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)
    row = MessageCitation(
        message_id=31,
        chunk_id=101,
        note_id=55,
        score=0.9,
        snippet="正文",
        page_no=2,
        rank=1,
    )
    row.id = 99
    monkeypatch.setattr(
        qa_service,
        "get_message_citations",
        lambda session, **kwargs: [row],
    )

    response = client.get(
        "/api/v1/qa/messages/31/citations", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == 99
    assert data[0]["chunk_id"] == 101
    assert data[0]["rank"] == 1


def test_get_message_citations_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)

    def missing(session, **kwargs):
        raise NotFoundError("消息不存在")

    monkeypatch.setattr(qa_service, "get_message_citations", missing)
    response = client.get(
        "/api/v1/qa/messages/999/citations", headers=_headers(user)
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40400
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_api.py -q`
Expected: FAIL —— 404（路由未注册）或 `ImportError`。

- [ ] **Step 3: 实现路由**

`backend/app/api/v1/qa.py`：

```python
"""S3-5 问答接口（API.md §5）：学生 SSE 问答与引用查询。"""
from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.qa import QaAskRequest, QaMessageCitationOut
from app.services import qa_service

router = APIRouter(prefix="/qa", tags=["qa"])


def _sse(event: qa_service.QaStreamEvent) -> str:
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"


def _stream(plan: qa_service.QaPlan) -> Iterator[str]:
    for event in qa_service.stream_events(plan):
        yield _sse(event)


@router.post(
    "/ask",
    summary="流式问答（SSE：meta/delta/done/error）",
    response_class=StreamingResponse,
)
def ask(
    payload: QaAskRequest,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    conversation_id = (
        int(payload.conversation_id)
        if payload.conversation_id is not None
        else None
    )
    plan = qa_service.prepare_ask(
        session,
        user_id=current_user.id,
        question=payload.question,
        scope=payload.scope,
        conversation_id=conversation_id,
    )
    return StreamingResponse(
        _stream(plan),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/messages/{message_id}/citations",
    response_model=Envelope[list[QaMessageCitationOut]],
    summary="查询本人消息的引用列表",
)
def message_citations(
    message_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[list[QaMessageCitationOut]]:
    rows = qa_service.get_message_citations(
        session, user_id=current_user.id, message_id=message_id
    )
    data = [
        QaMessageCitationOut(
            id=row.id,
            message_id=row.message_id,
            chunk_id=row.chunk_id,
            note_id=row.note_id,
            question_id=row.question_id,
            score=float(row.score) if row.score is not None else None,
            snippet=row.snippet,
            page_no=row.page_no,
            bbox_json=row.bbox_json,
            rank=row.rank,
        )
        for row in rows
    ]
    return Envelope(trace_id=get_trace_id(), data=data)
```

`backend/app/api/router.py` 加：

```python
from app.api.v1 import admin, auth, files, kp, notes, qa, retrieval, tasks
```

并 `api_router.include_router(qa.router)`。

- [ ] **Step 4: 跑接口测试与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_api.py -q`
Expected: `6 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: **666 passed, 1 warning**（660 + 6）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/v1/qa.py backend/app/api/router.py backend/tests/test_qa_api.py
git commit -m "feat(s3-5): QA SSE 接口与消息引用查询"
```

---

### Task 7: 文档同步、真实 SSE 验收与最终提交

**Files:**
- Modify: `docs/API.md` §5
- Modify: `docs/SCHEMA.md` §7
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md` S3-5
- Modify: `deploy/README.md`

**Interfaces:**
- 无新代码接口；把实现事实写回契约与进度。

- [ ] **Step 1: 更新 API.md §5**

在 `POST /api/v1/qa/ask` 下补齐：

```markdown
**事件补充**
- `meta.data`：`conversation_id`（字符串）、`user_message_id`、`citations[]`（全部上下文引用，编号供正文 `[n]` 使用）。
- `done.data`：`message_id`、`conversation_id`（字符串）、`tokens`（回答 + 改写总 token）、`latency_ms`（服务端总耗时）、`refused`。
- 流中失败新增 `event: error`，`data={"code":50000,"message":"生成失败"}`；此后连接关闭，不再发 `done`。
- 会话不存在/不属于当前学生统一 404/40400；`conversation_id` 非法格式 422/42200。
- chitchat/拒答也先发 `meta`（citations 为空），再发一次 `delta` 全文，再发 `done`。
- 断连：服务端关闭上游 LLM，保留 user 消息，不落 assistant。
- 本轮不实现限流；429 暂不返回。
```

`GET /qa/messages/{id}/citations` 下补：

```markdown
- 仅本人消息；不存在/越权统一 404/40400「消息不存在」。
- 返回 `message_citations` 表字段：`id/message_id/chunk_id/note_id/question_id/score/snippet/page_no/bbox_json/rank`，按 `rank,id` 升序。
```

- [ ] **Step 2: 更新 SCHEMA.md §7**

把三表实际字段/索引/FK 写进去；`messages.token_usage` 标明：

```json
{
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "total_tokens": 0,
  "cost_yuan": 0.0,
  "rewrite": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cost_yuan": 0.0,
    "degraded": false,
    "cache_hit": false
  }
}
```

并写明 `conversations.user_id → users.id`、`messages.conversation_id → conversations.id ON DELETE CASCADE`、`message_citations.message_id → messages.id ON DELETE CASCADE`；`messages.role` CHECK 为 `user/assistant/system`。

- [ ] **Step 3: 更新 PROGRESS / DECISIONS / 任务卡**

`docs/PROGRESS.md`：S3-5 标完成，记录：

```markdown
- S3-5 完成：`POST /api/v1/qa/ask` 真实 SSE（meta/delta/done/error），先落 user 消息，正常结束落 assistant + citations；断连不落 assistant；`GET /api/v1/qa/messages/{id}/citations` 仅本人。
- 迁移 `0007_s3_5`；测试 <实测数字>。
- 遗留：S3-6 引用校验/拒答重试；S3-7 llm_call_logs/Redis 缓存；S3-8 会话列表与前端；429 限流未实现。
```

`docs/DECISIONS.md`：新增 D-041（按现有最大编号续；若已占用则顺延），记录：

```markdown
## D-041 S3-5 问答流式与会话落库
- LLM 层新增 `chat_stream`；不支持流式的 Client 默认一次 chat 后单块输出。
- 先落 user 消息；assistant 只在正常结束后落库；断连/流中错误不落 assistant。
- S3-5 不做引用校验重试；只持久化合法 `[n]` 子集，S3-6 接管。
- conversation_id 对外字符串、库内 BIGINT。
```

`docs/AI协作开发实施计划.md`：S3-5 卡片勾选完成，备注产出文件与测试数。

- [ ] **Step 4: 更新 deploy/README.md**

加入 Nginx SSE 段：

```nginx
location /api/v1/qa/ask {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    add_header X-Accel-Buffering no;
}
```

并说明：不关 `proxy_buffering` 时 curl 可能一次收到完整响应；反代/网关也要支持流式。

- [ ] **Step 5: 起服务做真实 SSE 验收**

先确认迁移与测试：

```bash
cd study-agent/backend && ..\.venv\Scripts\alembic.exe current
cd study-agent && .\.venv\Scripts\python.exe -m pytest -q
```

生成 user 18 的 token（不打印密钥）：

```bash
cd study-agent
.\.venv\Scripts\python.exe -c "from app.core.security import create_access_token; print(create_access_token(user_id=18, role='student').token)"
```

另开后台起服务：

```bash
cd study-agent/backend
..\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

curl：

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/qa/ask ^
  -H "Authorization: Bearer <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"错位相减法怎么用\"}"
```

Expected：先 `event: meta`，随后多个 `event: delta`（不是一次性整段），最后 `event: done`；记录 `conversation_id`、`message_id`。

- [ ] **Step 6: DB 与追问验收**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,conversation_id,role,left(content_md,40),prompt_version,model,latency_ms from messages order by id desc limit 6;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,message_id,chunk_id,note_id,score,rank,left(snippet,30) from message_citations order by id desc limit 6;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,user_id,title,scope_json from conversations order by id desc limit 3;"
```

Expected：同一 conversation 下有 user+assistant；assistant 的 citations 行对应回答里的 `[n]`；`prompt_version` 为当前 active 的 `qa/vN`。

用 meta 返回的 conversation_id 追问：

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/qa/ask ^
  -H "Authorization: Bearer <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"那它的前提条件呢？\",\"conversation_id\":\"<CONV_ID>\"}"
```

Expected：仍返回 SSE；DB 中该 conversation 新增 user+assistant 两行。

查引用接口：

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8000/api/v1/qa/messages/<MESSAGE_ID>/citations
```

Expected：`code:0`，`data` 为 citation 数组；换他人消息/不存在消息 404。

断连验收（LLM 仍在生成时）：

```bash
curl -N --max-time 3 -X POST http://127.0.0.1:8000/api/v1/qa/ask ^
  -H "Authorization: Bearer <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"请详细解释错位相减法的所有变体\"}"
```

Expected：curl 以超时退出；DB 该轮只有 user、没有 assistant；服务端日志有 `qa_stream_disconnected`（或上游连接关闭）。

- [ ] **Step 7: 最终全套与提交**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿；记录实际数字（预计 666 passed, 1 warning）。

```bash
git add docs/API.md docs/SCHEMA.md docs/PROGRESS.md docs/DECISIONS.md docs/AI协作开发实施计划.md deploy/README.md
git commit -m "docs(s3-5): QA SSE 契约、会话表与部署说明"
```

---

## Self-Review

- **Spec coverage**：表/迁移（Task 1）、LLM 流式（Task 2）、answerer 复用（Task 3）、会话/scope/历史/改写（Task 4）、落库/断连/错误/引用查询（Task 5）、SSE/鉴权/引用接口（Task 6）、文档/真实验收（Task 7）。
- **类型一致性**：`QaPlan`、`QaStreamEvent`、`PreparedAnswer`、`AnswerChunk` 的字段在 Task 3-6 中一致；`conversation_id` 在事件中始终 `str`，服务内部 `int`。
- **已知计划偏差**：Task 2 的 `chat_stream` 在 `httpx.MockTransport` 下用 `response.iter_lines()`；若实际 MockTransport 对 content 的流式行为与真实响应不同，允许在测试中用 `httpx.Response(200, content=..., headers={"content-type":"text/event-stream"})` 固定，不改变实现契约。
- **测试数字**：按新增 3+5+3+13+6=30 条估算 666；执行时以实际 `pytest` 输出为准并回填 PROGRESS/spec。

---

## Execution Record

- 执行方式：本会话内联执行（用户确认 plan 后）。
- 提交：`5605174`（模型/迁移）→ `833b683`（LLM 流）→ `36db7be`（answerer）→ `af3e731`（schema/prepare）→ `cc8f741`（SSE/落库/引用）→ `1a5e41e`（API）→ `4f4b4c0`（断连修复）；本文档与验收记录随后提交；未 push。
- 测试：新增 **30** 条（模型 3、LLM 5、answerer 3、service 13、API 6），基线 636 → 全量 **666 passed, 1 warning**。
- 真实验收：迁移 `0007_s3_5` 应用；首问 SSE meta 1 / delta 181 / done 1、curl 24.480s、`done.tokens=1949`；DB user+assistant、4 条 citations、`qa/v1`；追问 3.688s、同会话新增两行、引用接口 200；chitchat 1.224s、无 prompt_version；不存在会话 404/40400。
- 断连：首版同步生成器不触发 `close()`，日志缺失；改为 **async 路由 + `run_in_threadpool(next, ...)` + `finally: events.close()`** 后，`curl --max-time 3` 断开即出现 `qa_stream_disconnected`，DB 只留 user、无 assistant。
- 偏差：`PreparedAnswer.built` 类型改为 `BuiltContext | None`；DECISIONS 实际编号 **D-039**（原计划 D-041）；Task 6 的 `_stream` 从同步生成器改为 async 生成器（原因见上）。
- 文档：API.md §5、SCHEMA.md §7、PROGRESS、DECISIONS D-039、实施计划 S3-5、deploy/README Nginx SSE 已同步。