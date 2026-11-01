"""S3-5 问答流式服务：会话/历史/改写/检索/Prompt/落库编排。"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.llm import LLMClient, LLMMessage, LLMResponse
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
from app.core.cache import Cache, get_cache
from app.core.db import new_session
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_citation import MessageCitation
from app.models.note import Note
from app.models.note_chunk import NoteChunk
from app.schemas.qa import QaScopeIn
from app.services import prompt_service, qa_cache_service
from app.services.citation_checker import (
    annotate_uncited,
    build_correction,
    check_answer,
    strip_invalid_citations,
)
from app.services.qa_cache_service import CachedAnswer, CachedCitation
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


@dataclass(frozen=True)
class QaStreamEvent:
    event: Literal["meta", "delta", "done", "error"]
    data: dict[str, object]


@dataclass(frozen=True)
class QaSuggestion:
    type: Literal["rephrase", "note"]
    text: str
    note_id: int | None = None


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
    cached: CachedAnswer | None = None
    cache_key: str | None = None


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

    cache = get_cache()
    cache_key = qa_cache_service.cache_key(user_id, clean, resolved_scope)
    cached = qa_cache_service.get(
        cache, user_id=user_id, question=clean, scope=resolved_scope
    )
    if cached is not None:
        return QaPlan(
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            question=clean,
            kind=cached.kind,  # type: ignore[arg-type]
            prepared=None,
            chitchat_reply=cached.answer if cached.kind == "chitchat" else None,
            citations=[
                QaCitationMeta(
                    index=item.index,
                    note_id=item.note_id,
                    chunk_id=item.chunk_id,
                    title=item.title,
                    heading_path=item.heading_path,
                    page_no=item.page_no,
                    snippet=item.snippet,
                )
                for item in cached.citations
            ],
            prompt_version=cached.prompt_version,
            rewrite=None,
            started_at=started,
            cached=cached,
            cache_key=cache_key,
        )

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
            cache_key=cache_key,
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
            cache_key=cache_key,
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
        cache_key=cache_key,
    )


def _usage_payload(responses: list[LLMResponse]) -> dict[str, object]:
    return {
        "prompt_tokens": sum(r.prompt_tokens for r in responses),
        "completion_tokens": sum(r.completion_tokens for r in responses),
        "total_tokens": sum(r.total_tokens for r in responses),
        "cost_yuan": sum(r.cost_yuan for r in responses),
    }


def _token_usage(
    responses: list[LLMResponse], rewrite: RewriteResult | None
) -> dict[str, object]:
    payload = _usage_payload(responses)
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
    responses: list[LLMResponse], rewrite: RewriteResult | None
) -> int:
    return sum(r.total_tokens for r in responses) + (
        rewrite.total_tokens if rewrite is not None else 0
    )


def _persist_assistant(
    *,
    session_factory: Callable[[], Session],
    plan: QaPlan,
    content: str,
    responses: list[LLMResponse],
    citation_indices: list[int],
    cached_citations: tuple[CachedCitation, ...] | None = None,
) -> Message:
    latency_ms = int((time.perf_counter() - plan.started_at) * 1000)
    model = (
        plan.cached.model
        if cached_citations is not None and plan.cached is not None
        else (responses[-1].model if responses else None)
    )
    token_usage = (
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_yuan": 0.0,
            "rewrite": None,
        }
        if cached_citations is not None
        else _token_usage(responses, plan.rewrite)
    )
    session = session_factory()
    try:
        message = Message(
            conversation_id=plan.conversation_id,
            role="assistant",
            content_md=content,
            token_usage=token_usage,
            latency_ms=latency_ms,
            model=model,
            prompt_version=plan.prompt_version,
        )
        session.add(message)
        session.flush()
        if cached_citations is not None:
            by_index = {item.index: item for item in cached_citations}
            for index in citation_indices:
                citation = by_index.get(index)
                if citation is None:
                    continue
                session.add(
                    MessageCitation(
                        message_id=message.id,
                        chunk_id=citation.chunk_id,
                        note_id=citation.note_id,
                        score=citation.score,
                        snippet=citation.snippet,
                        page_no=citation.page_no,
                        rank=index,
                    )
                )
        elif plan.prepared is not None and plan.prepared.built is not None:
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


def _suggestions() -> list[QaSuggestion]:
    return [
        QaSuggestion("rephrase", "换个问法，把问题拆得更具体"),
        QaSuggestion("note", "先补充相关笔记，或缩小检索范围"),
    ]


def _cached_indices(cached: CachedAnswer, text: str) -> list[int]:
    size = len(cached.citations)
    return [index for index in extract_citation_indices(text) if 1 <= index <= size]


def _put_answer_cache(
    plan: QaPlan,
    *,
    answer: str,
    kind: str,
    refused: bool,
    refusal_reason: str | None,
    suggestions: list[QaSuggestion],
    citations: tuple[CachedCitation, ...],
    model: str | None,
) -> None:
    if plan.cache_key is None:
        return
    cache_suggestions = tuple(
        qa_cache_service.CachedSuggestion(
            type=item.type,
            text=item.text,
            note_id=item.note_id,
        )
        for item in suggestions
    )
    try:
        qa_cache_service.put(
            get_cache(),
            key=plan.cache_key,
            answer=answer,
            kind=kind,
            refused=refused,
            refusal_reason=refusal_reason,
            suggestions=cache_suggestions,
            citations=citations,
            prompt_version=plan.prompt_version,
            model=model,
            ttl_seconds=get_settings().qa_cache_ttl_seconds,
        )
    except Exception:
        logger.warning(
            "qa_cache_write_failed",
            extra={"conversation_id": plan.conversation_id},
        )


def _done_data(
    plan: QaPlan,
    message: Message,
    *,
    refused: bool,
    responses: list[LLMResponse],
    refusal_reason: str | None,
    suggestions: list[QaSuggestion],
) -> dict[str, object]:
    return {
        "message_id": message.id,
        "conversation_id": str(plan.conversation_id),
        "tokens": _total_tokens(responses, plan.rewrite),
        "latency_ms": int((time.perf_counter() - plan.started_at) * 1000),
        "refused": refused,
        "refusal_reason": refusal_reason,
        "suggestions": [asdict(item) for item in suggestions],
        "cached": plan.cached is not None,
        "cost_yuan": sum(r.cost_yuan for r in responses)
        + (plan.rewrite.cost_yuan if plan.rewrite is not None else 0.0),
    }


def _error_event() -> QaStreamEvent:
    return QaStreamEvent(
        event="error",
        data={"code": 50000, "message": "生成失败"},
    )


def _answer_parts(text: str) -> list[str]:
    if not text:
        return [""]
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"\n{2,}", text):
        parts.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        parts.append(text[start:])
    return parts


def _consume_answer(
    prepared: PreparedAnswer,
    *,
    llm_client: LLMClient | None,
    messages: list[LLMMessage] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[LLMResponse], bool]:
    parts: list[str] = []
    responses: list[LLMResponse] = []
    if messages is None:
        stream = stream_answer(prepared, llm_client=llm_client)
    else:
        stream = stream_answer(
            prepared, llm_client=llm_client, messages=messages
        )
    cancelled = False
    try:
        for chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if chunk.text:
                parts.append(chunk.text)
            if chunk.response is not None:
                responses.append(chunk.response)
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    return "".join(parts), responses, cancelled


def stream_events(
    plan: QaPlan,
    *,
    llm_client: LLMClient | None = None,
    session_factory: Callable[[], Session] = new_session,
    cancel_event: threading.Event | None = None,
) -> Iterator[QaStreamEvent]:
    yield QaStreamEvent(
        event="meta",
        data={
            "conversation_id": str(plan.conversation_id),
            "user_message_id": plan.user_message_id,
            "citations": [asdict(citation) for citation in plan.citations],
        },
    )

    if plan.cached is not None:
        cached = plan.cached
        for part in _answer_parts(cached.answer):
            yield QaStreamEvent(event="delta", data={"text": part})
        cached_suggestions = [
            QaSuggestion(
                type=item.type,  # type: ignore[arg-type]
                text=item.text,
                note_id=item.note_id,
            )
            for item in cached.suggestions
        ]
        try:
            message = _persist_assistant(
                session_factory=session_factory,
                plan=plan,
                content=cached.answer,
                responses=[],
                citation_indices=_cached_indices(cached, cached.answer),
                cached_citations=cached.citations,
            )
        except Exception:
            logger.exception("qa_persist_cached_failed")
            yield _error_event()
            return
        yield QaStreamEvent(
            event="done",
            data=_done_data(
                plan,
                message,
                refused=cached.refused,
                responses=[],
                refusal_reason=cached.refusal_reason,
                suggestions=cached_suggestions,
            ),
        )
        return

    if plan.kind == "chitchat":
        text = plan.chitchat_reply or FALLBACK_REPLY
        yield QaStreamEvent(event="delta", data={"text": text})
        try:
            message = _persist_assistant(
                session_factory=session_factory,
                plan=plan,
                content=text,
                responses=[],
                citation_indices=[],
            )
        except Exception:
            logger.exception("qa_persist_chitchat_failed")
            yield _error_event()
            return
        _put_answer_cache(
            plan,
            answer=text,
            kind="chitchat",
            refused=False,
            refusal_reason=None,
            suggestions=[],
            citations=(),
            model=get_settings().llm_model,
        )
        yield QaStreamEvent(
            event="done",
            data=_done_data(
                plan,
                message,
                refused=False,
                responses=[],
                refusal_reason=None,
                suggestions=[],
            ),
        )
        return

    if plan.kind == "refused":
        yield QaStreamEvent(event="delta", data={"text": REFUSAL_TEXT})
        try:
            message = _persist_assistant(
                session_factory=session_factory,
                plan=plan,
                content=REFUSAL_TEXT,
                responses=[],
                citation_indices=[],
            )
        except Exception:
            logger.exception("qa_persist_refusal_failed")
            yield _error_event()
            return
        reason = (
            getattr(plan.prepared.refused, "refusal_reason", None)
            if plan.prepared is not None and plan.prepared.refused is not None
            else "no_context"
        ) or "no_context"
        refusal_suggestions = _suggestions()
        _put_answer_cache(
            plan,
            answer=REFUSAL_TEXT,
            kind="refused",
            refused=True,
            refusal_reason=reason,
            suggestions=refusal_suggestions,
            citations=(),
            model=get_settings().llm_model,
        )
        yield QaStreamEvent(
            event="done",
            data=_done_data(
                plan,
                message,
                refused=True,
                responses=[],
                refusal_reason=reason,
                suggestions=refusal_suggestions,
            ),
        )
        return

    if plan.prepared is None or plan.prepared.built is None:
        yield _error_event()
        return

    context_size = len(plan.prepared.built.items)
    try:
        first_text, first_responses, cancelled = _consume_answer(
            plan.prepared,
            llm_client=llm_client,
            cancel_event=cancel_event,
        )
    except GeneratorExit:
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

    if cancelled:
        logger.info(
            "qa_stream_disconnected",
            extra={"conversation_id": plan.conversation_id},
        )
        return

    check = check_answer(first_text, context_size=context_size)
    responses = list(first_responses)
    final_text = first_text
    if check.needs_retry and get_settings().qa_citation_max_retries >= 1:
        retry_messages = [
            LLMMessage(role="user", content=plan.prepared.prompt),
            LLMMessage(role="assistant", content=first_text or "(空回答)"),
            LLMMessage(role="user", content=build_correction(check)),
        ]
        try:
            retry_text, retry_responses, cancelled = _consume_answer(
                plan.prepared,
                llm_client=llm_client,
                messages=retry_messages,
                cancel_event=cancel_event,
            )
        except GeneratorExit:
            return
        except LLMError:
            logger.warning(
                "qa_stream_retry_llm_failed",
                extra={"conversation_id": plan.conversation_id},
            )
            yield _error_event()
            return
        except Exception:
            logger.exception(
                "qa_stream_retry_failed",
                extra={"conversation_id": plan.conversation_id},
            )
            yield _error_event()
            return
        if cancelled:
            logger.info(
                "qa_stream_disconnected",
                extra={"conversation_id": plan.conversation_id},
            )
            return
        responses.extend(retry_responses)
        final_text = retry_text
        check = check_answer(final_text, context_size=context_size)

    refused = False
    refusal_reason: str | None = None
    suggestions: list[QaSuggestion] = []
    if not check.has_content:
        refused = True
        refusal_reason = "empty_answer"
        final_text = REFUSAL_TEXT
        suggestions = _suggestions()
    elif not check.has_valid_citation:
        refused = True
        refusal_reason = "no_valid_citation"
        final_text = REFUSAL_TEXT
        suggestions = _suggestions()
    else:
        final_text = annotate_uncited(
            strip_invalid_citations(final_text, context_size=context_size),
            context_size=context_size,
        )

    indices = [] if refused else _valid_citation_indices(plan, final_text)
    for part in _answer_parts(final_text):
        yield QaStreamEvent(event="delta", data={"text": part})

    try:
        message = _persist_assistant(
            session_factory=session_factory,
            plan=plan,
            content=final_text,
            responses=responses,
            citation_indices=indices,
        )
    except Exception:
        logger.exception("qa_persist_assistant_failed")
        yield _error_event()
        return

    if plan.prepared.built is not None:
        cache_citations = tuple(
            CachedCitation(
                index=index,
                note_id=plan.prepared.built.items[index - 1].citation.note_id,
                chunk_id=plan.prepared.built.items[index - 1].citation.chunk_id,
                title=next(
                    (
                        item.title
                        for item in plan.citations
                        if item.index == index
                    ),
                    None,
                ),
                heading_path=plan.prepared.built.items[index - 1].citation.heading_path,
                page_no=plan.prepared.built.items[index - 1].citation.page_no,
                snippet=plan.prepared.built.items[index - 1].citation.snippet,
                score=plan.prepared.built.items[index - 1].citation.rerank_score,
            )
            for index in indices
        )
    else:
        cache_citations = ()
    _put_answer_cache(
        plan,
        answer=final_text,
        kind="rag",
        refused=refused,
        refusal_reason=refusal_reason,
        suggestions=suggestions,
        citations=cache_citations,
        model=responses[-1].model if responses else None,
    )

    yield QaStreamEvent(
        event="done",
        data=_done_data(
            plan,
            message,
            refused=refused,
            responses=responses,
            refusal_reason=refusal_reason,
            suggestions=suggestions,
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
                    score=(
                        float(citation.score)
                        if citation.score is not None
                        else None
                    ),
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
    last_message_at = max((item.created_at for item in messages), default=None)
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