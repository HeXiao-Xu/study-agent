"""任务执行器（S2-7，同步）：状态机 + 重试决策。

放在 worker 之外，是为了不装 ARQ 也能单测状态流转；
worker.py 只负责把结果翻译成 ARQ 的 Retry。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import new_session
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.tasks.registry import get_handler

logger = logging.getLogger(__name__)

_TERMINAL = {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value}


@dataclass(slots=True)
class TaskOutcome:
    status: str
    retry_in: float | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def execute_task(task_id: int, job_try: int) -> TaskOutcome:
    """执行一次任务尝试；返回状态与（可选）重试延迟秒数。"""
    with new_session() as session:
        task = session.get(AsyncTask, task_id)
        if task is None:
            logger.warning("task_missing", extra={"task_id": task_id})
            return TaskOutcome(status="missing")
        if task.status in _TERMINAL:
            return TaskOutcome(status=task.status)

        handler = get_handler(task.name)
        if handler is None:
            return _fail(session, task, f"未知任务类型：{task.name}")

        task.status = TaskStatus.RUNNING.value
        task.attempts = job_try
        if task.started_at is None:
            task.started_at = _now()
        session.commit()
        logger.info(
            "task_started",
            extra={"task_id": task.id, "task_name": task.name, "attempts": job_try},
        )

        try:
            result = handler(session, task.payload or {})
        except Exception as exc:
            # 处理函数可能改了一半数据：回滚后再写失败状态
            session.rollback()
            task = session.get(AsyncTask, task_id)
            if task is None:
                return TaskOutcome(status="missing")
            settings = get_settings()
            message = f"第 {job_try} 次失败：{exc}"
            if job_try < settings.task_max_tries:
                task.status = TaskStatus.PENDING.value
                task.error = message
                session.commit()
                delay = settings.task_retry_base_seconds * 2 ** (job_try - 1)
                logger.warning(
                    "task_retry",
                    extra={
                        "task_id": task.id,
                        "task_name": task.name,
                        "attempts": job_try,
                        "delay": delay,
                    },
                )
                return TaskOutcome(status=TaskStatus.PENDING.value, retry_in=delay)
            return _fail(session, task, message)

        task.status = TaskStatus.SUCCEEDED.value
        task.result = result
        task.error = None
        task.finished_at = _now()
        session.commit()
        logger.info(
            "task_succeeded",
            extra={"task_id": task.id, "task_name": task.name, "attempts": job_try},
        )
        return TaskOutcome(status=TaskStatus.SUCCEEDED.value)


def _fail(session: Session, task: AsyncTask, message: str) -> TaskOutcome:
    task.status = TaskStatus.FAILED.value
    task.error = message
    task.finished_at = _now()
    session.commit()
    logger.error(
        "task_failed",
        extra={"task_id": task.id, "task_name": task.name, "error": message},
    )
    return TaskOutcome(status=TaskStatus.FAILED.value)