"""S6-1/S6-3 list_notes：日期窗口、标签过滤、元数据与知识点/预览增量。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import list_notes as tool
from app.ai.agents.tools.base import ToolContext
from app.schemas.common import PageData
from app.schemas.notes import NoteSummary


class _Rows:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = rows

    def all(self):  # noqa: ANN201
        return self._rows


class _Session:
    def __init__(self, *, previews=(), kps=()):  # noqa: ANN001
        self.previews = list(previews)
        self.kps = list(kps)
        self.calls = 0

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.calls += 1
        return _Rows(self.previews if self.calls == 1 else self.kps)


def _ctx(session=None) -> ToolContext:  # noqa: ANN001
    return ToolContext(session=session or _Session(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


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


def test_list_notes_adds_preview_and_knowledge_points(monkeypatch):
    monkeypatch.setattr(
        tool,
        "list_notes_service",
        lambda *a, **k: PageData(items=[_note(1)], total=1, page=1, page_size=20),
    )
    session = _Session(
        previews=[(1, "函数内容" * 100)],
        kps=[(1, 137, "函数的单调性"), (1, 138, "函数的极值")],
    )
    out = tool.list_notes(_ctx(session), tool.ListNotesIn())
    assert out.items[0].preview == ("函数内容" * 100)[:200]
    assert out.items[0].kp_ids == [137, 138]
    assert out.items[0].kp_names == ["函数的单调性", "函数的极值"]


def test_list_notes_skips_extra_queries_when_empty(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        tool,
        "list_notes_service",
        lambda *a, **k: PageData(items=[], total=0, page=1, page_size=20),
    )
    tool.list_notes(_ctx(session), tool.ListNotesIn())
    assert session.calls == 0