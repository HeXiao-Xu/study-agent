"""S1-3 入库服务测试：fake session/client，验证删除/插入/维度/汇总（spec §7）。"""
from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.embedding.base import BatchStats
from app.ai.embedding.errors import EmbeddingError
from app.ai.rag.chunker import Chunk, ChunkType
from app.services.indexing import index_chunks


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement: object) -> None:
        self.executed.append(statement)

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeClient:
    model = "fake-embed"
    dim = 1024

    def __init__(self, *, dim: int = 1024, fail: bool = False) -> None:
        self.dim = dim
        self.usage_tokens = 0
        self.calls: list[list[str]] = []
        self.fail = fail

    def encode(self, texts: list[str], *, on_batch=None) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("fake failure")
        self.calls.append(list(texts))
        self.usage_tokens += len(texts) * 3
        if on_batch is not None:
            on_batch(BatchStats(0, 1, len(texts), len(texts) * 3, 1))
        return [[0.0] * self.dim for _ in texts]


def _chunk(content: str = "函数的单调性：设 f(x) 在区间 D 内。", index: int = 0) -> Chunk:
    return Chunk(
        content=content,
        chunk_index=index,
        heading_path="函数/单调性",
        page_no=2,
        token_count=12,
        chunk_type=ChunkType.note,
    )


def test_index_chunks_happy_path() -> None:
    session = FakeSession()
    client = FakeClient()
    result = index_chunks(session, [_chunk()], note_id=7, user_id=3, client=client)
    assert client.calls == [["函数的单调性：设 f(x) 在区间 D 内。"]]
    assert len(session.added) == 1
    row = session.added[0]
    assert row.note_id == 7
    assert row.user_id == 3
    assert row.chunk_index == 0
    assert row.token_count == 12
    assert row.chunk_type == "note"
    assert row.heading_path == "函数/单调性"
    assert row.page_no == 2
    assert row.source_file_id is None
    assert row.bbox_json is None
    assert "to_tsvector" in str(row.tsv).lower()
    assert session.committed is True
    assert result.chunk_count == 1
    assert result.vector_dim == 1024
    assert result.total_tokens == 3
    assert result.cost_cny == pytest.approx(3 / 1_000_000 * 0.5)


def test_replace_deletes_same_note_and_user() -> None:
    session = FakeSession()
    index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient())
    sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "DELETE FROM note_chunks" in sql
    assert "note_id = 7" in sql
    assert "user_id = 3" in sql


def test_no_replace_skips_delete() -> None:
    session = FakeSession()
    index_chunks(session, [_chunk()], note_id=7, user_id=3, replace=False, client=FakeClient())
    assert session.executed == []


def test_empty_chunks_with_replace_clears_old_rows() -> None:
    session = FakeSession()
    result = index_chunks(session, [], note_id=7, user_id=3, client=FakeClient())
    assert len(session.executed) == 1
    assert session.committed is True
    assert result.chunk_count == 0
    assert result.total_tokens == 0


def test_dimension_mismatch_rolls_back() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError, match="维度"):
        index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient(dim=8))
    assert session.rolled_back is True
    assert session.added == []


def test_client_failure_rolls_back() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError):
        index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient(fail=True))
    assert session.rolled_back is True
    assert session.added == []


def test_progress_callback_is_forwarded() -> None:
    seen: list[BatchStats] = []
    index_chunks(
        FakeSession(),
        [_chunk()],
        note_id=7,
        user_id=3,
        client=FakeClient(),
        progress=seen.append,
    )
    assert len(seen) == 1
