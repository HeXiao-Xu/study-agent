# S2-13 前端文件上传与解析状态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/files` 从占位页替换为可持久查看的文件工作台：文档拖拽/点选上传、真实上传进度、解析状态轮询、完成块数与前 3 条切片预览。

**Architecture:** 后端在现有 `files` / `note_chunks` 上增加只读列表、状态块数与切片预览接口，不改表；前端用 `FileUploader` 管理串行上传与轮询、`FileListView` 管理分页列表与切片抽屉，状态与轮询常量集中在 `views/files/constants.ts`。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2；Vue 3 + TypeScript + Element Plus + Vitest；不新增依赖。

**Spec:** `docs/spec/s2-13-files-ui.md`

## Global Constraints

- 不新增数据库迁移、不新增前后端依赖；接口变更先改 `docs/API.md`。
- `GET /files` 只返回当前登录用户自己的文件；所有查询显式 `user_id` 过滤。
- 文件页只接受 `.pdf/.docx/.md/.txt`；图片不进入此页。
- 上传队列串行；解析状态每 3000ms 轮询，单文件最多 300000ms。
- 失败重试只使用前端保留的原始 `File` 重新上传；不新增服务端重试接口。
- 不做删除、下载、完整切片分页；切片只预览前 3 条。
- 组件内保留局部错误文案；`http.ts` 的全局错误提示不重复弹。
- 测试数据明显假、结构真；外部调用全部 mock。
- 每个任务结束提交一次；Conventional Commits 带任务号；用户负责 `git push`。
- 真实联调时验收 PDF 可临时设 `PARSE_FORCE_PYMUPDF=true`，不得改生产默认。

---

## File Structure

| 文件 | 动作 | 责任 |
|---|---|---|
| `backend/app/models/file.py` | 修改 | `File.chunk_count` 只读属性 |
| `backend/app/schemas/files.py` | 修改 | `FileStatusOut.chunk_count`、`FileSummaryOut`、`ChunkPreviewOut` |
| `backend/app/services/file_service.py` | 修改 | `list_files`、`list_chunks`；只读查询与权限 |
| `backend/app/api/v1/files.py` | 修改 | `GET /files`、`GET /files/{id}/chunks` |
| `backend/tests/test_files_api.py` | 修改 | 列表/块数/切片契约测试；更新既有状态断言 |
| `docs/API.md` | 修改 | §3 新接口与轮询说明；§12 待办更新 |
| `web/src/types/files.ts` | 修改 | 文件页类型 |
| `web/src/api/files.ts` | 修改 | 上传进度、列表、状态、切片 API |
| `web/src/views/files/constants.ts` | 新建 | 类型/状态/格式化/轮询常量 |
| `web/src/views/files/constants.spec.ts` | 新建 | 格式化纯函数测试 |
| `web/src/views/files/useFileUploads.ts` | 新建 | 串行上传队列、轮询、超时、重试 |
| `web/src/views/files/useFileUploads.spec.ts` | 新建 | 队列状态机测试 |
| `web/src/components/files/FileUploader.vue` | 新建 | 拖拽/点选、队列卡片、进度与重试 |
| `web/src/components/files/FileUploader.spec.ts` | 新建 | 选择文件与队列展示 |
| `web/src/views/files/FileListView.vue` | 新建 | 文件列表、分页、历史轮询、切片抽屉 |
| `web/src/views/files/FileListView.spec.ts` | 新建 | 列表/空态/错误/分页/切片 |
| `web/src/router/index.ts` | 修改 | `/files` 指向真实页面 |

---

### Task 1: 后端文件列表、块数与切片接口

**Files:**
- Modify: `backend/app/models/file.py`
- Modify: `backend/app/schemas/files.py`
- Modify: `backend/app/services/file_service.py`
- Modify: `backend/app/api/v1/files.py`
- Modify: `backend/tests/test_files_api.py`
- Modify: `docs/API.md`

**Interfaces:**
- Consumes: `File`, `NoteChunk`, `get_file_status`, `paginate_query`, `PageParams`.
- Produces:
  - `File.chunk_count -> int`
  - `FileSummaryOut(id, filename, mime, size, parse_status, parse_progress, error_msg, chunk_count, created_at, parse_finished_at)`
  - `ChunkPreviewOut(chunk_index, content, token_count)`
  - `GET /api/v1/files?page=&page_size= -> Envelope[PageData[FileSummaryOut]]`
  - `GET /api/v1/files/{file_id}/chunks?limit=3 -> Envelope[list[ChunkPreviewOut]]`
  - `GET /api/v1/files/{file_id}/parse-status` 增加 `chunk_count`

- [ ] **Step 1: 先写失败测试**

在 `backend/tests/test_files_api.py` 的 import 中加入：

```python
from app.models.note_chunk import NoteChunk
from app.schemas.common import PageData
from app.schemas.files import FileSummaryOut
```

把 `FakeSession.__init__` 改成可注入 chunks，并增加 `scalars`：

```python
    def __init__(
        self,
        *,
        user: User | None = None,
        record: File | None = None,
        relation: int | None = None,
        chunks: list[NoteChunk] | None = None,
    ) -> None:
        self.user = user
        self.record = record
        self.relation = relation
        self.chunks = chunks or []
        self.last_statement: object | None = None
        self.added: list[object] = []
        self.commits = 0

    def scalars(self, statement: object):
        self.last_statement = statement
        return iter(self.chunks)
```

更新既有 `test_parse_status_returns_pending` 的期望，增加 `"chunk_count": 0`，并新增测试：

```python
def _chunk(index: int, *, owner_id: int = 1, source_file_id: int = 11) -> NoteChunk:
    return NoteChunk(
        note_id=1,
        user_id=owner_id,
        chunk_index=index,
        content=f"第 {index} 块",
        token_count=10,
        embedding=[0.0] * 1024,
        source_file_id=source_file_id,
    )


def test_parse_status_includes_chunk_count(client: TestClient) -> None:
    user = _user()
    record = _record(status="done")
    record.parse_result_json = {"chunks": 4}
    _wire(FakeSession(user=user, record=record))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["chunk_count"] == 4


def test_list_files_returns_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    record = _record(status="done")
    record.parse_result_json = {"chunks": 4}
    session = FakeSession(user=user, record=record)
    _wire(session)

    def fake_paginate(session_, stmt, params, *, item_model):
        return PageData(
            items=[item_model.model_validate(record)],
            total=1,
            page=params.page,
            page_size=params.page_size,
        )

    monkeypatch.setattr(file_service, "paginate_query", fake_paginate)
    resp = client.get("/api/v1/files", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert data["items"][0]["filename"] == "试卷.pdf"
    assert data["items"][0]["chunk_count"] == 4


def test_list_files_requires_token(client: TestClient) -> None:
    _wire(FakeSession())
    resp = client.get("/api/v1/files")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_chunks_returns_ordered_preview(client: TestClient) -> None:
    user = _user()
    session = FakeSession(
        user=user,
        record=_record(status="done"),
        chunks=[_chunk(0), _chunk(1)],
    )
    _wire(session)
    resp = client.get("/api/v1/files/11/chunks?limit=2", headers=_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [item["chunk_index"] for item in data] == [0, 1]
    assert data[0]["content"] == "第 0 块"
    sql = str(session.last_statement)
    assert "ORDER BY note_chunks.chunk_index" in sql
    assert "LIMIT" in sql.upper()


def test_chunks_other_user_returns_403(client: TestClient) -> None:
    user = _user(2, username="student_b")
    _wire(FakeSession(user=user, record=_record(owner_id=1), relation=None))
    resp = client.get("/api/v1/files/11/chunks", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_chunks_missing_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=None))
    resp = client.get("/api/v1/files/99/chunks", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q
```

Expected: 失败；`chunk_count` 缺字段、`GET /files` 404/405、`GET /files/11/chunks` 404。

- [ ] **Step 3: 实现模型属性与 schema**

`backend/app/models/file.py` 在 `File` 类末尾增加：

```python
    @property
    def chunk_count(self) -> int:
        """解析结果里的切片数；未完成或脏数据一律按 0 处理。"""
        raw = (self.parse_result_json or {}).get("chunks")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            return raw
        return 0
```

`backend/app/schemas/files.py` 改为：

```python
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
```

- [ ] **Step 4: 实现 service**

`backend/app/services/file_service.py` 增加 import：

```python
from app.models.note_chunk import NoteChunk
from app.schemas.common import PageData
from app.schemas.files import FileSummaryOut
from app.utils.pagination import PageParams, paginate_query
```

在 `read_image` 后增加：

```python
def list_files(
    session: Session, *, owner: User, params: PageParams
) -> PageData[FileSummaryOut]:
    """只列本人文件；固定创建时间倒序，避免深分页顺序漂移。"""
    stmt = (
        select(File)
        .where(File.user_id == owner.id)
        .order_by(File.created_at.desc(), File.id.desc())
    )
    return paginate_query(session, stmt, params, item_model=FileSummaryOut)


def list_chunks(
    session: Session, *, file_id: int, viewer: User, limit: int
) -> list[NoteChunk]:
    """切片预览复用文件权限；只查该文件产出的切片。"""
    record = get_file_status(session, file_id=file_id, viewer=viewer)
    stmt = (
        select(NoteChunk)
        .where(
            NoteChunk.source_file_id == record.id,
            NoteChunk.user_id == record.user_id,
        )
        .order_by(NoteChunk.chunk_index.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
```

- [ ] **Step 5: 实现路由**

`backend/app/api/v1/files.py` 改 import：

```python
from app.schemas.common import Envelope, PageData
from app.schemas.files import (
    ChunkPreviewOut,
    FileOut,
    FileStatusOut,
    FileSummaryOut,
    FileUploadOut,
)
from app.utils.pagination import PageParams, page_params
```

在 `upload_file` 后增加：

```python
@router.get(
    "",
    response_model=Envelope[PageData[FileSummaryOut]],
    summary="文件列表（仅本人）",
)
def list_files(
    params: PageParams = Depends(page_params),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[FileSummaryOut]]:
    page = file_service.list_files(session, owner=current_user, params=params)
    return Envelope(trace_id=get_trace_id(), data=page)
```

在 `get_parse_status` 后增加：

```python
@router.get(
    "/{file_id}/chunks",
    response_model=Envelope[list[ChunkPreviewOut]],
    summary="切片预览",
)
def list_file_chunks(
    file_id: int,
    limit: int = Query(3, ge=1, le=20, description="返回切片条数"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[list[ChunkPreviewOut]]:
    chunks = file_service.list_chunks(
        session, file_id=file_id, viewer=current_user, limit=limit
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=[ChunkPreviewOut.model_validate(chunk) for chunk in chunks],
    )
```

- [ ] **Step 6: 跑后端测试**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q
../.venv/Scripts/python.exe -m pytest -q
```

Expected: `test_files_api.py` 全绿；全套 **512 passed**（506 + 6）。

- [ ] **Step 7: 更新 API.md**

在 §3 `POST /files` 后增加 `GET /files`；在 `parse-status` 的 `data` 字段加入 `chunk_count`；在 `parse-status` 后增加 `GET /files/{id}/chunks`。关键片段：

```markdown
### GET /api/v1/files
- 权限：登录用户，仅本人文件
- 类型：同步（分页）
- 入参：`page`（默认 1）、`page_size`（默认 20，1–100）
- 排序：固定 `created_at DESC, id DESC`
- 出参：`Envelope[PageData[FileSummaryOut]]`
- FileSummaryOut：`id` / `filename` / `mime` / `size` / `parse_status` /
  `parse_progress` / `error_msg` / `chunk_count` / `created_at` / `parse_finished_at`

### GET /api/v1/files/{file_id}/chunks
- 权限：本人或已绑定该学生的 parent/teacher（admin 不绕过）
- 入参：`limit`（默认 3，1–20）
- 出参：`Envelope[ChunkPreviewOut[]]`，按 `chunk_index` 升序
- ChunkPreviewOut：`chunk_index` / `content` / `token_count`
- 未解析完成返回空数组
```

并把 §12 的文件行改成：

```markdown
| 文件 | 下载 / 删除、签名 URL 接口 | 后续（S2-13 已交付列表/解析状态/切片预览） |
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/models/file.py backend/app/schemas/files.py \
  backend/app/services/file_service.py backend/app/api/v1/files.py \
  backend/tests/test_files_api.py docs/API.md
git commit -m "feat(s2-13): 文件列表与切片预览接口"
```

---

### Task 2: 前端类型、API 与格式化常量

**Files:**
- Modify: `web/src/types/files.ts`
- Modify: `web/src/api/files.ts`
- Create: `web/src/views/files/constants.ts`
- Create: `web/src/views/files/constants.spec.ts`

**Interfaces:**
- Consumes: `http`, `ApiEnvelope`, `PageData`。
- Produces:
  - `ParseStatus`, `FileSummary`, `FileStatus`, `ChunkPreview`, `FileListParams`
  - `uploadDocument(file, onProgress?)`, `listFiles(params)`, `getFileStatus(id)`, `listFileChunks(id, limit)`
  - `ACCEPTED_EXTENSIONS`, `ACCEPT_ATTR`, `POLL_INTERVAL_MS`, `POLL_TIMEOUT_MS`
  - `extensionOf`, `isAcceptedFile`, `formatFileSize`, `formatFileType`, `formatDateTime`, `STATUS_LABELS`

- [ ] **Step 1: 写失败测试**

`web/src/views/files/constants.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import {
  extensionOf,
  formatFileSize,
  formatFileType,
  isAcceptedFile,
} from '@/views/files/constants'

describe('file constants', () => {
  it('extracts lower-case extension', () => {
    expect(extensionOf('试卷.PDF')).toBe('pdf')
    expect(extensionOf('noext')).toBe('')
  })

  it('accepts only parseable documents', () => {
    expect(isAcceptedFile('试卷.pdf')).toBe(true)
    expect(isAcceptedFile('笔记.MD')).toBe(true)
    expect(isAcceptedFile('图.png')).toBe(false)
  })

  it('formats byte sizes', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1024)).toBe('1.0 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1024 * 1024)).toBe('1.0 MB')
  })

  it('maps file type labels', () => {
    expect(formatFileType('试卷.pdf', 'application/pdf')).toBe('PDF')
    expect(formatFileType('笔记.md', 'text/markdown')).toBe('Markdown')
    expect(formatFileType('试卷.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')).toBe('Word')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/files/constants.spec.ts
```

Expected: 失败（模块不存在）。

- [ ] **Step 3: 改类型**

`web/src/types/files.ts`：

```ts
export type ParseStatus = 'pending' | 'parsing' | 'done' | 'failed'

export interface FileUploadOut {
  id: number
  filename: string
  mime: string
  size: number
  sha256: string
  parse_status: ParseStatus
  created_at: string
  deduped: boolean
}

export interface FileSummary {
  id: number
  filename: string
  mime: string
  size: number
  parse_status: ParseStatus
  parse_progress: number
  error_msg: string | null
  chunk_count: number
  created_at: string
  parse_finished_at: string | null
}

export interface FileStatus {
  id: number
  filename: string
  parse_status: ParseStatus
  parse_progress: number
  error_msg: string | null
  chunk_count: number
}

export interface ChunkPreview {
  chunk_index: number
  content: string
  token_count: number
}

export interface FileListParams {
  page: number
  page_size: number
}
```

- [ ] **Step 4: 改 API**

`web/src/api/files.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  ChunkPreview,
  FileListParams,
  FileStatus,
  FileSummary,
  FileUploadOut,
} from '@/types/files'

export async function uploadImage(file: File): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'false' },
    timeout: 60_000,
  })
  return resp.data.data
}

export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'true' },
    timeout: 300_000,
    onUploadProgress: (event) => {
      if (event.total && event.total > 0) {
        onProgress?.(Math.round((event.loaded * 100) / event.total))
      }
    },
  })
  return resp.data.data
}

export async function listFiles(params: FileListParams): Promise<PageData<FileSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<FileSummary>>>(`${API_PREFIX}/files`, {
    params,
  })
  return resp.data.data
}

export async function getFileStatus(id: number): Promise<FileStatus> {
  const resp = await http.get<ApiEnvelope<FileStatus>>(
    `${API_PREFIX}/files/${id}/parse-status`,
  )
  return resp.data.data
}

export async function listFileChunks(id: number, limit = 3): Promise<ChunkPreview[]> {
  const resp = await http.get<ApiEnvelope<ChunkPreview[]>>(
    `${API_PREFIX}/files/${id}/chunks`,
    { params: { limit } },
  )
  return resp.data.data
}

export async function getImageBlob(id: number): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/files/${id}/image`, {
    responseType: 'blob',
    timeout: 30_000,
  })
  return resp.data
}
```

- [ ] **Step 5: 写常量文件**

`web/src/views/files/constants.ts`：

```ts
import type { ParseStatus } from '@/types/files'

export const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'md', 'txt'] as const
export const ACCEPT_ATTR = '.pdf,.docx,.md,.txt'
export const POLL_INTERVAL_MS = 3_000
export const POLL_TIMEOUT_MS = 5 * 60 * 1_000
export const PAGE_SIZES = [10, 20, 50]

export const STATUS_LABELS: Record<ParseStatus, string> = {
  pending: '待解析',
  parsing: '解析中',
  done: '已完成',
  failed: '失败',
}

export function extensionOf(filename: string): string {
  const index = filename.lastIndexOf('.')
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : ''
}

export function isAcceptedFile(filename: string): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(filename))
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`
}

export function formatFileType(filename: string, mime: string): string {
  const ext = extensionOf(filename)
  if (ext === 'pdf') return 'PDF'
  if (ext === 'docx') return 'Word'
  if (ext === 'md') return 'Markdown'
  if (ext === 'txt') return 'TXT'
  return mime || ext.toUpperCase() || '文件'
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}
```

- [ ] **Step 6: 跑测试与类型检查**

```bash
cd web
npm run test:run -- src/views/files/constants.spec.ts
npm run build
```

Expected: 4 tests 通过；build 通过。

- [ ] **Step 7: 提交**

```bash
git add web/src/types/files.ts web/src/api/files.ts \
  web/src/views/files/constants.ts web/src/views/files/constants.spec.ts
git commit -m "feat(s2-13): 文件 API 与格式化常量"
```

---

### Task 3: 上传队列 composable（串行、轮询、超时、重试）

**Files:**
- Create: `web/src/views/files/useFileUploads.ts`
- Create: `web/src/views/files/useFileUploads.spec.ts`

**Interfaces:**
- Consumes: `uploadDocument`, `getFileStatus`, constants。
- Produces:
  - `UploadPhase = 'waiting'|'uploading'|'pending'|'parsing'|'done'|'failed'|'timeout'`
  - `UploadTask`（字段见下）
  - `useFileUploads(options?: { onFinished?: (task: UploadTask) => void })`
  - 返回 `{ tasks, enqueue, retry, clearFinished, dispose }`

- [ ] **Step 1: 写失败测试**

`web/src/views/files/useFileUploads.spec.ts`：

```ts
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getFileStatus, uploadDocument } from '@/api/files'
import { useFileUploads } from '@/views/files/useFileUploads'

vi.mock('@/api/files', () => ({
  uploadDocument: vi.fn(),
  getFileStatus: vi.fn(),
}))

const record = {
  id: 11,
  filename: '试卷.pdf',
  mime: 'application/pdf',
  size: 100,
  sha256: 'x',
  parse_status: 'pending' as const,
  created_at: '2026-10-29T12:00:00+00:00',
  deduped: false,
}

const pending = {
  id: 11,
  filename: '试卷.pdf',
  parse_status: 'pending' as const,
  parse_progress: 0,
  error_msg: null,
  chunk_count: 0,
}

const done = {
  ...pending,
  parse_status: 'done' as const,
  parse_progress: 100,
  chunk_count: 3,
}

function pdf(name = '试卷.pdf'): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

describe('useFileUploads', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(uploadDocument).mockReset()
    vi.mocked(getFileStatus).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('rejects unsupported files before uploading', () => {
    const uploads = useFileUploads()
    const rejected = uploads.enqueue([new File(['png'], '图.png', { type: 'image/png' })])
    expect(rejected).toHaveLength(1)
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it('reports upload progress before status polling', async () => {
    let resolveUpload: (value: typeof record) => void = () => undefined
    vi.mocked(uploadDocument).mockImplementation((_file, onProgress) => {
      onProgress?.(42)
      return new Promise((resolve) => {
        resolveUpload = resolve
      })
    })
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    expect(uploads.tasks.value[0].progress).toBe(42)
    expect(uploads.tasks.value[0].phase).toBe('uploading')
    resolveUpload(record)
    vi.mocked(getFileStatus).mockResolvedValue(pending)
    await flushPromises()
  })

  it('polls until done and emits the finished task', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValueOnce(pending).mockResolvedValueOnce(done)
    const onFinished = vi.fn()
    const uploads = useFileUploads({ onFinished })
    uploads.enqueue([pdf()])
    await flushPromises()
    expect(getFileStatus).toHaveBeenCalledWith(11)
    expect(uploads.tasks.value[0].phase).toBe('pending')
    vi.advanceTimersByTime(3_000)
    await flushPromises()
    expect(uploads.tasks.value[0].phase).toBe('done')
    expect(uploads.tasks.value[0].chunkCount).toBe(3)
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('shows failed status and retries with the same file', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValueOnce({
      ...pending,
      parse_status: 'failed',
      error_msg: 'RuntimeError: bad pdf',
    })
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    const task = uploads.tasks.value[0]
    expect(task.phase).toBe('failed')
    expect(task.error).toBe('RuntimeError: bad pdf')
    uploads.retry(task.uid)
    await flushPromises()
    expect(uploadDocument).toHaveBeenCalledTimes(2)
  })

  it('times out polling after five minutes', async () => {
    vi.mocked(uploadDocument).mockResolvedValue(record)
    vi.mocked(getFileStatus).mockResolvedValue(pending)
    const uploads = useFileUploads()
    uploads.enqueue([pdf()])
    await flushPromises()
    vi.setSystemTime(Date.now() + 300_001)
    vi.advanceTimersByTime(3_000)
    await flushPromises()
    expect(uploads.tasks.value[0].phase).toBe('timeout')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/files/useFileUploads.spec.ts
```

Expected: 失败（模块不存在）。

- [ ] **Step 3: 实现 composable**

`web/src/views/files/useFileUploads.ts`：

```ts
import axios from 'axios'
import { ref } from 'vue'

import { getFileStatus, uploadDocument } from '@/api/files'
import type { FileStatus, ParseStatus } from '@/types/files'
import {
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  isAcceptedFile,
} from '@/views/files/constants'

export type UploadPhase =
  | 'waiting'
  | 'uploading'
  | 'pending'
  | 'parsing'
  | 'done'
  | 'failed'
  | 'timeout'

export interface UploadTask {
  uid: string
  file: File
  name: string
  size: number
  progress: number
  phase: UploadPhase
  statusText: string
  error: string
  recordId: number | null
  chunkCount: number
  startedAt: number
  notified: boolean
}

interface UseFileUploadsOptions {
  onFinished?: (task: UploadTask) => void
}

let sequence = 0

function isActive(status: ParseStatus): boolean {
  return status === 'pending' || status === 'parsing'
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as { message?: string } | undefined
    return payload?.message ?? '上传失败，请重试'
  }
  if (error instanceof Error && error.message) return error.message
  return '上传失败，请重试'
}

export function useFileUploads(options: UseFileUploadsOptions = {}) {
  const tasks = ref<UploadTask[]>([])
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  let running = false

  function makeTask(file: File): UploadTask {
    sequence += 1
    return {
      uid: `${Date.now()}-${sequence}`,
      file,
      name: file.name,
      size: file.size,
      progress: 0,
      phase: 'waiting',
      statusText: '等待上传',
      error: '',
      recordId: null,
      chunkCount: 0,
      startedAt: 0,
      notified: false,
    }
  }

  function stopPolling(uid: string): void {
    const timer = timers.get(uid)
    if (timer) clearTimeout(timer)
    timers.delete(uid)
  }

  function notify(task: UploadTask): void {
    if (task.notified) return
    task.notified = true
    options.onFinished?.(task)
  }

  function applyStatus(task: UploadTask, status: FileStatus): void {
    task.progress = status.parse_progress
    task.chunkCount = status.chunk_count
    task.error = status.error_msg ?? ''
    if (status.parse_status === 'done') {
      task.phase = 'done'
      task.progress = 100
      task.statusText = `完成 · ${status.chunk_count} 块`
      stopPolling(task.uid)
      notify(task)
      return
    }
    if (status.parse_status === 'failed') {
      task.phase = 'failed'
      task.statusText = '解析失败'
      stopPolling(task.uid)
      notify(task)
      return
    }
    task.phase = status.parse_status
    task.statusText =
      status.parse_status === 'pending'
        ? '排队中'
        : `解析中 ${status.parse_progress}%`
  }

  function timeoutTask(task: UploadTask): void {
    if (task.phase === 'done' || task.phase === 'failed') return
    task.phase = 'timeout'
    task.statusText = '解析超时，请刷新查看'
    stopPolling(task.uid)
    notify(task)
  }

  function startPolling(task: UploadTask): void {
    if (timers.has(task.uid) || task.recordId === null) return
    const tick = async (): Promise<void> => {
      if (!isActive(task.phase as ParseStatus)) return
      if (Date.now() - task.startedAt >= POLL_TIMEOUT_MS) {
        timeoutTask(task)
        return
      }
      try {
        applyStatus(task, await getFileStatus(task.recordId as number))
      } catch {
        // 单次轮询失败不终止；下一轮继续，直到终态或超时
      }
      if (isActive(task.phase as ParseStatus)) {
        timers.set(task.uid, setTimeout(tick, POLL_INTERVAL_MS))
      }
    }
    timers.set(task.uid, setTimeout(tick, POLL_INTERVAL_MS))
  }

  async function startTask(task: UploadTask): Promise<void> {
    task.phase = 'uploading'
    task.statusText = '上传中'
    task.progress = 0
    task.error = ''
    task.notified = false
    try {
      const record = await uploadDocument(task.file, (percent) => {
        task.progress = percent
        task.statusText = `上传中 ${percent}%`
      })
      task.recordId = record.id
      task.startedAt = Date.now()
      try {
        const status = await getFileStatus(record.id)
        applyStatus(task, status)
        if (isActive(status.parse_status)) startPolling(task)
      } catch {
        task.phase = 'pending'
        task.statusText = '待解析'
        startPolling(task)
      }
    } catch (error) {
      task.phase = 'failed'
      task.statusText = '上传失败'
      task.error = errorMessage(error)
      notify(task)
    }
  }

  async function drain(): Promise<void> {
    if (running) return
    running = true
    try {
      let next = tasks.value.find((task) => task.phase === 'waiting')
      while (next) {
        await startTask(next)
        next = tasks.value.find((task) => task.phase === 'waiting')
      }
    } finally {
      running = false
    }
  }

  function enqueue(files: File[]): string[] {
    const rejected: string[] = []
    for (const file of files) {
      if (!isAcceptedFile(file.name)) {
        rejected.push(`${file.name}：仅支持 PDF / Word / Markdown / TXT`)
        continue
      }
      tasks.value.push(makeTask(file))
    }
    if (tasks.value.some((task) => task.phase === 'waiting')) void drain()
    return rejected
  }

  function retry(uid: string): void {
    const task = tasks.value.find((item) => item.uid === uid)
    if (!task) return
    stopPolling(uid)
    task.phase = 'waiting'
    task.progress = 0
    task.statusText = '等待上传'
    task.error = ''
    task.recordId = null
    task.chunkCount = 0
    task.startedAt = 0
    task.notified = false
    void drain()
  }

  function clearFinished(): void {
    tasks.value = tasks.value.filter(
      (task) => !['done', 'failed', 'timeout'].includes(task.phase),
    )
  }

  function dispose(): void {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
  }

  return { tasks, enqueue, retry, clearFinished, dispose }
}
```

- [ ] **Step 4: 跑测试**

```bash
cd web
npm run test:run -- src/views/files/useFileUploads.spec.ts
```

Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add web/src/views/files/useFileUploads.ts web/src/views/files/useFileUploads.spec.ts
git commit -m "feat(s2-13): 文件上传队列与解析轮询"
```

---

### Task 4: FileUploader 组件

**Files:**
- Create: `web/src/components/files/FileUploader.vue`
- Create: `web/src/components/files/FileUploader.spec.ts`

**Interfaces:**
- Consumes: `useFileUploads`、constants、Element Plus `ElMessage`。
- Produces:
  - `FileUploader` 组件；`emit('finished', task: UploadTask)`。
  - 对外暴露：拖拽区、隐藏 `input[type=file][data-testid=file-input]`、队列项 `[data-testid=upload-task-<uid>]`、`重试`/`清空已完成`。

- [ ] **Step 1: 写失败测试**

`web/src/components/files/FileUploader.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import FileUploader from './FileUploader.vue'
import { uploadDocument } from '@/api/files'

vi.mock('@/api/files', () => ({
  uploadDocument: vi.fn(),
  getFileStatus: vi.fn(),
}))

function makeFile(name = '试卷.pdf'): File {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

async function selectFiles(wrapper: ReturnType<typeof mount>, files: File[]) {
  const input = wrapper.find('[data-testid="file-input"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  await input.trigger('change')
  await flushPromises()
}

describe('FileUploader', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(uploadDocument).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('enqueues selected documents and shows the file name', async () => {
    vi.mocked(uploadDocument).mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(FileUploader, { global: { plugins: [ElementPlus] } })
    await selectFiles(wrapper, [makeFile()])
    expect(wrapper.text()).toContain('试卷.pdf')
    expect(uploadDocument).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('renders a queue item and clears finished items', async () => {
    vi.mocked(uploadDocument).mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(FileUploader, { global: { plugins: [ElementPlus] } })
    await selectFiles(wrapper, [makeFile('讲义.md')])
    expect(wrapper.find('[data-testid^="upload-task-"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('讲义.md')
    wrapper.unmount()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/components/files/FileUploader.spec.ts
```

Expected: 失败（组件不存在）。

- [ ] **Step 3: 写组件**

`web/src/components/files/FileUploader.vue`：

```vue
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import type { UploadTask } from '@/views/files/useFileUploads'
import { useFileUploads } from '@/views/files/useFileUploads'
import {
  ACCEPT_ATTR,
  formatFileSize,
} from '@/views/files/constants'

const emit = defineEmits<{ finished: [task: UploadTask] }>()
const inputRef = ref<HTMLInputElement>()
const dragging = ref(false)
const { tasks, enqueue, retry, clearFinished, dispose } = useFileUploads({
  onFinished: (task) => {
    emit('finished', task)
    if (task.phase === 'done') ElMessage.success(`${task.name} 解析完成`)
  },
})

const hasFinished = computed(() =>
  tasks.value.some((task) => ['done', 'failed', 'timeout'].includes(task.phase)),
)

function addFiles(list: FileList | null): void {
  if (!list || !list.length) return
  const rejected = enqueue(Array.from(list))
  if (rejected.length) ElMessage.warning(rejected.join('；'))
}

function onInputChange(event: Event): void {
  const input = event.target as HTMLInputElement
  addFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  addFiles(event.dataTransfer?.files ?? null)
}

function pickFile(): void {
  inputRef.value?.click()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    pickFile()
  }
}

function progressStatus(task: UploadTask): '' | 'success' | 'exception' {
  if (task.phase === 'done') return 'success'
  if (task.phase === 'failed' || task.phase === 'timeout') return 'exception'
  return ''
}

onUnmounted(dispose)
</script>

<template>
  <section class="file-uploader" aria-label="上传文件">
    <div
      class="dropzone"
      :class="{ dragging }"
      role="button"
      tabindex="0"
      data-testid="file-dropzone"
      @click="pickFile"
      @keydown="onKeydown"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="inputRef"
        class="file-input"
        type="file"
        multiple
        :accept="ACCEPT_ATTR"
        data-testid="file-input"
        @change="onInputChange"
      />
      <div class="drop-mark" aria-hidden="true">↑</div>
      <div class="drop-title">拖拽文件到这里，或点击选择</div>
      <p class="drop-hint">支持 PDF / Word / Markdown / TXT，单个文件不超过 60MB</p>
    </div>

    <div v-if="tasks.length" class="upload-queue" aria-live="polite">
      <div class="queue-head">
        <span>上传队列</span>
        <el-button v-if="hasFinished" link type="primary" @click="clearFinished">
          清空已完成
        </el-button>
      </div>
      <div
        v-for="task in tasks"
        :key="task.uid"
        class="queue-item"
        :data-testid="`upload-task-${task.uid}`"
      >
        <div class="queue-top">
          <span class="queue-name" :title="task.name">{{ task.name }}</span>
          <span class="queue-size">{{ formatFileSize(task.size) }}</span>
        </div>
        <el-progress
          :percentage="task.progress"
          :status="progressStatus(task)"
          :stroke-width="6"
          :show-text="false"
        />
        <div class="queue-bottom">
          <span class="queue-status">{{ task.statusText }}</span>
          <el-button
            v-if="task.phase === 'failed' && task.file"
            link
            type="primary"
            @click="retry(task.uid)"
          >
            重试
          </el-button>
        </div>
        <p v-if="task.error" class="queue-error">{{ task.error }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.file-uploader {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}

.dropzone {
  position: relative;
  padding: 28px 24px;
  text-align: center;
  cursor: pointer;
  background: var(--app-surface);
  border: 1px dashed #c7d0e0;
  border-radius: var(--app-radius-md);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.dropzone:hover,
.dropzone.dragging {
  background: var(--app-primary-soft);
  border-color: var(--app-primary);
}

.file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.drop-mark {
  display: grid;
  width: 36px;
  height: 36px;
  margin: 0 auto 10px;
  place-items: center;
  color: var(--app-primary);
  font-size: 20px;
  background: var(--app-primary-soft);
  border-radius: 50%;
}

.drop-title {
  color: var(--app-text);
  font-size: 14px;
  font-weight: 500;
}

.drop-hint {
  margin: 6px 0 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.upload-queue {
  padding: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.queue-item {
  padding: 12px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.queue-item:first-of-type {
  border-top: none;
}

.queue-top,
.queue-bottom {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.queue-top {
  margin-bottom: 8px;
}

.queue-name {
  overflow: hidden;
  color: var(--app-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-size {
  flex-shrink: 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.queue-bottom {
  margin-top: 6px;
}

.queue-status {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.queue-error {
  margin: 6px 0 0;
  color: var(--app-danger);
  font-size: 12px;
  word-break: break-word;
}
</style>
```

- [ ] **Step 4: 跑测试**

```bash
cd web
npm run test:run -- src/components/files/FileUploader.spec.ts
```

Expected: 2 passed。

- [ ] **Step 5: 提交**

```bash
git add web/src/components/files/FileUploader.vue web/src/components/files/FileUploader.spec.ts
git commit -m "feat(s2-13): 文件拖拽上传组件"
```

---

### Task 5: FileListView、路由与列表/切片测试

**Files:**
- Create: `web/src/views/files/FileListView.vue`
- Create: `web/src/views/files/FileListView.spec.ts`
- Modify: `web/src/router/index.ts`

**Interfaces:**
- Consumes: `listFiles`、`getFileStatus`、`listFileChunks`、`FileUploader`、`PageHeader`、`EmptyState`、constants。
- Produces: `/files` 真实页面，`meta.nav='files'`，`roles=['student']`。

- [ ] **Step 1: 写失败测试**

`web/src/views/files/FileListView.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FileListView from './FileListView.vue'
import { listFileChunks, listFiles } from '@/api/files'

vi.mock('@/api/files', () => ({
  listFiles: vi.fn(),
  getFileStatus: vi.fn(),
  listFileChunks: vi.fn(),
}))

const row = {
  id: 11,
  filename: '试卷.pdf',
  mime: 'application/pdf',
  size: 2048,
  parse_status: 'done' as const,
  parse_progress: 100,
  error_msg: null,
  chunk_count: 3,
  created_at: '2026-10-29T12:00:00+00:00',
  parse_finished_at: '2026-10-29T12:01:00+00:00',
}

function mountPage() {
  return mount(FileListView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        FileUploader: { template: '<div data-testid="uploader" />' },
        teleport: true,
      },
    },
  })
}

describe('FileListView', () => {
  beforeEach(() => {
    vi.mocked(listFiles).mockReset()
    vi.mocked(listFileChunks).mockReset()
  })

  it('renders files with size, status and chunk count', async () => {
    vi.mocked(listFiles).mockResolvedValue({
      items: [row],
      total: 1,
      page: 1,
      page_size: 10,
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('试卷.pdf')
    expect(wrapper.text()).toContain('PDF · 2.0 KB')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('3 块')
  })

  it('shows the empty state when there are no files', async () => {
    vi.mocked(listFiles).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有文件')
  })

  it('shows an error and retries loading', async () => {
    vi.mocked(listFiles).mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('文件列表加载失败')
    await wrapper.find('[data-testid="retry-list"]').trigger('click')
    await flushPromises()
    expect(listFiles).toHaveBeenCalledTimes(2)
  })

  it('requests the next page', async () => {
    vi.mocked(listFiles).mockResolvedValue({ items: [row], total: 20, page: 1, page_size: 10 })
    const wrapper = mountPage()
    await flushPromises()
    wrapper.findComponent({ name: 'ElPagination' }).vm.$emit('current-change', 2)
    await flushPromises()
    expect(listFiles).toHaveBeenLastCalledWith({ page: 2, page_size: 10 })
  })

  it('opens the chunk drawer with the first three chunks', async () => {
    vi.mocked(listFiles).mockResolvedValue({ items: [row], total: 1, page: 1, page_size: 10 })
    vi.mocked(listFileChunks).mockResolvedValue([
      { chunk_index: 0, content: '第一块', token_count: 10 },
      { chunk_index: 1, content: '第二块', token_count: 11 },
      { chunk_index: 2, content: '第三块', token_count: 12 },
    ])
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="preview-chunks"]').trigger('click')
    await flushPromises()
    expect(listFileChunks).toHaveBeenCalledWith(11, 3)
    expect(wrapper.text()).toContain('第一块')
    expect(wrapper.text()).toContain('第三块')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- src/views/files/FileListView.spec.ts
```

Expected: 失败（页面不存在）。

- [ ] **Step 3: 实现页面**

`web/src/views/files/FileListView.vue`：

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { getFileStatus, listFileChunks, listFiles } from '@/api/files'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import FileUploader from '@/components/files/FileUploader.vue'
import type { ChunkPreview, FileSummary, ParseStatus } from '@/types/files'
import {
  PAGE_SIZES,
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  STATUS_LABELS,
  formatDateTime,
  formatFileSize,
  formatFileType,
} from '@/views/files/constants'

const items = ref<FileSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const error = ref('')

const previewOpen = ref(false)
const previewFile = ref<FileSummary | null>(null)
const chunks = ref<ChunkPreview[]>([])
const chunksLoading = ref(false)
const chunksError = ref('')

let rowTimer: ReturnType<typeof setInterval> | undefined
let rowPollStartedAt = 0

function isActive(status: ParseStatus): boolean {
  return status === 'pending' || status === 'parsing'
}

function stopRowPolling(): void {
  if (rowTimer) clearInterval(rowTimer)
  rowTimer = undefined
}

function startRowPolling(): void {
  stopRowPolling()
  if (!items.value.some((item) => isActive(item.parse_status))) return
  rowPollStartedAt = Date.now()
  rowTimer = setInterval(() => {
    void pollActiveRows()
  }, POLL_INTERVAL_MS)
}

async function pollActiveRows(): Promise<void> {
  const active = items.value.filter((item) => isActive(item.parse_status))
  if (!active.length) {
    stopRowPolling()
    return
  }
  if (Date.now() - rowPollStartedAt >= POLL_TIMEOUT_MS) {
    stopRowPolling()
    return
  }
  const statuses = await Promise.all(
    active.map(async (item) => {
      try {
        return await getFileStatus(item.id)
      } catch {
        return null
      }
    }),
  )
  for (const status of statuses) {
    if (!status) continue
    const item = items.value.find((entry) => entry.id === status.id)
    if (!item) continue
    item.parse_status = status.parse_status
    item.parse_progress = status.parse_progress
    item.error_msg = status.error_msg
    item.chunk_count = status.chunk_count
  }
  if (!items.value.some((item) => isActive(item.parse_status))) stopRowPolling()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listFiles({ page: page.value, page_size: pageSize.value })
    items.value = result.items
    total.value = result.total
    startRowPolling()
  } catch {
    error.value = '文件列表加载失败，请重试'
    stopRowPolling()
  } finally {
    loading.value = false
  }
}

async function onPageChange(next: number): Promise<void> {
  page.value = next
  await load()
}

async function onSizeChange(size: number): Promise<void> {
  pageSize.value = size
  page.value = 1
  await load()
}

async function onUploadFinished(): Promise<void> {
  await load()
}

function statusType(status: ParseStatus): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'done') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'parsing') return 'warning'
  return 'info'
}

function statusText(row: FileSummary): string {
  if (row.parse_status === 'parsing') {
    return `${STATUS_LABELS.parsing} ${row.parse_progress}%`
  }
  return STATUS_LABELS[row.parse_status]
}

async function loadChunks(): Promise<void> {
  if (!previewFile.value) return
  chunksLoading.value = true
  chunksError.value = ''
  try {
    chunks.value = await listFileChunks(previewFile.value.id, 3)
  } catch {
    chunksError.value = '切片加载失败，请重试'
  } finally {
    chunksLoading.value = false
  }
}

async function openPreview(row: FileSummary): Promise<void> {
  if (row.parse_status !== 'done') return
  previewFile.value = row
  previewOpen.value = true
  chunks.value = []
  await loadChunks()
}

function resetPreview(): void {
  previewFile.value = null
  chunks.value = []
  chunksError.value = ''
}

function scrollToUploader(): void {
  document.querySelector('.file-uploader')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const previewTitle = computed(() => previewFile.value?.filename ?? '切片预览')

onMounted(load)
onUnmounted(stopRowPolling)
</script>

<template>
  <div class="files-page">
    <PageHeader title="文件" description="上传 PDF、Word、Markdown、TXT，系统自动解析并切片。" />

    <FileUploader @finished="onUploadFinished" />

    <div v-if="error" class="error-bar" role="alert">
      {{ error }}
      <el-button data-testid="retry-list" link type="primary" @click="load">重试</el-button>
    </div>

    <el-table v-if="items.length || loading" v-loading="loading" :data="items" class="files-table">
      <el-table-column label="文件名" min-width="280">
        <template #default="{ row }">
          <span class="row-name" :title="row.filename">{{ row.filename }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型 / 大小" width="180">
        <template #default="{ row }">
          {{ formatFileType(row.filename, row.mime) }} · {{ formatFileSize(row.size) }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="190">
        <template #default="{ row }">
          <el-tag :type="statusType(row.parse_status)" size="small" effect="plain">
            {{ statusText(row) }}
          </el-tag>
          <el-progress
            v-if="row.parse_status === 'parsing'"
            class="row-progress"
            :percentage="row.parse_progress"
            :stroke-width="4"
            :show-text="false"
          />
        </template>
      </el-table-column>
      <el-table-column label="切片数" width="110">
        <template #default="{ row }">
          {{ row.parse_status === 'done' ? `${row.chunk_count} 块` : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130" align="right">
        <template #default="{ row }">
          <el-button
            v-if="row.parse_status === 'done'"
            data-testid="preview-chunks"
            link
            type="primary"
            @click="openPreview(row)"
          >
            切片预览
          </el-button>
          <el-tooltip v-else-if="row.parse_status === 'failed'" :content="row.error_msg ?? '解析失败'">
            <span class="failed-hint">查看错误</span>
          </el-tooltip>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState v-else-if="!loading && !error" title="还没有文件" description="上传第一份资料，系统会自动切片并建立索引。">
      <template #actions>
        <el-button type="primary" @click="scrollToUploader">上传第一份资料</el-button>
      </template>
    </EmptyState>

    <div v-if="total > 0" class="pager">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="PAGE_SIZES"
        :total="total"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <el-drawer v-model="previewOpen" :title="previewTitle" size="520px" @closed="resetPreview">
      <div v-if="chunksLoading" v-loading="true" class="chunk-loading" />
      <div v-else-if="chunksError" class="chunk-error">
        {{ chunksError }}
        <el-button link type="primary" @click="loadChunks">重试</el-button>
      </div>
      <EmptyState
        v-else-if="!chunks.length"
        title="没有可预览的切片"
        description="该文件尚未产生切片，或解析结果为空。"
      />
      <div v-else class="chunk-list">
        <article v-for="chunk in chunks" :key="chunk.chunk_index" class="chunk-item">
          <header class="chunk-head">
            <span>#{{ chunk.chunk_index + 1 }}</span>
            <span>{{ chunk.token_count }} tokens</span>
          </header>
          <pre class="chunk-content">{{ chunk.content }}</pre>
        </article>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.files-page {
  min-width: 0;
}

.error-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 16px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.files-table {
  width: 100%;
}

.row-name {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-progress {
  width: 120px;
  margin-top: 6px;
}

.failed-hint {
  color: var(--app-danger);
  font-size: 12px;
  cursor: help;
}

.muted {
  color: var(--app-text-tertiary);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.chunk-loading {
  min-height: 160px;
}

.chunk-error {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--app-danger);
  font-size: 13px;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chunk-item {
  padding: 12px;
  background: #f8f9fb;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.chunk-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.chunk-content {
  max-height: 220px;
  margin: 0;
  overflow: auto;
  color: var(--app-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
```

- [ ] **Step 4: 改路由**

`web/src/router/index.ts` 把 `/files` 的占位组件替换为：

```ts
        {
          path: 'files',
          name: 'files',
          component: () => import('@/views/files/FileListView.vue'),
          meta: { title: '文件', nav: 'files', roles: ['student'] },
        },
```

- [ ] **Step 5: 跑测试与构建**

```bash
cd web
npm run test:run -- src/views/files/FileListView.spec.ts
npm run test:run
npm run build
```

Expected: FileListView 5 passed；全套 **55 passed**（既有 39 + 新增 16）；build 通过。

- [ ] **Step 6: 提交**

```bash
git add web/src/views/files/FileListView.vue web/src/views/files/FileListView.spec.ts \
  web/src/router/index.ts
git commit -m "feat(s2-13): 文件列表与切片预览页"
```

---

### Task 6: 真实联调、文档同步与最终验证

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s2-13-files-ui.md`
- Modify: `docs/plan/s2-13-files-ui.md`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: 可复核的实测记录、清理结果、最终提交。

- [ ] **Step 1: 跑全量自动测试**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
```

Expected: 后端全绿；前端全绿；build 通过。记录真实数字。

- [ ] **Step 2: 生成验收 PDF**

用一个含 3 道题的 PDF，避免中文默认字体缺字；例如用 PyMuPDF 生成 ASCII 数学题：

```bash
cd /e/BiShe-AIStudy/study-agent
./.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
import fitz

out = Path("web/.tmp-s213-paper.pdf")
doc = fitz.open()
page = doc.new_page()
lines = [
    "S2-13 acceptance paper",
    "1. Solve x^2 - 5x + 6 = 0.",
    "2. Find the derivative of f(x)=x^3+2x.",
    "3. Evaluate the integral of x^2 from 0 to 1.",
]
y = 72
for line in lines:
    page.insert_text((72, y), line, fontsize=12)
    y += 28
doc.save(out)
doc.close()
print(out, out.stat().st_size)
PY
```

- [ ] **Step 3: 起真实环境**

终端 A（后端，验收用快速 PDF 解析）：

```bash
cd /e/BiShe-AIStudy/study-agent/backend
PARSE_FORCE_PYMUPDF=true ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
```

终端 B（Worker，同样环境）：

```bash
cd /e/BiShe-AIStudy/study-agent/backend
PARSE_FORCE_PYMUPDF=true ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
```

终端 C：

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run dev -- --host 127.0.0.1 --port 5173
```

真实浏览器打开 `http://localhost:5173/login`，注册一次性学生账号 `s213_e2e_*`。

- [ ] **Step 4: 走真实流程**

1. 进入 `/files`。
2. 通过文件输入选择 `.tmp-s213-paper.pdf`（拖拽区也走同一 `addFiles`；真实浏览器用文件选择即可）。
3. 观察上传进度 → 解析中 → 完成。
4. 断言：页面出现文件名、`完成`、`N 块`，N > 0。
5. 刷新页面，文件仍在列表，状态仍为完成，块数不变。
6. 点「切片预览」，抽屉出现 `#1 / #2 / #3` 和前 3 条文本。
7. 再选一个 `.png`，确认前端拒绝，不发请求。
8. 记录 console error、横向滚动（`scrollWidth === innerWidth`）。
9. 截图到 `web/.tmp-screens-s213/`（不入库，收尾删除）。

- [ ] **Step 5: 数据库/存储证据**

```bash
cd /e/BiShe-AIStudy/study-agent
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "SELECT id,user_id,filename,parse_status,parse_progress,parse_result_json->>'chunks' AS chunks FROM files WHERE filename LIKE '%s213%' OR id=(SELECT max(id) FROM files);"
```

Expected: 一行 `done`、`100`、`chunks=N`；再查 `note_chunks` 数量与 `parse_result_json.chunks` 一致。

- [ ] **Step 6: 清理**

按依赖顺序删除该用户的数据与 MinIO 对象：

```bash
cd /e/BiShe-AIStudy/study-agent
USER_ID=$(docker exec study-agent-postgres psql -U study -d study_agent -tAc \
  "SELECT id FROM users WHERE username LIKE 's213_e2e_%' ORDER BY id DESC LIMIT 1")
docker exec study-agent-postgres psql -U study -d study_agent \
  -c "DELETE FROM note_kps WHERE note_id IN (SELECT id FROM notes WHERE user_id = ${USER_ID});" \
  -c "DELETE FROM note_chunks WHERE user_id = ${USER_ID};" \
  -c "DELETE FROM notes WHERE user_id = ${USER_ID};" \
  -c "DELETE FROM async_tasks WHERE user_id = ${USER_ID};" \
  -c "DELETE FROM files WHERE user_id = ${USER_ID};" \
  -c "DELETE FROM user_relations WHERE student_id = ${USER_ID} OR teacher_id = ${USER_ID};" \
  -c "DELETE FROM users WHERE id = ${USER_ID};"

./.venv/Scripts/python.exe - "${USER_ID}" <<'PY'
import sys
from minio import Minio

uid = sys.argv[1]
client = Minio("localhost:9000", access_key="study", secret_key="study123456", secure=False)
for obj in client.list_objects("study-agent", prefix=f"uploads/{uid}/", recursive=True):
    client.remove_object("study-agent", obj.object_name)
print("remaining", [o.object_name for o in client.list_objects("study-agent", prefix=f"uploads/{uid}/", recursive=True)])
PY

rm -f web/.tmp-s213-paper.pdf
rm -rf web/.tmp-screens-s213
docker exec study-agent-postgres psql -U study -d study_agent -tAc \
  "SELECT (SELECT count(*) FROM users WHERE username LIKE 's213_e2e_%'), (SELECT count(*) FROM files WHERE user_id = ${USER_ID});"
```

Expected: 最后一行 `0|0`。

- [ ] **Step 7: 写文档**

更新：
- `docs/API.md` 已在 Task 1 更新；核对与实现一致。
- `docs/DECISIONS.md` 增加 D-033：持久列表、文档类型、前端重试、3s/5min 轮询、切片预览。
- `docs/PROGRESS.md`：最近完成 S2-13、S2-13 勾选、遗留（无删除/下载、历史失败不能重试、只预览 3 条、OCR 未支持、队列不跨刷新、轮询上限）。
- `docs/AI协作开发实施计划.md`：`[x] S2-13`。
- `docs/spec/s2-13-files-ui.md` §10：commit、测试数、真实数据（文件 id、chunks 数）、偏差。
- 本 plan 末尾“执行记录”。

- [ ] **Step 8: 最终验证并提交**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
cd ..
git status --short
```

Expected: 全绿；工作树只剩文档改动。提交：

```bash
git add docs
git commit -m "docs(s2-13): 文件工作台验收记录"
```

---

## Self-Review

- **Spec coverage**：持久列表（Task 1）、块数（Task 1）、切片前 3 条（Task 1+5）、文档类型与前端拒绝（Task 2+4）、上传进度/队列（Task 3+4）、3 秒/5 分钟轮询（Task 3+5）、失败重试（Task 3+4）、页面/空态/错误/分页/抽屉（Task 5）、真实联调/文档（Task 6）。
- **Placeholder scan**：无 TBD/TODO；所有代码/测试/命令均为可执行内容。
- **Type consistency**：`UploadTask` 字段在 Task 3/4/5 一致；`FileSummary`/`FileStatus`/`ChunkPreview` 与后端 schema 字段一致；`listFileChunks(id, 3)` 与页面测试一致。
- **已知风险**：Task 3 的 fake timer 测试若因异步 tick 时序失败，按失败信息调整 `flushPromises`/推进时间，不改变生产逻辑；真实验收需 Worker 与 `PARSE_FORCE_PYMUPDF=true`，否则 Docling 可能超过 5 分钟。

---

## 执行记录

- 执行方式：用户在 plan 确认后选 **A. 本会话执行**；直接在 `main` 上沿用项目既有工作流，未另建 worktree。
- Task 1 `00f762a`：`File.chunk_count`、`FileSummaryOut`/`ChunkPreviewOut`、`GET /files`、`GET /files/{id}/chunks`、`parse-status.chunk_count`；测试 26 passed；后端全量 512 passed。
- Task 2 `2e5e8e3`：前端类型、`uploadDocument`/`listFiles`/`getFileStatus`/`listFileChunks`、格式化与轮询常量；4 条测试通过，build 通过。
- Task 3 `6c34aab`：`useFileUploads` 串行队列、Axios 进度、3s 轮询、5min 超时、失败重试；5 条测试通过。
- Task 4 `ea6d7b9`：`FileUploader.vue` 拖拽/点选、队列、进度、重试、清空已完成；2 条测试通过。
- Task 5 `76d7b2c`：`FileListView.vue`、`/files` 路由、分页、历史轮询、切片抽屉；5 条测试通过；前端全量 55 passed、build 通过。
- 修复 `1e4d1aa`：去掉测试里的 `teleport` stub（它导致 Element Plus `ElSelect` 递归更新），恢复与笔记页一致的 10/20/50 每页条数，并补 1 条列表历史轮询测试；前端全量 **56 passed / 14 files**。
- Task 6：真实验收使用 Chrome 155 + CDP、1440×900、真实 Postgres/Redis/MinIO、临时 ARQ Worker（`PARSE_FORCE_PYMUPDF=true`）。验收 PDF 6 页/7,958 bytes，上传后 `done/100/7 块`，刷新持久化，抽屉前 3 条；非法 PNG 被前端拒绝；console error 0；1440 无横向溢出。
- 实测偏差：首次 E2E 脚本断言文件名写错（实际 `tmp-s213-paper.pdf`）后重跑新账号；824px 横向溢出来自全局 `body min-width:1024px`，记为遗留 48；英文 PDF 触发 S2-10 `kp.align` evidence 超 200 字失败，记为遗留 47，未越界修改。
- 清理：2 个验收账号（id 20/21）、2 文件、2 文档笔记、14 切片、4 异步任务、2 MinIO 对象全部删除，计数回 0；临时 PDF/PNG/截图/CDP 脚本/Chrome profile 删除。
- 最终：pytest **512/512**、Vitest **56/56**、`npm run build` 通过；文档同步 API.md、DECISIONS D-033、PROGRESS、实施计划、spec §10；用户负责 push。