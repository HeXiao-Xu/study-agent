"""S3-2 检索服务测试（spec §5）：fake retriever/session，不触库、不调外部 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.rag.retriever import RerankInfo, RetrievalResult, RetrievedChunk
from app.core.exceptions import InvalidParamError
from app.schemas.retrieval import RetrievalScopeIn
from app.services import retrieval_service


class FakeResult:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[int, str]]:
        return list(self._rows)


class FakeSession:
    def __init__(self, rows: list[tuple[int, str]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[object] = []

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)


def _chunk(chunk_id: int, *, note_id: int = 1, rrf: float = 0.1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=note_id,
        source_file_id=None,
        chunk_index=chunk_id,
        content=f"  函数的定义域  第 {chunk_id} 块  ",
        heading_path="函数/定义域",
        page_no=1,
        chunk_type="note",
        vector_rank=chunk_id,
        vector_distance=0.1,
        rrf_score=rrf,
    )


def _result(
    *, fused: list[RetrievedChunk] | None = None, reranked: list[RetrievedChunk] | None = None
) -> RetrievalResult:
    hits = fused or []
    return RetrievalResult(
        query="函数的定义域",
        tsquery="函数 | 定义域",
        vector=hits,
        fulltext=hits,
        fused=hits,
        reranked=reranked or [],
        elapsed_ms=12,
        embedding_ms=9,
        vector_ms=2,
        fulltext_ms=1,
        rerank_info=RerankInfo(
            model="fake-rerank",
            candidates=2,
            top_k=2,
            tokens=10,
            latency_ms=3,
            cost_yuan=0.0,
        ),
    )


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    values = {
        "retrieval_top_k": 6,
        "retrieval_recall_k": 20,
        "retrieval_rerank_enabled": True,
    }
    values.update(overrides)
    monkeypatch.setattr(retrieval_service, "get_settings", lambda: SimpleNamespace(**values))


def test_search_rejects_blank_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    with pytest.raises(InvalidParamError, match="query"):
        retrieval_service.search_chunks(FakeSession(), user_id=1, query="   ")


def test_search_rejects_top_k_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    for value in (0, 21):
        with pytest.raises(InvalidParamError, match="top_k"):
            retrieval_service.search_chunks(FakeSession(), user_id=1, query="函数", top_k=value)


def test_search_empty_knowledge_base_returns_empty_without_title_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    session = FakeSession()
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _result(fused=[]))
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid_reranked", lambda *a, **k: _result())

    response = retrieval_service.search_chunks(FakeSession(), user_id=1, query="函数", rerank=False)

    assert response.hits == []
    assert response.debug is None
    assert session.statements == []


def test_search_rerank_false_uses_fused_and_skips_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    fused = [_chunk(1), _chunk(2)]
    captured: dict[str, object] = {}

    def fake_hybrid(session, query, **kwargs):
        captured.update(kwargs)
        return _result(fused=fused)

    def fake_reranked(*args, **kwargs):
        raise AssertionError("rerank=false 不应调用 retrieve_hybrid_reranked")

    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", fake_hybrid)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid_reranked", fake_reranked)

    response = retrieval_service.search_chunks(FakeSession(), user_id=1, query="函数", rerank=False)

    assert [hit.chunk_id for hit in response.hits] == [1, 2]
    assert response.rerank is False
    assert response.rerank_info is None
    assert response.embedding_ms == 9
    assert captured["top_k"] == 20
    assert captured["final_k"] == 6
    assert captured["user_id"] == 1


def test_search_rerank_true_uses_reranked(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _result(fused=[_chunk(1)], reranked=[_chunk(2)]),
    )
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应走无重排路径")),
    )

    response = retrieval_service.search_chunks(FakeSession(), user_id=1, query="函数")

    assert [hit.chunk_id for hit in response.hits] == [2]
    assert response.rerank is True
    assert response.rerank_info is not None
    assert response.rerank_info.fallback is False


def test_search_loads_titles_in_one_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    session = FakeSession([(1, "函数笔记"), (2, "数列笔记")])
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=[_chunk(1, note_id=1), _chunk(2, note_id=2)]),
    )

    response = retrieval_service.search_chunks(session, user_id=1, query="函数", rerank=False)

    assert len(session.statements) == 1
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "IN" in sql.upper()
    assert "notes.user_id" in sql
    assert [hit.note_title for hit in response.hits] == ["函数笔记", "数列笔记"]


def test_search_missing_title_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=[_chunk(1, note_id=1)]),
    )

    response = retrieval_service.search_chunks(FakeSession([]), user_id=1, query="函数", rerank=False)

    assert response.hits[0].note_title is None


def test_search_debug_only_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    hits = [_chunk(1), _chunk(2)]
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _result(fused=hits))

    plain = retrieval_service.search_chunks(FakeSession([]), user_id=1, query="函数", rerank=False)
    debug = retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="函数", rerank=False, debug=True
    )

    assert plain.debug is None
    assert debug.debug is not None
    assert debug.debug.tsquery == "函数 | 定义域"
    assert len(debug.debug.vector) == 2
    assert len(debug.debug.fused) == 2


def test_search_converts_scope_and_trims_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    captured: dict[str, object] = {}

    def fake_hybrid(session, query, **kwargs):
        captured["query"] = query
        captured["scope"] = kwargs.get("scope")
        return _result()

    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", fake_hybrid)
    scope = RetrievalScopeIn(subject_id=7, folder=" 函数 ", chunk_types=["note"])

    retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="  函数的定义域  ", rerank=False, scope=scope
    )

    assert captured["query"] == "函数的定义域"
    assert captured["scope"].subject_id == 7
    assert captured["scope"].folder == "函数"
    assert captured["scope"].chunk_types == ["note"]


def test_search_snippet_collapses_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _result(fused=[_chunk(1)]))

    response = retrieval_service.search_chunks(FakeSession([]), user_id=1, query="函数", rerank=False)

    assert response.hits[0].snippet == "函数的定义域 第 1 块"
    assert response.hits[0].content.strip().startswith("函数的定义域")


def _mode_result() -> RetrievalResult:
    return RetrievalResult(
        query="函数",
        tsquery="函数",
        vector=[_chunk(1), _chunk(2), _chunk(3)],
        fulltext=[_chunk(2)],
        fused=[_chunk(2), _chunk(3)],
        reranked=[_chunk(4)],
        elapsed_ms=10,
        embedding_ms=8,
        vector_ms=1,
        fulltext_ms=1,
        rerank_info=RerankInfo(
            model="fake-rerank",
            candidates=2,
            top_k=1,
            tokens=4,
            latency_ms=5,
            cost_yuan=0.0,
        ),
    )


def test_search_vector_returns_vector_list_without_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _mode_result())
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: pytest.fail("vector 不应调用 rerank"),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=2, retrieval="vector"
    )

    assert [hit.chunk_id for hit in response.hits] == [1, 2]
    assert response.rerank is False
    assert response.rerank_info is None


def test_search_hybrid_returns_fused_list_without_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _mode_result())
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: pytest.fail("hybrid 不应调用 rerank"),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=2, retrieval="hybrid"
    )

    assert [hit.chunk_id for hit in response.hits] == [2, 3]
    assert response.rerank is False


def test_search_hybrid_rerank_returns_reranked_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _mode_result(),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=1, retrieval="hybrid_rerank"
    )

    assert [hit.chunk_id for hit in response.hits] == [4]
    assert response.rerank is True
    assert response.rerank_info is not None


def test_search_rejects_invalid_retrieval_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    with pytest.raises(InvalidParamError, match="retrieval"):
        retrieval_service.search_chunks(
            FakeSession(), user_id=1, query="函数", retrieval="magic"
        )