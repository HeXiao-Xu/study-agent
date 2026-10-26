# S2-5 笔记表与 CRUD API spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-5
- 日期：2026-10-26
- 状态：已实现并验收（2026-10-26，pytest 322/322 + curl/psql 全流程；实施记录见 docs/plan/s2-5-notes-crud.md）
- 上游：S1-3（note_chunks 表）、S2-1（users / subjects / knowledge_points）、S2-2（认证）、S2-3（权限）、S2-4（分页）
- 下游：S2-6 文件上传（复用 files 表）、S2-8 解析 Worker、S3 检索（note_chunks.tsv）
- 产物：`alembic/versions/0003_s2_5_note_tables.py`、`models/{note,note_kp,file}.py`、`schemas/notes.py`、`services/note_service.py`、`api/v1/notes.py`、`utils/markdown_text.py`

## 1. 目标

交付真正的第一个业务 CRUD：笔记建 → 改 → 查 → 软删 → 列表不可见，并把 S2-3 的权限、S2-4 的分页第一次接到真实接口上。

1. 建 `notes` / `note_kps` / `files` 三张表，补齐 `note_chunks` 三个外键（S2-1 遗留）；
2. 保存时同时写 `content_md` 与 `content_text`（去公式纯文本）；
3. 列表支持学科 / 标签 / 关键词 / 时间筛选 + 统一分页排序；
4. 软删除：`deleted_at` 置位，列表/详情/更新统一过滤；
5. 真实 curl 全流程 + 数据库核验（`updated_at` 自动更新、`deleted_at` 置位）。

## 2. 范围

### 2.1 做

- 迁移 `0003_s2_5_note_tables.py`：建 3 表 + 3 个外键 + 索引；清理孤儿 `note_chunks`
- 模型：`Note`、`NoteKp`、`File`；`NoteChunk` 补 `ForeignKey`
- schema：`NoteCreate` / `NoteUpdate` / `NoteSummary` / `NoteOut`
- 服务：`create_note` / `list_notes` / `build_notes_query` / `get_note` / `update_note` / `delete_note`
- 工具：`to_plain_text(markdown)`（去公式/Markdown 语法，供检索）
- 路由：`POST /notes`、`GET /notes`、`GET /notes/{note_id}`、`PATCH /notes/{note_id}`、`DELETE /notes/{note_id}`
- 测试：`test_markdown_text.py`、`test_note_service.py`、`test_notes_api.py`
- 文档：API.md §2 定稿、SCHEMA.md §4 落库说明、AGENTS §9.6、DECISIONS D-025、PROGRESS

### 2.2 不做

- 不做笔记版本历史 / 协同编辑 / 回收站（软删后只能 SQL 恢复）
- 不做 `note_kps` 的读写接口（知识点对齐是 S2-10；本卡只建表）
- 不做 `files` 上传接口（S2-6）；`source_file_id` 暂不由客户端写入，留给 S2-8 解析流水线
- 不做笔记切片 / 向量化（S3；本卡不写 note_chunks）
- 不做笔记与错题/复习计划的联动
- 不做全文检索（`q` 用 ILIKE；jieba/tsvector 留给 S3 检索卡）
- 不做批量操作 / 导入导出

### 2.3 关键决策（2026-10-26 用户确认）

| # | 决策 | 理由 |
|---|---|---|
| 1 | 一次建 `notes` + `note_kps` + `files`，并补 `note_chunks` 的 `note_id` / `user_id` / `source_file_id` 三个外键；`files.sha256` 定「同用户唯一」 | 任务卡把 files 列为 S2-5 产出；SCHEMA §4.3 明确外键延后到 S2-5；多租户下按用户去重才不会串数据 |
| 2 | 迁移前清理孤儿 `note_chunks`：`user_id` 不在 users 或 `note_id` 不在 notes 的行删除（新库上无行，no-op） | 现状 83 行 `user_id=1` 的 S1-3 实验残留，users 表为空，直接加 FK 会失败；保留就得造假用户/假笔记，把脏数据带进正式库 |
| 3 | 更新用 PATCH（只改传入字段，`model_dump(exclude_unset=True)`）；删除用软删 + `204` 无响应体 | 编辑器自动保存会频繁只改正文，全量 PUT 容易把未加载字段清空；204 是 DELETE 的常规语义 |
| 4 | 读：列表=仅本人；详情=本人或已绑定家长/老师（复用 `ensure_student_access`，admin 不绕过）；写：仅本人且仅 `student` 角色 | 与 S2-3 的权限矩阵一致；写操作共享给家长/老师会造成“谁改的”无法追溯 |
| 5 | `q` 用 `ILIKE`（`title` + `content_text`），转义 `%`/`_`/`\` | 中文原词可直接搜、实现简单；jieba 全文检索依赖 note_chunks 的写入链路，适合 S3 |
| 6 | `content_text` 由 `content_md` 派生：去 `$...$`/`$$...$$`/`\(...\)`/`\[...\]` 公式，去 Markdown 标记，保留代码块与链接文字 | 公式符号对关键词检索无意义且会污染匹配；代码块内容可能是要搜的关键词 |
| 7 | `subject_id` 写入前校验存在（不存在 → `422/42200`），不靠数据库 FK 报 500 | 用户可传任意 id；让 FK 抛 IntegrityError 会变成 500 |
| 8 | `tags` 用 `TEXT[]`（SCHEMA 现值），过滤用 `tags @> ARRAY[tag]`（`postgresql.ARRAY.contains`）；单标签 ≤30 字、最多 20 个、去重保序 | 与 SCHEMA §4.2 一致；`@>` 可命中 GIN 索引（`= ANY` 在 SQLAlchemy 2.1 已弃用且不易走索引） |
| 9 | 列表返回 `NoteSummary`（不含正文），详情/创建/更新返回 `NoteOut`（含 `content_md`） | 20 条正文可能几 MB；列表页不需要全文 |

## 3. 数据模型与迁移（0003）

### 3.1 files（SCHEMA §4.1）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| user_id | BIGINT | FK `users.id`，NOT NULL，`ix_files_user_id` |
| filename / mime / storage_path | TEXT | NOT NULL |
| size | BIGINT | NOT NULL |
| sha256 | TEXT | NOT NULL；`uq_files_user_sha256 (user_id, sha256)` |
| parse_status | TEXT | NOT NULL default `'pending'`，CHECK `IN ('pending','done')`（S2-8 用新迁移扩枚举） |
| parse_result_json | JSONB | NULL |
| created_at | TIMESTAMPTZ | NOT NULL default now() |

### 3.2 notes（SCHEMA §4.2）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| user_id | BIGINT | FK `users.id`，NOT NULL |
| subject_id | BIGINT | FK `subjects.id`，NULL |
| title / content_md / content_text | TEXT | NOT NULL |
| tags | TEXT[] | NULL |
| folder | TEXT | NULL |
| source_file_id | BIGINT | FK `files.id`，NULL |
| created_at / updated_at | TIMESTAMPTZ | NOT NULL default now()；`updated_at` 应用层 `onupdate` |
| deleted_at | TIMESTAMPTZ | NULL |

索引：`ix_notes_user_id_subject_id (user_id, subject_id)`、`ix_notes_tags_gin`（GIN）。

### 3.3 note_kps（SCHEMA §4.4）

复合 PK `(note_id, kp_id)`；`note_id` FK `notes.id` ON DELETE CASCADE；`kp_id` FK `knowledge_points.id`；`confidence NUMERIC(4,3)`；`source TEXT` CHECK `IN ('ai','manual')`；`confirmed BOOLEAN` default false；`ix_note_kps_kp_id`。

### 3.4 note_chunks 补外键

- 先清理孤儿行（条件删除，见决策 2）；
- `note_id` → `notes.id` ON DELETE CASCADE；
- `user_id` → `users.id`；
- `source_file_id` → `files.id`（NULL 不校验）。

### 3.5 迁移可逆性

`downgrade()` 删外键 → 删 note_kps → notes → files。**被清理的 83 行 chunk 不可恢复**（迁移 docstring 写明；它们没有对应用户/笔记，属于 S1-3 实验残留）。

## 4. API 契约（写入 API.md §2）

| 方法 | 路径 | 权限 | 成功 | 说明 |
|---|---|---|---|---|
| POST | `/api/v1/notes` | `student` | 201 `Envelope[NoteOut]` | 创建；服务端生成 `content_text` |
| GET | `/api/v1/notes` | 登录用户 | 200 `Envelope[PageData[NoteSummary]]` | 仅本人；筛选 + 分页 + 排序 |
| GET | `/api/v1/notes/{note_id}` | 本人或已绑定家长/老师 | 200 `Envelope[NoteOut]` | 不存在/已软删 → 404 |
| PATCH | `/api/v1/notes/{note_id}` | 仅本人 `student` | 200 `Envelope[NoteOut]` | 部分更新；`content_md` 变则重算 `content_text` |
| DELETE | `/api/v1/notes/{note_id}` | 仅本人 `student` | 204 无体 | 软删：置 `deleted_at`，行保留 |

### 4.1 列表 query 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| subject_id | int ≥1 | — | 学科筛选 |
| tag | str 1–30 | — | 标签精确匹配（`tags @> ARRAY[tag]`） |
| q | str 1–100 | — | 关键词，`title`/`content_text` 子串匹配（大小写不敏感，转义 `%`/`_`） |
| created_from | ISO-8601 datetime | — | `created_at >=` |
| created_to | ISO-8601 datetime | — | `created_at <=` |
| page / page_size | int | 1 / 20 | S2-4 统一分页 |
| sort_by / order | str | `created_at` / `desc` | 白名单：`created_at`、`updated_at`、`title` |

### 4.2 出参

```json
// NoteSummary
{"id": 1, "title": "函数单调性", "subject_id": 1, "tags": ["函数"], "folder": "必修一",
 "created_at": "2026-10-26T14:00:00Z", "updated_at": "2026-10-26T14:00:00Z"}

// NoteOut = NoteSummary + content_md + source_file_id
```

`content_text` 只用于检索，**不出现在任何响应里**；`deleted_at` 也不返回。

### 4.3 错误

| 场景 | HTTP / code |
|---|---|
| 未登录 / token 无效 | 401 / 40100 |
| 非 student 调写接口 | 403 / 40300 |
| 详情越权（非本人且未绑定） | 403 / 40300「无权访问该资源」 |
| 改/删他人笔记 | 403 / 40300「无权修改/删除该资源」 |
| 笔记不存在或已软删 | 404 / 40400「笔记不存在」 |
| `subject_id` 不存在 | 422 / 42200「学科不存在」 |
| 排序字段非白名单 / 分页越界 / 字段校验失败 | 422 / 42200 |

## 5. 函数契约

```python
# utils/markdown_text.py
def to_plain_text(markdown: str) -> str

# services/note_service.py
NOTE_SORT_FIELDS: Mapping[str, Any] = {"created_at": Note.created_at, "updated_at": Note.updated_at, "title": Note.title}

def escape_like(term: str) -> str
def build_notes_query(*, owner_id: int, subject_id: int | None = None, tag: str | None = None,
                      q: str | None = None, created_from: datetime | None = None,
                      created_to: datetime | None = None) -> Select
def create_note(session: Session, *, owner: User, payload: NoteCreate) -> Note
def list_notes(session: Session, *, owner: User, params: PageParams, sorting: SortParams, **filters) -> PageData[NoteSummary]
def get_note(session: Session, *, note_id: int, viewer: User) -> Note
def update_note(session: Session, *, note_id: int, owner: User, payload: NoteUpdate) -> Note
def delete_note(session: Session, *, note_id: int, owner: User) -> None
```

- 一个用例一个事务：创建/更新/删除失败都 rollback 后抛。
- `get_note` 内部：先按 `id + deleted_at IS NULL` 查（None → 404），再 `note.user_id != viewer.id` 时调 `ensure_student_access`（越权 → 403/40300）。
- `update_note` / `delete_note`：仅 `note.user_id == owner.id`，否则 403；不再查关联关系。
- `list_notes` 先 `build_notes_query` → `apply_sort`（默认 `created_at`）→ `paginate_query(item_model=NoteSummary)`。
- `create_note` 校验 `subject_id`：`session.get(Subject, subject_id)` 为 None → `InvalidParamError("学科不存在")`。

## 6. content_text 规则（写进 docstring）

1. 先“冻结”围栏代码块与行内代码（占位符），避免公式/强调规则破坏代码；
2. 删 `$$...$$`、`\[...\]`、`\(...\)`、`$...$`（替换为空格）；
3. 图片 `![alt](url)` → `alt`；链接 `[text](url)` → `text`；
4. 删 HTML 标签、标题 `#`、引用 `>`、列表符号、分隔线、表格竖线；
5. 去强调标记 `**`/`__`/`~~`/成对 `*`/`_`，还原反斜杠转义；
6. 还原代码内容，最后把连续空白折叠成单空格并 strip。

## 7. 权限矩阵（与 S2-3 对齐）

| 操作 | 本人 | 已绑定家长/老师 | 其他学生 | admin |
|---|---|---|---|---|
| 列表（本人） | ✅ | ✅（看到自己的，通常为空） | ✅（自己的） | ✅（自己的） |
| 详情 | ✅ | ✅ | ❌ 403 | ❌ 403 |
| 创建 | ✅（student） | ❌ 403（角色限制） | ✅（自己的） | ❌ 403 |
| 修改 / 删除 | ✅ | ❌ 403 | ❌ 403 | ❌ 403 |

## 8. 测试（预计 38 条）

### 8.1 `tests/test_markdown_text.py`（10）

纯文本不变；行内公式删除；块级公式删除；`\(...\)`/`\[...\]` 删除；链接取文字；图片取 alt；标题/引用/列表/分隔线/表格标记删除；行内代码保留内容；围栏代码块保留内容且内部 `$` 不被删；空白折叠。

### 8.2 `tests/test_note_service.py`（17）

用 FakeSession（`scalar` 按实体分派；`get` 返回 Subject 或 None；`add/commit/refresh` 记录），列表用例 monkeypatch `note_service.paginate_query` 并断言编译后的 PostgreSQL SQL。

1. 创建写入 `content_text`（公式已剥离）与规范化 tags
2. 创建带 folder/subject
3. 创建时 subject 不存在 → 42200
4. 列表默认条件：`user_id` + `deleted_at IS NULL`
5. 列表 tag → SQL 含 `tags @>`
6. 列表 q 转义 `%`/`_`（SQL 参数里是 `\%`）
7. 列表时间区间 → 两个比较条件
8. 列表默认排序 `created_at DESC`
9. 列表非法排序字段 → 42200
10. 详情本人 → 返回笔记
11. 详情不存在 → 404
12. 详情他人未绑定 → 403
13. 详情已绑定家长 → 可读
14. 更新只传 title → content_text 不变
15. 更新 content_md → content_text 重算
16. 更新他人笔记 → 403
17. 软删 → `deleted_at` 非空且 commit；删他人 → 403

### 8.3 `tests/test_notes_api.py`（11）

TestClient + `get_db` 覆盖（复用 S2-2 模式），列表接口 monkeypatch `paginate_query`。

1. POST 201：返回 id/title、无 `content_text`、无 `deleted_at`
2. POST 空标题 → 422/42200
3. POST 教师角色 → 403/40300
4. GET 列表：`data` 4 键、items 无 `content_md`
5. GET 列表非法排序字段 → 422/42200
6. GET 详情本人 → 200
7. GET 详情他人未绑定 → 403（真实接口上的 A/B 403，补 S2-3 欠的 curl 同类证据）
8. GET 详情已绑定家长 → 200
9. GET 详情不存在 → 404/40400
10. PATCH 标题 → 200 且只改标题
11. DELETE → 204 空体且 `deleted_at` 置位

## 9. 验收

```bash
cd backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m pytest -q          # 基线 280 + 38 = 318
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

curl 全流程（真实数据，结束后清理）：

1. 注册 A、B 两个 student；
2. A `POST /notes` → 201，记录 `note_id`；
3. A `GET /notes` → 1 条，`data` 含 4 个分页字段；
4. A `GET /notes/{id}` → 200；
5. B `GET /notes/{id}` → 403/40300（S2-3 的真实接口证据）；
6. A `PATCH /notes/{id}` 改标题/正文 → 200；psql 对比 `updated_at` 变化；
7. `q=`、`tag=`、`subject_id=` 各一次筛选结果符合预期（subject 用 psql 临时插入再清理）；
8. A `DELETE /notes/{id}` → 204；`GET /notes` → 空；`GET /notes/{id}` → 404；psql 显示行仍在且 `deleted_at` 非空；
9. psql 核验 `note_chunks` 三个外键存在（`\d note_chunks`）、孤儿行已清空；
10. 清理测试数据（users/notes/subjects），避免污染。

## 10. 已知限制（进 PROGRESS / D-025）

- `q` 是 ILIKE 子串匹配：大数据量慢、无语义/分词；S3 换 jieba + tsvector。
- 软删不可恢复（无回收站接口）；`deleted_at` 行仍占存储。
- 列表只返回本人笔记；家长/老师目前只能通过详情逐条看孩子的笔记，没有“按学生列笔记”的接口。
- `note_kps` 只建表，无对齐逻辑。
- `files` 表建好但没有上传接口（S2-6），`notes.source_file_id` 暂时无法由 API 写入。
- 迁移会删除 83 行无主 chunk（S1-3 实验残留），不可恢复。

## 11. 文档同步

| 文档 | 改动 |
|---|---|
| API.md | §2 五条接口定稿（参数、出参、错误）；§12 TODO 行更新 |
| SCHEMA.md | §4.1 sha256 唯一性定稿（同用户）；§4.3 外键“延后到 S2-5”改为已落库；§10.2 parse_status 说明 |
| AGENTS.md | §9.6 增笔记模块锚点（模型 + 路由） |
| DECISIONS.md | D-025（9 条决策 + 验证 + 限制） |
| PROGRESS.md | S2-5 打勾、状态、遗留、变更日志 |
| requirements.txt / .env.example | 不变 |

## 12. 自检

- [x] 任务卡产出（notes/note_chunks/note_kps/files、api/v1/notes.py）→ §3 / §4
- [x] 软删除 `deleted_at` → §3.2 / §4 / §8
- [x] 同时写 content_md 与 content_text → §5 / §6
- [x] 列表按学科/标签/关键词/时间筛选 → §4.1 / §8.2
- [x] curl 建→改→查→软删→列表不可见 → §9
- [x] updated_at 自动更新 → §3.2 / §9-6
- [x] 复用 S2-3 权限、S2-4 分页 → §4 / §7
- [x] 无 TBD 留给实施者