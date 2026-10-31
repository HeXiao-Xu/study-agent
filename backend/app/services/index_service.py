"""S3-1 索引服务（spec §5）：笔记正文 → 切片 → note_chunks。

唯一入库编排入口：复用 S1-3 index_chunks，不重写向量化。
重建进度复用 async_tasks（每篇笔记一个 index.note 任务），不建新表。
TASK_INDEX_NOTE 定义在这里：tasks/index_note 反向导入 service，
若把常量放 task 模块会形成 service → task → service 的循环导入。
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient
from app.ai.parse.markdown import parse_markdown_text
from app.ai.rag.chunker import Chunk, chunk_document
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.note import Note
from app.models.note_chunk import NoteChunk
from app.models.user import User
from app.schemas.indexing import RebuildFailure, RebuildProgress, RebuildStart
from app.services.indexing import index_chunks

if TYPE_CHECKING:
    from app.tasks.queue import TaskQueue

TASK_INDEX_NOTE = "index.note"
_MAX_FAILURES = 20
_TERMINAL = {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value}


@dataclass(frozen=True)
class NoteIndexResult:
    note_id: int
    chunk_count: int
    total_tokens: int
    elapsed_ms: int
    cost_cny: float
    skipped: bool = False
    reason: str | None = None


def build_note_chunks(note: Note) -> list[Chunk]:
    """笔记 Markdown → 检索原子块；切片算法仍归 S1-2。"""
    document = parse_markdown_text(note.content_md, source=f"note:{note.id}")
    return chunk_document(document)


def index_note(
    session: Session, *, note_id: int, client: EmbeddingClient | None = None
) -> NoteIndexResult:
    """按笔记重建切片；软删/不存在的笔记不改动任何行。"""
    note = session.get(Note, note_id)
    if note is None:
        return NoteIndexResult(note_id, 0, 0, 0, 0.0, True, "note_missing")
    if note.deleted_at is not None:
        return NoteIndexResult(note_id, 0, 0, 0, 0.0, True, "note_deleted")

    started = time.perf_counter()
    chunks = build_note_chunks(note)
    stats = index_chunks(
        session,
        chunks,
        note_id=note.id,
        user_id=note.user_id,
        source_file_id=note.source_file_id,
        replace=True,
        client=client,
    )
    return NoteIndexResult(
        note_id=note.id,
        chunk_count=stats.chunk_count,
        total_tokens=stats.total_tokens,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        cost_cny=stats.cost_cny,
    )


def delete_note_chunks(session: Session, *, note_id: int, user_id: int) -> None:
    """软删笔记时调用；不 commit，与笔记状态同一事务。"""
    session.execute(
        delete(NoteChunk).where(
            NoteChunk.note_id == note_id, NoteChunk.user_id == user_id
        )
    )


def purge_deleted_note_chunks(session: Session) -> int:
    """清掉历史上软删笔记遗留的切片（检索链路不 join notes，靠这里兜底）。"""
    deleted_notes = select(Note.id).where(Note.deleted_at.is_not(None))
    result = session.execute(
        delete(NoteChunk).where(NoteChunk.note_id.in_(deleted_notes))
    )
    return int(result.rowcount or 0)


def start_rebuild(
    session: Session, *, owner: User, queue: TaskQueue
) -> RebuildStart:
    """为一篇笔记建一个 index.note 任务，共享 run_id 用于进度聚合。"""
    # 延迟导入：app.tasks 包会 import 本模块，顶层导入 task_service 会循环
    from app.services import task_service

    note_ids = list(
        session.scalars(
            select(Note.id).where(Note.deleted_at.is_(None)).order_by(Note.id)
        )
    )
    if not note_ids:
        raise InvalidParamError("没有可重建的笔记")

    purged = purge_deleted_note_chunks(session)
    session.commit()

    run_id = uuid.uuid4().hex
    for note_id in note_ids:
        task_service.create_task(
            session,
            owner=owner,
            name=TASK_INDEX_NOTE,
            payload={"note_id": note_id, "run_id": run_id},
            queue=queue,
        )
    return RebuildStart(
        run_id=run_id, total_notes=len(note_ids), purged_chunks=purged
    )


def _note_id_of(task: AsyncTask) -> int | None:
    value = (task.payload or {}).get("note_id")
    return int(value) if value is not None else None


def get_rebuild_progress(session: Session, *, run_id: str) -> RebuildProgress:
    tasks = list(
        session.scalars(
            select(AsyncTask)
            .where(
                AsyncTask.name == TASK_INDEX_NOTE,
                AsyncTask.payload["run_id"].astext == run_id,
            )
            .order_by(AsyncTask.id)
        )
    )
    if not tasks:
        raise NotFoundError("索引重建记录不存在")

    counts = Counter(task.status for task in tasks)
    total = len(tasks)
    terminal = sum(counts[status] for status in _TERMINAL)
    chunks = sum(
        int(task.result.get("chunks") or 0)
        for task in tasks
        if task.status == TaskStatus.SUCCEEDED.value and task.result
    )
    started_values = [task.started_at for task in tasks if task.started_at is not None]
    finished_values = [
        task.finished_at for task in tasks if task.finished_at is not None
    ]
    failures = [
        RebuildFailure(note_id=_note_id_of(task), error=task.error)
        for task in tasks
        if task.status == TaskStatus.FAILED.value
    ][:_MAX_FAILURES]

    return RebuildProgress(
        run_id=run_id,
        total=total,
        pending=counts[TaskStatus.PENDING.value],
        running=counts[TaskStatus.RUNNING.value],
        succeeded=counts[TaskStatus.SUCCEEDED.value],
        failed=counts[TaskStatus.FAILED.value],
        percent=round(terminal / total * 100),
        chunks=chunks,
        started_at=min(started_values) if started_values else None,
        finished_at=(
            max(finished_values) if terminal == total and finished_values else None
        ),
        failures=failures,
    )