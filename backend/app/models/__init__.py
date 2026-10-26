"""模型包：显式导入供 Alembic target_metadata 发现。"""
from app.core.db import Base
from app.models.file import File
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_chunk import NoteChunk
from app.models.note_kp import NoteKp
from app.models.subject import Subject
from app.models.user import User
from app.models.user_relation import UserRelation

__all__ = [
    "Base",
    "File",
    "KnowledgeEdge",
    "KnowledgePoint",
    "Note",
    "NoteChunk",
    "NoteKp",
    "Subject",
    "User",
    "UserRelation",
]