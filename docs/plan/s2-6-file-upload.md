# S2-6 文件上传 + MinIO + 去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `POST /api/v1/files`（流式上传、类型/大小校验、sha256 去重、入 MinIO）与 `GET /api/v1/files/{id}/parse-status`，并用真实 MinIO + Postgres 验收“重复上传返回同一 file_id 且不重复占空间 / 61MB 被拒”。

**Architecture:** 路由（依赖注入 storage + session）→ `file_service`（清洗文件名、类型与 magic 校验、哈希、去重、写对象、写库、补偿）→ `ObjectStorage` 协议 → `MinioStorage` 适配器。测试用假 storage 与假 session，套件零网络。

**Tech Stack:** Python 3.11 + FastAPI 0.143 + Pydantic 2.14 + SQLAlchemy 2.1 + MinIO SDK + python-multipart + MinIO 服务（compose 已在跑）+ Pytest。

**Spec:** `docs/spec/s2-6-file-upload.md`

## Global Constraints

- 新依赖只有两个：`minio`、`python-multipart`（用户已批准）；装完把实测版本写回 `requirements.txt`。
- 不建表、不改迁移；`files` 表与 `uq_files_user_sha256` 用 S2-5 的成果。
- 上传只对 `student` 开放；`parse-status` 本人或已绑定家长/老师，admin 不绕过。
- `storage_path` 只存内容寻址键 `uploads/{user_id}/{sha256[:2]}/{sha256}{ext}`；客户端文件名只做展示字段。
- 超限 → 413/41300；类型/magic 不符 → 422/42200；缺 `file` 字段 → 400/40000；MinIO 故障 → 500/50000「文件存储不可用」。
- 测试禁止连 MinIO/PostgreSQL；storage 走 `Depends(get_storage)` 覆盖，DB 走 `get_db` 覆盖。
- 命令在仓库根 `E:\BiShe-AIStudy\study-agent` 的 Git Bash 下执行，Python 用 `.venv/Scripts/python.exe`。
- 提交信息用 Conventional Commits 并带 `s2-6`；用户负责 `git push`。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/requirements.txt` | 新增两个依赖（实测版本） | 修改 |
| `backend/app/core/config.py` | `minio_secure` / `upload_max_size_mb` / `upload_allowed_extensions` | 修改 |
| `backend/app/core/exceptions.py` | `PayloadTooLargeError`(413/41300)、`StorageUnavailableError`(500/50000) | 修改 |
| `backend/app/core/storage.py` | `ObjectStorage` 协议 + `MinioStorage` + `get_storage()` | 新建 |
| `.env.example` | 三个新变量 | 修改 |
| `backend/app/services/file_service.py` | 文件名清洗、类型检测、magic、上传、状态查询 | 新建 |
| `backend/app/schemas/files.py` | `FileOut` / `FileUploadOut` / `FileStatusOut` | 新建 |
| `backend/app/api/v1/files.py` | 两个路由 | 新建 |
| `backend/app/api/router.py` | 挂载 files | 修改 |
| `backend/tests/test_storage.py` | 适配器 10 条 | 新建 |
| `backend/tests/test_file_rules.py` | 文件名/类型/magic 13 条 | 新建 |
| `backend/tests/test_file_service.py` | 上传与查询 13 条 | 新建 |
| `backend/tests/test_files_api.py` | 接口 10 条 | 新建 |
| `docs/API.md` / `docs/SCHEMA.md` / `AGENTS.md` / `docs/DECISIONS.md` / `docs/PROGRESS.md` | 契约/决策/进度 | 修改 |

---

### Task 1: 依赖、配置、错误类型与存储适配器

**Files:**
- Modify: `backend/requirements.txt`、`backend/app/core/config.py`、`backend/app/core/exceptions.py`、`.env.example`
- Create: `backend/app/core/storage.py`、`backend/tests/test_storage.py`

**Interfaces:**
- Produces: `app.core.storage.ObjectStorage`（协议：`put` / `exists` / `delete` / `download_to` / `presigned_get_url`）、`MinioStorage`、`get_storage()`；`PayloadTooLargeError`、`StorageUnavailableError`；Settings 三个新字段。

- [ ] **Step 1: 安装并锁定依赖**

```bash
cd /e/BiShe-AIStudy/study-agent
./.venv/Scripts/python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple minio python-multipart 2>&1 | tail -3
./.venv/Scripts/python.exe -m pip show minio python-multipart | grep -E "^(Name|Version)"
```
Expected: 两条 `Name/Version`，把版本号填入下一条提交的 `requirements.txt`（占位符 `<minio版本>` / `<multipart版本>` 必须替换为实测值）：

```
# --- S2-6 文件上传（官方 SDK + FastAPI multipart 解析；2026-10-26 用户批准）---
minio==<minio版本>
python-multipart==<multipart版本>
```

- [ ] **Step 2: 配置与错误类型**

`backend/app/core/config.py` 在 `minio_bucket` 后加：

```python
    # 开发环境走 http；生产启用 TLS 时置 true
    minio_secure: bool = False

    # --- 上传（S2-6）---
    upload_max_size_mb: int = 60
    # 逗号分隔、小写、不带点；服务层解析
    upload_allowed_extensions: str = "pdf,docx,md,txt,png,jpg,jpeg"
```

`backend/app/core/exceptions.py`：

```python
CODE_PAYLOAD_TOO_LARGE = 41300
```
```python
class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "文件过大") -> None:
        super().__init__(message, code=CODE_PAYLOAD_TOO_LARGE, http_status=413)


class StorageUnavailableError(AppError):
    """对象存储不可用：对外固定话术，不泄露 endpoint/凭据。"""

    def __init__(self, message: str = "文件存储不可用") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)
```
并在 `_HTTP_TO_CODE` 加 `413: CODE_PAYLOAD_TOO_LARGE`。

`.env.example` 的 MinIO 段追加：

```
MINIO_SECURE=false
# S2-6 上传限制
UPLOAD_MAX_SIZE_MB=60
UPLOAD_ALLOWED_EXTENSIONS=pdf,docx,md,txt,png,jpg,jpeg
```

- [ ] **Step 3: 写存储测试 `backend/tests/test_storage.py`**

```python
"""S2-6 对象存储适配器：注入假 MinIO 客户端，不连网络。"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from minio.error import S3Error

from app.core import storage as storage_module
from app.core.exceptions import StorageUnavailableError
from app.core.storage import MinioStorage, get_storage


class FakeStat:
    def __init__(self, size: int) -> None:
        self.size = size


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.closed = False
        self.released = False

    def stream(self, size: int):
        for start in range(0, len(self._payload), size):
            yield self._payload[start : start + size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.buckets: set[str] = set()
        self.puts: list[dict[str, object]] = []
        self.removed: list[str] = []
        self.bucket_checks = 0
        self.made: list[str] = []
        self.fail_put = False

    def bucket_exists(self, bucket: str) -> bool:
        self.bucket_checks += 1
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)
        self.made.append(bucket)

    def put_object(self, bucket, key, data, length, content_type):  # noqa: ANN001
        if self.fail_put:
            raise OSError("boom")
        self.puts.append(
            {"bucket": bucket, "key": key, "size": length, "content_type": content_type}
        )
        self.objects[key] = data.read()

    def stat_object(self, bucket, key):  # noqa: ANN001
        if key not in self.objects:
            # minio 7.2.20 的 S3Error 签名：(response, code, message, resource, request_id, host_id)
            raise S3Error(
                response=None,
                code="NoSuchKey",
                message="missing",
                resource=key,
                request_id="req",
                host_id="host",
            )
        return FakeStat(len(self.objects[key]))

    def remove_object(self, bucket, key):  # noqa: ANN001
        self.removed.append(key)
        self.objects.pop(key, None)

    def get_object(self, bucket, key):  # noqa: ANN001
        return FakeResponse(self.objects[key])

    def presigned_get_object(self, bucket, key, expires=None):  # noqa: ANN001
        return f"http://minio/{bucket}/{key}?expires={int(expires.total_seconds())}"


def test_put_sends_length_and_content_type() -> None:
    client = FakeMinio()
    store = MinioStorage(client=client, bucket="b")
    store.put("k.pdf", BytesIO(b"%PDF-1.4"), size=8, content_type="application/pdf")
    assert client.puts == [
        {"bucket": "b", "key": "k.pdf", "size": 8, "content_type": "application/pdf"}
    ]


def test_put_creates_missing_bucket_once() -> None:
    client = FakeMinio()
    store = MinioStorage(client=client, bucket="b")
    store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    store.put("b", BytesIO(b"y"), size=1, content_type="text/plain")
    assert client.made == ["b"]
    assert client.bucket_checks == 1


def test_put_skips_bucket_creation_when_exists() -> None:
    client = FakeMinio()
    client.buckets.add("b")
    store = MinioStorage(client=client, bucket="b")
    store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    assert client.made == []


def test_put_wraps_sdk_failure() -> None:
    client = FakeMinio()
    client.fail_put = True
    store = MinioStorage(client=client, bucket="b")
    with pytest.raises(StorageUnavailableError) as excinfo:
        store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    assert excinfo.value.code == 50000
    assert "minio" not in excinfo.value.message.lower()


def test_delete_removes_key() -> None:
    client = FakeMinio()
    client.objects["a"] = b"x"
    MinioStorage(client=client, bucket="b").delete("a")
    assert client.removed == ["a"]


def test_exists_reports_true_and_false() -> None:
    client = FakeMinio()
    client.objects["a"] = b"x"
    store = MinioStorage(client=client, bucket="b")
    assert store.exists("a") is True
    assert store.exists("missing") is False


def test_download_to_writes_target_stream() -> None:
    client = FakeMinio()
    client.objects["a"] = b"hello"
    target = BytesIO()
    response = client.get_object("b", "a")
    MinioStorage(client=client, bucket="b").download_to("a", target)
    assert target.getvalue() == b"hello"
    assert response is not None


def test_presigned_url_contains_expiry() -> None:
    store = MinioStorage(client=FakeMinio(), bucket="b")
    url = store.presigned_get_url("a", expires_seconds=600)
    assert "expires=600" in url


def test_get_storage_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    get_storage.cache_clear()
    monkeypatch.setattr(
        storage_module,
        "get_settings",
        lambda: SimpleNamespace(
            minio_endpoint="localhost:9000",
            minio_root_user="u",
            minio_root_password="p",
            minio_bucket="b",
            minio_secure=False,
        ),
    )
    assert get_storage() is get_storage()
    get_storage.cache_clear()


def test_client_uses_secure_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_minio(endpoint, access_key, secret_key, secure):  # noqa: ANN001
        captured.update(endpoint=endpoint, secure=secure)
        return FakeMinio()

    monkeypatch.setattr(
        storage_module,
        "get_settings",
        lambda: SimpleNamespace(
            minio_endpoint="example:9000",
            minio_root_user="u",
            minio_root_password="p",
            minio_bucket="b",
            minio_secure=True,
        ),
    )
    monkeypatch.setattr(storage_module, "Minio", fake_minio)
    storage_module.MinioStorage().exists("x")
    assert captured == {"endpoint": "example:9000", "secure": True}
```

- [ ] **Step 4: 跑测试确认红**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_storage.py -q
```
Expected: `ModuleNotFoundError: No module named 'app.core.storage'`.

- [ ] **Step 5: 实现 `backend/app/core/storage.py`**

```python
"""对象存储适配器（S2-6）：协议 + MinIO 实现 + 进程内单例。

路由只依赖 put/exists/delete 这些语义方法，测试注入假实现即可，套件不连 MinIO。
对外错误固定「文件存储不可用」，不把 endpoint/凭据带进响应。
"""
from __future__ import annotations

from functools import lru_cache
from typing import BinaryIO, Protocol

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings
from app.core.exceptions import StorageUnavailableError

_CHUNK = 64 * 1024
_MISSING_CODES = {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}


class ObjectStorage(Protocol):
    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def download_to(self, key: str, target: BinaryIO) -> None: ...

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...


class MinioStorage:
    """懒连接、懒建桶：桶由 compose 的 minio-init 建，这里只做自愈。"""

    def __init__(self, client: Minio | None = None, *, bucket: str | None = None) -> None:
        self._bucket = bucket or get_settings().minio_bucket
        self._client = client
        self._bucket_ready = False

    def _client_obj(self) -> Minio:
        if self._client is None:
            settings = get_settings()
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_root_user,
                secret_key=settings.minio_root_password,
                secure=settings.minio_secure,
            )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        client = self._client_obj()
        try:
            if not client.bucket_exists(self._bucket):
                client.make_bucket(self._bucket)
        except Exception as exc:  # SDK 异常类型多，统一收敛
            raise StorageUnavailableError() from exc
        self._bucket_ready = True

    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        self._ensure_bucket()
        client = self._client_obj()
        try:
            client.put_object(
                self._bucket, key, data, length=size, content_type=content_type
            )
            stat = client.stat_object(self._bucket, key)
        except Exception as exc:
            raise StorageUnavailableError() from exc
        if getattr(stat, "size", size) != size:
            # 落盘字节数与声明不一致：宁可报错，也不留半截对象
            self.delete(key)
            raise StorageUnavailableError()

    def exists(self, key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client_obj().stat_object(self._bucket, key)
            return True
        except S3Error as exc:
            if exc.code in _MISSING_CODES:
                return False
            raise StorageUnavailableError() from exc
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def delete(self, key: str) -> None:
        self._ensure_bucket()
        try:
            self._client_obj().remove_object(self._bucket, key)
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def download_to(self, key: str, target: BinaryIO) -> None:
        self._ensure_bucket()
        client = self._client_obj()
        try:
            response = client.get_object(self._bucket, key)
            try:
                for chunk in response.stream(_CHUNK):
                    target.write(chunk)
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        from datetime import timedelta

        self._ensure_bucket()
        try:
            return self._client_obj().presigned_get_object(
                self._bucket, key, expires=timedelta(seconds=expires_seconds)
            )
        except Exception as exc:
            raise StorageUnavailableError() from exc


@lru_cache
def get_storage() -> ObjectStorage:
    """进程内单例；FastAPI 依赖与测试覆盖共用同一入口。"""
    return MinioStorage()
```

- [ ] **Step 6: 跑绿**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_storage.py -q
```
Expected: `10 passed`（若 `StorageUnavailableError` 未定义会先失败，先确认 Step 2 已改）。

- [ ] **Step 7: 提交**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/app/core/exceptions.py backend/app/core/storage.py backend/tests/test_storage.py .env.example
git commit -m "feat(s2-6): 对象存储适配器与上传配置"
```

---

### Task 2: 文件名清洗与类型检测

**Files:**
- Create: `backend/app/services/file_service.py`（本任务只实现规则函数）、`backend/tests/test_file_rules.py`

**Interfaces:**
- Produces: `sanitize_filename(name) -> str`、`allowed_extensions() -> list[str]`、`detect_type(filename) -> tuple[str, str]`、`check_magic(head: bytes, ext: str) -> None`、常量 `MAX_FILENAME_LENGTH = 200`。

- [ ] **Step 1: 写测试 `backend/tests/test_file_rules.py`**

```python
"""S2-6 文件名与类型规则。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import InvalidParamError
from app.services import file_service


def _settings(extensions: str = "pdf,docx,md,txt,png,jpg,jpeg", max_mb: int = 60):
    return SimpleNamespace(
        upload_allowed_extensions=extensions, upload_max_size_mb=max_mb
    )


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service, "get_settings", lambda: _settings())


def test_sanitize_filename_strips_path_traversal() -> None:
    assert file_service.sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_normalizes_backslashes() -> None:
    assert file_service.sanitize_filename(r"C:\Users\a\试卷.pdf") == "试卷.pdf"


def test_sanitize_filename_removes_control_chars() -> None:
    assert file_service.sanitize_filename("笔\x00记\n.md") == "笔记.md"


def test_sanitize_filename_truncates_but_keeps_extension() -> None:
    name = file_service.sanitize_filename("a" * 500 + ".pdf")
    assert len(name) == file_service.MAX_FILENAME_LENGTH
    assert name.endswith(".pdf")


def test_sanitize_filename_rejects_empty_and_dots() -> None:
    for bad in ("", "   ", ".", "..", "/", "\\\\"):
        with pytest.raises(InvalidParamError):
            file_service.sanitize_filename(bad)


def test_detect_type_is_case_insensitive() -> None:
    assert file_service.detect_type("A.PDF") == ("pdf", "application/pdf")


def test_detect_type_rejects_unknown_extension() -> None:
    with pytest.raises(InvalidParamError) as excinfo:
        file_service.detect_type("run.exe")
    assert "pdf" in excinfo.value.message


def test_detect_type_follows_configured_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service, "get_settings", lambda: _settings("pdf"))
    with pytest.raises(InvalidParamError):
        file_service.detect_type("note.md")


def test_check_magic_rejects_text_disguised_as_pdf() -> None:
    with pytest.raises(InvalidParamError):
        file_service.check_magic(b"not a pdf at all", "pdf")


def test_check_magic_accepts_png_signature() -> None:
    file_service.check_magic(b"\x89PNG\r\n\x1a\n" + b"rest", "png")


def test_check_magic_rejects_binary_text_file() -> None:
    with pytest.raises(InvalidParamError):
        file_service.check_magic(b"abc\x00def", "txt")


def test_check_magic_accepts_docx_zip_header() -> None:
    file_service.check_magic(b"PK\x03\x04rest", "docx")


def test_allowed_extensions_reads_config() -> None:
    assert file_service.allowed_extensions() == [
        "pdf", "docx", "md", "txt", "png", "jpg", "jpeg"
    ]
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_file_rules.py -q
```
Expected: `ImportError: cannot import name 'file_service'` 或 `AttributeError`。

- [ ] **Step 3: 实现规则部分**

```python
"""S2-6 文件上传服务（spec §7）。

文件名只做展示：对象键用内容哈希，路径穿越在源头就被砍掉。
类型靠「扩展名白名单 + 文件头 magic」双校验：只信扩展名会被改名绕过。
"""
from __future__ import annotations

import re

from app.core.config import get_settings
from app.core.exceptions import InvalidParamError

MAX_FILENAME_LENGTH = 200

# ext -> (mime, magic)；magic=None 表示文本类，仅拒绝 NUL
TYPE_TABLE: dict[str, tuple[str, bytes | None]] = {
    "pdf": ("application/pdf", b"%PDF-"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    "md": ("text/markdown", None),
    "txt": ("text/plain", None),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def allowed_extensions() -> list[str]:
    raw = get_settings().upload_allowed_extensions
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def sanitize_filename(name: str | None) -> str:
    raw = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _CONTROL.sub("", raw).strip().strip(".")
    if not cleaned or cleaned in {".", ".."}:
        raise InvalidParamError("文件名不合法")
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, _, ext = cleaned.rpartition(".")
        if not ext or len(ext) > 20:
            stem, ext = cleaned, ""
        keep = MAX_FILENAME_LENGTH - (len(ext) + 1 if ext else 0)
        cleaned = (stem[:keep] + f".{ext}") if ext else stem[:keep]
    return cleaned


def detect_type(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = allowed_extensions()
    if ext not in allowed or ext not in TYPE_TABLE:
        shown = "，".join(allowed) if allowed else "（未配置）"
        raise InvalidParamError(f"不支持的文件类型：{ext or '（无扩展名）'}（允许：{shown}）")
    return ext, TYPE_TABLE[ext][0]


def check_magic(head: bytes, ext: str) -> None:
    _, magic = TYPE_TABLE[ext]
    if magic is None:
        if b"\x00" in head[:4096]:
            raise InvalidParamError("文件内容与类型不符")
        return
    if not head.startswith(magic):
        raise InvalidParamError("文件内容与类型不符")
```

- [ ] **Step 4: 跑绿**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_file_rules.py -q
```
Expected: `13 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/file_service.py backend/tests/test_file_rules.py
git commit -m "feat(s2-6): 上传文件名与类型校验"
```

---

### Task 3: 上传与去重服务

**Files:**
- Modify: `backend/app/services/file_service.py`
- Create: `backend/tests/test_file_service.py`

**Interfaces:**
- Consumes: Task 1 的 `ObjectStorage`、Task 2 的规则函数。
- Produces: `upload_file(session, *, owner: User, upload: UploadFile, storage: ObjectStorage) -> tuple[File, bool]`、`get_file_status(session, *, file_id: int, viewer: User) -> File`。

- [ ] **Step 1: 写测试 `backend/tests/test_file_service.py`**

```python
"""S2-6 上传/去重/补偿（FakeSession + FakeStorage，不连库不连网）。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.core.exceptions import (
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    PayloadTooLargeError,
    StorageUnavailableError,
)
from app.models.file import File
from app.models.user import User
from app.models.user_relation import UserRelation
from app.services import file_service


class FakeSession:
    def __init__(
        self,
        *,
        existing: File | None = None,
        relation: int | None = None,
        commit_error: Exception | None = None,
        scalar_after_error: File | None = None,
    ) -> None:
        self.existing = existing
        self.relation = relation
        self.commit_error = commit_error
        self.scalar_after_error = scalar_after_error
        self.scalar_calls = 0
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is UserRelation:
            return self.relation
        self.scalar_calls += 1
        if self.scalar_calls > 1 and self.scalar_after_error is not None:
            return self.scalar_after_error
        return self.existing

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def get(self, entity: type, pk: int):
        return self.existing if entity is File else None

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 7
        instance.created_at = datetime.now(timezone.utc)


class FakeStorage:
    def __init__(self, *, object_present: bool = True, fail_put: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[tuple[str, int, str]] = []
        self.deletes: list[str] = []
        self.object_present = object_present
        self.fail_put = fail_put

    def put(self, key: str, data, *, size: int, content_type: str) -> None:  # noqa: ANN001
        if self.fail_put:
            raise StorageUnavailableError()
        self.puts.append((key, size, content_type))
        self.objects[key] = data.read()

    def exists(self, key: str) -> bool:
        return self.object_present or key in self.objects

    def delete(self, key: str) -> None:
        self.deletes.append(key)
        self.objects.pop(key, None)


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_a") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _file(*, owner_id: int = 1, sha256: str | None = None) -> File:
    record = File(
        user_id=owner_id,
        filename="试卷.pdf",
        mime="application/pdf",
        size=8,
        storage_path=f"uploads/{owner_id}/aa/{sha256 or 'x'*64}.pdf",
        sha256=sha256 or "x" * 64,
        parse_status="pending",
    )
    record.id = 5
    record.created_at = datetime.now(timezone.utc)
    return record


def _upload(content: bytes = b"%PDF-1.4\n", filename: str = "试卷.pdf") -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(
            upload_allowed_extensions="pdf,docx,md,txt,png,jpg,jpeg",
            upload_max_size_mb=60,
        ),
    )


def test_upload_new_file_writes_object_and_row() -> None:
    session, storage = FakeSession(), FakeStorage()
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    assert deduped is False
    assert record.user_id == 1
    assert record.sha256 == digest
    assert record.storage_path == f"uploads/1/{digest[:2]}/{digest}.pdf"
    assert record.size == 9
    assert record.parse_status == "pending"
    assert storage.puts == [(record.storage_path, 9, "application/pdf")]
    assert session.commits == 1


def test_upload_duplicate_reuses_row_without_put() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    existing = _file(sha256=digest)
    session, storage = FakeSession(existing=existing), FakeStorage()
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is existing, deduped) == (True, True)
    assert storage.puts == []
    assert session.added == []


def test_upload_duplicate_with_missing_object_reuploads() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    existing = _file(sha256=digest)
    session, storage = FakeSession(existing=existing), FakeStorage(object_present=False)
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is existing, deduped) == (True, False)
    assert len(storage.puts) == 1


def test_upload_oversize_raises_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(
            upload_allowed_extensions="pdf", upload_max_size_mb=0
        ),
    )
    with pytest.raises(PayloadTooLargeError) as excinfo:
        file_service.upload_file(
            FakeSession(), owner=_user(), upload=_upload(), storage=FakeStorage()
        )
    assert excinfo.value.code == 41300


def test_upload_rejects_bad_magic() -> None:
    with pytest.raises(InvalidParamError):
        file_service.upload_file(
            FakeSession(),
            owner=_user(),
            upload=_upload(b"plain text", "fake.pdf"),
            storage=FakeStorage(),
        )


def test_upload_rejects_unknown_extension() -> None:
    with pytest.raises(InvalidParamError):
        file_service.upload_file(
            FakeSession(), owner=_user(), upload=_upload(filename="run.exe"), storage=FakeStorage()
        )


def test_upload_storage_failure_does_not_insert() -> None:
    session = FakeSession()
    with pytest.raises(StorageUnavailableError):
        file_service.upload_file(
            session, owner=_user(), upload=_upload(), storage=FakeStorage(fail_put=True)
        )
    assert session.added == []


def test_upload_db_failure_deletes_object() -> None:
    storage = FakeStorage()
    session = FakeSession(commit_error=RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        file_service.upload_file(session, owner=_user(), upload=_upload(), storage=storage)
    assert len(storage.deletes) == 1
    assert session.rollbacks == 1


def test_upload_concurrent_conflict_returns_existing_without_delete() -> None:
    digest = hashlib.sha256(b"%PDF-1.4\n").hexdigest()
    winner = _file(sha256=digest)
    storage = FakeStorage()
    session = FakeSession(
        commit_error=IntegrityError("insert", {}, Exception("dup")),
        scalar_after_error=winner,
    )
    record, deduped = file_service.upload_file(
        session, owner=_user(), upload=_upload(), storage=storage
    )
    assert (record is winner, deduped) == (True, True)
    assert storage.deletes == []


def test_get_file_status_returns_own_file() -> None:
    record = _file()
    assert file_service.get_file_status(FakeSession(existing=record), file_id=5, viewer=_user()) is record


def test_get_file_status_missing_returns_404() -> None:
    with pytest.raises(NotFoundError):
        file_service.get_file_status(FakeSession(existing=None), file_id=5, viewer=_user())


def test_get_file_status_other_returns_403() -> None:
    with pytest.raises(ForbiddenError):
        file_service.get_file_status(
            FakeSession(existing=_file(owner_id=1), relation=None),
            file_id=5,
            viewer=_user(2, username="student_b"),
        )


def test_get_file_status_allows_bound_parent() -> None:
    record = _file(owner_id=1)
    viewer = _user(3, role="parent", username="parent_1")
    assert (
        file_service.get_file_status(
            FakeSession(existing=record, relation=10), file_id=5, viewer=viewer
        )
        is record
    )
```

- [ ] **Step 2: 跑测试确认红**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_file_service.py -q
```
Expected: `AttributeError: module 'app.services.file_service' has no attribute 'upload_file'`。

- [ ] **Step 3: 实现上传与查询**

在 `file_service.py` 追加（并把 `Session` / `File` / `User` 的 import 补上）：

```python
import hashlib
import tempfile

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.permissions import ensure_student_access
from app.core.storage import ObjectStorage
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
)
from app.models.file import File
from app.models.user import User

_CHUNK_SIZE = 1024 * 1024
_KEY_PREFIX = "uploads"


def _build_key(user_id: int, sha256: str, ext: str) -> str:
    return f"{_KEY_PREFIX}/{user_id}/{sha256[:2]}/{sha256}.{ext}"


def _too_large(limit_mb: int) -> PayloadTooLargeError:
    return PayloadTooLargeError(f"文件超过 {limit_mb}MB 上限")


def upload_file(
    session: Session, *, owner: User, upload: UploadFile, storage: ObjectStorage
) -> tuple[File, bool]:
    filename = sanitize_filename(upload.filename)
    ext, mime = detect_type(filename)
    limit = get_settings().upload_max_size_mb * 1024 * 1024

    digest = hashlib.sha256()
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
        first = True
        while True:
            chunk = upload.file.read(_CHUNK_SIZE)
            if not chunk:
                break
            if first:
                check_magic(chunk[:4096], ext)
                first = False
            size += len(chunk)
            if size > limit:
                raise _too_large(get_settings().upload_max_size_mb)
            digest.update(chunk)
            spool.write(chunk)
        if first:
            raise InvalidParamError("文件内容为空")
        sha256 = digest.hexdigest()
        key = _build_key(owner.id, sha256, ext)

        existing = session.scalar(
            select(File).where(File.user_id == owner.id, File.sha256 == sha256)
        )
        if existing is not None and storage.exists(key):
            return existing, True

        spool.seek(0)
        storage.put(key, spool, size=size, content_type=mime)
        if existing is not None:
            return existing, False

        record = File(
            user_id=owner.id,
            filename=filename,
            mime=mime,
            size=size,
            storage_path=key,
            sha256=sha256,
            parse_status="pending",
        )
        session.add(record)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            winner = session.scalar(
                select(File).where(File.user_id == owner.id, File.sha256 == sha256)
            )
            if winner is None:
                raise ConflictError("文件上传冲突，请重试")
            return winner, True
        except Exception:
            session.rollback()
            try:
                storage.delete(key)
            except Exception:  # 补偿删除失败不掩盖原始异常
                pass
            raise
        session.refresh(record)
        return record, False


def get_file_status(session: Session, *, file_id: int, viewer: User) -> File:
    record = session.get(File, file_id)
    if record is None:
        raise NotFoundError("文件不存在")
    if record.user_id != viewer.id:
        ensure_student_access(session, viewer, record.user_id)
    return record
```

注意：`ensure_student_access` 依赖 `session.scalar` 返回 `UserRelation`；测试的 FakeSession 已按实体分派。`IntegrityError` 从 `sqlalchemy.exc` 导入。

- [ ] **Step 4: 跑绿**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_file_service.py -q
```
Expected: `13 passed`

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/file_service.py backend/tests/test_file_service.py
git commit -m "feat(s2-6): 文件上传与去重服务"
```

---

### Task 4: 接口、schema 与全量回归

**Files:**
- Create: `backend/app/schemas/files.py`、`backend/app/api/v1/files.py`、`backend/tests/test_files_api.py`
- Modify: `backend/app/api/router.py`

**Interfaces:**
- Consumes: `file_service.upload_file` / `get_file_status`、`get_storage`、`require_role` / `get_current_user`。
- Produces: `POST /api/v1/files`、`GET /api/v1/files/{file_id}/parse-status`。

- [ ] **Step 1: `backend/app/schemas/files.py`**

```python
"""S2-6 文件出入参（API.md §3）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    mime: str
    size: int
    sha256: str
    parse_status: str
    created_at: datetime


class FileUploadOut(FileOut):
    deduped: bool


class FileStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    parse_status: str
```

- [ ] **Step 2: `backend/app/api/v1/files.py`**

```python
"""S2-6 文件上传与解析状态（API.md §3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.context import get_trace_id
from app.core.exceptions import AppError
from app.core.permissions import require_role
from app.core.storage import ObjectStorage, get_storage
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.files import FileOut, FileStatusOut, FileUploadOut
from app.services import file_service

router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "",
    status_code=201,
    response_model=Envelope[FileUploadOut],
    summary="上传文件（去重）",
)
def upload_file(
    response: Response,
    file: UploadFile | None = File(default=None, description="待上传文件"),
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Envelope[FileUploadOut]:
    if file is None or not file.filename:
        raise AppError("请求缺少 file 字段", code=40000, http_status=400)
    record, deduped = file_service.upload_file(
        session, owner=current_user, upload=file, storage=storage
    )
    response.status_code = 200 if deduped else 201
    base = FileOut.model_validate(record)
    data = FileUploadOut(**base.model_dump(), deduped=deduped)
    return Envelope(trace_id=get_trace_id(), data=data)


@router.get(
    "/{file_id}/parse-status",
    response_model=Envelope[FileStatusOut],
    summary="查询解析状态",
)
def get_parse_status(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[FileStatusOut]:
    record = file_service.get_file_status(session, file_id=file_id, viewer=current_user)
    return Envelope(trace_id=get_trace_id(), data=FileStatusOut.model_validate(record))
```

- [ ] **Step 3: `router.py` 挂载**

```python
from app.api.v1 import auth, files, notes

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(notes.router)
api_router.include_router(files.router)
```

- [ ] **Step 4: 写接口测试 `backend/tests/test_files_api.py`**

```python
"""S2-6 文件接口：TestClient + 依赖覆盖，不连库不连 MinIO。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import PayloadTooLargeError
from app.core.security import create_access_token
from app.core.storage import get_storage
from app.main import app
from app.models.file import File
from app.models.user import User
from app.models.user_relation import UserRelation
from app.services import file_service


class FakeSession:
    def __init__(self, *, user: User | None = None, record: File | None = None,
                 relation: int | None = None) -> None:
        self.user = user
        self.record = record
        self.relation = relation
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        if entity is UserRelation:
            return self.relation
        return self.record

    def get(self, entity: type, pk: int):
        return self.record if entity is File else None

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 11
        instance.created_at = datetime.now(timezone.utc)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []

    def put(self, key: str, data, *, size: int, content_type: str) -> None:  # noqa: ANN001
        self.puts.append(key)
        self.objects[key] = data.read()

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_a") -> User:
    user = User(
        username=username, password_hash="hash", nickname=f"测试用户_{user_id}",
        grade="高一", role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _record(*, owner_id: int = 1) -> File:
    record = File(
        user_id=owner_id, filename="试卷.pdf", mime="application/pdf", size=8,
        storage_path="uploads/1/aa/x.pdf", sha256="a" * 64, parse_status="pending",
    )
    record.id = 11
    record.created_at = datetime.now(timezone.utc)
    return record


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _wire(session: FakeSession, storage: FakeStorage | None = None) -> FakeStorage:
    store = storage or FakeStorage()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_storage] = lambda: store
    return store


def _pdf() -> tuple[str, bytes, str]:
    return ("file", ("试卷.pdf", BytesIO(b"%PDF-1.4\n"), "application/pdf"))


def test_upload_returns_201_and_deduped_false(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files={"file": _pdf()[1]}, headers=_headers(user))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["deduped"] is False
    assert data["parse_status"] == "pending"
    assert "storage_path" not in data


def test_upload_duplicate_returns_200_and_same_id(client: TestClient) -> None:
    user = _user()
    session = FakeSession(user=user, record=_record())
    storage = FakeStorage()
    storage.objects["uploads/1/aa/" + "a" * 64 + ".pdf"] = b"%PDF-1.4\n"
    _wire(session, storage)
    resp = client.post("/api/v1/files", files={"file": _pdf()[1]}, headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == 11
    assert resp.json()["data"]["deduped"] is True
    assert storage.puts == []


def test_upload_oversize_returns_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    from types import SimpleNamespace

    monkeypatch.setattr(
        file_service, "get_settings",
        lambda: SimpleNamespace(upload_allowed_extensions="pdf", upload_max_size_mb=0),
    )
    resp = client.post("/api/v1/files", files={"file": _pdf()[1]}, headers=_headers(user))
    assert resp.status_code == 413
    assert resp.json()["code"] == 41300


def test_upload_bad_extension_returns_422(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post(
        "/api/v1/files",
        files={"file": ("run.exe", BytesIO(b"MZ"), "application/octet-stream")},
        headers=_headers(user),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_upload_missing_field_returns_400(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", data={}, headers=_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == 40000


def test_upload_requires_token(client: TestClient) -> None:
    _wire(FakeSession())
    resp = client.post("/api/v1/files", files={"file": _pdf()[1]})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_upload_forbidden_for_teacher(client: TestClient) -> None:
    user = _user(role="teacher", username="teacher_1")
    _wire(FakeSession(user=user))
    resp = client.post("/api/v1/files", files={"file": _pdf()[1]}, headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_parse_status_returns_pending(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=_record()))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "id": 11, "filename": "试卷.pdf", "parse_status": "pending"
    }


def test_parse_status_missing_returns_404(client: TestClient) -> None:
    user = _user()
    _wire(FakeSession(user=user, record=None))
    resp = client.get("/api/v1/files/99/parse-status", headers=_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


def test_parse_status_other_user_returns_403(client: TestClient) -> None:
    user = _user(2, username="student_b")
    _wire(FakeSession(user=user, record=_record(owner_id=1), relation=None))
    resp = client.get("/api/v1/files/11/parse-status", headers=_headers(user))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300
```

- [ ] **Step 5: 跑接口测试 + 全量回归**

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_files_api.py -q
../.venv/Scripts/python.exe -m pytest -q
```
Expected: `10 passed`；全量 **368 passed, 1 warning**（322 + 10 + 13 + 13 + 10；若数字不同以实测为准）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/files.py backend/app/api/v1/files.py backend/app/api/router.py backend/tests/test_files_api.py
git commit -m "feat(s2-6): 文件上传与解析状态接口"
```

---

### Task 5: 真实 MinIO + Postgres 验收

**Files:** 无代码改动（发现问题回改前序任务）。

- [ ] **Step 1: 起服务**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
```
后台运行，验收完 kill。

- [ ] **Step 2: 造样本与 61MB 文件**

```bash
cd /tmp
../.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
Path("/tmp/s2_6_sample.pdf").write_bytes(
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
)
Path("/tmp/s2_6_big.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * (61 * 1024 * 1024))
print("sample", Path("/tmp/s2_6_sample.pdf").stat().st_size)
print("big", Path("/tmp/s2_6_big.pdf").stat().st_size)
PY
```
Expected: `sample 78` 左右、`big 63963140` 左右。

- [ ] **Step 3: 注册/登录**

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"file_a","password":"test-pass-123","nickname":"文件A","role":"student"}'
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"file_b","password":"test-pass-123","nickname":"文件B","role":"student"}'
TOKEN_A=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"file_a","password":"test-pass-123"}' | \
  /e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
TOKEN_B=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"file_b","password":"test-pass-123"}' | \
  /e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
echo "$TOKEN_A" > /tmp/token_file_a; echo "$TOKEN_B" > /tmp/token_file_b
echo "len_a=${#TOKEN_A} len_b=${#TOKEN_B}"
```

- [ ] **Step 4: 首次上传 + 重复上传 + 对象计数**

```bash
TOKEN_A=$(cat /tmp/token_file_a)
echo "== first =="
curl -s -w '\nHTTP=%{http_code}\n' -F "file=@/tmp/s2_6_sample.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
echo "== second =="
curl -s -w '\nHTTP=%{http_code}\n' -F "file=@/tmp/s2_6_sample.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select id, filename, mime, size, sha256, storage_path, parse_status from files;"
/e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe - <<'PY'
from minio import Minio
client = Minio("localhost:9000", access_key="study", secret_key="study123456", secure=False)
objects = list(client.list_objects("study-agent", prefix="uploads/", recursive=True))
print("object_count", len(objects))
for obj in objects:
    print(obj.object_name, obj.size)
PY
```
Expected: 第一次 `HTTP=201`、`deduped=false`；第二次 `HTTP=200`、`deduped=true` 且 `id` 相同；psql 只有 **1** 行；`object_count 1`。

- [ ] **Step 5: 61MB 拒绝 + parse-status + 越权**

```bash
TOKEN_A=$(cat /tmp/token_file_a); TOKEN_B=$(cat /tmp/token_file_b)
echo "== big file =="
curl -s -w '\nHTTP=%{http_code}\n' -F "file=@/tmp/s2_6_big.pdf;type=application/pdf" \
  -H "Authorization: Bearer $TOKEN_A" localhost:8000/api/v1/files
echo "== status by A =="
curl -s -w '\nHTTP=%{http_code}\n' localhost:8000/api/v1/files/1/parse-status \
  -H "Authorization: Bearer $TOKEN_A"
echo "== status by B =="
curl -s -w '\nHTTP=%{http_code}\n' localhost:8000/api/v1/files/1/parse-status \
  -H "Authorization: Bearer $TOKEN_B"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) from files;"
```
Expected: 61MB → **413/41300**；A 200 `pending`；B **403/40300**；`count` 仍为 1。

- [ ] **Step 6: 清理**

```bash
/e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe - <<'PY'
from minio import Minio
from minio.deleteobjects import DeleteObject
client = Minio("localhost:9000", access_key="study", secret_key="study123456", secure=False)
objects = list(client.list_objects("study-agent", prefix="uploads/", recursive=True))
if objects:
    errors = client.remove_objects(
        "study-agent", [DeleteObject(o.object_name) for o in objects]
    )
    for err in errors:
        print("delete_error", err)
print("remaining", len(list(client.list_objects("study-agent", prefix="uploads/", recursive=True))))
PY
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "delete from files where user_id in (select id from users where username like 'file\_%');
   delete from users where username like 'file\_%';"
docker exec study-agent-postgres psql -U study -d study_agent -c \
  "select (select count(*) from files) files, (select count(*) from users) users;"
```
Expected: `remaining 0`；files=0、users=0。

- [ ] **Step 7: 记录证据**

把 Step 2–6 的真实输出摘要写入 plan「执行记录」与 PROGRESS 变更日志（数字必须实测，含 object_count、HTTP 码、错误 message）。

---

### Task 6: 文档同步与收尾

**Files:**
- Modify: `docs/API.md`（§3 两接口定稿、§12 缺口、§13 新增 41300）
- Modify: `docs/SCHEMA.md`（§4.1 `storage_path` 键规则、`parse_status` 现状）
- Modify: `AGENTS.md`（§9.2 上传/存储约定、§9.6 存储锚点）
- Modify: `docs/DECISIONS.md`（D-026）
- Modify: `docs/PROGRESS.md`（状态、清单、遗留、日志）
- Modify: `docs/spec/s2-6-file-upload.md`（状态行）
- Modify: `docs/plan/s2-6-file-upload.md`（执行记录）

- [ ] **Step 1: API.md §3 重写**

按 spec §5 写两个接口：权限、请求、201/200 语义、出参字段、错误码（413/41300、422/42200、400/40000、403/40300、500/50000）；§12 笔记行下方补「文件列表/下载/删除、签名 URL 接口」缺口；§13 表加 `| 41300 | 文件过大 | 413 |`。

- [ ] **Step 2: SCHEMA.md**

§4.1 `storage_path` 说明改为「MinIO 对象键：`uploads/{user_id}/{sha256[:2]}/{sha256}{ext}` ✅（S2-6 定稿）」；`parse_status` 行标注「S2-6 只写 `pending`；`parsing/failed` 与 error 信息由 S2-8 扩展」。

- [ ] **Step 3: AGENTS.md**

§9.2 加一条：上传必须流式、先校验后落库、对象键内容寻址、错误统一 `AppError`；§9.6 加存储锚点：

```markdown
- 对象存储锚点：backend/app/core/storage.py（`ObjectStorage` 协议 + `MinioStorage` 懒连接/懒建桶 + `get_storage()` 单例；SDK 异常统一 `StorageUnavailableError`；路由用 `Depends(get_storage)`，测试注入假实现）
- 文件上传锚点：backend/app/services/file_service.py（`sanitize_filename` 砍路径、`detect_type` + `check_magic` 双校验、流式哈希、`uq(user_id, sha256)` 去重、并发冲突复用赢家、库失败补偿删对象）
```

- [ ] **Step 4: DECISIONS.md 追加 D-026**

11 条决策（依赖、201/200、类型与 60MB、内容寻址键、不信任客户端头、413 码、冲突不删对象、补偿删除、parse-status 权限、仅 student、协议+适配器）+ 实测证据 + 已知限制（spec §12）。

- [ ] **Step 5: PROGRESS.md**

1. 当前状态：最近完成 S2-6，下一步 S2-7；
2. 清单 S2-6 打 `[x]`；
3. 遗留表更新：删除或改写第 13 行「files 有表无上传接口」，新增「无上传限流/病毒扫描」「无文件列表/下载/删除」「`parse_status` 只有 pending（S2-8 扩展）」「上传需读完整文件才能去重」；
4. 变更日志 `### 2026-10-26（S2-6）`：交付、决策、验收证据（pytest 数字 + curl/psql/python-minio 输出）、已知限制、文档同步。

- [ ] **Step 6: 全量回归 + 提交**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd .. && git status --short
git add docs/ AGENTS.md
git commit -m "docs(s2-6): 文件上传契约、决策与进度同步"
```

---

## Self-Review

**1. Spec coverage**

| spec 章节 | 覆盖任务 |
|---|---|
| §1 目标（流式/去重/对象键/parse-status/协议） | Task 1、3、4 |
| §2 范围（做/不做） | Task 1–4 + 文档声明 |
| §3 决策 1–11 | Task 1（1、6）、3（4、7、8）、4（2、9、10）、1+4（11） |
| §5 接口契约 | Task 4 + Task 6 API.md |
| §6 存储抽象 | Task 1 |
| §7 服务契约 | Task 2、3 |
| §8 配置项 | Task 1 Step 2 |
| §9 测试计划 | Task 1/2/3/4 |
| §10 真实验收 | Task 5 |
| §11 文档同步 | Task 6 |
| §12 已知限制 | Task 6 Step 4–5 |

**2. Placeholder scan**：唯一占位是 Task 1 的 `<minio版本>` / `<multipart版本>`，同一步给了取值命令；其余代码/命令/预期输出均为可执行内容。

**3. Type consistency**：`ObjectStorage.put(key, data, *, size, content_type)` 在 Task 1、3、4 与测试假实现中签名一致；`upload_file(session, *, owner, upload, storage)` 在 Task 3/4 一致；`FileOut.deduped` 由 `FileUploadOut` 承载；`get_storage()` 同时被路由 `Depends` 与测试覆盖使用；错误类型 `PayloadTooLargeError` / `StorageUnavailableError` / `ConflictError` / `InvalidParamError` / `NotFoundError` 均来自 `app.core.exceptions`。

## 执行记录

**安装版本**：`minio==7.2.20`、`python-multipart==0.0.32`（华为云镜像，已写入 requirements.txt）。

**提交列表**

1. `093c1eb feat(s2-6): 对象存储适配器与上传配置`
2. `ad0986a feat(s2-6): 上传文件名与类型校验`
3. `1aa9a76 feat(s2-6): 文件上传与去重服务`
4. `f47a36d feat(s2-6): 文件上传与解析状态接口`
5. `docs(s2-6): 文件上传契约、决策与进度同步`

**pytest**：Task 1 `10 passed`；Task 2 `13 passed`；Task 3 `13 passed`；Task 4 接口 `10 passed`；全量 **368 passed, 1 warning**（322 + 46）。

**真实 MinIO + Postgres 验收（实测输出）**

| 步骤 | 实测 |
|---|---|
| 样本 | `s2_6_sample.pdf` 77 字节；`s2_6_big.pdf` 63,963,145 字节（61MB+） |
| 首次上传 | `HTTP=201`，`id=1`、`size=77`、`sha256=68d3dbe2…d56`、`parse_status=pending`、`deduped=false` |
| 重复上传 | `HTTP=200`，同 `id=1`、`deduped=true` |
| psql | `files` 仅 1 行；`storage_path=uploads/8/68/68d3dbe2….pdf`、`user_id=8` |
| MinIO | `object_count 1`；对象 `uploads/8/68/<sha256>.pdf` 77 字节 |
| 文本类 | `.md` 上传 → `HTTP=201`、`mime=text/markdown`、`size=29` |
| 61MB | `HTTP=413`，`{"code":41300,"message":"文件超过 60MB 上限"}`；files 仍 1 行 |
| parse-status | A → `HTTP=200` `pending`；B → `HTTP=403` `{"code":40300,"message":"无权访问该资源"}` |
| 清理 | 对象 `remaining 0`；`files=0`、`users=0`；`.verify_tmp` 已删 |

**与 plan 的偏差**

1. `minio` 7.2.20 的 `S3Error.__init__` 是 `(response, code, message, resource, request_id, host_id)`，plan 里的位置参数构造会得到错误 `exc.code`；实现与测试改为关键字构造（已回填上文代码）。
2. `b"%PDF-1.4\n"` 是 9 字节，plan 断言 `size == 8` 有误；实现后按实测改 9（上文代码已改）。
3. `tests/test_files_api.py` 的重复上传用例需要用 `hashlib.sha256(_PDF_BYTES)` 计算真实对象键后播种 `FakeStorage`，否则 `storage.exists(key)` 为假会走成「行在、对象缺」分支。
4. 上传路由显式 `status_code=201` 写进装饰器（plan 只在处理函数里改 `response.status_code`），OpenAPI 文档与实际首次响应一致。

**遗留**：见 D-026 与 PROGRESS 遗留 14–17。