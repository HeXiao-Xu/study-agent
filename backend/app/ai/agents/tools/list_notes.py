"""S6-1 list_notes：本人笔记元数据列表（不返回正文）。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.services.note_service import NoteSummary
from app.services.note_service import list_notes as list_notes_service
from app.utils.pagination import PageParams, SortParams

PREVIEW_LIMIT = 200
KP_LIMIT = 10


class ListNotesIn(ToolInput):
    start_date: date | None = None
    end_date: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    subject_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            tag = raw.strip()
            if tag and tag not in cleaned:
                cleaned.append(tag)
        return cleaned

    @model_validator(mode="after")
    def _check_range(self) -> "ListNotesIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class NoteBrief(ToolOutput):
    note_id: int
    title: str
    subject_id: int | None = None
    tags: list[str] | None = None
    folder: str | None = None
    created_at: datetime
    updated_at: datetime
    # S6-3：给周导图聚类用；旧调用方不读也不受影响
    preview: str | None = None
    kp_ids: list[int] = Field(default_factory=list)
    kp_names: list[str] = Field(default_factory=list)


class ListNotesOut(ToolOutput):
    total: int
    filtered_total: int
    items: list[NoteBrief]


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, timezone.utc)


def list_notes(ctx: ToolContext, data: ListNotesIn) -> ListNotesOut:
    created_from = _utc_midnight(data.start_date) if data.start_date else None
    created_to = (
        _utc_midnight(data.end_date + timedelta(days=1)) - timedelta(microseconds=1)
        if data.end_date
        else None
    )
    tag = data.tags[0] if data.tags else None
    page = list_notes_service(
        ctx.session,
        owner=ctx.user,
        params=PageParams(page=1, page_size=data.limit),
        sorting=SortParams(sort_by="created_at", order="desc"),
        subject_id=data.subject_id,
        tag=tag,
        created_from=created_from,
        created_to=created_to,
    )
    items = page.items
    if len(data.tags) > 1:
        wanted = set(data.tags)
        items = [item for item in items if wanted.issubset(set(item.tags or []))]
    if items:
        note_ids = [item.id for item in items]
        previews = _load_previews(ctx.session, note_ids)
        kps = _load_kps(ctx.session, note_ids)
        briefs = [
            _to_brief(item, previews.get(item.id), kps.get(item.id)) for item in items
        ]
    else:
        briefs = []
    return ListNotesOut(
        total=page.total, filtered_total=len(briefs), items=briefs
    )


def _load_previews(session, note_ids: list[int]) -> dict[int, str]:  # noqa: ANN001
    rows = session.execute(
        select(Note.id, Note.content_text).where(Note.id.in_(note_ids))
    ).all()
    return {
        int(row[0]): (row[1] or "")[:PREVIEW_LIMIT]
        for row in rows
    }


def _load_kps(session, note_ids: list[int]) -> dict[int, list[tuple[int, str]]]:  # noqa: ANN001
    rows = session.execute(
        select(NoteKp.note_id, KnowledgePoint.id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == NoteKp.kp_id)
        .where(NoteKp.note_id.in_(note_ids))
        # 已确认的优先；同笔记内 kp_id 稳定排序，避免输出漂移
        .order_by(NoteKp.note_id, NoteKp.confirmed.desc(), KnowledgePoint.id)
    ).all()
    grouped: dict[int, list[tuple[int, str]]] = {}
    for note_id, kp_id, name in rows:
        bucket = grouped.setdefault(int(note_id), [])
        if len(bucket) < KP_LIMIT:
            bucket.append((int(kp_id), str(name)))
    return grouped


def _to_brief(
    item: NoteSummary,
    preview: str | None = None,
    kps: list[tuple[int, str]] | None = None,
) -> NoteBrief:
    pairs = kps or []
    return NoteBrief(
        note_id=item.id,
        title=item.title,
        subject_id=item.subject_id,
        tags=item.tags,
        folder=item.folder,
        created_at=item.created_at,
        updated_at=item.updated_at,
        preview=preview,
        kp_ids=[kp_id for kp_id, _ in pairs],
        kp_names=[name for _, name in pairs],
    )


SPEC = ToolSpec(
    name="list_notes",
    description=(
        "用途：按时间范围/标签/学科列出本人笔记的元数据，用于「上周写了哪些笔记」。"
        "参数 start_date/end_date 为 ISO 日期（含当天），tags 最多 10 个，limit 取 1–50。"
        "只返回标题、标签、文件夹、时间、内容前 200 字预览与知识点（kp_ids/kp_names），不返回正文；"
        "需要正文时改用 search_notes。"
        "多个标签时先按第一个标签分页再在内存过滤，filtered_total 可能小于 total。"
    ),
    input_model=ListNotesIn,
    output_model=ListNotesOut,
    handler=list_notes,
)