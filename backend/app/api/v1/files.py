"""S2-6 文件上传与解析状态（API.md §3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import AppError
from app.core.permissions import require_role
from app.core.storage import ObjectStorage, get_storage
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.files import FileOut, FileStatusOut, FileUploadOut
from app.services import file_service

router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "",
    status_code=201,
    response_model=Envelope[FileUploadOut],
    summary="上传文件（去重）",
)
def upload_file(
    response: Response,
    file: UploadFile | None = File(default=None, description="待上传文件"),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Envelope[FileUploadOut]:
    if file is None or not file.filename:
        raise AppError("请求缺少 file 字段", code=40000, http_status=400)
    record, deduped = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage
    )
    # 首次 201、命中已有记录 200：状态码本身携带“是否新建”的信息
    response.status_code = 200 if deduped else 201
    base = FileOut.model_validate(record)
    data = FileUploadOut(**base.model_dump(), deduped=deduped)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/{file_id}/parse-status",
    response_model=Envelope[FileStatusOut],
    summary="查询解析状态",
)
def get_parse_status(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[FileStatusOut]:
    record = file_service.get_file_status(session, file_id=file_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=FileStatusOut.model_validate(record))