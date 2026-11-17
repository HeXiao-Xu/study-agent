"""S6-1 search_questions：过滤透传、答案不外泄、页内稳定排序。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai.agents.tools import search_questions as tool
from app.ai.agents.tools.base import ToolContext
from app.schemas.common import PageData
from app.schemas.question import QuestionSummaryOut

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = rows

    def all(self):  # noqa: ANN201
        return self._rows


class _Session:
    def __init__(self, rows):  # noqa: ANN001
        self.rows = rows
        self.statements = []

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return _Rows(self.rows)


def _ctx(rows) -> ToolContext:  # noqa: ANN001
    return ToolContext(session=_Session(rows), user=SimpleNamespace(id=50), now=NOW)  # type: ignore[arg-type]


def _question(question_id: int, *, verified: bool) -> QuestionSummaryOut:
    return QuestionSummaryOut(
        id=question_id,
        subject_id=7,
        qtype="解答",
        difficulty=3,
        origin="manual",
        verified=verified,
        stem_md="题" * 2500,
        created_at=NOW,
        kp_names=["函数"],
    )


def test_search_questions_passes_filters_and_sorts_verified_first(monkeypatch):
    captured = {}

    def fake_list(session, *, filters, page, sort):  # noqa: ANN001
        captured.update(filters=filters, page=page, sort=sort)
        return PageData(
            items=[_question(1, verified=False), _question(2, verified=True)],
            total=2,
            page=1,
            page_size=page.page_size,
        )

    monkeypatch.setattr(tool, "list_questions_service", fake_list)
    out = tool.search_questions(
        _ctx([(1, None), (2, [{"key": "A", "text": "选项甲"}])]),
        tool.SearchQuestionsIn(
            kp_ids=[101], qtype="解答", difficulty=3, exclude_recent_days=14, limit=5
        ),
    )
    assert captured["filters"].kp_ids == [101]
    assert captured["filters"].difficulty == 3
    assert captured["filters"].exclude_user_id == 50
    assert captured["filters"].exclude_done_since == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert [item.question_id for item in out.items] == [2, 1]
    assert out.items[0].truncated is True
    assert len(out.items[0].stem_md) == 2000
    assert out.items[1].options is None
    assert out.items[0].options[0].key == "A"
    assert "answer_md" not in out.items[0].model_dump()


def test_search_questions_zero_days_disables_recent_exclusion(monkeypatch):
    captured = {}

    def fake_list(session, *, filters, page, sort):  # noqa: ANN001
        captured["filters"] = filters
        return PageData(items=[], total=0, page=1, page_size=page.page_size)

    monkeypatch.setattr(tool, "list_questions_service", fake_list)
    tool.search_questions(_ctx([]), tool.SearchQuestionsIn(exclude_recent_days=0))
    assert captured["filters"].exclude_user_id is None
    assert captured["filters"].exclude_done_since is None