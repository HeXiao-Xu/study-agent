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


def _done_data(
    plan: QaPlan,
    message: Message,
    *,
    refused: bool,
    response: LLMResponse | None,
) -> dict[str, object]:
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