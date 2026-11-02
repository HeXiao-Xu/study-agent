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


class QuestionOrigin(StrEnum):
    """questions.origin：题目来源（SCHEMA §5.1）。"""

    TEXTBOOK = "textbook"
    EXAM = "exam"
    MOCK = "mock"
    UPLOAD = "upload"
    AI = "ai"


class QuestionType(StrEnum):
    """questions.qtype：题型。用中文值，与卷面/前端展示一致（SCHEMA §10.6）。"""

    SINGLE = "单选"
    MULTIPLE = "多选"
    BLANK = "填空"
    SOLUTION = "解答"


def in_check(column: str, values: Iterable[str]) -> str:
    """渲染 `<column> IN ('a', 'b')`；StrEnum 成员经 f-string 取到值本身。"""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class MistakeStatus(StrEnum):
    """错题状态机（SCHEMA §10.7 固定中文值）。"""

    TODO = "待订正"
    CORRECTED = "已订正"
    MASTERED = "已掌握"


class CauseType(StrEnum):
    """错因分类（方案 6.3 六类 + 作答缺失时的 unknown）。"""

    CONCEPT = "概念不清"
    CALC = "计算失误"
    READING = "审题偏差"
    METHOD = "方法不当"
    FORGET = "知识遗忘"
    TIME = "时间不足"
    UNKNOWN = "unknown"


MISTAKE_STATUSES: tuple[str, ...] = tuple(item.value for item in MistakeStatus)
CAUSE_TYPES: tuple[str, ...] = tuple(item.value for item in CauseType)