"""S3-2 检索接口出入参（API.md §5）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.rag.retriever import RerankInfo

RetrievalChunkType = Literal["question", "note", "formula"]


class RetrievalScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: int | None = Field(None, ge=1)
    folder: str | None = Field(None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    chunk_types: list[RetrievalChunkType] | None = Field(None, min_length=1)

    @field_validator("folder")
    @classmethod
    def _strip_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _check_range_and_dedupe(self) -> "RetrievalScopeIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        if self.chunk_types:
            self.chunk_types = list(dict.fromkeys(self.chunk_types))
        return self


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(None, ge=1, le=20)
    rerank: bool | None = None
    debug: bool = False
    scope: RetrievalScopeIn | None = None


class RetrievalHit(BaseModel):
    chunk_id: int
    note_id: int
    note_title: str | None = None
    source_file_id: int | None = None
    chunk_index: int
    chunk_type: str | None = None
    content: str
    snippet: str
    heading_path: str | None = None
    page_no: int | None = None
    vector_rank: int | None = None
    vector_distance: float | None = None
    fulltext_rank: int | None = None
    fulltext_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


class RetrievalDebug(BaseModel):
    tsquery: str
    vector_ms: int
    fulltext_ms: int
    vector: list[RetrievalHit]
    fulltext: list[RetrievalHit]
    fused: list[RetrievalHit]


class RetrievalSearchResponse(BaseModel):
    query: str
    top_k: int
    rerank: bool
    elapsed_ms: int
    embedding_ms: int
    rerank_info: RerankInfo | None = None
    hits: list[RetrievalHit]
    debug: RetrievalDebug | None = None