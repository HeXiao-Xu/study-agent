"""S3-5 问答接口（API.md §5）：学生 SSE 问答与引用查询。"""
from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.qa import (
    QaAskRequest,
    QaConversationDetailOut,
    QaConversationOut,
    QaConversationRename,
    QaHistoryCitationOut,
    QaHistoryMessageOut,
    QaMessageCitationOut,
)
from app.services import qa_service

router = APIRouter(prefix="/qa", tags=["qa"])


def _sse(event: qa_service.QaStreamEvent) -> str:
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"


async def _stream(
    plan: qa_service.QaPlan, request: Request
) -> AsyncIterator[str]:
    cancel_event = threading.Event()
    events = qa_service.stream_events(plan, cancel_event=cancel_event)
    try:
        while True:
            event = await run_in_threadpool(next, events, None)
            if event is None:
                break
            if await request.is_disconnected():
                break
            yield _sse(event)
    finally:
        cancel_event.set()
        close = getattr(events, "close", None)
        if close is not None:
            try:
                close()
            except ValueError:
                # 生成器正在工作线程里执行；cancel_event 会让它收尾关闭上游。
                pass


@router.post(
    "/ask",
    summary="流式问答（SSE：meta/delta/done/error）",
    response_class=StreamingResponse,
)
def ask(
    payload: QaAskRequest,
    request: Request,
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
        _stream(plan, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
                    index=citation.index,
                    note_id=citation.note_id,
                    chunk_id=citation.chunk_id,
                    title=citation.title,
                    heading_path=citation.heading_path,
                    page_no=citation.page_no,
                    snippet=citation.snippet,
                    score=citation.score,
                    note_available=citation.note_available,
                )
                for citation in item.citations
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