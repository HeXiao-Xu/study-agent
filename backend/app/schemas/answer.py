"""S5-4 在线作答接口出入参（API.md §8）。"""
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_SELF_RATINGS = (0.0, 0.5, 1.0)


class AnswerSaveIn(BaseModel):
    """PUT /papers/{id}/answers/{question_id}。"""

    user_answer_md: str | None = Field(default=None, max_length=20000)
    time_spent_sec: int | None = Field(default=None, ge=0, le=86400)


class AnswerSubmitItemIn(BaseModel):
    question_id: int
    user_answer_md: str | None = Field(default=None, max_length=20000)
    self_rated: float | None = None
    time_spent_sec: int | None = Field(default=None, ge=0, le=86400)

    @model_validator(mode="after")
    def _check_self_rated(self) -> Self:
        if self.self_rated is not None and float(self.self_rated) not in ALLOWED_SELF_RATINGS:
            raise ValueError("self_rated 只能是 0 / 0.5 / 1")
        return self


class AnswerSubmitIn(BaseModel):
    items: list[AnswerSubmitItemIn] = Field(min_length=1, max_length=200)


class PaperBriefOut(BaseModel):
    id: int
    title: str
    status: str
    total_score: int


class AnswerRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: int
    user_answer_md: str | None
    self_rated: float | None
    is_correct: bool | None
    score: float | None
    time_spent_sec: int | None
    saved: bool


class PaperAnswersOut(BaseModel):
    paper: PaperBriefOut
    items: list[AnswerRowOut]
    submitted: bool
    earned_score: float | None


class GradedItemOut(BaseModel):
    question_id: int
    qtype: str
    is_correct: bool
    score: float
    self_rated: float | None
    user_answer_md: str | None


class MasteryDeltaOut(BaseModel):
    kp_id: int
    kp_name: str
    mastery_before: float | None
    mastery_after: float | None
    attempts_delta: int


class PaperSubmitOut(BaseModel):
    paper_id: int
    score: float
    total_score: int
    correct_count: int
    question_count: int
    elapsed_sec: int
    items: list[GradedItemOut]
    mastery: list[MasteryDeltaOut]
    mistake_question_ids: list[int]
    missing_question_ids: list[int]

