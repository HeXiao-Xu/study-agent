"""ARQ Worker 入口（S2-7）。

启动（backend/ 目录下）：
    ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings

同步处理函数在线程池里跑，避免阻塞 Worker 的事件循环。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from arq import Retry
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.tasks.runner import execute_task

logger = logging.getLogger(__name__)


async def run_task(ctx: dict[str, Any], task_id: int) -> str:
    job_try = int(ctx.get("job_try", 1))
    outcome = await asyncio.to_thread(execute_task, task_id, job_try)
    if outcome.retry_in is not None:
        raise Retry(defer=outcome.retry_in)
    return outcome.status


async def _on_startup(ctx: dict[str, Any]) -> None:
    # 不配日志的话根 logger 默认 WARNING，task_started/succeeded 这些 INFO 会被吞
    setup_logging(get_settings().log_level)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [run_task]
    redis_settings = _redis_settings()
    on_startup = _on_startup
    max_tries = get_settings().task_max_tries
    job_timeout = get_settings().task_job_timeout_seconds
    keep_result = get_settings().task_result_keep_seconds
    health_check_interval = 30