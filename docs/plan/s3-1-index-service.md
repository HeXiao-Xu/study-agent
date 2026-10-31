# S3-1 切片入库服务产品化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让笔记正文成为 RAG 检索来源：Markdown → 切片 → Embedding → `note_chunks`，并提供管理员全量重建与可查询的进度；笔记软删时同步清理切片。

**Architecture:** 新增 `ai/parse/markdown.py` 把笔记 Markdown 拆成 S1-2 能消费的 `ParsedBlock`，新增 `services/index_service.py` 作为唯一入库编排入口（内部只调 S1-3 `index_chunks`）。保存/重建统一走 `index.note` 异步任务；重建按笔记拆任务、用 `run_id` 聚合 `async_tasks` 状态计算进度，不新增表/迁移。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Pydantic v2 / ARQ / pytest（全部零真实网络）

**Spec:** `docs/spec/s3-1-index-service.md`

## Global Constraints

- 不新增依赖、不改 `requirements.txt` / `package.json`；本卡**无 Alembic 迁移**。
- 分层：路由只做校验与 `Envelope` 组装；业务在 `services/`；AI 调用只在 `ai/`；禁止在路由或 service 里直接调 SDK。
- 所有函数带类型注解；出参用 Pydantic 模型；业务错误抛 `AppError` 子类。
- 数据库查询必须显式带 `user_id`（AGENTS §4）。
- 测试外部依赖（Embedding/Redis/DB）全部 fake/monkeypatch；pytest 必须全绿（基线 524 passed）。
- 提交信息：`feat(s3-1): ...` / `docs(s3-1): ...`；`git push` 由用户执行。
- 不修改 `backend/app/services/indexing.py`、`backend/app/ai/rag/chunker.py`、S2-8 Worker。
- 验收必须真实跑（Postgres + Redis + Worker + 真实 Embedding），禁止造数。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/ai/parse/markdown.py` | 新建 | 笔记 Markdown → `ParsedDocument`（标题路径/代码块/表格/段落） |
| `backend/app/services/index_service.py` | 新建 | 索引唯一入口、笔记切片清理、重建启动与进度聚合 |
| `backend/app/schemas/indexing.py` | 新建 | 重建入参/进度出参 Pydantic 模型 |
| `backend/app/tasks/index_note.py` | 新建 | `index.note` 任务（调 service，不自行 commit） |
| `backend/app/tasks/__init__.py` | 修改 | 显式 import 注册 `index.note` |
| `backend/app/api/v1/admin.py` | 新建 | `POST /admin/index/rebuild`、`GET /admin/index/runs/{run_id}` |
| `backend/app/api/router.py` | 修改 | include admin 路由 |
| `backend/app/api/v1/notes.py` | 修改 | 创建/正文更新入队 `index.note`；通用 best-effort 入队 |
| `backend/app/services/note_service.py` | 修改 | 软删同一事务删除切片 |
| `backend/tests/test_markdown_parse.py` | 新建 | 解析器单测 |
| `backend/tests/test_index_service.py` | 新建 | 服务/进度单测 |
| `backend/tests/test_index_task.py` | 新建 | 任务单测 |
| `backend/tests/test_index_admin_api.py` | 新建 | 管理员接口单测 |
| `backend/tests/test_notes_api.py` | 修改 | 笔记索引副作用 + 删除切片断言 |
| `docs/spec/s3-1-index-service.md` | 已建 | 设计契约（已批准） |
| `docs/API.md`、`docs/SCHEMA.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md` | 修改 | 契约/决策/进度/锚点同步 |

---

### Task 1: Markdown 解析器

**Files:**
- Create: `backend/app/ai/parse/markdown.py`
- Test: `backend/tests/test_markdown_parse.py`

**Interfaces:**
- Consumes: `app.ai.parse.models.ParsedBlock` / `ParsedDocument`（S1-1 契约）
- Produces: `parse_markdown_text(text: str, *, source: str) -> ParsedDocument`（`parser="text"`、`page_no=None`、`is_scanned=False`），供 Task 2 的 `build_note_chunks` 使用

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_markdown_parse.py`：

```python
"""S3-1 笔记 Markdown → ParsedBlock（spec §4）。"""
from __future__ import annotations

from app.ai.parse.markdown import parse_markdown_text


def _blocks(text: str):
    return parse_markdown_text(text, source="note:1").blocks


def test_parse_markdown_text_headings_set_heading_path() -> None:
    blocks = _blocks("# 函数\n\n导数是变化率。\n\n## 单调性\n\n设区间 D。")
    assert [b.heading_path for b in blocks] == [
        ["函数"],
        ["函数"],
        ["函数", "单调性"],
        ["函数", "单调性"],
    ]
    assert blocks[0].text == "函数"
    assert blocks[1].text == "导数是变化率。"


def test_parse_markdown_text_level_skip_keeps_ancestor_path() -> None:
    blocks = _blocks("# 一\n\n### 三层\n\n正文")
    assert blocks[-1].heading_path == ["一", "三层"]


def test_parse_markdown_text_lower_heading_pops_stack() -> None:
    blocks = _blocks("# A\n\n## B\n\n# C\n\n正文")
    assert blocks[-1].heading_path == ["C"]


def test_parse_markdown_text_code_fence_is_single_block() -> None:
    blocks = _blocks("```python\n# 不是标题\nprint(1)\n```\n")
    assert len(blocks) == 1
    assert blocks[0].text.startswith("```python")
    assert "# 不是标题" in blocks[0].text


def test_parse_markdown_text_table_is_single_block() -> None:
    blocks = _blocks("| a | b |\n| --- | --- |\n| 1 | 2 |")
    assert len(blocks) == 1
    assert blocks[0].text.startswith("|")
    assert "\n" in blocks[0].text


def test_parse_markdown_text_blank_line_splits_paragraphs() -> None:
    blocks = _blocks("第一段\n\n第二段")
    assert [b.text for b in blocks] == ["第一段", "第二段"]


def test_parse_markdown_text_image_keeps_alt_only() -> None:
    blocks = _blocks("![函数图](note-file://12)")
    assert blocks[0].text == "函数图"


def test_parse_markdown_text_keeps_latex_and_list() -> None:
    blocks = _blocks("公式 $x^2$ 与 $$\\int_0^1 x dx$$\n\n- 第一条\n- 第二条")
    assert "$x^2$" in blocks[0].text
    assert blocks[1].text.startswith("- 第一条")


def test_parse_markdown_text_drops_empty_section_headings() -> None:
    blocks = _blocks("# 空节\n\n# 有内容\n\n正文")
    assert [b.text for b in blocks] == ["有内容", "正文"]


def test_parse_markdown_text_empty_returns_no_blocks() -> None:
    assert _blocks("   \n\n") == []


def test_parse_markdown_text_strips_closing_hashes() -> None:
    blocks = _blocks("# 标题 ###\n\n正文")
    assert blocks[0].text == "标题"


def test_parse_markdown_text_sets_text_parser_and_no_page() -> None:
    document = parse_markdown_text("# 标题\n\n正文", source="note:7")
    assert document.parser == "text"
    assert document.source == "note:7"
    assert document.is_scanned is False
    assert all(block.page_no is None for block in document.blocks)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_markdown_parse.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.ai.parse.markdown'`

- [ ] **Step 3: Implement the parser**

创建 `backend/app/ai/parse/markdown.py`：

```python
"""S3-1 笔记 Markdown → 解析块（spec §4）。

笔记没有可解析的文件，但 S1-2 切片器只认 ParsedBlock；这里把 Markdown
拆成标题块 + 段落/表格/代码块，标题路径交给切片器组织章节。
标题块文本必须等于所属小节 heading_path 的末元素，S1-2 才会把它并进小节。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.parse.models import ParsedBlock, ParsedDocument

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_CLOSING_HASH_RE = re.compile(r"[ \t]+#+[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


@dataclass
class _Item:
    """内部条目：heading 只为等 S1-2 合并；空小节的 heading 最后丢弃。"""

    kind: str  # heading / body
    text: str
    path: list[str]


def _strip_images(text: str) -> str:
    """图片 URL 不进入检索正文；alt 保留，避免整段空掉。"""
    return _IMAGE_RE.sub(lambda match: match.group(1), text)


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def _current_path(stack: list[tuple[int, str]]) -> list[str]:
    return [title for _, title in stack]


def parse_markdown_text(text: str, *, source: str) -> ParsedDocument:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    items: list[_Item] = []
    stack: list[tuple[int, str]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading is not None:
            level = len(heading.group(1))
            title = _CLOSING_HASH_RE.sub("", heading.group(2)).strip()
            index += 1
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            items.append(_Item("heading", title, _current_path(stack)))
            continue

        fence = _FENCE_RE.match(line)
        if fence is not None:
            char = fence.group(1)[0]
            buffer = [line]
            index += 1
            while index < len(lines):
                buffer.append(lines[index])
                closing = lines[index].strip()
                index += 1
                if closing.startswith(char * 3):
                    break
            items.append(_Item("body", "\n".join(buffer).strip(), _current_path(stack)))
            continue

        if _is_table_line(line):
            buffer = []
            while index < len(lines) and _is_table_line(lines[index]):
                buffer.append(lines[index].rstrip())
                index += 1
            items.append(_Item("body", "\n".join(buffer), _current_path(stack)))
            continue

        buffer = []
        while index < len(lines):
            current = lines[index]
            if not current.strip() or _HEADING_RE.match(current) or _FENCE_RE.match(current):
                break
            buffer.append(current.rstrip())
            index += 1
        body = _strip_images("\n".join(buffer)).strip()
        if body:
            items.append(_Item("body", body, _current_path(stack)))

    blocks: list[ParsedBlock] = []
    for position, item in enumerate(items):
        if item.kind == "heading":
            following = items[position + 1] if position + 1 < len(items) else None
            if following is None or following.kind == "heading":
                continue
        blocks.append(
            ParsedBlock(text=item.text, page_no=None, heading_path=list(item.path))
        )
    return ParsedDocument(source=source, parser="text", blocks=blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_markdown_parse.py -q
```

Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/parse/markdown.py backend/tests/test_markdown_parse.py
git commit -m "feat(s3-1): Markdown 解析器与标题路径"
```

---

### Task 2: 索引服务与重建进度

**Files:**
- Create: `backend/app/schemas/indexing.py`
- Create: `backend/app/services/index_service.py`
- Test: `backend/tests/test_index_service.py`

**Interfaces:**
- Consumes: `app.ai.parse.markdown.parse_markdown_text`（Task 1）、`app.ai.rag.chunker.chunk_document`、`app.services.indexing.index_chunks`、`app.services.task_service.create_task`
- Produces:
  - `TASK_INDEX_NOTE: str == "index.note"`（定义在 service，避免 task↔service 循环导入）
  - `NoteIndexResult`（frozen dataclass：`note_id, chunk_count, total_tokens, elapsed_ms, cost_cny, skipped, reason`）
  - `build_note_chunks(note: Note) -> list[Chunk]`
  - `index_note(session, *, note_id: int, client: EmbeddingClient | None = None) -> NoteIndexResult`
  - `delete_note_chunks(session, *, note_id: int, user_id: int) -> None`（不 commit）
  - `purge_deleted_note_chunks(session) -> int`（不 commit）
  - `start_rebuild(session, *, owner: User, queue: TaskQueue) -> RebuildStart`
  - `get_rebuild_progress(session, *, run_id: str) -> RebuildProgress`
  - schemas：`RebuildStart(run_id, total_notes, purged_chunks)`、`RebuildFailure(note_id, error)`、`RebuildProgress(run_id, total, pending, running, succeeded, failed, percent, chunks, started_at, finished_at, failures)`

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_index_service.py`：

```python
"""S3-1 索引服务与重建进度测试（spec §5）：fake session，零网络。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.rag.chunker import Chunk, ChunkType
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.note import Note
from app.services import index_service, task_service
from app.services.indexing import IndexingResult


class FakeResult:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self, *, note=None, note_ids=None, tasks=None, rowcount=0) -> None:
        self.note = note
        self.note_ids = note_ids or []
        self.tasks = tasks or []
        self.rowcount = rowcount
        self.executed: list[object] = []
        self.commits = 0
        self.rolled_back = 0

    def get(self, entity: type, pk: int):
        assert entity is Note
        return self.note

    def scalars(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is Note:
            return iter(self.note_ids)
        if entity is AsyncTask:
            return iter(self.tasks)
        raise AssertionError(f"unexpected entity: {entity}")

    def execute(self, statement: object):
        self.executed.append(statement)
        return FakeResult(self.rowcount)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def _note(*, note_id: int = 7, deleted: bool = False, source_file_id: int | None = None) -> Note:
    note = Note(
        user_id=3,
        subject_id=None,
        title="函数",
        content_md="# 函数\n\n设 $f(x)$ 在区间 D 内单调递增。\n\n## 单调性\n\n定义。",
        content_text="设 在区间 D 内单调递增。",
        tags=None,
        folder=None,
        source_file_id=source_file_id,
    )
    note.id = note_id
    note.deleted_at = datetime.now(timezone.utc) if deleted else None
    return note


def _chunk() -> Chunk:
    return Chunk(
        content="函数的单调性",
        chunk_index=0,
        heading_path="函数/单调性",
        page_no=None,
        token_count=6,
        chunk_type=ChunkType.note,
    )


def _sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_build_note_chunks_sets_heading_path() -> None:
    chunks = index_service.build_note_chunks(_note())
    assert chunks
    assert chunks[0].heading_path == "函数"
    assert all(chunk.chunk_type == ChunkType.note for chunk in chunks)


def test_index_note_passes_scope_and_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    note = _note(source_file_id=12)
    captured: dict[str, object] = {}

    def fake_index_chunks(session, chunks, **kwargs):
        captured.update(kwargs)
        return IndexingResult(
            chunk_count=len(chunks),
            vector_dim=1024,
            total_tokens=6,
            elapsed_ms=9,
            cost_cny=0.01,
        )

    monkeypatch.setattr(index_service, "build_note_chunks", lambda note: [_chunk()])
    monkeypatch.setattr(index_service, "index_chunks", fake_index_chunks)

    result = index_service.index_note(FakeSession(note=note), note_id=7)

    assert captured["note_id"] == 7
    assert captured["user_id"] == 3
    assert captured["source_file_id"] == 12
    assert captured["replace"] is True
    assert result.chunk_count == 1
    assert result.skipped is False


def test_index_note_missing_note_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(index_service, "index_chunks", lambda *a, **k: called.append(1))

    result = index_service.index_note(FakeSession(note=None), note_id=99)

    assert result.skipped is True
    assert result.reason == "note_missing"
    assert called == []


def test_index_note_deleted_note_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(index_service, "index_chunks", lambda *a, **k: called.append(1))

    result = index_service.index_note(FakeSession(note=_note(deleted=True)), note_id=7)

    assert result.skipped is True
    assert result.reason == "note_deleted"
    assert called == []


def test_delete_note_chunks_filters_note_and_user() -> None:
    session = FakeSession()
    index_service.delete_note_chunks(session, note_id=7, user_id=3)

    sql = _sql(session.executed[0])
    assert "DELETE FROM note_chunks" in sql
    assert "note_id = 7" in sql
    assert "user_id = 3" in sql
    assert session.commits == 0


def test_purge_deleted_note_chunks_filters_soft_deleted() -> None:
    session = FakeSession(rowcount=4)

    assert index_service.purge_deleted_note_chunks(session) == 4

    sql = _sql(session.executed[0])
    assert "DELETE FROM note_chunks" in sql
    assert "deleted_at IS NOT NULL" in sql
    assert session.commits == 0


def test_start_rebuild_creates_one_task_per_note(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(note_ids=[5, 6])
    created: list[dict[str, object]] = []

    monkeypatch.setattr(index_service, "purge_deleted_note_chunks", lambda s: 2)
    monkeypatch.setattr(
        task_service, "create_task", lambda session, **kwargs: created.append(kwargs)
    )

    result = index_service.start_rebuild(
        session, owner=SimpleNamespace(id=1), queue=SimpleNamespace()
    )

    assert session.commits == 1
    assert result.total_notes == 2
    assert result.purged_chunks == 2
    assert len(result.run_id) == 32
    assert [item["payload"] for item in created] == [
        {"note_id": 5, "run_id": result.run_id},
        {"note_id": 6, "run_id": result.run_id},
    ]
    assert all(item["name"] == index_service.TASK_INDEX_NOTE for item in created)


def test_start_rebuild_without_notes_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession(note_ids=[])
    monkeypatch.setattr(
        index_service,
        "purge_deleted_note_chunks",
        lambda s: pytest.fail("空库不应该清理切片"),
    )

    with pytest.raises(InvalidParamError, match="没有可重建的笔记"):
        index_service.start_rebuild(
            session, owner=SimpleNamespace(id=1), queue=SimpleNamespace()
        )


def _task(
    status: str,
    *,
    note_id: int = 1,
    chunks: int | None = None,
    error: str | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
) -> AsyncTask:
    task = AsyncTask(
        user_id=1,
        name=index_service.TASK_INDEX_NOTE,
        status=status,
        payload={"note_id": note_id, "run_id": "a" * 32},
        result={"chunks": chunks} if chunks is not None else None,
        error=error,
    )
    task.started_at = started
    task.finished_at = finished
    return task


def test_get_rebuild_progress_aggregates_statuses() -> None:
    started = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    session = FakeSession(
        tasks=[
            _task(TaskStatus.SUCCEEDED.value, note_id=5, chunks=3, started=started),
            _task(TaskStatus.SUCCEEDED.value, note_id=6, chunks=2, started=started),
            _task(TaskStatus.FAILED.value, note_id=7, error="Embedding 失败"),
            _task(TaskStatus.PENDING.value, note_id=8),
        ]
    )

    progress = index_service.get_rebuild_progress(session, run_id="a" * 32)

    assert progress.total == 4
    assert progress.succeeded == 2
    assert progress.failed == 1
    assert progress.pending == 1
    assert progress.running == 0
    assert progress.percent == 75
    assert progress.chunks == 5
    assert progress.finished_at is None
    assert [item.note_id for item in progress.failures] == [7]
    assert progress.failures[0].error == "Embedding 失败"


def test_get_rebuild_progress_marks_finished_when_all_terminal() -> None:
    finished = datetime(2026, 10, 31, 12, 1, tzinfo=timezone.utc)
    session = FakeSession(
        tasks=[
            _task(TaskStatus.SUCCEEDED.value, chunks=3, finished=finished),
            _task(TaskStatus.FAILED.value, note_id=2, error="坏笔记"),
        ]
    )

    progress = index_service.get_rebuild_progress(session, run_id="a" * 32)

    assert progress.percent == 100
    assert progress.finished_at == finished


def test_get_rebuild_progress_unknown_run_raises() -> None:
    with pytest.raises(NotFoundError, match="索引重建记录不存在"):
        index_service.get_rebuild_progress(FakeSession(tasks=[]), run_id="b" * 32)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.index_service'`

- [ ] **Step 3: Implement schemas**

创建 `backend/app/schemas/indexing.py`：

```python
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
```

- [ ] **Step 4: Implement the service**

创建 `backend/app/services/index_service.py`：

```python
"""S3-1 索引服务（spec §5）：笔记正文 → 切片 → note_chunks。

唯一入库编排入口：复用 S1-3 index_chunks，不重写向量化。
重建进度复用 async_tasks（每篇笔记一个 index.note 任务），不建新表。
TASK_INDEX_NOTE 定义在这里：tasks/index_note 反向导入 service，
若把常量放 task 模块会形成 service → task → service 的循环导入。
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient
from app.ai.parse.markdown import parse_markdown_text
from app.ai.rag.chunker import Chunk, chunk_document
from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.async_task import AsyncTask
from app.models.enums import TaskStatus
from app.models.note import Note
from app.models.note_chunk import NoteChunk
from app.models.user import User
from app.schemas.indexing import RebuildFailure, RebuildProgress, RebuildStart
from app.services.indexing import index_chunks

if TYPE_CHECKING:
    from app.tasks.queue import TaskQueue

TASK_INDEX_NOTE = "index.note"
_MAX_FAILURES = 20
_TERMINAL = {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value}


@dataclass(frozen=True)
class NoteIndexResult:
    note_id: int
    chunk_count: int
    total_tokens: int
    elapsed_ms: int
    cost_cny: float
    skipped: bool = False
    reason: str | None = None


def build_note_chunks(note: Note) -> list[Chunk]:
    """笔记 Markdown → 检索原子块；切片算法仍归 S1-2。"""
    document = parse_markdown_text(note.content_md, source=f"note:{note.id}")
    return chunk_document(document)


def index_note(
    session: Session, *, note_id: int, client: EmbeddingClient | None = None
) -> NoteIndexResult:
    """按笔记重建切片；软删/不存在的笔记不改动任何行。"""
    note = session.get(Note, note_id)
    if note is None:
        return NoteIndexResult(note_id, 0, 0, 0, 0.0, True, "note_missing")
    if note.deleted_at is not None:
        return NoteIndexResult(note_id, 0, 0, 0, 0.0, True, "note_deleted")

    started = time.perf_counter()
    chunks = build_note_chunks(note)
    stats = index_chunks(
        session,
        chunks,
        note_id=note.id,
        user_id=note.user_id,
        source_file_id=note.source_file_id,
        replace=True,
        client=client,
    )
    return NoteIndexResult(
        note_id=note.id,
        chunk_count=stats.chunk_count,
        total_tokens=stats.total_tokens,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        cost_cny=stats.cost_cny,
    )


def delete_note_chunks(session: Session, *, note_id: int, user_id: int) -> None:
    """软删笔记时调用；不 commit，与笔记状态同一事务。"""
    session.execute(
        delete(NoteChunk).where(
            NoteChunk.note_id == note_id, NoteChunk.user_id == user_id
        )
    )


def purge_deleted_note_chunks(session: Session) -> int:
    """清掉历史上软删笔记遗留的切片（检索链路不 join notes，靠这里兜底）。"""
    deleted_notes = select(Note.id).where(Note.deleted_at.is_not(None))
    result = session.execute(
        delete(NoteChunk).where(NoteChunk.note_id.in_(deleted_notes))
    )
    return int(result.rowcount or 0)


def start_rebuild(
    session: Session, *, owner: User, queue: TaskQueue
) -> RebuildStart:
    """为一篇笔记建一个 index.note 任务，共享 run_id 用于进度聚合。"""
    # 延迟导入：app.tasks 包会 import 本模块，顶层导入 task_service 会循环
    from app.services import task_service

    note_ids = list(
        session.scalars(
            select(Note.id).where(Note.deleted_at.is_(None)).order_by(Note.id)
        )
    )
    if not note_ids:
        raise InvalidParamError("没有可重建的笔记")

    purged = purge_deleted_note_chunks(session)
    session.commit()

    run_id = uuid.uuid4().hex
    for note_id in note_ids:
        task_service.create_task(
            session,
            owner=owner,
            name=TASK_INDEX_NOTE,
            payload={"note_id": note_id, "run_id": run_id},
            queue=queue,
        )
    return RebuildStart(
        run_id=run_id, total_notes=len(note_ids), purged_chunks=purged
    )


def _note_id_of(task: AsyncTask) -> int | None:
    value = (task.payload or {}).get("note_id")
    return int(value) if value is not None else None


def get_rebuild_progress(session: Session, *, run_id: str) -> RebuildProgress:
    tasks = list(
        session.scalars(
            select(AsyncTask)
            .where(
                AsyncTask.name == TASK_INDEX_NOTE,
                AsyncTask.payload["run_id"].astext == run_id,
            )
            .order_by(AsyncTask.id)
        )
    )
    if not tasks:
        raise NotFoundError("索引重建记录不存在")

    counts = Counter(task.status for task in tasks)
    total = len(tasks)
    terminal = sum(counts[status] for status in _TERMINAL)
    chunks = sum(
        int(task.result.get("chunks") or 0)
        for task in tasks
        if task.status == TaskStatus.SUCCEEDED.value and task.result
    )
    started_values = [task.started_at for task in tasks if task.started_at is not None]
    finished_values = [
        task.finished_at for task in tasks if task.finished_at is not None
    ]
    failures = [
        RebuildFailure(note_id=_note_id_of(task), error=task.error)
        for task in tasks
        if task.status == TaskStatus.FAILED.value
    ][:_MAX_FAILURES]

    return RebuildProgress(
        run_id=run_id,
        total=total,
        pending=counts[TaskStatus.PENDING.value],
        running=counts[TaskStatus.RUNNING.value],
        succeeded=counts[TaskStatus.SUCCEEDED.value],
        failed=counts[TaskStatus.FAILED.value],
        percent=round(terminal / total * 100),
        chunks=chunks,
        started_at=min(started_values) if started_values else None,
        finished_at=(
            max(finished_values)
            if terminal == total and finished_values
            else None
        ),
        failures=failures,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_service.py -q
```

Expected: `12 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/indexing.py backend/app/services/index_service.py backend/tests/test_index_service.py
git commit -m "feat(s3-1): 索引服务与重建进度聚合"
```

---

### Task 3: `index.note` 异步任务

**Files:**
- Create: `backend/app/tasks/index_note.py`
- Modify: `backend/app/tasks/__init__.py`
- Test: `backend/tests/test_index_task.py`

**Interfaces:**
- Consumes: `app.services.index_service.index_note` / `TASK_INDEX_NOTE` / `NoteIndexResult`
- Produces: 注册任务名 `index.note`；任务成功结果 `{"note_id", "chunks", "tokens", "elapsed_ms", "cost_cny", "skipped", "reason"}`（进度接口累加 `chunks` 依赖该键）

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_index_task.py`：

```python
"""S3-1 index.note 任务测试：不触库、不调 Embedding。"""
from __future__ import annotations

import pytest

from app.services.index_service import NoteIndexResult
from app.tasks import index_note as index_note_task_module
from app.tasks.index_note import TASK_INDEX_NOTE, index_note_task
from app.tasks.registry import get_handler


def test_task_is_registered() -> None:
    assert get_handler(TASK_INDEX_NOTE) is index_note_task


def test_index_note_task_returns_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_index_note(session, *, note_id):
        captured["note_id"] = note_id
        return NoteIndexResult(
            note_id=note_id,
            chunk_count=3,
            total_tokens=42,
            elapsed_ms=17,
            cost_cny=0.0001,
        )

    monkeypatch.setattr(index_note_task_module, "index_note", fake_index_note)

    result = index_note_task(object(), {"note_id": 9, "run_id": "a" * 32})

    assert captured["note_id"] == 9
    assert result == {
        "note_id": 9,
        "chunks": 3,
        "tokens": 42,
        "elapsed_ms": 17,
        "cost_cny": 0.0001,
        "skipped": False,
        "reason": None,
    }


def test_index_note_task_passes_skipped_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        index_note_task_module,
        "index_note",
        lambda session, *, note_id: NoteIndexResult(
            note_id=note_id,
            chunk_count=0,
            total_tokens=0,
            elapsed_ms=0,
            cost_cny=0.0,
            skipped=True,
            reason="note_deleted",
        ),
    )

    result = index_note_task(object(), {"note_id": 9})

    assert result["skipped"] is True
    assert result["reason"] == "note_deleted"


def test_index_note_task_rejects_missing_note_id() -> None:
    with pytest.raises(ValueError, match="note_id"):
        index_note_task(object(), {})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_task.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.tasks.index_note'`

- [ ] **Step 3: Implement the task**

创建 `backend/app/tasks/index_note.py`：

```python
"""S3-1 索引任务：执行 index_service.index_note（不自行 commit 任务状态）。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.index_service import TASK_INDEX_NOTE, index_note
from app.tasks.registry import register

logger = logging.getLogger(__name__)


@register(TASK_INDEX_NOTE)
def index_note_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = int(payload.get("note_id") or 0)
    if note_id <= 0:
        raise ValueError("payload 缺少 note_id")
    result = index_note(session, note_id=note_id)
    data = {
        "note_id": result.note_id,
        "chunks": result.chunk_count,
        "tokens": result.total_tokens,
        "elapsed_ms": result.elapsed_ms,
        "cost_cny": result.cost_cny,
        "skipped": result.skipped,
        "reason": result.reason,
    }
    logger.info(
        "index_note_done",
        extra={
            "note_id": result.note_id,
            "chunks": result.chunk_count,
            "tokens": result.total_tokens,
            "skipped": result.skipped,
        },
    )
    return data
```

修改 `backend/app/tasks/__init__.py`：

```python
"""异步任务包（S2-7/S2-8/S2-10/S3-1）...

这里显式导入内置任务模块：注册表靠 import 副作用填充，
worker/runner 只 import 本包时也必须能看到全部内置任务。
"""
from app.tasks import demo as _demo  # noqa: F401  注册 demo.sleep
from app.tasks import index_note as _index_note  # noqa: F401  注册 index.note
from app.tasks import kp_align as _kp_align  # noqa: F401  注册 kp.align
from app.tasks import parse_document as _parse_document  # noqa: F401  注册 parse.document

__all__ = ["_demo", "_index_note", "_kp_align", "_parse_document"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_task.py backend/tests/test_task_registry.py -q
```

Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/index_note.py backend/app/tasks/__init__.py backend/tests/test_index_task.py
git commit -m "feat(s3-1): index.note 任务与注册"
```

---

### Task 4: 笔记索引副作用与管理员重建接口

**Files:**
- Create: `backend/app/api/v1/admin.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/v1/notes.py`
- Modify: `backend/app/services/note_service.py`
- Modify: `backend/tests/test_notes_api.py`
- Test: `backend/tests/test_index_admin_api.py`

**Interfaces:**
- Consumes: `index_service.start_rebuild` / `get_rebuild_progress` / `delete_note_chunks`、`TASK_INDEX_NOTE`、`RebuildStart` / `RebuildProgress`
- Produces:
  - `POST /api/v1/admin/index/rebuild` → `202 Envelope[RebuildStart]`
  - `GET /api/v1/admin/index/runs/{run_id}` → `Envelope[RebuildProgress]`（`run_id` 必须 32 位小写十六进制，否则 422/42200）
  - 笔记创建/正文更新入队 `index.note`；软删删除切片

- [ ] **Step 1: Write the failing admin API tests**

创建 `backend/tests/test_index_admin_api.py`：

```python
"""S3-1 管理员重建索引接口测试（spec §7）：TestClient + 依赖覆盖。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.indexing import RebuildProgress, RebuildStart
from app.services import index_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def refresh(self, instance: object) -> None:
        return None

    def scalars(self, statement: object):
        return iter([])

    def execute(self, statement: object):
        return None


class FakeQueue:
    def enqueue(self, name: str, task_id: int) -> None:
        return None


def _user(user_id: int = 1, *, role: str = "admin", username: str = "admin_1") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade=None,
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: FakeQueue()


def test_rebuild_requires_admin(client: TestClient) -> None:
    teacher = _user(2, role="teacher", username="teacher_1")
    _override(FakeSession(user=teacher))
    resp = client.post(
        "/api/v1/admin/index/rebuild", headers=_headers(teacher)
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_rebuild_requires_token(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post("/api/v1/admin/index/rebuild")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_rebuild_returns_202(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        index_service,
        "start_rebuild",
        lambda session, *, owner, queue: RebuildStart(
            run_id="a" * 32, total_notes=4, purged_chunks=2
        ),
    )

    resp = client.post("/api/v1/admin/index/rebuild", headers=_headers(admin))

    assert resp.status_code == 202
    assert resp.json()["data"] == {
        "run_id": "a" * 32,
        "total_notes": 4,
        "purged_chunks": 2,
    }


def test_rebuild_returns_500_when_queue_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import TaskQueueUnavailableError

    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, *, owner, queue):
        raise TaskQueueUnavailableError()

    monkeypatch.setattr(index_service, "start_rebuild", fail)

    resp = client.post("/api/v1/admin/index/rebuild", headers=_headers(admin))

    assert resp.status_code == 500
    assert resp.json()["code"] == 50000


def test_progress_returns_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    progress = RebuildProgress(
        run_id="a" * 32,
        total=3,
        pending=0,
        running=0,
        succeeded=3,
        failed=0,
        percent=100,
        chunks=11,
        started_at=None,
        finished_at=None,
        failures=[],
    )
    monkeypatch.setattr(
        index_service, "get_rebuild_progress", lambda session, *, run_id: progress
    )

    resp = client.get(
        f"/api/v1/admin/index/runs/{'a' * 32}", headers=_headers(admin)
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["percent"] == 100
    assert data["chunks"] == 11
    assert data["failures"] == []
    assert set(data) == {
        "run_id",
        "total",
        "pending",
        "running",
        "succeeded",
        "failed",
        "percent",
        "chunks",
        "started_at",
        "finished_at",
        "failures",
    }


def test_progress_unknown_run_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import NotFoundError

    admin = _user()
    _override(FakeSession(user=admin))

    def missing(session, *, run_id):
        raise NotFoundError("索引重建记录不存在")

    monkeypatch.setattr(index_service, "get_rebuild_progress", missing)

    resp = client.get(
        f"/api/v1/admin/index/runs/{'b' * 32}", headers=_headers(admin)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_progress_rejects_bad_run_id(client: TestClient) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    resp = client.get("/api/v1/admin/index/runs/not-a-run-id", headers=_headers(admin))

    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_progress_forbidden_for_student(client: TestClient) -> None:
    student = _user(3, role="student", username="student_1")
    _override(FakeSession(user=student))

    resp = client.get(
        f"/api/v1/admin/index/runs/{'a' * 32}", headers=_headers(student)
    )

    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_admin_api.py -q
```

Expected: `404`（路由未注册）导致断言失败

- [ ] **Step 3: Implement admin routes**

创建 `backend/app/api/v1/admin.py`：

```python
"""S3-1 管理端接口：索引重建与进度（API.md §11）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.indexing import RebuildProgress, RebuildStart
from app.services import index_service
from app.tasks.queue import TaskQueue, get_task_queue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/index/rebuild",
    status_code=202,
    response_model=Envelope[RebuildStart],
    summary="全量重建笔记索引（每篇笔记一个 index.note 任务）",
)
def rebuild_index(
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[RebuildStart]:
    data = index_service.start_rebuild(session, owner=current_user, queue=queue)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/index/runs/{run_id}",
    response_model=Envelope[RebuildProgress],
    summary="查询索引重建进度",
)
def get_rebuild_run(
    run_id: str = Path(..., pattern="^[0-9a-f]{32}$", description="重建 run_id"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[RebuildProgress]:
    data = index_service.get_rebuild_progress(session, run_id=run_id)
    return Envelope(trace_id=get_trace_id(), data=data)
```

修改 `backend/app/api/router.py`：

```python
"""v1 路由汇总：只做 include，不写业务。"""
from fastapi import APIRouter

from app.api.v1 import admin, auth, files, kp, notes, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(notes.router)
api_router.include_router(files.router)
api_router.include_router(tasks.router)
api_router.include_router(kp.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
```

- [ ] **Step 4: Run admin tests to verify they pass**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_index_admin_api.py -q
```

Expected: `8 passed`

- [ ] **Step 5: Write failing note-side-effect tests**

在 `backend/tests/test_notes_api.py` 顶部补充导入：

```python
from sqlalchemy.dialects import postgresql

from app.models.async_task import AsyncTask
```

给 `FakeSession.__init__` 增加 `self.executed: list[object] = []`，并新增方法：

```python
    def execute(self, statement: object) -> None:
        self.executed.append(statement)
```

追加 4 条测试：

```python
def _task_names(session: FakeSession) -> list[str]:
    return [item.name for item in session.added if isinstance(item, AsyncTask)]


def test_create_note_enqueues_index_task(client: TestClient) -> None:
    session = FakeSession(user=_user())
    _override(session)

    resp = client.post(
        "/api/v1/notes",
        json={"title": "函数单调性", "content_md": "## 单调性\n\n设 $x$ 递增"},
        headers=_headers(session.user),
    )

    assert resp.status_code == 201
    assert "index.note" in _task_names(session)


def test_patch_note_content_enqueues_index_task(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)

    resp = client.patch(
        "/api/v1/notes/1",
        json={"content_md": "## 新章节\n\n新正文"},
        headers=_headers(session.user),
    )

    assert resp.status_code == 200
    assert "index.note" in _task_names(session)
    assert note.content_text == "新章节 新正文"


def test_patch_note_title_only_does_not_enqueue_index(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)

    resp = client.patch(
        "/api/v1/notes/1", json={"title": "新标题"}, headers=_headers(session.user)
    )

    assert resp.status_code == 200
    assert "index.note" not in _task_names(session)


def test_delete_note_deletes_chunks(client: TestClient) -> None:
    note = _note()
    session = FakeSession(user=_user(), note=note)
    _override(session)

    resp = client.delete("/api/v1/notes/1", headers=_headers(session.user))

    assert resp.status_code == 204
    sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "DELETE FROM note_chunks" in sql
    assert "note_id = 1" in sql
    assert "user_id = 1" in sql
```

- [ ] **Step 6: Run note tests to verify they fail**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_notes_api.py -q
```

Expected: 新增 4 条失败（没有 `index.note` 入队 / 没有 DELETE 语句；`FakeSession.execute` 若缺失会 `AttributeError`）

- [ ] **Step 7: Implement note-side effects**

修改 `backend/app/api/v1/notes.py`：

```python
"""S2-5 笔记 CRUD 接口（API.md §2）。

S3-1 起：创建与正文更新后 best-effort 入队 index.note（索引是增强能力，
队列不可用只警告，不回滚笔记保存）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import TaskQueueUnavailableError
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope, PageData
from app.schemas.notes import NoteCreate, NoteOut, NoteSummary, NoteUpdate
from app.services import note_service, task_service
from app.services.index_service import TASK_INDEX_NOTE
from app.tasks.kp_align import TASK_KP_ALIGN
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, SortParams, page_params, sort_params

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


def _enqueue_note_task(
    session: Session,
    *,
    user: User,
    note_id: int,
    name: str,
    queue: TaskQueue,
    event: str,
) -> None:
    try:
        task_service.create_task(
            session,
            owner=user,
            name=name,
            payload={"note_id": note_id},
            queue=queue,
        )
    except TaskQueueUnavailableError as exc:
        logger.warning(event, extra={"note_id": note_id, "error": str(exc)})


def _enqueue_index(
    session: Session, *, user: User, note_id: int, queue: TaskQueue
) -> None:
    _enqueue_note_task(
        session,
        user=user,
        note_id=note_id,
        name=TASK_INDEX_NOTE,
        queue=queue,
        event="index_note_enqueue_failed",
    )


def _enqueue_align(
    session: Session, *, user: User, note_id: int, queue: TaskQueue
) -> None:
    _enqueue_note_task(
        session,
        user=user,
        note_id=note_id,
        name=TASK_KP_ALIGN,
        queue=queue,
        event="kp_align_enqueue_failed",
    )
```

创建/更新路由改为：

```python
def create_note(...):
    note = note_service.create_note(session, owner=current_user, payload=payload)
    _enqueue_index(session, user=current_user, note_id=note.id, queue=queue)
    _enqueue_align(session, user=current_user, note_id=note.id, queue=queue)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))


def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[NoteOut]:
    note = note_service.update_note(
        session, note_id=note_id, owner=current_user, payload=payload
    )
    # 只有正文变了才需要重新 Embedding；改标题/标签不花这份钱
    if "content_md" in payload.model_fields_set:
        _enqueue_index(session, user=current_user, note_id=note.id, queue=queue)
    _enqueue_align(session, user=current_user, note_id=note.id, queue=queue)
    return Envelope(trace_id=get_trace_id(), data=NoteOut.model_validate(note))
```

修改 `backend/app/services/note_service.py` 的 `delete_note`：

```python
def delete_note(session: Session, *, note_id: int, owner: User) -> None:
    note = _load_note(session, note_id)
    if note.user_id != owner.id:
        raise ForbiddenError("无权删除该资源")
    note.deleted_at = datetime.now(timezone.utc)
    # 检索链路只按 user_id 过滤、不 join notes：切片必须与软删同事务清掉
    index_service.delete_note_chunks(
        session, note_id=note.id, user_id=note.user_id
    )
    _commit(session)
```

并在文件头部导入：

```python
from app.services import index_service
```

- [ ] **Step 8: Run note + admin tests**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest backend/tests/test_notes_api.py backend/tests/test_index_admin_api.py -q
```

Expected: 全部 passed（note 文件 20 条 + admin 8 条）

- [ ] **Step 9: Run full backend suite**

```bash
cd E:/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pytest -q
```

Expected: `563 passed` 左右（基线 524 + 新增 39；以实际为准，全绿即可）

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/v1/admin.py backend/app/api/router.py backend/app/api/v1/notes.py backend/app/services/note_service.py backend/tests/test_notes_api.py backend/tests/test_index_admin_api.py
git commit -m "feat(s3-1): 笔记索引副作用与管理员重建接口"
```

---

### Task 5: 真实环境验收 + 文档同步

**Files:**
- Modify: `docs/API.md`、`docs/SCHEMA.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-1-index-service.md`（执行记录）
- Modify: this plan（执行记录）

**Interfaces:**
- Consumes: Task 1–4 的全部产物
- Produces: 可复现的验收证据（真实块数/任务状态/耗时）与全套文档同步

- [ ] **Step 1: 起服务（真实 Postgres/Redis/MinIO + 真实 Embedding）**

```powershell
cd E:\BiShe-AIStudy\study-agent
docker ps --format "{{.Names}} {{.Status}}"   # 三个容器应 Up
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 另一终端：
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m arq app.tasks.worker.WorkerSettings
```

确认 `http://127.0.0.1:8000/health` 返回 ok；确认 `.env` 已配置 Embedding Key（不打印 Key）。

- [ ] **Step 2: 注册验收账号并提升 admin**

```powershell
$base = "http://127.0.0.1:8000/api/v1"
curl.exe -s -X POST "$base/auth/register" -H "Content-Type: application/json" `
  -d '{"username":"s31_student","password":"S31-pass-123","nickname":"S3-1验收学生","grade":"高一"}'
curl.exe -s -X POST "$base/auth/register" -H "Content-Type: application/json" `
  -d '{"username":"s31_admin","password":"S31-admin-123","nickname":"S3-1验收管理员"}'
docker exec study-agent-postgres psql -U study -d study_agent -c "update users set role='admin' where username='s31_admin';"
$student = (curl.exe -s -X POST "$base/auth/login" -H "Content-Type: application/json" -d '{"username":"s31_student","password":"S31-pass-123"}' | ConvertFrom-Json).data.access_token
$admin = (curl.exe -s -X POST "$base/auth/login" -H "Content-Type: application/json" -d '{"username":"s31_admin","password":"S31-admin-123"}' | ConvertFrom-Json).data.access_token
```

Expected: 注册 201、`update` 1 行、两个 token 非空。

- [ ] **Step 3: 创建笔记 → 确认自动入库**

```powershell
$body = @{ title = "S3-1 验收笔记"; tags = @("函数"); content_md = "# 函数`n`n设 $f(x)$ 在区间 D 内单调递增。`n`n## 单调性`n`n判断步骤：`n1. 取 $x_1<x_2$；`n2. 比较 $f(x_1)$ 与 $f(x_2)$。" } | ConvertTo-Json
Set-Content -Path .\s31-note.json -Value $body -Encoding utf8
$note = (curl.exe -s -X POST "$base/notes" -H "Authorization: Bearer $student" -H "Content-Type: application/json" --data-binary "@s31-note.json" | ConvertFrom-Json).data
$noteId = $note.id
Start-Sleep -Seconds 8
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,status,result->>'chunks' as chunks,error from async_tasks where name='index.note' and payload->>'note_id'='$noteId' order by id desc limit 1;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as chunks, string_agg(distinct heading_path,' | ') as headings from note_chunks where note_id=$noteId;"
```

Expected: 任务 `succeeded`、`chunks > 0`；`heading_path` 含 `函数`、`函数/单调性`。

- [ ] **Step 4: 修改正文 → 确认旧块删除、新块出现**

```powershell
$patch = @{ content_md = "# 函数`n`n设 $f(x)$ 在区间 D 内单调递增。`n`n## 单调性`n`n判断步骤：`n1. 取 $x_1<x_2$；`n2. 比较 $f(x_1)$ 与 $f(x_2)$。`n`nS3-1-唯一标记-20261031" } | ConvertTo-Json
Set-Content -Path .\s31-patch.json -Value $patch -Encoding utf8
curl.exe -s -X PATCH "$base/notes/$noteId" -H "Authorization: Bearer $student" -H "Content-Type: application/json" --data-binary "@s31-patch.json" | Out-Null
Start-Sleep -Seconds 8
docker exec study-agent-postgres psql -U study -d study_agent -c "select id,status,result->>'chunks' as chunks from async_tasks where name='index.note' and payload->>'note_id'='$noteId' order by id desc limit 1;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as hit_new from note_chunks where note_id=$noteId and content like '%唯一标记%';"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as chunks from note_chunks where note_id=$noteId;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select note_id,chunk_index,count(*) from note_chunks group by 1,2 having count(*)>1;"
```

Expected: 最新任务 succeeded；`hit_new = 1`；`chunks` 与该任务 `result.chunks` 一致；重复分组查询 0 行。

- [ ] **Step 5: 软删清理**

```powershell
$tmpBody = @{ title = "S3-1 临时笔记"; content_md = "# 临时`n`n这段只用于删除验收。" } | ConvertTo-Json
Set-Content -Path .\s31-tmp.json -Value $tmpBody -Encoding utf8
$tmp = (curl.exe -s -X POST "$base/notes" -H "Authorization: Bearer $student" -H "Content-Type: application/json" --data-binary "@s31-tmp.json" | ConvertFrom-Json).data
Start-Sleep -Seconds 6
curl.exe -s -X DELETE "$base/notes/$($tmp.id)" -H "Authorization: Bearer $student" | Out-Null
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as leftover from note_chunks where note_id=$($tmp.id);"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as orphan from note_chunks c join notes n on n.id=c.note_id where n.deleted_at is not null;"
```

Expected: `leftover = 0`、`orphan = 0`。

- [ ] **Step 6: 管理员全量重建 + 进度 + 幂等**

```powershell
$run = (curl.exe -s -X POST "$base/admin/index/rebuild" -H "Authorization: Bearer $admin" | ConvertFrom-Json).data
$runId = $run.run_id
"run_id=$runId total_notes=$($run.total_notes) purged=$($run.purged_chunks)"
Start-Sleep -Seconds 20
# 若仍有 pending/running，继续轮询该接口直到 percent=100
curl.exe -s "$base/admin/index/runs/$runId" -H "Authorization: Bearer $admin"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as total_chunks from note_chunks;"
# 再跑一次全量重建，验证不产生重复
$run2 = (curl.exe -s -X POST "$base/admin/index/rebuild" -H "Authorization: Bearer $admin" | ConvertFrom-Json).data
Start-Sleep -Seconds 20
curl.exe -s "$base/admin/index/runs/$($run2.run_id)" -H "Authorization: Bearer $admin"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as total_chunks_after from note_chunks;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select note_id,chunk_index,count(*) from note_chunks group by 1,2 having count(*)>1;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) as chunks_with_page from note_chunks where page_no is not null;"
```

Expected：两次进度 `percent=100`、`failed=0`、`chunks` == `total_chunks`；第二次跑完 `total_chunks_after` 与第一次相同；重复分组 0 行；`chunks_with_page` 变 0（全量重建按 Markdown 重建，页码归零——记录为已知代价）。

- [ ] **Step 7: 权限与回归**

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "$base/admin/index/rebuild" -H "Authorization: Bearer $student"   # 期望 403
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "$base/admin/index/rebuild"                                       # 期望 401
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe scripts\ask.py --user-id 18 "函数的单调性怎么判断？"
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 403 / 401；`ask.py` 能检索并给出带引用回答（不报错）；pytest 全绿。

- [ ] **Step 8: 更新契约与文档**

1. `docs/API.md`
   - §2 笔记：三条写接口后补"副作用"一行（创建/正文更新入队 `index.note`；软删同事务清理 `note_chunks`）。
   - §11 运维：新增 `POST /admin/index/rebuild`（202、admin、出参 `{run_id,total_notes,purged_chunks}`）与 `GET /admin/index/runs/{run_id}`（字段表、404/422 语义）。
2. `docs/SCHEMA.md` §4.3 末尾补注：S3-1 起 `note_chunks` 同时承载手写笔记（按 Markdown 重建），文档笔记重建后 `page_no/bbox_json` 为空。
3. `docs/DECISIONS.md` 追加 `D-035 S3-1 索引服务与重建进度`，记录 spec §2 的 8 条决策、"全量重建丢页码"代价、无新表/迁移。
4. `docs/PROGRESS.md`：当前状态/下一步、S3-1 勾选、变更日志（含实测块数与任务数字）、遗留问题（页码丢失、并发唯一键冲突+重试、无单笔记索引状态、重建费用随笔记量增长）。
5. `AGENTS.md` §9.2 增补一条：`services/index_service.py` 是笔记索引唯一入口；保存/重建统一走 `index.note` 任务；软删同事务删切片；重建进度靠 `async_tasks.payload.run_id` 聚合。§9.6 增补"索引服务锚点"（文件/函数清单 + `TASK_INDEX_NOTE` 常量位置及原因）。
6. `docs/AI协作开发实施计划.md` 第 14 章勾选 `[x] S3-1 索引服务产品化`。
7. `docs/spec/s3-1-index-service.md` §11 已知限制按实测补充；文末追加"实施记录（2026-10-31）"：pytest 数字、真实块数、重建 run 结果、`chunks_with_page=0` 的事实。
8. 本计划末尾"执行记录"填写：各命令实测输出摘要、提交号、偏差（无迁移）。

- [ ] **Step 9: Commit**

```bash
git add docs/API.md docs/SCHEMA.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md docs/AI协作开发实施计划.md docs/spec/s3-1-index-service.md docs/plan/s3-1-index-service.md
git commit -m "docs(s3-1): 索引服务验收记录与文档同步"
```

---

## Self-Review

**1. Spec coverage**

| Spec 要求 | 对应任务 |
|---|---|
| §4 Markdown 解析规则 1–8 | Task 1（12 条单测覆盖） |
| §5 `build_note_chunks` / `index_note` / `delete_note_chunks` / `purge_deleted_note_chunks` / `start_rebuild` / `get_rebuild_progress` | Task 2 |
| §6 `index.note` 任务与注册 | Task 3 |
| §7.1 笔记副作用（创建/正文更新/删除） | Task 4 Step 5–9 |
| §7.2 `POST /admin/index/rebuild` | Task 4 Step 1–4 |
| §7.3 `GET /admin/index/runs/{run_id}` | Task 4 Step 1–4 |
| §8 错误与边界 | Task 2 skipped/422/404 + Task 4 403/401/500/422 + Task 5 实测 |
| §10 验收 1–8 | Task 5 Step 3–7 |
| §12 文档同步 | Task 5 Step 8 |

**2. Placeholder scan**：无 TBD/TODO；所有代码步骤给出完整实现与测试；验收命令里的 `<test1 的 user_id>` 已按当前库固定为 `18`。

**3. Type consistency**：`NoteIndexResult.chunk_count` → 任务出参键 `chunks`（进度接口按 `chunks` 累加）；`TASK_INDEX_NOTE` 唯一定义在 `index_service`，task/API 均从该处导入；`RebuildStart/RebuildProgress` 在 schemas 与 service 间一致。

**已知顺序约束**：Task 2 的 `start_rebuild` 延迟导入 `task_service`（避免 `app.tasks` 包与 service 循环导入）；Task 3 必须在 Task 4 之前注册任务，否则笔记接口 `create_task` 会报"未知任务类型"。

## Execution Record

执行日期：2026-10-31。按 Task 1–5 顺序内联执行，每任务先失败测试再实现，逐任务提交。

| 任务 | 提交 | 测试 | 实测 |
|---|---|---|---|
| 1 Markdown 解析器 | `feat(s3-1): Markdown 解析器与标题路径` | `test_markdown_parse.py` 12 passed | 标题栈/代码块/表格/图片 alt/空小节均符合预期 |
| 2 索引服务 | `feat(s3-1): 索引服务与重建进度聚合` | `test_index_service.py` 11 passed | SQL 断言含 note_id+user_id、deleted_at；空库 422 |
| 3 index.note 任务 | `feat(s3-1): index.note 任务与注册` | `test_index_task.py` 4 + registry 5 passed | 任务已注册，skipped 结果透传 |
| 4 接口与副作用 | `feat(s3-1): 笔记索引副作用与管理员重建接口` | admin 8 + notes 17 passed；全量 **563 passed, 1 warning** | 仅正文 PATCH 入队；DELETE 同事务删块 |
| 5 真实验收+文档 | `docs(s3-1): 索引服务验收记录与文档同步` | 全量回归 563 passed | 见下 |

真实环境：Docker `study-agent-postgres/redis/minio` Up；uvicorn `127.0.0.1:8000` + `arq app.tasks.worker.WorkerSettings`；真实 DashScope `text-embedding-v4`（Key 已配置，未打印）。

验收数据（新建 `s31_student` id=25、`s31_admin` id=26 提升 admin）：

1. 创建 note 79 → `async_tasks` id 71 `succeeded`，`chunks=2, tokens=58`；`note_chunks` 2 行，`heading_path=函数 | 函数/单调性`。
2. PATCH 追加 `S3-1-唯一标记-20261031` → 任务 id 73 `succeeded`、2 块；`content LIKE '%唯一标记%'` = 1；总块数 2；重复分组 0。
3. 临时 note 80：删前 1 块，DELETE 204 后残留 0；软删孤儿 0。
4. 重建 run `c01a1490cd0f4abfb704f8824bb1323e`：`total_notes=5, purged_chunks=0`，轮询 `percent=100 / succeeded=5 / failed=0 / chunks=39`；表内 39 行（49→2、54→6、55→8、77→21、79→2），`page_no` 非空 0；重复分组 0。
5. 二次重建 run `a04d502f9a8b4b1284c408cd7dae251e`：同样 39 块、重复分组 0，总数不变。
6. 权限：student rebuild/progress 403、匿名 rebuild 401、坏 run_id 422、未知 run 404（`40400` 文案「索引重建记录不存在」）。
7. `scripts/ask.py --user-id 25 "S3-1 验收笔记里怎么判断函数的单调性？"`：真实检索命中笔记 #79 两个片段，回答引用 `[1] 函数/单调性`、`[2] 函数`，`refused=否`，`llm_calls=1`，退出码 0。

与计划的偏差：

1. **额外修了既有测试夹具**：`test_note_service.py` 的 FakeSession 缺 `execute`，`delete_note` 新增清切片后该文件 1 条既有用例失败；只补 `execute` + `executed` 列表，未改断言（属计划 Step 7 的连带影响，非放宽测试）。
2. **验收笔记载体**：计划示例用 `test1` 新建笔记，实际为隔离数据注册 `s31_student`（id 25）并在其名下建 note 79；`ask.py` 用 `--user-id 25`（计划原写 18），因为 18 名下没有新写笔记，用 25 才能证明手写笔记可召回。
3. **验收笔记 78**：首次用 PowerShell 双引号构造 LaTeX 时 `$` 被转义吞掉，建出的 78 内容不完整；已软删验证清理路径，正式数据用单引号 here-string 重建为 note 79。未把 78 计入证据。
4. 重建 run 的 `purged_chunks=0` 与计划示例一致（当时库内无软删残留），清理路径已由 note 78/80 的 DELETE 验收覆盖。
5. 文档提交与代码分开；`git push` 未执行（按项目约定由用户推送）。
6. **验收后清理**：删除 `s31_student`/`s31_admin`、3 篇验收笔记与 18 条任务；库回到 4 篇未删除笔记、37 块，避免把测试账号留在基线。