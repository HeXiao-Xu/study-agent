"""S4-1 题库出入参：字段与 SCHEMA §5.1 一一对应。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

_QType = Literal["单选", "多选", "填空", "解答"]
_Origin = Literal["textbook", "exam", "mock", "upload", "ai"]


class OptionIn(BaseModel):
    key: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


class QuestionCreateIn(BaseModel):
    subject_id: int
    stem_md: str = Field(min_length=5)
    options: list[OptionIn] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: _QType
    difficulty: int = Field(ge=1, le=5)
    kp_ids: list[int] = Field(default_factory=list)
    origin: _Origin = "upload"
    tags: list[str] | None = None
