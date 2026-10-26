# S2-12 笔记列表与编辑器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可用的笔记列表与 Markdown 编辑页，支持筛选/分页/保存/本地草稿/公式/图片，并补上图片取图契约。

**Architecture:** 后端先补两个图片契约（`parse=false` 上传、鉴权取图）；前端按“类型与 API → 查询/草稿/图片纯函数 → 列表 → 编辑器”分层，列表查询与图片替换可单测，编辑器真实渲染交给 Chrome CDP 验收。

**Tech Stack:** Vue 3.5.42 + TypeScript 6 + Vite 8 + Element Plus 2.14 + Pinia 4 + vue-router 5；md-editor-v3 7.1.0 + KaTeX 0.19.1；FastAPI + SQLAlchemy + MinIO；Vitest 4 + @vue/test-utils 2；pytest。

**Spec:** `docs/spec/s2-12-notes-ui.md`

## Global Constraints

- 桌面优先，按 1440×900 验收；不做手机/深色/i18n。
- 不新增运行时依赖，除已确认的 `md-editor-v3@7.1.0`、`katex@0.19.1`。
- 所有业务请求走 `src/api/http.ts` 的统一壳与 401 处理；API 前缀 `API_PREFIX='/api/v1'`。
- 图片正文只存 `note-file://<id>`；禁止把 MinIO endpoint、预签名参数写进正文。
- 不新增数据库列/迁移；`notes` 的字段契约不变。
- 每次 commit 用 Conventional Commits；不执行 `git push`（用户负责）。
- 测试必须真实跑：前端 `npm run test:run` + `npm run build`；后端 `pytest`；联调用真实 Postgres/Redis/MinIO。
- 不放假数据、不把“上传成功”当“图片可显示”。

---

## Task 1: 后端图片契约（parse=false + 取图）

**Files:**
- Modify: `backend/app/services/file_service.py:93-166`
- Modify: `backend/app/api/v1/files.py:1-70`
- Modify: `backend/tests/test_files_api.py`
- Modify: `docs/API.md` §3

**Interfaces:**
- Consumes: `ObjectStorage.download_to(key, target)`、`get_file_status(session, file_id, viewer)`、`ensure_student_access`。
- Produces:
  - `upload_file(session, *, owner, upload, storage, parse: bool = True) -> tuple[File, bool]`
  - `read_image(session, *, file_id: int, viewer: User) -> File`
  - `GET /api/v1/files/{file_id}/image` → 图片字节
  - `POST /api/v1/files?parse=false` → 新图片 `parse_status=done`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_files_api.py` 顶部补 import 与 PNG 常量：

```python
import base64

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
_PNG_DIGEST = hashlib.sha256(_PNG_BYTES).hexdigest()
```

给 `FakeStorage` 增加：

```python
    def download_to(self, key: str, target) -> None:  # noqa: ANN001
        target.write(self.objects[key])
```

在文件末尾追加：

```python
def _png_payload() -> dict[str, tuple[str, BytesIO, str]]:
    return {"file": ("图.png", BytesIO(_PNG_BYTES), "image/png")}


def _image_record(*, owner_id: int = 1) -> File:
    record = File(
        user_id=owner_id,
        filename="图.png",
        mime="image/png",
        size=len(_PNG_BYTES),
        storage_path=f"uploads/{owner_id}/{_PNG_DIGEST[:2]}/{_PNG_DIGEST}.png",
        sha256=_PNG_DIGEST,
        parse_status="done",
        parse_progress=100,
        error_msg=None,
    )
    record.id = 12
    record.created_at = datetime.now(timezone.utc)
    return record


def test_upload_inline_image_skips_parse(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user)
    queue = _wire(session)
    resp = client.post(
        "/api/v1/files?parse=false", files=_png_payload(), headers=_headers(user)
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["parse_status"] == "done"
    assert queue.calls == []
    record = session.added[0]
    assert isinstance(record, File)
    assert record.parse_progress == 100
    assert record.parse_finished_at is not None


def test_upload_inline_image_rejects_non_image(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/files?parse=false", files=_file_payload(), headers=_headers(user)
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_get_image_returns_bytes_and_headers(client: TestClient) -> None:
    user = _user()
    record = _image_record()
    storage = FakeStorage()
    storage.objects[record.storage_path] = _PNG_BYTES
    _wire(FakeSession(user=user, record=record), storage)
    resp = client.get("/api/v1/files/12/image", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["etag"] == f'"{_PNG_DIGEST}"'
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "private, max-age=300"


def test_get_image_other_user_returns_403(client: TestClient) -> None:
    user = _user(2, username="student_b")
    _wire(FakeSession(user=user, record=_image_record(owner_id=1), relation=None))
    resp = client.get("/api/v1/files/12/image", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_image_non_image_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=_record()))
    resp = client.get("/api/v1/files/11/image", headers=_headers(user))
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_get_image_missing_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=None))
    resp = client.get("/api/v1/files/99/image", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q
```

Expected: 新用例失败（`parse` 参数不存在 / `/image` 404）。

- [ ] **Step 3: 实现 service**

`backend/app/services/file_service.py` 顶部补：

```python
from datetime import datetime, timezone
```

把 `upload_file` 签名改为：

```python
def upload_file(
    session: Session,
    *,
    owner: User,
    upload: UploadFile,
    storage: ObjectStorage,
    parse: bool = True,
) -> tuple[File, bool]:
```

在 `ext, mime = detect_type(filename)` 之后加：

```python
    if not parse and not mime.startswith("image/"):
        raise InvalidParamError("该文件不是图片")
```

把 `record = File(...)` 的 `parse_status="pending"` 改为：

```python
            parse_status="done" if not parse else "pending",
            parse_progress=100 if not parse else 0,
            parse_finished_at=datetime.now(timezone.utc) if not parse else None,
```

文件末尾追加：

```python
def read_image(session: Session, *, file_id: int, viewer: User) -> File:
    """取图前统一做权限与 MIME 校验；非图片不返回字节。"""
    record = get_file_status(session, file_id=file_id, viewer=viewer)
    if not record.mime.startswith("image/"):
        raise InvalidParamError("不是图片文件")
    return record
```

- [ ] **Step 4: 实现路由**

`backend/app/api/v1/files.py`：

```python
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
```

`upload_file` 增加参数：

```python
    parse: bool = Query(True, description="是否入队文档解析；编辑器图片传 false"),
```

调用改为：

```python
    record, deduped = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage, parse=parse
    )
```

入队条件改为：

```python
    if parse and record.parse_status in {
        ParseStatus.PENDING.value,
        ParseStatus.FAILED.value,
    }:
```

文件末尾追加：

```python
@router.get(
    "/{file_id}/image",
    response_class=Response,
    summary="读取图片（内联展示）",
)
def get_image(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    record = file_service.read_image(session, file_id=file_id, viewer=current_user)
    buffer = BytesIO()
    storage.download_to(record.storage_path, buffer)
    return Response(
        content=buffer.getvalue(),
        media_type=record.mime,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": (
                "inline; filename*=UTF-8''" + quote(record.filename, safe="")
            ),
            "ETag": f'"{record.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
```

- [ ] **Step 5: 跑测试与全量回归**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```

Expected: 目标用例通过；全量 500+ 通过（新增 6 条）。

- [ ] **Step 6: 更新 API.md §3**

在 `POST /api/v1/files` 的入参补：

```markdown
- 入参：`multipart/form-data`，字段名 `file`；可选 query `parse`（默认 `true`）。
  `parse=false` 仅用于编辑器图片：只接受 `image/*`，新记录直接 `parse_status=done`、
  `parse_progress=100`，不入队解析；非图片返回 `422/42200`。
```

在 `GET /api/v1/files/{file_id}/parse-status` 后追加：

```markdown
### GET /api/v1/files/{file_id}/image
- 权限：本人，或已绑定该学生的 parent/teacher（admin 不绕过）
- 类型：同步，返回二进制
- 出参：图片字节；`Content-Type` 为记录 MIME，带 `ETag=sha256`、
  `Cache-Control: private, max-age=300`、`X-Content-Type-Options: nosniff`
- 错误：`404/40400` 文件不存在；`403/40300` 无权访问；`422/42200` 不是图片文件；
  `500/50000` 文件存储不可用
- 备注：内联展示用；首版一次性读入内存
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/file_service.py backend/app/api/v1/files.py backend/tests/test_files_api.py docs/API.md
git commit -m "feat(s2-12): 图片上传跳过解析与鉴权取图接口"
```

---

## Task 2: 前端依赖、类型、API 与纯函数

**Files:**
- Modify: `web/package.json`、`web/package-lock.json`
- Create: `web/src/types/common.ts`、`web/src/types/notes.ts`、`web/src/types/files.ts`、`web/src/types/kp.ts`
- Create: `web/src/api/notes.ts`、`web/src/api/files.ts`、`web/src/api/kp.ts`
- Create: `web/src/utils/noteDraft.ts`、`web/src/utils/noteImages.ts`
- Create: `web/src/views/notes/listQuery.ts`
- Test: `web/src/utils/noteDraft.spec.ts`、`web/src/utils/noteImages.spec.ts`、`web/src/views/notes/listQuery.spec.ts`

**Interfaces:**
- Consumes: `http`、`API_PREFIX`、`ApiEnvelope`、`PageData`。
- Produces:
  - `NoteSummary`、`NoteOut`、`NoteCreatePayload`、`NoteUpdatePayload`、`NoteSort`
  - `listNotes`、`getNote`、`createNote`、`updateNote`、`deleteNote`
  - `uploadImage`、`getImageBlob`、`listSubjects`
  - `DraftState`、`draftKey`、`readDraft`、`writeDraft`、`clearDraft`、`isDraftStale`
  - `extractImageIds`、`replaceImageTokens`、`replaceImageUrls`
  - `ListQueryState`、`normalizeListQuery`、`toNoteListParams`、`toListQuery`

- [ ] **Step 1: 安装依赖**

```bash
cd web && npm install md-editor-v3@7.1.0 katex@0.19.1
```

Expected: `package.json` dependencies 出现两项；lockfile 更新。

- [ ] **Step 2: 写类型**

`web/src/types/common.ts`：

```ts
export interface PageData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
```

`web/src/types/notes.ts`：

```ts
export type NoteSort = 'updated' | 'created' | 'title'

export interface NoteSummary {
  id: number
  title: string
  subject_id: number | null
  tags: string[] | null
  folder: string | null
  created_at: string
  updated_at: string
}

export interface NoteOut extends NoteSummary {
  content_md: string
  source_file_id: number | null
}

export interface NoteCreatePayload {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
}

export type NoteUpdatePayload = Partial<NoteCreatePayload>

export interface NoteListParams {
  q?: string
  subject_id?: number
  sort_by?: 'created_at' | 'updated_at' | 'title'
  order?: 'asc' | 'desc'
  page: number
  page_size: number
}
```

`web/src/types/files.ts`：

```ts
export interface FileUploadOut {
  id: number
  filename: string
  mime: string
  size: number
  sha256: string
  parse_status: string
  created_at: string
  deduped: boolean
}
```

`web/src/types/kp.ts`：

```ts
export interface SubjectOut {
  id: number
  name: string
  code: string
  stage: string
}
```

- [ ] **Step 3: 写 API**

`web/src/api/notes.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { PageData } from '@/types/common'
import type {
  NoteCreatePayload,
  NoteListParams,
  NoteOut,
  NoteSummary,
  NoteUpdatePayload,
} from '@/types/notes'

export async function listNotes(params: NoteListParams): Promise<PageData<NoteSummary>> {
  const resp = await http.get<ApiEnvelope<PageData<NoteSummary>>>(`${API_PREFIX}/notes`, {
    params,
  })
  return resp.data.data
}

export async function getNote(id: number): Promise<NoteOut> {
  const resp = await http.get<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes/${id}`)
  return resp.data.data
}

export async function createNote(payload: NoteCreatePayload): Promise<NoteOut> {
  const resp = await http.post<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes`, payload)
  return resp.data.data
}

export async function updateNote(id: number, payload: NoteUpdatePayload): Promise<NoteOut> {
  const resp = await http.patch<ApiEnvelope<NoteOut>>(`${API_PREFIX}/notes/${id}`, payload)
  return resp.data.data
}

export async function deleteNote(id: number): Promise<void> {
  await http.delete(`${API_PREFIX}/notes/${id}`)
}
```

`web/src/api/files.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { FileUploadOut } from '@/types/files'

export async function uploadImage(file: File): Promise<FileUploadOut> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<ApiEnvelope<FileUploadOut>>(`${API_PREFIX}/files`, form, {
    params: { parse: 'false' },
    timeout: 60_000,
  })
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

`web/src/api/kp.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { SubjectOut } from '@/types/kp'

export async function listSubjects(): Promise<SubjectOut[]> {
  const resp = await http.get<ApiEnvelope<SubjectOut[]>>(`${API_PREFIX}/kp/subjects`)
  return resp.data.data
}
```

- [ ] **Step 4: 写草稿与图片纯函数**

`web/src/utils/noteDraft.ts`：

```ts
const PREFIX = 'study-agent:note-draft:v1'

export interface DraftState {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
  draftSavedAt: string
  baseUpdatedAt: string | null
}

export function draftKey(noteId: number | null): string {
  return `${PREFIX}:${noteId ?? 'new'}`
}

export function writeDraft(noteId: number | null, state: DraftState): void {
  try {
    localStorage.setItem(draftKey(noteId), JSON.stringify(state))
  } catch {
    // 隐私模式/配额满：草稿降级为仅内存，不阻断编辑
  }
}

export function readDraft(noteId: number | null): DraftState | null {
  try {
    const raw = localStorage.getItem(draftKey(noteId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<DraftState>
    if (
      typeof value.title !== 'string' ||
      typeof value.content_md !== 'string' ||
      (value.subject_id !== null && typeof value.subject_id !== 'number') ||
      !Array.isArray(value.tags) ||
      value.tags.some((tag) => typeof tag !== 'string') ||
      typeof value.draftSavedAt !== 'string' ||
      (value.baseUpdatedAt !== null && typeof value.baseUpdatedAt !== 'string')
    ) {
      throw new Error('invalid draft')
    }
    return value as DraftState
  } catch {
    try {
      localStorage.removeItem(draftKey(noteId))
    } catch {
      // ignore
    }
    return null
  }
}

export function clearDraft(noteId: number | null): void {
  try {
    localStorage.removeItem(draftKey(noteId))
  } catch {
    // ignore
  }
}

export function isDraftStale(draft: DraftState, serverUpdatedAt: string | null): boolean {
  if (draft.baseUpdatedAt === null) return false
  return draft.baseUpdatedAt !== serverUpdatedAt
}
```

`web/src/utils/noteImages.ts`：

```ts
const TOKEN_PATTERN = /!\[([^\]]*)\]\(note-file:\/\/(\d+)\)/g

export function extractImageIds(markdown: string): number[] {
  const ids = new Set<number>()
  for (const match of markdown.matchAll(TOKEN_PATTERN)) {
    ids.add(Number(match[2]))
  }
  return [...ids]
}

export function replaceImageTokens(
  markdown: string,
  urlById: ReadonlyMap<number, string>,
): string {
  return markdown.replace(TOKEN_PATTERN, (whole, alt: string, rawId: string) => {
    const url = urlById.get(Number(rawId))
    return url ? `![${alt}](${url})` : whole
  })
}

export function replaceImageUrls(
  markdown: string,
  tokenByUrl: ReadonlyMap<string, string>,
): string {
  let result = markdown
  for (const [url, token] of tokenByUrl) {
    result = result.split(url).join(token)
  }
  return result
}
```

- [ ] **Step 5: 写列表查询纯函数**

`web/src/views/notes/listQuery.ts`：

```ts
import type { LocationQuery } from 'vue-router'
import type { NoteListParams, NoteSort } from '@/types/notes'

export interface ListQueryState {
  q: string
  subjectId: number | null
  sort: NoteSort
  page: number
  pageSize: number
}

const SORTS: NoteSort[] = ['updated', 'created', 'title']
const PAGE_SIZES = [10, 20, 50]

export function normalizeListQuery(raw: LocationQuery): ListQueryState {
  const q = typeof raw.q === 'string' ? raw.q.trim().slice(0, 100) : ''
  const subjectRaw = typeof raw.subject_id === 'string' ? Number(raw.subject_id) : NaN
  const subjectId = Number.isInteger(subjectRaw) && subjectRaw > 0 ? subjectRaw : null
  const sortRaw = typeof raw.sort === 'string' ? raw.sort : ''
  const sort = SORTS.includes(sortRaw as NoteSort) ? (sortRaw as NoteSort) : 'updated'
  const pageRaw = typeof raw.page === 'string' ? Number(raw.page) : 1
  const page = Number.isInteger(pageRaw) && pageRaw > 0 ? pageRaw : 1
  const sizeRaw = typeof raw.page_size === 'string' ? Number(raw.page_size) : 10
  const pageSize = PAGE_SIZES.includes(sizeRaw) ? sizeRaw : 10
  return { q, subjectId, sort, page, pageSize }
}

export function toNoteListParams(state: ListQueryState): NoteListParams {
  const params: NoteListParams = {
    page: state.page,
    page_size: state.pageSize,
  }
  if (state.q) params.q = state.q
  if (state.subjectId !== null) params.subject_id = state.subjectId
  if (state.sort === 'updated') {
    params.sort_by = 'updated_at'
    params.order = 'desc'
  } else if (state.sort === 'created') {
    params.sort_by = 'created_at'
    params.order = 'desc'
  } else {
    params.sort_by = 'title'
    params.order = 'asc'
  }
  return params
}

export function toListQuery(state: ListQueryState): Record<string, string> {
  const query: Record<string, string> = {}
  if (state.q) query.q = state.q
  if (state.subjectId !== null) query.subject_id = String(state.subjectId)
  if (state.sort !== 'updated') query.sort = state.sort
  if (state.page !== 1) query.page = String(state.page)
  if (state.pageSize !== 10) query.page_size = String(state.pageSize)
  return query
}
```

- [ ] **Step 6: 写三个 spec**

`web/src/utils/noteDraft.spec.ts`：

```ts
import { beforeEach, describe, expect, it } from 'vitest'

import { clearDraft, draftKey, isDraftStale, readDraft, writeDraft } from './noteDraft'

const draft = {
  title: '函数单调性',
  content_md: '# 笔记',
  subject_id: 7,
  tags: ['函数'],
  draftSavedAt: '2026-10-27T02:00:00.000Z',
  baseUpdatedAt: '2026-10-27T01:50:00+00:00',
}

describe('noteDraft', () => {
  beforeEach(() => localStorage.clear())

  it('roundtrips and clears', () => {
    writeDraft(5, draft)
    expect(readDraft(5)).toEqual(draft)
    clearDraft(5)
    expect(readDraft(5)).toBeNull()
  })

  it('uses distinct keys for new and existing notes', () => {
    expect(draftKey(null)).toBe('study-agent:note-draft:v1:new')
    expect(draftKey(5)).toBe('study-agent:note-draft:v1:5')
  })

  it('detects stale drafts by baseUpdatedAt', () => {
    expect(isDraftStale(draft, draft.baseUpdatedAt)).toBe(false)
    expect(isDraftStale(draft, '2026-10-27T03:00:00+00:00')).toBe(true)
    expect(isDraftStale({ ...draft, baseUpdatedAt: null }, null)).toBe(false)
  })

  it('drops malformed drafts', () => {
    localStorage.setItem(draftKey(5), '{bad')
    expect(readDraft(5)).toBeNull()
    expect(localStorage.getItem(draftKey(5))).toBeNull()
  })
})
```

`web/src/utils/noteImages.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { extractImageIds, replaceImageTokens, replaceImageUrls } from './noteImages'

const md = '文字\n![图1](note-file://3)\n![图2](note-file://4)'

describe('noteImages', () => {
  it('extracts unique ids', () => {
    expect(extractImageIds(`${md}\n![重复](note-file://3)`)).toEqual([3, 4])
    expect(extractImageIds('没有图片')).toEqual([])
  })

  it('replaces tokens with blob urls', () => {
    const out = replaceImageTokens(md, new Map([[3, 'blob:a'], [4, 'blob:b']]))
    expect(out).toBe('文字\n![图1](blob:a)\n![图2](blob:b)')
  })

  it('leaves unknown ids untouched', () => {
    expect(replaceImageTokens(md, new Map([[3, 'blob:a']]))).toBe(
      '文字\n![图1](blob:a)\n![图2](note-file://4)',
    )
  })

  it('replaces blob urls back to tokens', () => {
    const urls = new Map([
      ['blob:a', 'note-file://3'],
      ['blob:b', 'note-file://4'],
    ])
    expect(replaceImageUrls('![图1](blob:a) ![图2](blob:b)', urls)).toBe(
      '![图1](note-file://3) ![图2](note-file://4)',
    )
  })

  it('does not touch external image urls', () => {
    const input = '![外链](https://example.com/a.png)'
    expect(replaceImageUrls(input, new Map([['blob:a', 'note-file://3']]))).toBe(input)
  })
})
```

`web/src/views/notes/listQuery.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { normalizeListQuery, toListQuery, toNoteListParams } from './listQuery'

describe('listQuery', () => {
  it('normalizes invalid values to defaults', () => {
    expect(normalizeListQuery({ q: '  函数 ', sort: 'bad', page: '0', page_size: '7' })).toEqual({
      q: '函数',
      subjectId: null,
      sort: 'updated',
      page: 1,
      pageSize: 10,
    })
  })

  it('maps sort to API params', () => {
    expect(
      toNoteListParams({ q: '导数', subjectId: 7, sort: 'title', page: 2, pageSize: 20 }),
    ).toMatchObject({
      q: '导数',
      subject_id: 7,
      sort_by: 'title',
      order: 'asc',
      page: 2,
      page_size: 20,
    })
  })

  it('omits defaults from the URL', () => {
    expect(
      toListQuery({ q: '', subjectId: null, sort: 'updated', page: 1, pageSize: 10 }),
    ).toEqual({})
    expect(
      toListQuery({ q: '函数', subjectId: 7, sort: 'created', page: 2, pageSize: 50 }),
    ).toEqual({ q: '函数', subject_id: '7', sort: 'created', page: '2', page_size: '50' })
  })
})
```

- [ ] **Step 7: 跑测试与构建**

```bash
cd web && npm run test:run
cd web && npm run build
```

Expected: 新增 10 条左右全绿；既有 17 条不回归；build 通过。

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/types web/src/api web/src/utils/noteDraft.ts web/src/utils/noteImages.ts web/src/utils/noteDraft.spec.ts web/src/utils/noteImages.spec.ts web/src/views/notes/listQuery.ts web/src/views/notes/listQuery.spec.ts
git commit -m "feat(s2-12): 笔记/文件 API、草稿与图片工具"
```

---

## Task 3: 列表页、路由与导航高亮

**Files:**
- Create: `web/src/views/notes/useNoteList.ts`
- Create: `web/src/views/notes/NoteListView.vue`
- Create: `web/src/views/notes/NoteListView.spec.ts`
- Modify: `web/src/router/index.ts:24-36`
- Modify: `web/src/router/meta.d.ts`
- Modify: `web/src/components/layout/SideNav.vue`
- Modify: `web/src/components/layout/TopBar.vue`

**Interfaces:**
- Consumes: `listNotes`、`deleteNote`、`listSubjects`、`normalizeListQuery`、`toNoteListParams`、`toListQuery`、`PageHeader`、`EmptyState`。
- Produces: `/notes` 真实列表页；侧栏 `meta.nav` 高亮；编辑页路由 name `note-edit`、`note-new`。

- [ ] **Step 1: 路由与 meta**

`web/src/router/meta.d.ts` 增加：

```ts
    nav?: string
```

`web/src/router/index.ts` 的 notes 子路由替换为：

```ts
        {
          path: 'notes',
          name: 'notes',
          component: () => import('@/views/notes/NoteListView.vue'),
          meta: { title: '笔记', nav: 'notes', roles: ['student'] },
        },
        {
          path: 'notes/new',
          name: 'note-new',
          component: () => import('@/views/notes/NoteEditView.vue'),
          meta: { title: '新建笔记', nav: 'notes', roles: ['student'] },
        },
        {
          path: 'notes/:id(\\d+)/edit',
          name: 'note-edit',
          component: () => import('@/views/notes/NoteEditView.vue'),
          meta: { title: '编辑笔记', nav: 'notes', roles: ['student'] },
        },
```

注意 Vue Router 4/5 的 `:id(\\d+)` 在字符串里写 `:id(\\d+)`。

- [ ] **Step 2: 侧栏与面包屑**

`SideNav.vue` script：

```ts
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { NAV_ITEMS } from '@/layouts/nav'

const route = useRoute()
const activeNav = computed(() => route.meta.nav ?? route.name)
```

模板 active 判断改为：

```vue
:class="{ active: activeNav === item.name }"
:aria-current="activeNav === item.name ? 'page' : undefined"
```

`TopBar.vue` script：

```ts
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { NAV_ITEMS } from '@/layouts/nav'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const title = computed(() => String(route.meta.title ?? ''))
const section = computed(() => {
  const nav = route.meta.nav
  if (!nav || nav === route.name) return null
  return NAV_ITEMS.find((item) => item.name === nav) ?? null
})
```

模板面包屑改为：

```vue
    <nav class="crumbs" aria-label="面包屑">
      <router-link v-if="section" :to="section.path">{{ section.label }}</router-link>
      <router-link v-else to="/notes">首页</router-link>
      <span class="separator" aria-hidden="true">/</span>
      <span class="current">{{ title }}</span>
    </nav>
```

- [ ] **Step 3: 列表状态 composable**

`web/src/views/notes/useNoteList.ts`：

```ts
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { deleteNote, listNotes } from '@/api/notes'
import type { NoteSummary } from '@/types/notes'
import {
  normalizeListQuery,
  toListQuery,
  toNoteListParams,
  type ListQueryState,
} from '@/views/notes/listQuery'

export function useNoteList() {
  const route = useRoute()
  const router = useRouter()
  const items = ref<NoteSummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  const query = reactive<ListQueryState>(normalizeListQuery(route.query))
  let requestId = 0

  async function fetchList(): Promise<void> {
    const current = ++requestId
    loading.value = true
    error.value = ''
    try {
      const page = await listNotes(toNoteListParams(query))
      if (current !== requestId) return
      items.value = page.items
      total.value = page.total
    } catch {
      if (current !== requestId) return
      error.value = '笔记加载失败，请重试'
    } finally {
      if (current === requestId) loading.value = false
    }
  }

  async function updateQuery(patch: Partial<ListQueryState>, resetPage = false): Promise<void> {
    Object.assign(query, patch)
    if (resetPage) query.page = 1
    await router.replace({ query: toListQuery(query) })
  }

  function syncFromRoute(): void {
    Object.assign(query, normalizeListQuery(route.query))
  }

  return { items, total, loading, error, query, fetchList, updateQuery, syncFromRoute }
}
```

- [ ] **Step 4: 列表页**

`web/src/views/notes/NoteListView.vue`（完整骨架；样式用既有 token，表格内边距 12px）：

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { deleteNote } from '@/api/notes'
import { listSubjects } from '@/api/kp'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import type { SubjectOut } from '@/types/kp'
import { useNoteList } from '@/views/notes/useNoteList'

const route = useRoute()
const router = useRouter()
const { items, total, loading, error, query, fetchList, updateQuery, syncFromRoute } =
  useNoteList()
const subjects = ref<SubjectOut[]>([])
const subjectNames = computed(() => new Map(subjects.value.map((item) => [item.id, item.name])))
const keyword = ref(query.q)
let timer: ReturnType<typeof setTimeout> | undefined

const hasFilter = computed(() => Boolean(query.q) || query.subjectId !== null)

function formatTime(value: string): string {
  return value.replace('T', ' ').slice(0, 16)
}

function subjectName(id: number | null): string {
  return id === null ? '未分类' : (subjectNames.value.get(id) ?? '未分类')
}

function onKeywordInput(value: string): void {
  keyword.value = value
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    void updateQuery({ q: value.trim() }, true)
  }, 300)
}

async function onSubjectChange(value: number | null | undefined): Promise<void> {
  await updateQuery({ subjectId: typeof value === 'number' ? value : null }, true)
}

async function onSortChange(value: string): Promise<void> {
  await updateQuery({ sort: value as 'updated' | 'created' | 'title' }, true)
}

async function onPageChange(page: number): Promise<void> {
  await updateQuery({ page })
}

async function onSizeChange(size: number): Promise<void> {
  await updateQuery({ pageSize: size }, true)
}

async function clearFilters(): Promise<void> {
  keyword.value = ''
  await updateQuery({ q: '', subjectId: null }, true)
}

async function removeNote(id: number, title: string): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除「${title}」？删除后不可在列表恢复。`, '删除笔记', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteNote(id)
    ElMessage.success('已删除')
    if (items.value.length === 1 && query.page > 1) {
      await updateQuery({ page: query.page - 1 })
    } else {
      await fetchList()
    }
  } catch {
    // 全局拦截器已提示
  }
}

function editNote(id: number): void {
  void router.push({ name: 'note-edit', params: { id } })
}

function onRowClick(row: { id: number }): void {
  editNote(row.id)
}

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})

watch(
  () => route.query,
  async () => {
    syncFromRoute()
    keyword.value = query.q
    await fetchList()
  },
  { immediate: true },
)
</script>
```



```vue
<template>
  <div class="notes-page">
    <PageHeader
      title="笔记"
      description="按主题整理，保存后自动对齐知识点。"
    >
      <template #actions>
        <el-button type="primary" @click="router.push({ name: 'note-new' })">
          新建笔记
        </el-button>
      </template>
    </PageHeader>

    <section class="filter-bar" aria-label="笔记筛选">
      <el-input
        :model-value="keyword"
        class="keyword"
        placeholder="搜索标题或正文"
        clearable
        @update:model-value="onKeywordInput"
      />
      <el-select
        :model-value="query.subjectId"
        class="subject"
        placeholder="全部学科"
        clearable
        @update:model-value="onSubjectChange"
      >
        <el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select :model-value="query.sort" class="sort" @update:model-value="onSortChange">
        <el-option label="最近更新" value="updated" />
        <el-option label="最近创建" value="created" />
        <el-option label="标题 A–Z" value="title" />
      </el-select>
    </section>

    <div v-if="error" class="error-bar" role="alert">
      {{ error }}
      <el-button link type="primary" @click="fetchList">重试</el-button>
    </div>

    <el-table
      v-if="items.length || loading"
      v-loading="loading"
      :data="items"
      class="notes-table"
      row-key="id"
      @row-click="onRowClick"
    >
      <el-table-column prop="title" label="标题" min-width="320">
        <template #default="{ row }">
          <span class="row-title" :title="row.title">{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column label="学科" width="140">
        <template #default="{ row }">{{ subjectName(row.subject_id) }}</template>
      </el-table-column>
      <el-table-column label="标签" min-width="200">
        <template #default="{ row }">
          <el-tag
            v-for="tag in (row.tags ?? []).slice(0, 3)"
            :key="tag"
            size="small"
            effect="plain"
            class="tag"
          >{{ tag }}</el-tag>
          <span v-if="(row.tags ?? []).length > 3" class="tag-more">
            +{{ row.tags.length - 3 }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="editNote(row.id)">编辑</el-button>
          <el-button link type="danger" @click.stop="removeNote(row.id, row.title)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <EmptyState
      v-else-if="!loading && hasFilter"
      title="没有匹配的笔记"
      description="换个关键词或学科试试。"
    >
      <template #actions>
        <el-button @click="clearFilters">清空筛选</el-button>
      </template>
    </EmptyState>
    <EmptyState v-else-if="!loading" title="还没有笔记" description="把今天学到的东西写下来。">
      <template #actions>
        <el-button type="primary" @click="router.push({ name: 'note-new' })">写第一篇笔记</el-button>
      </template>
    </EmptyState>

    <div v-if="total > 0" class="pager">
      <el-pagination
        :current-page="query.page"
        :page-size="query.pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
.notes-page { display: grid; gap: 16px; }
.filter-bar {
  display: flex; gap: 12px; align-items: center;
  padding: 16px; background: var(--app-surface);
  border: 1px solid var(--app-border); border-radius: var(--app-radius-md);
}
.keyword { width: 320px; }
.subject { width: 180px; }
.sort { width: 160px; }
.error-bar {
  display: flex; gap: 8px; align-items: center; justify-content: space-between;
  padding: 10px 14px; color: var(--app-danger);
  background: #fff5f5; border: 1px solid #ffc9c9; border-radius: var(--app-radius-sm);
}
.notes-table { background: var(--app-surface); border-radius: var(--app-radius-md); }
.row-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { margin-right: 4px; }
.tag-more { color: var(--app-text-tertiary); font-size: 12px; }
.pager { display: flex; justify-content: flex-end; padding-top: 4px; }
</style>
```

- [ ] **Step 5: 先放编辑页占位，保证本任务可构建**

`web/src/views/notes/NoteEditView.vue`（Task 4 会整体替换）：

```vue
<template>
  <div>编辑页建设中</div>
</template>
```

- [ ] **Step 6: 写列表页测试**

`web/src/views/notes/NoteListView.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import NoteListView from './NoteListView.vue'

vi.mock('@/api/notes', () => ({
  listNotes: vi.fn(),
  deleteNote: vi.fn(),
}))
vi.mock('@/api/kp', () => ({
  listSubjects: vi.fn().mockResolvedValue([{ id: 7, name: '高中数学', code: 'math', stage: '高中' }]),
}))

import { deleteNote, listNotes } from '@/api/notes'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes', name: 'notes', component: NoteListView },
      { path: '/notes/new', name: 'note-new', component: { template: '<div />' } },
      { path: '/notes/:id/edit', name: 'note-edit', component: { template: '<div />' } },
    ],
  })
}

async function mountPage() {
  const router = makeRouter()
  await router.push('/notes')
  await router.isReady()
  const wrapper = mount(NoteListView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

describe('NoteListView', () => {
  beforeEach(() => {
    vi.mocked(listNotes).mockReset()
    vi.mocked(deleteNote).mockReset()
  })

  it('renders rows', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        { id: 1, title: '函数单调性', subject_id: 7, tags: ['函数'], folder: null,
          created_at: '2026-10-27T01:00:00+00:00', updated_at: '2026-10-27T02:00:00+00:00' },
      ],
      total: 1, page: 1, page_size: 10,
    })
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('函数单调性')
    expect(wrapper.text()).toContain('高中数学')
  })

  it('shows the empty state when there are no notes', async () => {
    vi.mocked(listNotes).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('还没有笔记')
  })

  it('shows filtered empty state', async () => {
    vi.mocked(listNotes).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 })
    const { wrapper } = await mountPage()
    await wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', '不存在')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()
    expect(wrapper.text()).toContain('没有匹配的笔记')
  })

  it('deletes after confirmation', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        { id: 1, title: '函数单调性', subject_id: 7, tags: [], folder: null,
          created_at: '2026-10-27T01:00:00+00:00', updated_at: '2026-10-27T02:00:00+00:00' },
      ],
      total: 1, page: 1, page_size: 10,
    })
    vi.mocked(deleteNote).mockResolvedValue()
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const { wrapper } = await mountPage()
    const buttons = wrapper.findAll('.el-table__row button')
    const danger = buttons.find((button) => button.text().includes('删除'))
    expect(danger).toBeTruthy()
    await danger!.trigger('click')
    await flushPromises()
    expect(deleteNote).toHaveBeenCalledWith(1)
    confirm.mockRestore()
  })

  it('navigates to the editor on row click', async () => {
    vi.mocked(listNotes).mockResolvedValue({
      items: [
        { id: 1, title: '函数单调性', subject_id: 7, tags: [], folder: null,
          created_at: '2026-10-27T01:00:00+00:00', updated_at: '2026-10-27T02:00:00+00:00' },
      ],
      total: 1, page: 1, page_size: 10,
    })
    const { wrapper, router } = await mountPage()
    await wrapper.find('.el-table__row').trigger('click')
    expect(router.currentRoute.value.name).toBe('note-edit')
    expect(router.currentRoute.value.params.id).toBe('1')
  })
})
```

- [ ] **Step 7: 跑测试**

```bash
cd web && npm run test:run -- src/views/notes/NoteListView.spec.ts
```

Expected: 5 条通过；若 `ElInput` 查找方式受 Element Plus 版本影响，改用
`wrapper.find('input').setValue('不存在')`。

- [ ] **Step 8: Commit**

```bash
git add web/src/views/notes web/src/router/index.ts web/src/router/meta.d.ts \
  web/src/components/layout/SideNav.vue web/src/components/layout/TopBar.vue
git commit -m "feat(s2-12): 笔记列表、筛选分页与导航高亮"
```

---

## Task 4: 编辑页、Markdown 编辑器、草稿与离开保护

**Files:**
- Create: `web/src/components/notes/TagInput.vue`
- Create: `web/src/components/notes/MarkdownEditor.vue`
- Create: `web/src/views/notes/useNoteEditor.ts`
- Replace: `web/src/views/notes/NoteEditView.vue`（Task 3 的占位）
- Create: `web/src/views/notes/NoteEditView.spec.ts`

**Interfaces:**
- Consumes: `getNote/createNote/updateNote`、`getImageBlob`、`uploadImage`、`readDraft/writeDraft/clearDraft/isDraftStale`、`extractImageIds/replaceImageTokens/replaceImageUrls`、`listSubjects`。
- Produces:
  - `useNoteEditor(noteId: Ref<number|null>, options): {form, loading, saving, dirty, error, pendingDraft, imageFailures, load, save, applyDraft, discardDraft, writeCurrentDraft, registerImage, revokeImages}`
  - `MarkdownEditor` emits `update:modelValue`、`save`、`upload-error`、`image-uploaded {id,url}`
  - `/notes/new` 与 `/notes/:id/edit` 可编辑、保存、恢复草稿、拦截离开。

- [ ] **Step 1: 写 TagInput**

`web/src/components/notes/TagInput.vue`：

```vue
<script setup lang="ts">
import { ElMessage } from 'element-plus'

const props = defineProps<{ modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

function onChange(values: string[]): void {
  const result: string[] = []
  for (const raw of values) {
    const tag = raw.trim()
    if (!tag) continue
    if (tag.length > 30) {
      ElMessage.warning('单个标签不超过 30 字')
      continue
    }
    if (!result.includes(tag)) result.push(tag)
  }
  if (result.length > 20) ElMessage.warning('最多 20 个标签')
  emit('update:modelValue', result.slice(0, 20))
}
</script>

<template>
  <el-select
    :model-value="props.modelValue"
    data-testid="tag-input"
    multiple
    filterable
    allow-create
    default-first-option
    placeholder="添加标签"
    class="tag-input"
    @change="onChange"
  />
</template>

<style scoped>
.tag-input {
  width: 260px;
}
</style>
```

- [ ] **Step 2: 写 MarkdownEditor**

`web/src/components/notes/MarkdownEditor.vue`：

```vue
<script setup lang="ts">
import { MdEditor, type ToolbarNames } from 'md-editor-v3'
import { ElMessage } from 'element-plus'

import { getImageBlob, uploadImage } from '@/api/files'

import 'md-editor-v3/lib/style.css'
import 'katex/dist/katex.min.css'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
  'upload-error': []
  'image-uploaded': [payload: { id: number; url: string }]
}>()

const toolbars: ToolbarNames[] = [
  'bold',
  'italic',
  'strikeThrough',
  'title',
  'quote',
  'unorderedList',
  'orderedList',
  'code',
  'link',
  'image',
  'table',
  'katex',
  '-',
  'preview',
  'fullscreen',
  'save',
]

async function onUploadImg(files: File[], callback: (urls: string[]) => void): Promise<void> {
  const urls: string[] = []
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      ElMessage.warning('只能插入图片文件')
      continue
    }
    try {
      const record = await uploadImage(file)
      const blob = await getImageBlob(record.id)
      const url = URL.createObjectURL(blob)
      urls.push(url)
      emit('image-uploaded', { id: record.id, url })
    } catch {
      emit('upload-error')
    }
  }
  callback(urls)
}
</script>

<template>
  <div class="editor-shell" data-testid="markdown-editor">
    <MdEditor
      :model-value="props.modelValue"
      :toolbars="toolbars"
      :no-mermaid="true"
      preview-theme="github"
      code-theme="atom"
      :style="{ height: '100%' }"
      :on-upload-img="onUploadImg"
      @update:model-value="emit('update:modelValue', $event)"
      @on-save="emit('save')"
    />
  </div>
</template>

<style scoped>
.editor-shell {
  height: calc(100vh - 280px);
  min-height: 420px;
  overflow: hidden;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
</style>
```

- [ ] **Step 3: 写 useNoteEditor**

`web/src/views/notes/useNoteEditor.ts`：

```ts
import { computed, reactive, ref, type Ref } from 'vue'

import { getImageBlob } from '@/api/files'
import { createNote, getNote, updateNote } from '@/api/notes'
import type { NoteCreatePayload, NoteUpdatePayload } from '@/types/notes'
import {
  clearDraft,
  isDraftStale,
  readDraft,
  writeDraft,
  type DraftState,
} from '@/utils/noteDraft'
import { extractImageIds, replaceImageTokens, replaceImageUrls } from '@/utils/noteImages'

export interface EditorForm {
  title: string
  content_md: string
  subject_id: number | null
  tags: string[]
}

export function emptyForm(): EditorForm {
  return { title: '', content_md: '', subject_id: null, tags: [] }
}

export function validateForm(form: EditorForm): string | null {
  const title = form.title.trim()
  const content = form.content_md.trim()
  if (!title) return '标题不能为空'
  if (title.length > 200) return '标题不能超过 200 字'
  if (!content) return '正文不能为空'
  if (content.length > 200_000) return '正文不能超过 200000 字'
  if (form.tags.length > 20) return '最多 20 个标签'
  if (form.tags.some((tag) => tag.length > 30)) return '单个标签不能超过 30 字'
  return null
}

function rawSnapshot(form: EditorForm): string {
  return JSON.stringify({
    title: form.title.trim(),
    content_md: form.content_md,
    subject_id: form.subject_id,
    tags: form.tags,
  })
}

export function useNoteEditor(
  noteId: Ref<number | null>,
  options: { onCreated?: (id: number) => void } = {},
) {
  const form = reactive<EditorForm>(emptyForm())
  const saved = ref<EditorForm>(emptyForm())
  const loading = ref(true)
  const saving = ref(false)
  const error = ref('')
  const pendingDraft = ref<DraftState | null>(null)
  const imageFailures = ref(0)
  const updatedAt = ref<string | null>(null)
  const tokenByUrl = new Map<string, string>()
  const objectUrls: string[] = []

  function revokeImages(): void {
    for (const url of objectUrls) URL.revokeObjectURL(url)
    objectUrls.length = 0
    tokenByUrl.clear()
  }

  async function hydrateImages(markdown: string): Promise<string> {
    const ids = extractImageIds(markdown)
    const urlById = new Map<number, string>()
    await Promise.all(
      ids.map(async (id) => {
        try {
          const blob = await getImageBlob(id)
          const url = URL.createObjectURL(blob)
          objectUrls.push(url)
          urlById.set(id, url)
          tokenByUrl.set(url, `note-file://${id}`)
        } catch {
          imageFailures.value += 1
        }
      }),
    )
    return replaceImageTokens(markdown, urlById)
  }

  function currentRaw(): EditorForm {
    return {
      title: form.title.trim(),
      content_md: replaceImageUrls(form.content_md, tokenByUrl).trim(),
      subject_id: form.subject_id,
      tags: [...form.tags],
    }
  }

  const dirty = computed(() => rawSnapshot(currentRaw()) !== rawSnapshot(saved.value))

  async function load(): Promise<void> {
    revokeImages()
    loading.value = true
    error.value = ''
    imageFailures.value = 0
    pendingDraft.value = null
    try {
      if (noteId.value === null) {
        Object.assign(form, emptyForm())
        saved.value = emptyForm()
        updatedAt.value = null
        const draft = readDraft(null)
        if (draft) pendingDraft.value = draft
        return
      }
      const note = await getNote(noteId.value)
      Object.assign(form, {
        title: note.title,
        content_md: note.content_md,
        subject_id: note.subject_id,
        tags: [...(note.tags ?? [])],
      })
      saved.value = {
        title: note.title,
        content_md: note.content_md,
        subject_id: note.subject_id,
        tags: [...(note.tags ?? [])],
      }
      updatedAt.value = note.updated_at
      const draft = readDraft(noteId.value)
      if (draft) {
        if (isDraftStale(draft, note.updated_at)) clearDraft(noteId.value)
        else pendingDraft.value = draft
      }
      form.content_md = await hydrateImages(note.content_md)
    } catch {
      error.value = '笔记加载失败，请返回列表重试'
    } finally {
      loading.value = false
    }
  }

  function registerImage(id: number, url: string): void {
    tokenByUrl.set(url, `note-file://${id}`)
  }

  async function applyDraft(): Promise<void> {
    const draft = pendingDraft.value
    if (!draft) return
    revokeImages()
    form.title = draft.title
    form.subject_id = draft.subject_id
    form.tags = [...draft.tags]
    form.content_md = await hydrateImages(draft.content_md)
    pendingDraft.value = null
  }

  function discardDraft(): void {
    clearDraft(noteId.value)
    pendingDraft.value = null
  }

  function writeCurrentDraft(): void {
    const raw = currentRaw()
    const empty =
      !raw.title && !raw.content_md.trim() && raw.subject_id === null && raw.tags.length === 0
    if (empty) {
      clearDraft(noteId.value)
      return
    }
    writeDraft(noteId.value, {
      ...raw,
      draftSavedAt: new Date().toISOString(),
      baseUpdatedAt: updatedAt.value,
    })
  }

  async function save(): Promise<boolean> {
    const raw = currentRaw()
    const validation = validateForm(raw)
    if (validation) {
      error.value = validation
      return false
    }
    if (!dirty.value) return true
    saving.value = true
    error.value = ''
    try {
      if (noteId.value === null) {
        const created = await createNote(raw)
        clearDraft(null)
        clearDraft(created.id)
        saved.value = {
          title: created.title,
          content_md: created.content_md,
          subject_id: created.subject_id,
          tags: [...(created.tags ?? [])],
        }
        updatedAt.value = created.updated_at
        form.title = created.title
        noteId.value = created.id
        options.onCreated?.(created.id)
        return true
      }
      const patch: NoteUpdatePayload = {}
      if (raw.title !== saved.value.title) patch.title = raw.title
      if (raw.content_md !== saved.value.content_md) patch.content_md = raw.content_md
      if (raw.subject_id !== saved.value.subject_id) patch.subject_id = raw.subject_id
      if (JSON.stringify(raw.tags) !== JSON.stringify(saved.value.tags)) patch.tags = raw.tags
      if (Object.keys(patch).length === 0) return true
      const updated = await updateNote(noteId.value, patch)
      saved.value = {
        title: updated.title,
        content_md: updated.content_md,
        subject_id: updated.subject_id,
        tags: [...(updated.tags ?? [])],
      }
      updatedAt.value = updated.updated_at
      form.title = updated.title
      clearDraft(noteId.value)
      return true
    } catch {
      error.value = '保存失败，请稍后重试'
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    form,
    loading,
    saving,
    error,
    pendingDraft,
    imageFailures,
    dirty,
    load,
    save,
    applyDraft,
    discardDraft,
    writeCurrentDraft,
    registerImage,
    revokeImages,
  }
}
```

- [ ] **Step 4: 写编辑页**

`web/src/views/notes/NoteEditView.vue`：

```vue
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listSubjects } from '@/api/kp'
import MarkdownEditor from '@/components/notes/MarkdownEditor.vue'
import TagInput from '@/components/notes/TagInput.vue'
import type { SubjectOut } from '@/types/kp'
import { useNoteEditor } from '@/views/notes/useNoteEditor'

const route = useRoute()
const router = useRouter()
const initialId = route.name === 'note-edit' ? Number(route.params.id) : null
const currentId = ref<number | null>(initialId)
const subjects = ref<SubjectOut[]>([])
const ready = ref(false)
const draftAt = ref<Date | null>(null)
let draftTimer: ReturnType<typeof setTimeout> | undefined

const editor = useNoteEditor(currentId, {
  onCreated: (id) => {
    void router.replace({ name: 'note-edit', params: { id } })
  },
})
const { form, loading, saving, error, dirty, pendingDraft, imageFailures } = editor

const statusText = computed(() => {
  if (saving.value) return '保存中…'
  if (draftAt.value) {
    return `草稿已保存 ${draftAt.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`
  }
  return dirty.value ? '未保存' : '已保存'
})

function scheduleDraft(): void {
  if (!ready.value || saving.value || !dirty.value) return
  if (draftTimer) clearTimeout(draftTimer)
  draftTimer = setTimeout(() => {
    editor.writeCurrentDraft()
    draftAt.value = new Date()
  }, 800)
}

async function maybeRestoreDraft(): Promise<void> {
  if (!pendingDraft.value) return
  try {
    await ElMessageBox.confirm('发现一份本地草稿，是否恢复？', '恢复草稿', {
      confirmButtonText: '恢复',
      cancelButtonText: '丢弃',
      showClose: false,
      closeOnClickModal: false,
      closeOnPressEscape: false,
    })
    await editor.applyDraft()
    ElMessage.success('已恢复本地草稿')
  } catch {
    editor.discardDraft()
  }
}

async function onSave(): Promise<void> {
  if (!dirty.value) {
    ElMessage.info('没有需要保存的修改')
    return
  }
  const ok = await editor.save()
  if (ok) {
    if (draftTimer) clearTimeout(draftTimer)
    draftAt.value = null
    ElMessage.success('已保存')
  }
}

function onBeforeUnload(event: BeforeUnloadEvent): void {
  event.preventDefault()
  event.returnValue = ''
}

watch(
  () => [form.title, form.content_md, form.subject_id, form.tags],
  scheduleDraft,
  { deep: true },
)

watch(dirty, (value) => {
  if (value) window.addEventListener('beforeunload', onBeforeUnload)
  else window.removeEventListener('beforeunload', onBeforeUnload)
})

onMounted(async () => {
  try {
    subjects.value = await listSubjects()
  } catch {
    subjects.value = []
  }
  await editor.load()
  ready.value = true
  await maybeRestoreDraft()
})

onUnmounted(() => {
  if (draftTimer) clearTimeout(draftTimer)
  window.removeEventListener('beforeunload', onBeforeUnload)
  editor.revokeImages()
})

onBeforeRouteLeave(async () => {
  if (saving.value) {
    ElMessage.warning('正在保存，请稍候')
    return false
  }
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的修改，已自动保存为本地草稿。仍要离开吗？', '离开笔记', {
      confirmButtonText: '离开',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
})
</script>

<template>
  <div class="edit-page">
    <header class="edit-header">
      <button class="back" type="button" @click="router.push({ name: 'notes' })">← 笔记</button>
      <span class="status" data-testid="save-status">{{ statusText }}</span>
      <el-button
        type="primary"
        data-testid="save-note"
        :loading="saving"
        @click="onSave"
      >保存</el-button>
    </header>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error && !form.title" class="load-error">
      <p>{{ error }}</p>
      <el-button @click="router.push({ name: 'notes' })">返回笔记列表</el-button>
    </div>
    <template v-else>
      <input
        v-model="form.title"
        class="title-input"
        data-testid="note-title"
        maxlength="200"
        aria-label="笔记标题"
        placeholder="无标题笔记"
      />
      <div class="meta-row">
        <el-select
          v-model="form.subject_id"
          class="subject-select"
          placeholder="未分类"
          clearable
        >
          <el-option v-for="item in subjects" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <TagInput v-model="form.tags" />
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-if="imageFailures" class="form-warning">
        {{ imageFailures }} 张图片加载失败；保存时不会丢失引用。
      </p>
      <MarkdownEditor
        v-model="form.content_md"
        @save="onSave"
        @upload-error="ElMessage.error('图片上传失败')"
        @image-uploaded="(payload) => editor.registerImage(payload.id, payload.url)"
      />
    </template>
  </div>
</template>

<style scoped>
.edit-page { display: grid; gap: 12px; }
.edit-header {
  display: flex; gap: 16px; align-items: center;
  min-height: 40px;
}
.back {
  padding: 4px 0; color: var(--app-text-secondary); font-size: 13px;
  background: none; border: none; cursor: pointer;
}
.back:hover { color: var(--app-primary); }
.status { margin-left: auto; color: var(--app-text-tertiary); font-size: 12px; }
.title-input {
  width: 100%; padding: 4px 0; color: var(--app-text); font-size: 26px; font-weight: 600;
  background: none; border: none; border-bottom: 1px solid transparent; outline: none;
}
.title-input:focus { border-bottom-color: var(--app-primary); }
.meta-row { display: flex; gap: 12px; align-items: center; }
.subject-select { width: 180px; }
.form-error { margin: 0; color: var(--app-danger); font-size: 13px; }
.form-warning { margin: 0; color: var(--app-warning); font-size: 13px; }
.loading, .load-error { padding: 64px; color: var(--app-text-secondary); text-align: center; }
</style>
```

- [ ] **Step 5: 写编辑页测试**

`web/src/views/notes/NoteEditView.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import NoteEditView from './NoteEditView.vue'

vi.mock('@/api/notes', () => ({
  getNote: vi.fn(),
  createNote: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
}))
vi.mock('@/api/kp', () => ({ listSubjects: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/files', () => ({
  getImageBlob: vi.fn(),
  uploadImage: vi.fn(),
}))

import { createNote, getNote, updateNote } from '@/api/notes'

const EditorStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue', 'save', 'upload-error', 'image-uploaded'],
  setup(props, { emit }) {
    return () =>
      h('textarea', {
        'data-testid': 'note-body',
        value: props.modelValue,
        onInput: (event: Event) =>
          emit('update:modelValue', (event.target as HTMLTextAreaElement).value),
      })
  },
})

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/notes', name: 'notes', component: { template: '<div />' } },
      { path: '/notes/new', name: 'note-new', component: NoteEditView },
      { path: '/notes/:id/edit', name: 'note-edit', component: NoteEditView },
    ],
  })
}

async function mountAt(path: string) {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(NoteEditView, {
    global: {
      plugins: [router, ElementPlus],
      stubs: { MarkdownEditor: EditorStub },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('NoteEditView', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.mocked(getNote).mockReset()
    vi.mocked(createNote).mockReset()
    vi.mocked(updateNote).mockReset()
  })

  it('loads an existing note', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 5,
      title: '函数单调性',
      content_md: '# 正文',
      subject_id: 7,
      tags: ['函数'],
      folder: null,
      source_file_id: null,
      created_at: '2026-10-27T01:00:00+00:00',
      updated_at: '2026-10-27T02:00:00+00:00',
    })
    const { wrapper } = await mountAt('/notes/5/edit')
    expect((wrapper.find('[data-testid="note-title"]').element as HTMLInputElement).value).toBe(
      '函数单调性',
    )
  })

  it('creates a note from the new page', async () => {
    vi.mocked(createNote).mockResolvedValue({
      id: 9,
      title: '新笔记',
      content_md: '正文',
      subject_id: null,
      tags: [],
      folder: null,
      source_file_id: null,
      created_at: '2026-10-27T01:00:00+00:00',
      updated_at: '2026-10-27T02:00:00+00:00',
    })
    const { wrapper, router } = await mountAt('/notes/new')
    await wrapper.find('[data-testid="note-title"]').setValue('新笔记')
    await wrapper.find('[data-testid="note-body"]').setValue('正文')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(createNote).toHaveBeenCalledWith({
      title: '新笔记',
      content_md: '正文',
      subject_id: null,
      tags: [],
    })
    expect(router.currentRoute.value.name).toBe('note-edit')
    expect(router.currentRoute.value.params.id).toBe('9')
  })

  it('patches only the changed title', async () => {
    vi.mocked(getNote).mockResolvedValue({
      id: 5,
      title: '旧标题',
      content_md: '正文',
      subject_id: null,
      tags: [],
      folder: null,
      source_file_id: null,
      created_at: '2026-10-27T01:00:00+00:00',
      updated_at: '2026-10-27T02:00:00+00:00',
    })
    vi.mocked(updateNote).mockResolvedValue({
      id: 5,
      title: '新标题',
      content_md: '正文',
      subject_id: null,
      tags: [],
      folder: null,
      source_file_id: null,
      created_at: '2026-10-27T01:00:00+00:00',
      updated_at: '2026-10-27T03:00:00+00:00',
    })
    const { wrapper } = await mountAt('/notes/5/edit')
    await wrapper.find('[data-testid="note-title"]').setValue('新标题')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(updateNote).toHaveBeenCalledWith(5, { title: '新标题' })
  })

  it('does not send an invalid new note', async () => {
    const { wrapper } = await mountAt('/notes/new')
    await wrapper.find('[data-testid="note-body"]').setValue('只有正文')
    await wrapper.find('[data-testid="save-note"]').trigger('click')
    await flushPromises()
    expect(createNote).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('标题不能为空')
  })

  it('restores a pending draft when confirmed', async () => {
    localStorage.setItem(
      'study-agent:note-draft:v1:new',
      JSON.stringify({
        title: '草稿标题',
        content_md: '草稿正文',
        subject_id: null,
        tags: [],
        draftSavedAt: '2026-10-27T02:00:00.000Z',
        baseUpdatedAt: null,
      }),
    )
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    const { wrapper } = await mountAt('/notes/new')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect((wrapper.find('[data-testid="note-title"]').element as HTMLInputElement).value).toBe(
      '草稿标题',
    )
    confirm.mockRestore()
  })
})
```

- [ ] **Step 6: 跑编辑器测试**

```bash
cd web && npm run test:run -- src/views/notes/NoteEditView.spec.ts
```

Expected: 5 条通过。若 `onMounted` 的 `listSubjects`/`getNote` 尚未 flush，
补 `await flushPromises()`；如 Element Plus 的 MessageBox 被全局 toast 干扰，
断言 `createNote` 调用即可。

- [ ] **Step 7: 验证 blob 图片预览（真实浏览器小探针）**

启动前后端后，在临时 HTML/浏览器控制台执行：

```js
const blob = await (await fetch('http://127.0.0.1:8000/api/v1/files/1/image', {
  headers: { Authorization: 'Bearer ' + localStorage.getItem('study-agent-token') }
})).blob()
const url = URL.createObjectURL(blob)
const md = `![x](${url})`
// 把 md 放进编辑器，确认预览 <img> 的 src 未被清空、naturalWidth > 0
```

若 Blob URL 被 sanitize 掉，**不要改全局 `sanitize` 放行任意 HTML**；
改为把图片转 data URL 预览（仅预览、保存仍 token），并在执行记录写明。
真实完整流程在 Task 5 再跑。

- [ ] **Step 8: 跑全量测试与构建**

```bash
cd web && npm run test:run
cd web && npm run build
```

Expected: 27+ 条全绿；构建通过（编辑器 chunk 会变大，记录警告，不顺手拆包）。

- [ ] **Step 9: Commit**

```bash
git add web/src/components/notes web/src/views/notes/useNoteEditor.ts web/src/views/notes/NoteEditView.vue web/src/views/notes/NoteEditView.spec.ts
git commit -m "feat(s2-12): Markdown 编辑页、草稿与离开保护"
```

---

## Task 5: 真实联调、截图与修正

**Files:**
- Create temporaries only (不入库): `web/.tmp-e2e-note.mjs`、`/tmp/s212-*.png`
- 可修：前面任务涉及的任何真实 bug（单独 fix commit）

**Interfaces:**
- Consumes: 全部前后端实现。
- Produces: 真实证据（DOM/DB/截图）、修正 commit。

- [ ] **Step 1: 起服务**

```bash
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
cd web && npm run dev -- --host 127.0.0.1 --port 5173
```

两者都用后台 job；健康检查：

```bash
curl -s http://127.0.0.1:8000/health
curl -s -o NUL -w "%{http_code}" http://localhost:5173/login
```

- [ ] **Step 2: 准备 PNG**

```bash
cd /tmp && ../e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe - <<'PY'
import base64, pathlib
png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
pathlib.Path("/tmp/s212-pixel.png").write_bytes(png)
PY
```

- [ ] **Step 3: 浏览器流程**

用无头 Chrome + CDP（复用 S2-11 的 `.tmp-e2e-*.mjs` 模式），1440×900：

1. 注册 `s212_e2e_<ts>` / `Password123!`，进 `/notes`。
2. 点“新建笔记”；`[data-testid=note-title]` 输入“函数单调性验收”。
3. 聚焦 `.cm-content`，用 `Input.insertText` 输入：

```markdown
# 单调性

定义：区间内自变量增大时函数值也增大。

$$\int_0^1 x^2 dx = \frac{1}{3}$$

![像素图](note-file://FILE_ID)
```

4. 点工具栏图片按钮，等待 `input[type=file]`，用 CDP `DOM.setFileInputFiles` 上传
   `/tmp/s212-pixel.png`；等待 `img[src^="blob:"]` 出现。
5. 断言预览 `.katex` 存在、`img.naturalWidth > 0`；正文区含 `note-file://`。
6. 点“保存”；等待 URL 变 `/notes/<id>/edit`；查 DB：
   `SELECT content_md FROM notes WHERE id=<id>` 含 `note-file://`，不含 `http://127.0.0.1:9000`、`X-Amz`。
7. `Page.reload()` 等加载完成；断言标题、`.katex`、`img.naturalWidth > 0` 仍成立。
8. 改标题不保存，等 1.2s；读 localStorage 草稿 key 存在；点侧栏“文件”出现离开确认；
   点“继续编辑”内容还在；再点侧栏并“离开”，回笔记列表；重新打开该笔记，出现
   “恢复草稿”弹窗；点“恢复”，标题为草稿值；保存后 localStorage 草稿 key 消失。
9. 列表：新建第二篇笔记（无图），测试关键词/学科筛选、排序、page_size=10/20、删除；
   删除确认不可点穿。
10. 打开 `/not-exist`、`/403` 仅做回归，确认未被笔记路由抢走。
11. 截图：列表、编辑页（公式+图片）、离开确认/草稿恢复。
12. 记录 console error、横向滚动 `document.documentElement.scrollWidth <= innerWidth`。

- [ ] **Step 4: 清理**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM note_kps WHERE note_id IN (SELECT id FROM notes WHERE user_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%'));"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM note_chunks WHERE user_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%');"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM notes WHERE user_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%');"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM async_tasks WHERE user_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%');"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM files WHERE user_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%');"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM user_relations WHERE student_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%') OR teacher_id IN (SELECT id FROM users WHERE username LIKE 's212_e2e_%');"
docker exec study-agent-postgres psql -U study -d study_agent -c \
"DELETE FROM users WHERE username LIKE 's212_e2e_%';"
# 清理后核对计数为 0
docker exec study-agent-postgres psql -U study -d study_agent -tAc \
"SELECT (SELECT count(*) FROM users WHERE username LIKE 's212_e2e_%') + (SELECT count(*) FROM notes WHERE user_id NOT IN (SELECT id FROM users));"
```

目标：`users/notes/files` 中验收数据为 0；临时脚本删除。

- [ ] **Step 5: 修正与复跑**

任何失败先复现→定位→补测试→修；真实 bug 单独 `fix(s2-12): ...` commit。
最后再跑：

```bash
cd web && npm run test:run && npm run build
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```

---

## Task 6: 文档同步与收尾

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s2-12-notes-ui.md` §15
- Modify: `docs/plan/s2-12-notes-ui.md` 执行记录

- [ ] **Step 1: PROGRESS**

- 当前状态“最近完成”改为 S2-12，下一步 S2-13。
- S2-12 勾选。
- 新增遗留：草稿仅本地、无阅读页/文件夹/标签筛选、图片 token 对导出不友好、图片一次性读内存、无压缩、编辑器包大、删除笔记不删图。
- 变更日志新增 `### 2026-10-27（S2-12）`：交付、决策、测试数、真实联调、偏差、已知不足。

- [ ] **Step 2: DECISIONS D-032**

写：表格 vs 卡片、直接编辑、本地草稿、图片 token+blob、parse=false、取图接口、md-editor 懒加载、筛选范围；验证与代价；已知不足。

- [ ] **Step 3: 实施计划勾选**

`docs/AI协作开发实施计划.md` 中 `- [ ] S2-12 ...` 改 `[x]`。

- [ ] **Step 4: spec/plan 执行记录**

spec §15 填 commits、测试数、真实联调结果、偏差、截图/清理。
plan 末尾加“执行记录”节，写同样内容 + 未做项。

- [ ] **Step 5: 最终验证**

```bash
cd web && npm run test:run && npm run build
cd backend && ../.venv/Scripts/python.exe -m pytest -q
git status --short
```

- [ ] **Step 6: Commit**

```bash
git add docs
git commit -m "docs(s2-12): 笔记列表与编辑器验收记录"
```

---

## Self-Review

- **Spec coverage**：列表（Task 3）、编辑/草稿/离开（Task 4）、图片契约（Task 1+2+4）、测试/验收（Task 5）、文档（Task 6）；无遗漏章节。
- **Placeholder scan**：无 TBD/TODO；Task 3 的临时编辑页在 Task 4 明确替换。
- **Type consistency**：`NoteCreatePayload`/`NoteUpdatePayload`、`DraftState`、`ListQueryState`、`registerImage(id,url)`、`image-uploaded {id,url}` 在各任务间一致。
- **已知计划内偏差**：`NoteListView` 测试用 `input` 或 `ElInput` 触发防抖，若 Element Plus 版本差异按测试失败信息调整；`md-editor-v3` 的 blob 预览在 Task 4 Step 7 做探针，不允许假设。

---

## 执行记录（2026-10-27）

- 计划提交 `e334cf2`；实施提交：`1ff82ae` 后端图片契约、`9bd5033` 前端 API/类型/工具、`aa1ef6d` 列表/路由/导航、`4479991` 编辑页/草稿、`1f232be` 时间与新笔记状态。
- 测试：前端 **39 passed / 10 files**（新增 22）；后端 **506 passed**；`npm run build` 通过（编辑页 405 KB / gzip 140 KB）。
- 真实联调结果见 `docs/spec/s2-12-notes-ui.md` §15；关键证据：note 37 / file 8、`note-file://8`、刷新后 `.katex=1` 且图片 `naturalWidth=64`、草稿 key 恢复/清除、列表 12→2→12→1→6→删除 11、console error 0、无横向滚动。
- 偏差：① 新建保存路由被 leave guard 误拦 → `finally` 中 `saving=false` 后回调；② 列表时间改本地时区；③ 空白新笔记状态改“新笔记”；④ 行点击单测改为对 `ElTable` 发 `row-click`；⑤ headless 下 md-editor 裁剪弹窗不可用，走“上传图片”下拉 + `DOM.setFileInputFiles`。
- 清理：验收用户/笔记/文件/任务/MinIO 对象全部删除，计数 0；临时 CDP 脚本与截图未入库。
- 未做项：阅读页、文件夹、标签筛选、版本历史、回收站、移动端、服务端草稿、图片压缩/缩略图、删除联动。
