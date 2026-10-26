"""S2-7 异步任务接口：提交 demo 任务 + 轮询状态。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.tasks import DemoTaskIn, TaskDetailOut, TaskOut
from app.services import task_service
from app.tasks.queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/demo",
    status_code=202,
    response_model=Envelope[TaskOut],
    summary="提交演示任务（验收用）",
)
def submit_demo(
    payload: DemoTaskIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    task = task_service.submit_demo(
        session,
        owner=current_user,
        seconds=payload.seconds,
        fail=payload.fail,
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get(
    "/{task_id}",
    response_model=Envelope[TaskDetailOut],
    summary="查询任务状态",
)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[TaskDetailOut]:
    task = task_service.get_task(session, task_id=task_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=TaskDetailOut.model_validate(task))