"""S4-1 题库接口：导入试卷（异步）、列表、详情、新增、编辑、拆分、合并、删除。

路由只做「参数校验 → service → Envelope」；权限与业务规则都在 question_service。
`/import` 必须声明在 `/{question_id}` 之前，否则会被路径参数吞掉。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import AppError, ForbiddenError
from app.core.storage import ObjectStorage, get_storage
from app.models.enums import QuestionOrigin
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.question import (
    QuestionCreateIn,
    QuestionDetailOut,
    QuestionMergeIn,
    QuestionSplitIn,
    QuestionSummaryOut,
    QuestionUpdateIn,
)
from app.schemas.tasks import TaskOut
from app.services import file_service, question_service, task_service
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

router = APIRouter(prefix="/questions", tags=["questions"])

_SUPPORTED_SUFFIXES = {".pdf", ".docx"}


@router.post(
    "/import", status_code=202, response_model=Envelope[TaskOut], summary="导入试卷并异步切题"
)
def import_questions(
    file: UploadFile | None = File(default=None, description="PDF 或 DOCX 试卷"),
    subject_id: int = Query(..., description="学科 id"),
    origin: str = Query("upload", description="题目来源：textbook/exam/mock/upload"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    if file is None or not file.filename:
        raise AppError("请求缺少 file 字段", code=40000, http_status=400)
    if Path(file.filename).suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise AppError("仅支持 PDF 或 DOCX 试卷", code=40000, http_status=400)
    if origin not in {item.value for item in QuestionOrigin}:
        raise AppError(f"非法的题目来源：{origin}", code=40000, http_status=400)
    if current_user.role == "student" and origin != QuestionOrigin.UPLOAD.value:
        raise ForbiddenError("学生导入的题目只能记为学生上传")
    question_service.ensure_subject_exists(session, subject_id)
    record, _ = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage, parse=False
    )
    task = task_service.create_task(
        session,
        owner=current_user,
        name=question_service.TASK_QUESTION_EXTRACT,
        payload={"file_id": record.id, "subject_id": subject_id,
                 "origin": origin, "created_by": current_user.id},
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get("", response_model=Envelope[PageData[QuestionSummaryOut]], summary="题目列表（公共题库）")
def list_questions(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    subject_id: int | None = Query(None, description="学科 id"),
    qtype: str | None = Query(None, description="单选/多选/填空/解答"),
    kp_id: int | None = Query(None, description="只出挂了该知识点的题"),
    origin: str | None = Query(None, description="题目来源"),
    mine: bool = Query(False, description="只看自己导入的题"),
    verified: bool | None = Query(None, description="答案是否来自卷面"),
    keyword: str | None = Query(None, description="题干关键词"),
    source_file_id: int | None = Query(None, description="按导入的试卷筛选"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[QuestionSummaryOut]]:
    filters = question_service.QuestionFilters(
        subject_id=subject_id,
        qtype=qtype,
        kp_id=kp_id,
        origin=origin,
        created_by=current_user.id if mine else None,
        verified=verified,
        keyword=keyword,
        source_file_id=source_file_id,
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=question_service.list_questions(session, filters=filters, page=params, sort=sort),
    )


@router.get("/{question_id}", response_model=Envelope[QuestionDetailOut], summary="题目详情")
def get_question(
    question_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    detail = question_service.get_question_detail(session, question_id=question_id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.post("", status_code=201, response_model=Envelope[QuestionDetailOut], summary="手动新增题目")
def create_question(
    payload: QuestionCreateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    if current_user.role == "student" and payload.origin != QuestionOrigin.UPLOAD.value:
        raise ForbiddenError("学生录入的题目只能记为学生上传")
    question = question_service.create_question(session, payload=payload, creator=current_user)
    detail = question_service.get_question_detail(session, question_id=question.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.patch("/{question_id}", response_model=Envelope[QuestionDetailOut], summary="编辑题目")
def update_question(
    question_id: int,
    payload: QuestionUpdateIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    question = question_service.update_question(
        session, question_id=question_id, payload=payload, viewer=current_user
    )
    detail = question_service.get_question_detail(session, question_id=question.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.post(
    "/{question_id}/split",
    response_model=Envelope[list[QuestionDetailOut]],
    summary="按标记把一题切成两题",
)
def split_question(
    question_id: int,
    payload: QuestionSplitIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[list[QuestionDetailOut]]:
    created = question_service.split_question(
        session, question_id=question_id, split_at=payload.split_at, viewer=current_user
    )
    data = [
        question_service.get_question_detail(session, question_id=item.id) for item in created
    ]
    return Envelope(trace_id=get_trace_id(), data=data)


@router.post("/merge", response_model=Envelope[QuestionDetailOut], summary="合并多道题为一道")
def merge_questions(
    payload: QuestionMergeIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[QuestionDetailOut]:
    merged = question_service.merge_questions(
        session, ids=payload.ids, viewer=current_user
    )
    detail = question_service.get_question_detail(session, question_id=merged.id)
    return Envelope(trace_id=get_trace_id(), data=detail)


@router.delete("/{question_id}", status_code=204, summary="删除题目")
def delete_question(
    question_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> None:
    question_service.delete_question(session, question_id=question_id, viewer=current_user)