"""S2-10 对齐任务 handler：不连库、不调 LLM。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.note import Note
from app.services.kp_align_service import AlignStats
from app.tasks import kp_align as task_module


class FakeSession:
    def __init__(self, note: Note | None) -> None:
        self.note = note

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        raise AssertionError(entity)


def _note(*, deleted: bool = False) -> Note:
    note = Note(
        user_id=1,
        subject_id=1,
        title="单调性",
        content_md="内容",
        content_text="内容",
        tags=None,
        folder=None,
    )
    note.id = 7
    note.deleted_at = datetime.now(timezone.utc) if deleted else None
    return note


def test_kp_align_task_returns_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        task_module, "align_note", lambda session, *, note: AlignStats(3, 2, 1, 1, 1)
    )
    result = task_module.kp_align_task(FakeSession(_note()), {"note_id": 7})  # type: ignore[arg-type]
    assert result == {
        "note_id": 7,
        "candidates": 3,
        "matched": 2,
        "auto": 1,
        "pending": 1,
        "dropped": 1,
    }


def test_kp_align_task_skips_missing_note() -> None:
    assert task_module.kp_align_task(FakeSession(None), {"note_id": 7}) == {  # type: ignore[arg-type]
        "note_id": 7,
        "skipped": True,
    }


def test_kp_align_task_skips_deleted_note() -> None:
    result = task_module.kp_align_task(FakeSession(_note(deleted=True)), {"note_id": 7})  # type: ignore[arg-type]
    assert result["skipped"] is True


def test_kp_align_task_rejects_missing_note_id() -> None:
    with pytest.raises(ValueError, match="note_id"):
        task_module.kp_align_task(FakeSession(None), {})  # type: ignore[arg-type]