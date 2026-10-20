"""S1-4 检索器测试：RRF 纯函数 + fake session（spec §11）。"""
from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.embedding.errors import EmbeddingError
from app.ai.rerank import (
    RerankCandidate,
    RerankClient,
    RerankError,
    RerankResponse,
    RerankScore,
)
from app.ai.rag.retriever import (
    RetrievalFilterUnavailable,
    RetrievedChunk,
    rerank_fused,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
    rrf_fuse,
)
from app.models.note_chunk import NoteChunk


def _hit(chunk_id: int, *, distance: float | None = None, ts: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=1,
        chunk_index=chunk_id,
        content=f"合成块 {chunk_id}",
        vector_distance=distance,
        fulltext_score=ts,
    )


def test_rrf_fuse_dedupes_and_sums_overlap() -> None:
    vector_hits = [_hit(i) for i in range(1, 21)]          # 1..20
    fulltext_hits = [_hit(i, ts=1.0) for i in range(16, 36)]  # 16..35，5 条重叠
    fused = rrf_fuse(vector_hits, fulltext_hits)

    assert len(fused) == 35
    by_id = {hit.chunk_id: hit for hit in fused}
    assert by_id[16].vector_rank == 16
    assert by_id[16].fulltext_rank == 1
    assert by_id[16].rrf_score == pytest.approx(1 / 76 + 1 / 61)
    assert by_id[1].rrf_score == pytest.approx(1 / 61)
    assert by_id[35].rrf_score == pytest.approx(1 / 80)


def test_rrf_fuse_keeps_single_path_hits() -> None:
    fused = rrf_fuse([_hit(1), _hit(2)], [_hit(3), _hit(4)])
    assert [hit.chunk_id for hit in fused] == [1, 3, 2, 4]
    assert {hit.chunk_id for hit in fused} == {1, 2, 3, 4}


def test_rrf_fuse_uses_rank_not_raw_score() -> None:
    vector_hits = [_hit(1, distance=0.99), _hit(2, distance=0.01)]
    fulltext_hits = [_hit(3, ts=0.01), _hit(4, ts=0.99)]

    assert [hit.chunk_id for hit in rrf_fuse(vector_hits, [])] == [1, 2]
    assert [hit.chunk_id for hit in rrf_fuse([], fulltext_hits)] == [3, 4]


def test_rrf_fuse_tie_break_is_stable() -> None:
    # 两条都是单路第 1，RRF 同分；最优单路名次也相同，按 chunk_id 升序
    fused = rrf_fuse([_hit(5)], [_hit(3)])
    assert [hit.chunk_id for hit in fused] == [3, 5]


class FakeResult:
    def __init__(self, rows: list[tuple[NoteChunk, float]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[NoteChunk, float]]:
        return list(self._rows)


class FakeSession:
    def __init__(self, *results: FakeResult) -> None:
        self._results = list(results)
        self.statements: list[object] = []

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return self._results.pop(0)


class FakeClient:
    model = "fake-embed"
    dim = 1024

    def __init__(self, *, dim: int = 1024) -> None:
        self.dim = dim
        self.usage_tokens = 0
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], *, on_batch=None) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1] * self.dim for _ in texts]


def make_chunk(chunk_id: int, *, note_id: int = 1, index: int = 0, content: str = "函数的定义域") -> NoteChunk:
    return NoteChunk(
        id=chunk_id,
        note_id=note_id,
        user_id=1,
        chunk_index=index,
        content=content,
        token_count=10,
        chunk_type="note",
        heading_path="函数/定义域",
        page_no=1,
        embedding=[0.0] * 1024,
    )


def test_retrieve_hybrid_both_paths_hit() -> None:
    c1, c2, c3 = make_chunk(1), make_chunk(2), make_chunk(3)
    session = FakeSession(
        FakeResult([(c1, 0.1), (c2, 0.2)]),
        FakeResult([(c2, 0.9), (c3, 0.5)]),
    )
    client = FakeClient()

    result = retrieve_hybrid(session, "函数的定义域", user_id=1, client=client)

    assert [hit.chunk_id for hit in result.vector] == [1, 2]
    assert [hit.chunk_id for hit in result.fulltext] == [2, 3]
    assert result.fused[0].chunk_id == 2
    assert result.fused[0].vector_rank == 2
    assert result.fused[0].fulltext_rank == 1
    assert result.fused[0].rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert "|" in result.tsquery
    assert client.calls == [["函数的定义域"]]


def test_query_filters_use_user_id_and_limits() -> None:
    session = FakeSession(FakeResult([]), FakeResult([]))
    retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(), top_k=20)

    vector_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    fulltext_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    vector_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    fulltext_params = session.statements[1].compile(dialect=postgresql.dialect()).params

    assert "<=>" in vector_sql
    assert "@@" in fulltext_sql
    assert "ts_rank_cd" in fulltext_sql.lower()
    assert "LIMIT" in vector_sql.upper()
    assert "LIMIT" in fulltext_sql.upper()
    assert 1 in vector_params.values()
    assert 1 in fulltext_params.values()


def test_rejects_subject_and_kp_filters() -> None:
    client = FakeClient()
    with pytest.raises(RetrievalFilterUnavailable, match="S2-1"):
        retrieve_hybrid(FakeSession(), "函数的定义域", user_id=1, client=client, subject_id=3)
    with pytest.raises(RetrievalFilterUnavailable, match="S2-1"):
        retrieve_hybrid(FakeSession(), "函数的定义域", user_id=1, client=client, kp_ids=[1, 2])
    assert client.calls == []


def test_empty_query_returns_empty_without_embedding() -> None:
    session = FakeSession()
    client = FakeClient()
    result = retrieve_hybrid(session, "   ", user_id=1, client=client)
    assert result.vector == []
    assert result.fulltext == []
    assert result.fused == []
    assert result.elapsed_ms == 0
    assert session.statements == []
    assert client.calls == []


def test_skips_fulltext_when_no_tokens() -> None:
    session = FakeSession(FakeResult([(make_chunk(1), 0.1)]))
    result = retrieve_hybrid(session, "！！！？？？", user_id=1, client=FakeClient())
    assert len(session.statements) == 1
    assert result.fulltext == []
    assert result.tsquery == ""
    assert [hit.chunk_id for hit in result.fused] == [1]


def test_final_k_truncates_fused_only() -> None:
    session = FakeSession(
        FakeResult([(make_chunk(1), 0.1), (make_chunk(2), 0.2), (make_chunk(3), 0.3)]),
        FakeResult([(make_chunk(4), 0.9), (make_chunk(5), 0.8)]),
    )
    result = retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(), final_k=2)
    assert len(result.fused) == 2
    assert len(result.vector) == 3
    assert len(result.fulltext) == 2


def test_dimension_mismatch_raises_embedding_error() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError, match="维度"):
        retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(dim=8))
    assert session.statements == []


def test_invalid_top_k_raises_value_error() -> None:
    with pytest.raises(ValueError, match="top_k"):
        retrieve_hybrid(FakeSession(), "函数", user_id=1, client=FakeClient(), top_k=0)
    with pytest.raises(ValueError, match="final_k"):
        retrieve_hybrid(FakeSession(), "函数", user_id=1, client=FakeClient(), final_k=0)


class FakeRerankClient(RerankClient):
    model = "fake-rerank"

    def __init__(self, *, scores: dict[int, float] | None = None, error: Exception | None = None) -> None:
        self.scores = scores or {}
        self.error = error
        self.calls: list[tuple[str, list[int], int | None]] = []

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        self.calls.append((query, [candidate.id for candidate in candidates], top_n))
        if self.error is not None:
            raise self.error
        scored = [
            RerankScore(id=candidate.id, score=self.scores.get(candidate.id, 0.0))
            for candidate in candidates
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return RerankResponse(
            model=self.model,
            scores=scored[:top_n] if top_n is not None else scored,
            tokens=10,
            latency_ms=3,
            cost_yuan=0.000005,
        )


def test_rerank_fused_orders_by_score() -> None:
    fused = [_hit(1), _hit(2), _hit(3)]
    client = FakeRerankClient(scores={1: 0.2, 2: 0.9, 3: 0.5})

    reranked, info = rerank_fused("q", fused, candidates=3, top_k=2, client=client)

    assert [hit.chunk_id for hit in reranked] == [2, 3]
    assert reranked[0].rerank_score == 0.9
    assert info is not None
    assert info.model == "fake-rerank"
    assert info.candidates == 3
    assert info.top_k == 2
    assert info.fallback is False
    assert client.calls == [("q", [1, 2, 3], 2)]


def test_rerank_fused_falls_back_on_error() -> None:
    fused = [_hit(1), _hit(2), _hit(3)]
    client = FakeRerankClient(error=RerankError("模拟失败"))

    reranked, info = rerank_fused("q", fused, candidates=3, top_k=2, client=client)

    assert [hit.chunk_id for hit in reranked] == [1, 2]
    assert info is not None
    assert info.fallback is True
    assert "模拟失败" in (info.error or "")
    assert info.tokens == 0


def test_rerank_fused_caps_candidates_at_30() -> None:
    fused = [_hit(i) for i in range(1, 41)]
    client = FakeRerankClient(scores={i: 0.1 for i in range(1, 41)})

    _, info = rerank_fused("q", fused, candidates=30, top_k=6, client=client)

    assert len(client.calls[0][1]) == 30
    assert info is not None
    assert info.candidates == 30


def test_rerank_fused_empty_returns_none() -> None:
    client = FakeRerankClient()
    reranked, info = rerank_fused("q", [], candidates=30, top_k=6, client=client)
    assert reranked == []
    assert info is None
    assert client.calls == []


def test_retrieve_hybrid_reranked_integrates_and_times() -> None:
    c1, c2, c3 = make_chunk(1), make_chunk(2), make_chunk(3)
    session = FakeSession(
        FakeResult([(c1, 0.1), (c2, 0.2), (c3, 0.3)]),
        FakeResult([(c2, 0.9), (c3, 0.5)]),
    )
    rerank_client = FakeRerankClient(scores={1: 0.2, 2: 0.9, 3: 0.5})

    result = retrieve_hybrid_reranked(
        session,
        "函数的定义域",
        user_id=1,
        client=FakeClient(),
        rerank_client=rerank_client,
        rerank_candidates=3,
        rerank_top_k=2,
    )

    assert [hit.chunk_id for hit in result.fused] == [2, 3, 1]
    assert [hit.chunk_id for hit in result.reranked] == [2, 3]
    assert result.rerank_info is not None
    assert result.rerank_info.fallback is False
    assert result.vector_ms >= 0
    assert result.fulltext_ms >= 0
    assert result.reranked[0].rerank_score == 0.9
    assert len(result.fused) == 3


def test_retrieve_hybrid_reranked_fallback_keeps_rrf_order() -> None:
    chunks = [make_chunk(i) for i in range(1, 8)]
    session = FakeSession(
        FakeResult([(chunk, 0.1 * index) for index, chunk in enumerate(chunks, start=1)]),
        FakeResult([]),
    )
    rerank_client = FakeRerankClient(error=RerankError("模拟失败"))

    result = retrieve_hybrid_reranked(
        session,
        "函数",
        user_id=1,
        client=FakeClient(),
        rerank_client=rerank_client,
    )

    assert [hit.chunk_id for hit in result.reranked] == [hit.chunk_id for hit in result.fused[:6]]
    assert result.rerank_info is not None
    assert result.rerank_info.fallback is True


def test_retrieve_hybrid_reranked_empty_query_skips_all() -> None:
    session = FakeSession()
    embed_client = FakeClient()
    rerank_client = FakeRerankClient()

    result = retrieve_hybrid_reranked(
        session,
        "   ",
        user_id=1,
        client=embed_client,
        rerank_client=rerank_client,
    )

    assert result.reranked == []
    assert result.rerank_info is None
    assert session.statements == []
    assert embed_client.calls == []
    assert rerank_client.calls == []


def test_retrieve_hybrid_reranked_invalid_params() -> None:
    with pytest.raises(ValueError, match="rerank_candidates"):
        retrieve_hybrid_reranked(
            FakeSession(), "函数", user_id=1, client=FakeClient(),
            rerank_client=FakeRerankClient(), rerank_candidates=0,
        )
    with pytest.raises(ValueError, match="rerank_top_k"):
        retrieve_hybrid_reranked(
            FakeSession(), "函数", user_id=1, client=FakeClient(),
            rerank_client=FakeRerankClient(), rerank_top_k=0,
        )


def test_rerank_fused_propagates_non_rerank_error() -> None:
    client = FakeRerankClient(error=ValueError("boom"))
    with pytest.raises(ValueError, match="boom"):
        rerank_fused("q", [_hit(1)], candidates=3, top_k=2, client=client)


def test_rerank_fused_factory_error_falls_back(monkeypatch) -> None:
    def no_key_client():
        raise RerankError("no key")

    monkeypatch.setattr("app.ai.rag.retriever.get_rerank_client", no_key_client)
    reranked, info = rerank_fused("q", [_hit(1), _hit(2)], candidates=3, top_k=2)

    assert [hit.chunk_id for hit in reranked] == [1, 2]
    assert info is not None
    assert info.fallback is True
    assert info.model == "unavailable"
