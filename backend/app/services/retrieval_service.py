"""S3-2 检索服务（spec §5）：scope 校验 + S1-4/S1-5 复用 + 标题批查。

检索 SQL 只在 ai/rag/retriever.py；本层只做业务编排，不写 SQL 检索逻辑。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.retriever import (
    RetrievalResult,
    RetrievalScope,
    RetrievedChunk,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
)
from app.core.config import get_settings
from app.core.exceptions import InvalidParamError
from app.models.note import Note
from app.schemas.retrieval import (
    RetrievalDebug,
    RetrievalHit,
    RetrievalScopeIn,
    RetrievalSearchResponse,
)

logger = logging.getLogger(__name__)

MAX_TOP_K = 20
SNIPPET_LIMIT = 200


def search_chunks(
    session: Session,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
    rerank: bool | None = None,
    scope: RetrievalScopeIn | None = None,
    debug: bool = False,
) -> RetrievalSearchResponse:
    settings = get_settings()
    clean_query = query.strip()
    if not clean_query:
        raise InvalidParamError("query 不能为空")

    resolved_top_k = settings.retrieval_top_k if top_k is None else top_k
    if not 1 <= resolved_top_k <= MAX_TOP_K:
        raise InvalidParamError(f"top_k 必须在 1–{MAX_TOP_K} 之间")

    use_rerank = settings.retrieval_rerank_enabled if rerank is None else rerank
    retrieval_scope = RetrievalScope(**scope.model_dump()) if scope else None

    if use_rerank:
        result = retrieve_hybrid_reranked(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            rerank_top_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.reranked
    else:
        result = retrieve_hybrid(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            final_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.fused

    titles = _load_titles(session, user_id, _note_ids(result))
    debug_out = None
    if debug:
        debug_out = RetrievalDebug(
            tsquery=result.tsquery,
            vector_ms=result.vector_ms,
            fulltext_ms=result.fulltext_ms,
            vector=[_to_hit(item, titles) for item in result.vector],
            fulltext=[_to_hit(item, titles) for item in result.fulltext],
            fused=[_to_hit(item, titles) for item in result.fused],
        )

    return RetrievalSearchResponse(
        query=clean_query,
        top_k=resolved_top_k,
        rerank=use_rerank,
        elapsed_ms=result.elapsed_ms,
        embedding_ms=result.embedding_ms,
        rerank_info=result.rerank_info if use_rerank else None,
        hits=[_to_hit(item, titles) for item in chosen],
        debug=debug_out,
    )


def _note_ids(result: RetrievalResult) -> list[int]:
    ids = {
        item.note_id
        for item in (
            *result.vector,
            *result.fulltext,
            *result.fused,
            *result.reranked,
        )
    }
    return sorted(ids)


def _load_titles(session: Session, user_id: int, note_ids: list[int]) -> dict[int, str]:
    """一次 IN 查询取标题；禁止在命中循环里查库。"""
    if not note_ids:
        return {}
    rows = session.execute(
        select(Note.id, Note.title).where(Note.user_id == user_id, Note.id.in_(note_ids))
    ).all()
    return {int(row[0]): row[1] for row in rows}


def _to_hit(item: RetrievedChunk, titles: dict[int, str]) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=item.chunk_id,
        note_id=item.note_id,
        note_title=titles.get(item.note_id),
        source_file_id=item.source_file_id,
        chunk_index=item.chunk_index,
        chunk_type=item.chunk_type,
        content=item.content,
        snippet=" ".join(item.content.split())[:SNIPPET_LIMIT],
        heading_path=item.heading_path,
        page_no=item.page_no,
        vector_rank=item.vector_rank,
        vector_distance=item.vector_distance,
        fulltext_rank=item.fulltext_rank,
        fulltext_score=item.fulltext_score,
        rrf_score=item.rrf_score,
        rerank_score=item.rerank_score,
    )