"""S3-5 问答接口出入参（API.md §5）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QaScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: int | None = Field(None, ge=1)
    folder: str | None = Field(None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("folder")
    @classmethod
    def _strip_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _check_range(self) -> "QaScopeIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class QaAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    scope: QaScopeIn | None = None
    conversation_id: str | None = Field(None, pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("question 不能为空")
        return clean


class QaCitationMeta(BaseModel):
    index: int
    note_id: int
    chunk_id: int
    title: str | None = None
    heading_path: str | None = None
    page_no: int | None = None
    snippet: str


class QaMetaData(BaseModel):
    conversation_id: str
    user_message_id: int
    citations: list[QaCitationMeta]


class QaDeltaData(BaseModel):
    text: str


class QaSuggestion(BaseModel):
    type: Literal["rephrase", "note"]
    text: str
    note_id: int | None = None


class QaDoneData(BaseModel):
    message_id: int
    conversation_id: str
    tokens: int
    latency_ms: int
    refused: bool
    refusal_reason: str | None = None
    suggestions: list[QaSuggestion] = Field(default_factory=list)


class QaErrorData(BaseModel):
    code: int
    message: str


class QaMessageCitationOut(BaseModel):
    id: int
    message_id: int
    chunk_id: int | None = None
    note_id: int | None = None
    question_id: int | None = None
    score: float | None = None
    snippet: str | None = None
    page_no: int | None = None
    bbox_json: dict[str, object] | None = None
    rank: int | None = None