# S2-3 权限：RBAC 与数据隔离 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-3
- 日期：2026-10-26
- 状态：已实施并验收（2026-10-26）；pytest 260/260，硬验收用例通过（证据见 plan 执行记录与 PROGRESS）
- 上游：S2-1 `users` / `user_relations`、S2-2 `get_current_user`（40100）
- 下游：S2-5 笔记 CRUD、S2-6 文件、S4 错题/报告、S3-7 管理端 `/admin/usage`——所有「学生数据」接口都必须复用本卡依赖
- 产物：`backend/app/core/permissions.py`

## 1. 目标

把「谁能看谁的数据」从每个接口各自发挥，收敛成两个可组合依赖 + 一个服务层守卫：

1. `require_role("admin")`：只放行指定角色（管理接口）；
2. `require_student_access(student_id)`：放行「本人」或「已绑定该学生的家长/老师」，否则 `403/40300`；
3. `ensure_student_access(session, viewer, student_id)`：给 service 用（资源的 `user_id` 来自数据库而非路径时）。

硬验收（任务卡原文）：测试验证「A 学生的笔记 B 访问返回 403」。

## 2. 范围

### 2.1 做

- `core/permissions.py`：`require_role` / `require_student_access` / `ensure_student_access` / `can_access_student` / `has_student_relation`
- 测试：纯函数真值表 + 用测试内临时 FastAPI 应用验证依赖行为（含任务卡硬验收）
- 文档：API.md §0 权限矩阵（RBAC 细则定稿）、AGENTS §9.2/§9.6、DECISIONS D-023、PROGRESS
- 无新依赖、无迁移、无新生产接口

### 2.2 不做

- 不新增任何生产接口。本卡没有可用的学生数据端点（`/auth/me` 只能看自己；`/admin/usage` 依赖的 `llm_call_logs` 表尚未建），因此 **curl 证据推迟到 S2-5** 笔记接口落地时补；本卡的验收证据是 pytest（任务卡本身也只要求测试）。
- 不做 `require_student_access` 的 admin 旁路（2026-10-26 用户拍板：admin 不绕过，见 §2.3）。
- 不做分页/排序/筛选（S2-4）、不做「家长-学生绑定」管理接口（SCHEMA 未定义绑定 API，暂由 SQL/后续卡处理）。
- 不做字段级脱敏、审计日志（后续卡）。
- 不改 `users` / `user_relations` 表结构。

### 2.3 关键决策（2026-10-26 用户确认）

| # | 决策 | 理由 |
|---|---|---|
| 1 | **验收载体 = 依赖 + pytest**：生产代码零新增接口，测试内临时应用验证 403 | 严守任务卡产出与契约；S2-5 笔记接口会原样复用同一依赖，届时补真实 curl |
| 2 | **admin 不绕过** `require_student_access` | 最小权限：admin 只能走 `require_role("admin")` 的专用管理接口，避免“普通接口 + 管理员身份 = 全量学生数据”的隐式超级权限 |
| 3 | 查看方角色限 `parent` / `teacher` | `user_relations.teacher_id` 语义是「查看方」（SCHEMA §2.2），学生即使出现在 `teacher_id`（脏数据）也不放行 |
| 4 | 越权统一 `403/40300`「无权访问该资源」 | 不区分“无权限”与“目标不存在”，避免用状态码探测学生是否存在；404 留给已授权后的资源缺失 |
| 5 | 只做依赖、不做装饰器 | FastAPI 依赖可组合、自动进 OpenAPI、可在 `dependency_overrides` 里替换；装饰器会隐藏参数与返回类型 |
| 6 | 权限判断只看数据库里的 `role` 与 `user_relations` | S2-2 已确定 token 内 role 不作为权限来源，`get_current_user` 每次回表 |

## 3. 权限模型（同步写入 API.md §0）

| 角色 | 数据范围 | 判定方式 |
|---|---|---|
| student | 仅本人 | `current_user.id == student_id` |
| parent | 本人 + 已绑定学生 | `exist(user_relations.teacher_id=本人 AND student_id=目标)` |
| teacher | 本人 + 已绑定学生 | 同上 |
| admin | 仅专用管理接口 | `require_role("admin")`；**不继承学生数据权限** |

规则：

- 「学生数据」= 任何 `user_id` 归属某个学生的资源（笔记、文件、错题、问答记录、复习计划、报告）。
- 访问他人数据失败统一 `403/40300`，不泄露目标是否存在。
- 服务层查询必须显式 `WHERE <model>.user_id == <已授权的 student_id>`；**禁止**只靠前端传参或只校验角色就返回数据。
- 角色来自数据库（`get_current_user`），token 内 `role` 不参与判定。

## 4. 函数契约

```python
def require_role(*roles: str) -> Callable[..., User]
def require_student_access(
    student_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> User
def has_student_relation(session: Session, *, viewer_id: int, student_id: int) -> bool
def can_access_student(session: Session, viewer: User, student_id: int) -> bool
def ensure_student_access(session: Session, viewer: User, student_id: int) -> None
```

- `require_role("admin", "teacher")`：工厂时校验角色名，拼错立即 `ValueError`（启动/导入期暴露，不留到运行期）；依赖内 `current_user.role not in roles` → `ForbiddenError("无权访问该资源")`。
- `require_student_access`：直接用 `Depends(require_student_access)`，`student_id` 由 FastAPI 从**路径参数** `{student_id}` 注入（依赖参数名与路径模板同名即按路径解析）；路由路径必须含 `{student_id}`，否则会退化成 query 参数——**只在 `/students/{student_id}/...` 形态使用**，并在 docstring 写明。
- `can_access_student`：`viewer.id == student_id` 直接 True（含 admin 看自己）；否则 `viewer.role ∈ {parent, teacher}` 且 `has_student_relation` 为真。
- `ensure_student_access`：失败抛 `ForbiddenError("无权访问该资源")`；给 service 层在“先查资源、拿 `resource.user_id`、再判权”的链路上用。
- 所有函数都要类型标注；依赖返回 `User`（查看方），方便路由继续用。

## 5. 使用约定（给 S2-5 起的接口）

```python
# 形态 1：路径里的学生（列表/报告）
@router.get("/students/{student_id}/notes")
def list_notes(student_id: int, viewer: User = Depends(require_student_access), ...):
    rows = session.scalars(select(Note).where(Note.user_id == student_id)).all()

# 形态 2：资源自带 owner（详情/更新/删除）
note = get_note_or_404(session, note_id)
ensure_student_access(session, current_user, note.user_id)
```

- 形态 1 的 SQL 必须显式 `where(Note.user_id == student_id)`；形态 2 用 `ensure_student_access` 后再按 `note.id` 查。
- 禁止 `where(Note.user_id == current_user.id)` 直接代替权限判断后又在别处接收 `student_id` 参数。

## 6. 测试

测试不连真实数据库（fake session + `get_db` 依赖覆盖）。

### 6.1 `tests/test_permissions.py`（纯函数 / 依赖单元）

1. 本人访问自己的数据 → True（student）
2. 已绑定家长访问学生 → True
3. 未绑定家长 → False
4. 已绑定老师 → True
5. 未绑定老师 → False
6. 同学访问他人 → False
7. admin 访问他人 → False（决策 2）
8. admin 访问自己 → True
9. `ensure_student_access` 越权 → `ForbiddenError`，`code=40300`
10. `ensure_student_access` 有权限 → 不抛
11. `require_role` 拼错角色名 → `ValueError`
12. `require_role("admin")` 依赖：admin 通过、student 抛 `ForbiddenError`
13. `has_student_relation`：命中 / 未命中

### 6.2 `tests/test_permissions_api.py`（测试内临时 FastAPI 应用）

夹具：新建 `FastAPI()`，挂两条路由（仅测试代码，不进生产）：

```python
@app.get("/students/{student_id}/notes")
def student_notes(student_id: int, viewer: User = Depends(require_student_access)):
    return {"owner_id": student_id, "viewer": viewer.username}

@app.get("/admin/only")
def admin_only(viewer: User = Depends(require_role("admin"))):
    return {"ok": True}
```

用例：

1. **A 带 token 访问 `/students/{A}/notes` → 200**（正例）
2. **B 带 token 访问 `/students/{A}/notes` → 403 + `40300` +「无权访问该资源」**（任务卡硬验收）
3. 已绑定家长访问学生 → 200
4. 未绑定家长 → 403
5. 已绑定老师 → 200
6. admin 访问学生笔记 → 403
7. admin 访问 `/admin/only` → 200
8. student 访问 `/admin/only` → 403
9. 不带 token 访问 `/students/{A}/notes` → 401（证明依赖链走 `get_current_user`）
10. 未绑定家长访问不存在的学生 id → 403（不泄露存在性）

## 7. 验收

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_permissions.py tests/test_permissions_api.py -q
../.venv/Scripts/python.exe -m pytest -q     # 全量回归，基线 237
```

- 验收标准：上述 23 条测试全绿，其中 `test_b_cannot_read_a_notes_returns_403` 必须存在且通过。
- 真实服务/curl：本卡无新接口，**不跑 curl**；S2-5 用真实笔记接口补「A 的 token 查 A → 200，B 的 token 查 A → 403」并贴输出。

## 8. 已知限制（写进 PROGRESS / D-023）

- 无绑定关系管理接口：家长/老师绑定学生目前只能靠 SQL 或后续卡；本卡只做「已绑定则放行」的判断。
- 无审计日志：越权尝试只打 403 响应，不落 `audit_logs`（表也未建）。
- 无缓存：每个受保护请求多一次 `user_relations` 查询（主键/索引 `ix_user_relations_student_id` 可支撑，量小可接受）；后续如有性能需求再加缓存。
- 无字段级脱敏：有权限的家长能看到该学生全部字段（当前 `users` 无敏感字段）。
- 本卡没有生产端点，因此 **curl 证据为空**，以 pytest 为验收证据，S2-5 补齐端到端。

## 9. 文档同步

| 文档 | 改动 |
|---|---|
| `API.md` | §0 增「角色与数据范围」矩阵 + 隔离规则；§0 认证行去掉「⚠ RBAC 细则 S2-3 定稿」 |
| `AGENTS.md` | §9.2 增学生数据接口约定；§9.6 增权限锚点 |
| `DECISIONS.md` | 新增 D-023（6 条决策 + 验证） |
| `PROGRESS.md` | S2-3 打勾、当前状态、变更日志；遗留项补「无绑定管理接口/审计」 |
| `SCHEMA.md` | 不改 |
| `requirements.txt` | 不改（无新依赖） |

## 10. 自检

- [x] 任务卡产出 `core/permissions.py` → §4
- [x] `require_role("admin")` → §4 / §6.1-12 / §6.2-7、8
- [x] `require_student_access(student_id)`（本人或已绑定家长）→ §4 / §6
- [x] 「所有涉及学生数据的查询必须带 user_id 过滤」→ §3 / §5（写入 API.md 与 AGENTS）
- [x] 硬验收「A 学生的笔记 B 访问 403」→ §6.2-2（用例名固定，便于论文引用）
- [x] 无新依赖 / 无迁移 / 无生产接口 → §2.1-2.2
- [x] 无 TBD 留给实施者