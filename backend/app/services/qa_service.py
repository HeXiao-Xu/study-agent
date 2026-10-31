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