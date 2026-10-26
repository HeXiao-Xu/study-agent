"""S2-5 笔记 CRUD 接口（API.md §2）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.notes import NoteCreate, NoteOut, NoteSummary, NoteUpdate
from app.services import note_service
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", status_code=201, response_model=Envelope[NoteOut], summary="新建笔记")
def create_note(
    payload: NoteCreate,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.create_note(session, owner=current_user, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.get(
    "", response_model=Envelope[PageData[NoteSummary]], summary="笔记列表（仅本人）"
)
def list_notes(
    params: PageParams = Depends(page_params),
    sorting: SortParams = Depends(sort_params),
    subject_id: int | None = Query(None, ge=1, description="学科筛选"),
    tag: str | None = Query(None, min_length=1, max_length=30, description="标签精确匹配"),
    q: str | None = Query(None, min_length=1, max_length=100, description="标题/正文关键词"),
    created_from: datetime | None = Query(None, description="创建时间下界（ISO-8601）"),
    created_to: datetime | None = Query(None, description="创建时间上界（ISO-8601）"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[NoteSummary]]:
    page = note_service.list_notes(
        session,
        owner=current_user,
        params=params,
        sorting=sorting,
        subject_id=subject_id,
        tag=tag,
        q=q,
        created_from=created_from,
        created_to=created_to,
    )
    return Envelope(trace_id=get_trace_id(), data=page)


@router.get("/{note_id}", response_model=Envelope[NoteOut], summary="笔记详情")
def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.get_note(session, note_id=note_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.patch("/{note_id}", response_model=Envelope[NoteOut], summary="部分更新笔记")
def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[NoteOut]:
    note = note_service.update_note(
        session, note_id=note_id, owner=current_user, payload=payload
    )
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


@router.delete("/{note_id}", status_code=204, response_model=None, summary="软删除笔记")
def delete_note(
    note_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> None:
    note_service.delete_note(session, note_id=note_id, owner=current_user)