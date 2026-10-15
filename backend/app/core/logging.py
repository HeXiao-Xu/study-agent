"""结构化日志：每行一个 JSON 对象，自动带 trace_id。

为什么 JSON 而不是人类可读格式：一行一个自包含对象，之后可以用
grep/jq 按 trace_id 把"一次请求的全部日志"直接筛出来（后期排查全靠它，
任务卡 S0-5 的坑也点名这一点）；可读性交给 event 字段的命名。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.context import get_trace_id

# LogRecord 自带的内部字段不进 payload，只留业务附加字段（extra=... 传进来的）
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
    # uvicorn 给部分日志塞的颜色占位字段，无信息量，过滤掉
    "color_message",
}


class JsonFormatter(logging.Formatter):
    """LogRecord → 一行 JSON；exc_info 展开为字符串放 exc 字段。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """进程入口调用一次；接管 root 与 uvicorn 的 handler，保证全进程统一 JSON 流。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn 的三个 logger 自带 handler，会打出格式不一致的第二份日志，统一换成同一个
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.propagate = False
