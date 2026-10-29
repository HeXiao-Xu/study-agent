"""S2-9 知识点树接口（API.md §4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.permissions import require_role
from app.models.note import Note
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.kp import KpCreate, KpNodeOut, KpOrderIn, KpTreeOut, KpUpdate, SubjectOut
from app.schemas.kp_align import AlignBatchIn, AlignBatchOut, PendingAlignOut
from app.schemas.tasks import TaskOut
from app.services import kp_align_service, kp_service, task_service
from app.services.kp_align_service import AlignPair
from app.tasks.kp_align import TASK_KP_ALIGN
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, page_params

router = APIRouter(prefix="/kp", tags=["kp"])


@router.get("/subjects", response_model=Envelope[list[SubjectOut]], summary="学科列表")
def list_subjects(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[list[SubjectOut]]:
    subjects = kp_service.list_subjects(session)
    return Envelope(
        trace_id=get_trace_id(),
        data=[SubjectOut.model_validate(subject) for subject in subjects],
    )


@router.get("/tree", response_model=Envelope[KpTreeOut], summary="知识点树")
def get_tree(
    subject: str = Query(min_length=1, max_length=30, description="学科 code"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[KpTreeOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=kp_service.get_tree(session, subject_code=subject),
    )


@router.post("", status_code=201, response_model=Envelope[KpNodeOut], summary="新建知识点")
def create_kp(
    payload: KpCreate,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[KpNodeOut]:
    kp = kp_service.create_kp(session, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=KpNodeOut.model_validate(kp))


@router.patch("/{kp_id}", response_model=Envelope[KpNodeOut], summary="更新知识点")
def update_kp(
    kp_id: int,
    payload: KpUpdate,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[KpNodeOut]:
    kp = kp_service.update_kp(session, kp_id=kp_id, payload=payload)
    return Envelope(trace_id=get_trace_id(), data=KpNodeOut.model_validate(kp))


@router.delete("/{kp_id}", status_code=204, summary="删除知识点")
def delete_kp(
    kp_id: int,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> None:
    kp_service.delete_kp(session, kp_id=kp_id)


@router.put("/order", status_code=204, summary="批量排序/移动知识点")
def reorder_kp(
    payload: KpOrderIn,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> None:
    kp_service.reorder_children(
        session,
        parent_id=payload.parent_id,
        ordered_ids=payload.ordered_ids,
        moved_id=payload.moved_id,
    )

@router.post(
    "/align/notes/{note_id}",
    status_code=202,
    response_model=Envelope[TaskOut],
    summary="手动重跑笔记对齐",
)
def align_note_endpoint(
    note_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise NotFoundError("笔记不存在")
    if note.user_id != current_user.id:
        raise ForbiddenError("无权访问该资源")
    task = task_service.create_task(
        session,
        owner=current_user,
        name=TASK_KP_ALIGN,
        payload={"note_id": note_id},
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get(
    "/align/pending",
    response_model=Envelope[PageData[PendingAlignOut]],
    summary="待确认队列",
)
def list_pending_align(
    note_id: int | None = Query(None, ge=1),
    params: PageParams = Depends(page_params),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[PendingAlignOut]]:
    page = kp_align_service.list_pending(
        session, viewer=current_user, params=params, note_id=note_id
    )
    return Envelope(trace_id=get_trace_id(), data=page)


@router.post(
    "/align/confirm", response_model=Envelope[AlignBatchOut], summary="批量确认对齐"
)
def confirm_align(
    payload: AlignBatchIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[AlignBatchOut]:
    result = kp_align_service.confirm_pairs(
        session,
        viewer=current_user,
        pairs=[AlignPair(**item.model_dump()) for item in payload.items],
    )
    return Envelope(trace_id=get_trace_id(), data=result)


@router.post(
    "/align/reject", response_model=Envelope[AlignBatchOut], summary="批量忽略对齐"
)
def reject_align(
    payload: AlignBatchIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[AlignBatchOut]:
    result = kp_align_service.reject_pairs(
        session,
        viewer=current_user,
        pairs=[AlignPair(**item.model_dump()) for item in payload.items],
    )
    return Envelope(trace_id=get_trace_id(), data=result)
