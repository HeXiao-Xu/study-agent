"""S3-8 会话回放 service：FakeSession，不连库。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError, NotFoundError
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
    return Conversation(
        id=12,
        user_id=1,
        title=title,
        scope_json={"subject_id": 7, "folder": "数列"},
        created_at=datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )


def _message(message_id: int, role: str, content: str) -> Message:
    return Message(
        id=message_id,
        conversation_id=12,
        role=role,
        content_md=content,
        created_at=datetime(2026, 11, 2, 10, 0, message_id, tzinfo=timezone.utc),
    )


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


def test_rename_conversation_trims_and_returns_summary() -> None:
    conversation = _conversation()
    session = FakeSession(
        scalar_results=[conversation],
        execute_rows=[[(2, datetime(2026, 11, 2, 10, 0, 1, tzinfo=timezone.utc))]],
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