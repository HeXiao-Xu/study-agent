"""S1-3 入库编排：切片 → 向量化 → note_chunks（spec §7）。

S2-8 Worker / S3-1 索引服务必须复用本函数，禁止另写一份。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.ai.embedding import BatchStats, EmbeddingClient, get_embedding_client
from app.ai.embedding.errors import EmbeddingError
from app.ai.rag.chunker import Chunk
from app.core.config import get_settings
from app.models.note_chunk import NoteChunk
from app.utils.zh_tokenizer import join_for_tsv

logger = logging.getLogger(__name__)


class IndexingResult(BaseModel):
    chunk_count: int
    vector_dim: int
    total_tokens: int
    elapsed_ms: int
    cost_cny: float


def index_chunks(
    session: Session,
    chunks: list[Chunk],
    *,
    note_id: int,
    user_id: int,
    source_file_id: int | None = None,
    replace: bool = True,
    client: EmbeddingClient | None = None,
    progress: Callable[[BatchStats], None] | None = None,
) -> IndexingResult:
    """把一组 Chunk 写入 note_chunks；同 note_id/user_id 重复调用幂等覆盖。"""
    started = time.perf_counter()
    settings = get_settings()
    embedding_client = client or get_embedding_client()
    tokens_before = embedding_client.usage_tokens

    if not chunks:
        try:
            if replace:
                session.execute(_delete_statement(note_id, user_id))
                session.commit()
        except Exception:
            session.rollback()
            raise
        return IndexingResult(
            chunk_count=0,
            vector_dim=embedding_client.dim,
            total_tokens=0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            cost_cny=0.0,
        )

    try:
        vectors = embedding_client.encode([chunk.content for chunk in chunks], on_batch=progress)
        if len(vectors) != len(chunks):
            raise EmbeddingError(
                f"Embedding 返回条数不符：期望 {len(chunks)}，实际 {len(vectors)}",
                retryable=False,
            )
        for index, vector in enumerate(vectors):
            if len(vector) != settings.embedding_dim:
                raise EmbeddingError(
                    f"第 {index} 条向量维度不符：期望 {settings.embedding_dim}，实际 {len(vector)}",
                    retryable=False,
                )
        if replace:
            session.execute(_delete_statement(note_id, user_id))
        rows = [
            NoteChunk(
                note_id=note_id,
                user_id=user_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                chunk_type=chunk.chunk_type.value,
                heading_path=chunk.heading_path or None,
                embedding=vector,
                tsv=func.to_tsvector("simple", join_for_tsv(chunk.content)),
                source_file_id=source_file_id,
                page_no=chunk.page_no,
                bbox_json=None,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        session.add_all(rows)
        session.commit()
    except Exception:
        session.rollback()
        raise

    total_tokens = embedding_client.usage_tokens - tokens_before
    cost_cny = total_tokens / 1_000_000 * settings.embedding_price_per_million
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "indexing_done",
        extra={
            "scene": "embed",
            "model": embedding_client.model,
            "note_id": note_id,
            "user_id": user_id,
            "chunks": len(chunks),
            "tokens": total_tokens,
            "cost_cny": cost_cny,
            "latency_ms": elapsed_ms,
        },
    )
    return IndexingResult(
        chunk_count=len(chunks),
        vector_dim=len(vectors[0]) if vectors else settings.embedding_dim,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
        cost_cny=cost_cny,
    )


def _delete_statement(note_id: int, user_id: int) -> object:
    """按 note + user 删除旧块；user_id 显式过滤是 AGENTS §4 的硬要求。"""
    return delete(NoteChunk).where(NoteChunk.note_id == note_id, NoteChunk.user_id == user_id)
