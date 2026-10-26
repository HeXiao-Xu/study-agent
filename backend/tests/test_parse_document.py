"""S2-8 解析任务：假 session/存储/索引，不连 DB/MinIO/Embedding。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.embedding.errors import EmbeddingError
from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.core.exceptions import InvalidParamError, StorageUnavailableError
from app.models.file import File
from app.models.note import Note
from app.tasks import parse_document as task_module
from app.tasks.parse_document import TASK_PARSE_DOCUMENT, parse_document_task


class FakeStorage:
    def __init__(self, payload: bytes = b"%PDF-1.4 sample", error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.downloads: list[str] = []

    def download_to(self, key, target) -> None:  # noqa: ANN001
        self.downloads.append(key)
        if self.error is not None:
            raise self.error
        target.write(self.payload)


class FakeSession:
    def __init__(self, file: File | None, note: Note | None = None) -> None:
        self.file = file
        self.note = note
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.statuses: list[str] = []

    def get(self, entity: type, pk: int):
        return self.file if entity is File else None

    def scalar(self, statement: object):
        return self.note

    def add(self, instance: object) -> None:
        self.added.append(instance)
        self.note = instance

    def flush(self) -> None:
        self.flushes += 1
        if self.note is not None and getattr(self.note, "id", None) is None:
            self.note.id = 77

    def commit(self) -> None:
        self.commits += 1
        if self.file is not None:
            self.statuses.append(self.file.parse_status)

    def rollback(self) -> None:
        self.rollbacks += 1


def _file(
    *, filename: str = "试卷.pdf", status: str = "pending", file_id: int = 9
) -> File:
    record = File(
        user_id=1,
        filename=filename,
        mime="application/pdf",
        size=128,
        storage_path=f"uploads/1/aa/{file_id}.pdf",
        sha256="a" * 64,
        parse_status=status,
        parse_progress=0,
        error_msg=None,
        parse_started_at=None,
        parse_finished_at=None,
        parse_result_json=None,
    )
    record.id = file_id
    return record


def _doc(text: str = "函数单调性 " * 40, *, scanned: bool = False) -> ParsedDocument:
    return ParsedDocument(
        source="ignored",
        parser="pymupdf",
        is_scanned=scanned,
        blocks=[] if scanned else [ParsedBlock(text=text, page_no=1)],
    )


def _note() -> Note:
    note = Note(
        user_id=1,
        subject_id=None,
        title="旧标题",
        content_md="旧内容",
        content_text="旧内容",
        tags=None,
        folder=None,
        source_file_id=9,
    )
    note.id = 77
    return note


def _patched(
    monkeypatch: pytest.MonkeyPatch,
    *,
    doc: ParsedDocument | None = None,
    parse_error: Exception | None = None,
    index_error: Exception | None = None,
    storage: FakeStorage | None = None,
    existing_note: Note | None = None,
) -> tuple[FakeSession, FakeStorage, list[dict[str, object]]]:
    store = storage or FakeStorage()
    session = FakeSession(_file(), existing_note)
    calls: list[dict[str, object]] = []

    def fake_parse(path, *, force_pymupdf=None):  # noqa: ANN001
        if parse_error is not None:
            raise parse_error
        return doc or _doc()

    def fake_index(session_, chunks, **kwargs):  # noqa: ANN001
        if index_error is not None:
            raise index_error
        calls.append({"chunks": chunks, **kwargs})
        return SimpleNamespace(
            chunk_count=len(chunks),
            vector_dim=1024,
            total_tokens=12,
            elapsed_ms=3,
            cost_cny=0.0,
        )

    monkeypatch.setattr(task_module, "get_storage", lambda: store)
    monkeypatch.setattr(task_module, "parse_document", fake_parse)
    monkeypatch.setattr(task_module, "index_chunks", fake_index)
    return session, store, calls


def test_parse_success_writes_done_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, calls = _patched(monkeypatch)
    result = parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    file = session.file
    assert file is not None
    assert file.parse_status == "done"
    assert file.parse_progress == 100
    assert file.error_msg is None
    assert file.parse_started_at is not None
    assert file.parse_finished_at is not None
    assert result["chunks"] == len(calls[0]["chunks"])
    assert file.parse_result_json["chunks"] == result["chunks"]
    assert file.parse_result_json["parser"] == "pymupdf"
    assert file.parse_result_json["blocks"] == 1
    assert file.parse_result_json["pages"] == 1
    assert store.downloads == [file.storage_path]


def test_parse_success_creates_document_note(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, calls = _patched(monkeypatch)
    parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    note = session.note
    assert note is not None
    assert note.title == "试卷"
    assert note.source_file_id == 9
    assert "函数单调性" in note.content_md
    assert note.content_text
    assert calls[0]["note_id"] == 77
    assert calls[0]["user_id"] == 1
    assert calls[0]["source_file_id"] == 9
    assert calls[0]["replace"] is True


def test_parse_reuses_existing_note(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, calls = _patched(monkeypatch, existing_note=_note())
    parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.added == []
    assert session.note is not None
    assert session.note.id == 77
    assert "函数单调性" in session.note.content_md
    assert session.note.content_md != "旧内容"
    assert calls[0]["note_id"] == 77


def test_parse_skips_done_file(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, calls = _patched(monkeypatch)
    assert session.file is not None
    session.file.parse_status = "done"
    result = parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert result == {"file_id": 9, "skipped": True}
    assert store.downloads == []
    assert calls == []


def test_parse_missing_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(None)
    with pytest.raises(InvalidParamError):
        parse_document_task(session, {"file_id": 1})  # type: ignore[arg-type]
    assert session.commits == 0


def test_parse_scanned_pdf_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, calls = _patched(monkeypatch, doc=_doc(scanned=True))
    with pytest.raises(InvalidParamError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert session.file.parse_status == "failed"
    assert "扫描版" in (session.file.error_msg or "")
    assert calls == []


def test_parse_empty_text_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(
        monkeypatch, doc=ParsedDocument(source="x", parser="pymupdf", blocks=[])
    )
    with pytest.raises(InvalidParamError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert session.file.parse_status == "failed"
    assert "未解析出可用文本" in (session.file.error_msg or "")


def test_parse_image_fails_with_readable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, _ = _patched(monkeypatch)
    assert session.file is not None
    session.file.filename = "错题.png"
    with pytest.raises(InvalidParamError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert "图片解析暂未支持" in (session.file.error_msg or "")
    assert store.downloads == []


def test_parse_unsupported_suffix_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, _ = _patched(monkeypatch)
    assert session.file is not None
    session.file.filename = "无扩展名"
    with pytest.raises(InvalidParamError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert "不支持的文件类型" in (session.file.error_msg or "")
    assert store.downloads == []


def test_parse_broken_pdf_fails_with_type(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(monkeypatch, parse_error=RuntimeError("bad pdf"))
    with pytest.raises(RuntimeError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert session.file.parse_status == "failed"
    assert "RuntimeError" in (session.file.error_msg or "")
    assert "bad pdf" in (session.file.error_msg or "")


def test_parse_storage_failure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(
        monkeypatch, storage=FakeStorage(error=StorageUnavailableError())
    )
    with pytest.raises(StorageUnavailableError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert session.file.parse_status == "failed"
    assert "文件存储不可用" in (session.file.error_msg or "")
    assert session.rollbacks >= 1


def test_parse_embedding_failure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(
        monkeypatch, index_error=EmbeddingError("厂商 500", retryable=False)
    )
    with pytest.raises(EmbeddingError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert session.file.parse_status == "failed"
    assert "EmbeddingError" in (session.file.error_msg or "")


def test_parse_recovers_after_previous_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(monkeypatch)
    assert session.file is not None
    session.file.parse_status = "failed"
    session.file.error_msg = "旧错误"
    parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert "parsing" in session.statuses
    assert session.file.parse_status == "done"
    assert session.file.error_msg is None


def test_parse_error_message_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(monkeypatch, parse_error=RuntimeError("x" * 2000))
    with pytest.raises(RuntimeError):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert len(session.file.error_msg or "") <= 500


def test_parse_result_json_has_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _ = _patched(monkeypatch)
    parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    serialized = json.dumps(session.file.parse_result_json, ensure_ascii=False)
    assert "函数单调性" not in serialized
    assert "content_md" not in serialized


def test_parse_removes_temporary_file(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Path] = []
    real_factory = task_module.tempfile.NamedTemporaryFile

    def tracking_factory(*args, **kwargs):  # noqa: ANN001
        handle = real_factory(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(task_module.tempfile, "NamedTemporaryFile", tracking_factory)
    session, _, _ = _patched(monkeypatch)
    parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert created
    assert all(not path.exists() for path in created)


def test_parse_cleanup_failure_does_not_mask_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = _patched(monkeypatch, parse_error=RuntimeError("bad pdf"))

    def failing_unlink(self, missing_ok=False):  # noqa: ANN001
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(RuntimeError, match="bad pdf"):
        parse_document_task(session, {"file_id": 9})  # type: ignore[arg-type]
    assert session.file is not None
    assert "RuntimeError" in (session.file.error_msg or "")


def test_parse_task_name_matches_registry() -> None:
    from app.tasks.registry import get_handler

    assert TASK_PARSE_DOCUMENT == "parse.document"
    assert get_handler(TASK_PARSE_DOCUMENT) is not None