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


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class LLMCallScene(StrEnum):
    """llm_call_logs.scene：S3-7 扩展后的实际调用场景。"""

    QA = "qa"
    QUERY_REWRITE = "query_rewrite"
    KP_ALIGN = "kp_align"
    EMBED = "embed"
    MISTAKE = "mistake"
    GEN = "gen"
    AGENT = "agent"


class LLMCallStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


def in_check(column: str, values: Iterable[str]) -> str:
    """渲染 `<column> IN ('a', 'b')`；StrEnum 成员经 f-string 取到值本身。"""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"