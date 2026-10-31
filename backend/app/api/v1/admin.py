"""S3-1 管理端接口：索引重建与进度（API.md §11）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.indexing import RebuildProgress, RebuildStart
from app.services import index_service
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