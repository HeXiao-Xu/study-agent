"""S6-1 list_mistakes：本人错题的筛选与摘要。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.services.mistake_service import (
    MistakeFilters,
    MistakeSummaryOut,
    list_mistakes as list_mistakes_service,
)
from app.utils.pagination import PageParams, SortParams

MistakeStatusIn = Literal["待订正", "已订正", "已掌握"]


class ListMistakesIn(ToolInput):
    kp_ids: list[int] | None = Field(default=None, min_length=1, max_length=20)
    status: MistakeStatusIn | None = None
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("kp_ids")
    @classmethod
    def _dedupe_kp_ids(cls, value: list[int] | None) -> list[int] | None:
        return list(dict.fromkeys(value)) if value else value

    @model_validator(mode="after")
    def _check_range(self) -> "ListMistakesIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class MistakeBrief(ToolOutput):
    mistake_id: int
    question_id: int
    status: str
    correct_streak: int
    stem_excerpt: str
    subject_id: int
    qtype: str
    difficulty: int
    kp_names: list[str]
    cause_type: str | None = None
    created_at: datetime
    last_review_at: datetime | None = None


class ListMistakesOut(ToolOutput):
    total: int
    items: list[MistakeBrief]


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, timezone.utc)


def _to_brief(item: MistakeSummaryOut) -> MistakeBrief:
    return MistakeBrief(
        mistake_id=item.id,
        question_id=item.question_id,
        status=item.status,
        correct_streak=item.correct_streak,
        stem_excerpt=item.stem_excerpt,
        subject_id=item.subject_id,
        qtype=item.qtype,
        difficulty=item.difficulty,
        kp_names=item.kp_names,
        cause_type=item.cause_type,
        created_at=item.created_at,
        last_review_at=item.last_review_at,
    )


def list_mistakes(ctx: ToolContext, data: ListMistakesIn) -> ListMistakesOut:
    created_from = _utc_midnight(data.start_date) if data.start_date else None
    created_to = (
        _utc_midnight(data.end_date + timedelta(days=1)) - timedelta(microseconds=1)
        if data.end_date
        else None
    )
    page = list_mistakes_service(
        ctx.session,
        user_id=ctx.user.id,
        filters=MistakeFilters(
            status=data.status,
            kp_ids=data.kp_ids,
            created_from=created_from,
            created_to=created_to,
        ),
        page=PageParams(page=1, page_size=data.limit),
        sort=SortParams(sort_by="created_at", order="desc"),
    )
    return ListMistakesOut(total=page.total, items=[_to_brief(item) for item in page.items])


SPEC = ToolSpec(
    name="list_mistakes",
    description=(
        "用途：按知识点/状态/时间筛选本人错题；用于「最近错了哪些」「按薄弱知识点聚合」。"
        "参数 kp_ids 最多 20 个，status 可选待订正/已订正/已掌握，start_date/end_date 为 ISO 日期（含当天），"
        "limit 取 1–50。返回错题摘要（题干片段、状态、题型、难度、知识点、错因），不返回答案与作答正文。"
    ),
    input_model=ListMistakesIn,
    output_model=ListMistakesOut,
    handler=list_mistakes,
)