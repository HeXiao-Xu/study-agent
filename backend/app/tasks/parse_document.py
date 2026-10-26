"""S2-8 文档解析任务：复用 S1-1/S1-2/S1-3，回写 files 状态与进度。

处理函数不重复实现解析/切片/向量化；失败时先提交 failed/error_msg
再抛出，避免 runner 的 rollback 把文件状态留在 parsing。
"""
from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.parse import parse_document
from app.ai.rag.chunker import chunk_document
from app.core.exceptions import InvalidParamError
from app.core.storage import get_storage
from app.models.enums import ParseStatus
from app.models.file import File
from app.models.note import Note
from app.services.indexing import index_chunks
from app.tasks.registry import register
from app.utils.markdown_text import to_plain_text

logger = logging.getLogger(__name__)

TASK_PARSE_DOCUMENT = "parse.document"

_PROGRESS_STARTED = 10
_PROGRESS_PARSED = 50
_PROGRESS_CHUNKED = 80
_MAX_ERROR_CHARS = 500
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@register(TASK_PARSE_DOCUMENT)
def parse_document_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    file_id = int(payload["file_id"])
    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if file.parse_status == ParseStatus.DONE.value:
        return {"file_id": file_id, "skipped": True}

    _mark_parsing(session, file)
    started = time.perf_counter()
    tmp_path: Path | None = None
    try:
        suffix = Path(file.filename).suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            raise InvalidParamError("图片解析暂未支持（待 OCR）")
        if suffix not in _SUPPORTED_SUFFIXES:
            raise InvalidParamError(f"不支持的文件类型：{suffix or '（无扩展名）'}")

        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = Path(handle.name)
        with handle:
            get_storage().download_to(file.storage_path, handle)

        doc = parse_document(tmp_path)
        if doc.is_scanned:
            raise InvalidParamError("扫描版 PDF：无可抽取文本，需 OCR（后续任务）")
        content_md = "\n\n".join(
            block.text.strip() for block in doc.blocks if block.text.strip()
        )
        if not content_md:
            raise InvalidParamError("未解析出可用文本")
        file.parse_progress = _PROGRESS_PARSED
        session.commit()

        chunks = chunk_document(doc)
        if not chunks:
            raise InvalidParamError("未解析出可用文本")
        file.parse_progress = _PROGRESS_CHUNKED
        session.commit()

        note = _upsert_note(session, file=file, content_md=content_md)
        stats = index_chunks(
            session,
            chunks,
            note_id=note.id,
            user_id=file.user_id,
            source_file_id=file.id,
            replace=True,
        )

        file.parse_status = ParseStatus.DONE.value
        file.parse_progress = 100
        file.error_msg = None
        file.parse_finished_at = _now()
        file.parse_result_json = {
            "parser": doc.parser,
            "pages": len({b.page_no for b in doc.blocks if b.page_no is not None}),
            "blocks": len(doc.blocks),
            "chunks": stats.chunk_count,
            "tokens": stats.total_tokens,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "degraded_reason": doc.degraded_reason,
            "note_id": note.id,
        }
        session.commit()
        logger.info(
            "file_parse_done",
            extra={
                "file_id": file.id,
                "chunks": stats.chunk_count,
                "tokens": stats.total_tokens,
            },
        )
        _enqueue_align(file)
        return {
            "file_id": file.id,
            "chunks": stats.chunk_count,
            "tokens": stats.total_tokens,
            "parser": doc.parser,
        }
    except Exception as exc:
        session.rollback()
        current = session.get(File, file_id)
        message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        if current is not None:
            current.parse_status = ParseStatus.FAILED.value
            current.error_msg = message
            current.parse_finished_at = _now()
            session.commit()
        logger.error("file_parse_failed", extra={"file_id": file_id, "error": message})
        raise
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:  # Windows 上解析器可能仍持有句柄
                logger.warning(
                    "file_parse_tmp_cleanup_failed",
                    extra={"file_id": file_id, "error": str(cleanup_exc)},
                )


def _mark_parsing(session: Session, file: File) -> None:
    file.parse_status = ParseStatus.PARSING.value
    file.parse_progress = _PROGRESS_STARTED
    file.error_msg = None
    if file.parse_started_at is None:
        file.parse_started_at = _now()
    session.commit()
    logger.info("file_parse_started", extra={"file_id": file.id})


def _upsert_note(session: Session, *, file: File, content_md: str) -> Note:
    note = session.scalar(
        select(Note).where(Note.user_id == file.user_id, Note.source_file_id == file.id)
    )
    title = (Path(file.filename).stem or file.filename)[:200]
    if note is None:
        note = Note(
            user_id=file.user_id,
            subject_id=None,
            title=title,
            content_md=content_md,
            content_text=to_plain_text(content_md),
            tags=None,
            folder=None,
            source_file_id=file.id,
        )
        session.add(note)
    else:
        note.title = title
        note.content_md = content_md
        note.content_text = to_plain_text(content_md)
    session.flush()
    return note

def _enqueue_align(file: File) -> None:
    """解析成功后入队对齐；独立 session，避免把任务提交混进 handler 主事务。"""
    from app.core.db import get_session_factory
    from app.models.user import User
    from app.services import task_service
    from app.tasks.kp_align import TASK_KP_ALIGN
    from app.tasks.queue import get_task_queue

    session = get_session_factory()()
    try:
        user = session.get(User, file.user_id)
        note = session.scalar(
            select(Note).where(
                Note.user_id == file.user_id, Note.source_file_id == file.id
            )
        )
        if user is None or note is None:
            return
        task_service.create_task(
            session,
            owner=user,
            name=TASK_KP_ALIGN,
            payload={"note_id": note.id},
            queue=get_task_queue(),
        )
    except Exception as exc:  # noqa: BLE001 —— 对齐是增强能力，不能影响解析结果
        logger.warning(
            "kp_align_enqueue_failed", extra={"file_id": file.id, "error": str(exc)}
        )
    finally:
        session.close()
