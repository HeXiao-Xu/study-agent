"""S6-1 search_notes：检索服务薄封装与正文截断。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai.agents.tools import search_notes as tool
from app.ai.agents.tools.base import ToolContext
from app.schemas.retrieval import RetrievalHit, RetrievalSearchResponse


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def _hit() -> RetrievalHit:
    return RetrievalHit(
        chunk_id=1,
        note_id=2,
        note_title="函数笔记",
        chunk_index=0,
        chunk_type="note",
        content="长" * 1500,
        snippet="长…",
        rrf_score=0.9,
    )


def test_search_notes_maps_hits_and_truncates(monkeypatch):
    captured = {}

    def fake_search(session, *, user_id, query, top_k, retrieval, scope, debug):  # noqa: ANN001
        captured.update(
            user_id=user_id, query=query, top_k=top_k, retrieval=retrieval, debug=debug
        )
        return RetrievalSearchResponse(
            query=query,
            top_k=top_k,
            rerank=False,
            elapsed_ms=12,
            embedding_ms=8,
            hits=[_hit()],
        )

    monkeypatch.setattr(tool, "search_chunks", fake_search)
    out = tool.search_notes(_ctx(), tool.SearchNotesIn(query="函数", top_k=3))
    assert captured["user_id"] == 50 and captured["debug"] is False
    assert captured["top_k"] == 3
    assert out.hit_count == 1
    assert out.hits[0].truncated is True
    assert len(out.hits[0].content) == 1200
    assert out.hits[0].note_title == "函数笔记"


def test_search_notes_passes_scope(monkeypatch):
    captured = {}

    def fake_search(session, *, user_id, query, top_k, retrieval, scope, debug):  # noqa: ANN001
        captured["scope"] = scope
        return RetrievalSearchResponse(
            query=query, top_k=top_k, rerank=False, elapsed_ms=1, embedding_ms=1, hits=[]
        )

    monkeypatch.setattr(tool, "search_chunks", fake_search)
    tool.search_notes(
        _ctx(),
        tool.SearchNotesIn(query="函数", subject_id=7, folder="函数", chunk_types=["note"]),
    )
    assert captured["scope"].subject_id == 7
    assert captured["scope"].folder == "函数"
    assert captured["scope"].chunk_types == ["note"]


def test_search_notes_rejects_empty_query_and_bad_range():
    with pytest.raises(ValidationError):
        tool.SearchNotesIn(query="")
    with pytest.raises(ValidationError):
        tool.SearchNotesIn(query="函数", start_date="2026-11-10", end_date="2026-11-01")