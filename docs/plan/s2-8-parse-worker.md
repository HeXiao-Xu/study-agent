# S2-8 文档解析 Worker + 进度回写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上传后自动入队 `parse.document`，Worker 复用 `parse_document → chunk_document → index_chunks` 把文档解析成“文档笔记 + chunks”，并把 `files` 状态机与进度回写。

**Architecture:** 上传路由在文件落库后调用 `task_service.create_task("parse.document", {"file_id": id})`；Worker 执行同步 handler：下载对象 → 解析 → 切片 → upsert 文档笔记 → `index_chunks` → 文件 `done`。失败时 handler 自己先提交 `failed/error_msg` 再抛给 runner 重试。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.1（同步）、Alembic、ARQ 0.28、MinIO、pgvector、pytest。

**Spec:** `docs/spec/s2-8-parse-worker.md`

## Global Constraints

- **不重写解析/切片/向量化**：必须复用 `app.ai.parse.parse_document`、`app.ai.rag.chunker.chunk_document`、`app.services.indexing.index_chunks`。
- 解析文本落 `notes`（`source_file_id=files.id`），chunk 挂该 `note_id`；不改 `note_chunks` 结构。
- `parse_status` 只允许 `pending/parsing/done/failed`；`parse_progress` 只允许 0–100 的阶段值 0/10/50/80/100。
- 错误信息 `f"{type(exc).__name__}: {exc}"` 截断 500 字，禁止把正文/密钥写入 `error_msg`。
- handler 必须在失败时先 `commit` 文件 `failed/error_msg` 再 `raise`（否则 runner 的 rollback 会把状态吞掉，文件永远 `parsing`）。
- 上传仅在 `record.parse_status ∈ {pending, failed}` 时入队；`done/parsing` 去重命中不重复入队。
- 图片（png/jpg/jpeg）失败信息固定「图片解析暂未支持（待 OCR）」；扫描版 PDF 失败信息含「扫描版」。
- 测试禁止真实网络/DB/MinIO/Embedding：解析器、存储、`index_chunks` 全部注入假实现。
- 提交信息带 `(s2-8)`；`git push` 由用户执行。

---

### Task 1: 迁移 0005、枚举与 File 模型

**Files:**
- Modify: `backend/app/models/enums.py`
- Modify: `backend/app/models/file.py`
- Create: `backend/alembic/versions/0005_s2_8_parse_progress.py`
- Test: 无单测；`alembic upgrade head` + `\d files` 验证

**Interfaces:**
- Consumes: `in_check`、现有 `ck_files_parse_status`
- Produces: `ParseStatus`（`PENDING/PARSING/DONE/FAILED`）、`File.error_msg/parse_progress/parse_started_at/parse_finished_at`

- [ ] **Step 1: 枚举**

`backend/app/models/enums.py` 在 `TaskStatus` 之后追加：

```python
class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"
```

- [ ] **Step 2: 模型**

`backend/app/models/file.py`：

- 导入增加 `SmallInteger`、`ParseStatus`（`from app.models.enums import ParseStatus, in_check`）。
- `__table_args__` 改为：

```python
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_files_user_sha256"),
        CheckConstraint(
            in_check("parse_status", [s.value for s in ParseStatus]),
            name="ck_files_parse_status",
        ),
        CheckConstraint(
            "parse_progress BETWEEN 0 AND 100", name="ck_files_parse_progress"
        ),
        Index("ix_files_user_id", "user_id"),
    )
```

- 在 `parse_result_json` 之后追加：

```python
    parse_progress: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parse_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 3: 迁移**

`backend/alembic/versions/0005_s2_8_parse_progress.py`：

```python
"""S2-8 文件解析进度与错误信息

Revision ID: 0005_s2_8
Revises: 0004_s2_7
Create Date: 2026-10-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_s2_8"
down_revision = "0004_s2_7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("parse_progress", sa.SmallInteger(), server_default=sa.text("0"), nullable=False))
    op.add_column("files", sa.Column("error_msg", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("parse_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("files", sa.Column("parse_finished_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_files_parse_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_parse_status",
        "files",
        "parse_status IN ('pending', 'parsing', 'done', 'failed')",
    )
    op.create_check_constraint(
        "ck_files_parse_progress", "files", "parse_progress BETWEEN 0 AND 100"
    )


def downgrade() -> None:
    op.drop_constraint("ck_files_parse_progress", "files", type_="check")
    op.drop_constraint("ck_files_parse_status", "files", type_="check")
    op.create_check_constraint(
        "ck_files_parse_status", "files", "parse_status IN ('pending', 'done')"
    )
    op.drop_column("files", "parse_finished_at")
    op.drop_column("files", "parse_started_at")
    op.drop_column("files", "error_msg")
    op.drop_column("files", "parse_progress")
```

- [ ] **Step 4: 迁移验证**

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic upgrade head`
Expected: 含 `Running upgrade 0004_s2_7 -> 0005_s2_8`

Run: `cd backend && ../.venv/Scripts/python.exe -m alembic check`
Expected: `No new upgrade operations detected.`

Run: `docker exec study-agent-postgres psql -U study -d study_agent -c "\d files"`
Expected: 新四列 + `ck_files_parse_status`（4 值）+ `ck_files_parse_progress`

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/enums.py backend/app/models/file.py backend/alembic/versions/0005_s2_8_parse_progress.py
git commit -m "feat(s2-8): 文件解析进度与错误字段"
```

---

### Task 2: 解析门面支持 md/txt

**Files:**
- Modify: `backend/app/ai/parse/models.py`
- Modify: `backend/app/ai/parse/__init__.py`
- Test: `backend/tests/test_parse_text.py`

**Interfaces:**
- Consumes: `ParsedDocument`、`ParsedBlock`
- Produces: `ParserName` 增加 `"text"`；`parse_plain_text(path) -> ParsedDocument`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_parse_text.py`：

```python
"""S2-8 md/txt 文本解析支路。"""
from __future__ import annotations

from pathlib import Path

from app.ai.parse import parse_document, parse_plain_text


def test_parse_plain_text_returns_single_block(tmp_path: Path) -> None:
    path = tmp_path / "笔记.md"
    path.write_bytes("# 标题\n函数单调性\n".encode("utf-8"))
    doc = parse_plain_text(path)
    assert doc.parser == "text"
    assert len(doc.blocks) == 1
    assert "函数单调性" in doc.blocks[0].text
    assert doc.blocks[0].page_no is None


def test_parse_document_dispatches_text_file(tmp_path: Path) -> None:
    path = tmp_path / "笔记.txt"
    path.write_bytes(b"\xff\xfeabc")  # 非法 UTF-8：替换不抛
    doc = parse_document(path)
    assert doc.parser == "text"
    assert len(doc.blocks) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_parse_text.py -q`
Expected: FAIL，`ImportError: cannot import name 'parse_plain_text'`

- [ ] **Step 3: 实现**

`backend/app/ai/parse/models.py`：

```python
ParserName = Literal["docling", "pymupdf", "docx", "text"]
```

`backend/app/ai/parse/__init__.py`：

- 导入 `ParsedBlock`：

```python
from app.ai.parse.models import ParsedBlock, ParsedDocument
```

- 在 `parse_document` 之前加：

```python
def parse_plain_text(path: str | Path) -> ParsedDocument:
    """md/txt → 单个 text block；UTF-8，非法字节替换不抛。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument(
        source=str(p),
        parser="text",
        blocks=[ParsedBlock(text=text, page_no=None)],
    )
```

- 在 `parse_document` 的 `.docx` 分支后插入：

```python
    if suffix in {".md", ".txt"}:
        return parse_plain_text(p)
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_parse_text.py -q`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/ai/parse/models.py backend/app/ai/parse/__init__.py backend/tests/test_parse_text.py
git commit -m "feat(s2-8): 解析门面支持 md/txt"
```

---

### Task 3: parse.document 任务

**Files:**
- Create: `backend/app/tasks/parse_document.py`
- Modify: `backend/app/tasks/__init__.py`
- Test: `backend/tests/test_parse_document.py`

**Interfaces:**
- Consumes: `register`、`get_storage().download_to`、`parse_document`、`chunk_document`、`index_chunks`、`to_plain_text`、`ParseStatus`
- Produces: `TASK_PARSE_DOCUMENT = "parse.document"`、`parse_document_task(session, payload) -> dict[str, Any]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_parse_document.py`：

```python
"""S2-8 解析任务：假 session/存储/索引，不连 DB/MinIO/Embedding。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.embedding.errors import EmbeddingError
from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.core.exceptions import InvalidParamError, StorageUnavailableError
from app.models.enums import ParseStatus
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


def test_parse_task_name_matches_registry() -> None:
    from app.tasks.registry import get_handler

    assert TASK_PARSE_DOCUMENT == "parse.document"
    assert get_handler(TASK_PARSE_DOCUMENT) is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_parse_document.py -q`
Expected: FAIL，`ModuleNotFoundError: app.tasks.parse_document`

- [ ] **Step 3: 实现任务**

`backend/app/tasks/parse_document.py`：

```python
"""S2-8 文档解析任务：复用 S1-1/S1-2/S1-3，回写 files 状态与进度。

处理函数不重复实现解析/切片/向量化；失败时先提交 failed/error_msg
再抛出，避免 runner 的 rollback 把文件状态留在 parsing。
"""
from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.parse import parse_document
from app.ai.rag.chunker import chunk_document
from app.core.exceptions import InvalidParamError
from app.core.storage import get_storage
from app.models.enums import ParseStatus
from app.models.file import File
from app.models.note import Note
from app.services.indexing import index_chunks
from app.tasks.registry import register
from app.utils.markdown_text import to_plain_text

logger = logging.getLogger(__name__)

TASK_PARSE_DOCUMENT = "parse.document"

_PROGRESS_STARTED = 10
_PROGRESS_PARSED = 50
_PROGRESS_CHUNKED = 80
_MAX_ERROR_CHARS = 500
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@register(TASK_PARSE_DOCUMENT)
def parse_document_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    file_id = int(payload["file_id"])
    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if file.parse_status == ParseStatus.DONE.value:
        return {"file_id": file_id, "skipped": True}

    _mark_parsing(session, file)
    started = time.perf_counter()
    tmp_path: Path | None = None
    try:
        suffix = Path(file.filename).suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            raise InvalidParamError("图片解析暂未支持（待 OCR）")
        if suffix not in _SUPPORTED_SUFFIXES:
            raise InvalidParamError(f"不支持的文件类型：{suffix or '（无扩展名）'}")

        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = Path(handle.name)
        with handle:
            get_storage().download_to(file.storage_path, handle)

        doc = parse_document(tmp_path)
        if doc.is_scanned:
            raise InvalidParamError("扫描版 PDF：无可抽取文本，需 OCR（后续任务）")
        content_md = "\n\n".join(
            block.text.strip() for block in doc.blocks if block.text.strip()
        )
        if not content_md:
            raise InvalidParamError("未解析出可用文本")
        file.parse_progress = _PROGRESS_PARSED
        session.commit()

        chunks = chunk_document(doc)
        if not chunks:
            raise InvalidParamError("未解析出可用文本")
        file.parse_progress = _PROGRESS_CHUNKED
        session.commit()

        note = _upsert_note(session, file=file, content_md=content_md)
        stats = index_chunks(
            session,
            chunks,
            note_id=note.id,
            user_id=file.user_id,
            source_file_id=file.id,
            replace=True,
        )

        file.parse_status = ParseStatus.DONE.value
        file.parse_progress = 100
        file.error_msg = None
        file.parse_finished_at = _now()
        file.parse_result_json = {
            "parser": doc.parser,
            "pages": len({b.page_no for b in doc.blocks if b.page_no is not None}),
            "blocks": len(doc.blocks),
            "chunks": stats.chunk_count,
            "tokens": stats.total_tokens,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "degraded_reason": doc.degraded_reason,
            "note_id": note.id,
        }
        session.commit()
        logger.info(
            "file_parse_done",
            extra={
                "file_id": file.id,
                "chunks": stats.chunk_count,
                "tokens": stats.total_tokens,
            },
        )
        return {
            "file_id": file.id,
            "chunks": stats.chunk_count,
            "tokens": stats.total_tokens,
            "parser": doc.parser,
        }
    except Exception as exc:
        session.rollback()
        current = session.get(File, file_id)
        message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        if current is not None:
            current.parse_status = ParseStatus.FAILED.value
            current.error_msg = message
            current.parse_finished_at = _now()
            session.commit()
        logger.error("file_parse_failed", extra={"file_id": file_id, "error": message})
        raise
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _mark_parsing(session: Session, file: File) -> None:
    file.parse_status = ParseStatus.PARSING.value
    file.parse_progress = _PROGRESS_STARTED
    file.error_msg = None
    if file.parse_started_at is None:
        file.parse_started_at = _now()
    session.commit()
    logger.info("file_parse_started", extra={"file_id": file.id})


def _upsert_note(session: Session, *, file: File, content_md: str) -> Note:
    note = session.scalar(
        select(Note).where(Note.user_id == file.user_id, Note.source_file_id == file.id)
    )
    title = (Path(file.filename).stem or file.filename)[:200]
    if note is None:
        note = Note(
            user_id=file.user_id,
            subject_id=None,
            title=title,
            content_md=content_md,
            content_text=to_plain_text(content_md),
            tags=None,
            folder=None,
            source_file_id=file.id,
        )
        session.add(note)
    else:
        note.title = title
        note.content_md = content_md
        note.content_text = to_plain_text(content_md)
    session.flush()
    return note
```

- [ ] **Step 4: 注册内置任务**

`backend/app/tasks/__init__.py` 改为：

```python
"""异步任务包（S2-7/S2-8）：注册表、执行器、ARQ 队列与 Worker 入口。

这里显式导入内置任务模块：注册表靠 import 副作用填充，
worker/runner 只 import 本包时也必须能看到全部任务。
"""
from app.tasks import demo as _demo  # noqa: F401  注册 demo.sleep
from app.tasks import parse_document as _parse_document  # noqa: F401  注册 parse.document

__all__ = ["_demo", "_parse_document"]
```

- [ ] **Step 5: 运行任务测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_parse_document.py -q`
Expected: `17 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/tasks/parse_document.py backend/app/tasks/__init__.py backend/tests/test_parse_document.py
git commit -m "feat(s2-8): 文档解析任务与进度回写"
```

---

### Task 4: 上传入队、状态接口与全量回归

**Files:**
- Modify: `backend/app/schemas/files.py`
- Modify: `backend/app/api/v1/files.py`
- Test: `backend/tests/test_files_api.py`

**Interfaces:**
- Consumes: `task_service.create_task`、`TASK_PARSE_DOCUMENT`、`get_task_queue`、`ParseStatus`
- Produces: 上传副作用（入队）、`FileStatusOut.parse_progress/error_msg`

- [ ] **Step 1: 改测试（先失败）**

`backend/tests/test_files_api.py` 做以下修改：

1. 导入增加：

```python
from app.tasks.parse_document import TASK_PARSE_DOCUMENT
from app.tasks.queue import get_task_queue
```

2. 新增 `FakeQueue`：

```python
class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.calls.append((name, task_id))
```

3. `_wire` 改为同时覆盖队列并返回队列：

```python
def _wire(session: FakeSession, storage: FakeStorage | None = None) -> FakeQueue:
    store = storage or FakeStorage()
    queue = FakeQueue()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[get_task_queue] = lambda: queue
    return queue
```

4. `_record` 增加状态与进度参数：

```python
def _record(*, owner_id: int = 1, status: str = "pending") -> File:
    record = File(
        user_id=owner_id,
        filename="试卷.pdf",
        mime="application/pdf",
        size=len(_PDF_BYTES),
        storage_path=f"uploads/{owner_id}/{_DIGEST[:2]}/{_DIGEST}.pdf",
        sha256=_DIGEST,
        parse_status=status,
        parse_progress=0,
        error_msg=None,
    )
    record.id = 11
    record.created_at = datetime.now(timezone.utc)
    return record
```

5. `test_parse_status_returns_pending` 的断言改为：

```python
    assert resp.json()["data"] == {
        "id": 11,
        "filename": "试卷.pdf",
        "parse_status": "pending",
        "parse_progress": 0,
        "error_msg": None,
    }
```

6. 追加 4 条用例：

```python
def test_upload_enqueues_parse_task(client: TestClient) -> None:
    user = _user()
    queue = _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 201
    assert queue.calls == [(TASK_PARSE_DOCUMENT, 11)]


def test_upload_duplicate_done_does_not_enqueue(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record(status="done"))
    storage = FakeStorage()
    storage.objects[_record().storage_path] = _PDF_BYTES
    queue = _wire(session, storage)
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 200
    assert queue.calls == []


def test_upload_duplicate_failed_reenqueues(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record(status="failed"))
    storage = FakeStorage()
    storage.objects[_record().storage_path] = _PDF_BYTES
    queue = _wire(session, storage)
    resp = client.post("/api/v1/files", files=_file_payload(), headers=_headers(user))
    assert resp.status_code == 200
    assert queue.calls == [(TASK_PARSE_DOCUMENT, 11)]


def test_parse_status_returns_progress_and_error(client: TestClient) -> None:
    user = _user()
    record = _record(status="failed")
    record.parse_progress = 50
    record.error_msg = "RuntimeError: bad pdf"
    _wire(FakeSession(user=user, record=record))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["parse_progress"] == 50
    assert data["error_msg"] == "RuntimeError: bad pdf"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q`
Expected: 新增用例失败（未入队 / `parse_progress` 不在响应里）

- [ ] **Step 3: schema 与路由**

`backend/app/schemas/files.py` 的 `FileStatusOut` 改为：

```python
class FileStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    parse_status: str
    parse_progress: int
    error_msg: str | None
```

`backend/app/api/v1/files.py`：

- 导入增加：

```python
from app.models.enums import ParseStatus
from app.services import file_service, task_service
from app.tasks.parse_document import TASK_PARSE_DOCUMENT
from app.tasks.queue import TaskQueue, get_task_queue
```

- `upload_file` 增加参数：

```python
    queue: TaskQueue = Depends(get_task_queue),
```

- 在 `record, deduped = file_service.upload_file(...)` 之后、组装响应之前插入：

```python
    if record.parse_status in {ParseStatus.PENDING.value, ParseStatus.FAILED.value}:
        task_service.create_task(
            session,
            owner=current_user,
            name=TASK_PARSE_DOCUMENT,
            payload={"file_id": record.id},
            queue=queue,
        )
```

- [ ] **Step 4: 接口测试与全量**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q`
Expected: `14 passed`

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `424 passed, 1 warning`（401 + 23）

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas/files.py backend/app/api/v1/files.py backend/tests/test_files_api.py
git commit -m "feat(s2-8): 上传自动入队与解析进度接口"
```

---

### Task 5: 真实 PDF + Worker + MinIO + Embedding 验收

**Files:** 无代码改动；产出验收证据

**Interfaces:**
- Consumes: Task 1–4 全部产物
- Produces: 真实运行证据（状态/进度/chunks/幂等/失败）

- [ ] **Step 1: 生成真实 PDF 与损坏样本**

```bash
cd backend && ../.venv/Scripts/python.exe - <<'PY'
import fitz
from pathlib import Path
base = Path("E:/BiShe-AIStudy/study-agent/.verify_tmp"); base.mkdir(exist_ok=True)
doc = fitz.open()
for i, title in enumerate(["一、函数单调性", "二、例题"]):
    page = doc.new_page()
    page.insert_text((72, 72), f"{title}（第 {i+1} 页）", fontsize=16)
    page.insert_text((72, 110), "设函数 f(x) 在区间 I 上单调递增，则对任意 x1<x2 有 f(x1)<f(x2)。", fontsize=11)
doc.save(base / "s2_8_sample.pdf"); doc.close()
(base / "s2_8_broken.pdf").write_bytes(b"%PDF-1.4\n" + b"not a real pdf" * 20)
print("sample", (base / "s2_8_sample.pdf").stat().st_size)
print("broken", (base / "s2_8_broken.pdf").stat().st_size)
PY
```

Expected：两个文件生成，sample > 1KB

- [ ] **Step 2: 起服务与 Worker**

```bash
# 终端 A
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
# 终端 B
cd backend && ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
```

Expected：Worker 打印 `functions: run_task`（本卡任务都经 run_task 分发）

- [ ] **Step 3: 注册用户并上传真实 PDF**

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"parse_a","password":"test-pass-123","nickname":"解析A","role":"student"}'
TOKEN_A=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"parse_a","password":"test-pass-123"}' | ./.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
echo "$TOKEN_A" > .verify_tmp/token_a
curl -s -w '\nHTTP=%{http_code}\n' -F "file=@.verify_tmp/s2_8_sample.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
```

Expected：`HTTP=201`，`parse_status=pending`，`deduped=false`

- [ ] **Step 4: 轮询状态与进度**

```bash
TOKEN_A=$(cat .verify_tmp/token_a)
for i in $(seq 1 30); do
  curl -s localhost:8000/api/v1/files/1/parse-status -H "Authorization: Bearer $TOKEN_A"; echo; sleep 1
done
```

Expected：依次出现 `pending` → `parsing`（progress 10/50/80）→ `done`（progress 100，error_msg=null）

- [ ] **Step 5: psql 核验产物**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select id, filename, parse_status, parse_progress, error_msg, parse_result_json from files;"
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select id, user_id, title, source_file_id, length(content_md) md_len from notes;"
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select count(*) chunks, count(distinct note_id) notes from note_chunks;"
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select status, attempts, result from async_tasks;"
```

Expected：`files` 一条 `done/100`；`notes` 一条 `source_file_id` 非空；`note_chunks` 数量 > 0 且等于 `parse_result_json->>'chunks'`；`async_tasks` succeeded

- [ ] **Step 6: 幂等（重复上传）**

```bash
TOKEN_A=$(cat .verify_tmp/token_a)
curl -s -w '\nHTTP=%{http_code}\n' -F "file=@.verify_tmp/s2_8_sample.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select (select count(*) from async_tasks) tasks, (select count(*) from note_chunks) chunks;"
```

Expected：`HTTP=200` + `deduped=true`；`tasks` 仍为 1、`chunks` 不变

- [ ] **Step 7: 损坏 PDF → failed 可读**

```bash
TOKEN_A=$(cat .verify_tmp/token_a)
curl -s -F "file=@.verify_tmp/s2_8_broken.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
# 等任务 3 次尝试结束（约 10s）后轮询
curl -s localhost:8000/api/v1/files/2/parse-status -H "Authorization: Bearer $TOKEN_A"
```

Expected：`parse_status=failed`，`error_msg` 含 `RuntimeError`/解析器异常，`parse_progress` 保留失败阶段（10 或 50）

- [ ] **Step 8: md 成功、png 失败**

```bash
printf '# 笔记\n函数单调性\n' > .verify_tmp/s2_8_note.md
printf '\x89PNG\r\n\x1a\nrest' > .verify_tmp/s2_8_img.png
TOKEN_A=$(cat .verify_tmp/token_a)
curl -s -F "file=@.verify_tmp/s2_8_note.md;type=text/markdown" -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
curl -s -F "file=@.verify_tmp/s2_8_img.png;type=image/png" -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
# 轮询 file 3（md）应为 done；file 4（png）应为 failed + 图片解析暂未支持
```

- [ ] **Step 9: Worker 日志核对**

Expected：`file_parse_started` / `file_parse_done` / `file_parse_failed` 出现，只含 file_id/chunks/tokens/error，不含正文

- [ ] **Step 10: 清理与全量测试**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "delete from note_chunks; delete from notes; delete from async_tasks; delete from files; delete from users where username like 'parse\_%';"
docker exec study-agent-postgres psql -U study -d study_agent -t -c \
 "select (select count(*) from note_chunks) chunks, (select count(*) from notes) notes, (select count(*) from files) files;"
# 删除 MinIO 对象后停掉 uvicorn/arq
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```

Expected：计数全 0；`424 passed, 1 warning`

---

### Task 6: 文档同步与提交

**Files:**
- Modify: `docs/API.md`、`docs/SCHEMA.md`、`AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`docs/AI协作开发实施计划.md`、`docs/spec/s1-1-doc-parse.md`
- Modify: `docs/spec/s2-8-parse-worker.md`（状态）、`docs/plan/s2-8-parse-worker.md`（执行记录）

- [ ] **Step 1: API.md**

- §3 上传：补充“成功后入队 `parse.document`；`done/parsing` 去重不重复入队；入队失败 500”。
- §3 parse-status：字段加 `parse_progress` / `error_msg`，状态机 `pending→parsing→done/failed`。
- §13 无新错误码（沿用 50000）。

- [ ] **Step 2: SCHEMA.md**

- §4.1 files 表补四列（error_msg/parse_progress/parse_started_at/parse_finished_at）与两个 CHECK。
- §10.2 parse_status 改为四值并标注 S2-8 定稿。

- [ ] **Step 3: AGENTS.md**

- §9.2 加：文件解析必须复用 `parse_document/chunk_document/index_chunks`；handler 失败先落 failed 再抛；「文档笔记」由 `(user_id, source_file_id)` 唯一确定。
- §9.6 加锚点：`backend/app/tasks/parse_document.py`。

- [ ] **Step 4: DECISIONS.md**

新增 D-028：文档笔记方案、阶段进度、md/txt 文本支路、图片失败、error_msg 策略、入队条件、幂等与重试、真实验收数字、已知限制。

- [ ] **Step 5: PROGRESS.md 与实施计划**

- 状态改 S2-8 完成、下一步 S2-9；勾选 `[x] S2-8`；遗留表更新（running 心跳、OCR、手动手解析、进度粒度过粗、删除文件无接口）；追加 2026-10-26 S2-8 日志。
- `docs/AI协作开发实施计划.md` 第 999 行 `[ ] S2-8` 改 `[x]`。

- [ ] **Step 6: S1-1 spec 枚举**

`docs/spec/s1-1-doc-parse.md` 的 `ParserName` 说明补 `text`（md/txt 支路，S2-8 增补）。

- [ ] **Step 7: spec/plan 状态与执行记录**

- spec 状态改「已实现并验收（日期；pytest 424/424 + 真实 PDF 证据）」。
- plan 写执行记录：commit 列表、pytest、状态/进度实测、chunks 计数、幂等、失败信息、偏差。

- [ ] **Step 8: 文档提交**

```bash
git add docs/ AGENTS.md
git commit -m "docs(s2-8): 文档解析契约、决策与进度同步"
```

---

## Self-Review

- 覆盖 spec：迁移/枚举（Task 1）、md/txt（Task 2）、解析任务与回写（Task 3）、上传入队与接口字段（Task 4）、真实验收（Task 5）、文档（Task 6）。
- 无占位符：每个新建文件与测试用例都给了完整代码；Task 3 的 `_patched` 明确标注“直接放进测试文件顶部”。
- 类型一致：`parse_document_task(session, payload) -> dict`、`TASK_PARSE_DOCUMENT`、`_upsert_note`、`File.parse_progress/error_msg` 在 Task 1/3/4 间一致。
- 已知取舍：文档笔记会进笔记列表；进度是阶段值；重试会短暂显示 failed；图片依赖后续 OCR；入队失败上传返回 500 但文件已存在。

## 执行记录

**提交列表**

1. `8efb613 feat(s2-8): 文件解析进度与错误字段`
2. `e0781ca feat(s2-8): 解析门面支持 md/txt`
3. `07d5c8a feat(s2-8): 文档解析任务与进度回写`
4. `ec43841 feat(s2-8): 上传自动入队与解析进度接口`
5. `db18636 fix(s2-8): 临时文件清理失败不再掩盖解析错误`
6. `docs(s2-8): 文档解析契约、决策与进度同步`

**pytest**：文本支路 `2 passed`；任务 `18 passed`；文件接口 `14 passed`；全量 **425 passed, 1 warning**（401 + 24；比 plan 预估多 1 条，因补了临时文件清理失败用例）。

**真实 PDF + Worker + MinIO + Postgres + 真实 Embedding**

| 步骤 | 实测 |
|---|---|
| 迁移 | `0004_s2_7 -> 0005_s2_8`；`alembic check` → `No new upgrade operations detected.`；`\d files` 见四列 + `ck_files_parse_status`(4 值) + `ck_files_parse_progress` |
| 中文 2 页 PDF（file 4） | 201 `pending` → 轮询 `parsing(10)` → `parsing(50)` → `done(100)`；`elapsed_ms=90240`；`parse_result_json={"pages":2,"blocks":4,"chunks":2,"parser":"docling","tokens":85,"degraded_reason":null}` |
| 文档笔记 | `notes` 自动建一条：`title=s2_8_sample_cn`、`source_file_id=4`、`content_md` 含「一、函数单调性」「二、例题」 |
| chunks | `note_chunks` 2 条（source_file_id=4），与 `parse_result_json.chunks` 一致；真实 Embedding `text-embedding-v4` |
| 幂等 | 重复上传同一 PDF → **200** `deduped=true`；`async_tasks` 2 条不变、chunks 2 条不变 |
| 损坏 PDF（file 5） | `failed`、`parse_progress=10`、`error_msg="FileDataError: Failed to open file '...tmp....pdf' as type pdf."`；任务 attempts=3、最终 failed；再次上传（failed 去重命中）会重新入队 |
| md（file 6） | `done/100`；1 个 chunk；真实 Embedding 9 tokens、latency 685ms |
| png（file 7） | `failed`、`error_msg="InvalidParamError: 图片解析暂未支持（待 OCR）"`；attempts=3 |
| Worker 日志 | `file_parse_started` / `file_parse_done` / `file_parse_failed` / `file_parse_tmp_cleanup_failed`；只含 file_id/chunks/tokens/error，无正文 |
| 清理 | note_chunks/notes/files/async_tasks/users 全 0；MinIO 5 个对象已删；uvicorn/arq 已停 |

**与 plan 的偏差**

1. 真实损坏 PDF 暴露 Windows 句柄问题：解析器异常退出后仍持有临时文件，`unlink` 抛 WinError 32 会**覆盖**原始 `FileDataError`，任务 error 变成不可读的锁冲突。改为 `try/except OSError` + `file_parse_tmp_cleanup_failed` WARNING，原始错误保留（`fix(s2-8)`，并补 1 条测试，所以总数 425 而非 424）。
2. S1-1 既有用例 `test_facade_unsupported_ext` 用 `.txt` 断言不支持；S2-8 契约新增 md/txt 支路后改为 `.xlsx`，并注明变更来源。
3. Docling 首次加载模型约 182s、第二次 90s，仍在 `TASK_JOB_TIMEOUT_SECONDS=300` 内；大文件分页续跑未实现（已入遗留 22）。
4. `app/tasks/parse_document.py` 会 commit `files` 的进度/失败态（spec 决策 5），与 AGENTS §9.2“handler 不得自行 commit”冲突；已在 §9.2 明确这是唯一例外，`async_tasks` 状态仍只由 runner 提交。
5. 首个英文样张因 PyMuPDF 默认字体不含中文，PDF 文本是替换符（验收误用，非解析器问题）；改用 `fontname="china-s"` 重新生成中文样张后文本正确，两次都作为证据保留。

**遗留**：见 D-028 与 PROGRESS 遗留 22–26。
