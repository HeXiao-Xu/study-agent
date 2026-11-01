# S3-8 前端问答页（流式 + 引用跳转）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让学生能在 `/qa` 选择 scope、连续流式提问、查看引用并跳到只读笔记高亮片段，同时支持会话新建/切换/重命名/删除与刷新恢复。

**Architecture:** 后端补齐 4 个会话读取/管理接口（复用现有 `conversations/messages/message_citations`，无迁移）；前端用 `fetch` 读取 SSE、纯函数解析事件，`md-editor-v3` 的 `MdPreview` 渲染 Markdown/KaTeX，新增只读笔记路由承载引用定位。

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2.0；Vue 3 + TypeScript + Pinia + Element Plus + md-editor-v3 + vitest。

**Spec:** `docs/spec/s3-8-qa-chat.md`

## Global Constraints

- 不新增第三方依赖；不修改 Alembic 迁移，不新增表/列。
- 所有新接口仅 `student` 且仅本人会话；不存在/越权统一 `404/40400`。
- 所有查询显式过滤 `user_id`；列表/详情禁止 N+1。
- 后端路由只做参数校验 → service → `Envelope`；业务异常用 `AppError` 子类。
- 前端 API 调用只经 `web/src/api/`；组件不得直接 import axios。
- 时间统一 UTC ISO-8601；不把真实学生姓名/联系方式写入日志或测试。
- 所有测试禁止真实 LLM/Embedding/网络；外部调用一律 mock。
- 每个任务结束必须跑该任务的测试并提交；提交信息含 `s3-8`。
- 用户负责 `git push`，执行者不得 push。

---

### Task 1: 会话摘要/回放契约与服务

**Files:**
- Modify: `docs/API.md`（§5 新增 4 个接口的契约）
- Modify: `backend/app/schemas/qa.py`
- Modify: `backend/app/services/qa_service.py`
- Modify: `backend/app/api/v1/qa.py`
- Create: `backend/tests/test_qa_conversations.py`
- Create: `backend/tests/test_qa_conversations_api.py`

**Interfaces:**
- Consumes: existing `Conversation`, `Message`, `MessageCitation`, `Note`, `NoteChunk`, `_find_conversation`, `_stored_scope`, `get_trace_id`, `require_role("student")`.
- Produces:
  - service dataclasses `ConversationSummary`, `ConversationCitation`, `ConversationMessage`, `ConversationDetail`
  - `list_conversations(session, *, user_id: int, limit: int = 50) -> list[ConversationSummary]`
  - `get_conversation_detail(session, *, user_id: int, conversation_id: int) -> ConversationDetail`
  - schemas `QaConversationOut`, `QaConversationDetailOut`, `QaHistoryMessageOut`, `QaHistoryCitationOut`
  - routes `GET /api/v1/qa/conversations`, `GET /api/v1/qa/conversations/{conversation_id}/messages`

- [x] **Step 1: 先写 API.md 契约**

在 `docs/API.md` 的 `GET /api/v1/qa/messages/{id}/citations` 之后、`## 6. 错题本` 之前加入：

```markdown
### GET /api/v1/qa/conversations
- 权限：student（仅本人会话）
- 类型：同步
- 入参：`limit`（可选，默认 50，1–100）
- 出参：`Envelope[QaConversationOut[]]`，按最近消息时间倒序；无消息按 `created_at`
- `QaConversationOut`：`id`（字符串）/ `title` / `scope`（同 §5 检索 scope，可为 null）/ `created_at` / `last_message_at` / `message_count`
- 备注：`title` 为空时回退首条 user 消息前 50 字，再回退「新对话」；只返回 `role in ('user','assistant')` 的计数
- 错误：401/40100；403/40300；422/42200

### GET /api/v1/qa/conversations/{conversation_id}/messages
- 权限：student（仅本人会话）
- 类型：同步
- 出参：`Envelope[QaConversationDetailOut]`：`conversation` 同上，`messages` 按 id 升序
- `QaHistoryMessageOut`：`id` / `role`（user|assistant）/ `content_md` / `created_at` / `refused` / `citations`
- `QaHistoryCitationOut`：`index`（=rank，空为 0）/ `note_id` / `chunk_id` / `title` / `heading_path` / `page_no` / `snippet` / `score` / `note_available`
- 备注：引用按 `rank,id` 升序；`title/heading_path` 左连接 `notes/note_chunks`；软删笔记 `note_available=false`；历史拒答仅按正文与 `REFUSAL_TEXT` 相等推导，不恢复当时 reason/suggestions
- 错误：404/40400「会话不存在」（含越权）；401/40100；403/40300

### PATCH /api/v1/qa/conversations/{conversation_id}
- 权限：student（仅本人会话）
- 类型：同步
- 入参：`{"title": "新标题"}`；trim 后 1–80 字
- 出参：`Envelope[QaConversationOut]`
- 错误：404/40400；422/42200 空白或超长

### DELETE /api/v1/qa/conversations/{conversation_id}
- 权限：student（仅本人会话）
- 类型：同步（物理删除）
- 出参：`204` 无响应体
- 备注：依赖 `messages` / `message_citations` 的数据库级联
- 错误：404/40400；401/40100；403/40300
```

- [x] **Step 2: 写失败的 service 测试**

创建 `backend/tests/test_qa_conversations.py`：

```python
"""S3-8 会话回放 service：FakeSession，不连库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation
from app.services import qa_service


class FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def all(self) -> list[object]:
        return list(self._rows)

    def one(self) -> object:
        return self._rows[0]


class FakeSession:
    def __init__(self, *, scalar_results=None, scalars_results=None, execute_rows=None):
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.execute_rows = list(execute_rows or [])
        self.deleted: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> FakeResult:
        return FakeResult(self.scalars_results.pop(0))

    def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.execute_rows.pop(0))

    def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, instance: object) -> None:
        return None


def _conversation(*, title: str | None = None) -> Conversation:
    row = Conversation(
        id=12,
        user_id=1,
        title=title,
        scope_json={"subject_id": 7, "folder": "数列"},
        created_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    return row


def _message(message_id: int, role: str, content: str) -> Message:
    row = Message(
        id=message_id,
        conversation_id=12,
        role=role,
        content_md=content,
        created_at=datetime(2026, 11, 2, 10, 0, message_id, tzinfo=timezone.utc),
    )
    return row


def test_list_conversations_falls_back_to_first_question_and_scope() -> None:
    conversation = _conversation()
    session = FakeSession(
        execute_rows=[
            [
                (
                    conversation,
                    2,
                    datetime(2026, 11, 2, 10, 0, 1, tzinfo=timezone.utc),
                    "错位相减法怎么用？",
                )
            ]
        ]
    )

    items = qa_service.list_conversations(session, user_id=1, limit=50)

    assert len(items) == 1
    assert items[0].title == "错位相减法怎么用？"
    assert items[0].scope is not None
    assert items[0].scope.folder == "数列"
    assert items[0].message_count == 2


def test_get_conversation_detail_returns_messages_and_citations() -> None:
    conversation = _conversation(title="数列")
    user = _message(30, "user", "问题")
    assistant = _message(31, "assistant", "回答 [1]")
    citation = MessageCitation(
        message_id=31,
        chunk_id=255,
        note_id=55,
        score=0.9,
        snippet="片段",
        page_no=None,
        rank=1,
    )
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[user, assistant]],
        execute_rows=[[(citation, "数列笔记", None, "数列/错位相减")]],
    )

    detail = qa_service.get_conversation_detail(
        session, user_id=1, conversation_id=12
    )

    assert detail.conversation.title == "数列"
    assert detail.conversation.message_count == 2
    assert [item.id for item in detail.messages] == [30, 31]
    assert detail.messages[1].citations[0].index == 1
    assert detail.messages[1].citations[0].title == "数列笔记"
    assert detail.messages[1].citations[0].note_available is True


def test_get_conversation_detail_marks_deleted_note_unavailable() -> None:
    conversation = _conversation()
    assistant = _message(31, "assistant", "回答 [1]")
    citation = MessageCitation(
        message_id=31, chunk_id=255, note_id=55, snippet="片段", rank=1
    )
    session = FakeSession(
        scalar_results=[conversation],
        scalars_results=[[assistant]],
        execute_rows=[
            [(citation, "已删笔记", datetime.now(timezone.utc), "旧章节")]
        ],
    )

    detail = qa_service.get_conversation_detail(
        session, user_id=1, conversation_id=12
    )

    assert detail.messages[0].citations[0].note_available is False


def test_get_conversation_detail_returns_404_for_other_user() -> None:
    session = FakeSession(scalar_results=[None])

    with pytest.raises(NotFoundError):
        qa_service.get_conversation_detail(session, user_id=1, conversation_id=99)
```

- [x] **Step 3: 运行测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_conversations.py -q
```

Expected: `AttributeError: module 'app.services.qa_service' has no attribute 'list_conversations'`。

- [x] **Step 4: 新增 schemas**

在 `backend/app/schemas/qa.py` 顶部加 `from datetime import date, datetime`（保留现有 `date`），并追加：

```python
class QaConversationOut(BaseModel):
    id: str
    title: str
    scope: QaScopeIn | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0


class QaHistoryCitationOut(BaseModel):
    index: int
    note_id: int | None = None
    chunk_id: int | None = None
    title: str | None = None
    heading_path: str | None = None
    page_no: int | None = None
    snippet: str | None = None
    score: float | None = None
    note_available: bool = True


class QaHistoryMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content_md: str
    created_at: datetime
    refused: bool = False
    citations: list[QaHistoryCitationOut] = Field(default_factory=list)


class QaConversationDetailOut(BaseModel):
    conversation: QaConversationOut
    messages: list[QaHistoryMessageOut]
```

- [x] **Step 5: 实现 service 的列表/详情**

在 `qa_service.py` 顶部导入：

```python
from datetime import datetime

from sqlalchemy import func, select
from app.models.note_chunk import NoteChunk
```

在 `QaCitationMeta` 附近追加 dataclass：

```python
@dataclass(frozen=True)
class ConversationSummary:
    id: int
    title: str
    scope: QaScopeIn | None
    created_at: datetime
    last_message_at: datetime | None
    message_count: int


@dataclass(frozen=True)
class ConversationCitation:
    index: int
    note_id: int | None
    chunk_id: int | None
    title: str | None
    heading_path: str | None
    page_no: int | None
    snippet: str | None
    score: float | None
    note_available: bool


@dataclass(frozen=True)
class ConversationMessage:
    id: int
    role: Literal["user", "assistant"]
    content_md: str
    created_at: datetime
    refused: bool
    citations: list[ConversationCitation]


@dataclass(frozen=True)
class ConversationDetail:
    conversation: ConversationSummary
    messages: list[ConversationMessage]
```

在文件末尾追加：

```python
def _display_title(conversation: Conversation, first_question: str | None) -> str:
    raw = conversation.title or first_question or ""
    clean = " ".join(str(raw).split())
    return clean[:50] or "新对话"


def _summary(
    conversation: Conversation,
    *,
    first_question: str | None,
    message_count: int,
    last_message_at: datetime | None,
) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=_display_title(conversation, first_question),
        scope=_stored_scope(conversation),
        created_at=conversation.created_at,
        last_message_at=last_message_at,
        message_count=message_count,
    )


def list_conversations(
    session: Session, *, user_id: int, limit: int = 50
) -> list[ConversationSummary]:
    first_question = (
        select(Message.content_md)
        .where(
            Message.conversation_id == Conversation.id,
            Message.role == "user",
        )
        .order_by(Message.id.asc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    activity = func.coalesce(func.max(Message.created_at), Conversation.created_at)
    rows = session.execute(
        select(
            Conversation,
            func.count(Message.id).label("message_count"),
            func.max(Message.created_at).label("last_message_at"),
            first_question.label("first_question"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .group_by(Conversation.id)
        .order_by(activity.desc(), Conversation.id.desc())
        .limit(limit)
    ).all()
    return [
        _summary(
            conversation,
            first_question=question,
            message_count=int(count),
            last_message_at=last,
        )
        for conversation, count, last, question in rows
    ]


def get_conversation_detail(
    session: Session, *, user_id: int, conversation_id: int
) -> ConversationDetail:
    conversation = _find_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    messages = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.id.asc())
        ).all()
    )
    by_message: dict[int, list[ConversationCitation]] = {
        item.id: [] for item in messages
    }
    if messages:
        rows = session.execute(
            select(
                MessageCitation,
                Note.title,
                Note.deleted_at,
                NoteChunk.heading_path,
            )
            .outerjoin(Note, Note.id == MessageCitation.note_id)
            .outerjoin(NoteChunk, NoteChunk.id == MessageCitation.chunk_id)
            .where(
                MessageCitation.message_id.in_([item.id for item in messages])
            )
            .order_by(MessageCitation.rank.asc(), MessageCitation.id.asc())
        ).all()
        for citation, title, deleted_at, heading_path in rows:
            by_message[citation.message_id].append(
                ConversationCitation(
                    index=citation.rank or 0,
                    note_id=citation.note_id,
                    chunk_id=citation.chunk_id,
                    title=title,
                    heading_path=heading_path,
                    page_no=citation.page_no,
                    snippet=citation.snippet,
                    score=float(citation.score)
                    if citation.score is not None
                    else None,
                    note_available=(
                        citation.note_id is not None
                        and title is not None
                        and deleted_at is None
                    ),
                )
            )
    first_question = next(
        (item.content_md for item in messages if item.role == "user"), None
    )
    last_message_at = max(
        (item.created_at for item in messages), default=None
    )
    return ConversationDetail(
        conversation=_summary(
            conversation,
            first_question=first_question,
            message_count=len(messages),
            last_message_at=last_message_at,
        ),
        messages=[
            ConversationMessage(
                id=item.id,
                role=item.role,  # type: ignore[arg-type]
                content_md=item.content_md,
                created_at=item.created_at,
                refused=(
                    item.role == "assistant"
                    and item.content_md.strip() == REFUSAL_TEXT
                ),
                citations=by_message[item.id],
            )
            for item in messages
        ],
    )
```

- [x] **Step 6: 实现两个 GET 路由**

在 `qa.py` 导入：

```python
from fastapi import APIRouter, Depends, Query, Request
from app.schemas.qa import (
    QaAskRequest,
    QaConversationDetailOut,
    QaConversationOut,
    QaHistoryCitationOut,
    QaHistoryMessageOut,
    QaMessageCitationOut,
)
```

追加映射与路由（放在 `/messages/...` 之前）：

```python
def _conversation_out(item: qa_service.ConversationSummary) -> QaConversationOut:
    return QaConversationOut(
        id=str(item.id),
        title=item.title,
        scope=item.scope,
        created_at=item.created_at,
        last_message_at=item.last_message_at,
        message_count=item.message_count,
    )


@router.get(
    "/conversations",
    response_model=Envelope[list[QaConversationOut]],
    summary="本人会话列表",
)
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[list[QaConversationOut]]:
    items = qa_service.list_conversations(
        session, user_id=current_user.id, limit=limit
    )
    return Envelope(
        trace_id=get_trace_id(), data=[_conversation_out(item) for item in items]
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=Envelope[QaConversationDetailOut],
    summary="本人会话消息与引用",
)
def conversation_messages(
    conversation_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[QaConversationDetailOut]:
    detail = qa_service.get_conversation_detail(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
    messages = [
        QaHistoryMessageOut(
            id=item.id,
            role=item.role,
            content_md=item.content_md,
            created_at=item.created_at,
            refused=item.refused,
            citations=[
                QaHistoryCitationOut(
                    index=item.index,
                    note_id=item.note_id,
                    chunk_id=item.chunk_id,
                    title=item.title,
                    heading_path=item.heading_path,
                    page_no=item.page_no,
                    snippet=item.snippet,
                    score=item.score,
                    note_available=item.note_available,
                )
                for item in item.citations
            ],
        )
        for item in detail.messages
    ]
    return Envelope(
        trace_id=get_trace_id(),
        data=QaConversationDetailOut(
            conversation=_conversation_out(detail.conversation),
            messages=messages,
        ),
    )
```

- [x] **Step 7: 运行 service 测试确认通过**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_conversations.py -q
```

Expected: `4 passed`。

- [x] **Step 8: 写 API 测试**

创建 `backend/tests/test_qa_conversations_api.py`：

```python
"""S3-8 会话接口：TestClient + service monkeypatch，不连库。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.services import qa_service


class FakeSession:
    def __init__(self, user: User) -> None:
        self.user = user

    def scalar(self, statement: object):
        return self.user

    def get(self, entity: type, pk: int):
        raise AssertionError("unexpected get")


def _user(role: str = "student") -> User:
    user = User(
        username=f"s3_8_{role}",
        password_hash="hash",
        nickname="S3-8 测试用户",
        grade=None,
        role=role,
    )
    user.id = 7
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _summary() -> qa_service.ConversationSummary:
    return qa_service.ConversationSummary(
        id=12,
        title="错位相减法",
        scope=None,
        created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        last_message_at=None,
        message_count=2,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_conversations_returns_string_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    monkeypatch.setattr(
        qa_service,
        "list_conversations",
        lambda session, **kwargs: [_summary()],
    )

    response = client.get(
        "/api/v1/qa/conversations", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == "12"
    assert data[0]["message_count"] == 2


def test_list_conversations_rejects_bad_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    response = client.get(
        "/api/v1/qa/conversations?limit=0", headers=_headers(user)
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_conversation_messages_returns_detail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    detail = qa_service.ConversationDetail(
        conversation=_summary(),
        messages=[
            qa_service.ConversationMessage(
                id=31,
                role="assistant",
                content_md="回答 [1]",
                created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                refused=False,
                citations=[
                    qa_service.ConversationCitation(
                        index=1,
                        note_id=55,
                        chunk_id=255,
                        title="数列笔记",
                        heading_path="数列/错位相减",
                        page_no=None,
                        snippet="片段",
                        score=0.9,
                        note_available=True,
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        qa_service,
        "get_conversation_detail",
        lambda session, **kwargs: detail,
    )

    response = client.get(
        "/api/v1/qa/conversations/12/messages", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation"]["id"] == "12"
    assert data["messages"][0]["citations"][0]["index"] == 1


def test_conversation_messages_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "get_conversation_detail", missing)
    response = client.get(
        "/api/v1/qa/conversations/999/messages", headers=_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_conversations_require_student(
    client: TestClient,
) -> None:
    teacher = _user(role="teacher")
    app.dependency_overrides[get_db] = lambda: FakeSession(teacher)
    response = client.get(
        "/api/v1/qa/conversations", headers=_headers(teacher)
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300
```

- [x] **Step 9: 运行 API 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_conversations.py backend/tests/test_qa_conversations_api.py -q
```

Expected: `9 passed`。

- [x] **Step 10: 提交**

```powershell
git add docs/API.md backend/app/schemas/qa.py backend/app/services/qa_service.py backend/app/api/v1/qa.py backend/tests/test_qa_conversations.py backend/tests/test_qa_conversations_api.py
git commit -m "feat(s3-8): 会话列表与消息回放接口"
```

---

### Task 2: 会话重命名与删除

**Files:**
- Modify: `backend/app/schemas/qa.py`
- Modify: `backend/app/services/qa_service.py`
- Modify: `backend/app/api/v1/qa.py`
- Modify: `backend/tests/test_qa_conversations.py`
- Modify: `backend/tests/test_qa_conversations_api.py`

**Interfaces:**
- Consumes: `ConversationSummary`, `_find_conversation`, `InvalidParamError`.
- Produces:
  - `rename_conversation(session, *, user_id: int, conversation_id: int, title: str) -> ConversationSummary`
  - `delete_conversation(session, *, user_id: int, conversation_id: int) -> None`
  - schema `QaConversationRename`
  - routes `PATCH /api/v1/qa/conversations/{conversation_id}`, `DELETE /api/v1/qa/conversations/{conversation_id}`

- [x] **Step 1: 写失败测试**

在 `test_qa_conversations.py` 追加：

```python
def test_rename_conversation_trims_and_returns_summary() -> None:
    conversation = _conversation()
    session = FakeSession(
        scalar_results=[conversation],
        execute_rows=[(2, datetime(2026, 11, 2, 10, 0, 1, tzinfo=timezone.utc))],
    )

    result = qa_service.rename_conversation(
        session, user_id=1, conversation_id=12, title="  新标题  "
    )

    assert conversation.title == "新标题"
    assert result.title == "新标题"
    assert result.message_count == 2
    assert session.commits == 1


def test_rename_conversation_rejects_blank_title() -> None:
    conversation = _conversation()
    session = FakeSession(scalar_results=[conversation])

    with pytest.raises(InvalidParamError):
        qa_service.rename_conversation(
            session, user_id=1, conversation_id=12, title="   "
        )


def test_delete_conversation_deletes_owned_row() -> None:
    conversation = _conversation()
    session = FakeSession(scalar_results=[conversation])

    qa_service.delete_conversation(session, user_id=1, conversation_id=12)

    assert session.deleted == [conversation]
    assert session.commits == 1
```

导入补 `InvalidParamError`：

```python
from app.core.exceptions import InvalidParamError, NotFoundError
```

- [x] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_conversations.py -q
```

Expected: `AttributeError: ... has no attribute 'rename_conversation'`。

- [x] **Step 3: 实现 service**

在 `qa_service.py` 末尾追加：

```python
def rename_conversation(
    session: Session, *, user_id: int, conversation_id: int, title: str
) -> ConversationSummary:
    conversation = _find_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    clean = " ".join(title.split())
    if not clean:
        raise InvalidParamError("会话标题不能为空")
    conversation.title = clean[:80]
    session.commit()
    count, last = session.execute(
        select(func.count(Message.id), func.max(Message.created_at)).where(
            Message.conversation_id == conversation.id
        )
    ).one()
    return _summary(
        conversation,
        first_question=None,
        message_count=int(count),
        last_message_at=last,
    )


def delete_conversation(
    session: Session, *, user_id: int, conversation_id: int
) -> None:
    conversation = _find_conversation(
        session, user_id=user_id, conversation_id=conversation_id
    )
    session.delete(conversation)
    session.commit()
```

- [x] **Step 4: 新增 schema 与路由**

`schemas/qa.py` 加：

```python
class QaConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        clean = " ".join(value.split())
        if not clean:
            raise ValueError("title 不能为空")
        return clean
```

`qa.py` 加导入：

```python
from app.schemas.qa import QaConversationRename
```

（`DELETE` 直接写 `status_code=204`，不引入 `status` 常量。）

在 GET 详情路由后追加：

```python
@router.patch(
    "/conversations/{conversation_id}",
    response_model=Envelope[QaConversationOut],
    summary="重命名本人会话",
)
def rename_conversation(
    conversation_id: int,
    payload: QaConversationRename,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[QaConversationOut]:
    item = qa_service.rename_conversation(
        session,
        user_id=current_user.id,
        conversation_id=conversation_id,
        title=payload.title,
    )
    return Envelope(trace_id=get_trace_id(), data=_conversation_out(item))


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    response_model=None,
    summary="删除本人会话",
)
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> None:
    qa_service.delete_conversation(
        session, user_id=current_user.id, conversation_id=conversation_id
    )
```

- [x] **Step 5: 写 API 测试**

在 `test_qa_conversations_api.py` 追加：

```python
def test_rename_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    monkeypatch.setattr(
        qa_service,
        "rename_conversation",
        lambda session, **kwargs: _summary(),
    )

    response = client.patch(
        "/api/v1/qa/conversations/12",
        headers=_headers(user),
        json={"title": "新标题"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == "12"


def test_rename_conversation_rejects_blank_title(
    client: TestClient,
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    response = client.patch(
        "/api/v1/qa/conversations/12",
        headers=_headers(user),
        json={"title": "   "},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_delete_conversation_returns_204(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    called = {}
    monkeypatch.setattr(
        qa_service,
        "delete_conversation",
        lambda session, **kwargs: called.update(kwargs),
    )

    response = client.delete(
        "/api/v1/qa/conversations/12", headers=_headers(user)
    )

    assert response.status_code == 204
    assert called["conversation_id"] == 12


def test_delete_conversation_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "delete_conversation", missing)
    response = client.delete(
        "/api/v1/qa/conversations/999", headers=_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40400
```

- [x] **Step 6: 运行后端会话测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_conversations.py backend/tests/test_qa_conversations_api.py -q
```

Expected: `13 passed`。

- [x] **Step 7: 跑 QA 回归**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py backend/tests/test_qa_api.py backend/tests/test_qa_cache_flow.py -q
```

Expected: 全部通过。

- [x] **Step 8: 提交**

```powershell
git add backend/app/schemas/qa.py backend/app/services/qa_service.py backend/app/api/v1/qa.py backend/tests/test_qa_conversations.py backend/tests/test_qa_conversations_api.py
git commit -m "feat(s3-8): 会话重命名与删除接口"
```

---

### Task 3: 前端类型、SSE 解析与会话 API

**Files:**
- Create: `web/src/types/qa.ts`
- Create: `web/src/utils/sse.ts`
- Create: `web/src/utils/sse.spec.ts`
- Create: `web/src/api/qa.ts`
- Create: `web/src/api/qa.spec.ts`

**Interfaces:**
- Produces `SseEvent`, `parseSseFrame`, `readSseStream`, `QaRequestError`, `askQuestion`, `listConversations`, `getConversationMessages`, `renameConversation`, `deleteConversation`.

- [x] **Step 1: 写失败测试**

`web/src/utils/sse.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { parseSseFrame, readSseStream } from './sse'

function bodyOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe('sse', () => {
  it('parses event and multi-line data', () => {
    const event = parseSseFrame('event: meta\ndata: {"a":1}\ndata: {"b":2}')
    expect(event).toEqual({ event: 'meta', data: '{"a":1}\n{"b":2}' })
  })

  it('parses CRLF and ignores comments', () => {
    const event = parseSseFrame(': keepalive\r\nevent: delta\r\ndata: {"text":"hi"}')
    expect(event?.event).toBe('delta')
    expect(event?.data).toBe('{"text":"hi"}')
  })

  it('reads frames across chunks and decodes UTF-8', async () => {
    const events = []
    for await (const event of readSseStream(
      bodyOf(['event: delta\ndata: {"text":"错', '位相减"}\n\n']),
    )) {
      events.push(event)
    }
    expect(events).toHaveLength(1)
    expect(events[0].data).toContain('错位相减')
  })

  it('returns null for a comment-only frame', () => {
    expect(parseSseFrame(': ping')).toBeNull()
  })
})
```

`web/src/api/qa.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { QaRequestError, askQuestion } from './qa'

describe('askQuestion', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('throws a readable error for a JSON HTTP error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: 40400, message: '会话不存在' }), {
          status: 404,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(
      askQuestion({ question: '问题' }, { onMeta: vi.fn(), onDelta: vi.fn(), onDone: vi.fn() }),
    ).rejects.toMatchObject({ message: '会话不存在', status: 404 })
  })

  it('dispatches meta/delta/done in order', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          'event: meta\ndata: {"conversation_id":"12","user_message_id":30,"citations":[]}\n\n' +
            'event: delta\ndata: {"text":"你好"}\n\n' +
            'event: done\ndata: {"message_id":31,"conversation_id":"12","tokens":1,"latency_ms":2,"refused":false,"suggestions":[],"cached":false}\n\n',
          { status: 200, headers: { 'content-type': 'text/event-stream' } },
        ),
      ),
    )
    const calls: string[] = []
    await askQuestion(
      { question: '你好' },
      {
        onMeta: () => calls.push('meta'),
        onDelta: () => calls.push('delta'),
        onDone: () => calls.push('done'),
      },
    )
    expect(calls).toEqual(['meta', 'delta', 'done'])
  })
})
```

- [x] **Step 2: 运行确认失败**

```powershell
cd web
npm run test:run -- src/utils/sse.spec.ts src/api/qa.spec.ts
```

Expected: 模块不存在 / 导出不存在。

- [x] **Step 3: 写类型**

`web/src/types/qa.ts`：

```ts
export interface QaScope {
  subject_id?: number | null
  folder?: string | null
  start_date?: string | null
  end_date?: string | null
}

export interface QaCitation {
  index: number
  note_id: number | null
  chunk_id: number | null
  title: string | null
  heading_path: string | null
  page_no: number | null
  snippet: string | null
  score?: number | null
  note_available?: boolean
}

export interface QaConversation {
  id: string
  title: string
  scope: QaScope | null
  created_at: string
  last_message_at: string | null
  message_count: number
}

export interface QaMessage {
  id: number
  role: 'user' | 'assistant'
  content_md: string
  created_at: string
  refused: boolean
  citations: QaCitation[]
}

export interface QaSuggestion {
  type: 'rephrase' | 'note'
  text: string
  note_id: number | null
}

export interface QaDoneData {
  message_id: number
  conversation_id: string
  tokens: number
  latency_ms: number
  refused: boolean
  refusal_reason: string | null
  suggestions: QaSuggestion[]
  cached: boolean
}

export interface QaMetaData {
  conversation_id: string
  user_message_id: number
  citations: QaCitation[]
}

export interface QaConversationDetail {
  conversation: QaConversation
  messages: QaMessage[]
}

export interface QaAskPayload {
  question: string
  scope?: QaScope | null
  conversation_id?: string | null
}
```

- [x] **Step 4: 写 SSE 解析**

`web/src/utils/sse.ts`：

```ts
export interface SseEvent {
  event: string
  data: string
}

export function parseSseFrame(frame: string): SseEvent | null {
  const lines = frame.split(/\r?\n/)
  let event = 'message'
  const data: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const raw = colon === -1 ? '' : line.slice(colon + 1)
    const value = raw.startsWith(' ') ? raw.slice(1) : raw
    if (field === 'event') event = value || 'message'
    if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  return { event, data: data.join('\n') }
}

export async function* readSseStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n?/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseSseFrame(frame)
        if (event) yield event
      }
    }
    buffer += decoder.decode()
    buffer = buffer.replace(/\r\n?/g, '\n')
    if (buffer.trim()) {
      const event = parseSseFrame(buffer)
      if (event) yield event
    }
  } finally {
    reader.releaseLock()
  }
}
```

- [x] **Step 5: 写 API 客户端**

`web/src/api/qa.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type {
  QaAskPayload,
  QaConversation,
  QaConversationDetail,
  QaDoneData,
  QaMetaData,
} from '@/types/qa'
import { readSseStream } from '@/utils/sse'

export class QaRequestError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly code = 0,
  ) {
    super(message)
    this.name = 'QaRequestError'
  }
}

export interface QaAskHandlers {
  onMeta: (data: QaMetaData) => void
  onDelta: (text: string) => void
  onDone: (data: QaDoneData) => void
}

export async function listConversations(limit = 50): Promise<QaConversation[]> {
  const resp = await http.get<ApiEnvelope<QaConversation[]>>(
    `${API_PREFIX}/qa/conversations`,
    { params: { limit } },
  )
  return resp.data.data
}

export async function getConversationMessages(
  conversationId: string,
): Promise<QaConversationDetail> {
  const resp = await http.get<ApiEnvelope<QaConversationDetail>>(
    `${API_PREFIX}/qa/conversations/${conversationId}/messages`,
  )
  return resp.data.data
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<QaConversation> {
  const resp = await http.patch<ApiEnvelope<QaConversation>>(
    `${API_PREFIX}/qa/conversations/${conversationId}`,
    { title },
  )
  return resp.data.data
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await http.delete(`${API_PREFIX}/qa/conversations/${conversationId}`)
}

export async function askQuestion(
  payload: QaAskPayload,
  handlers: QaAskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const base = import.meta.env.VITE_API_BASE ?? ''
  const token = useAuthStore().token
  const response = await fetch(`${base}${API_PREFIX}/qa/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    let message = '请求失败'
    let code = 0
    try {
      const body = (await response.json()) as { message?: string; code?: number }
      message = body.message ?? message
      code = body.code ?? 0
    } catch {
      // 非 JSON 错误体不暴露原始内容。
    }
    throw new QaRequestError(message, response.status, code)
  }
  if (!response.body) {
    throw new QaRequestError('服务器没有返回数据流', response.status)
  }

  let sawDone = false
  for await (const event of readSseStream(response.body)) {
    let data: unknown
    try {
      data = JSON.parse(event.data)
    } catch {
      throw new QaRequestError('SSE 数据格式错误')
    }
    if (event.event === 'meta') {
      handlers.onMeta(data as QaMetaData)
    } else if (event.event === 'delta') {
      handlers.onDelta(String((data as { text?: string }).text ?? ''))
    } else if (event.event === 'done') {
      sawDone = true
      handlers.onDone(data as QaDoneData)
    } else if (event.event === 'error') {
      throw new QaRequestError(
        String((data as { message?: string }).message ?? '生成失败'),
      )
    }
  }
  if (!sawDone) throw new QaRequestError('连接提前结束，未收到完成事件')
}
```

- [x] **Step 6: 运行前端基础测试**

```powershell
npm run test:run -- src/utils/sse.spec.ts src/api/qa.spec.ts
```

Expected: `6 passed`。

- [x] **Step 7: 提交**

```powershell
git add web/src/types/qa.ts web/src/utils/sse.ts web/src/utils/sse.spec.ts web/src/api/qa.ts web/src/api/qa.spec.ts
git commit -m "feat(s3-8): 会话 API 与 SSE 流解析"
```

---

### Task 4: 打字机与引用高亮纯函数

**Files:**
- Create: `web/src/utils/typewriter.ts`
- Create: `web/src/utils/typewriter.spec.ts`
- Create: `web/src/utils/highlight.ts`
- Create: `web/src/utils/highlight.spec.ts`

**Interfaces:**
- Produces:
  - `createTypewriter(options): Typewriter`，`Typewriter.push/flush/cancel/isIdle`
  - `highlightSnippet(root: HTMLElement, snippet: string): HTMLElement | null`
  - `scrollToHeading(root: HTMLElement, headingPath: string | null): HTMLElement | null`

- [x] **Step 1: 写失败测试**

`web/src/utils/typewriter.spec.ts`：

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createTypewriter } from './typewriter'

describe('createTypewriter', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reveals buffered text in chunks', () => {
    vi.useFakeTimers()
    let text = ''
    const writer = createTypewriter({
      onUpdate: (value) => {
        text = value
      },
      charsPerTick: 2,
      intervalMs: 10,
    })
    writer.push('abcdef')
    vi.advanceTimersByTime(10)
    expect(text).toBe('ab')
    vi.advanceTimersByTime(20)
    expect(text).toBe('abcdef')
  })

  it('calls onDrained once after the queue empties', () => {
    vi.useFakeTimers()
    const drained = vi.fn()
    const writer = createTypewriter({
      onUpdate: vi.fn(),
      onDrained: drained,
      charsPerTick: 5,
      intervalMs: 10,
    })
    writer.push('abc')
    vi.advanceTimersByTime(20)
    expect(drained).toHaveBeenCalledTimes(1)
  })

  it('flush reveals everything and cancel drops pending text', () => {
    vi.useFakeTimers()
    let text = ''
    const writer = createTypewriter({
      onUpdate: (value) => {
        text = value
      },
      charsPerTick: 1,
      intervalMs: 10,
    })
    writer.push('abc')
    writer.flush()
    expect(text).toBe('abc')
    expect(writer.isIdle()).toBe(true)

    writer.push('def')
    writer.cancel()
    expect(writer.isIdle()).toBe(true)
    vi.advanceTimersByTime(50)
    expect(text).toBe('abc')
  })
})
```

`web/src/utils/highlight.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { highlightSnippet, scrollToHeading } from './highlight'

describe('highlightSnippet', () => {
  it('marks a plain substring and returns the mark', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>错位相减法很好用</p>'
    const mark = highlightSnippet(root, '错位相减')
    expect(mark?.textContent).toBe('错位相减')
    expect(root.querySelector('mark.citation-hit')).not.toBeNull()
  })

  it('matches across nested text nodes', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>先看<strong>错位</strong>相减法</p>'
    const mark = highlightSnippet(root, '错位相减法')
    expect(mark).not.toBeNull()
    expect(root.textContent).toContain('错位相减法')
  })

  it('normalizes whitespace and returns null when missing', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>第一段   第二段</p>'
    expect(highlightSnippet(root, '第一段 第二段')).not.toBeNull()
    expect(highlightSnippet(root, '不存在')).toBeNull()
  })
})

describe('scrollToHeading', () => {
  it('finds the last heading segment', () => {
    const root = document.createElement('div')
    root.innerHTML = '<h2>数列/错位相减法</h2>'
    expect(scrollToHeading(root, '数列/错位相减法')?.textContent).toBe(
      '数列/错位相减法',
    )
    expect(scrollToHeading(root, null)).toBeNull()
  })
})
```

- [x] **Step 2: 运行确认失败**

```powershell
cd web
npm run test:run -- src/utils/typewriter.spec.ts src/utils/highlight.spec.ts
```

Expected: 模块不存在。

- [x] **Step 3: 实现 typewriter**

`web/src/utils/typewriter.ts`：

```ts
export interface TypewriterOptions {
  onUpdate: (text: string) => void
  onDrained?: () => void
  charsPerTick?: number
  intervalMs?: number
}

export interface Typewriter {
  push: (text: string) => void
  flush: () => void
  cancel: () => void
  isIdle: () => boolean
}

export function createTypewriter(options: TypewriterOptions): Typewriter {
  const charsPerTick = options.charsPerTick ?? 12
  const intervalMs = options.intervalMs ?? 16
  let visible = ''
  let pending = ''
  let timer: ReturnType<typeof setInterval> | null = null
  let drained = false

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function tick(): void {
    if (!pending) {
      stop()
      if (!drained) {
        drained = true
        options.onDrained?.()
      }
      return
    }
    visible += pending.slice(0, charsPerTick)
    pending = pending.slice(charsPerTick)
    options.onUpdate(visible)
  }

  function start(): void {
    if (timer !== null) return
    drained = false
    timer = setInterval(tick, intervalMs)
  }

  return {
    push(text: string) {
      if (!text) return
      pending += text
      start()
    },
    flush() {
      stop()
      if (pending) {
        visible += pending
        pending = ''
        options.onUpdate(visible)
      }
      if (!drained) {
        drained = true
        options.onDrained?.()
      }
    },
    cancel() {
      stop()
      pending = ''
      visible = ''
      drained = true
    },
    isIdle() {
      return pending.length === 0
    },
  }
}
```

- [x] **Step 4: 实现 highlight**

`web/src/utils/highlight.ts`：

```ts
export function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

interface CharRef {
  node: Text
  offset: number
}

function collectChars(root: HTMLElement): { text: string; refs: CharRef[] } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const refs: CharRef[] = []
  let text = ''
  let previousSpace = true
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    const parent = node.parentElement
    if (!parent || ['SCRIPT', 'STYLE'].includes(parent.tagName)) continue
    const raw = node.data
    for (let offset = 0; offset < raw.length; offset += 1) {
      const char = raw[offset]
      if (/\s/.test(char)) {
        if (!previousSpace && text.length > 0) {
          text += ' '
          refs.push({ node, offset })
          previousSpace = true
        }
        continue
      }
      text += char
      refs.push({ node, offset })
      previousSpace = false
    }
  }
  const trimmed = text.replace(/\s+$/, '')
  return { text: trimmed, refs: refs.slice(0, trimmed.length) }
}

function markNode(node: Text, start: number, end: number): HTMLElement | null {
  if (start >= end) return null
  const range = document.createRange()
  range.setStart(node, start)
  range.setEnd(node, end)
  const mark = document.createElement('mark')
  mark.className = 'citation-hit'
  try {
    range.surroundContents(mark)
    return mark
  } catch {
    return null
  }
}

export function highlightSnippet(
  root: HTMLElement,
  snippet: string,
): HTMLElement | null {
  const needle = normalizeText(snippet)
  if (!needle) return null
  const { text, refs } = collectChars(root)
  const start = text.indexOf(needle)
  if (start === -1) return null
  const end = start + needle.length
  const selected = refs.slice(start, end)
  const byNode = new Map<Text, { start: number; end: number }>()
  for (const ref of selected) {
    const current = byNode.get(ref.node)
    if (current === null || current === undefined) {
      byNode.set(ref.node, { start: ref.offset, end: ref.offset + 1 })
    } else {
      current.start = Math.min(current.start, ref.offset)
      current.end = Math.max(current.end, ref.offset + 1)
    }
  }
  let first: HTMLElement | null = null
  const entries = [...byNode.entries()].sort((a, b) => {
    if (a[0] === b[0]) return 0
    return a[0].compareDocumentPosition(b[0]) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
  })
  for (const [node, range] of entries.reverse()) {
    const mark = markNode(node, range.start, range.end)
    if (mark) first = mark
  }
  first?.scrollIntoView?.({ block: 'center' })
  return first
}

export function scrollToHeading(
  root: HTMLElement,
  headingPath: string | null,
): HTMLElement | null {
  const last = headingPath?.split('/').filter(Boolean).pop()
  if (!last) return null
  const headings = [...root.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')]
  const target = headings.find((item) => item.textContent?.includes(last))
  target?.scrollIntoView?.({ block: 'center' })
  return target ?? null
}
```

- [x] **Step 5: 运行测试**

```powershell
npm run test:run -- src/utils/typewriter.spec.ts src/utils/highlight.spec.ts
```

Expected: `6 passed`。

- [x] **Step 6: 提交**

```powershell
git add web/src/utils/typewriter.ts web/src/utils/typewriter.spec.ts web/src/utils/highlight.ts web/src/utils/highlight.spec.ts
git commit -m "feat(s3-8): 打字机与引用高亮工具"
```

---

### Task 5: 引用卡片与消息组件

**Files:**
- Create: `web/src/components/qa/CitationCard.vue`
- Create: `web/src/components/qa/CitationCard.spec.ts`
- Create: `web/src/components/qa/ChatMessage.vue`
- Create: `web/src/components/qa/ChatMessage.spec.ts`

**Interfaces:**
- `CitationCard` props `citation: QaCitation`; emits `open(citation)`.
- `ChatMessage` props `message`（包含 `id/role/content_md/refused/error/streaming/done`）; emits `citation(citation)`.
- `ChatMessage` 使用 `MdPreview`，测试用 stub 注入。

- [x] **Step 1: 写失败测试**

`CitationCard.spec.ts`：

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CitationCard from './CitationCard.vue'

const citation = {
  index: 1,
  note_id: 55,
  chunk_id: 255,
  title: '数列笔记',
  heading_path: '数列/错位相减法',
  page_no: 2,
  snippet: '错位相减法正文',
  score: 0.91,
  note_available: true,
}

describe('CitationCard', () => {
  it('renders metadata and emits open', async () => {
    const wrapper = mount(CitationCard, { props: { citation } })
    expect(wrapper.text()).toContain('数列笔记')
    expect(wrapper.text()).toContain('数列/错位相减法')
    expect(wrapper.text()).toContain('第 2 页')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ note_id: 55 })
  })

  it('disables the button when the note is unavailable', () => {
    const wrapper = mount(CitationCard, {
      props: { citation: { ...citation, note_available: false } },
    })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('原笔记已删除')
  })
})
```

`ChatMessage.spec.ts`：

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatMessage from './ChatMessage.vue'

const PreviewStub = {
  props: ['modelValue'],
  template: '<div class="preview">{{ modelValue }}</div>',
}

function mountMessage(overrides = {}) {
  return mount(ChatMessage, {
    props: {
      message: {
        id: 31,
        role: 'assistant',
        content_md: '回答 [1]',
        created_at: '2026-11-02T10:00:00+00:00',
        refused: false,
        citations: [],
        error: '',
        streaming: false,
        done: null,
        ...overrides,
      },
    },
    global: { stubs: { MdPreview: PreviewStub } },
  })
}

describe('ChatMessage', () => {
  it('renders assistant markdown through MdPreview', () => {
    const wrapper = mountMessage()
    expect(wrapper.find('.preview').text()).toContain('回答')
  })

  it('styles refusals and shows suggestions', () => {
    const wrapper = mountMessage({
      refused: true,
      content_md: '暂时无法回答',
      done: {
        suggestions: [{ type: 'rephrase', text: '换个问法', note_id: null }],
      },
    })
    expect(wrapper.classes()).toContain('refused')
    expect(wrapper.text()).toContain('换个问法')
  })

  it('shows an error state', () => {
    const wrapper = mountMessage({ error: '生成失败' })
    expect(wrapper.text()).toContain('生成失败')
  })
})
```

- [x] **Step 2: 运行确认失败**

```powershell
npm run test:run -- src/components/qa/CitationCard.spec.ts src/components/qa/ChatMessage.spec.ts
```

Expected: 组件不存在。

- [x] **Step 3: 实现 CitationCard**

`CitationCard.vue`：

```vue
<script setup lang="ts">
import type { QaCitation } from '@/types/qa'

const props = defineProps<{ citation: QaCitation }>()
const emit = defineEmits<{ open: [citation: QaCitation] }>()

function onClick(): void {
  if (props.citation.note_available === false || props.citation.note_id === null) return
  emit('open', props.citation)
}
</script>

<template>
  <button
    class="citation-card"
    type="button"
    :disabled="citation.note_available === false || citation.note_id === null"
    @click="onClick"
  >
    <span class="citation-index">[{{ citation.index }}]</span>
    <span class="citation-title">{{ citation.title || '未命名笔记' }}</span>
    <span v-if="citation.heading_path" class="citation-path">{{ citation.heading_path }}</span>
    <span v-if="citation.page_no" class="citation-page">第 {{ citation.page_no }} 页</span>
    <span v-if="citation.snippet" class="citation-snippet">{{ citation.snippet }}</span>
    <span v-if="citation.note_available === false" class="citation-missing">原笔记已删除</span>
  </button>
</template>

<style scoped>
.citation-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 8px;
  width: 100%;
  padding: 10px 12px;
  color: var(--app-text);
  text-align: left;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.citation-card:hover:not(:disabled) {
  border-color: var(--app-primary);
  background: var(--app-primary-soft);
}

.citation-card:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.citation-index {
  color: var(--app-primary);
  font-weight: 600;
}

.citation-title {
  font-weight: 600;
}

.citation-path,
.citation-page,
.citation-snippet,
.citation-missing {
  grid-column: 2;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.citation-snippet {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.citation-missing {
  color: var(--app-danger);
}
</style>
```

- [x] **Step 4: 实现 ChatMessage**

`ChatMessage.vue`：

```vue
<script setup lang="ts">
import { MdPreview } from 'md-editor-v3'

import CitationCard from '@/components/qa/CitationCard.vue'
import type { QaCitation } from '@/types/qa'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

export interface QaUiMessage {
  id: number
  role: 'user' | 'assistant'
  content_md: string
  created_at: string
  refused: boolean
  citations: QaCitation[]
  error: string
  streaming: boolean
  done: {
    tokens: number
    latency_ms: number
    cached: boolean
    suggestions: { type: string; text: string; note_id: number | null }[]
  } | null
}

const props = defineProps<{ message: QaUiMessage }>()
const emit = defineEmits<{
  citation: [citation: QaCitation]
  suggestion: [text: string]
}>()

function onSuggestion(text: string): void {
  emit('suggestion', text)
}
</script>

<template>
  <article
    class="chat-message"
    :class="[message.role, { refused: message.refused, failed: Boolean(message.error) }]"
    :data-testid="`message-${message.id}`"
  >
    <div class="message-meta">
      <span>{{ message.role === 'user' ? '我' : '知序' }}</span>
      <span v-if="message.done?.cached" class="badge">缓存命中</span>
      <span v-if="message.streaming" class="badge">生成中…</span>
    </div>
    <div v-if="message.role === 'user'" class="user-text">{{ message.content_md }}</div>
    <template v-else>
      <MdPreview
        v-if="message.content_md"
        :model-value="message.content_md"
        :no-mermaid="true"
        preview-theme="github"
        code-theme="atom"
      />
      <p v-if="message.error" class="message-error" role="alert">{{ message.error }}</p>
      <p v-if="message.refused" class="refusal-tip">未在资料中找到可靠依据，建议换问法或补充笔记。</p>
      <div v-if="message.citations.length" class="citation-list">
        <CitationCard
          v-for="citation in message.citations"
          :key="citation.index"
          :citation="citation"
          @open="emit('citation', $event)"
        />
      </div>
      <div v-if="message.done?.suggestions.length" class="suggestions">
        <button
          v-for="item in message.done.suggestions"
          :key="item.text"
          type="button"
          class="suggestion"
          @click="onSuggestion(item.text)"
        >
          {{ item.text }}
        </button>
      </div>
      <p v-if="message.done" class="usage">
        {{ message.done.tokens }} tokens · {{ (message.done.latency_ms / 1000).toFixed(1) }}s
      </p>
    </template>
  </article>
</template>

<style scoped>
.chat-message {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.chat-message.user {
  margin-left: 15%;
  background: var(--app-primary-soft);
  border-color: transparent;
}

.chat-message.refused {
  border-color: var(--app-warning);
}

.chat-message.failed {
  border-color: var(--app-danger);
}

.message-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.badge {
  padding: 1px 6px;
  color: var(--app-primary-strong);
  background: var(--app-primary-soft);
  border-radius: 999px;
}

.user-text {
  white-space: pre-wrap;
}

.message-error {
  margin: 0;
  color: var(--app-danger);
}

.refusal-tip {
  margin: 0;
  padding: 8px 10px;
  color: var(--app-warning);
  background: #fff4e6;
  border-radius: var(--app-radius-sm);
}

.citation-list,
.suggestions {
  display: grid;
  gap: 6px;
}

.suggestion {
  justify-self: start;
  padding: 4px 8px;
  color: var(--app-primary-strong);
  background: var(--app-primary-soft);
  border: none;
  border-radius: 999px;
  cursor: pointer;
}

.usage {
  margin: 0;
  color: var(--app-text-tertiary);
  font-size: 11px;
}
</style>
```

注意：`QaUiMessage` 从 `.vue` 的 `<script setup>` 导出类型在 Vue 编译下不保证可被外部 import；若类型检查报错，把 `QaUiMessage` 移到 `web/src/types/qa.ts`，组件从那里 import。**计划统一选择后者**：在 `types/qa.ts` 追加 `QaUiMessage`，`ChatMessage.vue` 不导出 interface。

- [x] **Step 5: 把 UI 消息类型放 types**

在 `types/qa.ts` 追加：

```ts
export interface QaUiMessage extends QaMessage {
  localId: string
  error: string
  streaming: boolean
  done: {
    tokens: number
    latency_ms: number
    cached: boolean
    suggestions: QaSuggestion[]
  } | null
}
```

并让 `ChatMessage.vue` 从 `@/types/qa` import `QaUiMessage`，删除组件内 interface。

- [x] **Step 6: 运行组件测试**

```powershell
npm run test:run -- src/components/qa/CitationCard.spec.ts src/components/qa/ChatMessage.spec.ts
```

Expected: `5 passed`。

- [x] **Step 7: 提交**

```powershell
git add web/src/types/qa.ts web/src/components/qa/CitationCard.vue web/src/components/qa/CitationCard.spec.ts web/src/components/qa/ChatMessage.vue web/src/components/qa/ChatMessage.spec.ts
git commit -m "feat(s3-8): 消息与引用卡片组件"
```

---

### Task 6: `/qa` 会话页、scope 与流式集成

**Files:**
- Create: `web/src/views/qa/scope.ts`
- Create: `web/src/views/qa/scope.spec.ts`
- Create: `web/src/views/qa/Chat.vue`
- Create: `web/src/views/qa/Chat.spec.ts`
- Modify: `web/src/router/index.ts`

**Interfaces:**
- Consumes:
  - `listConversations/getConversationMessages/renameConversation/deleteConversation/askQuestion` from `@/api/qa`
  - `listSubjects` from `@/api/kp`
  - `CitationCard/ChatMessage` components
  - `createTypewriter` 与 `QaUiMessage`
- Produces: route `/qa` → `Chat.vue`，`meta.roles=['student']`。

- [x] **Step 1: 写 scope 失败测试**

`web/src/views/qa/scope.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { toScopePayload } from './scope'

describe('toScopePayload', () => {
  it('drops empty fields and trims folder', () => {
    expect(
      toScopePayload({
        subjectId: null,
        folder: '  数列  ',
        dateRange: null,
      }),
    ).toEqual({ folder: '数列' })
  })

  it('maps date range to ISO dates', () => {
    expect(
      toScopePayload({
        subjectId: 7,
        folder: '',
        dateRange: ['2026-01-01', '2026-02-01'],
      }),
    ).toEqual({ subject_id: 7, start_date: '2026-01-01', end_date: '2026-02-01' })
  })

  it('returns null when nothing is selected', () => {
    expect(
      toScopePayload({ subjectId: null, folder: '  ', dateRange: null }),
    ).toBeNull()
  })

  it('rejects an inverted date range', () => {
    expect(() =>
      toScopePayload({
        subjectId: null,
        folder: '',
        dateRange: ['2026-02-01', '2026-01-01'],
      }),
    ).toThrow('结束日期不能早于开始日期')
  })
})
```

- [x] **Step 2: 运行确认失败**

```powershell
npm run test:run -- src/views/qa/scope.spec.ts
```

Expected: 模块不存在。

- [x] **Step 3: 实现 scope**

`web/src/views/qa/scope.ts`：

```ts
import type { QaScope } from '@/types/qa'

export interface ScopeForm {
  subjectId: number | null
  folder: string
  dateRange: [string, string] | null
}

export function toScopePayload(form: ScopeForm): QaScope | null {
  const folder = form.folder.trim()
  const start = form.dateRange?.[0] ?? null
  const end = form.dateRange?.[1] ?? null
  if (start && end && end < start) {
    throw new Error('结束日期不能早于开始日期')
  }
  const scope: QaScope = {}
  if (form.subjectId !== null) scope.subject_id = form.subjectId
  if (folder) scope.folder = folder
  if (start) scope.start_date = start
  if (end) scope.end_date = end
  return Object.keys(scope).length ? scope : null
}
```

- [x] **Step 4: 实现 Chat.vue**

`<script setup lang="ts">` 的主体：

```ts
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listSubjects } from '@/api/kp'
import {
  askQuestion,
  deleteConversation,
  getConversationMessages,
  listConversations,
  renameConversation,
} from '@/api/qa'
import ChatMessage from '@/components/qa/ChatMessage.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import type { QaCitation, QaConversation, QaDoneData, QaMessage, QaUiMessage } from '@/types/qa'
import { createTypewriter, type Typewriter } from '@/utils/typewriter'
import { toScopePayload, type ScopeForm } from '@/views/qa/scope'

const route = useRoute()
const router = useRouter()
const conversations = ref<QaConversation[]>([])
const messages = ref<QaUiMessage[]>([])
const subjects = ref<{ id: number; name: string }[]>([])
const activeId = ref<string | null>(null)
const loadingList = ref(false)
const loadingMessages = ref(false)
const listError = ref('')
const streaming = ref(false)
const question = ref('')
const subjectId = ref<number | null>(null)
const folder = ref('')
const dateRange = ref<[string, string] | null>(null)
const scrollHost = ref<HTMLElement | null>(null)

let controller: AbortController | null = null
let writer: Typewriter | null = null
let tempId = 0
let scrollTicket = 0

const hasMessages = computed(() => messages.value.length > 0)

function scheduleScroll(): void {
  if (scrollTicket) return
  scrollTicket = window.setTimeout(() => {
    scrollTicket = 0
    const host = scrollHost.value
    if (host) host.scrollTop = host.scrollHeight
  }, 16)
}

function toUi(item: QaMessage): QaUiMessage {
  return {
    ...item,
    localId: `server-${item.id}`,
    error: '',
    streaming: false,
    done: null,
  }
}

function resetScope(): void {
  subjectId.value = null
  folder.value = ''
  dateRange.value = null
}

function applyConversationScope(conversation: QaConversation): void {
  subjectId.value = conversation.scope?.subject_id ?? null
  folder.value = conversation.scope?.folder ?? ''
  const start = conversation.scope?.start_date
  const end = conversation.scope?.end_date
  dateRange.value = start && end ? [start, end] : null
}

function stopStream(): void {
  controller?.abort()
  controller = null
  writer?.cancel()
  writer = null
  streaming.value = false
}

async function loadConversations(preferred?: string | null): Promise<void> {
  loadingList.value = true
  listError.value = ''
  try {
    const items = await listConversations()
    conversations.value = items
    const target = preferred ?? activeId.value ?? route.query.conversation
    const id = typeof target === 'string' && items.some((item) => item.id === target)
      ? target
      : items[0]?.id ?? null
    if (id && id !== activeId.value) await selectConversation(id)
    else if (id && activeId.value === id) {
      const current = items.find((item) => item.id === id)
      if (current) applyConversationScope(current)
    }
  } catch {
    listError.value = '会话列表加载失败'
  } finally {
    loadingList.value = false
  }
}

async function selectConversation(id: string): Promise<void> {
  stopStream()
  activeId.value = id
  loadingMessages.value = true
  try {
    const detail = await getConversationMessages(id)
    messages.value = detail.messages.map(toUi)
    applyConversationScope(detail.conversation)
    await router.replace({ name: 'qa', query: { conversation: id } })
    await nextTick()
    scheduleScroll()
  } catch {
    messages.value = []
    ElMessage.error('会话消息加载失败')
  } finally {
    loadingMessages.value = false
  }
}

function newConversation(): void {
  stopStream()
  activeId.value = null
  messages.value = []
  resetScope()
  void router.replace({ name: 'qa' })
}

async function send(): Promise<void> {
  const text = question.value.trim()
  if (!text || streaming.value) return
  let scope
  try {
    scope = toScopePayload({
      subjectId: subjectId.value,
      folder: folder.value,
      dateRange: dateRange.value,
    })
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '范围不合法')
    return
  }
  question.value = ''
  const localId = `local-${++tempId}`
  const userMessage: QaUiMessage = {
    id: -tempId,
    role: 'user',
    content_md: text,
    created_at: new Date().toISOString(),
    refused: false,
    citations: [],
    localId,
    error: '',
    streaming: false,
    done: null,
  }
  const assistant: QaUiMessage = {
    id: -(++tempId),
    role: 'assistant',
    content_md: '',
    created_at: new Date().toISOString(),
    refused: false,
    citations: [],
    localId: `local-${tempId}`,
    error: '',
    streaming: true,
    done: null,
  }
  messages.value.push(userMessage, assistant)
  streaming.value = true
  await nextTick()
  scheduleScroll()

  writer = createTypewriter({
    onUpdate: (value) => {
      assistant.content_md = value
      scheduleScroll()
    },
    onDrained: () => {
      if (assistant.done || assistant.error) {
        assistant.streaming = false
        streaming.value = false
      }
    },
  })
  controller = new AbortController()
  try {
    await askQuestion(
      { question: text, scope, conversation_id: activeId.value },
      {
        onMeta: (data) => {
          userMessage.id = data.user_message_id
          activeId.value = data.conversation_id
          assistant.citations = data.citations.map((item) => ({
            ...item,
            note_available: true,
          }))
          void router.replace({
            name: 'qa',
            query: { conversation: data.conversation_id },
          })
        },
        onDelta: (chunk) => writer?.push(chunk),
        onDone: (data: QaDoneData) => {
          assistant.id = data.message_id
          assistant.refused = data.refused
          assistant.done = {
            tokens: data.tokens,
            latency_ms: data.latency_ms,
            cached: data.cached,
            suggestions: data.suggestions,
          }
          if (writer?.isIdle()) {
            assistant.streaming = false
            streaming.value = false
          }
          void loadConversations(data.conversation_id)
        },
      },
      controller.signal,
    )
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      messages.value = messages.value.filter((item) => item !== assistant)
      return
    }
    writer?.cancel()
    assistant.error = error instanceof Error ? error.message : '生成失败'
    assistant.streaming = false
    streaming.value = false
  } finally {
    controller = null
    if (!assistant.done && !assistant.error) {
      assistant.error = '连接提前结束'
      assistant.streaming = false
      streaming.value = false
    }
  }
}

async function onRename(conversation: QaConversation): Promise<void> {
  try {
    const result = await ElMessageBox.prompt('输入新的会话标题', '重命名会话', {
      inputValue: conversation.title,
      inputValidator: (value: string) => Boolean(value?.trim()) || '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    const updated = await renameConversation(conversation.id, result.value.trim())
    const index = conversations.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) conversations.value[index] = updated
    ElMessage.success('已重命名')
  } catch {
    // 用户取消对话框，不提示错误。
  }
}

async function onDelete(conversation: QaConversation): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除「${conversation.title}」及其消息？`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteConversation(conversation.id)
    if (activeId.value === conversation.id) newConversation()
    conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
    if (!activeId.value) {
      const next = conversations.value[0]
      if (next) await selectConversation(next.id)
    }
  } catch {
    ElMessage.error('删除会话失败')
  }
}

function onSuggestion(text: string): void {
  question.value = text
}

function onCitation(citation: QaCitation): void {
  if (citation.note_id === null || citation.note_available === false) return
  const query: Record<string, string> = {}
  if (citation.snippet) query.snippet = citation.snippet
  if (citation.heading_path) query.heading = citation.heading_path
  if (citation.page_no !== null) query.page = String(citation.page_no)
  if (citation.chunk_id !== null) query.chunk = String(citation.chunk_id)
  void router.push({
    name: 'note-read',
    params: { id: String(citation.note_id) },
    query,
  })
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
  await loadConversations(typeof route.query.conversation === 'string' ? route.query.conversation : null)
})

onBeforeUnmount(() => {
  stopStream()
  if (scrollTicket) window.clearTimeout(scrollTicket)
})
```

模板结构（完整实现，不省略关键绑定）：

```vue
<template>
  <div class="qa-page">
    <aside class="conversation-pane">
      <div class="pane-head">
        <h1>智能问答</h1>
        <el-button type="primary" size="small" data-testid="new-conversation" @click="newConversation">
          新对话
        </el-button>
      </div>
      <p v-if="listError" class="list-error">{{ listError }}</p>
      <div v-else-if="loadingList" class="list-loading">加载中…</div>
      <div v-else class="conversation-list">
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-row"
          :class="{ active: conversation.id === activeId }"
          @click="void selectConversation(conversation.id)"
        >
          <span class="conversation-title">{{ conversation.title }}</span>
          <span class="conversation-meta">{{ conversation.message_count }} 条</span>
          <div class="conversation-actions">
            <el-button link size="small" @click.stop="void onRename(conversation)">改名</el-button>
            <el-button link type="danger" size="small" @click.stop="void onDelete(conversation)">删除</el-button>
          </div>
        </div>
        <p v-if="!conversations.length" class="list-empty">还没有会话，直接提问开始。</p>
      </div>
    </aside>

    <section class="chat-pane">
      <header class="chat-head">
        <div>
          <strong>{{ activeId ? '继续追问' : '新对话' }}</strong>
          <span class="chat-hint">基于你的笔记作答，引用可跳转</span>
        </div>
        <div class="scope-panel">
          <el-select v-model="subjectId" placeholder="全部学科" clearable size="small">
            <el-option v-for="subject in subjects" :key="subject.id" :label="subject.name" :value="subject.id" />
          </el-select>
          <el-input v-model="folder" placeholder="笔记本（文件夹）" clearable size="small" />
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            size="small"
          />
        </div>
      </header>

      <div ref="scrollHost" class="messages" data-testid="messages">
        <EmptyState v-if="!hasMessages && !loadingMessages" title="问点什么" description="例如：错位相减法怎么用？" />
        <div v-else-if="loadingMessages" class="list-loading">消息加载中…</div>
        <ChatMessage
          v-for="message in messages"
          :key="message.localId"
          :message="message"
          @citation="onCitation"
          @suggestion="onSuggestion"
        />
      </div>

      <form class="composer" @submit.prevent="void send()">
        <textarea
          v-model="question"
          data-testid="question-input"
          rows="2"
          maxlength="500"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="void send()"
        />
        <el-button
          type="primary"
          native-type="submit"
          :loading="streaming"
          :disabled="streaming || !question.trim()"
          data-testid="send-question"
        >
          发送
        </el-button>
      </form>
    </section>
  </div>
</template>
```

样式用现有 token（至少实现 `.qa-page` 两列、`.messages` 滚动、`.conversation-row.active` 高亮、`.composer` 底部固定）。不新增全局 CSS。

- [x] **Step 5: 修改路由**

`router/index.ts` 的 `/qa`：

```ts
{
  path: 'qa',
  name: 'qa',
  component: () => import('@/views/qa/Chat.vue'),
  meta: { title: '智能问答', nav: 'qa', roles: ['student'] },
},
```

- [x] **Step 6: 写 Chat 测试**

`Chat.spec.ts` 至少覆盖：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Chat from './Chat.vue'
import {
  askQuestion,
  deleteConversation,
  getConversationMessages,
  listConversations,
  renameConversation,
} from '@/api/qa'
import { listSubjects } from '@/api/kp'

vi.mock('@/api/qa', () => ({
  askQuestion: vi.fn(),
  deleteConversation: vi.fn(),
  getConversationMessages: vi.fn(),
  listConversations: vi.fn(),
  renameConversation: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn() }))

const conversation = {
  id: '12',
  title: '错位相减法',
  scope: null,
  created_at: '2026-11-02T10:00:00+00:00',
  last_message_at: null,
  message_count: 2,
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/qa', name: 'qa', component: Chat },
      { path: '/notes/:id', name: 'note-read', component: { template: '<div />' } },
    ],
  })
  await router.push('/qa')
  await router.isReady()
  return { wrapper: mount(Chat, { global: { plugins: [router, ElementPlus] } }), router }
}

beforeEach(() => {
  vi.mocked(listConversations).mockReset()
  vi.mocked(getConversationMessages).mockReset()
  vi.mocked(listSubjects).mockReset()
  vi.mocked(askQuestion).mockReset()
  vi.mocked(renameConversation).mockReset()
  vi.mocked(deleteConversation).mockReset()
  vi.mocked(listSubjects).mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Chat', () => {
  it('loads conversations and messages', async () => {
    vi.mocked(listConversations).mockResolvedValue([conversation])
    vi.mocked(getConversationMessages).mockResolvedValue({
      conversation,
      messages: [
        {
          id: 30,
          role: 'user',
          content_md: '问题',
          created_at: '2026-11-02T10:00:00+00:00',
          refused: false,
          citations: [],
        },
      ],
    })
    const { wrapper } = await mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('错位相减法')
    expect(wrapper.text()).toContain('问题')
  })

  it('sends question and renders streamed answer', async () => {
    vi.mocked(listConversations).mockResolvedValue([conversation])
    vi.mocked(getConversationMessages).mockResolvedValue({ conversation, messages: [] })
    vi.mocked(askQuestion).mockImplementation(async (_payload, handlers) => {
      handlers.onMeta({
        conversation_id: '12',
        user_message_id: 30,
        citations: [],
      })
      handlers.onDelta('你好')
      handlers.onDone({
        message_id: 31,
        conversation_id: '12',
        tokens: 1,
        latency_ms: 2,
        refused: false,
        refusal_reason: null,
        suggestions: [],
        cached: false,
      })
    })
    vi.useFakeTimers()
    const { wrapper } = await mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="question-input"]').setValue('你好')
    await wrapper.get('[data-testid="send-question"]').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(100)
    await flushPromises()
    expect(wrapper.text()).toContain('你好')
    expect(askQuestion).toHaveBeenCalledWith(
      expect.objectContaining({ question: '你好', conversation_id: '12' }),
      expect.any(Object),
      expect.any(AbortSignal),
    )
  })

  it('does not send blank questions', async () => {
    vi.mocked(listConversations).mockResolvedValue([])
    const { wrapper } = await mountPage()
    await flushPromises()
    await wrapper.get('[data-testid="send-question"]').trigger('click')
    expect(askQuestion).not.toHaveBeenCalled()
  })
})
```

真实实现中若 `AbortSignal` 在 jsdom 不可用，用 `expect.anything()` 替换第三参断言；不要删除断言。

- [x] **Step 7: 运行前端测试与构建**

```powershell
npm run test:run -- src/views/qa/scope.spec.ts src/views/qa/Chat.spec.ts src/components/qa/CitationCard.spec.ts src/components/qa/ChatMessage.spec.ts
npm run build
```

Expected: 指定测试全绿；build 0。

- [x] **Step 8: 提交**

```powershell
git add web/src/views/qa web/src/router/index.ts web/src/types/qa.ts
git commit -m "feat(s3-8): 流式问答页与会话管理"
```

---

### Task 7: 只读笔记页与引用定位

**Files:**
- Create: `web/src/views/notes/NoteReadView.vue`
- Create: `web/src/views/notes/NoteReadView.spec.ts`
- Modify: `web/src/router/index.ts`

**Interfaces:**
- Consumes `getNote(id)`、`MdPreview`、`highlightSnippet`、`scrollToHeading`。
- Produces route `/notes/:id(\d+)` name `note-read`。

- [x] **Step 1: 写失败测试**

`NoteReadView.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NoteReadView from './NoteReadView.vue'
import { getNote } from '@/api/notes'

vi.mock('@/api/notes', () => ({ getNote: vi.fn() }))

const PreviewStub = {
  props: ['modelValue'],
  template: '<div class="md-preview">{{ modelValue }}</div>',
}

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes/:id(\\d+)', name: 'note-read', component: NoteReadView },
      { path: '/notes/:id(\\d+)/edit', name: 'note-edit', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(NoteReadView, {
    global: { plugins: [router, ElementPlus], stubs: { MdPreview: PreviewStub } },
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.mocked(getNote).mockReset()
})

describe('NoteReadView', () => {
  it('renders note and highlights query snippet', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 55,
      title: '数列笔记',
      subject_id: 1,
      tags: [],
      folder: null,
      created_at: '2026-11-01T00:00:00+00:00',
      updated_at: '2026-11-01T00:00:00+00:00',
      content_md: '错位相减法很好用',
      source_file_id: null,
    })
    const { wrapper } = await mountAt('/notes/55?snippet=错位相减')
    await flushPromises()
    expect(wrapper.text()).toContain('数列笔记')
    expect(wrapper.find('mark.citation-hit').text()).toBe('错位相减')
  })

  it('shows a fallback notice when snippet cannot be located', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 55,
      title: '数列笔记',
      subject_id: null,
      tags: [],
      folder: null,
      created_at: '2026-11-01T00:00:00+00:00',
      updated_at: '2026-11-01T00:00:00+00:00',
      content_md: '正文',
      source_file_id: null,
    })
    const { wrapper } = await mountAt('/notes/55?snippet=不存在&heading=数列/公式')
    await flushPromises()
    expect(wrapper.text()).toContain('未能精确定位')
  })
})
```

- [x] **Step 2: 运行确认失败**

```powershell
npm run test:run -- src/views/notes/NoteReadView.spec.ts
```

Expected: 组件不存在。

- [x] **Step 3: 实现 NoteReadView**

```vue
<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MdPreview } from 'md-editor-v3'

import { getNote } from '@/api/notes'
import type { NoteOut } from '@/types/notes'
import { highlightSnippet, scrollToHeading } from '@/utils/highlight'

import 'md-editor-v3/lib/preview.css'
import 'katex/dist/katex.min.css'

const route = useRoute()
const router = useRouter()
const note = ref<NoteOut | null>(null)
const loading = ref(true)
const error = ref('')
const manualNotice = ref(false)
const previewHost = ref<HTMLElement | null>(null)
let appliedQuery = ''

function queryString(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

async function applyHighlight(): Promise<void> {
  const host = previewHost.value
  const signature = `${queryString('snippet')}|${queryString('heading')}`
  if (!host || !note.value || !signature || signature === appliedQuery) return
  const snippet = queryString('snippet')
  if (!snippet) return
  appliedQuery = signature
  await nextTick()
  const mark = highlightSnippet(host, snippet)
  if (mark) {
    manualNotice.value = false
    return
  }
  const heading = queryString('heading')
  const located = scrollToHeading(host, heading || null)
  manualNotice.value = true
  if (!located && heading) manualNotice.value = true
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    note.value = await getNote(Number(route.params.id))
    await nextTick()
    await applyHighlight()
  } catch {
    error.value = '笔记不存在或无权访问'
  } finally {
    loading.value = false
  }
}

function toEdit(): void {
  if (note.value) void router.push({ name: 'note-edit', params: { id: note.value.id } })
}

watch(() => route.query, () => {
  appliedQuery = ''
  void applyHighlight()
})

onMounted(load)
</script>

<template>
  <div class="read-page">
    <header class="read-head">
      <button class="back" type="button" @click="router.push({ name: 'notes' })">← 笔记</button>
      <span v-if="note" class="read-status">只读</span>
      <el-button v-if="note" type="primary" plain data-testid="edit-note" @click="toEdit">
        编辑
      </el-button>
    </header>
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="load-error">
      <p>{{ error }}</p>
      <el-button @click="router.push({ name: 'notes' })">返回笔记列表</el-button>
    </div>
    <template v-else-if="note">
      <h1 class="note-title">{{ note.title }}</h1>
      <p v-if="manualNotice" class="fallback-notice" data-testid="citation-fallback">
        未能精确定位引用片段，已滚动到对应章节。引用原文：{{ queryString('snippet') }}
      </p>
      <div ref="previewHost" class="preview-host">
        <MdPreview :model-value="note.content_md" :no-mermaid="true" preview-theme="github" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.read-page { display: grid; gap: 14px; }
.read-head { display: flex; gap: 12px; align-items: center; min-height: 40px; }
.read-head .back { padding: 4px 0; color: var(--app-text-secondary); background: none; border: none; cursor: pointer; }
.read-status { color: var(--app-text-tertiary); font-size: 12px; }
.note-title { margin: 0; font-size: 24px; }
.preview-host { padding: 20px 24px; background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); }
.fallback-notice { margin: 0; padding: 10px 12px; color: var(--app-warning); background: #fff4e6; border-radius: var(--app-radius-sm); }
.preview-host :deep(mark.citation-hit) { padding: 0 2px; background: #fff3bf; border-radius: 2px; }
</style>
```

若 `MdPreview` 渲染是异步的，`nextTick` 仍可能早于 HTML 注入；在 `MdPreview` 上加 `@on-html-changed="applyHighlight"`，并把 `applyHighlight` 的 `signature` 守卫保留，保证只高亮一次。

- [x] **Step 4: 加路由**

在 `/notes/:id(\\d+)/edit` 之前加：

```ts
{
  path: 'notes/:id(\\d+)',
  name: 'note-read',
  component: () => import('@/views/notes/NoteReadView.vue'),
  meta: { title: '笔记详情', nav: 'notes' },
},
```

- [x] **Step 5: 运行测试**

```powershell
npm run test:run -- src/views/notes/NoteReadView.spec.ts
```

Expected: `2 passed`；若高亮测试失败，先用 `highlight.spec.ts` 单独定位，不要改测试绕过。

- [x] **Step 6: 提交**

```powershell
git add web/src/views/notes/NoteReadView.vue web/src/views/notes/NoteReadView.spec.ts web/src/router/index.ts
git commit -m "feat(s3-8): 引用跳转与只读笔记页"
```

---

### Task 8: 真实联调、文档与全量验证

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-8-qa-chat.md`
- Modify: `docs/plan/s3-8-qa-chat.md`
- Maybe modify: `docs/API.md`（若实现中字段有偏差，必须回写）

**Interfaces:**
- Consumes 全部前置任务；不新增代码接口。

- [x] **Step 1: 后端全量回归**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 记录真实 `N passed`，不得沿用计划估算。

- [x] **Step 2: 前端全量测试与构建**

```powershell
cd web
npm run test:run
npm run build
```

Expected: 记录真实 files/tests 数字；build 退出码 0。

- [x] **Step 3: 真实验收（必须手工操作真实页面）**

1. 启动后端与前端（按项目现有命令；前端 `npm run dev`，后端 `uvicorn app.main:app --reload`，从 `backend/` 运行）。
2. 用真实学生 `test1` 登录，打开 `/qa`。
3. 问 10 轮，至少包含：
   - 一个笔记内问题（验证引用）；
   - 一个重复问题（验证缓存命中，第二轮 `done.cached=true` 且明显更快）；
   - 一个无依据问题（验证拒答样式）；
   - 一个多轮追问（验证历史上下文）。
4. 每轮记录：首字延迟、结束耗时、tokens、cached、是否渲染公式/列表。
5. 点 3 条不同引用：确认跳到 `/notes/{id}?snippet=...`，正文出现 `<mark class="citation-hit">` 或明确的章节回退提示。
6. 刷新页面：确认 URL `?conversation=` 保留，消息和引用恢复。
7. 改名、刷新确认保留；删除当前会话，确认列表减少、消息不再出现。
8. 打开教师账号访问 `/qa`，确认 403/无权限页（前端路由 roles + 后端 403 都验证）。

把实测数字、页面路径、失败项写入 PROGRESS，禁止写“应该正常”。

- [x] **Step 4: 更新文档**

- `PROGRESS.md`：S3-8 勾选、当前状态、变更日志（交付/决策/测试/实测）、遗留（历史拒答原因不恢复、引用高亮是文本匹配、会话列表 50 条无分页）。
- `DECISIONS.md`：新增 `D-042 S3-8 前端问答页`，记录 4 个会话接口、历史引用左连接、`note_available`、只读页高亮匹配失败降级、无新依赖/无迁移。
- `AI协作开发实施计划.md`：S3-8 标 ✅ + 实施记录；任务卡清单同步。
- `spec`/`plan`：追加实施记录与实际偏差。

- [x] **Step 5: 最终验证**

```powershell
git diff --check
git status --short
```

Expected: 无 whitespace 错误；只含预期文件。

- [x] **Step 6: 提交**

```powershell
git add docs/PROGRESS.md docs/DECISIONS.md "docs/AI协作开发实施计划.md" docs/spec/s3-8-qa-chat.md docs/plan/s3-8-qa-chat.md docs/API.md
git commit -m "docs(s3-8): 问答页与引用跳转验收记录"
```

---

## 自检

- **Spec 覆盖**：§3 契约 → Task 1/2；§5.1–5.4 前端基础/SSE/打字机 → Task 3/4/6；§5.5 引用跳转 → Task 5/7；§5.6 scope → Task 6；§5.7 权限/路由 → Task 6/7；§6 测试 → 各任务；§7 真实验收 → Task 8。
- **占位符扫描**：无 TODO/TBD；每个实现步骤给关键代码、测试代码、运行命令与预期输出。
- **类型一致性**：`QaConversationOut.id` 为 string；前端 `QaConversation.id` 为 string；`QaUiMessage` 在 types 中定义；`ConversationSummary/Detail` 字段与 API 映射一致；`toScopePayload` 返回 `QaScope`，`askQuestion` 接收 `QaScope`。
- **已知风险**：历史拒答 reason/suggestions 不落库；引用高亮可能退化为章节定位；会话列表固定 50 条；这些在 spec §8 与 Task 8 文档中明确记录。

---

## 实施记录（2026-11-02）

- Task 1–8 全部完成；所有 `Step` 已勾选。后端新增 16 条（service 7 + API 9），全量 **735 passed, 1 warning**；前端新增 29 条/9 文件，全量 **114 passed / 29 files**；`npm run build` 退出 0（仅 775KB chunk 警告）。
- 真实 10 轮 SSE 总耗时 93.7s、tokens 22,092、首字 1.590–34.627s；缓存轮 248ms/tokens=0，拒答轮 2.868s/30 字；20 条消息、30 条引用、1 条拒答；会话列表 22 条，改名 200，临时删除 204→404/40400。
- 真实 Chrome（headless + CDP）：引用 `/notes/55` 与 `/notes/49` 均命中 `mark.citation-hit`，无回退；刷新恢复 22 条消息/32 条引用；UI 新建→改名→删除临时会话成功；教师 `/qa` → `/403`。
- 实施偏差：① `highlightSnippet` 增加“完整→去公式→仅非公式行”候选匹配，并补块级分隔；② `NoteReadView` 从 `nextTick` 立即标注改为 `on-html-changed` 后 80ms 去抖，加 `appliedQuery/applying` 防重入，修复预览未完成时标注导致段落丢失；③ PreviewStub 在 mounted 时触发 `onHtmlChanged`。均已同步 spec §9 与 DECISIONS D-042。
- 未做：历史拒答原因/建议回放、会话列表分页、逐帧流畅度测量、CI E2E；均写入已知限制，未粉饰。