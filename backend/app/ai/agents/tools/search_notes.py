"""S6-1 search_notes：个人知识库混合检索的薄封装。"""
from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.schemas.retrieval import (
    RetrievalChunkType,
    RetrievalHit,
    RetrievalMode,
    RetrievalScopeIn,
)
from app.services.retrieval_service import search_chunks

CONTENT_LIMIT = 1200


class SearchNotesIn(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    subject_id: int | None = Field(default=None, ge=1)
    folder: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    chunk_types: list[RetrievalChunkType] | None = Field(
        default=None, min_length=1, max_length=3
    )
    top_k: int = Field(default=8, ge=1, le=20)
    retrieval: RetrievalMode = "hybrid"

    @model_validator(mode="after")
    def _check_range(self) -> "SearchNotesIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        if self.chunk_types:
            self.chunk_types = list(dict.fromkeys(self.chunk_types))
        return self


class SearchNoteHit(ToolOutput):
    chunk_id: int
    note_id: int
    note_title: str | None = None
    chunk_index: int
    chunk_type: str | None = None
    heading_path: str | None = None
    page_no: int | None = None
    content: str
    snippet: str
    truncated: bool
    rrf_score: float
    rerank_score: float | None = None


class SearchNotesOut(ToolOutput):
    query: str
    retrieval: str
    top_k: int
    hit_count: int
    elapsed_ms: int
    embedding_ms: int
    hits: list[SearchNoteHit]


def _to_hit(hit: RetrievalHit) -> SearchNoteHit:
    content = hit.content or ""
    truncated = len(content) > CONTENT_LIMIT
    return SearchNoteHit(
        chunk_id=hit.chunk_id,
        note_id=hit.note_id,
        note_title=hit.note_title,
        chunk_index=hit.chunk_index,
        chunk_type=hit.chunk_type,
        heading_path=hit.heading_path,
        page_no=hit.page_no,
        content=content[:CONTENT_LIMIT],
        snippet=hit.snippet,
        truncated=truncated,
        rrf_score=hit.rrf_score,
        rerank_score=hit.rerank_score,
    )


def search_notes(ctx: ToolContext, data: SearchNotesIn) -> SearchNotesOut:
    scope = None
    if any(
        value is not None
        for value in (
            data.subject_id,
            data.folder,
            data.start_date,
            data.end_date,
            data.chunk_types,
        )
    ):
        scope = RetrievalScopeIn(
            subject_id=data.subject_id,
            folder=data.folder,
            start_date=data.start_date,
            end_date=data.end_date,
            chunk_types=data.chunk_types,
        )
    result = search_chunks(
        ctx.session,
        user_id=ctx.user.id,
        query=data.query,
        top_k=data.top_k,
        retrieval=data.retrieval,
        scope=scope,
        debug=False,
    )
    hits = [_to_hit(hit) for hit in result.hits]
    return SearchNotesOut(
        query=result.query,
        retrieval=data.retrieval,
        top_k=result.top_k,
        hit_count=len(hits),
        elapsed_ms=result.elapsed_ms,
        embedding_ms=result.embedding_ms,
        hits=hits,
    )


SPEC = ToolSpec(
    name="search_notes",
    description=(
        "用途：在学生个人知识库里做混合检索，返回可引用的笔记片段；"
        "需要「笔记里怎么说的」或为答案找依据时用。"
        "参数 query 为检索问题，可用 subject_id/folder/start_date/end_date/chunk_types 限定范围，"
        "top_k 取 1–20 条，retrieval 可选 vector/hybrid/hybrid_rerank。"
        "返回带 note_id、标题、页码与正文片段的命中列表（正文超过 1200 字会截断）。"
    ),
    input_model=SearchNotesIn,
    output_model=SearchNotesOut,
    handler=search_notes,
)