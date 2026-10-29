"""S2-6/S2-13 文件出入参（API.md §3）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    mime: str
    size: int
    sha256: str
    parse_status: str
    created_at: datetime


class FileUploadOut(FileOut):
    deduped: bool


class FileStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    parse_status: str
    parse_progress: int
    error_msg: str | None
    chunk_count: int = 0


class FileSummaryOut(FileStatusOut):
    mime: str
    size: int
    created_at: datetime
    parse_finished_at: datetime | None


class ChunkPreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    content: str
    token_count: int