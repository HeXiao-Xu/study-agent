"""S2-1 枚举常量：值集的唯一来源（SCHEMA §10；CHECK 文本由 in_check 生成）。

为什么不用 PostgreSQL ENUM：改值集需要 ALTER TYPE，加值不可回滚，downgrade
就变成不可执行；TEXT + CHECK 可以用 DROP/ADD CONSTRAINT 对称回退。
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"


class EdgeRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    CONFUSABLE = "confusable"
    CONTAINS = "contains"


class EdgeSource(StrEnum):
    AI = "ai"
    MANUAL = "manual"


def in_check(column: str, values: Iterable[str]) -> str:
    """渲染 `<column> IN ('a', 'b')`；StrEnum 成员经 f-string 取到值本身。"""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"