"""S6-1 search_questions：题库取材（只给题干，不泄露答案）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.models.question import Question
from app.schemas.question import QuestionSummaryOut
from app.services.question_service import QuestionFilters
from app.services.question_service import list_questions as list_questions_service
from app.utils.pagination import PageParams, SortParams
from sqlalchemy import select

STEM_LIMIT = 2000
EXCERPT_LIMIT = 120
QuestionTypeIn = Literal["单选", "多选", "填空", "解答"]


class SearchQuestionsIn(ToolInput):
    kp_ids: list[int] | None = Field(default=None, min_length=1, max_length=20)
    subject_id: int | None = Field(default=None, ge=1)
    qtype: QuestionTypeIn | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    exclude_recent_days: int = Field(default=14, ge=0, le=90)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("kp_ids")
    @classmethod
    def _dedupe(cls, value: list[int] | None) -> list[int] | None:
        return list(dict.fromkeys(value)) if value else value


class QuestionOption(ToolOutput):
    key: str
    text: str


class QuestionBrief(ToolOutput):
    question_id: int
    stem_md: str
    stem_excerpt: str
    truncated: bool
    options: list[QuestionOption] | None = None
    qtype: str
    difficulty: int
    origin: str
    verified: bool
    kp_names: list[str]


class SearchQuestionsOut(ToolOutput):
    total: int
    items: list[QuestionBrief]


def _load_options(session, question_ids: list[int]) -> dict[int, list[dict[str, str]] | None]:  # noqa: ANN001
    if not question_ids:
        return {}
    rows = session.execute(
        select(Question.id, Question.options_json).where(Question.id.in_(question_ids))
    ).all()
    return {int(row[0]): row[1] for row in rows}


def _to_brief(
    item: QuestionSummaryOut, options_json: list[dict[str, str]] | None
) -> QuestionBrief:
    stem = item.stem_md or ""
    return QuestionBrief(
        question_id=item.id,
        stem_md=stem[:STEM_LIMIT],
        stem_excerpt=stem[:EXCERPT_LIMIT],
        truncated=len(stem) > STEM_LIMIT,
        options=(
            [
                QuestionOption(
                    key=str(option.get("key", "")),
                    text=str(option.get("text", "")),
                )
                for option in options_json
            ]
            if options_json
            else None
        ),
        qtype=item.qtype,
        difficulty=item.difficulty,
        origin=item.origin,
        verified=item.verified,
        kp_names=item.kp_names,
    )


def search_questions(ctx: ToolContext, data: SearchQuestionsIn) -> SearchQuestionsOut:
    exclude_since: datetime | None = None
    if data.exclude_recent_days > 0:
        exclude_since = ctx.now - timedelta(days=data.exclude_recent_days)
    page = list_questions_service(
        ctx.session,
        filters=QuestionFilters(
            kp_ids=data.kp_ids,
            subject_id=data.subject_id,
            qtype=data.qtype,
            difficulty=data.difficulty,
            exclude_user_id=ctx.user.id if exclude_since else None,
            exclude_done_since=exclude_since,
        ),
        page=PageParams(page=1, page_size=data.limit),
        sort=SortParams(sort_by="id", order="desc"),
    )
    options_map = _load_options(ctx.session, [item.id for item in page.items])
    briefs = [_to_brief(item, options_map.get(item.id)) for item in page.items]
    # 同一次取材优先给已验证题目；页内稳定排序，total 仍是过滤后的总数。
    briefs.sort(key=lambda item: (not item.verified, -item.question_id))
    return SearchQuestionsOut(total=page.total, items=briefs)


SPEC = ToolSpec(
    name="search_questions",
    description=(
        "用途：按知识点/题型/难度从公共题库取题干，供组卷取材或定位变式题源题；不返回答案。"
        "参数 kp_ids 最多 20 个，qtype 可选单选/多选/填空/解答，difficulty 取 1–5，"
        "exclude_recent_days 排除本人近 N 天做过的题（0 表示不排除），limit 取 1–50。"
        "返回每题题干（超 2000 字截断）、选项、题型、难度、来源与知识点，已验证题目排在前面。"
    ),
    input_model=SearchQuestionsIn,
    output_model=SearchQuestionsOut,
    handler=search_questions,
)