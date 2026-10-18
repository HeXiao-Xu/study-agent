"""S1-3 模型契约测试：字段/可空性/索引与 SCHEMA §4.3 一致（spec §5）。"""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from app.models.note_chunk import NoteChunk

_EXPECTED_COLUMNS = {
    "id",
    "note_id",
    "user_id",
    "chunk_index",
    "content",
    "token_count",
    "chunk_type",
    "heading_path",
    "embedding",
    "tsv",
    "source_file_id",
    "page_no",
    "bbox_json",
}


def test_table_name_and_columns() -> None:
    assert NoteChunk.__tablename__ == "note_chunks"
    assert set(NoteChunk.__table__.columns.keys()) == _EXPECTED_COLUMNS


def test_embedding_is_vector_1024() -> None:
    embedding = NoteChunk.__table__.columns["embedding"]
    assert isinstance(embedding.type, Vector)
    assert embedding.type.dim == 1024
    assert embedding.nullable is False


def test_tsv_and_jsonb_types() -> None:
    assert isinstance(NoteChunk.__table__.columns["tsv"].type, TSVECTOR)
    assert isinstance(NoteChunk.__table__.columns["bbox_json"].type, JSONB)


def test_nullable_flags_match_schema() -> None:
    cols = NoteChunk.__table__.columns
    for name in ("note_id", "user_id", "chunk_index", "content", "token_count", "embedding"):
        assert cols[name].nullable is False
    for name in ("chunk_type", "heading_path", "tsv", "source_file_id", "page_no", "bbox_json"):
        assert cols[name].nullable is True


def test_unique_and_indexes() -> None:
    table = NoteChunk.__table__
    uniques = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_note_chunks_note_chunk_index" in uniques
    index_names = {idx.name for idx in table.indexes}
    assert {"ix_note_chunks_user_id", "ix_note_chunks_tsv_gin", "ix_note_chunks_embedding_hnsw"} <= index_names


def test_id_is_bigint() -> None:
    assert isinstance(NoteChunk.__table__.columns["id"].type, BigInteger)
    assert isinstance(NoteChunk.__table__.columns["chunk_index"].type, Integer)
    assert isinstance(NoteChunk.__table__.columns["content"].type, Text)
