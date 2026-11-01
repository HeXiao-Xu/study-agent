"""S3-1 管理端接口：索引重建与进度（API.md §11）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.indexing import RebuildProgress, RebuildStart
from app.schemas.prompt import PromptCreate, PromptTemplateOut
from app.schemas.usage import UsageReport
from app.services import index_service, prompt_service, usage_service
from app.tasks.queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/index/rebuild",
    status_code=202,
    response_model=Envelope[RebuildStart],
    summary="全量重建笔记索引（每篇笔记一个 index.note 任务）",
)
def rebuild_index(
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[RebuildStart]:
    data = index_service.start_rebuild(session, owner=current_user, queue=queue)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/index/runs/{run_id}",
    response_model=Envelope[RebuildProgress],
    summary="查询索引重建进度",
)
def get_rebuild_run(
    run_id: str = Path(..., pattern="^[0-9a-f]{32}$", description="重建 run_id"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[RebuildProgress]:
    data = index_service.get_rebuild_progress(session, run_id=run_id)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/usage",
    response_model=Envelope[UsageReport],
    summary="查询 LLM/Embedding 用量（UTC 日 × scene × model）",
)
def get_usage(
    range: str = Query("7d", pattern="^(1d|7d|30d)$"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[UsageReport]:
    data = usage_service.get_usage(session, range_key=range)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/prompts",
    response_model=Envelope[list[PromptTemplateOut]],
    summary="查询 Prompt 版本历史",
)
def list_prompt_templates(
    name: str | None = None,
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[list[PromptTemplateOut]]:
    rows = prompt_service.list_prompts(session, name=name)
    data = [PromptTemplateOut.model_validate(row) for row in rows]
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post(
    "/prompts",
    status_code=201,
    response_model=Envelope[PromptTemplateOut],
    summary="新建 Prompt 版本（不可变）",
)
def create_prompt_template(
    payload: PromptCreate,
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[PromptTemplateOut]:
    prompt = prompt_service.create_prompt_version(
        session,
        name=payload.name,
        content=payload.content,
        version=payload.version,
        variables_json=payload.variables_json,
        model_hint=payload.model_hint,
        created_by=current_user.id,
        activate=payload.activate,
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=PromptTemplateOut.model_validate(prompt),
    )


@router.put(
    "/prompts/{prompt_id}/activate",
    response_model=Envelope[PromptTemplateOut],
    summary="启用指定 Prompt 版本",
)
def activate_prompt_template(
    prompt_id: int = Path(..., ge=1, description="Prompt 版本 id"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[PromptTemplateOut]:
    prompt = prompt_service.activate_prompt(session, prompt_id)
    return Envelope(
        trace_id=get_trace_id(),
        data=PromptTemplateOut.model_validate(prompt),
    )