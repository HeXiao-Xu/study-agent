"""模型包：显式导入供 Alembic target_metadata 发现。"""
from app.core.db import Base
from app.models.note_chunk import NoteChunk

__all__ = ["Base", "NoteChunk"]
