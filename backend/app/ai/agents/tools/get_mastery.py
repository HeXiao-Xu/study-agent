"""S6-1 get_mastery：批量取本人知识点掌握度（未评估不冒充 0）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.services import mastery_service


class GetMasteryIn(ToolInput):
    kp_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("kp_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))


class MasteryBrief(ToolOutput):
    kp_id: int
    kp_name: str
    subject_id: int
    exam_weight: float | None = None
    mastery_t: float | None = None
    assessed: bool
    attempts: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


class GetMasteryOut(ToolOutput):
    assessed_count: int
    unassessed_kp_ids: list[int]
    missing_kp_ids: list[int]
    items: list[MasteryBrief]


def get_mastery(ctx: ToolContext, data: GetMasteryIn) -> GetMasteryOut:
    states = mastery_service.mastery_details(
        ctx.session,
        user_id=ctx.user.id,
        kp_ids=data.kp_ids,
        now=ctx.now,
    )
    found = {state.kp_id for state in states}
    return GetMasteryOut(
        assessed_count=sum(1 for state in states if state.assessed),
        unassessed_kp_ids=[state.kp_id for state in states if not state.assessed],
        missing_kp_ids=[kp_id for kp_id in data.kp_ids if kp_id not in found],
        items=[
            MasteryBrief(
                kp_id=state.kp_id,
                kp_name=state.kp_name,
                subject_id=state.subject_id,
                exam_weight=state.exam_weight,
                mastery_t=state.mastery_t,
                assessed=state.assessed,
                attempts=state.attempts,
                stability=state.stability,
                last_practice_at=state.last_practice_at,
                due_at=state.due_at,
            )
            for state in states
        ],
    )


SPEC = ToolSpec(
    name="get_mastery",
    description=(
        "用途：批量查询本人知识点的有效掌握度 M_t 与复习到期时间，作为组卷/复习推荐的依据。"
        "参数 kp_ids 为 1–50 个知识点 id。"
        "返回每条知识点的 M_t（未评估为 null）、attempts/stability/due_at，并区分未评估与不存在的 id。"
    ),
    input_model=GetMasteryIn,
    output_model=GetMasteryOut,
    handler=get_mastery,
)