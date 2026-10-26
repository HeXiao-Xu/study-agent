"""任务注册表（S2-7）：任务名 → 同步处理函数。

处理函数签名 (Session, payload) -> dict | None；不得自行 commit，
由 runner 统一提交/回滚。名字以 ".all" 结尾是为未来的批量任务预留。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

TaskHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]

HANDLERS: dict[str, TaskHandler] = {}


def register(name: str) -> Callable[[TaskHandler], TaskHandler]:
    if not name or name.endswith(".all"):
        raise ValueError(f"非法任务名：{name!r}")

    def decorator(func: TaskHandler) -> TaskHandler:
        if name in HANDLERS:
            raise ValueError(f"任务名已注册：{name}")
        HANDLERS[name] = func
        return func

    return decorator


def get_handler(name: str) -> TaskHandler | None:
    return HANDLERS.get(name)