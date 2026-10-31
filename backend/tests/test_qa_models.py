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