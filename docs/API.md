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
  `parse=false` 表示只存原件：允许图片（编辑器插图）与 PDF/DOCX（试卷原件，切题由 `question.extract` 负责，不建笔记）。
  新记录直接 `parse_status=done`、`parse_progress=100`、`parse_finished_at=now`，不入队解析；
  其他类型返回 `422/42200`（S4-1 起由“仅图片”放宽）。
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

### 4.5 知识图谱关系（S4-5）

> 四类关系：`contains`（树派生）/ `prerequisite`（LLM 推断）/ `related` / `confusable`（向量候选 + LLM 复核）。AI 推断的边默认 `review_status='pending'`，只有人工通过才是 `approved`；`rejected` 作为墓碑保留，重跑不复活。全部接口仅 `admin` / `teacher`。

#### POST /api/v1/kp/graph/build
- 权限：admin / teacher
- 类型：异步（`graph.build`）
- 入参：`{"subject_id": 7, "relations": ["contains", "prerequisite", "related", "confusable"], "limit": 50}`（`relations`/`limit` 可选，`limit` 只对前置推断生效）
- 出参：202 `Envelope[TaskOut]`
- 备注：`subject_id` 必填；`contains` 直接 `approved`（自动补 `reviewed_at`，`reviewed_by` 为空）；其余 `pending`；单次调用上限 180 次，超限任务仍 `succeeded` 且结果 `truncated=true`；任务超时口径见 `TASK_JOB_TIMEOUT_SECONDS`（默认 1800 s）
- 错误：`403/40300`（学生）、`422/42200`（未知 relation）、`500/50000`（队列不可用）

#### GET /api/v1/kp/graph/edges
- 权限：admin / teacher
- 入参：`status`（默认 `pending`，可选 `approved`/`rejected`/`all`）、`relation`、`subject_id`、`q`（任一端名称包含）、`page`/`page_size`/`sort_by`/`order`
- 出参：`Envelope[PageData[GraphEdgeOut]]`
- `GraphEdgeOut`：`{"id": 12, "src_kp_id": 3, "src_name": "函数单调性", "dst_kp_id": 8, "dst_name": "导数应用", "relation": "prerequisite", "weight": 0.82, "source": "ai", "review_status": "pending", "reviewed_at": null, "created_at": "2026-11-04T01:00:00Z"}`
- 备注：两端名称一次 `IN` 批查，禁止 N+1；`weight` = 置信度（前置）或余弦相似度（相关/易混）；排序在 `created_at`/`weight`/`id` 之上**始终追加 `id` 兜底**（同批写入的边时间戳相同，否则分页会重复/漏行）
- 错误：`403/40300`、`422/42200`

#### POST /api/v1/kp/graph/edges/{edge_id}/review
- 权限：admin / teacher
- 入参：`{"approve": true}`
- 出参：`Envelope[GraphEdgeOut]`
- 备注：幂等——重复提交同一结论只刷新 `reviewed_at`；`reviewed_by` 记当前账号；服务层直接 `commit`（路由的 `get_db` 不提交）
- 错误：`403/40300`、`404/40400`

#### POST /api/v1/kp/graph/edges/review
- 权限：admin / teacher
- 入参：`{"edge_ids": [1, 2, 999], "approve": false}`
- 出参：`Envelope[{"updated": 2, "skipped": 1}]`（不存在的 id 计入 `skipped`）
- 错误：`403/40300`、`422/42200`（空数组/超过 200 条）

#### GET /api/v1/kp/graph/snapshot
- 权限：任意登录用户（图谱结构非隐私数据；学生也能看）
- 入参：`subject_id`（必填，int ≥1）
- 出参：`Envelope[GraphSnapshotOut]`，`{"subject": {"id": 7, "name": "高中数学"}, "nodes": [{"id": 12, "name": "导数与函数的单调性", "level": 3, "parent_id": 9, "exam_weight": 0.8, "mistake_count": 2, "mastery": 0.42}], "edges": [{"src_kp_id": 3, "dst_kp_id": 12, "relation": "prerequisite", "weight": 0.95}], "stats": {"nodes": 108, "edges": 264, "pending_edges": 50, "by_relation": {"contains": 107, "prerequisite": 114, "related": 4, "confusable": 39}}}`
- 备注：`edges` **只含 `review_status='approved'`**；`stats.pending_edges` 只给计数（老师视角提示待审核量），不返回 pending 边；`by_relation` 四个键恒在（无该关系时为 0）；`mistake_count` 口径 = `mistakes(user_id=当前用户) → questions → question_kps` 去重计数，老师也是本人口径；`mastery`（S4-7）= 当前用户在该知识点的**折算后**掌握度 `M_t`（`mastery.mastery · exp(−Δt/S)`），**无行 = `null`（未评估）**，前端据此配色；`mistake_count` 保留在详情侧栏，不再参与节点配色
- 错误：`401/40100`、`404/40400`（学科不存在）、`422/42200`

#### GET /api/v1/kp/graph/nodes/{kp_id}
- 权限：任意登录用户
- 出参：`Envelope[GraphNodeDetailOut]`，字段见 `docs/spec/s4-6-graph-view.md` §3.1（含 `path` 面包屑、四类 approved 邻居、本人笔记与错题）
- 备注：`notes` 只取 `note_kps.confirmed=true` + `notes.deleted_at IS NULL` + 本人，最多 20 条；`mistakes` 按 `created_at DESC` 最多 20 条，`stem` 为题干前 60 字；四类邻居都只取 approved，`contains` 不出现在侧栏（父链由 `path` 表达）
- 错误：`401/40100`、`404/40400`（知识点不存在）、`422/42200`

#### GET /api/v1/kp/graph/stats
- 权限：admin / teacher
- 入参：`subject_id`（可选）
- 出参：`Envelope[{"subject_id": 7, "nodes": 108, "edges": 152, "by_relation": {"contains": 107, "prerequisite": 30}, "by_status": {"approved": 107, "pending": 45}, "last_built_at": "..."}]`
- 错误：`403/40300`

### 掌握度（S4-7）

#### POST /api/v1/kp/mastery/recompute
- 权限：`student`（teacher/parent/admin 403/40300）
- 类型：同步
- 说明：按时间序回放本人全部错题的「作答事件」重建掌握度。事件来源：每条错题按状态折算 s（`待订正`=0 / `已订正`=0.5 / `已掌握`=1），事件时间取 `last_review_at`，为空则取 `created_at`；难度取 `questions.difficulty`；一条错题挂 K 个知识点就产生 K 次同类事件。**覆盖式重建**：先删本人 `mastery` 全部行，再按时间序重算；无 `question_kps` 的错题只计数不产生事件。
- 出参：`Envelope[{"events_replayed": 44, "rows_built": 13, "skipped_no_kp": 31}]`
- 备注：幂等（同数据跑两次结果一致）；只重建不新增事件来源
- 错误：`401/40100`、`403/40300`、`422/42200`

#### GET /api/v1/kp/mastery
- 权限：`student`（只读本人）
- 类型：同步
- 入参：`subject_id`（可选，int ≥1）、`page` / `page_size`（统一分页）、`sort_by`（白名单 `mastery`｜`due_at`｜`attempts`｜`kp_id`，默认 `mastery`）/ `order`（默认 `asc`，即最薄弱优先）
- 出参：`Envelope[PageData[MasteryOut]]`，`MasteryOut = {"kp_id": 12, "kp_name": "导数与函数的单调性", "subject_id": 7, "mastery": 0.462, "mastery_t": 0.353, "attempts": 5, "correct_cnt": 5, "stability": 37.78, "last_practice_at": "...", "due_at": "..."}`
- 备注：`mastery` 是库存原值，`mastery_t` 是**按当前时间折算**的有效掌握度（无 `last_practice_at` 时等于 `mastery`）；**只返回有行（已评估）的知识点**，没有行代表未评估而不是 0 掌握；同 `mastery` 值多时按 `kp_id ASC` 兜底，避免翻页重复
- 错误：`401/40100`、`403/40300`、`422/42200`

## 5. RAG 问答（论文核心）

### POST /api/v1/retrieval/search（S3-2）
- 权限：`student`（teacher/parent/admin 403/40300）
- 类型：同步 JSON（非流式）
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | query | string | 是 | 1–500 字，去空白后非空 |
  | top_k | int | 否 | 1–20，缺省 `RETRIEVAL_TOP_K=6` |
  | rerank | bool | 否 | 缺省 `RETRIEVAL_RERANK_ENABLED=true`；false 走 RRF 顺序 |
  | retrieval | string | 否 | `vector`/`hybrid`/`hybrid_rerank`；缺省保持原行为 |
  | debug | bool | 否 | 默认 false；true 才返回候选明细 |
  | scope | object | 否 | `{subject_id?, folder?, start_date?, end_date?, chunk_types?}` |

- `retrieval` 与 `rerank` 冲突：vector/hybrid + rerank=true、hybrid_rerank + rerank=false 均 422。
- `vector` 复用混合检索的向量召回后取前 top_k，延迟口径偏保守。

- scope 语义：`folder` 精确匹配 `notes.folder`（当前无 notebook 表）；`start_date/end_date` 按 `notes.created_at`（UTC 日期，end 含当天）；`chunk_types ∈ {question,note,formula}`，传 `[]` 为 422；未知字段 422。
- 出参：`query/top_k/rerank/elapsed_ms/embedding_ms/rerank_info/hits[]/debug?`
  - hit：`chunk_id/note_id/note_title/chunk_index/chunk_type/content/snippet/heading_path/page_no/vector_rank/vector_distance/fulltext_rank/fulltext_score/rrf_score/rerank_score`
  - `debug`：`tsquery/vector_ms/fulltext_ms/vector[]/fulltext[]/fused[]`（完整候选，最多每路 20 条，仅调试用）
  - `rerank_info`：开启重排时返回 `{model,candidates,top_k,tokens,latency_ms,cost_yuan,fallback,error}`；关闭时为 null
- 备注：空知识库/无命中返回 200 + `hits=[]`；rerank 失败自动回退 fused（`rerank_info.fallback=true`），接口不报错；检索恒过滤 `user_id` 与 `notes.deleted_at IS NULL`。
- 错误码：401 未登录 / 403 非 student / 422 参数非法 / 500 Embedding 不可用
- 性能口径（S3-2 验收）：HTTP 端到端、`rerank=false`、20 问、预热 3 次，P95 < 500ms（含查询 Embedding）；实测见 `docs/plan/s3-2-retrieval-service.md`。

### POST /api/v1/qa/ask
- 权限：student
- 类型：SSE 流式（`text/event-stream`）
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | question | string | 是 | 用户问题，1–500 字；首尾空白会被裁剪 |
  | scope | object | 否 | {subject_id?, folder?, start_date?, end_date?}（语义同 §5 检索接口，S3-5 复用） |
  | conversation_id | string | 否 | 十进制正整数字符串；不传则新建会话 |

- SSE 事件：
  - `meta`：`{conversation_id(字符串), user_message_id, citations:[{index,note_id,chunk_id,title,heading_path,page_no,snippet}]}`；`citations` 为全部上下文引用，编号供正文 `[n]` 使用
  - `delta`：`{text:"..."}`；校验后的文本块，0..N 个；拼接后等于最终正文（含补充声明）。S3-6 起完整生成、校验/最多重试一次后才发 `delta`，首字延迟增加
  - `done`：`{message_id, conversation_id(字符串), tokens, latency_ms, refused, refusal_reason, suggestions, cached, cost_yuan}`；`tokens`=所有 LLM 尝试（首轮+重试）的回答 token + 改写 token，`latency_ms`=服务端总耗时
    - `refusal_reason`：`null` / `no_context` / `low_score` / `empty_answer` / `no_valid_citation`
    - `suggestions`：`[{type:"rephrase"|"note", text, note_id}]`；正常回答为空数组，拒答固定返回换问法+补笔记两条
    - `cached`：S3-7 起；命中 Redis 问答缓存为 `true`，此时 `tokens=0`、不再调用 LLM/Embedding，但仍落新的 assistant 消息与引用
    - `cost_yuan`：S3-9 起；本次回答真实 LLM 费用（含查询改写），缓存/未调 LLM 为 `0.0`
  - `error`：`{code:50000,message:"生成失败"}`；流中失败后连接关闭，不再发 `done`
- 错误码：401 未登录 / 403 非 student / 404 会话不存在或不属于当前学生（40400，不泄露存在性）/ 422 入参非法（42200）/ 500 生成失败
- 备注：
  - 先落 user 消息，正常结束后落 assistant + citations；断连时关闭上游 LLM，保留 user、不落 assistant。
  - 无检索依据时 `refused=true` 与固定拒答文案，不调用 LLM；chitchat 不检索。
  - chitchat/拒答也先发 `meta`（citations 为空），再发一次 `delta` 全文，再发 `done`。
  - S3-6 引用校验：整篇无合法引用→重试一次；仍无合法引用→拒答；有合法引用但部分块无引用/含越界编号→去掉越界编号，只给未引用块加 `【以下为模型补充，未在你的资料中找到依据】`，保留回答。`message_citations` 只落最终正文中的合法 `[n]`。
  - 本轮不实现限流；429 暂不返回。
  - 检索链路与参数（方案 6.4）：向量 top-20 + 全文 top-20 → RRF（k=60）→ Rerank 取 top-6 → 上下文预算 4k–6k token；拒答阈值 τ=0.35（重排分归一化，需实测校准）；温度 0.3；多轮仅取最近 3 轮做 query 改写；缓存 (user_id, 规范化问题, scope) 24h

### GET /api/v1/qa/messages/{id}/citations
- 权限：student（仅本人消息）
- 类型：同步
- 出参：`message_citations` 表字段 `id/message_id/chunk_id/note_id/question_id/score/snippet/page_no/bbox_json/rank`，按 `rank,id` 升序
- 错误：不存在/越权统一 404/40400「消息不存在」

### GET /api/v1/qa/conversations
- 权限：student（仅本人会话）
- 类型：同步
- 入参：`limit`（可选，默认 50，1–100）
- 出参：`Envelope[QaConversationOut[]]`，按最近消息时间倒序；无消息按 `created_at`
- `QaConversationOut`：`id`（字符串）/ `title` / `scope`（同 `POST /qa/ask` 的 scope，可为 null）/ `created_at` / `last_message_at` / `message_count`
- 备注：`title` 为空时回退首条 user 消息前 50 字，再回退「新对话」；`message_count` 只统计 `role in ('user','assistant')`
- 错误：401/40100；403/40300；422/42200

### GET /api/v1/qa/conversations/{conversation_id}/messages
- 权限：student（仅本人会话）
- 类型：同步
- 出参：`Envelope[QaConversationDetailOut]`：`conversation` 同上，`messages` 按消息 id 升序
- `QaHistoryMessageOut`：`id` / `role`（user|assistant）/ `content_md` / `created_at` / `refused` / `citations`
- `QaHistoryCitationOut`：`index`（=rank，空为 0）/ `note_id` / `chunk_id` / `title` / `heading_path` / `page_no` / `snippet` / `score` / `note_available`
- 备注：引用按 `rank,id` 升序；`title/heading_path` 左连接 `notes/note_chunks`；软删笔记 `note_available=false`；历史拒答仅按正文与 `REFUSAL_TEXT` 相等推导，不恢复当时 reason/suggestions
- 错误：404/40400「会话不存在」（含越权）；401/40100；403/40300

### PATCH /api/v1/qa/conversations/{conversation_id}
- 权限：student（仅本人会话）
- 类型：同步
- 入参：`{"title": "新标题"}`；trim 后 1–80 字
- 出参：`Envelope[QaConversationOut]`
- 错误：404/40400；422/42200 空白或超长

### DELETE /api/v1/qa/conversations/{conversation_id}
- 权限：student（仅本人会话）
- 类型：同步（物理删除）
- 出参：`204` 无响应体
- 备注：依赖 `messages` / `message_citations` 的数据库级联
- 错误：404/40400；401/40100；403/40300

## 5.5 题库与试卷切题（S4-1 定稿）

> 题库为**公共语料**（`questions` 无 `user_id`）：任何登录用户可读全部题目；写限创建者本人或 teacher/admin。
> 枚举：`qtype` = `单选` / `多选` / `填空` / `解答`；`origin` = `textbook` / `exam` / `mock` / `upload` / `ai`（TEXT + CHECK）。
> 判重两道闸（命中任一即视为同一题）：规范化题干 `stem_hash` 命中 `UNIQUE(subject_id, stem_hash)`，或题干向量余弦 ≥ 0.92。

### POST /api/v1/questions/import
- 权限：登录用户；`student` 的 `origin` 只能是 `upload`（其他值 `403/40300`）
- 类型：异步任务（`question.extract`，用 §3.5 的 `GET /api/v1/tasks/{task_id}` 轮询，不新增任务查询接口）
- 请求：`multipart/form-data`，字段名 `file`（`.pdf` / `.docx`）；query `subject_id`（必填，正整数）、`origin`（默认 `upload`）
- 成功：**202** `Envelope[TaskOut]`：`id` / `name`（`question.extract`）/ `status`（`pending`）/ `created_at`
- 原件：落 `files` 表（`parse=false`，`parse_status=done`、`parse_progress=100`），不入 `parse.document`；试卷不写笔记、不切片、不进检索池
- 任务结果 `result`（`status=succeeded` 后）：

```json
{"file_id": 96, "subject_id": 7, "detected_count": 20, "expected_count": 20,
 "created": 20, "duplicated": 0,
 "failed_items": [{"index": 13, "reason": "题目抽取失败（已重试 2 次）：选择题至少需要 2 个选项"}],
 "degraded": false, "warnings": [], "elapsed_ms": 131948}
```

- 备注：`failed_items` 只装**单题**失败（`index` 为卷面题号，1-based；`reason` 截断到 200 字），任务仍 `succeeded`；`degraded=true` 表示规则切分不可信、改用 `mode=block` 逐块抽取；整卷无文本 / 扫描版 / 全部题目抽取失败（含一个题号都没切出）时任务 `failed`，`error` 写明原因
- 错误：`400/40000` 缺 `file` / 非 PDF 或 DOCX / 非法 `origin`；`403/40300` 学生用了非 `upload` 的 `origin`；`404/40400` 学科不存在；`422/42200` 缺 `subject_id`；`500/50000`「任务队列不可用」（沿用 S2-7，spec 原写 `503/50300`，以本契约为准）

### GET /api/v1/questions
- 权限：登录用户（公共题库，不按 `user_id` 过滤）
- 类型：同步（分页）
- 入参：

  | 参数 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | page / page_size | int | 否 | 同 §0（默认 1 / 20，1–100） |
  | subject_id | int | 否 | 学科 id |
  | qtype | string | 否 | `单选` / `多选` / `填空` / `解答` |
  | kp_id | int | 否 | 只出挂了该知识点的题（`EXISTS` 子查询，一题多知识点不产生重复行） |
  | origin | string | 否 | 题目来源 |
  | mine | bool | 否 | `true` 只看自己创建的题（实现为布尔 `mine`，前端传 `mine=true`；spec 原写 `created_by=me`） |
  | verified | bool | 否 | 答案是否来自卷面 |
  | keyword | string | 否 | 题干子串（`ILIKE`，`%`/`_` 已转义） |
  | source_file_id | int | 否 | 只出某份导入试卷的题 |
  | sort_by | string | 否 | 白名单 `created_at` / `id` / `difficulty`，默认 `created_at` |
  | order | string | 否 | `asc` / `desc`，默认 `desc` |

- 出参：`Envelope[PageData[QuestionSummary]]`
- 排序：按 `sort_by` + `order` 主排序后**追加 `id DESC` 兜底**；同一次导入的题 `created_at` 相同，没有 tiebreaker 时翻页会重复/漏行
- `QuestionSummary`：`id` / `subject_id` / `qtype` / `difficulty` / `origin` / `verified` / `stem_md` / `source_file_id` / `created_by` / `created_at` / `kp_names`（`list[str]`，一页一次 `IN` 批查填充，按 `question_kps.weight` 降序）
- 示例：

```json
{"code": 0, "message": "ok", "trace_id": "4f1c…",
 "data": {"items": [{"id": 12, "subject_id": 7, "qtype": "单选", "difficulty": 2,
                     "origin": "upload", "verified": true,
                     "stem_md": "1. 已知函数 $f(x)=x^2-2x$，则 $f(x)$ 的最小值为（  ）",
                     "source_file_id": 96, "created_by": 18,
                     "created_at": "2026-11-03T02:41:07.218738Z",
                     "kp_names": ["一元二次函数"]}],
          "total": 20, "page": 1, "page_size": 20}}
```

- 错误：`422/42200` 分页越界 / 排序字段非白名单（message 列可选字段）

### GET /api/v1/questions/{question_id}
- 权限：登录用户
- 类型：同步
- 出参：`Envelope[QuestionDetail]`
- `QuestionDetail` = `QuestionSummary` + `options_json` / `answer_md` / `analysis_md` / `stem_latex` / `tags` / `kps`
- `kps[]` 元素：`{kp_id, kp_name, kp_code, weight}`，按 `weight` 降序；`weight` 是 **JSON number（float，如 `0.93`）**，不是字符串 `"0.930000"`（DB 仍为 `NUMERIC(8,6)`）
- 备注：**没有 `kp_ids` 字段**；前端从 `kps[].kp_id` 取（spec 原提过 `kp_ids`，以本契约为准）
- 错误：`404/40400`「题目不存在」

### POST /api/v1/questions
- 权限：登录用户；`student` 的 `origin` 只能 `upload`（否则 `403/40300`）
- 类型：同步，**201**
- 入参：`{subject_id, stem_md(≥5), options?(list[{key,text}]), answer_md?, analysis_md?, qtype, difficulty(1–5), kp_ids?, origin?(默认 upload), tags?}`
- 行为：规范化题干 → 判重（命中 `409/40900`）→ 一次 embedding → 落库；`kp_ids` 为人工指定，直接写 `question_kps(weight=1.0)`，不参与自动对齐；`verified` 固定 `false`（人工录入没有卷面答案来源）
- 题型/选项交叉校验：`单选` / `多选` 至少 2 个选项且 `key` 不重复；`填空` / `解答` 不得带选项；违反 → `422/42200`
- 出参：`Envelope[QuestionDetail]`
- 错误：`409/40900`「题目已存在（题库里已有同一道题）」；`404/40400` 学科不存在；`422/42200` 字段非法 / 题型与选项不自洽 / 知识点不存在或不属于该学科

### PATCH /api/v1/questions/{question_id}
- 权限：创建者本人 / teacher / admin（否则 `403/40300`）
- 类型：同步（部分更新）
- 入参：`stem_md` / `options` / `answer_md` / `analysis_md` / `qtype` / `difficulty` / `kp_ids` / `origin` / `tags` / `verified` 任选，只改传入字段
- `null` 语义：`qtype` / `difficulty` / `origin` / `verified` 显式传 `null` → **422/42200**（这些列非空，不能写 NULL）；`answer_md` / `analysis_md` / `tags` / `options` 传 `null` 表示清空
- 行为：题干**原始串**变化 → 重算 `stem_hash` + `embedding` + 自动重新对齐知识点（`kp_names=[]`），先做哈希判重（撞其他题 → `409/40900`）；只改空格/标点也会真落库（不会被误判为“未变化”而静默丢弃）
- 撞题 409 覆盖两条路径：先查先写之间的并发 `INSERT` 冲突，以及 `UPDATE` 撞 `UNIQUE(subject_id, stem_hash)`（统一由唯一约束兜底，不返回 500）
- 题型/选项交叉校验按**更新后的有效状态**做：只改 `qtype` 时结合库中现有选项校验，只改 `options` 时结合库中现有 `qtype`；`单选`/`多选` 至少 2 个选项且 key 不重复，`填空`/`解答` 不得带选项，违反 → `422/42200`
- `kp_ids`：传数组则整体替换为人工关联（`weight=1.0`），传空数组清空
- 前端行为：审题页保存只在**知识点集合真的变化**时才下发 `kp_ids`；只改难度/答案不会重建 `question_kps`，也不会把对齐 `weight` 重置为 1.0（S5-1 组卷要用真实权重）
- 出参：`Envelope[QuestionDetail]`
- 错误：`403/40300`；`404/40400`；`409/40900` 撞题（含并发 UPDATE 撞唯一约束）；`422/42200` 非空字段传 null / 题型与选项不自洽 / 知识点非法

### POST /api/v1/questions/{question_id}/split
- 权限：同 PATCH
- 类型：同步
- 入参：`{"split_at": "2."}`（1–50 字）；在题干中**首次出现**该标记处切开，标记保留在第二题开头
- 行为：两半各自重算 hash/embedding 并自动对齐知识点；判重时用 `exclude_ids` 排除原题（原题仍在库，拆出的子串与原题余弦 ≥0.92，不排除会把自己判成重复）；成功后原题硬删（连带 `question_kps`）
- 出参：`Envelope[list[QuestionDetail]]`（长度 2，顺序与原题干一致）
- 错误：`422/42200` `split_at` 为空 / 题干中找不到该标记（或标记位于开头）/ 任一半去空白后 < 5 字；`409/40900` 拆出的题已存在于题库 / 原题被错题本引用；`403/40300`；`404/40400`

### POST /api/v1/questions/merge
- 权限：同 PATCH，且对**全部** id 都有权（任一题无权 → `403/40300`）
- 类型：同步
- 入参：`{"ids": [a, b]}`（2–10 个；去重后仍须 ≥2）
- 行为：按 id 升序拼接题干（空行分隔），答案与解析按同序拼接（跳过空值）；`subject_id` / `qtype` / `origin` / `created_by` / `source_file_id` 取 id 最小的题，`difficulty` 取其中最大值，`verified` 为全部为真才为真，`options_json` / `tags` 置空；新题重算 hash/embedding 并自动对齐；判重 `exclude_ids` 排除全部源题；成功后源题硬删
- 出参：`Envelope[QuestionDetail]`
- 错误：`422/42200` 少于 2 个 / 不属于同一学科（spec 原写 `400/40000`，实现按 `InvalidParamError` 统一 422）；`409/40900` 合并后的题目已存在于题库 / 源题被错题本引用；`403/40300`；`404/40400`

### DELETE /api/v1/questions/{question_id}
- 权限：同 PATCH
- 类型：同步（硬删）
- 出参：**204** 无响应体
- 行为：同一事务删除 `question_kps` 关联；`mistakes` 表存在时先查引用（S4-2 建表后自动生效，S4-1 阶段用 `has_table` 守卫跳过）
- 错误：`403/40300`；`404/40400`；`409/40900`「题目已被错题本引用，不能删除、合并或拆分」

## 6. 错题本（S4-2 定稿，S4-3 增诊断）

> 错题是**学生私有数据**：所有接口只作用于当前登录用户，他人记录与不存在统一 `404/40400`，不泄露存在性。
> 枚举：`status` = `待订正` / `已订正` / `已掌握`；`cause_type` / `secondary_causes` = `概念不清` / `计算失误` / `审题偏差` / `方法不当` / `知识遗忘` / `时间不足` / `unknown`（TEXT + CHECK，常量见 `MistakeStatus` / `CauseType`，SCHEMA §10）。
> 同一 `(user_id, question_id)` 只保留一条错题：重复录入**不返回 409**，而是复用既有行并重置 `status=待订正`、`correct_streak=0`（`last_review_at` 不动），响应仍是 **201**、`created=false`。
> `mistake_analyses` 由 S4-3 写入：录入后异步诊断（`mistake.analyze`），也可用 `POST /{id}/analyze` 手动重跑；一道错题至多一条诊断（重跑覆盖同一行）。
> 路由声明顺序：`/photo`、`/stats` 必须先于 `/{mistake_id}`（否则会被路径参数吞掉，与 §5.5 `/questions/import` 同款坑）。
> S4-4 起 `mistake_analyses.similar_questions_json` 存变式题（版本化 JSON，见 `SCHEMA.md` §5.4）：
> 手动触发一次生成 3 道，经「独立复算 + 确定性答案比对」自检后只保留通过的题；用户在详情页**逐题**确认后才入库。
> 详情接口的 `analysis.similar_questions` / `analysis.variants_stats` 在未生成时为 `null`，生成过但一道未通过时为 `[]` + 计数。

### POST /api/v1/mistakes/photo
- 权限：登录用户
- 类型：异步任务（`mistake.recognize`；202 + 用 §3.5 的 `GET /api/v1/tasks/{task_id}` 轮询，不新增任务查询接口）
- 请求：`multipart/form-data` + query：

  | 位置 | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|---|
  | query | subject_id | int | 是 | 学科 id；不存在 → `404/40400` |
  | multipart | file | file | 是 | 题目照片，仅 PNG / JPEG |
  | multipart | my_answer_md | string | 否 | 学生手填作答；**优先于**视觉识别结果 |

- 行为：校验学科 → 按扩展名预判 PNG/JPEG → `file_service.upload_file(parse=false)` 落 `files`（`parse_status=done`、`parse_progress=100`，不建笔记/不切片）→ 入队 `mistake.recognize`；任务从图片识别题干并建题（进入公共题库，`origin=upload`、`source_file_id=图片 file_id`），再建/复用错题并挂原图。
- 复用同题时的字段覆盖：同 `(user, question)` 已存在则复用并重置（与 `POST /api/v1/mistakes` 同一语义）；`my_answer_md` 只有本次识别到作答才覆盖（`used_answer_source=vision/student`），识别为 `none` 时保留原值；`correct_answer_md` 同理，只有视觉从图中读出答案才覆盖（**不会**回填题目 `answer_md`）；`image_file_id` 总是替换成本次上传的图片。
- 成功：**202** `Envelope[TaskOut]`：`id` / `name`（`mistake.recognize`）/ `status`（`pending`）/ `created_at`
- 任务结果 `result`（`status=succeeded` 后）：

```json
{"mistake_id": 12, "question_id": 65, "created": true, "reused_question": false,
 "confidence": 0.86, "low_confidence": false, "used_answer_source": "student",
 "warnings": [], "elapsed_ms": 9123}
```

  | 字段 | 说明 |
  |---|---|
  | mistake_id / question_id | 新建或复用的错题 / 题目 id |
  | created | 错题是新建（`true`）还是复用重置（`false`） |
  | reused_question | 识别出的题干命中题库判重、复用了既有题 |
  | confidence | 视觉模型自评 0–1，未校准，只作提示 |
  | low_confidence | `confidence < 0.5` 为 `true`（**等于 0.5 不算低**）；题目仍入库 |
  | used_answer_source | 作答来源 `student` / `vision` / `none`：学生手填 > 视觉识别 > 无，**不猜**（不编造会污染 S4-3 诊断） |
  | warnings | 识别告警（如手写体不清、作答缺失） |
  | elapsed_ms | 任务耗时 |

- 错误：`422/42200` 缺 `file` / 非 PNG/JPEG（**缺文件也是 422**，与 §5.5 `/questions/import` 的 `400/40000` 不一致，属现状）；`404/40400` 学科不存在；`401/40100`；`500/50000`「任务队列不可用」（沿用 S2-7）
- 备注：拍照上传只接受 PNG/JPEG；WebP 未在 `file_service` 上传层开放（`TYPE_TABLE` / `upload_allowed_extensions` 均无），补 WebP 属跨模块改动，本卡不做（d-11）。`ai/vision` 的 `ALLOWED_MIMES` 仍保留 webp 作防御，但本链路不可达。

### GET /api/v1/mistakes/stats
- 权限：登录用户（仅本人）
- 类型：同步
- 入参：

  | 参数 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | created_from | datetime | 否 | `created_at` 下界（含） |
  | created_to | datetime | 否 | `created_at` 上界（含） |

- 口径：`total` = `by_status` 三个状态计数之和（不是诊断数，也不按错因/知识点去重）；三条聚合都带 `user_id` 与日期边界。
  - `by_status`：固定按 `待订正` / `已订正` / `已掌握` 顺序返回，缺的状态补 0；
  - `by_cause`：只统计已有诊断的错题（`mistake_analyses` 内连接），按 `count DESC, cause_type` 稳定排序；S4-3 前为 `[]`；
  - `top_kps`：取前 10，按 `count DESC, kp_id`；一条错题挂多个知识点时在每个知识点各计 1 次。
- 出参：`Envelope[MistakeStatsOut]`
- 示例：

```json
{"code": 0, "message": "ok", "trace_id": "9b2e…",
 "data": {"total": 12,
          "by_status": [{"status": "待订正", "count": 7},
                        {"status": "已订正", "count": 3},
                        {"status": "已掌握", "count": 2}],
          "by_cause": [{"cause_type": "概念不清", "count": 4},
                       {"cause_type": "计算失误", "count": 2}],
          "top_kps": [{"kp_id": 3, "kp_name": "函数的单调性", "count": 5}]}}
```

- 错误：`422/42200` 时间格式非法；`401/40100`

### GET /api/v1/mistakes
- 权限：登录用户（仅本人）
- 类型：同步（分页）
- 入参：

  | 参数 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | page / page_size | int | 否 | 同 §0（默认 1 / 20，1–100） |
  | status | string | 否 | `待订正` / `已订正` / `已掌握`；非法值 `422/42200` |
  | cause_type | string | 否 | 错因值（§10）；S4-3 前无数据；当前不做值集校验，按字符串过滤 |
  | kp_id | int | 否 | 题目挂载的 KP **或** 诊断 `kp_ids` 命中即返回（两段 `EXISTS`，一题多 KP 不产生重复行） |
  | created_from | datetime | 否 | `created_at` 下界（含） |
  | created_to | datetime | 否 | `created_at` 上界（含） |
  | sort_by | string | 否 | 白名单 `created_at` / `last_review_at` / `status` / `correct_streak`，默认 `created_at` |
  | order | string | 否 | `asc` / `desc`，默认 `desc` |

- 时区口径：`created_from` / `created_to` 接受带时区偏移的 ISO-8601；只给日期时按 UTC 解释，前端按用户本地时区换算成当天 00:00:00 ~ 23:59:59.999 后发送（UTC+8 的「11-03」= `2026-11-02T16:00:00.000Z` ~ `2026-11-03T15:59:59.999Z`）。
- 出参：`Envelope[PageData[MistakeSummary]]`
- 排序：主排序后**追加 `id DESC` 兜底**（同一秒录入的多条错题不重复/漏行）；`last_review_at` 为 NULL 的行按 PostgreSQL 默认排序，NULL 排序口径待定（见 PROGRESS 遗留）。
- `MistakeSummary`：`id` / `question_id` / `status` / `correct_streak` / `stem_excerpt`（题干前 120 字）/ `subject_id` / `qtype` / `difficulty` / `kp_names`（一页一次 `IN` 批查，按 `question_kps.weight` 降序、同权重按 `kp_id`）/ `cause_type`（S4-3 前恒 `null`）/ `has_image` / `created_at` / `last_review_at`
- 示例：

```json
{"code": 0, "message": "ok", "trace_id": "4f1c…",
 "data": {"items": [{"id": 12, "question_id": 65, "status": "待订正",
                     "correct_streak": 0, "stem_excerpt": "已知函数 $f(x)=x^2-4x+3$…",
                     "subject_id": 7, "qtype": "解答", "difficulty": 2,
                     "kp_names": ["一元二次函数"], "cause_type": null,
                     "has_image": true, "created_at": "2026-11-03T04:12:09.118Z",
                     "last_review_at": null}],
          "total": 12, "page": 1, "page_size": 20}}
```

- 错误：`422/42200` 非法 `status` / 排序字段非白名单 / 分页越界；`401/40100`

### POST /api/v1/mistakes
- 权限：登录用户
- 类型：同步，**201**
- 入参（JSON）：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | question_id | int | 是 | 题库题目 id（正数） |
  | my_answer_md | string | 否 | 学生作答 |
  | correct_answer_md | string | 否 | 正确答案；缺省时取题目的 `answer_md` |

- 行为：题目不存在 → `404/40400`；同 `(user, question)` 已存在 → 复用并重置（`status=待订正`、`correct_streak=0`，`last_review_at` 不动），返回 **201 + `created=false`**；并发重复录入撞唯一约束时由服务端重查赢家后按同一语义复用，不把 `IntegrityError` 暴露成 500。
- 复用分支的作答覆盖规则（与代码一致，按此为准）：
  - `my_answer_md`：只在本次**显式传入**时覆盖，不传保留原值；
  - `correct_answer_md`：先按「本次传入 > 题目 `answer_md`」定值，**非空就覆盖** —— 即本次不传且题目有标准答案时，会用题目答案覆盖已存的正确答案（用户在详情页手工改过的值会被还原）；
  - 两者都取不到值（本次不传且题目无 `answer_md`）时保留原值。
- 出参：`Envelope[MistakeCreateOut]`（= `MistakeDetail` + `created: bool`）
- 错误：`404/40400` 题目不存在；`409/40900`「错题录入冲突，请重试」（并发冲突且重查不到赢家，极少数）；`422/42200` `question_id` 非法；`401/40100`

### GET /api/v1/mistakes/{mistake_id}
- 权限：登录用户（仅本人；他人与不存在统一 404）
- 类型：同步
- 出参：`Envelope[MistakeDetail]`
- `MistakeDetail` = `MistakeSummary` + `stem_md` / `options`（`[{key,text}]`，非选择题为 `null`）/ `my_answer_md` / `correct_answer_md` / `image_url`（`/api/v1/files/{file_id}/image`，需 Bearer；前端经 `http.ts` 取 blob 再转 objectURL）/ `analysis`
- `analysis`：`{cause_type, secondary_causes, error_step, explanation_md, review_advice_md, kp_ids, confidence, model, prompt_version, created_at}`；未诊断（或诊断失败且从未成功过）时恒为 `null`
  - `cause_type="unknown"`：学生没有作答（或识别不出），只讲题不推断错因，此时 `secondary_causes=[]`、`error_step=null`
  - `confidence`：LLM 自评 0.00–1.00（库里 `NUMERIC(3,2)`，出参转 `number`），前端在 `< 0.5` 时提示「把握较低」
  - `created_at`：**最近一次**诊断落库时间（重跑覆盖会刷新）
- 错误：`404/40400`「错题不存在」；`401/40100`

### PATCH /api/v1/mistakes/{mistake_id}
- 权限：登录用户（仅本人）
- 类型：同步（部分更新）
- 入参：`{my_answer_md?, correct_answer_md?, status?}`，只改传入字段
- `null` 语义：`my_answer_md` / `correct_answer_md` 显式传 `null` 表示清空；`status` 是 NOT NULL 列，显式传 `null` → **422/42200**；`status` 非三值 → `422/42200`
- 行为：**只改状态标签，不驱动 `correct_streak`、也不刷新 `last_review_at`**；连续答对次数只能由 `POST /review` 产生（D-7）
- 出参：`Envelope[MistakeDetail]`
- 错误：`404/40400`；`422/42200`；`401/40100`

### POST /api/v1/mistakes/{mistake_id}/review
- 权限：登录用户（仅本人）
- 类型：同步
- 入参：`{"correct": true}`（必填 bool，表示本次复习是否答对）
- 状态机（`MASTERY_STREAK = 2`）：
  - `correct=true` → `correct_streak += 1`；`>= 2` → `已掌握`，否则 `已订正`；
  - `correct=false` → `correct_streak = 0`、`status = 待订正`（已掌握后答错也回退）；
  - 三种情况都刷新 `last_review_at`；已掌握后继续答对，`correct_streak` 继续递增（不封顶）。
- 出参：`Envelope[MistakeDetail]`（返回更新后的整行，前端直接刷新徽标）
- 错误：`404/40400`；`422/42200` 缺 `correct`；`401/40100`

### POST /api/v1/mistakes/{mistake_id}/analyze
- 权限：登录用户（仅本人；他人与不存在统一 `404/40400`）
- 类型：异步（**202**，用 §3.5 的 `GET /api/v1/tasks/{task_id}` 轮询，不新增任务查询接口）
- 入参：query `force`（bool，默认 `true`；`force=false` 表示已有诊断就别再花一次 LLM 调用）
- 行为：先校验错题归属，再建 `mistake.analyze` 任务；`force=false` 且已有诊断时任务立即 `succeeded` 且 `result.skipped=true`（前端据此提示「已有诊断」，不需要为它单独写分支）
- 任务结果 `result`（`succeeded` 后）：

```json
{"mistake_id": 12, "cause_type": "概念不清", "secondary_causes": ["计算失误"],
 "confidence": 0.82, "retrieval_hits": 2}
```

  跳过时：`{"mistake_id": 12, "skipped": true}`
- 出参：**202** `Envelope[TaskOut]`
- 错误：`404/40400`「错题不存在」；`422/42200` `force` 非布尔；`500/50000`「任务队列不可用」（任务已落库为 `failed`）；`401/40100`
- 备注：录入错题时（`POST /mistakes` 与拍照识别成功后）会自动 best-effort 入队同一任务，已有诊断则跳过；入队失败只记日志，不影响录入本身

### POST /api/v1/mistakes/{mistake_id}/variants
- 权限：登录用户（仅本人；他人与不存在统一 `404/40400`）
- 类型：异步（**202**，用 §3.5 的 `GET /api/v1/tasks/{task_id}` 轮询，不新增任务查询接口）
- 行为：手动触发生成 3 道变式题（不自动触发，避免一次录入烧掉多次生成调用）。前置条件两道，均为 **409/40900**：
  1. 该错题已有诊断（`mistake_analyses` 一行）→ 否则「请先完成错因诊断」；
  2. 原题题干 ≥10 字 → 否则「这道题题干太短，暂不支持生成变式」。
- 任务结果 `result`（`succeeded` 后）：

```json
{"mistake_id": 12, "requested": 3, "passed": 2, "rejected": 1, "rounds": 2, "elapsed_ms": 41235}
```

- 出参：**202** `Envelope[TaskOut]`
- 错误：`404/40400`「错题不存在」；`409/40900` 上面前置条件；`500/50000`「任务队列不可用」（任务已落库为 `failed`）；`401/40100`
- 备注：结果写进 `mistake_analyses.similar_questions_json`（覆盖上一次，前端**重新生成**语义即覆盖）；
  **生成彻底失败（重试耗尽）时任务 `failed` 且旧 JSON 保持不变**，已通过的部分则保留并照常成功。

### POST /api/v1/mistakes/{mistake_id}/variants/{variant_id}/accept
- 权限：登录用户（仅本人）
- 类型：同步（把一道变式题写进题库 `questions`）
- 入参：路径 `variant_id`（JSON 里的 8 位十六进制 id，不是数据库 id）
- 行为：已在本次 JSON 里确认过的变式题 → 幂等返回既有 `question_id` + `created=false`；
  题库里已有同 `stem_hash` 的题 → 同样复用 + `created=false`；否则新建
  （`origin=ai`、`verified=false`、`tags=["AI变式"]`、知识点链接继承原题、`created_by`=本人）。
- 出参：**200** `Envelope[{"question_id": 128, "created": true}]`
- 错误：`404/40400`「变式题不存在或已被重新生成」；`401/40100`
- 备注：服务内两次提交（建题一次、回写 JSON 的 `accepted_question_id` 一次）非原子，
  但重试收敛到同一 `question_id`（spec §6.4 已说明）。

### DELETE /api/v1/mistakes/{mistake_id}
- 权限：登录用户（仅本人）
- 类型：同步（硬删）
- 出参：**204** 无响应体
- 行为：同一事务先删诊断行（`mistake_analyses`）再删主行，不留孤儿；不可恢复
- 错误：`404/40400`；`401/40100`

## 7. 题目生成

### POST /api/v1/questions/generate
- 权限：student
- 类型：异步任务 ⚠（通用「凭空出题」仍为 TODO）
- 说明：S4-4 只交付了**错题变式**这一条路径 —— `POST /api/v1/mistakes/{id}/variants`（见 §6）。
  它已实现方案 6.5 要求的两道关：格式校验（题型↔选项交叉校验）+ 独立复算（答案由第二遍无答案解题得出，
  再用确定性比对判定），不一致丢弃并重生成（最多 2 轮 / 12 次调用）。与本文旧设想不同的是：
  通过的题**不自动入库**，由用户逐题确认（`.../variants/{variant_id}/accept`），入库时 `verified=false`、`origin=ai`。
- 本接口（不带错题的通用生成）未实现，留待后续任务卡。

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
- 权限：admin（403/40300）
- 类型：同步
- 入参：`range` = `1d` | `7d` | `30d`，默认 `7d`；非法值 422/42200
- 出参：`Envelope[UsageReport]`；`data` = `{range, start_date, end_date, totals, items}`
  - `totals`：`{calls, failed_calls, prompt_tokens, completion_tokens, total_tokens, cost_yuan, avg_latency_ms}`
  - `items`：按 `date ASC, scene ASC, model ASC`，每行 `{date, scene, model, calls, failed_calls, prompt_tokens, completion_tokens, total_tokens, cost_yuan, avg_latency_ms}`
- 口径：UTC 日历日；`1d` 只含今天；`cost_yuan` 为按配置单价估算的元，保留 8 位；失败调用的 token/cost 按 0 聚合
- 示例：见 `docs/spec/s3-7-cache-llm-logs-usage.md` §3.2

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

### GET /api/v1/admin/prompts（S3-4 定稿）
- 权限：`admin`（其他角色 403/40300；匿名 401/40100）
- 类型：同步
- 入参：查询 `name` 可选，匹配 `^[a-z][a-z0-9_]{0,63}$`（非法 422/42200）
- 出参：`Envelope[list[PromptTemplateOut]]`，按 `created_at DESC, id DESC`；含 `content`
- `PromptTemplateOut`：`id/name/version/content/variables_json/model_hint/is_active/created_by/created_at/updated_at`
- 说明：版本历史只读；`is_active` 由部分唯一索引保证每个 name 最多一条

### POST /api/v1/admin/prompts（S3-4 定稿）
- 权限：`admin`
- 类型：同步，**201**
- 入参：`{name, content, version?, variables_json?, model_hint?, activate?}`
  - `name` 必填 + 正则；`content` 1–20000 字（strip 后非空）；`version` 可选 + `^[A-Za-z0-9._-]{1,32}$`
  - `version` 省略时自动取同 name 最大 `vN` + 1；`activate` 默认 false
- 出参：`Envelope[PromptTemplateOut]`；`created_by`=当前 admin
- 行为：版本行不可变；`activate=true` 同事务停用旧版并启用新版
- 错误：`409/40900`「Prompt 版本已存在」；`422/42200` 校验失败；`403/401`

### PUT /api/v1/admin/prompts/{id}/activate（S3-4 定稿）
- 权限：`admin`
- 类型：同步
- 入参：路径 `id` 正整数
- 行为：同 name 全部停用后启用目标，刷新 `updated_at`；先 flush 停用再启用，避免部分唯一索引冲突
- 出参：`Envelope[PromptTemplateOut]`（目标 `is_active=true`）
- 错误：`404/40400`「Prompt 版本不存在」；`422/42200` id 非法；`403/401`

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
| 错题 | AI 错因诊断接口（`POST /mistakes/{id}/analyze`）、统计看板 | S4-3 / S4-8（S4-2 已交付列表、统计、拍照录入与 CRUD） |
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
