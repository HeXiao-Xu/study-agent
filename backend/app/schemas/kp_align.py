"""S2-10 对齐队列出入参。"""
from __future__ import annotations

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator


class AlignPair(BaseModel):
    note_id: int = Field(ge=1)
    kp_id: int = Field(ge=1)


class AlignBatchIn(BaseModel):
    items: list[AlignPair] = Field(min_length=1, max_length=100)


class AlignBatchOut(BaseModel):
    confirmed: int = 0
    deleted: int = 0
    skipped: int = 0


class PendingAlignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    note_id: int
    kp_id: int
    confidence: float
    note_title: str = Field(validation_alias=AliasPath("note", "title"))
    note_excerpt: str = Field(
        default="",
        validation_alias=AliasPath("note", "content_text"),
    )
    kp_name: str = Field(validation_alias=AliasPath("knowledge_point", "name"))
    kp_code: str = Field(validation_alias=AliasPath("knowledge_point", "code"))

    @field_validator("note_excerpt", mode="before")
    @classmethod
    def _truncate_excerpt(cls, value: object) -> str:
        text = str(value or "").strip()
        if len(text) <= 300:
            return text
        return f"{text[:300]}…"