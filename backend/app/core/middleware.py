"""TraceId 中间件：每请求生成/沿用 trace_id，注入日志上下文与响应头。

透出格式（定稿 docs/API.md §0）：请求头 X-Trace-Id 可选传入（前端/网关续链），
响应头一律回传；请求内日志与错误体里的 trace_id 与之同值。

为什么是纯 ASGI 而不是 BaseHTTPMiddleware：少一层任务包装，且能在
http.response.start 阶段对所有响应（含异常处理器生成的 4xx/5xx）统一补头。
"""

from __future__ import annotations

import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import reset_trace_id, set_trace_id

# 只接受受限字符集与长度：防日志注入 / 防超长头撑爆日志行
_VALID_TRACE = re.compile(r"^[0-9A-Za-z\-]{1,64}$")


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        incoming = headers.get("x-trace-id", "")
        trace_id = incoming if _VALID_TRACE.fullmatch(incoming) else uuid.uuid4().hex

        # 两处存放：contextvar 供请求路径内的日志/内层异常处理器读取；
        # scope.state 供最外层 500 兜底处理器读取（contextvar 不向上传播）
        token = set_trace_id(trace_id)
        scope.setdefault("state", {})
        scope["state"]["trace_id"] = trace_id

        async def send_with_trace_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-trace-id", trace_id.encode("ascii"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_header)
        finally:
            reset_trace_id(token)
