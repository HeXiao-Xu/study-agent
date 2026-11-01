"""请求级上下文：trace_id 的定义与存取。

为什么用 contextvars 而不是全局变量：asyncio 下每个请求一个协程，
ContextVar 天然按协程隔离，并发请求互不串号；在线程池里执行也有正确语义。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def get_trace_id() -> str:
    """当前协程的 trace_id；无请求上下文（如启动期）时返回 '-'。"""
    return _trace_id.get()


def set_trace_id(value: str) -> Token[str]:
    """写入 trace_id，返回 token 供中间件在请求结束时复位，防止跨请求泄漏。"""
    return _trace_id.set(value)


def reset_trace_id(token: Token[str]) -> None:
    _trace_id.reset(token)


def get_current_user_id() -> int | None:
    """当前请求的登录用户；脚本/后台任务无请求上下文时为 None。"""
    return _current_user_id.get()


def set_current_user_id(value: int | None) -> Token[int | None]:
    return _current_user_id.set(value)


def reset_current_user_id(token: Token[int | None]) -> None:
    _current_user_id.reset(token)
