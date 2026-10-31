"""S3-5 问答接口（API.md §5）：学生 SSE 问答与引用查询。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

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


async def _stream(
    plan: qa_service.QaPlan, request: Request
) -> AsyncIterator[str]:
    events = qa_service.stream_events(plan)
    try:
        while True:
            event = await run_in_threadpool(next, events, None)
            if event is None:
                break
            if await request.is_disconnected():
                break
            yield _sse(event)
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()


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