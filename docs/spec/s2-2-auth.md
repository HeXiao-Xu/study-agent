# S2-2 认证（注册 / 登录 / JWT / 当前用户）spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-2
- 日期：2026-10-26
- 状态：已实施并验收（2026-10-26）；pytest 237/237，curl 全链路通过（证据见 plan 执行记录与 PROGRESS）
- 上游：S0-5 配置/异常/统一壳、S2-1 `users` 表（含 `username/password_hash/nickname/grade/role`）
- 下游：S2-3 RBAC 与数据隔离（在 `get_current_user` 上加权限依赖）、S2-11 前端登录页
- 产物：`backend/app/core/security.py`、`backend/app/api/deps.py`、`backend/app/api/v1/auth.py`、`backend/app/services/auth_service.py`、`backend/app/schemas/auth.py`、`backend/app/api/router.py`

## 1. 目标

让系统具备「谁能用、以什么身份用」的最小闭环：

1. 公开注册（student/teacher/parent，禁止 admin）；
2. 用户名 + 口令登录，签发 JWT；
3. `get_current_user` 依赖把 Bearer token 换成数据库里的用户对象，供后续所有业务接口复用；
4. 口令只存 Argon2id 哈希；登录失败不泄露"用户是否存在"。

验收标准（任务卡）：pytest 覆盖**注册 / 登录 / 错误密码 / token 过期**四种情况；curl 拿到 token 后能访问受保护接口。

## 2. 范围

### 2.1 做

- `core/security.py`：口令哈希/校验、JWT 签发/解析、密钥配置校验（纯函数，易单测）
- `api/deps.py`：`get_db`（每请求一个 Session）、`get_current_user`（HTTPBearer）
- `services/auth_service.py`：注册、认证、签发响应；业务错误用 `AppError` 子类
- `schemas/auth.py`：`RegisterRequest / LoginRequest / UserOut / TokenOut`
- `api/v1/auth.py` + `api/router.py`：`/api/v1/auth/{register,login,me}`
- 配置：`AUTH_SECRET_KEY / AUTH_ALGORITHM / AUTH_ACCESS_TOKEN_EXPIRE_MINUTES`，启动时校验
- 依赖：`pwdlib[argon2]==0.3.1`、`PyJWT==2.15.1`（2026-10-26 用户批准）
- 错误码：新增 `40900`（资源冲突）与 `ConflictError`
- 测试：安全原语、服务（fake session）、接口（TestClient + 依赖覆盖）、配置校验
- 文档同步：API.md §0/§1/§12/§13、AGENTS §9.6、DECISIONS D-022、PROGRESS、.env.example、requirements.txt

### 2.2 不做

- 不做 refresh token / 登出 / token 黑名单（API.md 待定项，后续单独卡；本卡说明其影响）
- 不做登录限流/验证码/锁定（部署层或 S3-7 后再议）
- 不做邮箱/手机号验证、找回密码（SCHEMA 无 email 字段，方案未要求）
- 不做 RBAC 与家长-学生关系校验（S2-3）
- 不做前端登录页（S2-11）
- 不改 `users` 表结构与迁移（S2-1 已交付）；不改 `note_chunks`
- 不引入额外依赖（`python-multipart` 不装：登录走 JSON）

### 2.3 关键决策（2026-10-26 用户拍板）

| # | 决策 | 理由 |
|---|---|---|
| 1 | 哈希用 `pwdlib[argon2]==0.3.1`（Argon2id），令牌用 `PyJWT==2.15.1` | FastAPI 官方安全示例现行方案；passlib 停更且与 bcrypt≥4 不兼容，python-jose 停更 |
| 2 | 登录走 **JSON + HTTPBearer**，响应套统一壳 | 与 API.md §0 统一响应一致；前端 axios 直接发 JSON；Swagger 仍可粘贴 Bearer token 调试 |
| 3 | 注册角色可选 `student/teacher/parent`，**`admin` 不可自助注册** | 老师/家长没有 `user_relations` 绑定就看不到任何学生数据，权限由 S2-3 兜底；admin 用 Pydantic `Literal` 直接拒绝（422） |
| 4 | 单 access token，默认 **24h**，无 refresh | 任务卡只要求注册/登录/JWT；refresh/登出列在 API.md 待定项，避免本卡膨胀 |
| 5 | 登录失败统一 401「用户名或密码错误」，用户不存在时也跑一次假哈希校验 | 不泄露用户是否存在，并抹平"存在/不存在"的响应时间差 |
| 6 | 防重名 = DB `uq_users_username` + 捕获 `IntegrityError` → 409 | 并发注册也不会漏；先查后插仍有竞态 |

## 3. 接口契约（同步更新 docs/API.md）

### 3.1 POST /api/v1/auth/register

- 权限：公开；类型：同步；状态码 **201**
- 入参（JSON）：

  | 字段 | 类型 | 必填 | 约束 |
  |---|---|---|---|
  | username | string | 是 | 3–50 字符，不含空白；入库前 trim + 转小写 |
  | password | string | 是 | 8–128 字符 |
  | nickname | string | 是 | 1–50 字符（trim 后非空） |
  | grade | string | 否 | ≤20 字符 |
  | role | string | 否 | `student`(默认) / `teacher` / `parent`；`admin` → 422 |

- 出参：`Envelope[UserOut]`
- 错误：422（参数校验，`42200`）；409（用户名已存在，`40900`）

### 3.2 POST /api/v1/auth/login

- 权限：公开；类型：同步
- 入参（JSON）：`{username, password}`（username 同样 trim+小写）
- 出参：`Envelope[TokenOut]`：

  ```json
  {"code":0,"message":"ok","trace_id":"...","data":{
    "access_token":"<jwt>","token_type":"bearer","expires_in":86400,
    "user":{"id":1,"username":"student01","nickname":"测试用户_1","grade":"高一","role":"student","created_at":"..."}}}
  ```
- 错误：401（用户名或密码错误，`40100`）；422（缺字段）

### 3.3 GET /api/v1/auth/me

- 权限：需 `Authorization: Bearer <token>`；类型：同步
- 出参：`Envelope[UserOut]`
- 错误：401（未提供凭据 / 无效凭据 / 已过期，均 `40100`）

### 3.4 通用约定

- 认证头：`Authorization: Bearer <jwt>`；JWT 载荷 `{sub: "<user_id>", role, iat, exp}`，算法 HS256，默认 24h。
- `role` 以**数据库为准**：token 里的 role 只用于快速判断/日志，`get_current_user` 每次按 `sub` 回表取用户；角色被改动后旧 token 不会获得新权限（也意味着降权立即生效）。
- 用户名不区分大小写（注册与登录都归一化为小写）。

## 4. 认证原语（core/security.py）

```python
@dataclass(frozen=True)
class IssuedToken: token: str; expires_in: int
@dataclass(frozen=True)
class TokenClaims: user_id: int; role: str; exp: datetime

def hash_password(password: str) -> str
def verify_password(password: str, password_hash: str) -> bool
def create_access_token(*, user_id: int, role: str, expires_delta: timedelta | None = None) -> IssuedToken
def decode_access_token(token: str) -> TokenClaims
def ensure_auth_configured(settings: Settings | None = None) -> None
```

- `hash_password`：`pwdlib.PasswordHash.recommended()`（Argon2id）。
- `verify_password`：哈希串损坏/格式不对一律返回 `False`，不抛异常（防止 500）。
- `create_access_token`：`now = datetime.now(timezone.utc)`；`exp = now + (expires_delta or 配置分钟数)`；`sub` 必须是 **字符串**（RFC 7519 / PyJWT 要求）。
- `decode_access_token`：
  - `jwt.ExpiredSignatureError` → `AuthError("登录已过期，请重新登录")`
  - 其他 `jwt.InvalidTokenError`（签名错/结构错/缺 exp/sub）→ `AuthError("无效的认证凭据")`
  - `sub` 非整数、`role` 不在 `UserRole` 枚举内 → `AuthError("无效的认证凭据")`
- `ensure_auth_configured`：`AUTH_SECRET_KEY` 为空 → `RuntimeError`（启动即失败，不允许无密钥跑起来）。`env=prod` 且长度 <32 → Settings 校验直接拒绝。
- 密钥只从 `Settings.auth_secret_key` 读（`repr=False`），代码/日志不出现。

## 5. 服务层（services/auth_service.py）

```python
class UserAlreadyExistsError(AppError):   # code=40900, http 409, message="用户名已存在"
def register_user(session: Session, payload: RegisterRequest) -> User
def authenticate_user(session: Session, *, username: str, password: str) -> User
def issue_token_for(user: User) -> TokenOut
```

- `register_user`：归一化 username → 查无同名（可选快路径）→ `hash_password` → `session.add` → `commit`；`IntegrityError` → `rollback` + `UserAlreadyExistsError`；成功后 `refresh(user)` 拿到 `id/created_at`。
- `authenticate_user`：按归一化 username 查；**用户不存在时对固定 dummy 哈希跑一次 `verify_password`** 再抛 `AuthError("用户名或密码错误")`；密码错抛同一错误（同文案、同状态码）。
- `issue_token_for`：`create_access_token(user_id=user.id, role=user.role)` → `TokenOut(access_token, expires_in, user=UserOut.model_validate(user))`。
- 一个用例一个事务；失败先 `rollback` 再抛异常，不吞异常。

## 6. 依赖与装配

### 6.1 api/deps.py

```python
bearer = HTTPBearer(auto_error=False)
def get_db() -> Iterator[Session]      # new_session() + finally close
def get_current_user(credentials = Depends(bearer), session = Depends(get_db)) -> User
```

- `credentials is None` / scheme 非 bearer → `AuthError("未提供认证凭据")`
- `decode_access_token` → 按 `sub` 回表；用户不存在 → `AuthError("账号不存在或已被删除")`
- 返回 ORM `User`，后续 S2-3 直接在其上加 `require_role/require_student_access`

### 6.2 路由装配

- `api/router.py`：`api_router = APIRouter(prefix="/api/v1")`，`include_router(auth.router)`
- `main.py`：`app.include_router(api_router)`
- 路由函数只做「Pydantic 入参 → service → `Envelope(trace_id=get_trace_id(), data=...)`」，不写业务分支。

## 7. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_SECRET_KEY` | `""` | HS256 密钥；**必须在 .env 配置**，空值启动报错；`.env.example` 放占位 |
| `AUTH_ALGORITHM` | `HS256` | 只允许 HS256/384/512（`Literal`） |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | 24 小时 |

- `Settings.auth_secret_key` 带 `repr=False`；`env=prod` 时长度 <32 直接 `ValidationError`。
- `.env` 追加随机生成的 64 字符密钥（不提交）；`.env.example` 写占位说明。

## 8. 错误处理与错误码

| 场景 | HTTP | code | message |
|---|---|---|---|
| 注册参数非法（含 admin 角色） | 422 | 42200 | 参数校验失败: <loc> <msg>（S0-5 统一处理器） |
| 注册用户名已存在 | 409 | **40900（新增）** | 用户名已存在 |
| 登录用户名/密码错误 | 401 | 40100 | 用户名或密码错误 |
| 未带 token / scheme 不对 | 401 | 40100 | 未提供认证凭据 |
| token 无效（签名/结构/claims） | 401 | 40100 | 无效的认证凭据 |
| token 过期 | 401 | 40100 | 登录已过期，请重新登录 |
| token 有效但用户已删 | 401 | 40100 | 账号不存在或已被删除 |

- 新增 `CODE_CONFLICT = 40900`、`ConflictError`，并把 409 加入 `_HTTP_TO_CODE`（API.md §13 同步）。
- 所有响应仍由 S0-5 全局处理器统一转壳，路由不手拼错误 JSON。

## 9. 测试

测试套件不连真实数据库 / 不发真实网络请求（AGENTS §9.4）。三条线：

### 9.1 `tests/test_security.py`（纯函数）

1. `hash_password` 产物不是明文、两次哈希不同（盐）
2. 正确口令 `verify_password` 为 True，错误口令为 False
3. 损坏哈希串 → False 不抛异常
4. 签发→解析 roundtrip：`user_id/role` 一致、`exp` 在未来
5. 过期 token（`expires_delta=timedelta(seconds=-1)`）→ `AuthError("登录已过期...")`
6. 换密钥签发 → `AuthError("无效的认证凭据")`
7. 篡改 token 字符串 → `AuthError`
8. `ensure_auth_configured` 空密钥 → `RuntimeError`；有密钥不抛

### 9.2 `tests/test_auth_service.py`（fake session）

1. 注册成功：用户名被 trim+小写、`password_hash != 明文`、返回对象字段正确
2. 注册重名：`commit` 抛 `IntegrityError` → `UserAlreadyExistsError`，且调用了 `rollback`
3. 登录成功返回对应用户
4. 登录用户不存在 → `AuthError`（且假哈希校验被调用）
5. 登录密码错 → `AuthError`
6. `issue_token_for`：`expires_in` 等于配置秒数，token 可被 `decode_access_token` 解出 `user_id/role`

### 9.3 `tests/test_auth_api.py`（TestClient + `get_db` 依赖覆盖）

1. 注册 → 201、统一壳、`data` 无 `password_hash`
2. 注册参数非法（短密码 / admin 角色 / 含空格用户名）→ 422 + `42200`
3. 注册重名 → 409 + `40900`
4. 登录 → 200、`access_token` 非空、`token_type=bearer`、`expires_in=86400`、`user.role`
5. 登录密码错 / 用户不存在 → 都是 401 + 同一 message
6. `/auth/me` 不带 token → 401 + "未提供认证凭据"
7. `/auth/me` 带有效 token → 200 + 用户信息
8. `/auth/me` 带过期 token → 401 + "登录已过期"
9. `/auth/me` 带乱码 token → 401 + "无效的认证凭据"

### 9.4 `tests/test_config.py` 追加

1. auth 默认值（空密钥允许、1440 分钟、HS256）
2. `repr` 不包含密钥
3. `env=prod` + 短密钥 → `ValidationError`
4. `env=prod` + 32+ 字符密钥 → 通过

## 10. 验收（实施后真实执行并贴输出）

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q          # 237 passed（基线 206 + 本卡 31）

# 起服务（另一个终端）
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# ① 注册（用明显假数据）
curl -s -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"Test_User_1","password":"test-pass-123","nickname":"测试用户_1","grade":"高一"}'
# 期望 201 + code=0 + data.username=test_user_1（已转小写）、无 password_hash

# ② 重复注册 → 409 + 40900
# ③ admin 角色 → 422 + 42200
# ④ 登录
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"test_user_1","password":"test-pass-123"}' | ../.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
# ⑤ 受保护接口
curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
# ⑥ 无 token → 401；错误密码 → 401 同一文案
# ⑦ 数据库确认只存哈希
docker exec study-agent-postgres psql -U study -d study_agent \
  -c "SELECT username, left(password_hash, 16) AS hash_prefix, role FROM users WHERE username='test_user_1';"
```

验收后清掉 curl 产生的测试用户（`DELETE FROM users WHERE username='test_user_1';`），保持库内无测试数据。

## 11. 已知限制（写进 PROGRESS / DECISIONS）

- **无 refresh / 登出 / 吊销**：无状态 JWT 在过期前一直有效；密钥轮换会让所有 token 立刻失效。后续卡再补 refresh 与黑名单。
- **无登录限流**：暴力破解防护依赖部署层或后续缓存（S3-7 有 Redis 后补）。
- **Argon2id 单次校验约几十毫秒**（本机实测值回填），登录接口 P95 会比只读接口高；这是有意的成本。
- **用户名大小写归一化**：已注册的 `Alice` 与 `alice` 视为同一账号；论文需写明该规则。
- token 里的 `role` 不是权限来源，数据库才是；S2-3 必须基于回表用户判断。

## 12. 文档同步

| 文档 | 改动 |
|---|---|
| `API.md` | §0 认证行写 Bearer/24h；§1 三条接口定稿；§12 删「注册/登出/refresh」行，保留「refresh/登出策略待定」；§13 增 40900 |
| `AGENTS.md` | §9.6 增认证锚点（core/security.py + api/deps.py） |
| `DECISIONS.md` | 新增 D-022（6 条决策 + 验证） |
| `PROGRESS.md` | S2-2 打勾、当前状态、变更日志（实测数字） |
| `.env.example` | 新增 `AUTH_*` 三项 |
| `requirements.txt` | 新增 `pwdlib[argon2]==0.3.1`、`PyJWT==2.15.1` |
| `SCHEMA.md` | **不改**（users 表 S2-1 已交付） |

## 13. 自检

- [x] 任务卡四项验收（注册/登录/错误密码/token 过期）在 §9 都有对应用例
- [x] 任务卡「JWT 含 user_id/role/exp」→ §3.4 / §4
- [x] 任务卡「提供 get_current_user 依赖」→ §6.1
- [x] 任务卡「登录失败不泄露用户不存在」→ §2.3-5 / §5 / §9.3-5
- [x] 任务卡「不手写令牌与哈希」→ 依赖 pwdlib/PyJWT（§2.3-1）
- [x] 新增依赖已获用户批准（2026-10-26）
- [x] 契约先行：API.md 更新列在 §3 / §12，写码前完成
- [x] 无 TBD 留给实施者