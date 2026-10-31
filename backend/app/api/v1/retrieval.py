"""S3-2 检索接口（API.md §5）：仅 student，检索本人切片。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.retrieval import RetrievalSearchRequest, RetrievalSearchResponse
from app.services import retrieval_service

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/search",
    response_model=Envelope[RetrievalSearchResponse],
    summary="检索本人笔记切片（带 scope 与可选重排）",
)
def search_chunks(
    payload: RetrievalSearchRequest,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[RetrievalSearchResponse]:
    data = retrieval_service.search_chunks(
        session,
        user_id=current_user.id,
        query=payload.query,
        top_k=payload.top_k,
        rerank=payload.rerank,
        scope=payload.scope,
        debug=payload.debug,
    )
    return Envelope(trace_id=get_trace_id(), data=data)