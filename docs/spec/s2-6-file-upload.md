# S2-6 文件上传 + MinIO + 去重 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-6
- 日期：2026-10-26
- 状态：已实现并验收（2026-10-26；pytest 368/368 + 真实 MinIO/Postgres 全流程；实施记录见 docs/plan/s2-6-file-upload.md）
- 上游：S0-4（MinIO + 自动建桶 `study-agent`）、S2-1（`files` 表骨架）、S2-5（`uq_files_user_sha256` 定稿）、S2-2/S2-3（认证与权限）、S2-4（分页，未用到）
- 下游：S2-7 任务框架、S2-8 解析 Worker（读 MinIO 对象、改 `parse_status`）、S2-12 笔记插图
- 产物：`app/core/storage.py`、`app/schemas/files.py`、`app/services/file_service.py`、`app/api/v1/files.py`、`tests/test_storage.py`、`tests/test_file_service.py`、`tests/test_files_api.py`

## 1. 目标

1. `POST /api/v1/files`：接收 multipart 文件，**流式**落临时文件（不把 60MB 读进内存），边读边算 `sha256` 与字节数，按扩展名白名单 + 文件头 magic 校验类型，超限立即中止。
2. 同用户同 `sha256` **复用已有记录**：第二次上传返回同一 `file_id` 与 `deduped=true`，不再写对象存储（验收硬指标）。
3. 对象入 MinIO，`files.storage_path` 存内容寻址的对象键；原始文件名只做展示，不参与路径。
4. `GET /api/v1/files/{id}/parse-status`：返回 `pending`（S2-8 再扩展 `parsing/failed`），权限同笔记详情（本人或已绑定家长/老师）。
5. 存储层抽成 `ObjectStorage` 协议 + MinIO 适配器，测试全部用假实现，套件不连网络。

非目标：异步解析（S2-7/8）、上传进度、断点续传、文件列表/下载/删除、`parse_result_json` 写入、图片转存/缩略图。

## 2. 范围

### 2.1 做

- `app/core/storage.py`：`ObjectStorage` 协议、`MinioStorage` 适配器、`get_storage()` 单例、`StorageUnavailableError`。
- `app/schemas/files.py`：`FileOut` / `FileUploadOut` / `FileStatusOut`。
- `app/services/file_service.py`：文件名清洗、类型校验、`upload_file`、`get_file_status`。
- `app/api/v1/files.py` + `router.py` 挂载。
- `core/config.py` 新增 `minio_secure` / `upload_max_size_mb` / `upload_allowed_extensions`；`.env.example` 同步。
- `requirements.txt` 新增 `minio`、`python-multipart`（版本按安装实测锁定）。
- `core/exceptions.py` 新增 `PayloadTooLargeError`（413/41300）。
- 测试 3 个文件（约 36 条）。
- 真实 curl + psql + MinIO 对象计数验收。

### 2.2 不做

- 不建表、不改迁移（`files` 表 S2-5 已建；`parse_status` 的 `parsing/failed` 与 `error_msg` 由 S2-8 迁移扩展）。
- 不做文件列表/下载/硬删；签名 URL 方法在存储层预留，接口留 S2-12。
- 不解析、不入 `note_chunks`、不写 `parse_result_json`。
- 不引入病毒扫描、图片压缩、PDF 预检。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 新增依赖 `minio`（官方 SDK）+ `python-multipart` | 前者提供流式 `put_object` 与 `presigned_get_url`；后者是 FastAPI 解析 multipart 的硬依赖（用户已批准） |
| 2 | 去重响应：首次 **201**，重复 **200** 且 `deduped=true` | 状态码不撒谎，前端能区分“新建/复用”，验收脚本可断言 |
| 3 | 类型：`pdf/docx/md/txt/png/jpg/jpeg`，默认上限 **60MB**，均为配置项 | 覆盖 S2-8 试卷与 S2-12 插图；扩展名白名单 + magic 双重校验，防伪造 |
| 4 | 对象键 `uploads/{user_id}/{sha256[:2]}/{sha256}{ext}` | 内容寻址天然幂等、无重名、无路径穿越；分两层目录避免单目录对象过多 |
| 5 | 不信任客户端 `Content-Type`/`filename`：MIME 由扩展名映射，文件名只做展示清理 | 防 SSRF/MIME 混淆与路径注入 |
| 6 | 超限返回 **413/41300** | 语义比 422 准确；新增错误码登记进 API.md §13 |
| 7 | 先写对象后写库；唯一键冲突视为并发去重，**不删对象**（键相同，删了会毁掉赢家） | 内容寻址下两个请求写的是同一个对象 |
| 8 | 库写失败（非唯一冲突）时补偿删除刚传对象 | 避免孤儿对象；失败尽力而为，异常照抛 |
| 9 | `parse-status` 权限同笔记详情：本人或已绑定家长/老师，admin 不绕过 | 与 S2-3/S2-5 一致，避免“家长能看笔记不能看来源” |
| 10 | 上传仅 `student` 角色 | 内容归属于学生个人知识库 |
| 11 | 存储层用协议 + 适配器 + `get_storage()` 单例，路由用 `Depends(get_storage)` | 测试覆盖依赖即可全假实现，和 ai/ 适配器同一套路 |

## 4. 数据

无迁移。使用 S2-5 的 `files` 表：

| 字段 | 本卡写入 |
|---|---|
| `filename` | 清洗后的原文件名（展示用，≤200 字符） |
| `mime` | 扩展名映射值（如 `application/pdf`） |
| `size` | 实际字节数 |
| `storage_path` | `uploads/{user_id}/{sha256[:2]}/{sha256}{ext}` |
| `sha256` | 流式计算的小写十六进制 |
| `parse_status` | 固定 `pending`（CHECK 目前只允许 pending/done） |
| `parse_result_json` | 不写 |

## 5. 接口契约

### POST /api/v1/files

- 权限：`student`（其他角色 403/40300）
- 请求：`multipart/form-data`，字段名 `file`
- 成功：`Envelope[FileUploadOut]`
  - 首次：**201**，`deduped=false`
  - 重复：**200**，`deduped=true`，返回已有 `id` 与元数据
- `data` 字段：`id` / `filename` / `mime` / `size` / `sha256` / `parse_status` / `created_at` / `deduped`
- 错误：
  - `413/41300`：超过 `upload_max_size_mb`（message 含上限，如「文件超过 60MB 上限」）
  - `422/42200`：扩展名不在白名单（message 列允许类型）/ 文件头与类型不符 / 文件名为空
  - `400/40000`：请求未带 `file` 字段
  - `403/40300`：非 student
  - `500/50000`：MinIO 不可用（「文件存储不可用」）

### GET /api/v1/files/{file_id}/parse-status

- 权限：本人或已绑定家长/老师（`ensure_student_access`，admin 不绕过）
- 出参：`Envelope[FileStatusOut]`，字段 `id` / `filename` / `parse_status`
- 错误：`404/40400`（文件不存在）；`403/40300`（无权访问该资源）

## 6. 存储抽象（`app/core/storage.py`）

```python
class ObjectStorage(Protocol):
    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def download_to(self, key: str, target: BinaryIO) -> None: ...
    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...
```

- `MinioStorage`：懒连接；首次操作前 `bucket_exists`，不存在则 `make_bucket`（桶已在 compose 里建好，这里只是自愈）；`put` 校验 `size` 与 SDK 返回一致；所有 SDK 异常包成 `StorageUnavailableError`（500/50000，message 固定「文件存储不可用」，不泄露 endpoint/凭据）。
- `get_storage()`：`lru_cache` 单例，供 `Depends` 覆盖。
- 配置：`minio_endpoint` / `minio_root_user` / `minio_root_password` / `minio_bucket`（已有）+ `minio_secure: bool = False`。
- `presigned_get_url` 本卡不暴露接口，S2-12 笔记插图用。

## 7. 服务契约（`app/services/file_service.py`）

```python
ALLOWED_TYPES: dict[str, tuple[str, bytes | None]]  # ext -> (mime, magic)
def sanitize_filename(name: str | None) -> str
def allowed_extensions() -> list[str]              # 读配置，供报错 message
def detect_type(filename: str) -> tuple[str, str]  # (ext, mime)；不在白名单抛 422
def check_magic(head: bytes, ext: str) -> None     # 不符抛 422
def upload_file(session, *, owner: User, upload: UploadFile) -> tuple[File, bool]
def get_file_status(session, *, file_id: int, viewer: User) -> File
```

`upload_file` 流程：

1. `sanitize_filename` → 空则 422；`detect_type` 取 ext/mime。
2. 分块（1MB）读入 `SpooledTemporaryFile`，同步累计 `size`/`sha256`；超过上限立即 413（不再读完）。
3. 首块做 magic 校验（文本类额外拒绝前 4KB 含 `\x00`）。
4. 按 `(user_id, sha256)` 查已有记录：
   - 命中且对象存在 → 直接返回 `(existing, True)`（不再上传）。
   - 命中但对象缺失 → 重新 `put` 同一 key，返回 `(existing, False)`（自愈）。
5. 未命中 → `put` 到内容寻址 key → 插库 → commit → `refresh` → `(file, False)`。
6. `IntegrityError`（并发同文件）→ rollback → 重查 → 返回 `(existing, True)`；仍查不到则 `ConflictError`。
7. 其他异常 → 尽力 `delete(key)` 后原样抛出。

`sanitize_filename`：`\` 归一到 `/`，取 basename，去控制字符与首尾空白/点，压到 200 字符且保留扩展名；`""`/`.`/`..` 视为非法。

`get_file_status`：不存在 404「文件不存在」；`viewer.id != file.user_id` 时走 `ensure_student_access`，越权 403/40300。

## 8. 配置项（`.env.example` 同步）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MINIO_SECURE` | `false` | 开发走 http；生产 TLS 设 true |
| `UPLOAD_MAX_SIZE_MB` | `60` | 单文件上限 |
| `UPLOAD_ALLOWED_EXTENSIONS` | `pdf,docx,md,txt,png,jpg,jpeg` | 逗号分隔，小写、不带点 |

## 9. 测试计划（约 36 条，全部不连网络）

`tests/test_storage.py`（约 10）
1. put 传对 bucket/key/length/content_type
2. 首次操作自动建桶，第二次不重复建
3. bucket_exists 返回 True 时不建桶
4. put 抛 SDK 异常 → `StorageUnavailableError`（500/50000，message 不含 endpoint）
5. delete 调用正确 key
6. exists 真/假
7. download_to 写入目标流
8. presign 带过期秒数且返回 URL
9. `get_storage()` 同一实例
10. 配置 `minio_secure=true` 时构造客户端带 secure

`tests/test_file_service.py`（约 16）
1-5. `sanitize_filename`：路径穿越 `../../etc/passwd` → `passwd`；Windows 反斜杠；控制字符；超长截断保留扩展名；空/`.`/`..` 非法
6. `detect_type` 大小写不敏感（`A.PDF`）
7. 非白名单扩展名 → 422 且 message 列允许类型
8. 配置收窄白名单后 `md` 被拒（确认读配置）
9. magic 不符（假 PDF 文本）→ 422
10. PNG 正确 magic 通过
11. 文本类含 NUL → 422
12. 正常上传：行字段齐全、key 形如 `uploads/1/ab/<sha256>.pdf`、返回 deduped=False
13. 重复上传：返回同 id、deduped=True 且**不调用 put**
14. 行存在但对象缺失：重新 put，deduped=False
15. 超限（把 `upload_max_size_mb` 配成 0 → mock 大小校验）→ 413
16. MinIO 失败 → 500 且未插库；库写失败 → 补偿 delete
17. 并发 `IntegrityError` → 返回已有记录且不 delete
18-20. `get_file_status`：本人 200/对象；不存在 404；他人 403；已绑定家长放行

`tests/test_files_api.py`（约 10）
1. 上传 201 + `deduped=false` + 壳字段完整
2. 重复上传 200 + `deduped=true` + 同 id
3. 超限 413/41300
4. 非法扩展名 422/42200
5. 缺 `file` 字段 400/40000
6. 未带 token 401/40100
7. teacher 上传 403/40300
8. parse-status 本人 200
9. parse-status 不存在 404
10. parse-status 他人 403

## 10. 验收（真实 MinIO + Postgres）

1. `pytest -q` 全绿（预计 358）。
2. 起 uvicorn，注册 `file_a` / `file_b`，登录拿 token。
3. 造两个文件：小 PDF（`%PDF-1.4` 头 + 内容）与 61MB 稀疏文件。
4. `curl -F file=@a.pdf` → 201，`deduped=false`，记 `file_id`；psql 查行（`sha256`、`size`、`storage_path`、`parse_status=pending`）。
5. 同一文件再传 → **200**，`deduped=true`，`id` 相同；MinIO 该前缀对象数仍为 **1**（`docker exec` 用 `mc find` 或 `mc ls --recursive` 统计）。
6. `curl -F file=@61mb.bin` → **413/41300**；psql 计数不增、对象数不增。
7. `GET /files/{id}/parse-status`（A）→ 200 `pending`；B 访问 → 403/40300。
8. 清理：删除 files 行、MinIO 对象、测试用户；`pytest` 再跑一遍确认无污染。

## 11. 文档同步

- `API.md` §3 定稿两个接口 + §12 缺口更新 + §13 新增 41300。
- `SCHEMA.md` §4.1 标注 `storage_path` 键规则与 `parse_status` 取值现状。
- `AGENTS.md` §9.2 上传/存储约定 + §9.6 存储适配器锚点。
- `DECISIONS.md` D-026（本 spec 决策 1–11 + 验收证据）。
- `PROGRESS.md` 状态、清单、遗留、变更日志。
- `requirements.txt` / `.env.example`。
- spec/plan 执行记录。

## 12. 已知限制

- 上传要读完整个文件才能去重（sha256 需要全量），不能秒回；60MB 约 1–2 秒（本地）。
- 只有扩展名 + 头部 magic 校验，不防“合法 PDF 里藏恶意脚本”；docx 只验 ZIP 头，不解析内部结构。
- 无病毒扫描、无图片重编码、无上传限流（429 未接入）。
- `parse_status` 只有 `pending`，S2-8 迁移扩展状态机与 `error_msg`。
- 无文件列表/下载/删除接口；`presigned_get_url` 只有存储层方法。
- 并发两个不同用户传同一文件会各存一份（按用户隔离的代价，符合 `uq_files_user_sha256`）。
- 库写失败后的补偿删除是尽力而为，极端情况下仍可能留孤儿对象（需后续清理任务）。