"""S2-5 笔记业务（spec §5）。

一个用例一个事务；越权与不存在分开报：不存在 404，他人可读范围外 403。
写操作只认 owner，不再查家长/老师关系——谁改的必须可追溯。
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.core.permissions import ensure_student_access
from app.models.note import Note
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.notes import NoteCreate, NoteSummary, NoteUpdate
from app.utils.markdown_text import to_plain_text
from app.utils.pagination import PageParams, SortParams, apply_sort, paginate_query

NOTE_SORT_FIELDS: Mapping[str, Any] = {
    "created_at": Note.created_at,
    "updated_at": Note.updated_at,
    "title": Note.title,
}

_REQUIRED_FIELDS = ("title", "content_md")


def escape_like(term: str) -> str:
    """转义 LIKE 元字符：用户输入的 % 不能变成通配符。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_notes_query(
    *,
    owner_id: int,
    subject_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Select:
    stmt = select(Note).where(Note.user_id == owner_id, Note.deleted_at.is_(None))
    if subject_id is not None:
        stmt = stmt.where(Note.subject_id == subject_id)
    if tag:
        # @> 能被 ix_notes_tags_gin 直接命中；= ANY(tags) 则容易退化成逐行判断
        stmt = stmt.where(Note.tags.contains([tag]))
    if q:
        pattern = f"%{escape_like(q)}%"
        stmt = stmt.where(
            or_(
                Note.title.ilike(pattern, escape="\\"),
                Note.content_text.ilike(pattern, escape="\\"),
            )
        )
    if created_from is not None:
        stmt = stmt.where(Note.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Note.created_at <= created_to)
    return stmt


def _ensure_subject_exists(session: Session, subject_id: int | None) -> None:
    if subject_id is None:
        return
    if session.get(Subject, subject_id) is None:
        raise InvalidParamError("学科不存在")


def _load_note(session: Session, note_id: int) -> Note:
    note = session.scalar(
        select(Note).where(Note.id == note_id, Note.deleted_at.is_(None))
    )
    if note is None:
        raise NotFoundError("笔记不存在")
    return note


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def create_note(session: Session, *, owner: User, payload: NoteCreate) -> Note:
    _ensure_subject_exists(session, payload.subject_id)
    note = Note(
        user_id=owner.id,
        subject_id=payload.subject_id,
        title=payload.title,
        content_md=payload.content_md,
        content_text=to_plain_text(payload.content_md),
        tags=payload.tags or None,
        folder=payload.folder,
    )
    session.add(note)
    _commit(session)
    session.refresh(note)
    return note


def list_notes(
    session: Session,
    *,
    owner: User,
    params: PageParams,
    sorting: SortParams,
    subject_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PageData[NoteSummary]:
    stmt = build_notes_query(
        owner_id=owner.id,
        subject_id=subject_id,
        tag=tag,
        q=q,
        created_from=created_from,
        created_to=created_to,
    )
    stmt = apply_sort(
        stmt,
        sort_by=sorting.sort_by,
        order=sorting.order,
        allowed=NOTE_SORT_FIELDS,
        default_sort="created_at",
    )
    return paginate_query(session, stmt, params, item_model=NoteSummary)


def get_note(session: Session, *, note_id: int, viewer: User) -> Note:
    note = _load_note(session, note_id)
    if note.user_id != viewer.id:
        ensure_student_access(session, viewer, note.user_id)
    return note


def update_note(
    session: Session, *, note_id: int, owner: User, payload: NoteUpdate
) -> Note:
    note = _load_note(session, note_id)
    if note.user_id != owner.id:
        raise ForbiddenError("无权修改该资源")
    data = payload.model_dump(exclude_unset=True)
    for field in _REQUIRED_FIELDS:
        if field in data and data[field] is None:
            raise InvalidParamError(f"{field} 不能为空")
    if "subject_id" in data:
        _ensure_subject_exists(session, data["subject_id"])
    if "content_md" in data:
        note.content_text = to_plain_text(data["content_md"])
    if "tags" in data:
        data["tags"] = data["tags"] or None
    for field, value in data.items():
        setattr(note, field, value)
    _commit(session)
    session.refresh(note)
    return note


def delete_note(session: Session, *, note_id: int, owner: User) -> None:
    note = _load_note(session, note_id)
    if note.user_id != owner.id:
        raise ForbiddenError("无权删除该资源")
    note.deleted_at = datetime.now(timezone.utc)
    _commit(session)