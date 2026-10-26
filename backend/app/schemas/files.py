"""S2-6 文件出入参（API.md §3）。"""
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