"""S2-5 笔记出入参（API.md §2）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TAGS = 20
MAX_TAG_LENGTH = 30


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"单个标签不超过 {MAX_TAG_LENGTH} 字")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content_md: str = Field(min_length=1, max_length=200_000)
    subject_id: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    folder: str | None = Field(default=None, max_length=100)

    @field_validator("title", "content_md")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = Field(default=None, min_length=1, max_length=200_000)
    subject_id: int | None = Field(default=None, ge=1)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    folder: str | None = Field(default=None, max_length=100)

    @field_validator("title", "content_md")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("tags")
    @classmethod
    def _normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_tags(value)


class NoteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subject_id: int | None
    tags: list[str] | None
    folder: str | None
    created_at: datetime
    updated_at: datetime


class NoteOut(NoteSummary):
    content_md: str
    source_file_id: int | None