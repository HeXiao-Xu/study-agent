"""S6-2/S6-5 Agent 任务接口（API.md §10）：创建 202 / 列表 / 查询 / 确认 202。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.agent import (
    AgentConfirmIn,
    AgentStepOut,
    AgentTaskCreateIn,
    AgentTaskDetailOut,
    AgentTaskOut,
)
from app.schemas.common import Envelope, PageData
from app.services import agent_service
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/agent", tags=["agent"])

AgentTaskStatusIn = Literal[
    "pending", "running", "waiting_confirm", "succeeded", "failed"
]


def _detail(task, steps) -> AgentTaskDetailOut:  # noqa: ANN001
    base = AgentTaskOut.model_validate(task)
    return AgentTaskDetailOut(
        **base.model_dump(),
        input=task.input_json,
        result=task.result_json,
        steps=[
            AgentStepOut(
                step_no=step.step_no,
                thought=step.thought,
                tool_name=step.tool_name,
                tool_input=step.tool_input_json,
                tool_output=step.tool_output_json,
                latency_ms=step.latency_ms,
                status=step.status,
            )
            for step in steps
        ],
    )


@router.post(
    "/tasks",
    status_code=202,
    response_model=Envelope[AgentTaskOut],
    summary="创建 Agent 任务",
)
def create_agent_task(
    payload: AgentTaskCreateIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[AgentTaskOut]:
    task = agent_service.create_agent_task(
        session,
        owner=current_user,
        task_type=payload.task_type,
        task_input=payload.input,
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=AgentTaskOut.model_validate(task))


@router.get(
    "/tasks",
    response_model=Envelope[PageData[AgentTaskOut]],
    summary="Agent 任务分页列表",
)
def list_agent_tasks(
    status: AgentTaskStatusIn | None = Query(default=None),
    task_type: str | None = Query(default=None, min_length=1, max_length=50),
    page: PageParams = Depends(page_params),
    sorting: SortParams = Depends(sort_params),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[PageData[AgentTaskOut]]:
    data = agent_service.list_agent_tasks(
        session,
        user_id=current_user.id,
        status=status,
        task_type=task_type,
        page=page,
        sort=sorting,
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/tasks/{task_id}",
    response_model=Envelope[AgentTaskDetailOut],
    summary="查询 Agent 任务与步骤",
)
def get_agent_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[AgentTaskDetailOut]:
    task, steps = agent_service.get_agent_task(
        session, task_id=task_id, viewer=current_user
    )
    return Envelope(trace_id=get_trace_id(), data=_detail(task, steps))


@router.post(
    "/tasks/{task_id}/retry",
    status_code=202,
    response_model=Envelope[AgentTaskOut],
    summary="重跑失败的 Agent 任务",
)
def retry_agent_task(
    task_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[AgentTaskOut]:
    task = agent_service.retry_agent_task(
        session, task_id=task_id, viewer=current_user, queue=queue
    )
    return Envelope(trace_id=get_trace_id(), data=AgentTaskOut.model_validate(task))


@router.post(
    "/tasks/{task_id}/confirm",
    status_code=202,
    response_model=Envelope[AgentTaskOut],
    summary="人工确认并恢复 Agent 任务",
)
def confirm_agent_task(
    task_id: int,
    payload: AgentConfirmIn,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[AgentTaskOut]:
    task = agent_service.confirm_agent_task(
        session,
        task_id=task_id,
        viewer=current_user,
        decision=payload.model_dump(),
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=AgentTaskOut.model_validate(task))