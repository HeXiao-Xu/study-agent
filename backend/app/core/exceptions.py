"""统一异常与错误响应（契约：docs/API.md §0 与 §13）。

错误码规则（S0-5 定稿）：0 = 成功；错误码 = HTTP 状态前 3 位 + 2 位序号。
基础设施段：40000/40100/40300/40400/42200/42900/50000；
业务码 6xxxx 起按模块分段（S2 各业务卡起用）。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_trace_id

logger = logging.getLogger(__name__)

CODE_OK = 0
CODE_BAD_REQUEST = 40000
CODE_UNAUTHORIZED = 40100
CODE_FORBIDDEN = 40300
CODE_NOT_FOUND = 40400
CODE_CONFLICT = 40900
CODE_VALIDATION = 42200
CODE_PAYLOAD_TOO_LARGE = 41300
CODE_RATE_LIMIT = 42900
CODE_INTERNAL = 50000

# starlette 原生 HTTP 状态 → 业务码；未列出的 4xx 归 40000、5xx 归 50000
_HTTP_TO_CODE = {
    401: CODE_UNAUTHORIZED,
    403: CODE_FORBIDDEN,
    404: CODE_NOT_FOUND,
    409: CODE_CONFLICT,
    413: CODE_PAYLOAD_TOO_LARGE,
    429: CODE_RATE_LIMIT,
}

_PAPER_FIELD_LABELS = {
    "kp_ids": "知识点",
    "total_questions": "题量",
    "qtype_ratio": "题型占比",
    "difficulty_dist": "难度分布",
    "total_score": "总分",
    "duration_min": "时长",
    "exclude_recent_days": "排除近期天数",
    "seed": "随机种子",
    "kp_weights": "知识点权重",
    "title": "试卷标题",
    "question_ids": "题目",
    "selected_question_ids": "当前卷面题目",
    "replace_question_id": "要替换的题目",
    "constraint": "组卷条件",
}
_CODE_LIKE_CHARS = "[]{}'\"≥≤_"


def _is_paper_path(path: str) -> bool:
    return path == "/api/v1/papers" or path.startswith("/api/v1/papers/")


def _paper_validation_message(error: dict[str, object]) -> str:
    """把组卷参数错误翻成不含字段名/括号/英文的普通中文。"""
    loc = [str(part) for part in error.get("loc", [])]
    field = next((part for part in reversed(loc) if part in _PAPER_FIELD_LABELS), "")
    label = _PAPER_FIELD_LABELS.get(field, "填写内容")
    kind = str(error.get("type", ""))
    ctx = error.get("ctx") or {}
    if kind == "missing":
        return f"请填写{label}"
    if kind == "too_short":
        if field == "kp_ids":
            return "请至少选择 1 个知识点"
        if field == "question_ids":
            return "请至少保留 1 道题"
        return f"{label}不能为空"
    if kind == "too_long":
        return f"{label}数量太多"
    if kind == "greater_than_equal":
        return f"{label}不能小于 {ctx.get('ge')}"
    if kind == "greater_than":
        return f"{label}必须大于 {ctx.get('gt')}"
    if kind == "less_than_equal":
        return f"{label}不能大于 {ctx.get('le')}"
    if kind == "less_than":
        return f"{label}必须小于 {ctx.get('lt')}"
    if kind in ("int_parsing", "int_type"):
        return f"{label}必须是整数"
    if kind in ("float_parsing", "float_type"):
        return f"{label}必须是数字"
    if kind in ("dict_type", "list_type"):
        return f"{label}格式不正确"
    if kind == "string_too_short":
        return f"{label}不能为空"
    if kind == "literal_error":
        return f"{label}选项不正确"
    if kind == "value_error":
        message = str(error.get("msg", "")).removeprefix("Value error, ").strip()
        if message and not any(char in message for char in _CODE_LIKE_CHARS):
            return message
    return f"{label}填写不正确"


def _trace_of(request: Request) -> str:
    """contextvar 优先（内层异常处理器可见）；最外层兜底处理器退回 scope state。

    为什么需要两处：ContextVar 只向下传播；500 兜底处理器挂在最外层
    ServerErrorMiddleware 上，看不到内层 set 的值，但它拿得到同一个 scope。
    """
    tid = get_trace_id()
    if tid != "-":
        return tid
    state: dict[str, object] = request.scope.get("state") or {}
    return str(state.get("trace_id", "-"))


def _error_body(request: Request, code: int, message: str) -> dict[str, object]:
    """所有错误响应的唯一出口格式 {code, message, trace_id, data:None}。"""
    return {"code": code, "message": message, "trace_id": _trace_of(request), "data": None}


class AppError(Exception):
    """可控错误基类：路由/服务层 raise，由全局处理器统一转壳。"""

    def __init__(self, message: str, *, code: int = CODE_BAD_REQUEST, http_status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, code=CODE_NOT_FOUND, http_status=404)


class AuthError(AppError):
    def __init__(self, message: str = "未认证或凭据已过期") -> None:
        super().__init__(message, code=CODE_UNAUTHORIZED, http_status=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权访问") -> None:
        super().__init__(message, code=CODE_FORBIDDEN, http_status=403)


class ConflictError(AppError):
    def __init__(self, message: str = "资源冲突") -> None:
        super().__init__(message, code=CODE_CONFLICT, http_status=409)


class InvalidParamError(AppError):
    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__(message, code=CODE_VALIDATION, http_status=422)


class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "文件过大") -> None:
        super().__init__(message, code=CODE_PAYLOAD_TOO_LARGE, http_status=413)


class StorageUnavailableError(AppError):
    """对象存储不可用：对外固定话术，不泄露 endpoint/凭据。"""

    def __init__(self, message: str = "文件存储不可用") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


class TaskQueueUnavailableError(AppError):
    """任务入队失败：Redis 不可用或队列操作异常（不泄露地址）。"""

    def __init__(self, message: str = "任务队列不可用") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


class PdfRenderError(AppError):
    """PDF 渲染失败：对外固定话术，不泄露浏览器路径/堆栈。"""

    def __init__(self, message: str = "PDF 渲染失败") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)


def install_exception_handlers(app: FastAPI) -> None:
    """把四类异常统一转成 {code, message, trace_id, data:null}。"""

    @app.exception_handler(AppError)
    async def on_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 预期内的业务异常：按声明返回，不刷堆栈（刷堆栈会淹没真正的意外错误）
        return JSONResponse(status_code=exc.http_status, content=_error_body(request, exc.code, exc.message))

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 框架自身抛的 404/405 等（如访问不存在的路由）也必须走统一壳
        if exc.status_code in _HTTP_TO_CODE:
            code = _HTTP_TO_CODE[exc.status_code]
        else:
            code = CODE_BAD_REQUEST if exc.status_code < 500 else CODE_INTERNAL
        return JSONResponse(status_code=exc.status_code, content=_error_body(request, code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 细节全量进日志（服务端排查用）；对外壳只给首条错误定位，保持格式严格
        logger.warning("validation_failed", extra={"errors": exc.errors()})
        first = exc.errors()[0] if exc.errors() else {}
        if _is_paper_path(request.url.path):
            message = _paper_validation_message(first)
        else:
            loc = ".".join(str(part) for part in first.get("loc", []))
            message = f"参数校验失败: {loc} {first.get('msg', '')}".strip()
        return JSONResponse(status_code=422, content=_error_body(request, CODE_VALIDATION, message))

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 未知异常：完整堆栈只进日志；对外不透内部细节（防止泄露实现信息）
        logger.exception("unhandled_exception")
        return JSONResponse(status_code=500, content=_error_body(request, CODE_INTERNAL, "服务器内部错误"))
