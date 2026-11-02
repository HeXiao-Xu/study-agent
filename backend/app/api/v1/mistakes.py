"""S4-2 错题接口：拍照录入、列表、统计、录入、详情、更新、复习、删除。

路由只做「参数校验 → service → Envelope」；归属隔离与状态机都在 mistake_service。
`/photo` 与 `/stats` 必须声明在 `/{mistake_id}` 之前，否则会被路径参数吞掉
（与 S4-1 `/questions/import` 同款坑）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import InvalidParamError
from app.core.storage import ObjectStorage, get_storage
from app.models.enums import MISTAKE_STATUSES
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.mistake import (
    MistakeCreateIn,
    MistakeCreateOut,
    MistakeDetailOut,
    MistakeReviewIn,
    MistakeStatsOut,
    MistakeSummaryOut,
    MistakeUpdateIn,
)
from app.schemas.tasks import TaskOut
from app.services import mistake_service
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/mistakes", tags=["mistakes"])


@router.post("/photo", status_code=202, response_model=Envelope[TaskOut], summary="拍照录入错题")
def create_from_photo(
    file: UploadFile | None = File(default=None, description="题目照片（PNG/JPEG）"),
    subject_id: int = Query(..., description="学科 id"),
    my_answer_md: str | None = Form(default=None, description="学生手填作答（可选）"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    if file is None or not file.filename:
        raise InvalidParamError("请求缺少 file 字段")
    task = mistake_service.start_photo_recognize(
        session,
        owner=current_user,
        subject_id=subject_id,
        upload=file,
        storage=storage,
        queue=queue,
        my_answer_md=my_answer_md,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get("/stats", response_model=Envelope[MistakeStatsOut], summary="错题统计")
def get_stats(
    created_from: datetime | None = Query(None, description="创建时间下界（含）"),
    created_to: datetime | None = Query(None, description="创建时间上界（含）"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeStatsOut]:
    data = mistake_service.stats(
        session, user_id=current_user.id, created_from=created_from, created_to=created_to
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get("", response_model=Envelope[PageData[MistakeSummaryOut]], summary="错题列表")
def list_mistakes(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    status: str | None = Query(None, description="状态：待订正/已订正/已掌握"),
    cause_type: str | None = Query(None, description="错因（S4-3 起才有数据）"),
    kp_id: int | None = Query(None, description="只出关联该知识点的错题"),
    created_from: datetime | None = Query(None, description="创建时间下界（含）"),
    created_to: datetime | None = Query(None, description="创建时间上界（含）"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[MistakeSummaryOut]]:
    # 先按值集校验，非法状态不进 service（与 PATCH 的状态校验同一份常量）。
    if status is not None and status not in MISTAKE_STATUSES:
        raise InvalidParamError(f"非法的错题状态：{status}")
    filters = mistake_service.MistakeFilters(
        status=status,
        cause_type=cause_type,
        kp_id=kp_id,
        created_from=created_from,
        created_to=created_to,
    )
    data = mistake_service.list_mistakes(
        session, user_id=current_user.id, filters=filters, page=params, sort=sort
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("", status_code=201, response_model=Envelope[MistakeCreateOut], summary="从题库录入错题")
def create_mistake(
    payload: MistakeCreateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeCreateOut]:
    detail, created = mistake_service.create_from_question(
        session, user_id=current_user.id, payload=payload
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=MistakeCreateOut(**detail.model_dump(), created=created),
    )


@router.get("/{mistake_id}", response_model=Envelope[MistakeDetailOut], summary="错题详情")
def get_mistake(
    mistake_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    data = mistake_service.get_detail(
        session, user_id=current_user.id, mistake_id=mistake_id
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.patch("/{mistake_id}", response_model=Envelope[MistakeDetailOut], summary="更新错题")
def update_mistake(
    mistake_id: int,
    payload: MistakeUpdateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    data = mistake_service.update_mistake(
        session, user_id=current_user.id, mistake_id=mistake_id, payload=payload
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/{mistake_id}/review", response_model=Envelope[MistakeDetailOut], summary="复习记录")
def review_mistake(
    mistake_id: int,
    payload: MistakeReviewIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[MistakeDetailOut]:
    data = mistake_service.record_review(
        session, user_id=current_user.id, mistake_id=mistake_id, correct=payload.correct
    )
    return Envelope(trace_id=get_trace_id(), data=data)


@router.delete("/{mistake_id}", status_code=204, summary="删除错题")
def delete_mistake(
    mistake_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> None:
    mistake_service.delete_mistake(session, user_id=current_user.id, mistake_id=mistake_id)
