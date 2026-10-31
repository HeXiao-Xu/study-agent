"""S3-1 index.note 任务测试：不触库、不调 Embedding。"""
from __future__ import annotations

import pytest

from app.services.index_service import NoteIndexResult
from app.tasks import index_note as index_note_task_module
from app.tasks.index_note import TASK_INDEX_NOTE, index_note_task
from app.tasks.registry import get_handler


def test_task_is_registered() -> None:
    assert get_handler(TASK_INDEX_NOTE) is index_note_task


def test_index_note_task_returns_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_index_note(session, *, note_id):
        captured["note_id"] = note_id
        return NoteIndexResult(
            note_id=note_id,
            chunk_count=3,
            total_tokens=42,
            elapsed_ms=17,
            cost_cny=0.0001,
        )

    monkeypatch.setattr(index_note_task_module, "index_note", fake_index_note)

    result = index_note_task(object(), {"note_id": 9, "run_id": "a" * 32})

    assert captured["note_id"] == 9
    assert result == {
        "note_id": 9,
        "chunks": 3,
        "tokens": 42,
        "elapsed_ms": 17,
        "cost_cny": 0.0001,
        "skipped": False,
        "reason": None,
    }


def test_index_note_task_passes_skipped_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        index_note_task_module,
        "index_note",
        lambda session, *, note_id: NoteIndexResult(
            note_id=note_id,
            chunk_count=0,
            total_tokens=0,
            elapsed_ms=0,
            cost_cny=0.0,
            skipped=True,
            reason="note_deleted",
        ),
    )

    result = index_note_task(object(), {"note_id": 9})

    assert result["skipped"] is True
    assert result["reason"] == "note_deleted"


def test_index_note_task_rejects_missing_note_id() -> None:
    with pytest.raises(ValueError, match="note_id"):
        index_note_task(object(), {})