"""S3-4 Prompt 管理出入参（API.md §11）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
VERSION_PATTERN = r"^[A-Za-z0-9._-]{1,32}$"


class PromptCreate(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    content: str = Field(min_length=1, max_length=20000)
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)
    variables_json: list[str] | None = None
    model_hint: str | None = Field(default=None, max_length=100)
    activate: bool = False

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content 不能为空")
        return value

    @field_validator("variables_json")
    @classmethod
    def _variables_not_blank(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("variables_json 不能包含空字符串")
        return value


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    content: str
    variables_json: list[str] | None
    model_hint: str | None
    is_active: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime