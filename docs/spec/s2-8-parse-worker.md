# S2-8 文档解析 Worker + 进度回写 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-8
- 日期：2026-10-26
- 状态：已实现并验收（2026-10-26；pytest 425/425 + 真实 PDF/损坏 PDF/md/png + 真实 Embedding 证据；实施记录见 docs/plan/s2-8-parse-worker.md）
- 上游：S1-1 解析门面、S1-2 切片器、S1-3 入库编排、S2-5 笔记表、S2-6 文件上传、S2-7 任务框架、迁移 0004 为当前 head
- 下游：S2-10 对齐（消费文档笔记与 chunk）、S3-1 索引服务、S3-5 前端轮询
- 产物：迁移 `0005_s2_8_parse_progress.py`、`tasks/parse_document.py`、`ai/parse/__init__.py` 文本支路、`file_service` 上传后入队、`FileStatusOut`、测试与真实 PDF 验收

## 1. 目标

1. 上传成功后自动入队 `parse.document`，Worker 复用 `parse_document → chunk_document → index_chunks`，**不另写解析/切片/向量化**。
2. `files.parse_status` 状态机 `pending → parsing → done / failed`，失败写 `error_msg`（可读、≤500 字），并记录 `parse_started_at / parse_finished_at / parse_progress(0–100)`。
3. 解析文本落一条“文档笔记”（`notes.source_file_id = files.id`），切片写 `note_chunks`，RAG 与 S2-10 无需改契约。
4. 幂等：同一文件重复上传（去重命中）且已 `done` 时不重复入队；任务重投时 `done` 直接跳过；重复执行会覆盖同一笔记的 chunks。
5. 损坏 PDF / 扫描件 / 图片 / 空文本 → `failed` + 可读 `error_msg`，不静默成功。

非目标：OCR（S3-x）、错误详情分页/日志回放、前端代码、S2-10 知识点对齐、手动重解析接口、批量解析。

## 2. 范围

### 2.1 做

- 迁移 0005：`files` 增加 `error_msg`、`parse_progress`、`parse_started_at`、`parse_finished_at`，补 `parse_status` 与 `parse_progress` 的 CHECK。
- `app/models/enums.py`：新增 `ParseStatus`（`pending/parsing/done/failed`）。
- `app/ai/parse/__init__.py`：`.md/.txt` 走 `parse_plain_text`（UTF-8，`errors="replace"`），`ParserName` 增加 `text`。
- `app/tasks/parse_document.py`：任务名 `parse.document`，payload `{"file_id": int}`。
- `app/api/v1/files.py`：上传成功后按状态入队；`FileStatusOut` 增加 `error_msg`、`parse_progress`。
- `app/schemas/files.py`：同步字段。
- 测试：`tests/test_parse_document.py`（约 17）+ `tests/test_files_api.py` 增补（约 4）+ `tests/test_parse_text.py`（2）。

### 2.2 不做

- 不给上传接口新增字段；不返回 `task_id`（前端按 `file_id` 轮询 `/parse-status`）。
- 不新增手动重解析接口（失败重试靠重新上传，去重命中且 `failed` 会重新入队）。
- 不允许图片解析成功：`png/jpg/jpeg` 一律 `failed` +「图片解析暂未支持（待 OCR）」。
- 不改 `note_chunks` 结构，不把 `note_id` 改可空。
- 不做解析进度细到页（进度是阶段值 0/10/50/80/100）。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 解析产物自动落一条 **文档笔记**（`notes.source_file_id`） | `note_chunks.note_id` 是 NOT NULL 且 RAG 引用依赖它；自动建笔记零迁移、复用 `index_chunks`，不污染 S1-3/S1-4 契约 |
| 2 | 只在上传接口入队；不加手动重解析接口 | 任务卡验收就是“上传后轮询”；去重命中且 `pending/failed` 时补入队，覆盖重试 |
| 3 | `parse_result_json` **只存统计**，全文只在 `note.content_md` | 避免同一份 60MB 文本存两份；统计足够支撑排障与后续对齐 |
| 4 | 笔记按 `(user_id, source_file_id)` 查找，重复执行时更新内容而非新建 | 幂等；S2-5 的笔记列表会看到“文档笔记”，可编辑可删 |
| 5 | 状态写库由 handler 自己 `commit` 后抛出 | runner 失败会 rollback；若等 runner，`files` 会永远停在 `parsing`。handler 先落 `failed` + `error_msg` 再 re-raise，重试时重新置 `parsing` |
| 6 | 进度用阶段值：开始 10、解析完 50、切片完 80、入库完成 100 | 不引入细粒度回调，避免 `index_chunks` 内部 commit 与进度更新互相干扰 |
| 7 | 扫描版 PDF 直接失败 | `parse_document` 已判定 `is_scanned`，无文本可切；OCR 是后续卡 |
| 8 | `.md/.txt` 走本地文本解析，`ParserName` 增加 `text` | S2-6 允许这两类上传；不能落地成“永远 failed”。同步更新 S1-1 spec 的枚举说明 |
| 9 | 图片类型失败但错误可读 | S2-6 允许上传图片；解析能力未到位时给明确提示，不假装成功 |
| 10 | 错误信息 `f"{type(exc).__name__}: {exc}"` 截断 500 字 | 足够定位（存储/解析/embedding），不把整篇正文或密钥写进库 |
| 11 | 任务重投时 `done` 直接返回 `{"skipped": true}` | 幂等；避免重复 embedding 花钱 |
| 12 | 上传入队失败 → 上传仍已落库，但接口返回 500/50000 | 与 S2-7 一致；重新上传会去重并补入队，不产生重复文件 |

## 4. 数据（迁移 0005）

`files` 追加：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| error_msg | TEXT | 是 | — | 最近一次解析失败原因（≤500 字） |
| parse_progress | SMALLINT | 否 | 0 | 0–100，阶段值 |
| parse_started_at | TIMESTAMPTZ | 是 | — | 首次开始解析时间 |
| parse_finished_at | TIMESTAMPTZ | 是 | — | 终态时间 |

约束：
- `ck_files_parse_status`：`parse_status IN ('pending','parsing','done','failed')`
- `ck_files_parse_progress`：`parse_progress BETWEEN 0 AND 100`

枚举：`ParseStatus`（StrEnum）加入 `app/models/enums.py`；`File` 模型补字段。

> 迁移前库内 `files` 为空；若线上有旧行，`pending` 满足新 CHECK。

## 5. 接口

### POST /api/v1/files（S2-6 契约 + 入队副作用）

- 响应体不变（201/200 + `deduped`）；额外副作用：当 `record.parse_status ∈ {pending, failed}` 时入队 `parse.document`。
- `done` / `parsing` 的去重命中**不**重复入队。
- 入队失败：文件与记录已存在，但接口 `500/50000`「任务队列不可用」；重新上传会命中去重并补入队。

### GET /api/v1/files/{file_id}/parse-status（扩展）

`data` 字段：`id` / `filename` / `parse_status` / `parse_progress` / `error_msg`。

- `pending`：库里还没开始（任务已入队或还没被 Worker 取）
- `parsing`：Worker 正在解析（`parse_progress` 10/50/80）
- `done`：chunks 已入库，`parse_progress=100`
- `failed`：`error_msg` 可读，`parse_progress` 停在失败阶段

## 6. 组件契约

### ai/parse/__init__.py

```python
ParserName = Literal["docling", "pymupdf", "docx", "text"]

def parse_plain_text(path: str | Path) -> ParsedDocument:
    """md/txt → 单个 text block；UTF-8，非法字节替换不抛。"""
```

`parse_document()` 对 `.md/.txt` 调 `parse_plain_text`；`.png/.jpg/.jpeg` 仍抛 `InvalidParamError("不支持的文件类型…")`。

### tasks/parse_document.py

```python
TASK_PARSE_DOCUMENT = "parse.document"
_PROGRESS_STARTED = 10
_PROGRESS_PARSED = 50
_PROGRESS_CHUNKED = 80

@register(TASK_PARSE_DOCUMENT)
def parse_document_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
```

流程：
1. `file_id = int(payload["file_id"])`；`session.get(File, id)` 为空 → 抛 `InvalidParamError("文件不存在")`。
2. `parse_status == done` → 返回 `{"file_id": id, "skipped": True}`（不再下载/embedding）。
3. 置 `parsing`、`parse_started_at`（首次）、`parse_progress=10`、`error_msg=None`，`commit`。
4. `storage = get_storage()`；`storage.download_to(path, NamedTemporaryFile)`；根据 `filename` 后缀分派（pdf/docx/md/txt/图片）。
5. `parse_document` → `ParsedDocument`；`is_scanned` → 抛 `InvalidParamError("扫描版 PDF：无可抽取文本…")`。
6. `content_md = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())`；为空 → 抛「未解析出可用文本」。
7. `parse_progress=50`，commit。
8. `chunks = chunk_document(doc)`；为空 → 抛「未解析出可用文本」；`parse_progress=80`，commit。
9. 查/建 Note（`user_id + source_file_id`），`session.flush()` 拿 id；更新 `content_md/content_text`。
10. `index_chunks(session, chunks, note_id=note.id, user_id=file.user_id, source_file_id=file.id, replace=True)`。
11. 置 `done`、`parse_progress=100`、`parse_finished_at`、`parse_result_json=统计`，commit；返回 `{"file_id", "chunks", "parser", "tokens"}`。

异常：捕获 `Exception`，置 `failed` + `error_msg=截断` + `parse_finished_at` + 保留 `parse_progress`，`commit`，`raise`（交给 runner 决定重试/终态）。清理临时文件用 `finally`。

`parse_result_json` 统计字段：`parser` / `pages`（不同 page_no 数）/ `blocks` / `chunks` / `tokens` / `elapsed_ms` / `degraded_reason` / `note_id`。

### api/v1/files.py

`upload_file()` 增加 `queue: TaskQueue = Depends(get_task_queue)`；upload 成功后：

```python
if record.parse_status in {"pending", "failed"}:
    task_service.create_task(
        session, owner=current_user, name=TASK_PARSE_DOCUMENT,
        payload={"file_id": record.id}, queue=queue,
    )
```

`FileUploadOut` 不变；`FileStatusOut` 增加 `parse_progress: int`、`error_msg: str | None`。

## 7. 配置

无新增配置；复用 `UPLOAD_*`、`TASK_*`、Storage。`.env.example` 不变。

## 8. 测试计划（约 23 条）

`tests/test_parse_text.py`（2）
1. `.md/.txt` → `parse_plain_text` 返回单 block、`parser="text"`、非法字节被替换
2. `parse_document(".md")` 走文本支路（不调 PDF 解析）

`tests/test_parse_document.py`（17）
1. 成功：文件 done、progress=100、started/finished 非空、result 统计字段齐全
2. 成功：自动建 Note（title=文件名去扩展名、source_file_id、content_text 派生）
3. 成功：复用已有 Note（同 user+source_file_id，不新增）
4. 成功：`index_chunks` 收到 note_id/user_id/source_file_id/replace=True
5. 已 done：不下载、不建任务、返回 skipped
6. 文件不存在 → 抛 InvalidParamError，任务 failed 可读
7. 扫描件 → failed + error_msg 含「扫描版」
8. 空文本 → failed +「未解析出可用文本」
9. 图片 → failed +「图片解析暂未支持」
10. 损坏 PDF（解析器抛）→ failed，error_msg 含异常类型
11. 存储下载失败 → failed + error_msg 可读
12. embedding 失败 → failed + error_msg 含「Embedding」
13. 失败后再执行 → 重新置 parsing 并最终 done（重试恢复）
14. 错误信息超长 → error_msg 截断 ≤500
15. 文件名无扩展名 → failed（不支持的类型）
16. `parse_result_json` 不含正文（只统计）
17. 临时文件用完删除（断言目录无残留）

`tests/test_files_api.py` 增补（4）
1. 新上传 → 入队一次 `parse.document` + file_id
2. 去重命中且 done → 不入队
3. 去重命中且 failed → 重新入队
4. parse-status 返回 progress/error_msg

## 9. 验收（真实 PDF + Worker + MinIO + Postgres + 真实 Embedding）

1. `alembic upgrade head` → `0005_s2_8`；`\d files` 有新列与两个 CHECK。
2. 起 uvicorn + arq worker；注册 student。
3. 用 PyMuPDF 生成一份含标题/正文/公式文本的 2 页 PDF（`生成脚本见验收命令`），上传 → 201。
4. 轮询 `/files/{id}/parse-status`：`pending` → `parsing`（progress 10/50/80）→ `done`（progress 100）。
5. psql：`notes` 多一条 `source_file_id=<file>` 的文档笔记；`note_chunks` 数量与 `parse_result_json.chunks` 一致；`files.parse_result_json` 只有统计、无正文。
6. 重复上传同一 PDF → 200 `deduped=true`，**不新增**任务与 chunks（数量不变）。
7. 上传损坏 PDF（`%PDF-1.4` + 垃圾字节）→ 轮询到 `failed`，`error_msg` 可读（含解析器异常）。
8. 上传 `.md` → 解析成功、chunks > 0；上传 `.png`（合法 magic）→ `failed` +「图片解析暂未支持」。
9. 清理 notes/note_chunks/files/async_tasks/users 与对象；pytest 全绿。
10. Worker 日志出现 `file_parse_started` / `file_parse_done` / `file_parse_failed`（只含 file_id/chunks，不含正文）。

## 10. 文档同步

- API.md §3：上传副作用、parse-status 新字段与状态机、错误语义。
- SCHEMA.md §4.1：files 四个新列；§10.2 parse_status 枚举改四值。
- AGENTS.md §9.2 解析约定；§9.6 解析 Worker 锚点。
- DECISIONS.md D-028。
- PROGRESS.md 状态/清单/遗留/日志；docs/AI协作开发实施计划.md 勾选 S2-8。
- spec/plan 执行记录；S1-1 spec 的 `ParserName` 枚举补 `text`。

## 11. 已知限制

- 解析与 embedding 同步跑在 300s job_timeout 内；超大 PDF 可能超时（失败可读，无分页续跑）。
- 图片/扫描件不支持，需 OCR 卡。
- 自动建的“文档笔记”会出现在笔记列表；删除文件没有接口，笔记与文件可能不同步。
- 重试每次都会把 `failed` 写一次再回 `parsing`，轮询可能看到短暂抖动。
- `parse_result_json` 不含正文，若 note 被删则解析文本丢失，只能重新上传（去重命中 done 不会重解析）。
- 进度是阶段值，不是页级进度；embedding 阶段停在 80。
- 上传接口入队失败会返回 500，但文件记录已存在。