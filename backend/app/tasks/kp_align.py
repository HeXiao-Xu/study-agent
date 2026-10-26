"""S2-10 知识点对齐任务（同步 handler，不自行 commit）。"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.note import Note
from app.services.kp_align_service import align_note
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_KP_ALIGN = "kp.align"


@register(TASK_KP_ALIGN)
def kp_align_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = int(payload.get("note_id") or 0)
    if note_id <= 0:
        raise ValueError("payload 缺少 note_id")
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        return {"note_id": note_id, "skipped": True}
    stats = align_note(session, note=note)
    result = asdict(stats) | {"note_id": note_id}
    logger.info("kp_align_done", extra=result)
    return result