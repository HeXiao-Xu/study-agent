"""S6-1 工具基座：上下文、规格、统一错误与调用入口。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    CODE_INTERNAL,
    AppError,
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class ToolInputError(InvalidParamError):
    """工具入参不合法：与 API 的 422/42200 同语义。"""

    def __init__(self, message: str = "工具参数不合法") -> None:
        super().__init__(message)


class ToolExecutionError(AppError):
    """工具执行失败：对外固定话术，不泄露 Prompt/响应正文/堆栈。"""

    def __init__(self, message: str = "工具执行失败") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    """一次工具调用的只读上下文；工具不得 commit。"""

    session: Session
    user: User
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # 写工具必须由确认流程显式放行；当前 11 个工具全只读（S6-6）
    allow_write: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    handler: Callable[[ToolContext, Any], ToolOutput]
    write: bool = False


_INPUT_TYPE_MESSAGES = {
    "missing": "缺少必填字段",
    "too_short": "内容太短",
    "too_long": "内容太长",
    "string_too_short": "不能为空",
    "string_too_long": "内容太长",
    "greater_than_equal": "数值太小",
    "greater_than": "数值太小",
    "less_than_equal": "数值太大",
    "less_than": "数值太大",
    "int_parsing": "必须是整数",
    "int_type": "必须是整数",
    "float_parsing": "必须是数字",
    "float_type": "必须是数字",
    "list_type": "格式不正确",
    "dict_type": "格式不正确",
    "literal_error": "选项不正确",
    "extra_forbidden": "包含未知字段",
}


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    message = str(error.get("msg", "")).removeprefix("Value error, ").strip()
    if message and any("\u4e00" <= char <= "\u9fff" for char in message):
        return message
    return _INPUT_TYPE_MESSAGES.get(str(error.get("type", "")), "参数格式不正确")


def format_validation_error(exc: ValidationError) -> str:
    """把 Pydantic 校验错误转成简短中文（任务输入/工具入参共用）。"""
    return _first_error(exc)


def invoke_tool(name: str, ctx: ToolContext, payload: dict[str, Any]) -> ToolOutput:
    """按工具名校验入参并调用；S6-2 的 act 节点只依赖本入口。"""
    from app.ai.agents.tools.registry import TOOLS

    spec = TOOLS.get(name)
    if spec is None:
        raise NotFoundError("工具不存在")
    if spec.write and not ctx.allow_write:
        logger.warning("agent_tool_write_blocked tool=%s", name)
        raise ForbiddenError("写操作需要人工确认")
    try:
        data = spec.input_model.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "agent_tool_input_invalid tool=%s error=%s", name, _first_error(exc)
        )
        raise ToolInputError(f"工具参数不合法：{_first_error(exc)}") from exc
    try:
        return spec.handler(ctx, data)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - Agent 调用点需要统一失败语义
        logger.exception("agent_tool_failed tool=%s", name)
        raise ToolExecutionError(f"工具 {name} 执行失败") from exc