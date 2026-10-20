"""S1-4 混合检索：向量 + jieba 全文 + RRF 融合（spec docs/spec/s1-4-retrieval.md）。

RRF 只用排名，不归一化 distance / ts_rank；公式 score = Σ 1/(60 + rank_i)。
"""
from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.ai.embedding.errors import EmbeddingError
from app.ai.rerank import (
    RerankCandidate,
    RerankClient,
    RerankError,
    get_rerank_client,
)
from app.core.config import get_settings
from app.models.note_chunk import NoteChunk
from app.utils.zh_tokenizer import build_tsquery_or

logger = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_TOP_K = 20
DEFAULT_RERANK_CANDIDATES = 30
DEFAULT_RERANK_TOP_K = 6


class RetrievalFilterUnavailable(ValueError):
    """S1-4 只能下推 user_id；subject/kp 依赖 S2-1 的 notes/note_kps。"""


class RetrievedChunk(BaseModel):
    chunk_id: int
    note_id: int
    chunk_index: int
    content: str
    heading_path: str | None = None
    page_no: int | None = None
    chunk_type: str | None = None
    vector_rank: int | None = None
    vector_distance: float | None = None
    fulltext_rank: int | None = None
    fulltext_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


class RerankInfo(BaseModel):
    model: str
    candidates: int
    top_k: int
    tokens: int
    latency_ms: int
    cost_yuan: float
    fallback: bool = False
    error: str | None = None


class RetrievalResult(BaseModel):
    query: str
    tsquery: str
    vector: list[RetrievedChunk]
    fulltext: list[RetrievedChunk]
    fused: list[RetrievedChunk]
    elapsed_ms: int
    vector_ms: int = 0
    fulltext_ms: int = 0
    reranked: list[RetrievedChunk] = Field(default_factory=list)
    rerank_info: RerankInfo | None = None


def rrf_fuse(
    vector_hits: list[RetrievedChunk],
    fulltext_hits: list[RetrievedChunk],
    *,
    k: int = RRF_K,
    final_k: int | None = None,
) -> list[RetrievedChunk]:
    """按 chunk_id 去重并融合两路排名；只认排名，不认原始分数。"""
    if k <= 0:
        raise ValueError("k 必须为正整数")
    if final_k is not None and final_k <= 0:
        raise ValueError("final_k 必须为正整数")

    merged: dict[int, RetrievedChunk] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        item = hit.model_copy(deep=True)
        item.vector_rank = rank
        item.rrf_score = 1.0 / (k + rank)
        merged[item.chunk_id] = item

    for rank, hit in enumerate(fulltext_hits, start=1):
        item = merged.get(hit.chunk_id)
        if item is None:
            item = hit.model_copy(deep=True)
            item.rrf_score = 0.0
            merged[item.chunk_id] = item
        item.fulltext_rank = rank
        item.fulltext_score = hit.fulltext_score
        item.rrf_score += 1.0 / (k + rank)

    def best_rank(item: RetrievedChunk) -> int:
        ranks = [r for r in (item.vector_rank, item.fulltext_rank) if r is not None]
        return min(ranks) if ranks else 10**9

    fused = sorted(
        merged.values(),
        key=lambda item: (-item.rrf_score, best_rank(item), item.chunk_id),
    )
    return fused[:final_k] if final_k is not None else fused


def _to_chunk(
    chunk: NoteChunk,
    *,
    vector_rank: int | None = None,
    vector_distance: float | None = None,
    fulltext_rank: int | None = None,
    fulltext_score: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        note_id=chunk.note_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        heading_path=chunk.heading_path,
        page_no=chunk.page_no,
        chunk_type=chunk.chunk_type,
        vector_rank=vector_rank,
        vector_distance=vector_distance,
        fulltext_rank=fulltext_rank,
        fulltext_score=fulltext_score,
    )


def _vector_search(
    session: Session,
    query_vector: list[float],
    *,
    user_id: int,
    top_k: int,
) -> list[RetrievedChunk]:
    distance = NoteChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(NoteChunk, distance)
        .where(NoteChunk.user_id == user_id)
        .order_by(distance.asc(), NoteChunk.id.asc())
        .limit(top_k)
    )
    rows = session.execute(stmt).all()
    return [
        _to_chunk(row[0], vector_rank=rank, vector_distance=float(row[1]))
        for rank, row in enumerate(rows, start=1)
    ]


def _fulltext_search(
    session: Session,
    tsquery_str: str,
    *,
    user_id: int,
    top_k: int,
) -> list[RetrievedChunk]:
    tsquery = func.to_tsquery("simple", tsquery_str)
    score = func.ts_rank_cd(NoteChunk.tsv, tsquery).label("fulltext_score")
    stmt = (
        select(NoteChunk, score)
        .where(NoteChunk.user_id == user_id, NoteChunk.tsv.op("@@")(tsquery))
        .order_by(score.desc(), NoteChunk.id.asc())
        .limit(top_k)
    )
    rows = session.execute(stmt).all()
    return [
        _to_chunk(row[0], fulltext_rank=rank, fulltext_score=float(row[1]))
        for rank, row in enumerate(rows, start=1)
    ]


def retrieve_hybrid(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    final_k: int | None = None,
    client: EmbeddingClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult:
    """两路检索 + RRF；user_id 必填，subject/kp 在 S2-1 前不可用。"""
    if subject_id is not None or kp_ids:
        raise RetrievalFilterUnavailable(
            "S1-4 仅支持 user_id 过滤；subject_id/kp_ids 需要 S2-1 的 notes/note_kps 表"
        )
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")
    if final_k is not None and final_k <= 0:
        raise ValueError("final_k 必须为正整数")

    query = query.strip()
    if not query:
        return RetrievalResult(
            query="",
            tsquery="",
            vector=[],
            fulltext=[],
            fused=[],
            elapsed_ms=0,
        )

    started = time.perf_counter()
    settings = get_settings()
    embedding_client = client or get_embedding_client()
    query_vector = embedding_client.encode([query])[0]
    if len(query_vector) != settings.embedding_dim:
        raise EmbeddingError(
            f"查询向量维度不符：期望 {settings.embedding_dim}，实际 {len(query_vector)}",
            retryable=False,
        )

    vector_started = time.perf_counter()
    vector_hits = _vector_search(session, query_vector, user_id=user_id, top_k=top_k)
    vector_ms = int((time.perf_counter() - vector_started) * 1000)

    tsquery_str = build_tsquery_or(query)
    fulltext_started = time.perf_counter()
    fulltext_hits = (
        _fulltext_search(session, tsquery_str, user_id=user_id, top_k=top_k)
        if tsquery_str
        else []
    )
    fulltext_ms = int((time.perf_counter() - fulltext_started) * 1000)
    fused = rrf_fuse(vector_hits, fulltext_hits, final_k=final_k)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    logger.info(
        "retrieval_done",
        extra={
            "scene": "retrieve",
            "user_id": user_id,
            "top_k": top_k,
            "vector_hits": len(vector_hits),
            "fulltext_hits": len(fulltext_hits),
            "fused_hits": len(fused),
            "tsquery": tsquery_str,
            "latency_ms": elapsed_ms,
            "vector_ms": vector_ms,
            "fulltext_ms": fulltext_ms,
        },
    )
    return RetrievalResult(
        query=query,
        tsquery=tsquery_str,
        vector=vector_hits,
        fulltext=fulltext_hits,
        fused=fused,
        elapsed_ms=elapsed_ms,
        vector_ms=vector_ms,
        fulltext_ms=fulltext_ms,
    )


def rerank_fused(
    query: str,
    fused: list[RetrievedChunk],
    *,
    candidates: int = DEFAULT_RERANK_CANDIDATES,
    top_k: int = DEFAULT_RERANK_TOP_K,
    client: RerankClient | None = None,
) -> tuple[list[RetrievedChunk], RerankInfo | None]:
    """取 fused[:candidates] 重排；失败回退 fused[:top_k]，不抛给调用方。"""
    if candidates <= 0:
        raise ValueError("candidates 必须为正整数")
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")
    if not fused:
        return [], None

    selected = fused[: min(candidates, len(fused))]
    started = time.perf_counter()
    rerank_client: RerankClient | None = None
    try:
        rerank_client = client or get_rerank_client()
        response = rerank_client.rerank(
            query,
            [RerankCandidate(id=hit.chunk_id, content=hit.content) for hit in selected],
            top_n=min(top_k, len(selected)),
        )
        if not response.scores:
            raise RerankError("Rerank 返回空分数", provider=rerank_client.model)
        score_by_id = {item.id: item.score for item in response.scores}
        original_order = {hit.chunk_id: index for index, hit in enumerate(selected)}
        scored = [
            hit.model_copy(update={"rerank_score": score_by_id[hit.chunk_id]})
            for hit in selected
            if hit.chunk_id in score_by_id
        ]
        if not scored:
            raise RerankError("Rerank 分数与候选完全对不上", provider=rerank_client.model)
        scored.sort(
            key=lambda hit: (-score_by_id[hit.chunk_id], original_order[hit.chunk_id])
        )
        return scored[:top_k], RerankInfo(
            model=response.model,
            candidates=len(selected),
            top_k=top_k,
            tokens=response.tokens,
            latency_ms=response.latency_ms,
            cost_yuan=response.cost_yuan,
            fallback=False,
        )
    except RerankError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        model = rerank_client.model if rerank_client is not None else "unavailable"
        logger.warning(
            "rerank_fallback",
            extra={
                "scene": "rerank",
                "model": model,
                "candidates": len(selected),
                "top_k": top_k,
                "error": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return fused[:top_k], RerankInfo(
            model=model,
            candidates=len(selected),
            top_k=top_k,
            tokens=0,
            latency_ms=latency_ms,
            cost_yuan=0.0,
            fallback=True,
            error=str(exc),
        )


def retrieve_hybrid_reranked(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    rerank_candidates: int | None = None,
    rerank_top_k: int | None = None,
    client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult:
    """S1-4 混合检索 → top30 → rerank → top6；rerank 失败只回退。"""
    settings = get_settings()
    candidates = settings.rerank_candidates if rerank_candidates is None else rerank_candidates
    final_top_k = settings.rerank_top_k if rerank_top_k is None else rerank_top_k
    if candidates <= 0:
        raise ValueError("rerank_candidates 必须为正整数")
    if final_top_k <= 0:
        raise ValueError("rerank_top_k 必须为正整数")

    result = retrieve_hybrid(
        session,
        query,
        user_id=user_id,
        top_k=top_k,
        final_k=None,
        client=client,
        subject_id=subject_id,
        kp_ids=kp_ids,
    )
    if not result.fused:
        return result

    reranked, info = rerank_fused(
        result.query,
        result.fused,
        candidates=candidates,
        top_k=final_top_k,
        client=rerank_client,
    )
    if info is not None:
        logger.info(
            "retrieval_reranked",
            extra={
                "scene": "retrieve",
                "user_id": user_id,
                "rerank_used": not info.fallback,
                "rerank_fallback": info.fallback,
                "rerank_tokens": info.tokens,
                "rerank_ms": info.latency_ms,
                "rerank_cost_yuan": info.cost_yuan,
                "reranked_hits": len(reranked),
            },
        )
    return result.model_copy(update={"reranked": reranked, "rerank_info": info})