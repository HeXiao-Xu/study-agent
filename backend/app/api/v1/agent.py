"""S6-2 Agent 任务接口（API.md §10）：创建 202 / 查询 / 确认 202。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
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
from app.schemas.common import Envelope
from app.services import agent_service
from app.tasks.queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/agent", tags=["agent"])


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