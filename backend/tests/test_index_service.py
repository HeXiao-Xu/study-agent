"""S3-1 索引服务与重建进度测试（spec §5）：fake session，零网络。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.rag.chunker import Chunk, ChunkType
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.note import Note
from app.services import index_service, task_service
from app.services.indexing import IndexingResult


class FakeResult:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self, *, note=None, note_ids=None, tasks=None, rowcount=0) -> None:
        self.note = note
        self.note_ids = note_ids or []
        self.tasks = tasks or []
        self.rowcount = rowcount
        self.executed: list[object] = []
        self.commits = 0
        self.rolled_back = 0

    def get(self, entity: type, pk: int):
        assert entity is Note
        return self.note

    def scalars(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is Note:
            return iter(self.note_ids)
        if entity is AsyncTask:
            return iter(self.tasks)
        raise AssertionError(f"unexpected entity: {entity}")

    def execute(self, statement: object):
        self.executed.append(statement)
        return FakeResult(self.rowcount)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def _note(
    *, note_id: int = 7, deleted: bool = False, source_file_id: int | None = None
) -> Note:
    note = Note(
        user_id=3,
        subject_id=None,
        title="函数",
        content_md="# 函数\n\n设 $f(x)$ 在区间 D 内单调递增。\n\n## 单调性\n\n定义。",
        content_text="设 在区间 D 内单调递增。",
        tags=None,
        folder=None,
        source_file_id=source_file_id,
    )
    note.id = note_id
    note.deleted_at = datetime.now(timezone.utc) if deleted else None
    return note


def _chunk() -> Chunk:
    return Chunk(
        content="函数的单调性",
        chunk_index=0,
        heading_path="函数/单调性",
        page_no=None,
        token_count=6,
        chunk_type=ChunkType.note,
    )


def _sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_build_note_chunks_sets_heading_path() -> None:
    chunks = index_service.build_note_chunks(_note())
    assert chunks
    assert chunks[0].heading_path == "函数"
    assert all(chunk.chunk_type == ChunkType.note for chunk in chunks)


def test_index_note_passes_scope_and_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    note = _note(source_file_id=12)
    captured: dict[str, object] = {}

    def fake_index_chunks(session, chunks, **kwargs):
        captured.update(kwargs)
        return IndexingResult(
            chunk_count=len(chunks),
            vector_dim=1024,
            total_tokens=6,
            elapsed_ms=9,
            cost_cny=0.01,
        )

    monkeypatch.setattr(index_service, "build_note_chunks", lambda note: [_chunk()])
    monkeypatch.setattr(index_service, "index_chunks", fake_index_chunks)

    result = index_service.index_note(FakeSession(note=note), note_id=7)

    assert captured["note_id"] == 7
    assert captured["user_id"] == 3
    assert captured["source_file_id"] == 12
    assert captured["replace"] is True
    assert result.chunk_count == 1
    assert result.skipped is False


def test_index_note_missing_note_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(index_service, "index_chunks", lambda *a, **k: called.append(1))

    result = index_service.index_note(FakeSession(note=None), note_id=99)

    assert result.skipped is True
    assert result.reason == "note_missing"
    assert called == []


def test_index_note_deleted_note_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(index_service, "index_chunks", lambda *a, **k: called.append(1))

    result = index_service.index_note(FakeSession(note=_note(deleted=True)), note_id=7)

    assert result.skipped is True
    assert result.reason == "note_deleted"
    assert called == []


def test_delete_note_chunks_filters_note_and_user() -> None:
    session = FakeSession()
    index_service.delete_note_chunks(session, note_id=7, user_id=3)

    sql = _sql(session.executed[0])
    assert "DELETE FROM note_chunks" in sql
    assert "note_id = 7" in sql
    assert "user_id = 3" in sql
    assert session.commits == 0


def test_purge_deleted_note_chunks_filters_soft_deleted() -> None:
    session = FakeSession(rowcount=4)

    assert index_service.purge_deleted_note_chunks(session) == 4

    sql = _sql(session.executed[0])
    assert "DELETE FROM note_chunks" in sql
    assert "deleted_at IS NOT NULL" in sql
    assert session.commits == 0


def test_start_rebuild_creates_one_task_per_note(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(note_ids=[5, 6])
    created: list[dict[str, object]] = []

    monkeypatch.setattr(index_service, "purge_deleted_note_chunks", lambda s: 2)
    monkeypatch.setattr(
        task_service, "create_task", lambda session, **kwargs: created.append(kwargs)
    )

    result = index_service.start_rebuild(
        session, owner=SimpleNamespace(id=1), queue=SimpleNamespace()
    )

    assert session.commits == 1
    assert result.total_notes == 2
    assert result.purged_chunks == 2
    assert len(result.run_id) == 32
    assert [item["payload"] for item in created] == [
        {"note_id": 5, "run_id": result.run_id},
        {"note_id": 6, "run_id": result.run_id},
    ]
    assert all(item["name"] == index_service.TASK_INDEX_NOTE for item in created)


def test_start_rebuild_without_notes_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(note_ids=[])
    monkeypatch.setattr(
        index_service,
        "purge_deleted_note_chunks",
        lambda s: pytest.fail("空库不应该清理切片"),
    )

    with pytest.raises(InvalidParamError, match="没有可重建的笔记"):
        index_service.start_rebuild(
            session, owner=SimpleNamespace(id=1), queue=SimpleNamespace()
        )


def _task(
    status: str,
    *,
    note_id: int = 1,
    chunks: int | None = None,
    error: str | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
) -> AsyncTask:
    task = AsyncTask(
        user_id=1,
        name=index_service.TASK_INDEX_NOTE,
        status=status,
        payload={"note_id": note_id, "run_id": "a" * 32},
        result={"chunks": chunks} if chunks is not None else None,
        error=error,
    )
    task.started_at = started
    task.finished_at = finished
    return task


def test_get_rebuild_progress_aggregates_statuses() -> None:
    started = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    session = FakeSession(
        tasks=[
            _task(TaskStatus.SUCCEEDED.value, note_id=5, chunks=3, started=started),
            _task(TaskStatus.SUCCEEDED.value, note_id=6, chunks=2, started=started),
            _task(TaskStatus.FAILED.value, note_id=7, error="Embedding 失败"),
            _task(TaskStatus.PENDING.value, note_id=8),
        ]
    )

    progress = index_service.get_rebuild_progress(session, run_id="a" * 32)

    assert progress.total == 4
    assert progress.succeeded == 2
    assert progress.failed == 1
    assert progress.pending == 1
    assert progress.running == 0
    assert progress.percent == 75
    assert progress.chunks == 5
    assert progress.finished_at is None
    assert [item.note_id for item in progress.failures] == [7]
    assert progress.failures[0].error == "Embedding 失败"


def test_get_rebuild_progress_marks_finished_when_all_terminal() -> None:
    finished = datetime(2026, 10, 31, 12, 1, tzinfo=timezone.utc)
    session = FakeSession(
        tasks=[
            _task(TaskStatus.SUCCEEDED.value, chunks=3, finished=finished),
            _task(TaskStatus.FAILED.value, note_id=2, error="坏笔记"),
        ]
    )

    progress = index_service.get_rebuild_progress(session, run_id="a" * 32)

    assert progress.percent == 100
    assert progress.finished_at == finished


def test_get_rebuild_progress_unknown_run_raises() -> None:
    with pytest.raises(NotFoundError, match="索引重建记录不存在"):
        index_service.get_rebuild_progress(FakeSession(tasks=[]), run_id="b" * 32)