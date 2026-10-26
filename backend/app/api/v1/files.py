"""S2-6 文件上传与解析状态（API.md §3）。"""
from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import AppError
from app.core.permissions import require_role
from app.core.storage import ObjectStorage, get_storage
from app.models.enums import ParseStatus
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.files import FileOut, FileStatusOut, FileUploadOut
from app.services import file_service, task_service
from app.tasks.parse_document import TASK_PARSE_DOCUMENT
from app.tasks.queue import TaskQueue, get_task_queue

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
    parse: bool = Query(True, description="是否入队文档解析；编辑器图片传 false"),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[FileUploadOut]:
    if file is None or not file.filename:
        raise AppError("请求缺少 file 字段", code=40000, http_status=400)
    record, deduped = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage, parse=parse
    )
    # done/parsing 的去重命中不重复入队；pending（新文件）与 failed（重试）补入队
    if parse and record.parse_status in {
        ParseStatus.PENDING.value,
        ParseStatus.FAILED.value,
    }:
        task_service.create_task(
            session,
            owner=current_user,
            name=TASK_PARSE_DOCUMENT,
            payload={"file_id": record.id},
            queue=queue,
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


@router.get(
    "/{file_id}/image",
    response_class=Response,
    summary="读取图片（内联展示）",
)
def get_image(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    record = file_service.read_image(session, file_id=file_id, viewer=current_user)
    buffer = BytesIO()
    storage.download_to(record.storage_path, buffer)
    return Response(
        content=buffer.getvalue(),
        media_type=record.mime,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": (
                "inline; filename*=UTF-8''" + quote(record.filename, safe="")
            ),
            "ETag": f'"{record.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )