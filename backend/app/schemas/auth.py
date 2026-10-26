"""S2-2 认证出入参（契约：docs/API.md §1）。

用户名统一 trim + 小写：避免 “Alice / alice” 被当成两个账号；
口令长度上限 128 是防御性限制（Argon2 本身不截断）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RegisterableRole = Literal["student", "teacher", "parent"]


def _normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if any(char.isspace() for char in normalized):
        raise ValueError("用户名不能包含空白字符")
    if not 3 <= len(normalized) <= 50:
        raise ValueError("用户名长度需为 3–50 个字符")
    return normalized


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=50)
    grade: str | None = Field(default=None, max_length=20)
    role: RegisterableRole = "student"

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return _normalize_username(value)

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, value: str) -> str:
        nickname = value.strip()
        if not nickname:
            raise ValueError("昵称不能为空")
        return nickname

    @field_validator("grade")
    @classmethod
    def _grade(cls, value: str | None) -> str | None:
        if value is None:
            return None
        grade = value.strip()
        return grade or None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        username = value.strip().lower()
        if any(char.isspace() for char in username):
            raise ValueError("用户名不能包含空白字符")
        return username


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    grade: str | None
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut