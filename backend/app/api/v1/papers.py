"""S5-2 组卷接口（API.md §8）：同步生成、无状态换题、保存草稿、读取。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.paper import (
    PaperDetailOut,
    PaperGenerateIn,
    PaperOut,
    PaperPreviewOut,
    PaperReplaceIn,
    PaperReplaceOut,
    PaperSaveIn,
)
from app.services import paper_plan_service, pdf_service

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("/generate", response_model=Envelope[PaperPreviewOut])
def generate_paper(
    payload: PaperGenerateIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperPreviewOut]:
    """同步生成预览，不写库；题库不足用 200 + ok=false 表达。"""
    data = paper_plan_service.generate_preview(
        session, payload, user_id=user.id, now=datetime.now(timezone.utc)
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/replace-item", response_model=Envelope[PaperReplaceOut])
def replace_paper_item(
    payload: PaperReplaceIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperReplaceOut]:
    """无状态换题：前端带上整张卷面，后端重建候选池后挑替身。"""
    data = paper_plan_service.replace_item(
        session, payload, user_id=user.id, now=datetime.now(timezone.utc)
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post(
    "",
    response_model=Envelope[PaperOut],
    status_code=status.HTTP_201_CREATED,
)
def save_paper(
    payload: PaperSaveIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperOut]:
    """保存草稿：总分由服务端按题目分值重算。"""
    data = paper_plan_service.save_draft(session, payload, user_id=user.id)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get("/{paper_id}/export.pdf")
def export_paper_pdf(
    paper_id: int,
    variant: Literal["questions", "answers"] = Query(default="questions"),
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Response:
    """导出题干卷/答案卷；实时渲染，不写库、不缓存。"""
    content, filename = pdf_service.export_pdf(
        session,
        user_id=user.id,
        paper_id=paper_id,
        variant=variant,
        now=datetime.now(timezone.utc),
    )
    disposition = (
        f'attachment; filename="paper-{paper_id}-{variant}.pdf"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{paper_id}", response_model=Envelope[PaperDetailOut])
def read_paper(
    paper_id: int,
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Envelope[PaperDetailOut]:
    """读本人试卷；顺序就是保存时数组的顺序。"""
    data = paper_plan_service.get_paper(session, user_id=user.id, paper_id=paper_id)
    return Envelope(trace_id=get_trace_id(), data=data)
