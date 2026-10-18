# S1-3 Embedding 与 pgvector 入库 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 S1-2 的切片结果批量向量化并写入 `note_chunks`，建 HNSW 向量索引与 GIN 全文索引，跑通「解析→切片→向量化→入库→SQL 验收」真实链路。

**Architecture:** Embedding 走 `ai/embedding/` 适配器（OpenAI 兼容 / DashScope v4 / 本地占位）；jieba 分词封在 `utils/zh_tokenizer.py`；入库编排收在 `services/indexing.py`；`models/note_chunk.py` 与首个 Alembic 迁移同源；`scripts/index_demo.py` 只负责 CLI 与打印。

**Tech Stack:** Python 3.11（`.venv`）、SQLAlchemy 2.0、Alembic、psycopg 3、pgvector、jieba、httpx、pytest。

**Spec:** `docs/spec/s1-3-embedding.md`（执行者两份都要读；spec §4–§7 是规则依据）。

## Global Constraints

- 解释器 `E:\BiShe-AIStudy\study-agent\.venv\Scripts\python.exe`；pip 走华为云镜像
- 测试一律从 `backend/` 目录跑 `python -m pytest`（`-m` 才会把 cwd 加进 sys.path）
- 阶段 1 命令行阶段，**不动 API.md**；SCHEMA 只把 §0 维度从 ⚠ 改为 ✅，并补一行「FK 于 S2-1 补」说明
- 首个迁移**只建 note_chunks**，不加外键；`note_id/user_id/source_file_id` 为普通 BIGINT
- Embedding 批大小默认 **10**（DashScope v4 单次最多 10 行，任务卡 32 条/次不成立）
- 所有 Embedding 调用只走 `ai/` 层；业务层只 import 门面；Key 只从 Settings 读，禁止打印/提交
- 测试零真实网络：httpx 用 `MockTransport`；DB 集成放在 Task 7 真实验收，不进 pytest
- 本项目惯例：**整卡一个提交** `feat(s1-3)`，各任务不单独 commit
- 所有函数签名带类型标注；注释只写「为什么」；常量集中模块顶部
- 不引入 sentence-transformers / FlagEmbedding / openai SDK；不做增量索引产品化（S3-1）

---

### Task 1: 依赖安装 + 配置 + DB 基座

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/core/db.py`
- Modify: `.env.example`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: Settings 新字段 `embedding_provider / embedding_api_key / embedding_base_url / embedding_model / embedding_dim / embedding_batch_size / embedding_timeout_seconds / embedding_max_retries / embedding_price_per_million`
- Produces: `app.core.db.Base`、`get_engine()`、`get_session_factory()`、`new_session()`

- [ ] **Step 1: 安装五个依赖并记录实测版本**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple `
  sqlalchemy alembic "psycopg[binary]" jieba pgvector
.\.venv\Scripts\python.exe -m pip show sqlalchemy alembic psycopg jieba pgvector | Select-String "^Name:|^Version:"
```

Expected: 五组 Name/Version 全部打印，无报错。记下版本号供 Step 2 使用。

- [ ] **Step 2: requirements.txt 追加钉版依赖**

在文件末尾追加（版本号**必须**用 Step 1 实测值，禁止照抄本文档）：

```text
# --- S1-3 数据库与向量化（任务卡点名；版本以 2026-10-19 实测为准）---
sqlalchemy==<Step 1 实测版本>
alembic==<Step 1 实测版本>
psycopg[binary]==<Step 1 实测版本>
jieba==<Step 1 实测版本>
pgvector==<Step 1 实测版本>
```

- [ ] **Step 3: 写失败测试** `backend/tests/test_config.py`

```python
"""S1-3 配置测试：Embedding 默认值与 Key 别名（spec §9.1）。"""
from __future__ import annotations

from app.core.config import Settings


def test_embedding_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_provider == "dashscope"
    assert s.embedding_model == "text-embedding-v4"
    assert s.embedding_dim == 1024
    assert s.embedding_batch_size == 10  # 厂商硬上限，不是任务卡的 32
    assert s.embedding_price_per_million == 0.5


def test_embedding_key_accepts_dashscope_alias(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-dashscope"
    assert "sk-test-dashscope" not in repr(s)


def test_embedding_key_empty_embedding_falls_back_to_dashscope(monkeypatch) -> None:
    """真实 .env 常同时有空的 EMBEDDING_API_KEY= 与 DASHSCOPE_API_KEY=。"""
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-fallback")
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-fallback"


def test_embedding_key_accepts_embedding_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test-embedding")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-embedding"


def test_embedding_key_embedding_env_wins_when_both_set(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test-explicit")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-explicit"
```

- [ ] **Step 4: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```

Expected: FAIL（`AttributeError` 或断言失败，字段尚不存在）。

- [ ] **Step 5: 改 `backend/app/core/config.py`**

在 LLM 段之后追加：

```python
    # --- Embedding（S1-3；厂商 API，禁止本地大模型依赖）---
    embedding_provider: Literal["dashscope", "openai_compat", "local"] = "dashscope"
    # 两个字段分开收，空值回退：用户常只填标准名 DASHSCOPE_API_KEY
    embedding_api_key: str = Field(default="", repr=False)
    dashscope_api_key: str = Field(default="", repr=False)
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embedding_batch_size: int = 10  # DashScope v4 单次最多 10 行
    embedding_timeout_seconds: float = 60.0
    embedding_max_retries: int = 4
    # 元/百万 token（0.0005 元/千 token）；只用于估算展示，不写死调用逻辑
    embedding_price_per_million: float = 0.5

    @model_validator(mode="after")
    def _fallback_dashscope_key(self) -> "Settings":
        """EMBEDDING_API_KEY 为空时回退 DASHSCOPE_API_KEY。

        为什么不用 AliasChoices：.env 里 EMBEDDING_API_KEY= 是空字符串也算「已设置」，
        会导致用户只填标准名时反而取到空 Key。
        """
        if not self.embedding_api_key:
            self.embedding_api_key = self.dashscope_api_key
        return self
```

顶部 import 改为：

```python
from pydantic import Field, model_validator
```

- [ ] **Step 6: 新建 `backend/app/core/db.py`**

```python
"""SQLAlchemy 基座：Engine/Session/Base 的唯一入口（S1-3 首次接入数据库）。"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """所有 ORM 模型的基类；Alembic 的 target_metadata 指向它的 metadata。"""


def get_engine() -> Engine:
    """惰性建引擎：import 模型/跑纯单测时不触发任何数据库连接。"""
    global _engine
    if _engine is None:
        # hide_parameters=True：异常信息里不出现连接参数（含密码）
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def new_session() -> Session:
    """CLI/Worker 用；调用方负责 `with new_session() as session:` 关闭。"""
    return get_session_factory()()
```

- [ ] **Step 7: `.env.example` 追加 Embedding 段**

```dotenv
# ===== Embedding（S1-3；Key 只放 .env，禁止提交）=====
EMBEDDING_PROVIDER=dashscope
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
EMBEDDING_TIMEOUT_SECONDS=60
EMBEDDING_MAX_RETRIES=4
EMBEDDING_PRICE_PER_MILLION=0.5
```

- [ ] **Step 8: 跑测试确认通过**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```

Expected: `5 passed`（默认值 + 两个 Key 名 + 空值回退 + 显式名优先）。

---

### Task 2: Embedding 适配器（TDD，零真实网络）

**Files:**
- Create: `backend/app/ai/embedding/base.py`、`errors.py`、`openai_compat.py`、`local.py`、`__init__.py`
- Delete: `backend/app/ai/embedding/.gitkeep`
- Test: `backend/tests/test_embedding_client.py`

**Interfaces:**
- Produces: `BatchStats(batch_index, batch_count, batch_size, tokens, latency_ms)`
- Produces: `EmbeddingClient(model, dim, usage_tokens, request_count, encode(texts, *, on_batch=None))`
- Produces: `EmbeddingError(message, *, provider, status_code, retryable)`
- Produces: `OpenAICompatibleEmbeddingClient(...)`、`LocalEmbeddingClient()`、`get_embedding_client()`

- [ ] **Step 1: 写失败测试** `backend/tests/test_embedding_client.py`

```python
"""S1-3 Embedding 适配器测试：分批/重试/维度/Key 不泄漏（spec §4/§10）。"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.embedding.base import BatchStats
from app.ai.embedding.errors import EmbeddingError
from app.ai.embedding.local import LocalEmbeddingClient
from app.ai.embedding.openai_compat import OpenAICompatibleEmbeddingClient


def _client(handler: Callable[[httpx.Request], httpx.Response], **kwargs) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        api_key="sk-secret-test",
        base_url="https://example.invalid/v1",
        model="fake-embed",
        dim=4,
        batch_size=10,
        max_retries=kwargs.pop("max_retries", 0),
        sleep=kwargs.pop("sleep", lambda _s: None),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _ok_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    items = []
    for i, text in enumerate(body["input"]):
        items.append({"embedding": [float(text[1:])] * 4, "index": i})
    return httpx.Response(200, json={"data": items, "usage": {"total_tokens": len(items) * 3}})


def test_encode_batches_and_preserves_order() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return _ok_response(request)

    client = _client(handler)
    vectors = client.encode([f"t{i}" for i in range(25)])
    assert calls == [10, 10, 5]
    assert [int(v[0]) for v in vectors] == list(range(25))
    assert len(vectors) == 25
    assert client.usage_tokens == 75


def test_on_batch_reports_each_batch() -> None:
    stats: list[BatchStats] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response(request)

    client = _client(handler)
    client.encode([f"t{i}" for i in range(25)], on_batch=stats.append)
    assert [(s.batch_index, s.batch_size) for s in stats] == [(0, 10), (1, 10), (2, 5)]


def test_429_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "rate"}})
        return _ok_response(request)

    client = _client(handler, max_retries=1, sleep=sleeps.append)
    vectors = client.encode(["t0"])
    assert len(vectors) == 1
    assert calls["n"] == 2
    assert sleeps == [2.0]  # 尊重 Retry-After


def test_retry_exhausted_raises_embedding_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "rate"}})

    client = _client(handler, max_retries=2)
    with pytest.raises(EmbeddingError) as exc:
        client.encode(["t0"])
    assert calls["n"] == 3
    assert exc.value.retryable is True
    assert "sk-secret-test" not in str(exc.value)


def test_401_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = _client(handler, max_retries=3)
    with pytest.raises(EmbeddingError):
        client.encode(["t0"])
    assert calls["n"] == 1


def test_dimension_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}], "usage": {"total_tokens": 1}})

    client = _client(handler)
    with pytest.raises(EmbeddingError, match="维度"):
        client.encode(["t0"])


def test_empty_input_sends_no_request() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok_response(request)

    client = _client(handler)
    assert client.encode([]) == []
    assert calls["n"] == 0


def test_repr_hides_key() -> None:
    client = _client(_ok_response)
    assert "sk-secret-test" not in repr(client)
    assert "sk-secret-test" not in str(client)


def test_local_client_is_placeholder() -> None:
    with pytest.raises(NotImplementedError, match="占位"):
        LocalEmbeddingClient().encode(["x"])
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_embedding_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ai.embedding.base'`。

- [ ] **Step 3: 实现 `base.py` 与 `errors.py`**

`backend/app/ai/embedding/base.py`：

```python
"""Embedding 适配器契约：可替换厂商，业务层只依赖这个抽象（spec §4）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BatchStats:
    """单批进度：给 demo 打印与日志用，不参与返回向量。"""

    batch_index: int
    batch_count: int
    batch_size: int
    tokens: int
    latency_ms: int


class EmbeddingClient(ABC):
    def __init__(self, *, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self.usage_tokens = 0  # 累计 token，服务层做差值得本次用量
        self.request_count = 0  # 含重试的 HTTP 请求数

    @abstractmethod
    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        """文本列表 → 向量列表；顺序必须与输入一致。"""
```

`backend/app/ai/embedding/errors.py`：

```python
"""Embedding 专用异常：不携带 Key，不吞厂商错误上下文。"""
from __future__ import annotations


class EmbeddingError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "openai_compat",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
```

- [ ] **Step 4: 实现 `openai_compat.py`**

```python
"""OpenAI 兼容 Embedding 适配器：默认服务 DashScope（spec §4.2）。

为什么手写重试而不是用 openai SDK：项目只依赖 httpx，重试/退避/维度校验
需要完全可控；SDK 会引入额外依赖与隐式重试。
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.errors import EmbeddingError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dim: int,
        batch_size: int = 10,
        timeout: float = 60.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(model=model, dim=dim)
        if not api_key:
            raise EmbeddingError(
                "EMBEDDING_API_KEY / DASHSCOPE_API_KEY 未配置：请在仓库根 .env 填入 Key（spec §9.1）",
                provider="openai_compat",
            )
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleEmbeddingClient(model={self.model!r}, dim={self.dim}, "
            f"url={self._url!r})"
        )

    def close(self) -> None:
        self._http.close()

    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        batches = [texts[i : i + self._batch_size] for i in range(0, len(texts), self._batch_size)]
        vectors: list[list[float]] = []
        for batch_index, batch in enumerate(batches):
            started = time.perf_counter()
            payload = self._post_with_retry(batch, batch_index=batch_index)
            vectors.extend(self._parse_vectors(payload, expected=len(batch)))
            latency_ms = int((time.perf_counter() - started) * 1000)
            tokens = int((payload.get("usage") or {}).get("total_tokens", 0))
            self.usage_tokens += tokens
            logger.info(
                "embedding_call",
                extra={
                    "scene": "embed",
                    "model": self.model,
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                },
            )
            if on_batch is not None:
                on_batch(
                    BatchStats(
                        batch_index=batch_index,
                        batch_count=len(batches),
                        batch_size=len(batch),
                        tokens=tokens,
                        latency_ms=latency_ms,
                    )
                )
        return vectors

    def _post_with_retry(self, batch: list[str], *, batch_index: int) -> dict:
        payload = {
            "model": self.model,
            "input": batch,
            "dimensions": self.dim,
            "encoding_format": "float",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise EmbeddingError(
                        f"Embedding 网络错误（重试耗尽）：{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                delay = self._backoff(attempt, None)
                logger.warning(
                    "embedding_retry",
                    extra={"attempt": attempt + 1, "reason": type(exc).__name__, "delay_s": delay},
                )
                self._sleep(delay)
                continue
            self.request_count += 1
            if response.status_code < 400:
                return self._json_or_raise(response)
            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    raise EmbeddingError(
                        f"Embedding 请求重试耗尽（HTTP {response.status_code}）",
                        status_code=response.status_code,
                        retryable=True,
                    )
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "embedding_retry",
                    extra={
                        "attempt": attempt + 1,
                        "status": response.status_code,
                        "delay_s": delay,
                    },
                )
                self._sleep(delay)
                continue
            raise EmbeddingError(
                f"Embedding 请求失败：HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
                retryable=False,
            )
        raise EmbeddingError("Embedding 请求失败：未知重试状态", retryable=False)

    @staticmethod
    def _json_or_raise(response: httpx.Response) -> dict:
        try:
            return response.json()
        except ValueError as exc:
            raise EmbeddingError("Embedding 响应不是合法 JSON", retryable=False) from exc

    def _parse_vectors(self, payload: dict, *, expected: int) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingError(
                f"Embedding 返回条数不符：期望 {expected}，实际 {len(data) if isinstance(data, list) else '非列表'}",
                retryable=False,
            )
        items = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in items:
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dim:
                actual = len(vector) if isinstance(vector, list) else "非列表"
                raise EmbeddingError(
                    f"Embedding 维度不符：期望 {self.dim}，实际 {actual}（spec §4.4 停止并报告）",
                    retryable=False,
                )
            vectors.append([float(value) for value in vector])
        return vectors

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        base = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
        return base + random.uniform(0, base * 0.25)
```

- [ ] **Step 5: 实现 `local.py` 与门面 `__init__.py`**

`backend/app/ai/embedding/local.py`：

```python
"""本地 Embedding 占位：后期成本优化时再填（spec §4.1）。

本期明确不引入 sentence-transformers / FlagEmbedding（AGENTS §2），
接口先占位，保证切换厂商不动业务层。
"""
from __future__ import annotations

from collections.abc import Callable

from app.ai.embedding.base import BatchStats, EmbeddingClient


class LocalEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(model="local", dim=0)

    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        raise NotImplementedError("LocalEmbeddingClient 为占位实现：后期成本优化时再填（spec §4.1）")
```

`backend/app/ai/embedding/__init__.py`：

```python
"""Embedding 门面：全项目唯一获取客户端的入口（spec §4）。"""
from __future__ import annotations

from functools import lru_cache

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.errors import EmbeddingError
from app.ai.embedding.local import LocalEmbeddingClient
from app.ai.embedding.openai_compat import OpenAICompatibleEmbeddingClient
from app.core.config import get_settings

__all__ = [
    "BatchStats",
    "EmbeddingClient",
    "EmbeddingError",
    "LocalEmbeddingClient",
    "OpenAICompatibleEmbeddingClient",
    "get_embedding_client",
]


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.embedding_provider == "local":
        return LocalEmbeddingClient()
    return OpenAICompatibleEmbeddingClient(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        timeout=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
```

- [ ] **Step 6: 跑测试确认通过**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_embedding_client.py -v
```

Expected: `9 passed`。若有失败，改实现，**禁止改断言迁就实现**。

---

### Task 3: 中文分词与 tsquery 工具（TDD）

**Files:**
- Create: `backend/app/utils/zh_tokenizer.py`、`backend/app/utils/math_dict.txt`
- Modify: `backend/app/utils/__init__.py`（若无则新建空文件）
- Delete: `backend/app/utils/.gitkeep`
- Test: `backend/tests/test_zh_tokenizer.py`

**Interfaces:**
- Produces: `tokenize_zh(text) -> list[str]`、`join_for_tsv(text) -> str`、`build_tsquery(text) -> str`

- [ ] **Step 1: 写失败测试** `backend/tests/test_zh_tokenizer.py`

```python
"""S1-3 中文分词工具测试：jieba 切词与 tsquery 安全（spec §6/§10）。"""
from __future__ import annotations

from app.utils.zh_tokenizer import build_tsquery, join_for_tsv, tokenize_zh


def test_tokenize_zh_splits_chinese_words() -> None:
    tokens = tokenize_zh("函数的单调性：设 f(x) 在区间 D 内。")
    assert "函数" in tokens
    assert "单调性" in tokens
    assert "：" not in tokens
    assert "。" not in tokens
    assert all(" " not in token for token in tokens)


def test_tokenize_zh_filters_tsquery_operators() -> None:
    assert "&" not in tokenize_zh("函数 & 单调性")
    assert "|" not in tokenize_zh("函数 | 单调性")
    assert "(" not in tokenize_zh("f(x)")
    assert ")" not in tokenize_zh("f(x)")


def test_tokenize_zh_lowercases_latin() -> None:
    assert tokenize_zh("Function") == ["function"]


def test_tokenize_zh_empty_and_punctuation_only() -> None:
    assert tokenize_zh("") == []
    assert tokenize_zh("（）！？，。；：") == []


def test_join_for_tsv_uses_single_spaces() -> None:
    joined = join_for_tsv("函数的 单调性")
    assert "  " not in joined
    assert "函数" in joined
    assert "单调性" in joined


def test_build_tsquery_is_safe_and_ands_tokens() -> None:
    query = build_tsquery("函数的单调性")
    assert " & " in query
    for unsafe in ("&", "|", "!", "(", ")", ":", "*", "'"):
        if unsafe != "&":
            assert unsafe not in query
    assert build_tsquery("") == ""
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_zh_tokenizer.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.utils.zh_tokenizer'`。

- [ ] **Step 3: 实现**

`backend/app/utils/__init__.py` 保持空文件（或已有内容不动）。
`backend/app/utils/zh_tokenizer.py`：

```python
"""中文分词工具：jieba 切词后写入 tsv，查询侧复用同一函数（spec §6）。

为什么不用 to_tsquery('chinese', ...)：PostgreSQL 没有中文内置分词；
为什么不用 bigram：SCHEMA §9 明确精度不如分词。
"""
from __future__ import annotations

import re
from pathlib import Path

import jieba

# jieba 默认词典会把「单调性」切成「单调/性」，导致领域检索词被拆碎；
# 用标准 userdict 机制补高中数学高频词（不是自写分词逻辑）
_DICT_PATH = Path(__file__).with_name("math_dict.txt")
if _DICT_PATH.exists():
    jieba.load_userdict(str(_DICT_PATH))

# 只保留中文/字母/数字/下划线；tsquery 操作符与标点一律丢弃，避免拼出非法查询
_TOKEN_RE = re.compile(r"^[\w\u4e00-\u9fff]+$", re.UNICODE)


def tokenize_zh(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    tokens: list[str] = []
    for raw in jieba.cut(text, cut_all=False):
        token = raw.strip().lower()
        if token and _TOKEN_RE.match(token):
            tokens.append(token)
    return tokens


def join_for_tsv(text: str) -> str:
    """写入侧：空格连接的词串，交给 to_tsvector('simple', ...)。"""
    return " ".join(tokenize_zh(text))


def build_tsquery(text: str) -> str:
    """查询侧：token 用 & 连接；空文本返回空串，调用方跳过全文查询。"""
    return " & ".join(tokenize_zh(text))
```

`backend/app/utils/math_dict.txt`：45 个高中数学高频词，每行 `词 100000`，至少包含
`单调性 / 定义域 / 值域 / 奇偶性 / 周期性 / 导数 / 极值 / 等差数列 / 等比数列 / 圆锥曲线`
（实测默认 jieba 会把「单调性」切成「单调/性」，任务卡验收 SQL 会 0 命中）。

- [ ] **Step 4: 先打印一次真实分词，确认断言与实际一致**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -c "from app.utils.zh_tokenizer import tokenize_zh; print(tokenize_zh('函数的单调性：设 f(x) 在区间 D 内。'))"
```

Expected: 列表中包含 `函数`、`单调性`。若 jieba 把 `单调性` 切成别的形态，调整**测试断言**到真实分词（分词器是成熟库，不改它的策略），并把实际输出记入 spec §6 回填。

- [ ] **Step 5: 跑测试确认通过**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_zh_tokenizer.py -v
```

Expected: `7 passed`（含领域词典用例）。

---

### Task 4: NoteChunk 模型 + Alembic 首个迁移

**Files:**
- Create: `backend/app/models/note_chunk.py`、`backend/app/models/__init__.py`
- Delete: `backend/app/models/.gitkeep`
- Create: `backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`、`backend/alembic/versions/0001_create_note_chunks.py`
- Test: `backend/tests/test_note_chunk_model.py`

**Interfaces:**
- Produces: `NoteChunk`（表 `note_chunks`）、`app.models.Base` 可被 Alembic 导入
- Produces: Alembic revision `0001_s1_3`，`upgrade head` 建表 + 扩展 + 三个索引

- [ ] **Step 1: 写失败测试** `backend/tests/test_note_chunk_model.py`

```python
"""S1-3 模型契约测试：字段/可空性/索引与 SCHEMA §4.3 一致（spec §5）。"""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from app.models.note_chunk import NoteChunk

_EXPECTED_COLUMNS = {
    "id",
    "note_id",
    "user_id",
    "chunk_index",
    "content",
    "token_count",
    "chunk_type",
    "heading_path",
    "embedding",
    "tsv",
    "source_file_id",
    "page_no",
    "bbox_json",
}


def test_table_name_and_columns() -> None:
    assert NoteChunk.__tablename__ == "note_chunks"
    assert set(NoteChunk.__table__.columns.keys()) == _EXPECTED_COLUMNS


def test_embedding_is_vector_1024() -> None:
    embedding = NoteChunk.__table__.columns["embedding"]
    assert isinstance(embedding.type, Vector)
    assert embedding.type.dim == 1024
    assert embedding.nullable is False


def test_tsv_and_jsonb_types() -> None:
    assert isinstance(NoteChunk.__table__.columns["tsv"].type, TSVECTOR)
    assert isinstance(NoteChunk.__table__.columns["bbox_json"].type, JSONB)


def test_nullable_flags_match_schema() -> None:
    cols = NoteChunk.__table__.columns
    for name in ("note_id", "user_id", "chunk_index", "content", "token_count", "embedding"):
        assert cols[name].nullable is False
    for name in ("chunk_type", "heading_path", "tsv", "source_file_id", "page_no", "bbox_json"):
        assert cols[name].nullable is True


def test_unique_and_indexes() -> None:
    table = NoteChunk.__table__
    uniques = {c.name for c in table.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_note_chunks_note_chunk_index" in uniques
    index_names = {idx.name for idx in table.indexes}
    assert {"ix_note_chunks_user_id", "ix_note_chunks_tsv_gin", "ix_note_chunks_embedding_hnsw"} <= index_names


def test_id_is_bigint() -> None:
    assert isinstance(NoteChunk.__table__.columns["id"].type, BigInteger)
    assert isinstance(NoteChunk.__table__.columns["chunk_index"].type, Integer)
    assert isinstance(NoteChunk.__table__.columns["content"].type, Text)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_note_chunk_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.models.note_chunk'`。

- [ ] **Step 3: 实现模型**

`backend/app/models/note_chunk.py`：

```python
"""note_chunks ORM 模型：与 SCHEMA §4.3 一一对应（spec §5.1）。"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.db import Base


class NoteChunk(Base):
    __tablename__ = "note_chunks"
    __table_args__ = (
        UniqueConstraint("note_id", "chunk_index", name="uq_note_chunks_note_chunk_index"),
        Index("ix_note_chunks_user_id", "user_id"),
        Index("ix_note_chunks_tsv_gin", "tsv", postgresql_using="gin"),
        Index(
            "ix_note_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    note_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=text("'note'"))
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

`backend/app/models/__init__.py`：

```python
"""模型包：显式导入供 Alembic target_metadata 发现。"""
from app.models.note_chunk import NoteChunk

__all__ = ["NoteChunk"]
```

- [ ] **Step 4: 跑模型测试确认通过**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_note_chunk_model.py -v
```

Expected: `6 passed`。

- [ ] **Step 5: 创建 Alembic 脚手架**

`backend/alembic.ini`：

```ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = %(here)s
sqlalchemy.url = postgresql+psycopg://study:study123@localhost:5432/study_agent

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/alembic/env.py`：

```python
"""Alembic 环境：连接串只从 Settings 读，metadata 来自 app.models（spec §5.2）。"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/alembic/script.py.mako`：

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 6: 写首个迁移** `backend/alembic/versions/0001_create_note_chunks.py`

```python
"""S1-3 create note_chunks（首个迁移，只建这一张表）

Revision ID: 0001_s1_3
Revises:
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_s1_3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector 扩展必须先于 vector 列；IF NOT EXISTS 兼容 compose 首启已建的情况
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "note_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.Text(), server_default=sa.text("'note'"), nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("note_id", "chunk_index", name="uq_note_chunks_note_chunk_index"),
    )
    op.create_index("ix_note_chunks_user_id", "note_chunks", ["user_id"])
    op.create_index("ix_note_chunks_tsv_gin", "note_chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_note_chunks_embedding_hnsw",
        "note_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    op.drop_table("note_chunks")
```

- [ ] **Step 7: 离线渲染迁移 SQL，确认脚手架可用（不连库）**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m alembic upgrade head --sql | Select-String "CREATE TABLE note_chunks|hnsw|GIN|vector"
```

Expected: 输出含 `CREATE TABLE note_chunks`、`CREATE EXTENSION`、`USING hnsw`、`USING gin`、`vector(1024)`。若 Alembic 版本对 `%(here)s` 或 logging 配置报错，按报错修 ini，不改迁移语义。

---

### Task 5: 入库服务 `index_chunks`（TDD）

**Files:**
- Create: `backend/app/services/indexing.py`
- Delete: `backend/app/services/.gitkeep`
- Modify: `backend/app/services/__init__.py`（若无则新建空文件）
- Test: `backend/tests/test_indexing.py`

**Interfaces:**
- Consumes: `EmbeddingClient`、`join_for_tsv`、`NoteChunk`、`Chunk`
- Produces: `IndexingResult(chunk_count, vector_dim, total_tokens, elapsed_ms, cost_cny)`
- Produces: `index_chunks(session, chunks, *, note_id, user_id, source_file_id=None, replace=True, client=None, progress=None)`

- [ ] **Step 1: 写失败测试** `backend/tests/test_indexing.py`

```python
"""S1-3 入库服务测试：fake session/client，验证删除/插入/维度/汇总（spec §7）。"""
from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.embedding.base import BatchStats
from app.ai.embedding.errors import EmbeddingError
from app.ai.rag.chunker import Chunk, ChunkType
from app.services.indexing import index_chunks


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement: object) -> None:
        self.executed.append(statement)

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeClient:
    model = "fake-embed"
    dim = 1024

    def __init__(self, *, dim: int = 1024, fail: bool = False) -> None:
        self.dim = dim
        self.usage_tokens = 0
        self.calls: list[list[str]] = []
        self.fail = fail

    def encode(self, texts: list[str], *, on_batch=None) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("fake failure")
        self.calls.append(list(texts))
        self.usage_tokens += len(texts) * 3
        if on_batch is not None:
            on_batch(BatchStats(0, 1, len(texts), len(texts) * 3, 1))
        return [[0.0] * self.dim for _ in texts]


def _chunk(content: str = "函数的单调性：设 f(x) 在区间 D 内。", index: int = 0) -> Chunk:
    return Chunk(
        content=content,
        chunk_index=index,
        heading_path="函数/单调性",
        page_no=2,
        token_count=12,
        chunk_type=ChunkType.note,
    )


def test_index_chunks_happy_path() -> None:
    session = FakeSession()
    client = FakeClient()
    result = index_chunks(session, [_chunk()], note_id=7, user_id=3, client=client)
    assert client.calls == [["函数的单调性：设 f(x) 在区间 D 内。"]]
    assert len(session.added) == 1
    row = session.added[0]
    assert row.note_id == 7
    assert row.user_id == 3
    assert row.chunk_index == 0
    assert row.token_count == 12
    assert row.chunk_type == "note"
    assert row.heading_path == "函数/单调性"
    assert row.page_no == 2
    assert row.source_file_id is None
    assert row.bbox_json is None
    assert "to_tsvector" in str(row.tsv).lower()
    assert session.committed is True
    assert result.chunk_count == 1
    assert result.vector_dim == 1024
    assert result.total_tokens == 3
    assert result.cost_cny == pytest.approx(3 / 1_000_000 * 0.5)


def test_replace_deletes_same_note_and_user() -> None:
    session = FakeSession()
    index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient())
    sql = str(session.executed[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert "DELETE FROM note_chunks" in sql
    assert "note_id = 7" in sql
    assert "user_id = 3" in sql


def test_no_replace_skips_delete() -> None:
    session = FakeSession()
    index_chunks(session, [_chunk()], note_id=7, user_id=3, replace=False, client=FakeClient())
    assert session.executed == []


def test_empty_chunks_with_replace_clears_old_rows() -> None:
    session = FakeSession()
    result = index_chunks(session, [], note_id=7, user_id=3, client=FakeClient())
    assert len(session.executed) == 1
    assert session.committed is True
    assert result.chunk_count == 0
    assert result.total_tokens == 0


def test_dimension_mismatch_rolls_back() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError, match="维度"):
        index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient(dim=8))
    assert session.rolled_back is True
    assert session.added == []


def test_client_failure_rolls_back() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError):
        index_chunks(session, [_chunk()], note_id=7, user_id=3, client=FakeClient(fail=True))
    assert session.rolled_back is True
    assert session.added == []


def test_progress_callback_is_forwarded() -> None:
    seen: list[BatchStats] = []
    index_chunks(
        FakeSession(),
        [_chunk()],
        note_id=7,
        user_id=3,
        client=FakeClient(),
        progress=seen.append,
    )
    assert len(seen) == 1
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_indexing.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.indexing'`。

- [ ] **Step 3: 实现 `backend/app/services/indexing.py`**

```python
"""S1-3 入库编排：切片 → 向量化 → note_chunks（spec §7）。

S2-8 Worker / S3-1 索引服务必须复用本函数，禁止另写一份。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.ai.embedding import BatchStats, EmbeddingClient, get_embedding_client
from app.ai.embedding.errors import EmbeddingError
from app.ai.rag.chunker import Chunk
from app.core.config import get_settings
from app.models.note_chunk import NoteChunk
from app.utils.zh_tokenizer import join_for_tsv

logger = logging.getLogger(__name__)


class IndexingResult(BaseModel):
    chunk_count: int
    vector_dim: int
    total_tokens: int
    elapsed_ms: int
    cost_cny: float


def index_chunks(
    session: Session,
    chunks: list[Chunk],
    *,
    note_id: int,
    user_id: int,
    source_file_id: int | None = None,
    replace: bool = True,
    client: EmbeddingClient | None = None,
    progress: Callable[[BatchStats], None] | None = None,
) -> IndexingResult:
    """把一组 Chunk 写入 note_chunks；同 note_id/user_id 重复调用幂等覆盖。"""
    started = time.perf_counter()
    settings = get_settings()
    embedding_client = client or get_embedding_client()
    tokens_before = embedding_client.usage_tokens

    if not chunks:
        try:
            if replace:
                session.execute(_delete_statement(note_id, user_id))
                session.commit()
        except Exception:
            session.rollback()
            raise
        return IndexingResult(
            chunk_count=0,
            vector_dim=embedding_client.dim,
            total_tokens=0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            cost_cny=0.0,
        )

    try:
        vectors = embedding_client.encode([chunk.content for chunk in chunks], on_batch=progress)
        if len(vectors) != len(chunks):
            raise EmbeddingError(
                f"Embedding 返回条数不符：期望 {len(chunks)}，实际 {len(vectors)}",
                retryable=False,
            )
        for index, vector in enumerate(vectors):
            if len(vector) != settings.embedding_dim:
                raise EmbeddingError(
                    f"第 {index} 条向量维度不符：期望 {settings.embedding_dim}，实际 {len(vector)}",
                    retryable=False,
                )
        if replace:
            session.execute(_delete_statement(note_id, user_id))
        rows = [
            NoteChunk(
                note_id=note_id,
                user_id=user_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                chunk_type=chunk.chunk_type.value,
                heading_path=chunk.heading_path or None,
                embedding=vector,
                tsv=func.to_tsvector("simple", join_for_tsv(chunk.content)),
                source_file_id=source_file_id,
                page_no=chunk.page_no,
                bbox_json=None,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        session.add_all(rows)
        session.commit()
    except Exception:
        session.rollback()
        raise

    total_tokens = embedding_client.usage_tokens - tokens_before
    cost_cny = total_tokens / 1_000_000 * settings.embedding_price_per_million
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "indexing_done",
        extra={
            "scene": "embed",
            "model": embedding_client.model,
            "note_id": note_id,
            "user_id": user_id,
            "chunks": len(chunks),
            "tokens": total_tokens,
            "cost_cny": cost_cny,
            "latency_ms": elapsed_ms,
        },
    )
    return IndexingResult(
        chunk_count=len(chunks),
        vector_dim=len(vectors[0]) if vectors else settings.embedding_dim,
        total_tokens=total_tokens,
        elapsed_ms=elapsed_ms,
        cost_cny=cost_cny,
    )


def _delete_statement(note_id: int, user_id: int) -> object:
    """按 note + user 删除旧块；user_id 显式过滤是 AGENTS §4 的硬要求。"""
    return delete(NoteChunk).where(NoteChunk.note_id == note_id, NoteChunk.user_id == user_id)
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_indexing.py -v
```

Expected: `7 passed`。

---

### Task 6: 演示脚本 `scripts/index_demo.py`

**Files:**
- Create: `scripts/index_demo.py`

**Interfaces:**
- Consumes: `parse_document`、`chunk_document`、`get_embedding_client`、`index_chunks`、`new_session`
- Produces: CLI 参数 `file / --note-id / --user-id / --source-file-id / --force-pymupdf / --probe-only / --no-replace`

- [ ] **Step 1: 实现脚本**

```python
"""S1-3 演示：解析 → 切片 → 探测维度 → 批量向量化 → pgvector 入库。

用法（仓库根目录）：
    python scripts/index_demo.py <文件> [--note-id 1] [--user-id 1]
           [--source-file-id N] [--force-pymupdf] [--probe-only] [--no-replace]
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import BatchStats, get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.parse import parse_document  # noqa: E402
from app.ai.rag.chunker import chunk_document  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.services.indexing import index_chunks  # noqa: E402

_ACCEPTANCE_SQL = """
验收 SQL（在仓库根目录执行）：
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM note_chunks;"
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT heading_path, left(content,30) FROM note_chunks LIMIT 5;"
  docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT left(content,60) FROM note_chunks WHERE tsv @@ to_tsquery('simple','函数 & 单调性') LIMIT 3;"
"""


def _print_progress(stats: BatchStats) -> None:
    print(
        f"  [batch {stats.batch_index + 1}/{stats.batch_count}] "
        f"{stats.batch_size} 条 · {stats.tokens} tokens · {stats.latency_ms} ms"
    )


def _probe(client) -> int:
    settings = get_settings()
    vector = client.encode(["维度探测：函数的单调性"])[0]
    print(f"Embedding 实测：model={client.model} 维度={len(vector)}（配置 {settings.embedding_dim}）")
    if len(vector) != settings.embedding_dim:
        print(
            "维度与配置/SCHEMA 不一致，停止。请报告契约冲突，不要自行改表（spec §4.4）。",
            file=sys.stderr,
        )
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Embedding 与 pgvector 入库演示（S1-3）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--note-id", type=int, default=1, help="合成笔记 ID（S2-1 前无 notes 表）")
    parser.add_argument("--user-id", type=int, default=1, help="合成用户 ID")
    parser.add_argument("--source-file-id", type=int, default=None, help="合成来源文件 ID")
    parser.add_argument("--force-pymupdf", action="store_true", help="解析走快速路径")
    parser.add_argument("--probe-only", action="store_true", help="只探测向量维度，不写库")
    parser.add_argument("--no-replace", action="store_true", help="不删除同 note_id 的旧块")
    args = parser.parse_args()

    set_trace_id("index-" + uuid.uuid4().hex[:12])
    try:
        client = get_embedding_client()
    except EmbeddingError as exc:
        print(f"Embedding 未就绪：{exc}", file=sys.stderr)
        return 2
    if args.probe_only:
        try:
            return _probe(client)
        except EmbeddingError as exc:
            print(f"Embedding 调用失败：{exc}", file=sys.stderr)
            return 2

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    chunks = chunk_document(doc)
    questions = sum(1 for chunk in chunks if chunk.chunk_type.value == "question")
    print(
        f"文件: {doc.source}    解析器: {doc.parser}    "
        f"块数: {len(chunks)}（question {questions}）"
    )
    if not chunks:
        print("没有可入库的切片（扫描版/空文档），退出。")
        return 0

    try:
        with new_session() as session:
            result = index_chunks(
                session,
                chunks,
                note_id=args.note_id,
                user_id=args.user_id,
                source_file_id=args.source_file_id,
                replace=not args.no_replace,
                client=client,
                progress=_print_progress,
            )
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 3
    except EmbeddingError as exc:
        print(f"Embedding 调用失败：{exc}", file=sys.stderr)
        return 2

    print("-" * 72)
    print(
        f"入库完成：{result.chunk_count} 块 · 维度 {result.vector_dim} · "
        f"{result.total_tokens} tokens · {result.elapsed_ms} ms · "
        f"估算花费 ¥{result.cost_cny:.6f}"
    )
    print(_ACCEPTANCE_SQL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 语法与参数自检（不连库、不调 API）**

```powershell
cd E:\BiShe-AIStudy\study-agent
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\index_demo.py --help
```

Expected: 打印参数列表，退出码 0。

- [ ] **Step 3: 跑全量单测（此时仍未连真实 DB/API）**

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: 既有 44 + 新增 34（config 5 + embedding 9 + tokenizer 7 + model 6 + indexing 7）= `78 passed`（若新增用例数不同，以实际为准，但不得有 FAIL）。

---

### Task 7: 真实环境验收（Docker + Key + 迁移 + 三份样张 + SQL）

**Files:** 无代码改动；只跑命令并记录实测输出。

**前置：**
- 用户已在仓库根 `.env` 填入 `DASHSCOPE_API_KEY`（或 `EMBEDDING_API_KEY`）
- 三份样张位于 `E:\BiShe-AIStudy\测试数据\`

- [ ] **Step 1: 启动基础服务并自检**

```powershell
cd E:\BiShe-AIStudy\study-agent
docker compose -f deploy/docker-compose.dev.yml up -d
Start-Sleep -Seconds 5
.\.venv\Scripts\python.exe scripts\check_services.py
```

Expected: postgres/redis/minio 三件套全 PASS，pgvector 扩展存在，bucket 存在。

- [ ] **Step 2: 确认 Key 已配置（只打印布尔值，绝不打印 Key）**

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -c "from app.core.config import get_settings; print('key_configured=', bool(get_settings().embedding_api_key))"
```

Expected: `key_configured= True`。若为 False，**停止**，让用户先填 `.env`；不要用假 Key。

- [ ] **Step 3: 真实维度探测（建迁移前，任务卡坑 ①）**

```powershell
cd E:\BiShe-AIStudy\study-agent
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学笔记-函数与导数.pdf" --probe-only
```

Expected: `Embedding 实测：model=text-embedding-v4 维度=1024（配置 1024）`，退出码 0。
若维度不是 1024：**停止全部后续步骤**，把实测值报告给用户，等用户决定是否改 SCHEMA；禁止改迁移硬凑。

- [ ] **Step 4: 执行迁移并核对表结构**

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m alembic upgrade head
docker exec study-agent-postgres psql -U study -d study_agent -c "\d note_chunks"
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='note_chunks';"
```

Expected:
- `alembic` 输出 `Running upgrade -> 0001_s1_3`；
- `\d note_chunks` 含 `embedding | vector(1024)`、`tsv | tsvector`、`uq_note_chunks_note_chunk_index`；
- 索引列表含 `ix_note_chunks_embedding_hnsw`（`USING hnsw ... vector_cosine_ops`）与 `ix_note_chunks_tsv_gin`（`USING gin`）。

- [ ] **Step 5: 三份真实样张入库**

```powershell
cd E:\BiShe-AIStudy\study-agent
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学试卷-函数单元测试.pdf" --note-id 101
.\.venv\Scripts\python.exe scripts\index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学笔记-函数与导数.pdf" --note-id 102
.\.venv\Scripts\python.exe scripts\index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学教材页-函数的单调性.pdf" --note-id 103
```

Expected: 三次都打印 `入库完成：... 维度 1024 ...`，进度批次逐条打印；记录每次块数/tokens/耗时/花费。
若 Docling 模型缓存丢失或报网络错误，按 README FAQ 设 `HF_ENDPOINT`/`HF_HUB_DISABLE_XET` 后重试；不许用 `--force-pymupdf` 绕过层级验收（除非用户同意并在报告中注明）。

- [ ] **Step 6: 任务卡三条验收 SQL**

```powershell
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM note_chunks;"
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT heading_path, left(content,30) FROM note_chunks LIMIT 5;"
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT left(content,60) FROM note_chunks WHERE tsv @@ to_tsquery('simple','函数 & 单调性') LIMIT 3;"
```

Expected:
- `count(*)` 等于三次脚本打印块数之和；
- 第二句显示真实 heading_path 与内容前缀；
- 第三句至少 1 行命中。若 0 行：打印 `SELECT tokenize?` 无法直接查，改用
  `SELECT to_tsvector('simple', content) ...` 或跑
  `python -c "from app.utils.zh_tokenizer import tokenize_zh; print(tokenize_zh('函数的单调性'))"` 排查分词；
  **如实报告**，不得改 SQL 或伪造数据。

- [ ] **Step 7: 幂等复跑验证**

```powershell
.\.venv\Scripts\python.exe scripts\index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学试卷-函数单元测试.pdf" --note-id 101
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM note_chunks WHERE note_id=101;"
```

Expected: 第二次的 count 与第一次相同（先删后插，无重复）。

- [ ] **Step 8: 向量检索冒烟（为 S1-4 预验，不算本卡验收）**

```powershell
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT note_id, chunk_index, left(content,40), embedding <=> (SELECT embedding FROM note_chunks WHERE note_id=102 LIMIT 1) AS distance FROM note_chunks ORDER BY embedding <=> (SELECT embedding FROM note_chunks WHERE note_id=102 LIMIT 1) LIMIT 3;"
```

Expected: 返回 3 行且 distance 为有限数值（HNSW 可走）。只作为索引可用性冒烟，结果质量留给 S1-4。

---

### Task 8: 文档归档与提交

**Files:**
- Modify: `docs/SCHEMA.md`（§0 维度定稿 + §4.3 表下 FK 说明）
- Modify: `docs/DECISIONS.md`（新增 D-016）
- Modify: `docs/PROGRESS.md`（勾选 S1-3 + 当前状态 + 变更日志）
- Modify: `AGENTS.md`（§9.6 ai 适配器锚点补 embedding）
- Modify: `docs/spec/s1-3-embedding.md`（回填实测：维度、批大小、jieba 分词、实测数字）
- Modify: `backend/requirements.txt`（若 Task 1 未完成钉版）

- [ ] **Step 1: SCHEMA 定稿**

`docs/SCHEMA.md` §0 把：

```markdown
- 向量维度：统一 `VECTOR(1024)`（⚠ 与最终选定的 Embedding API 维度一致，S1-3 定稿）
```

改为：

```markdown
- 向量维度：统一 `VECTOR(1024)`（✅ S1-3 定稿：DashScope text-embedding-v4 实测输出 1024）
```

在 §4.3 note_chunks 表后加一行：

```markdown
> S1-3 建表时 notes/users/files 尚未建，note_id/user_id/source_file_id 暂不加外键；S2-1 建齐后补。
```

- [ ] **Step 2: DECISIONS 新增 D-016**

```markdown
## D-016 S1-3 Embedding 与入库实现决策（spec §4/§5 归档）

- 日期：2026-10-19（S1-3 实现验收后归档；spec 见 docs/spec/s1-3-embedding.md）
- 决策 1（DashScope text-embedding-v4 + 1024 维）：中文数学文本表现好、OpenAI 兼容、按量便宜（0.0005 元/千 token）；实测输出 1024 与 SCHEMA 一致，迁移按 1024 硬编码
- 决策 2（批大小 10 而非任务卡 32）：厂商硬限制「text-embedding-v4 单次最多 10 行、单行 ≤8192 token」；批大小做成配置，代码不写死
- 决策 3（只建 note_chunks、暂不加 FK）：notes/users/files 属 S2-1；S1-3 用合成 note_id/user_id 完成真实入库验收，S2-1 补外键
- 决策 4（调用日志先结构化、S3-7 入库）：本卡迁移范围不含 llm_call_logs；每次 HTTP 批次落 scene/model/tokens/latency/trace_id，S3-7 建表后切换。临时偏离 AGENTS §5，已获用户确认
- 决策 5（jieba 应用层分词 + to_tsvector('simple')）：与 SCHEMA §9 一致，不用 pg_jieba、不用 bigram；查询侧复用同一 tokenize 函数
- 决策 6（同步 Embedding 客户端）：任务卡接口为 `encode(list[str])`；CLI/Worker 同步最直接，HTTP 超时与重试可控；后续 API 层需要异步时再包线程池
- 验证：pytest 全绿；真实样张三份入库；HNSW/GIN 存在；三条验收 SQL；幂等复跑（详见 PROGRESS 2026-10-19）
```

- [ ] **Step 3: PROGRESS 更新**

- 「当前状态」改为阶段 1 继续，最近完成 S1-3，下一步 S1-4。
- 任务清单 `- [ ] S1-3` 改 `- [x]`。
- 变更日志加 2026-10-19 条目：交付文件、依赖、实测样张数字、验收证据、偏离项。

- [ ] **Step 4: AGENTS §9.6 回填 Embedding 锚点**

在「ai 适配器样例」后加：

```markdown
- ai Embedding 适配器样例：backend/app/ai/embedding/openai_compat.py（同一抽象 base.py；门面 __init__.py 按配置切换厂商；本地实现 local.py 仅占位）
```

- [ ] **Step 5: spec 回填实测**

在 spec 末尾新增「## 15. 实施回填（实测）」：记录真实维度、三份样张块数/ tokens / 耗时 / 花费、jieba 对「函数的单调性」的实际分词、全文查询命中数、依赖实测版本。数字必须来自 Task 7 输出，禁止编造。

- [ ] **Step 6: 最终全量测试 + git 状态检查**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest -q
cd ..
git status --short
```

Expected: pytest 全绿；`git status` 只列出本卡相关文件（**.env 不得出现**）。

- [ ] **Step 7: 提交（整卡一个 commit）**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/alembic backend/alembic.ini backend/app/ai/embedding backend/app/core/config.py backend/app/core/db.py backend/app/models backend/app/services backend/app/utils backend/requirements.txt backend/tests scripts/index_demo.py docs/spec/s1-3-embedding.md docs/plan/s1-3-embedding.md docs/SCHEMA.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md .env.example
git commit -m "feat(s1-3): Embedding 适配器与 pgvector 入库（HNSW + jieba 全文索引）"
git log --oneline -3
git status --short
```

Expected: commit 成功；`git log` 顶部是本提交；`git status` 干净（未跟踪的样张/临时文件除外）。用户负责 `git push`。

---

## Self-Review（写 plan 时已执行）

1. **Spec 覆盖**：spec §2 契约→T2/T5；§3 分层→T1/T5；§4 适配器→T2；§4.3 批大小→T2；§4.4 维度探测→T7；§4.5 日志/成本→T2/T5；§5 模型/迁移→T4；§6 分词→T3；§7 服务→T5；§8 demo→T6；§9 配置/依赖→T1；§10 测试→T1–T5；§11 偏离→T8（D-016）；§12 验收→T7；§13 风险→T6/T7。无缺口。
2. **占位符扫描**：仅 requirements 版本号一处标注「以 Step 1 实测为准」（AGENTS §6 禁止编造版本，属实测回填字段，不是未实现内容）。其余步骤均有可直接执行的代码/命令。
3. **类型一致性**：`BatchStats` 字段在 T2 定义、T5/T6 消费一致；`EmbeddingClient.encode(texts, *, on_batch)` 在 T2 定义、T5/T6 调用一致；`IndexingResult` 字段在 T5 定义、T6 消费一致；`index_chunks` 参数在 T5 定义、T6 调用一致；模型列名与 T5 行构造一致。
4. **执行期偏离**：Task 3 增加 `math_dict.txt` 领域 userdict（默认 jieba 拆「单调/性」，验收 SQL 会 0 命中），已获用户同意并记入 D-016；Task 4 env.py 增加 `connect_timeout=5`（Windows 下 Alembic 首次连接偶发挂起）；Task 1 Key 配置从 `AliasChoices` 改为双字段 + 空值回退（避免空 `EMBEDDING_API_KEY=` 覆盖 `DASHSCOPE_API_KEY`）。
