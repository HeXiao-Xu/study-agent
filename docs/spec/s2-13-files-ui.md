# S2-13 前端文件上传与解析状态 — 设计 Spec

- 日期：2026-10-29
- 状态：待用户复核
- 上游：S2-6 文件上传 + 去重、S2-7 异步任务、S2-8 文档解析与切片、S2-11 应用壳
- 下游：S2-14 知识点树、S3 问答引用切片
- 任务卡原文：`components/FileUploader.vue`、`views/files/Index.vue`；拖拽上传、进度条、失败重试；解析中 3 秒轮询、最多 5 分钟；完成后展示切片预览

## 1. 目标

把 `/files` 从占位页替换成可用的文件工作台：

1. 学生拖拽或点选 PDF / Word / Markdown / TXT，看到真实上传进度。
2. 上传成功后自动进入解析，页面每 3 秒更新状态，最多轮询 5 分钟。
3. 解析完成后显示切片数量，并能预览前 3 条切片。
4. 刷新页面、重新登录后仍能看到自己的历史文件及解析结果。
5. 失败可见原因；本次会话内可用原文件重试。

## 2. 非目标

- 不做文件删除、下载、重命名、文件夹、回收站。
- 不做服务端「按文件 id 重试」接口；刷新后的历史失败记录只能重新选择文件上传。
- 不做完整切片列表/分页，只预览前 3 条。
- 不接受图片进入文件页：S2-8 尚未支持 OCR，图片仍只在笔记编辑器里作为插图（`parse=false`）。
- 不做上传断点续传、并发上传、后台轮询；离开页面即停止轮询。
- 不新增数据库迁移，不新增前端依赖。

## 3. 已确认决策

| # | 决策 | 选择 |
|---|---|---|
| 1 | 文件历史范围 | **持久文件列表**：新增 `GET /files`，刷新/重新登录仍可见 |
| 2 | 切片展示 | **块数 + 前 3 条文本**，用抽屉预览 |
| 3 | 解析失败重试 | **前端重新上传原文件**；不新增重试接口 |
| 4 | 可上传类型 | **只收可解析文档**：`.pdf/.docx/.md/.txt`；图片不进入此页 |
| 5 | 页面形态 | 上传区 + 文件表格 + 切片抽屉；与笔记页一致 |
| 6 | 上传队列 | 多选、串行上传；不并发 |
| 7 | 轮询 | 上传项每 3 秒、最多 5 分钟；页面里的历史解析中文件也轮询，规则相同 |

## 4. 后端契约

### 4.1 `GET /api/v1/files`

- 权限：登录用户，**仅返回本人文件**（`WHERE user_id = 当前用户`）；不返回他人文件，也不因角色放宽。
- 类型：同步分页。
- 入参：`page`（默认 1，≥1）、`page_size`（默认 20，1–100）。
- 排序：固定 `created_at DESC, id DESC`，不开放 `sort_by`。
- 出参：`Envelope[PageData[FileSummaryOut]]`，`PageData` 复用 S2-4 的 `{items,total,page,page_size}`。
- `FileSummaryOut`：
  - `id` / `filename` / `mime` / `size`
  - `parse_status`（`pending|parsing|done|failed`）
  - `parse_progress`（0–100）
  - `error_msg`（失败原因，成功为 null）
  - `chunk_count`（从 `parse_result_json.chunks` 读取；无结果/非法值返回 0）
  - `created_at` / `parse_finished_at`
- 错误：`422/42200` 分页越界或非整数；未登录 401。

### 4.2 `GET /api/v1/files/{file_id}/parse-status`

在 S2-6 现有字段上增加：

- `chunk_count: int`：同 `FileSummaryOut`，从 `parse_result_json.chunks` 读取，默认 0。

其余字段、权限、错误保持不变（本人或已绑定该学生的 parent/teacher；404/403/422）。

### 4.3 `GET /api/v1/files/{file_id}/chunks`

- 权限：与 `parse-status` 一致，复用 `get_file_status`；admin 不绕过。
- 入参：`limit`（默认 3，1–20）。
- 查询：`note_chunks WHERE source_file_id = file_id AND user_id = file.user_id ORDER BY chunk_index ASC LIMIT limit`。
- 出参：`Envelope[list[ChunkPreviewOut]]`，未解析完返回空数组。
- `ChunkPreviewOut`：`chunk_index`（原始 0 基序号）/ `content`（该块 Markdown 纯文本）/ `token_count`。
- 错误：文件不存在 404；无权 403；`limit` 越界 422；不因无切片报 404。

### 4.4 模型/服务改动

- `File` 增加只读属性 `chunk_count`：
  ```python
  @property
  def chunk_count(self) -> int:
      raw = (self.parse_result_json or {}).get("chunks")
      return int(raw) if isinstance(raw, int) and raw >= 0 else 0
  ```
- `file_service.list_files(session, *, owner, params) -> PageData[FileSummaryOut]`。
- `file_service.list_chunks(session, *, file_id, viewer, limit) -> list[NoteChunk]`，权限统一走 `get_file_status`。
- 路由层只做参数校验和组装，不写业务查询。
- 不改表结构、不改上传/去重/解析 Worker 逻辑。

### 4.5 API 文档同步

`docs/API.md` §3 增加上述两个接口，并更新 `parse-status` 的 `chunk_count` 与“客户端 3 秒轮询、最多 5 分钟”的说明；§12 待定接口清单把“文件列表”标记为 S2-13 已交付，删除/下载仍待后续。

## 5. 前端结构

### 5.1 文件

| 文件 | 职责 |
|---|---|
| `web/src/types/files.ts` | `ParseStatus`、`FileSummary`、`FileStatus`、`ChunkPreview`、`FileListParams` |
| `web/src/api/files.ts` | 新增 `uploadDocument` / `listFiles` / `getFileStatus` / `listFileChunks`；保留 `uploadImage` / `getImageBlob` |
| `web/src/views/files/constants.ts` | 可接受扩展名、状态文案/颜色、轮询间隔与上限、示例文件说明 |
| `web/src/views/files/useFileUploads.ts` | 上传队列、真实进度、状态轮询、超时、重试、清理 |
| `web/src/components/files/FileUploader.vue` | 拖拽/点选区 + 队列卡片 + 进度条 + 错误/重试 |
| `web/src/views/files/FileListView.vue` | 列表、分页、状态标签、错误态/空态、切片抽屉、历史解析中轮询 |
| `web/src/router/index.ts` | `/files` 改真实页面，`meta: { title:'文件', nav:'files', roles:['student'] }` |

### 5.2 上传 API

```ts
uploadDocument(file: File, onProgress?: (percent: number) => void): Promise<FileUploadOut>
```

- `POST /api/v1/files`，`FormData` 字段 `file`，query `parse=true`，超时 5 分钟。
- `onUploadProgress` 仅在 `event.total > 0` 时换算 0–100。
- 后端 201/200 都视为成功；`deduped=true` 不特殊处理，继续查状态。
- 文件类型前端先校验，后端仍做最终 magic/大小校验；组件内保留局部错误文案，同时沿用 `http.ts` 的全局错误提示，不重复弹第二次。

### 5.3 上传队列状态机

每个任务：

```ts
type UploadPhase = 'uploading' | 'pending' | 'parsing' | 'done' | 'failed' | 'timeout'

interface UploadTask {
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
}
```

流程：

1. 选择/拖入文件 → 校验扩展名 → 入队。
2. 串行取队首：`uploadDocument`，`progress` 显示上传百分比。
3. 上传成功 → 立即 `getFileStatus(recordId)` 一次：
   - `done`：显示 `完成 · N 块`，进入终态。
   - `failed`：显示 `error_msg`，进入终态。
   - `pending/parsing`：进入轮询。
4. 轮询每 3 秒，直到 `done/failed` 或从上传成功起超过 5 分钟：
   - 超时 → `相位=timeout`，文案「解析超时，请刷新查看」，停止轮询。
5. 终态触发 `finished` 事件；页面刷新列表。
6. 失败时若仍持有原 `File`，显示「重试」：重置该任务为 `uploading` 并重新上传同一文件；后端 sha256 去重后补入队。
7. 上传 HTTP 失败：`phase=failed`，`error` 取后端 message 或「上传失败」，保留原文件可重试。

队列展示：

- 每项：文件名、大小、进度条、状态文案、错误文案、重试按钮（仅失败且文件仍在）。
- 上传中进度条用真实百分比；解析中显示 `parse_progress`（0/10/50/80/100）。
- 队列不因完成自动消失；提供「清空已完成」按钮。
- 同一文件重复选择允许（用于重试/重新解析），靠后端去重。

### 5.4 文件列表

- 进入页面加载第 1 页，页大小默认 10，可切 10/20/50。
- 列：
  1. 文件名（长名省略 + title）
  2. 类型/大小：`PDF · 1.2 MB`，未知类型显示扩展名
  3. 状态：标签 + 进度条/错误 tooltip
  4. 切片数：`—`（未完成）/`N 块`
  5. 上传时间：本地时区 `YYYY-MM-DD HH:mm`
  6. 操作：`切片预览`（仅 done）；失败行显示「查看错误」，不提供历史重试
- 空态：
  - 无任何文件：「还没有文件」+「上传第一份资料」，引导到上传区。
  - 有错误：错误条 + 「重试」。
- 分页：与笔记页一致的 `el-pagination`；当前页删/无数据不涉及删除。
- 页面打开时，对 `pending/parsing` 行启动 3 秒轮询，最多 5 分钟；终止后刷新该页，拿到 `chunk_count`。上传队列中的新文件由 uploader 自己轮询，避免双轮询。

### 5.5 切片抽屉

- 点击「切片预览」→ 右侧 `el-drawer`，标题为文件名。
- 内容：最多 3 条，按 `chunk_index` 升序：
  - `#1 · 123 tokens`
  - 文本区域等宽/可滚动，保留换行，不用 Markdown 渲染。
- 加载中 skeleton/`v-loading`；请求失败显示错误 + 重试。
- 空切片显示「该文件没有可预览的切片」。

## 6. 交互与错误

- 选择文件时若包含不支持类型：该文件不入队，就地提示支持的类型；其他合法文件继续。
- 上传大小超过后端上限：显示后端 `413` 文案；不截断。
- 上传/解析期间按钮不禁用整页；只对当前上传项显示状态。
- 轮询请求失败：该次跳过，下一轮继续；连续失败不终止，直到 5 分钟超时或终态。
- 401 仍走全局跳登录；403/404 显示后端文案。
- 卸载页面：清 interval，避免离开后继续请求。
- 可访问性：上传区支持键盘 Enter/Space 打开文件选择；进度条与错误用 `aria-live="polite"`。

## 7. 测试计划

### 7.1 后端（约 6 条）

| 用例 | 断言 |
|---|---|
| `GET /files` 分页 | `{items,total,page,page_size}`；仅本用户；`chunk_count` 正确 |
| `GET /files` 未登录 | 401 |
| `parse-status` 含块数 | `parse_result_json={"chunks":4}` → `chunk_count=4`；null → 0 |
| `GET chunks` 顺序/limit | 只取该 `source_file_id`，`chunk_index` 升序，`limit` 生效 |
| `GET chunks` 越权 | 他人文件 → 403/40300 |
| `GET chunks` 不存在 | 404/40400 |

### 7.2 前端（约 10 条）

| 用例 | 断言 |
|---|---|
| 只接受文档 | 选择 `.png` 不入队，提示支持类型 |
| 上传进度 | 回调 42% → 进度条/文案 42% |
| 上传成功→解析中 | 上传后调用 status，显示「解析中」 |
| 轮询到完成 | 3 秒后 status=done，显示「完成 · 3 块」，触发 finished |
| 解析失败→重试 | 显示 error_msg；点重试再次调用 uploadDocument |
| 5 分钟超时 | 推进定时器后停止轮询，显示超时 |
| 列表渲染 | 文件名/类型/大小/状态/块数/时间 |
| 空态/错误态 | 无文件显示引导；加载失败可重试 |
| 分页 | 切页调用 `page=2` |
| 切片抽屉 | 调用 `chunks?limit=3`，展示 3 条 |

### 7.3 真实联调

Chrome/CDP，1440×900，真实 Postgres/Redis/MinIO/ARQ：

1. 注册/登录学生，进 `/files`。
2. 上传一份含 3 道题的 PDF（验收时后端设 `PARSE_FORCE_PYMUPDF=true` 走快速路径；生产默认不变）。
3. 观察上传百分比 → `解析中` → `完成 · N 块`（N>0）。
4. 表格出现该文件，刷新页面后仍在；切片预览返回前 3 条，序号从 1 开始。
5. 上传非法类型（如 `.png`）被前端拒绝；失败重试用同一文件仍成功（若构造失败场景）。
6. console error 0；无横向滚动。
7. 清理验收用户、文件、笔记、chunks、async_tasks、MinIO 对象；计数回 0。

## 8. 验收

- 上传试卷 → 进度条 → 完成后能看到自动切出的块数量。
- 刷新后文件与解析结果仍在。
- 预览能读到前 3 条切片。
- 类型校验、错误态、空态、分页可用。
- `npm run test:run`、`npm run build`、后端 `pytest` 全绿。
- 不出现 MinIO endpoint/预签名参数。

## 9. 文档同步

- `docs/API.md` §3：列表、chunks、`chunk_count`、轮询说明。
- `docs/DECISIONS.md` D-033：持久列表、文档类型、前端重试、轮询上限。
- `docs/PROGRESS.md`：S2-13 勾选、遗留问题（无删除/下载、重试仅本次会话、无完整切片分页、图片 OCR 未支持）。
- `docs/AI协作开发实施计划.md`：S2-13 勾选。
- 本 spec §10、plan 执行记录：提交、测试数、真实联调、偏差。
- `SCHEMA.md` 不改（无迁移）。

## 10. 执行记录

（实施后回填：commit、测试数、浏览器实测、偏差。）

## 11. 已知限制

- 文件页只收可解析文档；图片 OCR 未支持。
- 无删除/下载，文件与生成的笔记/切片没有删除联动。
- 刷新后历史失败文件不能一键重试，只能重新选文件；上传队列本身也不跨刷新保存。
- 只预览前 3 条切片，不能翻页看全部。
- 轮询最多 5 分钟；超时后需手动刷新，后台解析可能仍在继续。
- 串行上传，多文件时后面的文件要等待。
- 文件列表无搜索/状态筛选，只按上传时间倒序和分页。