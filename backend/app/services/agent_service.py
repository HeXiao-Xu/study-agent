"""S6-2 Agent 任务 service：唯一业务入口（建任务/查询/确认/执行编排）。

状态机执行会逐节点 commit `agent_steps` 与 `agent_tasks.state_json`，让
GET 轮询能看到实时进度；这是 S2-8 文档解析 Worker 之外的第二个「handler
自行 commit」例外，且不提交 async_tasks 状态。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.constants import TASK_RUN_AGENT
from app.ai.agents.engine import (
    AgentEngine,
    AgentState,
    AgentStepLimitError,
    RunContext,
    StepRecorder,
)
from app.ai.agents.state import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_WAITING_CONFIRM,
    jsonable,
    new_state,
)
from app.ai.agents.tasks import get_task_spec
from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
)
from app.models.agent_step import AgentStep
from app.models.agent_task import AgentTask
from app.models.user import User
from app.schemas.agent import AgentTaskOut
from app.schemas.common import PageData
from app.services import task_service
from app.tasks.queue import TaskQueue
from app.utils.pagination import (
    PageParams,
    SortParams,
    apply_sort,
    paginate_query,
)

logger = logging.getLogger(__name__)

_TERMINAL = {STATUS_SUCCEEDED, STATUS_FAILED}

_AGENT_TASK_SORTABLE = {
    "created_at": AgentTask.created_at,
    "id": AgentTask.id,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DbStepRecorder(StepRecorder):
    """把每个节点写成 agent_steps，并同步 agent_tasks 快照。"""

    def __init__(self, session: Session, task: AgentTask) -> None:
        self.session = session
        self.task = task

    def record(
        self,
        *,
        step_no: int,
        thought: str | None,
        status: str,
        state: AgentState,
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        tool_output: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self.session.add(
            AgentStep(
                task_id=self.task.id,
                step_no=step_no,
                thought=thought,
                tool_name=tool_name,
                tool_input_json=jsonable(tool_input) if tool_input is not None else None,
                tool_output_json=jsonable(tool_output) if tool_output is not None else None,
                latency_ms=latency_ms,
                status=status,
            )
        )
        snapshot = jsonable(state)
        self.task.steps_count = step_no
        self.task.state_json = snapshot
        self.task.token_cost = int(snapshot.get("token_cost") or 0)
        task_status = str(snapshot.get("status") or STATUS_RUNNING)
        self.task.status = task_status
        if task_status == STATUS_WAITING_CONFIRM:
            self.task.result_json = {
                "artifacts": snapshot.get("artifacts") or {},
                "citations": snapshot.get("citations") or [],
                "awaiting_confirm": True,
            }
        elif task_status in _TERMINAL:
            self.task.result_json = snapshot.get("result")
            self.task.error = snapshot.get("error")
            self.task.finished_at = _now()
        self.session.commit()


def create_agent_task(
    session: Session,
    *,
    owner: User,
    task_type: str,
    task_input: dict[str, Any],
    queue: TaskQueue,
) -> AgentTask:
    spec = get_task_spec(task_type)
    if spec is None:
        raise InvalidParamError(f"任务类型尚未启用：{task_type}")
    validated = spec.validate_input(task_input)
    task = AgentTask(
        user_id=owner.id,
        task_type=task_type,
        input_json=validated,
        status="pending",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    try:
        task_service.create_task(
            session,
            owner=owner,
            name=TASK_RUN_AGENT,
            payload={"agent_task_id": task.id},
            queue=queue,
        )
    except Exception:
        task.status = STATUS_FAILED
        task.error = "任务入队失败"
        task.finished_at = _now()
        session.commit()
        raise
    return task


def _load_owned(session: Session, *, task_id: int, viewer: User) -> AgentTask:
    task = session.get(AgentTask, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    if task.user_id != viewer.id:
        raise ForbiddenError("无权访问该任务")
    return task


def get_agent_task(
    session: Session, *, task_id: int, viewer: User
) -> tuple[AgentTask, list[AgentStep]]:
    task = _load_owned(session, task_id=task_id, viewer=viewer)
    steps = list(
        session.scalars(
            select(AgentStep)
            .where(AgentStep.task_id == task.id)
            .order_by(AgentStep.step_no.asc())
        ).all()
    )
    return task, steps


def list_agent_tasks(
    session: Session,
    *,
    user_id: int,
    status: str | None,
    task_type: str | None,
    page: PageParams,
    sort: SortParams,
) -> PageData[AgentTaskOut]:
    """本人 Agent 任务分页列表；筛选全部下推 SQL。"""
    stmt = select(AgentTask).where(AgentTask.user_id == user_id)
    if status:
        stmt = stmt.where(AgentTask.status == status)
    if task_type:
        stmt = stmt.where(AgentTask.task_type == task_type)
    stmt = apply_sort(
        stmt,
        sort_by=sort.sort_by or "created_at",
        order=sort.order if sort.sort_by else "desc",
        allowed=_AGENT_TASK_SORTABLE,
        default_sort="created_at",
    )
    # 同秒创建时用 id 兜底，避免翻页重复/漏行（S4-1/S4-5 同类坑）
    stmt = stmt.order_by(AgentTask.id.desc())
    return paginate_query(session, stmt, page, item_model=AgentTaskOut)


def confirm_agent_task(
    session: Session,
    *,
    task_id: int,
    viewer: User,
    decision: dict[str, Any],
    queue: TaskQueue,
) -> AgentTask:
    task = _load_owned(session, task_id=task_id, viewer=viewer)
    if task.status != STATUS_WAITING_CONFIRM:
        raise ConflictError("当前状态不需要确认")
    old_state = dict(task.state_json or {})
    old_error = task.error
    state = old_state
    state["confirm_decision"] = {
        "approved": bool(decision.get("approved")),
        "comment": decision.get("comment"),
        "edits": decision.get("edits"),
    }
    state["resume_from"] = "confirm"
    state["need_human_confirm"] = False
    task.state_json = jsonable(state)
    task.status = "pending"
    task.error = None
    task.finished_at = None
    session.commit()
    try:
        task_service.create_task(
            session,
            owner=viewer,
            name=TASK_RUN_AGENT,
            payload={"agent_task_id": task.id},
            queue=queue,
        )
    except Exception:
        task.state_json = old_state
        task.status = STATUS_WAITING_CONFIRM
        task.error = old_error
        session.commit()
        raise
    return task


def _mark_failed(session: Session, task: AgentTask, message: str) -> None:
    task.status = STATUS_FAILED
    task.error = message
    task.finished_at = _now()
    session.commit()


def run_agent_task(session: Session, agent_task_id: int) -> dict[str, Any]:
    task = session.get(AgentTask, agent_task_id)
    if task is None:
        return {"status": "missing"}
    if task.status in _TERMINAL or task.status == STATUS_WAITING_CONFIRM:
        return {"status": task.status}

    user = session.get(User, task.user_id)
    if user is None:
        _mark_failed(session, task, "任务发起者不存在")
        return {"status": task.status}
    spec_cls = get_task_spec(task.task_type)
    if spec_cls is None:
        _mark_failed(session, task, f"任务类型尚未启用：{task.task_type}")
        return {"status": task.status}
    spec = spec_cls(task.input_json)

    settings = get_settings()
    if task.state_json:
        state = dict(task.state_json)
        if state.get("resume_from") != "confirm":
            state["resume_from"] = "resume"
        state["status"] = STATUS_RUNNING
        state["error"] = None
    else:
        budget = int(task.input_json.get("token_budget") or settings.agent_token_budget)
        state = new_state(
            user_id=task.user_id,
            task_input=task.input_json,
            token_budget=budget,
            max_steps=settings.agent_max_steps,
        )
    task.status = STATUS_RUNNING
    if task.started_at is None:
        task.started_at = _now()
    task.finished_at = None
    session.commit()

    recorder = DbStepRecorder(session, task)
    engine = AgentEngine(
        spec,
        RunContext(session=session, user=user, recorder=recorder),
    )
    try:
        engine.run(state)
    except AgentStepLimitError as exc:
        _mark_failed(session, task, str(exc))
    except Exception:  # noqa: BLE001 - 图异常统一收敛为任务失败，堆栈进日志
        logger.exception("agent_task_failed task_id=%s", agent_task_id)
        session.rollback()
        task = session.get(AgentTask, agent_task_id)
        if task is not None:
            _mark_failed(session, task, "任务执行失败")
    session.refresh(task)
    return {"status": task.status}


__all__ = [
    "TASK_RUN_AGENT",
    "DbStepRecorder",
    "create_agent_task",
    "get_agent_task",
    "list_agent_tasks",
    "confirm_agent_task",
    "run_agent_task",
]