"""S2-6 文件上传服务（spec §7）。

文件名只做展示：对象键用内容哈希，路径穿越在源头就被砍掉。
类型靠「扩展名白名单 + 文件头 magic」双校验：只信扩展名会被改名绕过。
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    InvalidParamError,
    NotFoundError,
    PayloadTooLargeError,
)
from app.core.permissions import ensure_student_access
from app.core.storage import ObjectStorage
from app.models.file import File
from app.models.note_chunk import NoteChunk
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.files import FileSummaryOut
from app.utils.pagination import PageParams, paginate_query

MAX_FILENAME_LENGTH = 200
_CHUNK_SIZE = 1024 * 1024
_KEY_PREFIX = "uploads"

# ext -> (mime, magic)；magic=None 表示文本类，仅拒绝 NUL
TYPE_TABLE: dict[str, tuple[str, bytes | None]] = {
    "pdf": ("application/pdf", b"%PDF-"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    "md": ("text/markdown", None),
    "txt": ("text/plain", None),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def allowed_extensions() -> list[str]:
    raw = get_settings().upload_allowed_extensions
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def sanitize_filename(name: str | None) -> str:
    raw = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _CONTROL.sub("", raw).strip().strip(".")
    if not cleaned or cleaned in {".", ".."}:
        raise InvalidParamError("文件名不合法")
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, _, ext = cleaned.rpartition(".")
        if not ext or len(ext) > 20:
            stem, ext = cleaned, ""
        keep = MAX_FILENAME_LENGTH - (len(ext) + 1 if ext else 0)
        cleaned = (stem[:keep] + f".{ext}") if ext else stem[:keep]
    return cleaned


def detect_type(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = allowed_extensions()
    if ext not in allowed or ext not in TYPE_TABLE:
        shown = "，".join(allowed) if allowed else "（未配置）"
        raise InvalidParamError(
            f"不支持的文件类型：{ext or '（无扩展名）'}（允许：{shown}）"
        )
    return ext, TYPE_TABLE[ext][0]


def check_magic(head: bytes, ext: str) -> None:
    _, magic = TYPE_TABLE[ext]
    if magic is None:
        if b"\x00" in head[:4096]:
            raise InvalidParamError("文件内容与类型不符")
        return
    if not head.startswith(magic):
        raise InvalidParamError("文件内容与类型不符")

def _build_key(user_id: int, sha256: str, ext: str) -> str:
    return f"{_KEY_PREFIX}/{user_id}/{sha256[:2]}/{sha256}.{ext}"


def upload_file(
    session: Session,
    *,
    owner: User,
    upload: UploadFile,
    storage: ObjectStorage,
    parse: bool = True,
) -> tuple[File, bool]:
    """流式读完 → 查重 → 写对象 → 写库；返回 (记录, 是否复用已有记录)。"""
    filename = sanitize_filename(upload.filename)
    ext, mime = detect_type(filename)
    if not parse and not mime.startswith("image/"):
        raise InvalidParamError("该文件不是图片")
    limit = get_settings().upload_max_size_mb * 1024 * 1024

    digest = hashlib.sha256()
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
        first = True
        while True:
            chunk = upload.file.read(_CHUNK_SIZE)
            if not chunk:
                break
            if first:
                check_magic(chunk[:4096], ext)
                first = False
            size += len(chunk)
            if size > limit:
                raise PayloadTooLargeError(
                    f"文件超过 {get_settings().upload_max_size_mb}MB 上限"
                )
            digest.update(chunk)
            spool.write(chunk)
        if first:
            raise InvalidParamError("文件内容为空")

        sha256 = digest.hexdigest()
        key = _build_key(owner.id, sha256, ext)

        existing = session.scalar(
            select(File).where(File.user_id == owner.id, File.sha256 == sha256)
        )
        if existing is not None and storage.exists(key):
            return existing, True

        spool.seek(0)
        storage.put(key, spool, size=size, content_type=mime)
        if existing is not None:
            # 行在、对象被清理过：补齐对象即可，不新增行
            return existing, False

        record = File(
            user_id=owner.id,
            filename=filename,
            mime=mime,
            size=size,
            storage_path=key,
            sha256=sha256,
            parse_status="done" if not parse else "pending",
            parse_progress=100 if not parse else 0,
            parse_finished_at=datetime.now(timezone.utc) if not parse else None,
        )
        session.add(record)
        try:
            session.commit()
        except IntegrityError:
            # 并发同文件：先到的那条赢了，对象键相同，别删对象
            session.rollback()
            winner = session.scalar(
                select(File).where(File.user_id == owner.id, File.sha256 == sha256)
            )
            if winner is None:
                raise ConflictError("文件上传冲突，请重试")
            return winner, True
        except Exception:
            session.rollback()
            try:
                storage.delete(key)
            except Exception:  # 补偿删除失败不掩盖原始异常
                pass
            raise
        session.refresh(record)
        return record, False


def get_file_status(session: Session, *, file_id: int, viewer: User) -> File:
    record = session.get(File, file_id)
    if record is None:
        raise NotFoundError("文件不存在")
    if record.user_id != viewer.id:
        ensure_student_access(session, viewer, record.user_id)
    return record


def read_image(session: Session, *, file_id: int, viewer: User) -> File:
    """取图前统一做权限与 MIME 校验；非图片不返回字节。"""
    record = get_file_status(session, file_id=file_id, viewer=viewer)
    if not record.mime.startswith("image/"):
        raise InvalidParamError("不是图片文件")
    return record


def list_files(
    session: Session, *, owner: User, params: PageParams
) -> PageData[FileSummaryOut]:
    """只列本人文件；固定创建时间倒序，避免深分页顺序漂移。"""
    stmt = (
        select(File)
        .where(File.user_id == owner.id)
        .order_by(File.created_at.desc(), File.id.desc())
    )
    return paginate_query(session, stmt, params, item_model=FileSummaryOut)


def list_chunks(
    session: Session, *, file_id: int, viewer: User, limit: int
) -> list[NoteChunk]:
    """切片预览复用文件权限；只查该文件产出的切片。"""
    record = get_file_status(session, file_id=file_id, viewer=viewer)
    stmt = (
        select(NoteChunk)
        .where(
            NoteChunk.source_file_id == record.id,
            NoteChunk.user_id == record.user_id,
        )
        .order_by(NoteChunk.chunk_index.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
