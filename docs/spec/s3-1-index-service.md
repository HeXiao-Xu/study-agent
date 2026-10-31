# S3-1 切片入库服务产品化 — 设计 Spec

- 任务卡：`docs/AI协作开发实施计划.md`「S3-1 切片入库服务产品化」
- 日期：2026-10-31
- 状态：**已批准**（2026-10-31 用户确认；进入 `docs/plan/s3-1-index-service.md` 实现）
- 上游：S1-3 `services/indexing.index_chunks`、S2-5 笔记 CRUD、S2-7 异步任务框架、S2-8 解析 Worker
- 下游：S3-2 检索服务、S3-5 问答 API、S3-8 引用跳转
- 产物：Markdown → 块解析器、`services/index_service.py`、`tasks/index_note.py`、管理员重建接口、笔记侧索引副作用、测试

## 1. 目标

1. **笔记正文进入检索库**：手写笔记此前没有任何 `note_chunks`（当前库 4 篇笔记中 3 篇文档笔记有 37 块，手写笔记 0 块），RAG 检索不到。S3-1 起，笔记创建/正文更新/删除都维护 `note_chunks`。
2. **唯一编排入口**：新增 `services/index_service.py`，内部只用 S1-3 的 `index_chunks`（切片 → Embedding → 覆盖写），**不另写向量化逻辑**；按笔记维度先删旧块再插新块，同一次 `index_chunks` 调用内提交。
3. **重新索引产品化**：管理员触发全量重建，进度可查（每篇笔记一个 `index.note` 任务，`run_id` 聚合任务状态）。
4. **顺手修复既有正确性问题**：笔记软删后 `note_chunks` 仍留在库里，而 S1-4 检索只按 `user_id` 过滤、不看 `notes.deleted_at`——删除笔记后其内容仍会被 RAG 检索到。S3-1 在软删的同一事务里删除切片。

非目标：前端页面（S3-8）、检索 scope 过滤（S3-2）、问答链路（S3-5）、文件重新解析/文件删除接口、`index_chunks` / Embedding 客户端改造、新表或迁移。

## 2. 已确认决策

| # | 决策 | 理由 / 来源 |
|---|---|---|
| 1 | 进度方案：**每篇笔记一个 `index.note` 任务**，请求体带同一 `run_id`；进度接口按 `async_tasks` 的 `payload->>'run_id'` 聚合 | 用户 2026-10-31 选 A。不新增表/迁移；每篇笔记独立 300s 超时，单篇失败不影响其余笔记 |
| 2 | 索引范围：**全部未删除笔记**；正文变化即重建；文档笔记被编辑后按 Markdown 重建，`page_no` 置空 | 用户 2026-10-31 选 A。编辑后的文本无法对齐原页码；重新上传/解析文件可恢复 |
| 3 | 全量重建 = **所有未删除笔记都按 `content_md` 重建**（含文档笔记） | 与"重建结果只由当前正文决定"一致，可复现；代价：文档笔记的页码/bbox 归零（见 §11 已知限制）。**这一条请重点评审** |
| 4 | 重建开始前清理**软删笔记的残留切片**（一条 SQL），并跳过软删笔记 | 防止已删内容继续被检索 |
| 5 | 保存路径 best-effort：`index.note` 入队失败只记 WARNING，笔记保存仍成功 | 与 S2-10 `kp.align` 一致；索引是增强能力，不能反过来让保存失败 |
| 6 | 重建接口入队失败返回 `500/50000`（队列不可用），已创建的任务保留 | 与 S2-6 上传入队失败一致；重复调用会新建 run，旧任务仍会执行（覆盖写幂等） |
| 7 | 同一笔记并发索引任务不引入锁 | `UNIQUE(note_id, chunk_index)` 冲突会让后一个任务失败，runner 自动重试（3 次）后成功；不为此引入 advisory lock |
| 8 | 只在「正文」变化时重建 | 改标题/标签/学科不触发 Embedding，避免无谓花费 |

## 3. 架构与数据流

```
POST/PATCH /notes（正文变化）                 DELETE /notes/{id}
        │ 入队 index.note(force)                   │ 同一事务
        ▼                                         ▼
   ARQ worker → tasks/index_note.py          DELETE note_chunks(note_id,user_id)
        │
        ▼
   services/index_service.index_note()
        ├─ ai/parse/markdown.py  parse_markdown_text()  → ParsedDocument
        ├─ ai/rag/chunker.py     chunk_document()       → list[Chunk]（S1-2 复用）
        └─ services/indexing.py  index_chunks(replace=True)  → note_chunks

POST /admin/index/rebuild
        └─ index_service.start_rebuild(): 清理软删残块 + 每篇笔记 create_task(index.note, run_id)
GET /admin/index/runs/{run_id}
        └─ index_service.get_rebuild_progress(): 聚合 async_tasks 状态/结果
```

不复用 `parse_plain_text`（它把整个文件当单块），也不改 S2-8 Worker 的 PDF/DOCX 解析链路。

## 4. Markdown → 块解析（`backend/app/ai/parse/markdown.py`）

```python
def parse_markdown_text(text: str, *, source: str) -> ParsedDocument
```

输出复用 S1-1 的 `ParsedDocument`（`parser="text"`、`is_scanned=False`、`page_no=None`），交给 S1-2 `chunk_document()` 完成题目/公式判定、300–800 token 装包与笔记块重叠，**不新写切片算法**。

规则：

| # | 规则 |
|---|---|
| 1 | `\r\n` / `\r` 统一为 `\n` |
| 2 | 标题：ATX 风格 `^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$`；按级别维护 `heading_path` 栈（遇低级标题先弹出同级及更深项） |
| 3 | 标题块文本 = **去掉 `#` 的标题文字**（与 S1-1 约定一致：标题块文本 == 下一块 `heading_path` 末元素，S1-2 会把它并进所属小节）；若标题后紧接另一个标题或文末（空小节），丢弃该标题块 |
| 4 | 围栏代码块（```` ``` ```` / `~~~` 起止）整段一块，保留原文（含围栏行），内部不识别标题、不按空行切 |
| 5 | 表格：连续以 `|` 开头的行合成一块（S1-2 以"以 `|` 开头且含换行"识别表格，整表不拦腰切） |
| 6 | 其余按空行分段；段内保留原始 Markdown（LaTeX `$...$`、列表、强调原样保留，供 Embedding 与前端渲染） |
| 7 | 图片 `![alt](url)` 降为 `alt`（`note-file://` 等 URL 不进入检索正文）；普通链接保持原样 |
| 8 | 空正文 → `blocks=[]`（`chunk_document` 返回 `[]`，`index_chunks` 清空旧块） |

标题块会进入块内容（如"函数/单调性"小节首块包含"单调性"一行），`heading_path` 同时写入 `note_chunks.heading_path`，供引用卡片显示章节。

## 5. 索引服务（`backend/app/services/index_service.py`）

```python
@dataclass(frozen=True)
class NoteIndexResult:
    note_id: int
    chunk_count: int
    total_tokens: int
    elapsed_ms: int
    cost_cny: float
    skipped: bool = False
    reason: str | None = None

def build_note_chunks(note: Note) -> list[Chunk]
def index_note(session: Session, *, note_id: int, client: EmbeddingClient | None = None) -> NoteIndexResult
def delete_note_chunks(session: Session, *, note_id: int, user_id: int) -> None      # 不 commit
def purge_deleted_note_chunks(session: Session) -> int                              # 自行 commit
def start_rebuild(session: Session, *, owner: User, queue: TaskQueue) -> RebuildStart
def get_rebuild_progress(session: Session, *, run_id: str) -> RebuildProgress
```

- `index_note`：`session.get(Note)` → 不存在/已软删返回 `skipped=True, reason="note_missing"|"note_deleted"`（**不动旧块**：软删路径已清理）；否则 `build_note_chunks` → `index_chunks(..., note_id, user_id, source_file_id=note.source_file_id, replace=True)`；空块也会清空旧块。
- `delete_note_chunks`：`DELETE FROM note_chunks WHERE note_id=:id AND user_id=:uid`（显式 `user_id`，AGENTS §4），由 `note_service.delete_note` 在软删同一事务内调用，随后统一 commit。
- `purge_deleted_note_chunks`：`DELETE FROM note_chunks WHERE note_id IN (SELECT id FROM notes WHERE deleted_at IS NOT NULL)`，返回删除行数，**不 commit**（由调用方提交）。
- `start_rebuild`：
  1. **一次查询**全部未删除笔记 id（`ORDER BY id`）；
  2. 数量为 0 → `InvalidParamError("没有可重建的笔记")`；
  3. `purged_chunks = purge_deleted_note_chunks(session)`，`session.commit()` 固化清理结果；
  4. `run_id = uuid4().hex`；
  5. 逐篇 `task_service.create_task(owner=owner, name=TASK_INDEX_NOTE, payload={"note_id": id, "run_id": run_id}, queue=queue)`；
  6. 返回 `RebuildStart(run_id, total_notes, purged_chunks)`。
- `get_rebuild_progress`：按 `name='index.note' AND payload->>'run_id'=:run_id` 聚合：
  - `status` 分组计数 → `pending/running/succeeded/failed/total`；
  - `chunks = sum(result->>'chunks')`（只统计 succeeded 且 result 非空）；
  - `started_at = min(started_at)`、`finished_at = max(finished_at)`；
  - `percent = round((succeeded + failed) / total * 100)`；
  - `failures`：failed 任务按 id 升序最多 20 条 `{note_id, error}`；
  - 聚合结果为空 → `NotFoundError("索引重建记录不存在")`。

## 6. 任务（`backend/app/tasks/index_note.py`）

```python
TASK_INDEX_NOTE = "index.note"   # 定义在 index_service，避免 task 模块与 service 循环导入

@register(TASK_INDEX_NOTE)
def index_note_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]
```

- `note_id = int(payload.get("note_id") or 0)`；`<=0` → `ValueError("payload 缺少 note_id")`（runner 记失败）。
- `run_id` 原样忽略（只用于聚合查询）。
- 调 `index_service.index_note`，返回 `{"note_id", "chunks", "tokens", "elapsed_ms", "cost_cny", "skipped", "reason"}`；成功结果供进度接口累加 `chunks`。
- 不自行 commit（`index_chunks` 内部提交切片；任务状态由 runner 提交）。
- 在 `app/tasks/__init__.py` 显式 import，保证 Worker 注册。

## 7. 接口契约（写入 `docs/API.md`）

### 7.1 笔记接口副作用（不改出参）

| 接口 | 新增副作用 |
|---|---|
| `POST /api/v1/notes` | 创建成功后 best-effort 入队 `index.note`（payload 仅 `note_id`） |
| `PATCH /api/v1/notes/{id}` | 仅当请求体**显式包含 `content_md`** 时入队 `index.note`；只改标题/标签/学科不入队 |
| `DELETE /api/v1/notes/{id}` | 软删同一事务内删除该笔记全部 `note_chunks` |

入队失败：`index.note` 与 `kp.align` 同样只记 WARNING，接口仍成功返回。

### 7.2 `POST /api/v1/admin/index/rebuild`

- 权限：`admin`（`require_role("admin")`）
- 类型：同步（只创建任务，不做 Embedding）；成功 `202`
- 入参：无
- 出参 `data`：

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | run_id | string | 32 位十六进制，进度查询用 |
  | total_notes | int | 本次入队的笔记数 |
  | purged_chunks | int | 清理的软删笔记残块数 |

- 错误码：400/401/403/422（没有可重建笔记）/500（队列不可用）

### 7.3 `GET /api/v1/admin/index/runs/{run_id}`

- 权限：`admin`
- 出参 `data`：

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | run_id | string | |
  | total | int | 任务总数 |
  | pending / running / succeeded / failed | int | 各状态任务数 |
  | percent | int | 0–100，`(succeeded+failed)/total` |
  | chunks | int | 已成功写入的切片总数 |
  | started_at / finished_at | string? | ISO-8601；全部开始/全部结束才非空 |
  | failures | array | `[{note_id, error}]`，最多 20 条 |

- 错误码：401/403/404（run 不存在）/500

## 8. 错误与边界

| 场景 | 行为 |
|---|---|
| 任务执行前笔记被删 | `skipped=True, reason="note_deleted"`，任务算 success（不重试） |
| 笔记正文为空块（如只有图片/公式） | `index_chunks([])` 清空旧块，任务 success、`chunks=0` |
| Embedding 失败/维度不符 | 抛 `EmbeddingError` → 任务失败 → runner 重试（最多 3 次）；旧块保留（删块发生在向量成功之后） |
| 同一笔记两个索引任务并发 | 后提交者可能撞 `uq_note_chunks_note_chunk_index` → 该次失败、runner 重试后成功（最终一致） |
| 重建时队列中途不可用 | 已建任务保留并继续执行，接口 500；重新调用会新建 run |
| 重建 run 无任何任务（空库） | `start_rebuild` 直接 422，不产生查不到的 run |
| 笔记保存后索引任务失败 | 笔记保存成功；`GET /tasks/{id}` 可查失败原因，重新保存正文可重试 |

## 9. 测试计划（全部零真实网络）

| 文件 | 用例 |
|---|---|
| `tests/test_markdown_parse.py`（约 9） | 多级标题 → `heading_path`；标题内容并入下一块；空小节标题丢弃；围栏代码整块且内部 `#` 不当标题；表格整块；空行分段；图片降为 alt；LaTeX/列表原样；空文本 |
| `tests/test_index_service.py`（约 10） | `build_note_chunks` 走 parse+chunk；`index_note` 传对 note/user/source_file 与 `replace=True`；笔记不存在/软删 → skipped 且不调 embedding；空块清空旧块；统计透传；`delete_note_chunks` 语句含 note_id+user_id；`purge_deleted_note_chunks` SQL 过滤 `deleted_at`；`start_rebuild` 空库 422、N 篇建 N 个任务且 run_id 一致；进度聚合纯函数（计数/percent/failures/未知 run） |
| `tests/test_index_task.py`（约 4） | 缺 note_id 抛错；正常调 service 并返回统计；skipped 结果原样返回；run_id 不影响执行 |
| `tests/test_index_admin_api.py`（约 8） | 未登录 401；student/teacher 403；admin 重建 202 + 出参；进度 200 字段齐全；未知 run 404；队列失败 500/50000；认证失败不建任务 |
| `tests/test_notes_api.py`（增补约 4） | 创建入队 `index.note`；PATCH 含 `content_md` 入队；PATCH 只改标题不入队；DELETE 执行 chunk 删除语句 |
| 既有 | 524 条保持全绿；`test_indexing.py` 不改 |

`FakeSession`/`FakeQueue` 沿用 S2 测试写法；任务与接口测试不触库、不调 Embedding。

## 10. 验收（真实 Postgres + Redis + Worker + 真实 Embedding）

前置：`docker compose -f deploy/docker-compose.dev.yml up -d`（当前三件套已在跑）；`alembic upgrade head`（本卡无迁移）；起 uvicorn 与 arq worker。

1. **pytest**：全套全绿（实际 **563 passed, 1 warning**，基线 524 + 39 条）。
2. **创建笔记即入库**：`test1` 登录 → `POST /notes`（含 `## 标题`、LaTeX、列表）→ 等任务成功 → psql 查 `note_chunks`：块数 == 任务结果 `result.chunks`，`heading_path` 正确，`content` 含标题文字。
3. **改正文即重建**：`PATCH` 追加一句唯一标记 → 等任务成功 → psql：旧标记内容查不到、新标记能查到、`SELECT count(*)` 与任务 `result.chunks` 一致；同笔记重复保存不出现重复 `(note_id, chunk_index)`。
4. **软删清理**：新建临时笔记并等入库 → `DELETE` → psql 该 note 的 `note_chunks` 为 0；`SELECT count(*) FROM note_chunks c JOIN notes n ON n.id=c.note_id WHERE n.deleted_at IS NOT NULL` 为 0。
5. **管理员全量重建**：注册/提升一个 admin → `POST /admin/index/rebuild` 得 `run_id`、`total_notes` == 库内未删除笔记数 → 轮询 `GET /admin/index/runs/{run_id}`：`pending+running` 归零、`failed=0`、`percent=100`、`chunks` == `SELECT count(*) FROM note_chunks`；**再跑一次** `note_chunks` 总数不变、`SELECT note_id, chunk_index, count(*) ... GROUP BY 1,2 HAVING count(*)>1` 返回 0 行。
6. **权限**：student/teacher 调两个 admin 接口均 403/40300；无 token 401/40100。
7. **回归**：`scripts/ask.py` 用真实问题检索，结果仍能命中（确认重建后检索链路正常）；`pytest` 全绿。
8. 验收数据（块数/任务状态/耗时）原样贴进 `docs/plan/s3-1-index-service.md` 执行记录，不造数。

## 11. 已知限制（写入正式文档）

1. **全量重建丢失页码**：文档笔记按 Markdown 重建后 `page_no`/`bbox_json` 为 NULL，引用卡片只剩"笔记 + 章节"；恢复页码需要重新上传并解析文件（本卡不做文件重解析接口）。
2. 重建覆盖**所有用户**的笔记（管理员操作），一次重建的 Embedding 费用与笔记量成正比。
3. 每篇笔记一个任务：笔记数很多时重建会向 Redis 投递大量任务，当前规模（个位数到百位数）可接受。
4. 无逐笔记索引进度/状态字段：正文保存后只能通过任务状态、psql 块数确认；失败需重新保存正文触发重试。
5. 并发索引同一笔记可能产生一次唯一键冲突，依赖 runner 重试自愈（不引入锁）。
6. 索引正文保留 Markdown 与 LaTeX（Embedding 可接受），因此 `note_chunks.content` 与 `notes.content_text`（去公式纯文本）不同；`tsv` 仍由 jieba 切词生成。
7. 上传的 `.md` 文件仍走 S2-8 的"整文件单块"解析；只有笔记保存/重建路径使用新的 Markdown 分块，两者对同一内容可能产生不同块数。

## 12. 文档同步

- `docs/API.md`：§2 笔记副作用；§11 新增两个 admin 接口。
- `docs/SCHEMA.md`：无表结构变化（备注 `note_chunks` 由 S3-1 起也承载手写笔记）。
- `docs/DECISIONS.md`：D-035 记录本卡 8 条决策与"全量重建丢页码"代价。
- `docs/PROGRESS.md`：状态、S3-1 勾选、变更日志、遗留问题（页码/并发冲突/无状态字段）。
- `AGENTS.md`：§9.2 增补索引服务约定；§9.6 增补索引服务锚点。
- `docs/plan/s3-1-index-service.md`：实施计划 + 执行记录（实测数字）。
- `docs/AI协作开发实施计划.md` 第 14 章勾选 S3-1。

## 13. 与任务卡的偏离

| # | 任务卡原文 | 本卡执行 | 原因 |
|---|---|---|---|
| 1 | 产出 `services/index_service.py`、重建索引接口 | 另加 `ai/parse/markdown.py`、`schemas/indexing.py`、`api/v1/admin.py` | 笔记是 Markdown，需要块解析器；接口与 schema 按项目分层落位 |
| 2 | "索引进度可查" | 进度以**重建 run** 为单位，不提供单笔记进度 | 复用 `async_tasks`，不新增表/迁移；单笔记量小、可查块数 |
| 3 | "按 file/note 维度删除旧 chunk" | 只按 note 维度（file → 文档笔记是 1:1，删除条件仍带 `user_id`） | 文件解析产物挂在文档笔记上，按 note 删除即覆盖 file 维度；本卡不做文件重解析 |

## 14. 实施记录（2026-10-31）

- 代码落位与 spec 一致：`ai/parse/markdown.py`、`schemas/indexing.py`、`services/index_service.py`、`tasks/index_note.py`、`api/v1/admin.py`；`tasks/__init__.py` 注册；notes 路由与 `note_service.delete_note` 接入副作用；无迁移、无新依赖。
- 测试：新增 39 条（Markdown 12、service 11、task 4、admin 8、notes 4），全量 **563 passed, 1 warning**；既有 524 条零回归（`test_note_service.py` 仅给 FakeSession 补 `execute`，`test_notes_api.py` 同）。
- 真实验收（库内 5 篇未删除笔记：49/54/55/77/79）：
  - 新建 note 79 → 任务 succeeded、2 块/58 tokens，`heading_path=函数`、`函数/单调性`。
  - PATCH 追加唯一标记 → 新任务 succeeded、命中 1 行、块数 2，`(note_id, chunk_index)` 重复 0。
  - 软删临时 note 80 → 残留 0、孤儿 0。
  - 全量重建 run1 `c01a1490cd0f4abfb704f8824bb1323e`：`total_notes=5, purged=0, percent=100, succeeded=5, failed=0, chunks=39`；run2 `a04d502f9a8b4b1284c408cd7dae251e` 结果相同；表内 39 行、各笔记 2/6/8/21/2、重复分组 0。
  - 重建后 `page_no` 非空 = 0（已确认代价）。
  - 权限：student 两接口 403、匿名 401、坏 run_id 422、未知 run 404。
  - `scripts/ask.py --user-id 25` 真实检索并回答，引用笔记 #79 的「函数/单调性」与「函数」两个片段（`refused=否`，`llm_calls=1`）。
- 验收后清理：删除 `s31_student`/`s31_admin` 两个账号、其 3 篇笔记（78/79/80）与 18 条 `async_tasks`；库回到 4 篇未删除笔记、37 块（3 篇文档笔记 35 块 + 原手写笔记 2 块），`page_no` 因本次全量重建已为 0。