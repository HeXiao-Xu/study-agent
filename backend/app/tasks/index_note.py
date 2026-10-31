"""S3-1 索引任务：执行 index_service.index_note（不自行 commit 任务状态）。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.index_service import TASK_INDEX_NOTE, index_note
from app.tasks.registry import register

logger = logging.getLogger(__name__)


@register(TASK_INDEX_NOTE)
def index_note_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = int(payload.get("note_id") or 0)
    if note_id <= 0:
        raise ValueError("payload 缺少 note_id")
    result = index_note(session, note_id=note_id)
    data = {
        "note_id": result.note_id,
        "chunks": result.chunk_count,
        "tokens": result.total_tokens,
        "elapsed_ms": result.elapsed_ms,
        "cost_cny": result.cost_cny,
        "skipped": result.skipped,
        "reason": result.reason,
    }
    logger.info(
        "index_note_done",
        extra={
            "note_id": result.note_id,
            "chunks": result.chunk_count,
            "tokens": result.total_tokens,
            "skipped": result.skipped,
        },
    )
    return data