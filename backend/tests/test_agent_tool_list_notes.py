"""S6-1 list_notes：日期窗口、标签过滤与元数据映射。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import list_notes as tool
from app.ai.agents.tools.base import ToolContext
from app.schemas.common import PageData
from app.schemas.notes import NoteSummary


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def _note(note_id: int, tags: list[str] | None = None) -> NoteSummary:
    return NoteSummary(
        id=note_id,
        title=f"笔记{note_id}",
        subject_id=7,
        tags=tags,
        folder=None,
        created_at=datetime(2026, 11, 15, 8, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 15, 8, tzinfo=timezone.utc),
    )


def test_list_notes_passes_date_window_and_end_is_inclusive(monkeypatch):
    captured = {}

    def fake_list(session, *, owner, params, sorting, **kwargs):  # noqa: ANN001
        captured.update(owner_id=owner.id, page_size=params.page_size, **kwargs)
        return PageData(items=[_note(1)], total=1, page=1, page_size=params.page_size)

    monkeypatch.setattr(tool, "list_notes_service", fake_list)
    out = tool.list_notes(
        _ctx(),
        tool.ListNotesIn(
            start_date=date(2026, 11, 10), end_date=date(2026, 11, 16), limit=5
        ),
    )
    assert captured["created_from"] == datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert captured["created_to"].date() == date(2026, 11, 16)
    assert captured["created_to"].hour == 23
    assert captured["page_size"] == 5
    assert out.items[0].note_id == 1


def test_list_notes_filters_extra_tags_in_memory(monkeypatch):
    def fake_list(session, *, owner, params, sorting, **kwargs):  # noqa: ANN001
        return PageData(
            items=[_note(1, ["函数"]), _note(2, ["函数", "复习"])],
            total=2,
            page=1,
            page_size=params.page_size,
        )

    monkeypatch.setattr(tool, "list_notes_service", fake_list)
    out = tool.list_notes(_ctx(), tool.ListNotesIn(tags=["函数", "复习"]))
    assert [item.note_id for item in out.items] == [2]
    assert out.total == 2
    assert out.filtered_total == 1


def test_list_notes_without_dates_passes_none(monkeypatch):
    captured = {}

    def fake_list(session, *, owner, params, sorting, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return PageData(items=[], total=0, page=1, page_size=params.page_size)

    monkeypatch.setattr(tool, "list_notes_service", fake_list)
    out = tool.list_notes(_ctx(), tool.ListNotesIn())
    assert captured["created_from"] is None
    assert captured["created_to"] is None
    assert out.items == []