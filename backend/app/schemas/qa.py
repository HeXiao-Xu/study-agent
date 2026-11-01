"""S3-5 问答接口出入参（API.md §5）。"""
from __future__ import annotations

from datetime import date, datetime
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
    cached: bool = False


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


class QaConversationOut(BaseModel):
    id: str
    title: str
    scope: QaScopeIn | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0


class QaHistoryCitationOut(BaseModel):
    index: int
    note_id: int | None = None
    chunk_id: int | None = None
    title: str | None = None
    heading_path: str | None = None
    page_no: int | None = None
    snippet: str | None = None
    score: float | None = None
    note_available: bool = True


class QaHistoryMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content_md: str
    created_at: datetime
    refused: bool = False
    citations: list[QaHistoryCitationOut] = Field(default_factory=list)


class QaConversationDetailOut(BaseModel):
    conversation: QaConversationOut
    messages: list[QaHistoryMessageOut]


class QaConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        clean = " ".join(value.split())
        if not clean:
            raise ValueError("title 不能为空")
        return clean