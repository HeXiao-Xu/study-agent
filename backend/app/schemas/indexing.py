"""S3-1 索引重建出入参（API.md §11）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RebuildStart(BaseModel):
    run_id: str
    total_notes: int
    purged_chunks: int


class RebuildFailure(BaseModel):
    note_id: int | None
    error: str | None


class RebuildProgress(BaseModel):
    run_id: str
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int
    percent: int
    chunks: int
    started_at: datetime | None
    finished_at: datetime | None
    failures: list[RebuildFailure]