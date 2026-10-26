"""S2-7 异步任务服务：提交（先落库再入队）、查询与权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    TaskQueueUnavailableError,
)
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.user import User
from app.tasks.demo import TASK_DEMO_SLEEP
from app.tasks.queue import TaskQueue
from app.tasks.registry import get_handler


def create_task(
    session: Session,
    *,
    owner: User,
    name: str,
    payload: dict[str, Any],
    queue: TaskQueue,
) -> AsyncTask:
    if get_handler(name) is None:
        raise InvalidParamError(f"未知任务类型：{name}")
    task = AsyncTask(
        user_id=owner.id,
        name=name,
        status=TaskStatus.PENDING.value,
        payload=payload,
        attempts=0,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    try:
        queue.enqueue(name, task.id)
    except Exception as exc:
        # 入队失败不能留下永远 pending 的幽灵任务
        task.status = TaskStatus.FAILED.value
        task.error = "任务入队失败"
        task.finished_at = datetime.now(timezone.utc)
        session.commit()
        raise TaskQueueUnavailableError() from exc
    return task


def submit_demo(
    session: Session,
    *,
    owner: User,
    seconds: int,
    fail: bool,
    queue: TaskQueue,
) -> AsyncTask:
    return create_task(
        session,
        owner=owner,
        name=TASK_DEMO_SLEEP,
        payload={"seconds": seconds, "fail": fail},
        queue=queue,
    )


def get_task(session: Session, *, task_id: int, viewer: User) -> AsyncTask:
    task = session.get(AsyncTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    if task.user_id != viewer.id:
        raise ForbiddenError("无权访问该任务")
    return task