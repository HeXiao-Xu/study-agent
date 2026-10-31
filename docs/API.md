# API.md — 接口契约

> 来源：《个性化学习智能体-毕业设计完整方案.md》第 6 章 + 附录 B（接口草案），条目格式参照实施计划附录 B2。
> 本文件是前后端的**共同语言**，接口变更必须先改这里再写代码（AGENTS.md §8）。
> 规则：方案未写明的字段一律标 `TODO 待定`，禁止自行编造；每条接口标注权限与类型（同步 / 异步任务 / SSE 流式）。

## 0. 全局约定

- Base path：`/api/v1`；另有 `GET /health`（无前缀，S0-5 交付）
- 命名：路径与字段一律 `snake_case`（与数据库一致，**定死**）
- 认证：Bearer JWT（S2-2 交付）：请求头 `Authorization: Bearer <token>`；载荷 `{sub, role, iat, exp}`，HS256，默认 24h 过期；无 refresh/登出（见 §12）。未特别标注的接口权限默认 `student`，且只能访问自己的数据；RBAC 与数据隔离见下
- 角色与数据范围（S2-3 定稿）：

| 角色 | 数据范围 | 说明 |
|---|---|---|
| student | 仅本人 | 学生数据接口隐式 `WHERE user_id = 当前用户` |
| parent / teacher | 本人 + 已绑定学生 | 绑定关系在 `user_relations`（`teacher_id`=查看方）；跨学生访问必须过 `require_student_access` / `ensure_student_access` |
| admin | 仅专用管理接口 | 通过 `require_role("admin")` 判定；**不继承**学生数据权限 |

- 数据隔离（S2-3 定稿）：访问他人学生数据失败统一 `403/40300`「无权访问该资源」，不区分“无权限”与“不存在”；服务层查询必须显式 `WHERE <model>.user_id = <已授权学生>`，禁止只校验角色就返回数据；token 内 `role` 不作为权限来源（以数据库为准）
- 统一响应：`{code, message, trace_id, data}`（成功 `code=0`；错误结构与码表见 §13，S0-5 已落地）
- trace_id 透出：响应头 `X-Trace-Id` 一律返回；请求头可传 `X-Trace-Id` 续链（S0-5 定稿）
- 分页（S2-4 定稿）：所有列表接口统一 query `page`（默认 1，≥1）+ `page_size`（默认 20，1–100）；响应 `data = {items, total, page, page_size}`；越界/非整数 → `422/42200`；超过末页返回空 `items`，`total` 不变
- 排序（S2-4 定稿）：`sort_by`（字段白名单，各接口在文档中列出）+ `order`（`asc`/`desc`，默认 `desc`）；非白名单字段 → `422/42200`「不支持的排序字段：xxx（可选：...）」；筛选一律显式 query 参数，不使用通用 filter DSL
- 异步任务轮询约定（S2-7 定稿）：提交接口返回 `202` + 任务 `id`；客户端每 1–2s `GET /api/v1/tasks/{id}`，直到 `status ∈ {succeeded, failed}`；本阶段不提供 SSE/WebSocket 推送（S3-5 再定流式）

## 1. 认证（S2-2 定稿）

> 通用约定
> - 认证头：`Authorization: Bearer <jwt>`；载荷 `{sub, role, iat, exp}`（`sub` 为字符串 user_id），HS256，默认 24h。
> - 用户名不区分大小写：注册与登录都会 trim 后转小写；`^[^\s]{3,50}$`（不含空白，3–50 字符）。
> - `role` 以数据库为准：`GET /auth/me` 等接口按 `sub` 回表取用户，token 里的 `role` 只用于快速判断/日志。
> - 三条接口都套统一壳；错误结构与业务码见 §13。

### POST /api/v1/auth/register
- 权限：公开
- 类型：同步
- 状态码：**201**
- 入参（JSON）：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| username | string | 是 | 3–50 字符，不含空白；入库前 trim + 小写 |
| password | string | 是 | 8–128 字符（只存 Argon2id 哈希） |
| nickname | string | 是 | 1–50 字符（trim 后非空） |
| grade | string | 否 | ≤20 字符，可空 |
| role | string | 否 | `student`(默认) / `teacher` / `parent`；`admin` 不可自助注册 |

- 出参：`data` = UserOut：`{id, username, nickname, grade, role, created_at}`（`created_at` ISO-8601 UTC，无 `password_hash`）
- 错误：`422/42200` 参数校验失败（含 `role=admin`）；`409/40900` 用户名已存在

### POST /api/v1/auth/login
- 权限：公开
- 类型：同步
- 入参（JSON）：`{username, password}`（username 同样 trim + 小写）
- 出参：`data` = TokenOut：

```json
{"access_token": "<jwt>", "token_type": "bearer", "expires_in": 86400,
 "user": {"id": 1, "username": "student01", "nickname": "测试用户_1", "grade": "高一", "role": "student", "created_at": "2026-10-26T13:21:07.218738Z"}}
```

- 错误：`401/40100` 用户名或密码错误（用户不存在与密码错误**同文案同状态码**，不泄露账号是否存在）

### GET /api/v1/auth/me
- 权限：需 `Authorization: Bearer <token>`
- 类型：同步
- 出参：`data` = UserOut（同上）
- 错误：`401/40100` 未提供认证凭据 / 无效的认证凭据 / 登录已过期，请重新登录 / 账号不存在或已被删除

## 2. 笔记

## 2. 笔记（S2-5 定稿）

### POST /api/v1/notes
- 权限：`student`（仅本人可建；teacher / parent / admin → 403/40300）
- 类型：同步
- 入参：`title`（1–200）、`content_md`（1–200000）、`subject_id`（可选，必须存在）、`tags`（可选，≤20 个、单个 ≤30 字、去重保序）、`folder`（可选，≤100）
- 出参：`data` = NoteOut
- 备注：服务端由 `content_md` 派生 `content_text`（去公式纯文本，不出参）；`source_file_id` 由解析流水线写，本接口不收；**S3-1 起创建成功后 best-effort 入队 `index.note`**（队列不可用只记 WARNING，不影响 201）
- 错误：`422/42200` 字段校验失败 / 学科不存在；`403/40300` 非 student

### GET /api/v1/notes
- 权限：登录用户（仅本人数据）
- 类型：同步（分页）
- 入参：`subject_id` / `tag`（精确匹配，`tags @> ARRAY[tag]`）/ `q`（标题+正文子串，`%`/`_` 已转义）/ `created_from` / `created_to`（ISO-8601）/ `page` / `page_size` / `sort_by`（`created_at`｜`updated_at`｜`title`）/ `order`（`asc`｜`desc`，默认 `desc`）
- 出参：`data` = `{items: NoteSummary[], total, page, page_size}`
- 备注：仅返回 `deleted_at IS NULL`；`NoteSummary` 不含正文（正文用详情接口取）
- 错误：`422/42200` 分页越界 / 排序字段非白名单（message 列出可选字段）/ 时间格式非法

### GET /api/v1/notes/{note_id}
- 权限：本人，或已绑定该学生的 parent/teacher（S2-3 规则，admin 不绕过）
- 类型：同步
- 出参：`data` = NoteOut（含 `content_md`）
- 错误：`404/40400`「笔记不存在」（含已软删）；`403/40300`「无权访问该资源」

### PATCH /api/v1/notes/{note_id}
- 权限：仅本人且 `student`
- 类型：同步（部分更新）
- 入参：`title` / `content_md` / `subject_id` / `tags` / `folder` 任选；只改传入字段，`content_md` 变则重算 `content_text`；`subject_id` / `tags` / `folder` 传 `null` 表示清空
- 出参：`data` = NoteOut
- 备注：**S3-1 起仅当请求体显式包含 `content_md` 时** best-effort 入队 `index.note`；只改标题/标签不重算向量
- 错误：`404/40400`；`403/40300`「无权修改该资源」；`422/42200` 字段为空 / 学科不存在

### DELETE /api/v1/notes/{note_id}
- 权限：仅本人且 `student`
- 类型：同步（软删除）
- 出参：`204` 无响应体（置 `deleted_at=now()`，行保留）
- 备注：**S3-1 起同一事务删除该笔记全部 `note_chunks`**（检索链路不 join `notes`，靠此保证软删后不再被召回）
- 错误：`404/40400`；`403/40300`「无权删除该资源」

### 笔记对象

- NoteSummary：`id` / `title` / `subject_id` / `tags` / `folder` / `created_at` / `updated_at`
- NoteOut = NoteSummary + `content_md` + `source_file_id`
- `content_text`（检索用）与 `deleted_at` **永不返回**

## 3. 文件上传与解析（S2-6 上传 + S2-8 解析 Worker 定稿）

### POST /api/v1/files
- 权限：`student`（其他角色 403/40300）
- 类型：同步上传返回 + 后台异步解析（S2-8 起：上传成功后自动入队 `parse.document`）
- 请求：`multipart/form-data`，字段名 `file`；可选 query `parse`（默认 `true`）。
  `parse=false` 仅用于编辑器图片：只接受 `image/*`，新记录直接 `parse_status=done`、
  `parse_progress=100`、`parse_finished_at=now`，不入队解析；非图片返回 `422/42200`。
  去重命中返回已有记录且不改其解析状态。
- 成功：`Envelope[FileUploadOut]`
  - 首次：**201**，`deduped=false`
  - 同用户同内容重复上传：**200**，`deduped=true`，返回已有 `id`（不再写对象存储）
- `data` 字段：`id` / `filename` / `mime` / `size` / `sha256` / `parse_status` / `created_at` / `deduped`
- 类型与大小：扩展名白名单 + 文件头 magic 双校验；`UPLOAD_ALLOWED_EXTENSIONS`（默认 `pdf,docx,md,txt,png,jpg,jpeg`）、`UPLOAD_MAX_SIZE_MB`（默认 60）
- 存储：对象键 `uploads/{user_id}/{sha256[:2]}/{sha256}{ext}`（内容寻址，不暴露给客户端）
- 解析副作用：仅当 `parse_status ∈ {pending, failed}` 时入队；`done/parsing` 的去重命中不重复入队
- 入队失败：文件已落库，但接口返回 `500/50000`「任务队列不可用」；重新上传会命中 `sha256` 去重并补入队
- 错误：
  - `400/40000`：请求缺少 `file` 字段
  - `413/41300`：超过大小上限（message 含上限）
  - `422/42200`：扩展名不在白名单 / 文件内容与类型不符 / 文件名为空
  - `403/40300`：非 student
  - `500/50000`：「文件存储不可用」（MinIO 异常，不泄露 endpoint）

### GET /api/v1/files
- 权限：登录用户，仅本人文件
- 类型：同步（分页）
- 入参：`page`（默认 1）、`page_size`（默认 20，1–100）
- 排序：固定 `created_at DESC, id DESC`
- 出参：`Envelope[PageData[FileSummaryOut]]`
- FileSummaryOut：`id` / `filename` / `mime` / `size` / `parse_status` /
  `parse_progress` / `error_msg` / `chunk_count` / `created_at` / `parse_finished_at`
- 备注：`chunk_count` 从 `parse_result_json.chunks` 派生；未完成或无结果时为 0

### GET /api/v1/files/{file_id}/image
- 权限：本人，或已绑定该学生的 parent/teacher（admin 不绕过）
- 类型：同步，返回二进制
- 出参：图片字节；`Content-Type` 为记录 MIME，带 `ETag=sha256`、
  `Cache-Control: private, max-age=300`、`X-Content-Type-Options: nosniff`
- 错误：`404/40400` 文件不存在；`403/40300` 无权访问；`422/42200` 不是图片文件；
  `500/50000` 文件存储不可用
- 备注：内联展示用；首版一次性读入内存

### GET /api/v1/files/{file_id}/parse-status
- 权限：本人或已绑定该学生的 parent/teacher（admin 不绕过）
- 类型：同步
- 出参：`Envelope[FileStatusOut]`：`id` / `filename` / `parse_status` / `parse_progress` / `error_msg` / `chunk_count`
- 状态机（S2-8 定稿）：`pending` → `parsing` → `done` / `failed`
- `parse_progress`：阶段值 `0`（未开始）/`10`（已开始）/`50`（解析完成）/`80`（切片完成）/`100`（入库完成）
- `error_msg`：仅 `failed` 非空，格式 `异常类型: 原因`，≤500 字
- `chunk_count`：解析结果中的切片数；未完成或脏数据为 0
- 轮询建议：前端每 3s 一次，直到 `done`/`failed`；单次上传最多轮询 5 分钟，不做 SSE/WebSocket
- 错误：`404/40400`「文件不存在」；`403/40300`「无权访问该资源」

### GET /api/v1/files/{file_id}/chunks
- 权限：本人，或已绑定该学生的 parent/teacher（admin 不绕过）
- 类型：同步
- 入参：`limit`（默认 3，1–20）
- 出参：`Envelope[ChunkPreviewOut[]]`，按 `chunk_index` 升序
- ChunkPreviewOut：`chunk_index` / `content` / `token_count`
- 备注：S2-13 只用于列表页预览前 3 条；未解析完成返回空数组
- 错误：`404/40400`「文件不存在」；`403/40300`「无权访问该资源」

## 3.5 异步任务（S2-7 定稿）

### POST /api/v1/tasks/demo
- 权限：`student`
- 类型：异步任务提交
- 请求体：`{"seconds": 5, "fail": false}`（`seconds` 1–10，默认 5；`fail` 默认 false）
- 成功：**202**，`Envelope[TaskOut]`：`id` / `name`（`demo.sleep`）/ `status`（`pending`）/ `created_at`
- 错误：`403/40300` 非 student；`422/42200` 参数越界；`500/50000`「任务队列不可用」
- 说明：验收/联调端点；S2-8 起业务接口内部复用 `task_service.create_task`，不经过此端点

### GET /api/v1/tasks/{task_id}
- 权限：仅创建者（admin 不绕过）
- 出参：`Envelope[TaskDetailOut]`：`id` / `name` / `status` / `attempts` / `payload` / `result` / `error` / `created_at` / `started_at` / `finished_at`
- 状态机：`pending → running → succeeded`；可重试失败回 `pending`，第 3 次失败终态 `failed`
- 错误：`404/40400`「任务不存在」；`403/40300`「无权访问该任务」

## 4. 知识点（S2-9 / S2-10 定稿）

### GET /api/v1/kp/subjects
- 权限：登录用户
- 类型：同步
- 出参：`Envelope[SubjectOut[]]`：`id` / `name` / `code` / `stage`
- 备注：当前由导入脚本种出 `math`（高中数学）

### GET /api/v1/kp/tree?subject=math
- 权限：登录用户（原 student 放宽为登录用户，学生仍可读）
- 类型：同步
- 入参：`subject`（学科 **code**，1–30，必填）
- 出参：`Envelope[KpTreeOut]`：

  ```json
  {"subject": {"id": 1, "name": "高中数学", "code": "math", "stage": "高中"},
   "nodes": [{"id": 1, "subject_id": 1, "parent_id": null, "name": "高中数学",
              "code": "MATH", "level": 1, "description": null, "exam_weight": 1.0,
              "order_no": 0, "children": []}]}
  ```

- 备注：一次 SQL 查完同 subject 全部节点（`level, order_no, id` 排序），内存组树；节点按 `order_no, id` 稳定排序
- 错误：`404/40400`「学科不存在」；`422/42200` 缺 `subject`

### POST /api/v1/kp
- 权限：`admin` / `teacher`（其他角色 → 403/40300）
- 类型：同步
- 入参：`subject`（学科 code）/ `parent_id`（可选，必须同 subject）/ `code`（1–50，同 subject 内唯一）/ `name`（1–100）/ `description`（可选，≤500）/ `exam_weight`（可选，0–1）/ `order_no`（可选，≥0，默认 0）
- 出参：**201** `Envelope[KpNodeOut]`（不含 `children`）
- 备注：`level` 由父节点推导（根 1，最深 4），不接受客户端传；`code` 创建后不可改
- 错误：`404/40400` 学科/父节点不存在；`409/40900`「知识点编码已存在」；`422/42200` 层级超 4 / 父节点不属于同一学科

### PATCH /api/v1/kp/{kp_id}
- 权限：`admin` / `teacher`
- 类型：同步（部分更新）
- 入参：`name` / `description` / `exam_weight` / `order_no` / `parent_id` 任选；`parent_id=null` 表示移到根；`code` / `subject_id` 不可改
- 出参：`Envelope[KpNodeOut]`
- 备注：改父时校验目标同 subject、不能是自身/后代（环），且移动后子树高度不超过 4；成功自动 BFS 重算该节点及全部后代 `level`
- 错误：`404/40400` 节点/新父节点不存在；`422/42200` 成环 / 超过 4 级 / 跨学科

### DELETE /api/v1/kp/{kp_id}
- 权限：`admin` / `teacher`
- 类型：同步（物理删除）
- 出参：**204** 无响应体
- 备注：删除保护顺序——有子节点、被 `note_kps` 引用、被 `knowledge_edges` 引用，任一命中即拒绝（不级联）
- 错误：`404/40400`；`409/40900`「存在子知识点，请先删除子节点」/「已被笔记引用，无法删除」/「存在知识点关系引用，无法删除」

### PUT /api/v1/kp/order
- 权限：`admin` / `teacher`
- 类型：同步，单事务
- 入参：`parent_id`（目标父节点，`null` 表示根级）、`ordered_ids`（1–200，目标父级完整子节点顺序）、`moved_id`（可选，被移动节点）
- 语义：传 `moved_id` 时先改父级、重算层级，再按 `ordered_ids` 写 `order_no`；不传只做同级排序
- 成功：**204** 无响应体
- 备注：`ordered_ids` 必须包含目标父级的全部子节点且包含 `moved_id`；跨父级移动时源父级剩余节点也会归一化为连续 `order_no`
- 错误：`404/40400` 父级/节点不存在；`422/42200` 重复/缺兄弟/跨学科/成环/超 4 级/`moved_id` 不在列表；`403/40300` 非教师/管理员

### POST /api/v1/kp/align/notes/{note_id}
- 权限：笔记所有者（`student`；他人笔记 403/40300，不存在/已软删 404/40400）
- 类型：异步任务（`kp.align`）
- 成功：**202** `Envelope[TaskOut]`：`id` / `name` / `status` / `created_at`
- 备注：重跑会删除该笔记 `source='ai'` 的旧关联后重算；`source='manual'`（用户已确认）保留
- 错误：`403/40300`；`404/40400`「笔记不存在」；`500/50000`「任务队列不可用」

### GET /api/v1/kp/align/pending
- 权限：登录用户（仅返回本人笔记的待确认项）
- 类型：同步分页
- 入参：`note_id`（可选，≥1）/ `page` / `page_size`（1–100）
- 出参：`Envelope[PageData[PendingAlignOut]]`：

  ```json
  {"items": [{"note_id": 3, "note_title": "函数单调性笔记",
              "note_excerpt": "函数单调性：设函数 f(x) 在区间 D 上……",
              "kp_id": 12, "kp_name": "函数的单调性", "kp_code": "MATH-FUNC-02",
              "confidence": 0.68}],
   "total": 1, "page": 1, "page_size": 20}
  ```

- 备注：只列 `source='ai' AND confirmed=false` 且 `confidence` 在 `[0.55, 0.75)` 的行；笔记已软删不返回；固定排序 `note_id DESC, kp_id`；`note_excerpt` 为正文去首尾空白后前 300 字，超出以 `…` 结尾，空正文为空串
- 错误：`422/42200` 分页/筛选参数非法

### POST /api/v1/kp/align/confirm
- 权限：登录用户（仅本人笔记）
- 类型：同步
- 入参：`{"items":[{"note_id":3,"kp_id":12}]}`，1–100 对
- 出参：`Envelope[AlignBatchOut]`：`{"confirmed": 1, "deleted": 0, "skipped": 0}`
- 备注：命中行置 `confirmed=true`、`source='manual'`；不属于本人/不存在的对计入 `skipped`（不报 404）
- 错误：`422/42200` 空列表 / 超过 100 对

### POST /api/v1/kp/align/reject
- 权限：登录用户（仅本人笔记）
- 类型：同步
- 入参：同上
- 出参：`Envelope[AlignBatchOut]`：`{"confirmed": 0, "deleted": 1, "skipped": 0}`
- 备注：只删除 `source='ai' AND confirmed=false` 的行；已确认或 manual 行计入 `skipped`；忽略后重跑可能再次出现
- 错误：`422/42200`

## 5. RAG 问答（论文核心）

### POST /api/v1/qa/ask
- 权限：student
- 类型：SSE 流式
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | question | string | 是 | 用户问题，1–500 字 |
  | scope | object | 否 | {subject_id?, notebook_id?, start_date?, end_date?} |
  | conversation_id | string | 否 | 不传则新建会话 |

- SSE 事件：
  - `meta`：{citations:[{index,note_id,chunk_id,title,heading_path,page_no,snippet}]}
  - `delta`：{text:"..."}
  - `done`：{message_id, tokens, latency_ms, refused:bool}
- 错误码：401 未登录 / 403 无权访问该 scope / 429 超出频率限制 / 500 生成失败
- 备注：无检索依据时返回 refused=true 与固定拒答文案，不调用 LLM
- 检索链路与参数（方案 6.4）：向量 top-20 + 全文 top-20 → RRF（k=60）→ Rerank 取 top-6 → 上下文预算 4k–6k token；拒答阈值 τ=0.35（重排分归一化，需实测校准）；温度 0.3；多轮仅取最近 3 轮做 query 改写；缓存 (user_id, 规范化问题, scope) 24h

### GET /api/v1/qa/messages/{id}/citations
- 权限：student（仅本人消息）
- 类型：同步
- 出参：引用列表（对应 message_citations 表）

## 6. 错题本

### POST /api/v1/mistakes
- 权限：student
- 类型：同步
- 入参：题目 + 我的答案（`image_file_id` 可选，拍照录入）
- 出参：TODO（S4-2）

### POST /api/v1/mistakes/{id}/analyze
- 权限：student
- 类型：异步任务
- 说明：触发 AI 诊断；五维输出见方案 6.3（知识点定位 / 错因分类 6 类+unknown / 第一处错误步骤 / 变式训练 2–3 道 / 复习建议）
- 出参：任务受理结果（TODO，S4-3）

### GET /api/v1/mistakes/{id}/analysis
- 权限：student
- 类型：同步
- 出参：诊断结果（mistake_analyses 表）

## 7. 题目生成

### POST /api/v1/questions/generate
- 权限：student
- 类型：异步任务 ⚠（TODO 同步/异步 S4-4 定）
- 说明：生成后必须过「格式校验（LaTeX 可编译、选项齐全、答案在选项内）+ 独立复算」两道关，不一致丢弃或重生成（最多 2 次），通过后入库并标 `verified`（方案 6.5）
- 入参：TODO（S4-4）

## 8. 组卷与作答

### POST /api/v1/papers/generate
- 权限：student
- 类型：异步任务 ⚠（TODO S5-2 定）
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | kp_ids | array | 是 | 知识点覆盖清单 |
  | qtype_ratio | object | 是 | 题型配比 |
  | difficulty_dist | object | 是 | 难度分布（如 3:5:2） |
  | total_score | number | 是 | 总分 |

- 出参：试卷 JSON + 预览（题干与答案分离，方案 6.5）
- 备注：组卷为「约束满足 + 贪心打分」：掌握度 < 0.5 优先基础题、> 0.8 配难题、排除近 14 天做过的题

### GET /api/v1/papers/{id}/export.pdf
- 权限：student
- 类型：同步（Playwright 渲染）
- 出参：PDF 下载

### POST /api/v1/answers
- 权限：student
- 类型：同步
- 说明：提交作答 → 回写掌握度（方案 6.6：s = 1/0.5/0，K_eff = K0/difficulty，M ← clamp(M + K_eff·(s−M), 0, 1)；S 更新与 due_at 计算）
- 入参/出参：TODO（S5-4）

## 9. 复习与报告

### GET /api/v1/review/today
- 权限：student
- 类型：同步
- 出参：今日复习清单（priority = 0.5·(1−M_t) + 0.3·逾期程度 + 0.2·考纲权重；M_t < 0.4 天天出现；总量控制在 30–40 分钟，方案 6.6）

### GET /api/v1/reports/mastery?range=30d
- 权限：student
- 类型：同步
- 出参：掌握度数据（雷达图/热力图/学习轨迹所需，方案 6.8）

## 10. Agent

### POST /api/v1/agent/tasks
- 权限：student
- 类型：异步任务
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | type | string | 是 | "weekly_mindmap" \| "mistake_paper" |
  | input | object | 是 | 任务输入（结构随 type 定，TODO S6-3/S6-4） |

- 约束（方案 6.7）：最大步数 12；单任务 token 预算上限；工具入参 JSON Schema 校验；写操作必须经人工确认；全程步骤日志 + 引用收集

### GET /api/v1/agent/tasks/{id}
- 权限：student（仅本人任务）
- 类型：同步
- 出参：任务状态 + 步骤列表（agent_steps，支持回放）

### POST /api/v1/agent/tasks/{id}/confirm
- 权限：student
- 类型：同步
- 说明：人工确认（human-in-the-loop），任务从 waiting_confirm 继续

## 11. 运维

### GET /api/v1/admin/usage?range=7d
- 权限：admin ⚠（RBAC 细则 S2-3）
- 类型：同步
- 出参：用量统计（llm_call_logs 聚合：scene/model/tokens/cost/latency）

### POST /api/v1/admin/index/rebuild（S3-1 定稿）
- 权限：`admin`（其他角色 403/40300）
- 类型：异步（**202**，立即返回 run_id；每篇未删除笔记一个 `index.note` 任务）
- 入参：无
- 出参：`Envelope[RebuildStart]`：`run_id`（32 位 hex）/ `total_notes` / `purged_chunks`
- 行为：
  - 先清掉“软删笔记仍残留”的 `note_chunks`（`purged_chunks` 为删除行数），提交后再建任务
  - 任务 payload 固定 `{"note_id": <id>, "run_id": "<run_id>"}`，同一 run_id 聚合进度
  - 直接删旧块再插新块（`index_chunks(replace=True)`），无需额外去重
- 错误：`403/40300`；`422/42200`「没有可重建的笔记」（库中无未删除笔记）；`500/50000`「任务队列不可用」（已提交的清理由此前的 commit 保留，返回失败）
- 备注：全量重建按笔记 `content_md` 重建，文档笔记的 `page_no/bbox_json` 会清空（S3-1 已知代价）；并发重建/并发保存同一笔记可能触发 `uq_note_chunks_note_chunk_index` 唯一冲突，由任务 runner 重试收敛

### GET /api/v1/admin/index/runs/{run_id}（S3-1 定稿）
- 权限：`admin`（其他角色 403/40300）
- 类型：同步
- 入参：路径 `run_id`，必须匹配 `^[0-9a-f]{32}$`（否则 422/42200）
- 出参：`Envelope[RebuildProgress]`：
  `run_id` / `total` / `pending` / `running` / `succeeded` / `failed` / `percent`（0–100 整数）/ `chunks`（成功任务切片数之和）/ `started_at` / `finished_at`（全部终态才非空）/ `failures`（≤20 条，`{note_id, error}`）
- 聚合方式：按 `name='index.note' AND payload->>'run_id'=run_id` 查 `async_tasks`，Python 内聚合，不建新表
- 错误：`403/40300`；`404/40400`「索引重建记录不存在」；`422/42200` run_id 格式非法

### GET /health
- 权限：公开
- 类型：同步
- 说明：无 `/api/v1` 前缀；S0-5 交付，健康检查

## 12. 待定接口清单（TODO，方案未列、对应任务定稿时补充）

| 模块 | 缺口 | 定稿任务 |
|---|---|---|
| 认证 | 登出 / refresh / token 吊销策略 | 后续（S2-2 已交付注册/登录/me；无状态 JWT 暂无吊销） |
| 笔记 | 笔记本（folder）管理、回收站恢复、按学生列笔记（家长视角） | 后续（S2-5 已交付建/列表/详情/更新/软删） |
| 文件 | 下载 / 删除、签名 URL 接口 | 后续（S2-13 已交付列表/解析状态/切片预览） |
| 异步任务 | 任务列表 / 取消 / 重跑、running 心跳回收、SSE 状态推送 | 后续（S2-7 已交付提交/轮询/重试；S3-5 定流式） |
| 知识点 | 树的导入与管理端接口 | S2-9 |
| 错题 | 列表 / 统计看板 | S4-2 / S4-8 |
| 复习 | 计划手动调整 | S5-5 |

## 13. 错误码表

S0-5 定稿（落地于 `backend/app/core/exceptions.py`）：

- 规则：`0` = 成功；错误码 = **HTTP 状态前 3 位 + 2 位序号**；业务码 6xxxx 起按模块分段（S2 各业务卡起用）
- trace_id 透出：响应头 `X-Trace-Id` 一律返回；请求头可传 `X-Trace-Id` 续链

| code | 含义 | HTTP |
|---|---|---|
| 40000 | 通用请求错误 | 400 |
| 40100 | 未认证 | 401 |
| 40300 | 无权限 | 403 |
| 40400 | 资源不存在 | 404 |
| 40900 | 资源冲突（如用户名已存在） | 409 |
| 41300 | 文件过大（S2-6） | 413 |
| 42200 | 参数校验失败 | 422 |
| 42900 | 限流 | 429 |
| 50000 | 服务器内部错误 | 500 |

---

> 维护规则（AGENTS.md）：接口变化必须同步本文件；前后端字段命名以本文件为准（snake_case）；与本文件冲突的实现视为 bug。
