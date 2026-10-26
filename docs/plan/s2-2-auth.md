# S2-2 认证（注册 / 登录 / JWT / 当前用户）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`GET /api/v1/auth/me` 与可复用的 `get_current_user` 依赖，口令用 Argon2id 哈希、令牌用 HS256 JWT。

**Architecture:** 原语（哈希/JWT）放 `core/security.py`，业务（注册/认证/签发）放 `services/auth_service.py`，请求级依赖（Session/当前用户）放 `api/deps.py`，路由只做「校验 → service → 统一壳」。数据库经同步 SQLAlchemy Session，`role` 以回表数据为准。

**Tech Stack:** Python 3.11 + FastAPI 0.143 + Pydantic v2 + SQLAlchemy 2.1 + pwdlib 0.3.1（Argon2id）+ PyJWT 2.15.1。

**Spec:** `docs/spec/s2-2-auth.md`

## Global Constraints

- 只允许新增两个依赖：`pwdlib[argon2]==0.3.1`、`PyJWT==2.15.1`（2026-10-26 用户批准）；不装 `python-multipart`（登录走 JSON）。
- 口令只存 Argon2id 哈希；代码/日志/响应里禁止出现明文口令或哈希。
- 密钥只从 `Settings.auth_secret_key`（`repr=False`）读取；`.env` 不提交。
- JWT：HS256，载荷 `{sub, role, iat, exp}`，默认 24h；`sub` 为字符串。
- 登录失败统一 401 +「用户名或密码错误」；用户不存在时也要跑一次假哈希校验。
- 所有成功响应必须套 `Envelope`；所有业务错误抛 `AppError` 子类（新增 `ConflictError`/40900）。
- 路由函数只做参数校验 → service → 组装壳，不写业务分支。
- 测试禁止连真实数据库、发真实网络请求；`get_db` 统一用依赖覆盖。
- 不改 `users` 表与迁移；不动 `note_chunks`。
- 命令在仓库根 `E:\BiShe-AIStudy\study-agent` 的 Git Bash 下执行。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/requirements.txt` | 记录两个新依赖 | 修改 |
| `.env.example` / `.env` | `AUTH_*` 三项（.env 写真实随机密钥） | 修改（.env 不入库） |
| `backend/app/core/config.py` | `auth_*` 配置 + prod 密钥强度校验 | 修改 |
| `backend/app/core/exceptions.py` | `CODE_CONFLICT=40900`、`ConflictError`、409 映射 | 修改 |
| `backend/app/core/security.py` | Argon2id 哈希、JWT 签发/解析、启动校验 | 新建 |
| `backend/app/schemas/auth.py` | `RegisterRequest/LoginRequest/UserOut/TokenOut` | 新建 |
| `backend/app/services/auth_service.py` | 注册、认证、签发 | 新建 |
| `backend/app/api/__init__.py`、`api/v1/__init__.py` | 包初始化 | 新建 |
| `backend/app/api/deps.py` | `get_db`、`get_current_user`、`bearer_scheme` | 新建 |
| `backend/app/api/v1/auth.py` | 三条路由 | 新建 |
| `backend/app/api/router.py` | `/api/v1` 汇总 | 新建 |
| `backend/app/main.py` | 启动校验 + `include_router` | 修改 |
| `backend/tests/test_security.py` | 原语测试 | 新建 |
| `backend/tests/test_auth_service.py` | 服务测试（fake session） | 新建 |
| `backend/tests/test_auth_api.py` | 接口测试（依赖覆盖） | 新建 |
| `backend/tests/test_config.py` | auth 配置测试 | 修改 |
| `docs/API.md` 等 | 契约与文档同步 | 修改 |

---

### Task 1: 依赖、配置与冲突错误码

**Files:**
- Modify: `backend/requirements.txt`、`.env.example`、`.env`、`backend/app/core/config.py`、`backend/app/core/exceptions.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.auth_secret_key`（str，默认 ""，repr 隐藏）、`Settings.auth_algorithm`（`Literal["HS256","HS384","HS512"]`，默认 HS256）、`Settings.auth_access_token_expire_minutes`（int，默认 1440）、`CODE_CONFLICT=40900`、`ConflictError`。Task 2/3/4 依赖这些名字。

- [ ] **Step 1: 安装依赖并钉版本**

Run:
```bash
cd /e/BiShe-AIStudy/study-agent
.venv/Scripts/python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple \
  "pwdlib[argon2]==0.3.1" "PyJWT==2.15.1"
.venv/Scripts/python.exe -m pip list | grep -i -E "pwdlib|pyjwt|argon2"
```
Expected: 三个包出现；`pwdlib 0.3.1`、`PyJWT 2.15.1`。

- [ ] **Step 2: 写 requirements**

在 `backend/requirements.txt` 末尾追加：

```
# --- S2-2 认证（任务卡：官方安全示例；Argon2id + JWT；2026-10-26 用户批准）---
pwdlib[argon2]==0.3.1
PyJWT==2.15.1
```

- [ ] **Step 3: 写失败测试（配置项）**

在 `backend/tests/test_config.py` 末尾追加：

```python
def test_auth_defaults(monkeypatch) -> None:
    for name in ("AUTH_SECRET_KEY", "AUTH_ALGORITHM", "AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.auth_secret_key == ""
    assert s.auth_algorithm == "HS256"
    assert s.auth_access_token_expire_minutes == 1440


def test_auth_secret_hidden_from_repr(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "sk-test-auth-secret")
    s = Settings(_env_file=None)
    assert s.auth_secret_key == "sk-test-auth-secret"
    assert "sk-test-auth-secret" not in repr(s)


def test_auth_prod_requires_long_secret(monkeypatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("AUTH_SECRET_KEY", "too-short")
    try:
        Settings(_env_file=None)
    except ValidationError as exc:
        assert "AUTH_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("prod 环境短密钥应被拒绝")


def test_auth_prod_accepts_long_secret(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    assert Settings(_env_file=None).auth_secret_key == "x" * 32
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_config.py -q -k auth`
Expected: `AttributeError: ... auth_secret_key`（4 条失败）

- [ ] **Step 5: 改 config 与 exceptions**

在 `backend/app/core/config.py` 的 `qa_*` 之后、`@model_validator` 之前插入：

```python
    # --- 认证（S2-2；密钥只放 .env，禁止提交）---
    auth_secret_key: str = Field(default="", repr=False)
    auth_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    auth_access_token_expire_minutes: int = 1440
```

在 `_fallback_dashscope_key` 之后追加第二个校验器：

```python
    @model_validator(mode="after")
    def _validate_auth_secret(self) -> "Settings":
        """prod 环境不允许短密钥；dev 允许空值（由 create_app 启动时再拒绝，便于纯单测）。"""
        if self.env == "prod" and len(self.auth_secret_key) < 32:
            raise ValueError("AUTH_SECRET_KEY 长度至少 32 个字符（prod 环境）")
        return self
```

在 `backend/app/core/exceptions.py`：

1) 常量区加 `CODE_CONFLICT = 40900`（紧跟 `CODE_VALIDATION` 之后）；
2) `_HTTP_TO_CODE` 加一行 `409: CODE_CONFLICT,`；
3) 在 `ForbiddenError` 之后加：

```python
class ConflictError(AppError):
    def __init__(self, message: str = "资源冲突") -> None:
        super().__init__(message, code=CODE_CONFLICT, http_status=409)
```

- [ ] **Step 6: 写 .env 与 .env.example**

生成密钥：
```bash
.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 末尾追加（把 `<上面输出的密钥>` 换成真实值）：

```
# ===== 认证（S2-2；密钥只放 .env，禁止提交）=====
AUTH_SECRET_KEY=<上面输出的密钥>
AUTH_ALGORITHM=HS256
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

`.env.example` 末尾追加：

```
# ===== 认证（S2-2；密钥只放 .env，禁止提交）=====
# 生成：python -c "import secrets; print(secrets.token_urlsafe(48))"
AUTH_SECRET_KEY=change-me-generate-a-random-64-char-secret
AUTH_ALGORITHM=HS256
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: 全绿（含既有用例）。

- [ ] **Step 8: 提交**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/app/core/exceptions.py backend/tests/test_config.py .env.example
git commit -m "feat(s2-2): 认证依赖、配置项与冲突错误码"
```

---

### Task 2: 认证原语 `core/security.py`

**Files:**
- Create: `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: `Settings.auth_*`、`AuthError`、`UserRole`。
- Produces: `IssuedToken(token, expires_in)`、`TokenClaims(user_id, role, exp)`、`hash_password`、`verify_password`、`dummy_password_hash`、`create_access_token(*, user_id, role, expires_delta=None, settings=None)`、`decode_access_token(token, *, settings=None)`、`ensure_auth_configured(settings=None)`。Task 3/4 只调这些。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_security.py`：

```python
"""S2-2 认证原语测试：Argon2id 哈希与 HS256 JWT（spec §9.1）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthError
from app.core.security import (
    create_access_token,
    decode_access_token,
    ensure_auth_configured,
    hash_password,
    verify_password,
)

_SECRET = "test-secret-key-0123456789abcdef0123456789abcdef"


def _settings(**overrides) -> Settings:
    data = {"auth_secret_key": _SECRET}
    data.update(overrides)
    return Settings(_env_file=None, **data)


def test_hash_password_is_not_plaintext_and_salted() -> None:
    first = hash_password("test-pass-123")
    second = hash_password("test-pass-123")
    assert first != "test-pass-123"
    assert first != second
    assert first.startswith("$argon2")


def test_verify_password_accepts_correct_and_rejects_wrong() -> None:
    hashed = hash_password("test-pass-123")
    assert verify_password("test-pass-123", hashed) is True
    assert verify_password("wrong-pass-1", hashed) is False


def test_verify_password_returns_false_on_broken_hash() -> None:
    assert verify_password("test-pass-123", "definitely-not-a-hash") is False


def test_token_roundtrip_carries_user_id_role_and_exp() -> None:
    settings = _settings()
    issued = create_access_token(user_id=7, role="teacher", settings=settings)
    claims = decode_access_token(issued.token, settings=settings)
    assert claims.user_id == 7
    assert claims.role == "teacher"
    assert claims.exp.tzinfo is not None
    assert claims.exp > datetime.now(timezone.utc)
    assert issued.expires_in == 1440 * 60


def test_expired_token_raises_auth_error() -> None:
    settings = _settings()
    issued = create_access_token(
        user_id=1, role="student", expires_delta=timedelta(seconds=-5), settings=settings
    )
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=settings)
    assert "过期" in excinfo.value.message


def test_token_signed_with_other_secret_is_rejected() -> None:
    issued = create_access_token(
        user_id=1,
        role="student",
        settings=_settings(auth_secret_key="other-secret-0123456789abcdef0123456789"),
    )
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=_settings())
    assert excinfo.value.message == "无效的认证凭据"


def test_tampered_token_is_rejected() -> None:
    issued = create_access_token(user_id=1, role="student", settings=_settings())
    with pytest.raises(AuthError):
        decode_access_token(issued.token[:-3] + "abc", settings=_settings())


def test_unknown_role_in_token_is_rejected() -> None:
    settings = _settings()
    issued = create_access_token(user_id=1, role="hacker", settings=settings)
    with pytest.raises(AuthError) as excinfo:
        decode_access_token(issued.token, settings=settings)
    assert excinfo.value.message == "无效的认证凭据"


def test_ensure_auth_configured_rejects_empty_secret() -> None:
    with pytest.raises(RuntimeError):
        ensure_auth_configured(Settings(_env_file=None, auth_secret_key=""))


def test_ensure_auth_configured_accepts_secret() -> None:
    ensure_auth_configured(_settings())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_security.py -q`
Expected: `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 3: 实现 `security.py`**

```python
"""S2-2 认证原语：Argon2id 口令哈希 + HS256 JWT（spec §4）。

为什么把原语与业务分开：哈希/JWT 是纯函数，能脱离数据库单测；
service 只负责“查库 + 组装 + 事务”，router 只负责壳。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthError
from app.models.enums import UserRole

_PASSWORD_HASH = PasswordHash.recommended()
_VALID_ROLES = frozenset(member.value for member in UserRole)


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_in: int


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    role: str
    exp: datetime


def hash_password(password: str) -> str:
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """哈希串损坏/格式不认识 → False（不能让登录接口 500）。

    pwdlib 的 UnknownHashError 继承自 Exception（不是 ValueError）；
    argon2 的 InvalidHashError 继承 ValueError，两个都要接住。
    """
    try:
        return _PASSWORD_HASH.verify(password, password_hash)
    except (UnknownHashError, ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """登录用户不存在时也跑一次校验，抹平“存在/不存在”的响应时间差。"""
    return hash_password("dummy-password-for-timing-equalization")


def _secret(settings: Settings) -> str:
    if not settings.auth_secret_key:
        raise RuntimeError(
            "AUTH_SECRET_KEY 未配置：请在 .env 设置随机密钥（见 .env.example）"
        )
    return settings.auth_secret_key


def ensure_auth_configured(settings: Settings | None = None) -> None:
    """启动时快速失败，避免无密钥的服务跑起来后才在登录处 500。"""
    _secret(settings or get_settings())


def create_access_token(
    *,
    user_id: int,
    role: str,
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
) -> IssuedToken:
    current = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta or timedelta(minutes=current.auth_access_token_expire_minutes)
    )
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": expires}
    token = jwt.encode(payload, _secret(current), algorithm=current.auth_algorithm)
    return IssuedToken(token=token, expires_in=int((expires - now).total_seconds()))


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenClaims:
    current = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            _secret(current),
            algorithms=[current.auth_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("无效的认证凭据") from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("无效的认证凭据") from exc

    role = payload.get("role")
    if role not in _VALID_ROLES:
        raise AuthError("无效的认证凭据")

    exp_raw = payload.get("exp")
    if not isinstance(exp_raw, (int, float)):
        raise AuthError("无效的认证凭据")
    return TokenClaims(
        user_id=user_id,
        role=role,
        exp=datetime.fromtimestamp(exp_raw, tz=timezone.utc),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_security.py -q`
Expected: `10 passed`

若 `verify_password` 对坏哈希抛的异常不在 `(UnknownHashError, ValueError, TypeError)` 里，按实际类型补进 except 元组，**不要**改成 `except Exception: return False` 把真 bug 一起吞掉。

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/security.py backend/tests/test_security.py
git commit -m "feat(s2-2): Argon2id 哈希与 HS256 JWT 原语"
```

---

### Task 3: Schema 与服务层

**Files:**
- Create: `backend/app/schemas/auth.py`、`backend/app/services/auth_service.py`
- Test: `backend/tests/test_auth_service.py`

**Interfaces:**
- Consumes: Task 2 的 `hash_password / verify_password / dummy_password_hash / create_access_token`；`UserRole`；`User`。
- Produces: `RegisterRequest(username, password, nickname, grade, role)`（username 已归一化）、`LoginRequest`、`UserOut`、`TokenOut`、`UserAlreadyExistsError`、`register_user(session, payload)`、`authenticate_user(session, *, username, password)`、`issue_token_for(user)`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_auth_service.py`：

```python
"""S2-2 认证服务测试：fake session 覆盖注册/登录/签发（spec §9.2）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import security
from app.core.config import Settings
from app.core.exceptions import AuthError
from app.core.security import decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services import auth_service
from app.services.auth_service import (
    UserAlreadyExistsError,
    authenticate_user,
    issue_token_for,
    register_user,
)


class FakeSession:
    def __init__(self, *, user: User | None = None, commit_error: Exception | None = None) -> None:
        self.user = user
        self.commit_error = commit_error
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[object] = []
        self.statements: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)
        if getattr(instance, "id", None) is None:
            instance.id = 1
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    def scalar(self, statement: object) -> User | None:
        self.statements.append(statement)
        return self.user


def _payload(**overrides) -> RegisterRequest:
    data = {
        "username": "Test_User_1",
        "password": "test-pass-123",
        "nickname": "测试用户_1",
        "grade": "高一",
        "role": "student",
    }
    data.update(overrides)
    return RegisterRequest(**data)


def _user(**overrides) -> User:
    data = {
        "username": "test_user_1",
        "password_hash": hash_password("test-pass-123"),
        "nickname": "测试用户_1",
        "grade": "高一",
        "role": "student",
    }
    data.update(overrides)
    user = User(**data)
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def test_register_user_normalizes_username_and_hashes_password() -> None:
    session = FakeSession()
    user = register_user(session, _payload())
    assert user.username == "test_user_1"
    assert user.password_hash != "test-pass-123"
    assert verify_password("test-pass-123", user.password_hash) is True
    assert session.commits == 1
    assert session.refreshed == [user]


def test_register_user_duplicate_raises_conflict_and_rolls_back() -> None:
    session = FakeSession(commit_error=IntegrityError("INSERT", {}, Exception("duplicate")))
    with pytest.raises(UserAlreadyExistsError) as excinfo:
        register_user(session, _payload())
    assert excinfo.value.code == 40900
    assert session.rollbacks == 1


def test_authenticate_user_returns_matching_user() -> None:
    session = FakeSession(user=_user())
    user = authenticate_user(session, username="test_user_1", password="test-pass-123")
    assert user.id == 1


def test_authenticate_user_unknown_verifies_dummy_hash(monkeypatch) -> None:
    session = FakeSession(user=None)
    verified: list[str] = []

    def fake_verify(password: str, password_hash: str) -> bool:
        verified.append(password_hash)
        return False

    monkeypatch.setattr(auth_service, "verify_password", fake_verify)
    with pytest.raises(AuthError) as excinfo:
        authenticate_user(session, username="nobody_1", password="whatever-123")
    assert verified, "用户不存在时也必须跑一次哈希校验"
    assert excinfo.value.message == "用户名或密码错误"


def test_authenticate_user_wrong_password_raises_same_message() -> None:
    session = FakeSession(user=_user())
    with pytest.raises(AuthError) as excinfo:
        authenticate_user(session, username="test_user_1", password="wrong-pass-1")
    assert excinfo.value.message == "用户名或密码错误"


def test_issue_token_for_respects_configured_expiry(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        auth_secret_key="test-secret-0123456789abcdef0123456789abcd",
        auth_access_token_expire_minutes=30,
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    token_out = issue_token_for(_user())
    assert token_out.expires_in == 1800
    assert token_out.token_type == "bearer"
    assert token_out.user.username == "test_user_1"
    claims = decode_access_token(token_out.access_token)
    assert claims.user_id == 1
    assert claims.role == "student"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_auth_service.py -q`
Expected: `ModuleNotFoundError: No module named 'app.schemas.auth'`

- [ ] **Step 3: 写 `schemas/auth.py`**

```python
"""S2-2 认证出入参（契约：docs/API.md §1）。

用户名统一 trim + 小写：避免 “Alice / alice” 被当成两个账号；
口令长度上限 128 是防御性限制（Argon2 本身不截断）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RegisterableRole = Literal["student", "teacher", "parent"]


def _normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if any(char.isspace() for char in normalized):
        raise ValueError("用户名不能包含空白字符")
    if not 3 <= len(normalized) <= 50:
        raise ValueError("用户名长度需为 3–50 个字符")
    return normalized


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=50)
    grade: str | None = Field(default=None, max_length=20)
    role: RegisterableRole = "student"

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return _normalize_username(value)

    @field_validator("nickname")
    @classmethod
    def _nickname(cls, value: str) -> str:
        nickname = value.strip()
        if not nickname:
            raise ValueError("昵称不能为空")
        return nickname

    @field_validator("grade")
    @classmethod
    def _grade(cls, value: str | None) -> str | None:
        if value is None:
            return None
        grade = value.strip()
        return grade or None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        username = value.strip().lower()
        if any(char.isspace() for char in username):
            raise ValueError("用户名不能包含空白字符")
        return username


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    grade: str | None
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
```

- [ ] **Step 4: 写 `services/auth_service.py`**

```python
"""S2-2 认证业务：注册、登录、签发令牌（spec §5）。

一个用例一个事务：注册失败必须 rollback 后再抛，不能留下半插入状态。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import CODE_CONFLICT, AppError, AuthError
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import RegisterRequest, TokenOut, UserOut


class UserAlreadyExistsError(AppError):
    def __init__(self, message: str = "用户名已存在") -> None:
        super().__init__(message, code=CODE_CONFLICT, http_status=409)


def register_user(session: Session, payload: RegisterRequest) -> User:
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
        grade=payload.grade,
        role=payload.role,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise UserAlreadyExistsError() from exc
    session.refresh(user)
    return user


def authenticate_user(session: Session, *, username: str, password: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        # 用户不存在也做一次哈希校验：响应时间不因“账号是否存在”而不同
        verify_password(password, dummy_password_hash())
        raise AuthError("用户名或密码错误")
    if not verify_password(password, user.password_hash):
        raise AuthError("用户名或密码错误")
    return user


def issue_token_for(user: User) -> TokenOut:
    issued = create_access_token(user_id=user.id, role=user.role)
    return TokenOut(
        access_token=issued.token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(user),
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_auth_service.py -q`
Expected: `6 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/auth.py backend/app/services/auth_service.py backend/tests/test_auth_service.py
git commit -m "feat(s2-2): 注册与登录服务层"
```

---

### Task 4: 依赖、路由与装配

**Files:**
- Create: `backend/app/api/__init__.py`、`backend/app/api/v1/__init__.py`、`backend/app/api/deps.py`、`backend/app/api/v1/auth.py`、`backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: Task 2 `decode_access_token`、Task 3 service 与 schema。
- Produces: `get_db`、`bearer_scheme`、`get_current_user`（S2-3 直接复用）、`api_router`；三条 HTTP 路由。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_auth_api.py`：

```python
"""S2-2 认证接口测试：TestClient + get_db 依赖覆盖，不连真实数据库（spec §9.3）。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User

REGISTER_BODY = {
    "username": "Test_User_1",
    "password": "test-pass-123",
    "nickname": "测试用户_1",
    "grade": "高一",
    "role": "student",
}


class FakeSession:
    def __init__(self, *, user: User | None = None, commit_error: Exception | None = None) -> None:
        self.user = user
        self.commit_error = commit_error
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 1
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(timezone.utc)

    def scalar(self, statement: object) -> User | None:
        return self.user


def _user(**overrides) -> User:
    data = {
        "username": "test_user_1",
        "password_hash": hash_password("test-pass-123"),
        "nickname": "测试用户_1",
        "grade": "高一",
        "role": "student",
    }
    data.update(overrides)
    user = User(**data)
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_register_returns_201_envelope_without_password_hash(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 0
    assert body["trace_id"]
    assert body["data"]["username"] == "test_user_1"
    assert body["data"]["role"] == "student"
    assert "password_hash" not in body["data"]


def test_register_rejects_short_password(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "password": "short"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_register_rejects_admin_role(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "role": "admin"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_register_rejects_username_with_space(client: TestClient) -> None:
    _override(FakeSession())
    resp = client.post(
        "/api/v1/auth/register", json={**REGISTER_BODY, "username": "bad user"}
    )
    assert resp.status_code == 422


def test_register_duplicate_username_returns_409(client: TestClient) -> None:
    _override(FakeSession(commit_error=IntegrityError("INSERT", {}, Exception("dup"))))
    resp = client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900
    assert resp.json()["message"] == "用户名已存在"


def test_login_returns_token_envelope(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "Test_User_1", "password": "test-pass-123"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["id"] == 1


def test_login_wrong_password_and_unknown_user_share_message(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "test_user_1", "password": "wrong-pass-1"},
    )
    _override(FakeSession(user=None))
    unknown = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody_1", "password": "wrong-pass-1"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"] == "用户名或密码错误"
    assert wrong.json()["code"] == unknown.json()["code"] == 40100


def test_me_without_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["message"] == "未提供认证凭据"


def test_me_with_valid_token_returns_user(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    token = create_access_token(user_id=1, role="student").token
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "test_user_1"


def test_me_with_expired_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    token = create_access_token(
        user_id=1, role="student", expires_delta=timedelta(seconds=-5)
    ).token
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
    assert "过期" in resp.json()["message"]


def test_me_with_garbage_token_returns_401(client: TestClient) -> None:
    _override(FakeSession(user=_user()))
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "无效的认证凭据"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_auth_api.py -q`
Expected: `ImportError: cannot import name 'get_db' from 'app.api.deps'`（或 404，因暂无路由）

- [ ] **Step 3: 建包与依赖**

`backend/app/api/__init__.py`：

```python
"""HTTP 接口包：路由按版本放子包（v1 起）。"""
```

`backend/app/api/v1/__init__.py`：

```python
"""v1 接口：每个模块一个文件，由 api/router.py 汇总。"""
```

`backend/app/api/deps.py`：

```python
"""请求级依赖：数据库 Session 与当前登录用户（spec §6.1）。

S2-3 的 require_role/require_student_access 直接在本文件的
get_current_user 之上组合，不再自己解析 token。
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import new_session
from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("未提供认证凭据")
    claims = decode_access_token(credentials.credentials)
    user = session.scalar(select(User).where(User.id == claims.user_id))
    if user is None:
        raise AuthError("账号不存在或已被删除")
    return user
```

- [ ] **Step 4: 建路由与装配**

`backend/app/api/v1/auth.py`：

```python
"""S2-2 认证接口：注册 / 登录 / 当前用户（spec §3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.schemas.common import Envelope
from app.services.auth_service import authenticate_user, issue_token_for, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=201,
    response_model=Envelope[UserOut],
    summary="注册（student/teacher/parent，admin 不可自助注册）",
)
def register(
    payload: RegisterRequest, session: Session = Depends(get_db)
) -> Envelope[UserOut]:
    user = register_user(session, payload)
    return Envelope[UserOut](trace_id=get_trace_id(), data=UserOut.model_validate(user))


@router.post("/login", response_model=Envelope[TokenOut], summary="登录")
def login(
    payload: LoginRequest, session: Session = Depends(get_db)
) -> Envelope[TokenOut]:
    user = authenticate_user(session, username=payload.username, password=payload.password)
    return Envelope[TokenOut](trace_id=get_trace_id(), data=issue_token_for(user))


@router.get("/me", response_model=Envelope[UserOut], summary="当前登录用户")
def me(current_user: User = Depends(get_current_user)) -> Envelope[UserOut]:
    return Envelope[UserOut](
        trace_id=get_trace_id(), data=UserOut.model_validate(current_user)
    )
```

`backend/app/api/router.py`：

```python
"""v1 路由汇总：只做 include，不写业务。"""
from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)

__all__ = ["api_router"]
```

`backend/app/main.py`：

1) 在 `from app.core.logging import setup_logging` 之后加
```python
from app.api.router import api_router
```
实际按字母序放在 `from app import __version__` 之后：
```python
from app.api.router import api_router
from app.core.config import get_settings
```
2) 在 `from app.core.middleware import TraceIdMiddleware` 之后加：
```python
from app.core.security import ensure_auth_configured
```
3) 在 `create_app()` 里 `setup_logging(...)` 之后加：
```python
    ensure_auth_configured(settings)
```
4) 在 `install_exception_handlers(app)` 之后加：
```python
    app.include_router(api_router)
```

- [ ] **Step 5: 跑接口测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_auth_api.py -q`
Expected: `11 passed`

- [ ] **Step 6: 回归既有测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_main.py tests/test_auth_service.py tests/test_security.py -q`
Expected: 全绿（`/health` 仍正常，三条新路由不影响 404 壳）。

- [ ] **Step 7: 提交**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_auth_api.py
git commit -m "feat(s2-2): 认证路由、get_current_user 依赖与应用装配"
```

---

### Task 5: 文档同步、真实验收与全量回归

**Files:**
- Modify: `docs/API.md`、`docs/AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`

- [ ] **Step 1: 更新 `docs/API.md`**

1. §0「认证」行改为：
   `- 认证：Bearer JWT（S2-2 交付）：请求头 \`Authorization: Bearer <token>\`；载荷 \`{sub, role, iat, exp}\`，HS256，默认 24h 过期；无 refresh/登出（待后续）。未特别标注的接口权限默认 \`student\`，且只能访问自己的数据；⚠ RBAC 细则 S2-3 定稿`
2. §1 认证整节替换为三条接口（照 spec §3 写全入参表、出参、错误码；含「用户名不区分大小写」与「role 以数据库为准」备注）。
3. §12 待定清单：删掉 `| 认证 | 注册 / 登出 / refresh / token 刷新策略 | S2-2 |`，改为 `| 认证 | 登出 / refresh / 吊销策略 | 后续（S2-2 已交付注册/登录/me，无状态 JWT 暂无吊销） |`。
4. §13 错误码表加一行：`| 40900 | 资源冲突（如用户名已存在） | 409 |`。

- [ ] **Step 2: 更新 `docs/AGENTS.md` §9.6**

在「后端路由样例」行之后加：

```
- 后端认证样例：backend/app/core/security.py + backend/app/api/deps.py（Argon2id 口令哈希；PyJWT HS256，sub=user_id 字符串；HTTPBearer 取 token；get_current_user 回表取角色为权威；错误统一 AuthError→40100）
```

并把「后端路由样例：（待 S2 首个正式路由后回填）」替换为：

```
- 后端路由样例：backend/app/api/v1/auth.py（路由只做 Pydantic 入参 → service → Envelope 组装；业务错误由 service 抛 AppError）
```

- [ ] **Step 3: 更新 `docs/DECISIONS.md`**

在 D-021 之后追加 D-022（6 条决策 + 验证，内容照 spec §2.3/§10，验证数字待 Step 6 回填后写真实值）。

- [ ] **Step 4: 更新 `docs/PROGRESS.md`**

1. 当前状态：最近完成改 S2-2，下一步改 S2-3；
2. 任务清单 S2-2 打 `[x]`；
3. 变更日志追加 `### 2026-10-26（S2-2）`：交付、验收证据（pytest 数字、curl 实测输出摘要、Argon2 登录耗时实测）、已知限制（无 refresh/限流、密钥轮换影响）、文档同步。

- [ ] **Step 5: 起服务做真实 curl 验收**

Run（另开后台任务）：
```bash
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```
然后在另一条命令里逐条执行并保存输出：

```bash
curl -s -o /tmp/reg.json -w "%{http_code}\n" -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"Test_User_1","password":"test-pass-123","nickname":"测试用户_1","grade":"高一"}'
cat /tmp/reg.json

curl -s -o /dev/null -w "dup=%{http_code}\n" -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test_user_1","password":"test-pass-123","nickname":"测试用户_1"}'

curl -s -o /dev/null -w "admin=%{http_code}\n" -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test_admin_1","password":"test-pass-123","nickname":"测试用户_A","role":"admin"}'

TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"test_user_1","password":"test-pass-123"}' \
  | ../.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
echo "token_len=${#TOKEN}"
curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
curl -s -o /tmp/me401.json -w "no_token=%{http_code}\n" localhost:8000/api/v1/auth/me
curl -s -o /tmp/pw401.json -w "wrong_pw=%{http_code}\n" -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"username":"test_user_1","password":"wrong-pass-1"}'
cat /tmp/me401.json; echo; cat /tmp/pw401.json; echo
docker exec study-agent-postgres psql -U study -d study_agent \
  -c "SELECT username, left(password_hash, 20) AS hash_prefix, role FROM users WHERE username='test_user_1';"
```

Expected：注册 201、`data.username=test_user_1`、无 `password_hash`；dup=409；admin=422；`token_len` > 100；`/me` 返回同一用户；no_token=401、wrong_pw=401 且两条 message 都是「用户名或密码错误」/「未提供认证凭据」；库里 `hash_prefix` 以 `$argon2` 开头。

- [ ] **Step 6: 清理测试数据并停止服务**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "DELETE FROM users WHERE username LIKE 'test_%';"
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM users;"
```
Expected: `0`（本卡验收不留下任何测试账号）。然后停掉后台 uvicorn（`job_kill`），确认 8000 无 LISTEN。

- [ ] **Step 7: 全量回归**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `237 passed`（206 基线 + 31 新增：配置 4 / 安全原语 10 / 服务 6 / 接口 11；如实记录，不允许改测试凑数）。

- [ ] **Step 8: 回填 D-022 与 PROGRESS 的真实数字**

把 Step 5/7 的实测输出写进 DECISIONS D-022「验证」与 PROGRESS 变更日志（pytest 数字、curl 状态码、Argon2 单次登录耗时）。

- [ ] **Step 9: 提交**

```bash
git add docs/
git commit -m "docs(s2-2): 认证契约、决策与进度同步"
```

- [ ] **Step 10: 核对工作区**

Run: `git status --short && git log --oneline -6`
Expected: 工作区干净；最近 5 个提交为本卡 5 个 commit。

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §2.1 做（原语/deps/service/schema/路由/配置/测试/文档） | Task 1–5 |
| §2.3 关键决策 6 条 | Task 1（依赖/配置）、2（哈希/JWT）、3（失败话术/防重名）、4（HTTPBearer）、5（文档） |
| §3 三条接口契约 | Task 3（schema）+ Task 4（路由） |
| §3.4 载荷/role 以库为准/大小写 | Task 2（载荷）+ Task 3（归一化）+ Task 4（回表） |
| §4 原语行为（过期/篡改/坏哈希/启动校验） | Task 2 测试 11 条 |
| §5 服务行为（事务/假哈希/签发） | Task 3 测试 6 条 |
| §6 deps 与装配 | Task 4 |
| §7 配置与密钥 | Task 1 + Task 4 启动校验 |
| §8 错误码（40900/40100/42200） | Task 1 + Task 4 测试 |
| §9 测试四条线 | Task 1–4 的测试文件 |
| §10 验收 | Task 5 Step 5–7 |
| §11 已知限制 | Task 5 Step 4/8 |
| §12 文档同步 | Task 5 Step 1–4、8 |

**2. Placeholder scan**：无 TBD/TODO；每个代码步骤给出完整文件内容；文档步骤给出精确替换文本。

**3. Type consistency**：`IssuedToken(token, expires_in)`、`TokenClaims(user_id, role, exp)` 在 Task 2 定义、Task 3/4 消费；`get_db`/`get_current_user`/`bearer_scheme` 命名在 Task 4 与 S2-3 交接说明一致；错误码 `CODE_CONFLICT=40900`、`UserAlreadyExistsError` 在 Task 1/3/4 一致。

## 执行记录

- 2026-10-26 实施完成，5 个 commit：`f2ad012` 依赖/配置/40900 → `802cf06` 安全原语 → `4748f59` schema+service → `e0f0844` 路由/依赖/装配 → 本条为文档同步提交。
- 测试：`pytest -q` → **237 passed, 1 warning**（基线 206 + 新增 31：test_config 4 / test_security 10 / test_auth_service 6 / test_auth_api 11）。实施中两处小偏差：安全原语用例实际 10 条（非计划写的 11）；接口用例 11 条（非 12）。均以实际为准并已回填本节与 spec。
- 真实 curl（uvicorn:8000）：register 201 → `{"code":0,...,"username":"test_user_1","role":"student"}`（`id=4`，无 `password_hash`）；重复注册 409/40900；`role=admin` 422/42200；login 200 → `token_len=164`；`/auth/me` 200 回显同一用户；无 token 401「未提供认证凭据」；错密码与未知用户均 401「用户名或密码错误」（同文案同码）；过期 token 401「登录已过期，请重新登录」；乱码 token 401「无效的认证凭据」。
- 时间侧信道：login 0.269–0.277s，未知用户 0.260–0.289s（dummy 哈希生效）。
- DB：`password_hash` 前缀 `$argon2id$v=19$m=655`；验收后 `DELETE` 测试账号，`users` 计数 0。
- 备注：`register` 返回的 `id=4` 是 S2-1 负向验证时 identity 序列已推进所致，非脏数据（插入前 `users` 为空，删除后仍为 0）。