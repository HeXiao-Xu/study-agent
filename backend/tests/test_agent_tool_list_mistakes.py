"""S6-1 list_mistakes：过滤条件透传与摘要映射。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import list_mistakes as tool
from app.ai.agents.tools.base import ToolContext
from app.schemas.common import PageData
from app.schemas.mistake import MistakeSummaryOut


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def _mistake(mistake_id: int) -> MistakeSummaryOut:
    return MistakeSummaryOut(
        id=mistake_id,
        question_id=100 + mistake_id,
        status="待订正",
        correct_streak=0,
        stem_excerpt="题干摘要",
        subject_id=7,
        qtype="解答",
        difficulty=3,
        kp_names=["函数"],
        cause_type="概念不清",
        created_at=datetime(2026, 11, 15, 8, tzinfo=timezone.utc),
        last_review_at=None,
    )


def test_list_mistakes_passes_filters_and_maps(monkeypatch):
    captured = {}

    def fake_list(session, *, user_id, filters, page, sort):  # noqa: ANN001
        captured.update(user_id=user_id, filters=filters, page=page, sort=sort)
        return PageData(items=[_mistake(1)], total=1, page=1, page_size=page.page_size)

    monkeypatch.setattr(tool, "list_mistakes_service", fake_list)
    out = tool.list_mistakes(
        _ctx(),
        tool.ListMistakesIn(
            kp_ids=[101, 102],
            status="待订正",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 16),
            limit=7,
        ),
    )
    assert captured["user_id"] == 50
    assert captured["filters"].kp_ids == [101, 102]
    assert captured["filters"].status == "待订正"
    assert captured["filters"].created_to.date() == date(2026, 11, 16)
    assert captured["page"].page_size == 7
    assert out.items[0].mistake_id == 1
    assert out.items[0].question_id == 101
    assert out.items[0].cause_type == "概念不清"


def test_list_mistakes_empty(monkeypatch):
    monkeypatch.setattr(
        tool,
        "list_mistakes_service",
        lambda *a, **k: PageData(items=[], total=0, page=1, page_size=20),
    )
    out = tool.list_mistakes(_ctx(), tool.ListMistakesIn())
    assert out.total == 0 and out.items == []