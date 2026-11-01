# S3-7 缓存 + LLM 调用日志 + 用量统计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给问答加 Redis 结果/Embedding 缓存，把 chat/embedding 调用落 `llm_call_logs`，并提供按天 × scene × model 的管理端用量接口。

**Architecture:** `core/cache.py` 提供可注入的同步 Redis/Memory 缓存；`qa_cache_service` 负责 key 与 JSON 载荷，`prepare_ask` 在改写前查缓存、`stream_events` 成功后回写；Embedding 用包装客户端按内容哈希缓存。适配器在成功/失败时 best-effort 写 `llm_call_logs`，`usage_service` 单条 SQL 聚合后由 admin 接口返回。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Pydantic v2、Alembic、Redis 5.3.1、PostgreSQL 16、pytest。

**Spec:** `docs/spec/s3-7-cache-llm-logs-usage.md`

## Global Constraints

- 不新增第三方依赖；`redis==5.3.1` 已在 `backend/requirements.txt`。
- 测试禁止真实外部调用：LLM/Embedding/Redis 全部 fake/mock；禁止依赖本机 Redis。
- 所有 Python 函数签名带类型标注；金额入库用 `NUMERIC(14,8)`/`Decimal`，不用 float 落库。
- Prompt/回答正文、学生个人信息不得写入 `llm_call_logs` 或缓存日志。
- 缓存/日志是 best-effort：Redis 或日志 DB 故障只 WARNING，不阻断问答。
- 时间统一 UTC；用量按 UTC 日历日切。
- 契约先行：先改 `docs/SCHEMA.md` 与 `docs/API.md`。
- 每个任务结束跑目标测试 + 全量 pytest；基线 **686 passed, 1 warning**。
- 禁止修改已提交的 `0007` 及更早迁移。
- 当前工作目录：`E:\BiShe-AIStudy\study-agent`；命令使用 `.\.venv\Scripts\python.exe -m pytest -q`。

---

### Task 1: 契约、枚举、模型与迁移

**Files:**
- Modify: `backend/app/models/enums.py`
- Create: `backend/app/models/llm_call_log.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0008_s3_7_llm_call_logs.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `docs/SCHEMA.md`（§8.4、§10.14、§10 枚举表）
- Modify: `docs/API.md`（§5 `done.cached`、§11 `/admin/usage`）
- Test: `backend/tests/test_llm_call_log_model.py`

**Interfaces:**
- Produces: `LLMCallScene` (`qa/query_rewrite/kp_align/embed/mistake/gen/agent`)、`LLMCallStatus` (`success/failed`)、`LLMCallLog` ORM。
- Produces: `Settings.cache_enabled`, `qa_cache_enabled`, `qa_cache_ttl_seconds`, `embedding_cache_enabled`, `embedding_cache_ttl_seconds`。
- Produces: 迁移 revision `0008_s3_7`，`down_revision="0007_s3_5"`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_llm_call_log_model.py
from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Numeric, Text

from app.models import LLMCallLog
from app.models.enums import LLMCallScene, LLMCallStatus, in_check


def test_llm_call_scene_and_status_values_match_schema() -> None:
    assert {item.value for item in LLMCallScene} == {
        "qa", "query_rewrite", "kp_align", "embed", "mistake", "gen", "agent",
    }
    assert {item.value for item in LLMCallStatus} == {"success", "failed"}


def test_llm_call_log_columns_match_schema() -> None:
    columns = {column.name for column in LLMCallLog.__table__.columns}
    assert columns == {
        "id", "user_id", "scene", "model", "prompt_tokens", "completion_tokens",
        "cost", "latency_ms", "trace_id", "status", "created_at",
    }
    assert isinstance(LLMCallLog.__table__.c.id.type, BigInteger)
    assert isinstance(LLMCallLog.__table__.c.cost.type, Numeric)
    assert isinstance(LLMCallLog.__table__.c.model.type, Text)
    assert isinstance(LLMCallLog.__table__.c.created_at.type, DateTime)


def test_llm_call_log_constraints_and_indexes_exist() -> None:
    constraints = {
        item.name for item in LLMCallLog.__table__.constraints
        if isinstance(item, CheckConstraint)
    }
    assert constraints == {"ck_llm_call_logs_scene", "ck_llm_call_logs_status"}
    indexes = {
        item.name for item in LLMCallLog.__table__.indexes
        if isinstance(item, Index)
    }
    assert indexes == {
        "ix_llm_call_logs_user_id_created_at",
        "ix_llm_call_logs_scene",
        "ix_llm_call_logs_trace_id",
    }


def test_llm_call_log_check_text_is_rendered() -> None:
    assert in_check("scene", LLMCallScene) == (
        "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', "
        "'mistake', 'gen', 'agent')"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_call_log_model.py -q`
Expected: FAIL `ImportError: cannot import name 'LLMCallLog'`。

- [ ] **Step 3: 实现枚举与模型**

`enums.py` 追加：

```python
class LLMCallScene(StrEnum):
    QA = "qa"
    QUERY_REWRITE = "query_rewrite"
    KP_ALIGN = "kp_align"
    EMBED = "embed"
    MISTAKE = "mistake"
    GEN = "gen"
    AGENT = "agent"


class LLMCallStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
```

`llm_call_log.py` 按 `SCHEMA §8.4`：

```python
class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"
    __table_args__ = (
        CheckConstraint(in_check("scene", LLMCallScene), name="ck_llm_call_logs_scene"),
        CheckConstraint(in_check("status", LLMCallStatus), name="ck_llm_call_logs_status"),
        Index("ix_llm_call_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_llm_call_logs_scene", "scene"),
        Index("ix_llm_call_logs_trace_id", "trace_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_llm_call_logs_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    scene: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

`models/__init__.py` 导入并加入 `__all__`。

- [ ] **Step 4: 写迁移 `0008_s3_7_llm_call_logs.py`**

使用与 `0007` 相同的 `sa.BigInteger`/`sa.Identity`/`sa.Numeric`/`postgresql` 风格；创建表、两条 CHECK、三个索引；`downgrade()` 先删索引再删表。`revision="0008_s3_7"`, `down_revision="0007_s3_5"`。

- [ ] **Step 5: 加配置**

```python
# core/config.py：S3-7 缓存
cache_enabled: bool = True
qa_cache_enabled: bool = True
qa_cache_ttl_seconds: int = 86400
embedding_cache_enabled: bool = True
embedding_cache_ttl_seconds: int = 604800
```

`.env.example` 在 QA 段后追加同名大写变量并注释“S3-7”。

- [ ] **Step 6: 改契约**

`SCHEMA §8.4`：`scene` 写明扩展值集，`status` 写 `success/failed`，`cost | NUMERIC(14,8)`，`user_id` 注明 `ON DELETE SET NULL`。
`SCHEMA §10.14`：改为扩展后的 scene 列表；新增 status 行。
`API.md §5`：`done` 增 `cached: boolean`，说明缓存命中 `tokens=0`、仍落新消息。
`API.md §11`：补 `/admin/usage` 的 range、出参 JSON（照 spec §3.2）。

- [ ] **Step 7: 跑测试与迁移 dry-run**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_call_log_model.py -q`
Expected: 4 passed。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `690 passed, 1 warning`（686 + 4）。

- [ ] **Step 8: 提交**

```bash
git add backend/app/models/enums.py backend/app/models/llm_call_log.py \
  backend/app/models/__init__.py backend/alembic/versions/0008_s3_7_llm_call_logs.py \
  backend/app/core/config.py .env.example docs/SCHEMA.md docs/API.md \
  backend/tests/test_llm_call_log_model.py
git commit -m "feat(s3-7): llm_call_logs 模型、迁移与契约"
```

---

### Task 2: Redis 缓存层与 QA 缓存载荷

**Files:**
- Create: `backend/app/core/cache.py`
- Create: `backend/app/services/qa_cache_service.py`
- Test: `backend/tests/test_cache.py`
- Test: `backend/tests/test_qa_cache.py`

**Interfaces:**
- Produces: `Cache` Protocol（`get/set/delete`）、`MemoryCache(now=...)`、`RedisCache(client=None)`、`get_cache() -> Cache`。
- Produces: `CachedCitation`、`CachedSuggestion`、`CachedAnswer` dataclasses。
- Produces: `normalize_question(text) -> str`、`cache_key(user_id, question, scope) -> str`、`get(cache, *, user_id, question, scope) -> CachedAnswer | None`、`put(cache, *, key, answer, kind, refused, refusal_reason, suggestions, citations, prompt_version, model, ttl_seconds) -> bool`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_cache.py
from __future__ import annotations

from app.core.cache import MemoryCache, RedisCache


class BoomClient:
    def get(self, key: str) -> str:
        raise RuntimeError("redis down")

    def set(self, key: str, value: str, ex: int) -> bool:
        raise RuntimeError("redis down")


def test_memory_cache_honors_ttl() -> None:
    now = [0.0]
    cache = MemoryCache(now=lambda: now[0])
    assert cache.set("k", "v", 10) is True
    assert cache.get("k") == "v"
    now[0] = 10.0
    assert cache.get("k") is None


def test_redis_cache_fail_open_on_get_and_set() -> None:
    cache = RedisCache(client=BoomClient())
    assert cache.get("k") is None
    assert cache.set("k", "v", 10) is False


def test_redis_cache_delete_is_best_effort() -> None:
    class NoDelete:
        def delete(self, key: str) -> int:
            raise RuntimeError("redis down")

    RedisCache(client=NoDelete()).delete("k")
```

```python
# backend/tests/test_qa_cache.py
from __future__ import annotations

from datetime import date

from app.core.cache import MemoryCache
from app.schemas.qa import QaScopeIn
from app.services import qa_cache_service as qc


def _scope() -> QaScopeIn:
    return QaScopeIn(subject_id=7, folder="函数", start_date=date(2026, 1, 1))


def _answer() -> qc.CachedAnswer:
    return qc.CachedAnswer(
        answer="结论[1]",
        kind="rag",
        refused=False,
        refusal_reason=None,
        suggestions=(),
        citations=(qc.CachedCitation(
            index=1, note_id=55, chunk_id=101, title="数列笔记",
            heading_path="数列/错位相减法", page_no=2,
            snippet="错位相减法正文", score=0.9,
        ),),
        prompt_version="qa/v1",
        model="qwen-plus",
    )


def test_cache_key_is_stable_and_scope_sensitive() -> None:
    assert qc.cache_key(18, "  错位相减  法 ", _scope()) == qc.cache_key(
        18, "错位相减 法", _scope()
    )
    assert qc.cache_key(18, "问题", _scope()) != qc.cache_key(18, "问题", None)


def test_put_then_get_roundtrip() -> None:
    cache = MemoryCache()
    key = qc.cache_key(18, "问题", _scope())
    assert qc.put(cache, key=key, answer=_answer().answer, kind="rag",
                  refused=False, refusal_reason=None, suggestions=(),
                  citations=_answer().citations, prompt_version="qa/v1",
                  model="qwen-plus", ttl_seconds=60) is True
    loaded = qc.get(cache, user_id=18, question="问题", scope=_scope())
    assert loaded == _answer()


def test_corrupt_payload_is_miss_and_deleted() -> None:
    cache = MemoryCache()
    key = qc.cache_key(18, "问题", _scope())
    cache.set(key, "{not-json", 60)
    assert qc.get(cache, user_id=18, question="问题", scope=_scope()) is None
    assert cache.get(key) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_cache.py backend/tests/test_qa_cache.py -q`
Expected: FAIL `ModuleNotFoundError` / `ImportError`。

- [ ] **Step 3: 实现 `core/cache.py`**

```python
class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_seconds: int) -> bool: ...
    def delete(self, key: str) -> None: ...


class MemoryCache:
    def __init__(self, *, now=time.monotonic) -> None: ...
    # dict[key] = (value, expires_at)；get 过期即删；set 返回 True
```

`RedisCache`：

- `__init__(self, *, client: object | None = None)`；无 client 时懒建
  `redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)`。
- `get/set/delete` 全部 `try/except Exception`，`logger.warning("cache_unavailable", extra={"op": ...})`，返回 None/False。
- `set` 调 `client.set(key, value, ex=ttl_seconds)`。
- `get_cache()` 用 `@lru_cache(maxsize=1)`；`settings.cache_enabled` 为 false 时返回 `MemoryCache`？不行，关闭应禁用。增加 `NullCache`（get None/set False/delete no-op），关闭时返回它。

- [ ] **Step 4: 实现 `qa_cache_service.py`**

```python
@dataclass(frozen=True)
class CachedCitation:
    index: int
    note_id: int
    chunk_id: int
    title: str | None
    heading_path: str | None
    page_no: int | None
    snippet: str
    score: float


@dataclass(frozen=True)
class CachedSuggestion:
    type: str
    text: str
    note_id: int | None = None


@dataclass(frozen=True)
class CachedAnswer:
    answer: str
    kind: str                  # "rag" | "refused"
    refused: bool
    refusal_reason: str | None
    suggestions: tuple[CachedSuggestion, ...]
    citations: tuple[CachedCitation, ...]
    prompt_version: str | None
    model: str | None
```

实现：

- `normalize_question`: `" ".join(question.split())`。
- `_scope_key`: `"null"` 或 `json.dumps(scope.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。
- key：`f"qa:v1:{user_id}:{sha256(scope).hexdigest()[:16]}:{sha256(question).hexdigest()}"`。
- `put`: `json.dumps(asdict(payload), ensure_ascii=False)`；`cache.set(key, raw, ttl_seconds)`；序列化异常返回 False。
- `get`: `cache.get`，`json.loads` + 显式字段校验（kind、citations 类型、suggestions 类型）；任何 `ValueError/TypeError/KeyError` 都 `cache.delete(key)` 并返回 None；`qa_cache_enabled=False` 时直接 None（`prepare_ask` 只有在拿到 cache 时才调用，开关由路由传入的 cache 决定；这里再加一层）。
- 不记录问题原文，只记录 key 的 hash 片段或 `qa_cache_hit/miss`。

- [ ] **Step 5: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_cache.py backend/tests/test_qa_cache.py -q`
Expected: 6 passed。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `696 passed, 1 warning`。

- [ ] **Step 6: 提交**

```bash
git add backend/app/core/cache.py backend/app/services/qa_cache_service.py \
  backend/tests/test_cache.py backend/tests/test_qa_cache.py
git commit -m "feat(s3-7): Redis 缓存层与 QA 缓存载荷"
```

---

### Task 3: Embedding 内容哈希缓存

**Files:**
- Create: `backend/app/ai/embedding/cached.py`
- Modify: `backend/app/ai/embedding/__init__.py`
- Test: `backend/tests/test_embedding_cached.py`

**Interfaces:**
- Produces: `CachedEmbeddingClient(inner: EmbeddingClient, cache: Cache, ttl_seconds: int)`，实现 `encode` 并保持模型、维度、顺序。
- `get_embedding_client()` 在 `embedding_cache_enabled` 时返回包装客户端。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_embedding_cached.py
from __future__ import annotations

from app.ai.embedding.cached import CachedEmbeddingClient
from app.ai.embedding.base import EmbeddingClient, BatchStats
from app.core.cache import MemoryCache


class FakeEmbedding(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(model="fake-embed", dim=2)
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        vectors = [[float(len(text)), 1.0] for text in texts]
        if on_batch is not None:
            on_batch(BatchStats(0, 1, len(texts), 10, 1))
        return vectors


def test_cached_embedding_hits_without_inner_call() -> None:
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(), 60)
    first = client.encode(["a", "bb"])
    second = client.encode(["a", "bb"])
    assert first == second == [[1.0, 1.0], [2.0, 1.0]]
    assert inner.calls == [["a", "bb"]]


def test_cached_embedding_only_encodes_misses_in_order() -> None:
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(), 60)
    client.encode(["a"])
    assert client.encode(["a", "bbb", "cc"]) == [[1.0, 1.0], [3.0, 1.0], [2.0, 1.0]]
    assert inner.calls == [["a"], ["bbb", "cc"]]


def test_cached_embedding_bypasses_cache_after_ttl() -> None:
    now = [0.0]
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(now=lambda: now[0]), 5)
    client.encode(["a"])
    now[0] = 6.0
    client.encode(["a"])
    assert inner.calls == [["a"], ["a"]]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_embedding_cached.py -q`
Expected: FAIL `ModuleNotFoundError`。

- [ ] **Step 3: 实现包装器**

```python
class CachedEmbeddingClient(EmbeddingClient):
    def __init__(self, inner: EmbeddingClient, cache: Cache, ttl_seconds: int) -> None:
        super().__init__(model=inner.model, dim=inner.dim)
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_seconds

    def encode(self, texts, *, on_batch=None):
        if not texts:
            return []
        keys = [self._key(text) for text in texts]
        vectors: list[list[float] | None] = [None] * len(texts)
        miss_indexes: list[int] = []
        for index, key in enumerate(keys):
            raw = self._cache.get(key)
            if raw is not None:
                try:
                    value = json.loads(raw)
                    if isinstance(value, list) and len(value) == self.dim:
                        vectors[index] = [float(item) for item in value]
                        continue
                except (TypeError, ValueError):
                    pass
            miss_indexes.append(index)
        if miss_indexes:
            miss_texts = [texts[index] for index in miss_indexes]
            fresh = self._inner.encode(miss_texts, on_batch=on_batch)
            if len(fresh) != len(miss_texts):
                raise EmbeddingError("Embedding 返回条数不符", retryable=False)
            for index, vector in zip(miss_indexes, fresh):
                vectors[index] = vector
                self._cache.set(keys[index], json.dumps(vector), self._ttl)
        if any(vector is None for vector in vectors):
            raise EmbeddingError("Embedding 返回条数不符", retryable=False)
        return [vector for vector in vectors if vector is not None]
```

`_key`：`f"embed:{self.model}:{self.dim}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"`。
维度不符的缓存值视为 miss，重新编码。

- [ ] **Step 4: 改门面**

`embedding/__init__.py` 的 `get_embedding_client()`：

```python
inner = OpenAICompatibleEmbeddingClient(...) if ... else LocalEmbeddingClient()
if not settings.embedding_cache_enabled:
    return inner
return CachedEmbeddingClient(inner, get_cache(), settings.embedding_cache_ttl_seconds)
```

`__all__` 增加 `CachedEmbeddingClient`。不要改 `LocalEmbeddingClient` 内部。

- [ ] **Step 5: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_embedding_cached.py backend/tests/test_embedding_client.py -q`
Expected: 3 + 现有 embedding 测试全过。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `699 passed, 1 warning`。

- [ ] **Step 6: 提交**

```bash
git add backend/app/ai/embedding/cached.py backend/app/ai/embedding/__init__.py \
  backend/tests/test_embedding_cached.py
git commit -m "feat(s3-7): Embedding 内容哈希缓存"
```

---

### Task 4: LLM 调用日志与上下文

**Files:**
- Modify: `backend/app/core/context.py`
- Create: `backend/app/core/llm_log.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/ai/llm/openai_compat.py`
- Modify: `backend/app/ai/llm/__init__.py`
- Modify: `backend/app/ai/embedding/openai_compat.py`
- Modify: `backend/app/ai/embedding/__init__.py`
- Modify: `backend/app/ai/align/extractor.py`
- Test: `backend/tests/test_llm_call_log.py`
- Test: `backend/tests/test_llm.py`
- Test: `backend/tests/test_llm_stream.py`
- Test: `backend/tests/test_embedding_client.py`

**Interfaces:**
- Produces: `get_current_user_id() -> int | None`、`set_current_user_id(value) -> Token[int | None]`。
- Produces: `record_llm_call(*, scene, model, status, prompt_tokens, completion_tokens, cost_yuan, latency_ms, user_id=None, trace_id=None, session_factory=new_session) -> None`。
- Produces: `OpenAICompatibleLLMClient(..., log_calls=False)`、`OpenAICompatibleEmbeddingClient(..., log_calls=False, price_per_million=0.5)`。
- `get_llm_client()`/`get_embedding_client()` 传 `log_calls=True` 和配置单价。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_llm_call_log.py
from __future__ import annotations

from decimal import Decimal

from app.core import llm_log
from app.core.context import reset_current_user_id, set_current_user_id
from app.models.llm_call_log import LLMCallLog


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.closed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_record_llm_call_writes_success_row() -> None:
    session = FakeSession()
    token = set_current_user_id(18)
    try:
        llm_log.record_llm_call(
            scene="qa", model="qwen-plus", status="success",
            prompt_tokens=100, completion_tokens=20, cost_yuan=0.00012,
            latency_ms=321, session_factory=lambda: session,
        )
    finally:
        reset_current_user_id(token)
    row = session.added[0]
    assert isinstance(row, LLMCallLog)
    assert row.user_id == 18
    assert row.scene == "qa"
    assert row.status == "success"
    assert row.cost == Decimal("0.00012")
    assert session.committed is True and session.closed is True


def test_record_llm_call_failure_does_not_raise() -> None:
    class Boom:
        def add(self, instance: object) -> None:
            raise RuntimeError("db down")

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    llm_log.record_llm_call(
        scene="qa", model="m", status="failed", prompt_tokens=None,
        completion_tokens=None, cost_yuan=None, latency_ms=1,
        session_factory=lambda: Boom(),
    )  # 不抛异常即通过
```

追加到 `test_llm.py`：

```python
def test_chat_logs_success_when_enabled(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "app.ai.llm.openai_compat.record_llm_call",
        lambda **kwargs: captured.append(kwargs),
    )
    client = _client(lambda request: _ok("答[1]", {
        "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
    }), log_calls=True)
    client.chat([LLMMessage("user", "问题")])
    assert captured[0]["scene"] == "qa"
    assert captured[0]["status"] == "success"
    assert captured[0]["prompt_tokens"] == 10


def test_chat_logs_failure_when_enabled(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "app.ai.llm.openai_compat.record_llm_call",
        lambda **kwargs: captured.append(kwargs),
    )
    client = _client(lambda request: httpx.Response(400, json={"error": "bad"}),
                     log_calls=True)
    with pytest.raises(LLMError):
        client.chat([LLMMessage("user", "问题")])
    assert captured[0]["status"] == "failed"
    assert captured[0]["prompt_tokens"] is None
```

追加到 `test_llm_stream.py`：

```python
def test_stream_logs_success_when_enabled(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "app.ai.llm.openai_compat.record_llm_call",
        lambda **kwargs: captured.append(kwargs),
    )
    client = _client(_stream_handler(["你", "好"]), log_calls=True)
    events = list(client.chat_stream([LLMMessage("user", "问题")]))
    assert events[-1].response is not None
    assert captured[-1]["scene"] == "qa"
    assert captured[-1]["status"] == "success"
```

追加到 `test_embedding_client.py`：

```python
def test_embedding_logs_success_and_failure_when_enabled(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        "app.ai.embedding.openai_compat.record_llm_call",
        lambda **kwargs: captured.append(kwargs),
    )
    client = _client(lambda request: httpx.Response(200, json={
        "data": [{"embedding": [0.1, 0.2]}],
        "usage": {"total_tokens": 10},
    }), log_calls=True)
    client.encode(["文本"])
    assert captured[0]["scene"] == "embed"
    assert captured[0]["status"] == "success"
    assert captured[0]["prompt_tokens"] == 10

    bad = _client(lambda request: httpx.Response(400, json={"error": "bad"}),
                  log_calls=True)
    with pytest.raises(Exception):
        bad.encode(["文本"])
    assert captured[-1]["status"] == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_call_log.py backend/tests/test_llm.py -q`
Expected: FAIL `ImportError`/`TypeError: unexpected keyword log_calls`。

- [ ] **Step 3: 实现上下文与写入口**

`context.py`：

```python
_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

def get_current_user_id() -> int | None:
    return _current_user_id.get()

def set_current_user_id(value: int | None) -> Token[int | None]:
    return _current_user_id.set(value)

def reset_current_user_id(token: Token[int | None]) -> None:
    _current_user_id.reset(token)
```

`api/deps.get_current_user` 在返回前：

```python
set_current_user_id(user.id)
return user
```

`llm_log.py`：

```python
def record_llm_call(
    *, scene: str, model: str, status: str,
    prompt_tokens: int | None, completion_tokens: int | None,
    cost_yuan: float | None, latency_ms: int | None,
    user_id: int | None = None, trace_id: str | None = None,
    session_factory: Callable[[], Session] = new_session,
) -> None:
    resolved_user_id = user_id if user_id is not None else get_current_user_id()
    resolved_trace_id = trace_id
    if resolved_trace_id is None:
        value = get_trace_id()
        resolved_trace_id = None if value == "-" else value
    cost = None if cost_yuan is None else Decimal(str(round(cost_yuan, 8)))
    try:
        session = session_factory()
        try:
            session.add(LLMCallLog(
                user_id=resolved_user_id, scene=scene, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cost=cost, latency_ms=latency_ms, trace_id=resolved_trace_id,
                status=status,
            ))
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.warning("llm_call_log_failed", extra={"scene": scene, "status": status})
```

- [ ] **Step 4: LLM 适配器埋点**

`OpenAICompatibleLLMClient.__init__` 增加 `log_calls: bool = False`；`chat`：

```python
started = time.perf_counter()
try:
    data = self._post_with_retry(payload)
except Exception:
    self._record(scene, "failed", None, None, None,
                 int((time.perf_counter() - started) * 1000))
    raise
...
self._record(scene, "success", prompt_tokens, completion_tokens, cost, latency_ms)
```

`_record` 只在 `self._log_calls` 时调用 `record_llm_call`，`cost_yuan=None` 表示失败。

`chat_stream`：在 `while True` 外套 `try`；`GeneratorExit` 时若还没记成功，记 `failed` 后 `raise`；普通异常记 `failed` 后 `raise`；正常结束算出 usage 后先记 `success`，再 `yield` 最终 `LLMResponse`。用一个 `logged = False` 防止重复。

`get_llm_client()` 传 `log_calls=True`。

- [ ] **Step 5: Embedding 适配器埋点**

`OpenAICompatibleEmbeddingClient.__init__` 增加 `log_calls: bool = False, price_per_million: float = 0.5`。
`encode` 每批：

```python
started = time.perf_counter()
try:
    payload = self._post_with_retry(...)
    vectors.extend(...)
    tokens = int((payload.get("usage") or {}).get("total_tokens", 0))
except Exception:
    self._record("failed", None, int((time.perf_counter() - started) * 1000))
    raise
cost = tokens * self._price / 1_000_000
self._record("success", tokens, latency_ms, cost)
```

`get_embedding_client()` 传 `log_calls=True, price_per_million=settings.embedding_price_per_million`。

`ai/align/extractor.py` 的 `client.chat(...)` 增加 `scene="kp_align"`。

- [ ] **Step 6: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_call_log.py backend/tests/test_llm.py backend/tests/test_llm_stream.py backend/tests/test_embedding_client.py -q`
Expected: 全过（新增 2 条日志写入口 + 2 条 chat + 1 条 stream + 1 条 embedding，共 6 条）。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `705 passed, 1 warning`。

- [ ] **Step 7: 提交**

```bash
git add backend/app/core/context.py backend/app/core/llm_log.py backend/app/api/deps.py \
  backend/app/ai/llm/openai_compat.py backend/app/ai/llm/__init__.py \
  backend/app/ai/embedding/openai_compat.py backend/app/ai/embedding/__init__.py \
  backend/app/ai/align/extractor.py backend/tests/test_llm_call_log.py \
  backend/tests/test_llm.py backend/tests/test_llm_stream.py \
  backend/tests/test_embedding_client.py
git commit -m "feat(s3-7): LLM/Embedding 调用日志埋点"
```

---

### Task 5: 用量聚合服务与 `/admin/usage`

**Files:**
- Create: `backend/app/services/usage_service.py`
- Create: `backend/app/schemas/usage.py`
- Modify: `backend/app/api/v1/admin.py`
- Test: `backend/tests/test_usage_service.py`
- Test: `backend/tests/test_usage_api.py`

**Interfaces:**
- Produces: `get_usage(session: Session, *, range_key: str) -> UsageReport`。
- Produces: `UsageTotals`、`UsageItem`、`UsageReport` Pydantic 模型。
- `GET /api/v1/admin/usage?range=7d` → `Envelope[UsageReport]`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_usage_service.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.usage_service import get_usage


class FakeResult:
    def __init__(self, rows): self._rows = rows
    def all(self): return list(self._rows)


class FakeSession:
    def __init__(self, rows): self.rows = rows
    def execute(self, statement): return FakeResult(self.rows)


def test_usage_aggregates_rows_and_totals() -> None:
    rows = [
        (date(2026, 11, 1), "qa", "qwen-plus", 2, 0, 100, 50, 150,
         Decimal("0.0002"), 1200),
        (date(2026, 11, 1), "embed", "text-embedding-v4", 3, 1, 300, 0, 300,
         Decimal("0.0001"), 80),
    ]
    report = get_usage(FakeSession(rows), range_key="7d")
    assert report.range == "7d"
    assert report.totals.calls == 5
    assert report.totals.failed_calls == 1
    assert report.totals.total_tokens == 450
    assert report.totals.cost_yuan == pytest.approx(0.0003)
    assert [item.scene for item in report.items] == ["qa", "embed"]


def test_usage_empty_range() -> None:
    report = get_usage(FakeSession([]), range_key="1d")
    assert report.items == []
    assert report.totals.calls == 0
    assert report.totals.cost_yuan == 0.0
```

```python
# backend/tests/test_usage_api.py
from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import admin as admin_module
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.usage import UsageItem, UsageReport, UsageTotals


class FakeSession:
    def __init__(self, user: User | None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")


def _user(role: str = "admin") -> User:
    user = User(
        username=f"{role}_1", password_hash="hash", nickname="测试用户",
        grade=None, role=role,
    )
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_usage_requires_token(client: TestClient) -> None:
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(None)
    resp = client.get("/api/v1/admin/usage?range=7d")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_usage_rejects_non_admin_and_bad_range(client: TestClient) -> None:
    student = _user("student")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(student)
    resp = client.get("/api/v1/admin/usage?range=7d", headers=_headers(student))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300

    admin = _user("admin")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(admin)
    resp = client.get("/api/v1/admin/usage?range=999d", headers=_headers(admin))
    assert resp.status_code == 422


def test_usage_returns_report(client: TestClient, monkeypatch) -> None:
    admin = _user("admin")
    app.dependency_overrides[deps.get_db] = lambda: FakeSession(admin)
    report = UsageReport(
        range="7d",
        start_date=date(2026, 10, 26),
        end_date=date(2026, 11, 1),
        totals=UsageTotals(calls=2, total_tokens=120, cost_yuan=0.0002),
        items=[UsageItem(
            date=date(2026, 11, 1), scene="qa", model="qwen-plus",
            calls=2, total_tokens=120, cost_yuan=0.0002, avg_latency_ms=100,
        )],
    )
    monkeypatch.setattr(
        admin_module.usage_service, "get_usage", lambda session, *, range_key: report
    )
    resp = client.get("/api/v1/admin/usage?range=7d", headers=_headers(admin))
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    assert body["data"]["range"] == "7d"
    assert body["data"]["items"][0]["scene"] == "qa"
    assert body["data"]["totals"]["calls"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_usage_service.py backend/tests/test_usage_api.py -q`
Expected: FAIL `ModuleNotFoundError` / 404。

- [ ] **Step 3: 实现 schema 与 service**

```python
# schemas/usage.py
class UsageTotals(BaseModel):
    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_yuan: float = 0.0
    avg_latency_ms: int = 0

class UsageItem(UsageTotals):
    date: date
    scene: str
    model: str

class UsageReport(BaseModel):
    range: Literal["1d", "7d", "30d"]
    start_date: date
    end_date: date
    totals: UsageTotals
    items: list[UsageItem]
```

`usage_service`：

- `_RANGE_DAYS = {"1d": 1, "7d": 7, "30d": 30}`；非法抛 `InvalidParamError("range 仅支持 1d/7d/30d")`。
- `today = datetime.now(UTC).date()`；`start_date = today - timedelta(days=days - 1)`；`start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)`；`end_dt = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)`。
- 查询：

```python
day = func.date(LLMCallLog.created_at)
failed = func.sum(case((LLMCallLog.status == "failed", 1), else_=0))
rows = session.execute(
    select(
        day.label("date"), LLMCallLog.scene, LLMCallLog.model,
        func.count().label("calls"), failed.label("failed_calls"),
        func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0),
        func.coalesce(func.sum(LLMCallLog.completion_tokens), 0),
        func.coalesce(func.sum(LLMCallLog.prompt_tokens + LLMCallLog.completion_tokens), 0),
        func.coalesce(func.sum(LLMCallLog.cost), 0),
        func.coalesce(func.avg(LLMCallLog.latency_ms), 0),
    )
    .where(LLMCallLog.created_at >= start_dt, LLMCallLog.created_at < end_dt)
    .group_by(day, LLMCallLog.scene, LLMCallLog.model)
    .order_by(day, LLMCallLog.scene, LLMCallLog.model)
).all()
```

- 逐行转 `UsageItem`；`cost_yuan=float(Decimal(str(value)).quantize(Decimal("0.00000001")))`；`avg_latency_ms=int(round(value))`。
- totals 用 `sum(item.calls ...)`，`avg_latency_ms` 用加权平均（`sum(latency*calls)/calls`），空数据为 0。
- 若 `prompt_tokens`/`completion_tokens` 为 NULL，`coalesce` 后为 0。

- [ ] **Step 4: 加路由**

`admin.py` 顶部导入 `Query`、`Literal`、`UsageReport`、`usage_service`：

```python
@router.get("/usage", response_model=Envelope[UsageReport], summary="按天统计 LLM 用量")
def get_usage_report(
    range_: Literal["1d", "7d", "30d"] = Query("7d", alias="range"),
    current_user: User = Depends(require_role("admin")),
    session: Session = Depends(get_db),
) -> Envelope[UsageReport]:
    data = usage_service.get_usage(session, range_key=range_)
    return Envelope(trace_id=get_trace_id(), data=data)
```

- [ ] **Step 5: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_usage_service.py backend/tests/test_usage_api.py -q`
Expected: 5 passed（service 2 + API 3）。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `710 passed, 1 warning`。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/usage_service.py backend/app/schemas/usage.py \
  backend/app/api/v1/admin.py backend/tests/test_usage_service.py \
  backend/tests/test_usage_api.py
git commit -m "feat(s3-7): 用量聚合服务与管理端接口"
```

---

### Task 6: QA 缓存接入与 `done.cached`

**Files:**
- Modify: `backend/app/services/qa_service.py`
- Modify: `backend/app/api/v1/qa.py`
- Modify: `backend/app/schemas/qa.py`
- Test: `backend/tests/test_qa_service.py`
- Test: `backend/tests/test_qa_api.py`

**Interfaces:**
- `prepare_ask(..., cache: Cache | None = None)`。
- `stream_events(..., cache: Cache | None = None)`。
- `QaPlan` 末尾新增 `cached: CachedAnswer | None = None`、`cache_key: str | None = None`。
- `done` data 新增 `cached: bool`；schema `QaDoneData.cached: bool = False`。

- [ ] **Step 1: 写失败测试**

追加到 `test_qa_service.py`：

```python
from app.core.cache import MemoryCache
from app.services import qa_cache_service


def _seed_cache(cache: MemoryCache, *, question: str = "错位相减法怎么用") -> str:
    key = qa_cache_service.cache_key(18, question, _scope())
    qa_cache_service.put(
        cache, key=key, answer="缓存答案[1]", kind="rag", refused=False,
        refusal_reason=None, suggestions=(),
        citations=(qa_cache_service.CachedCitation(
            index=1, note_id=55, chunk_id=101, title="数列笔记",
            heading_path="数列/错位相减法", page_no=2,
            snippet="错位相减法正文", score=0.9,
        ),),
        prompt_version="qa/v1", model="qwen-plus", ttl_seconds=60,
    )
    return key


def test_prepare_ask_cache_hit_skips_rewrite_and_retrieval(monkeypatch) -> None:
    cache = MemoryCache()
    _seed_cache(cache)
    session = FakeSession()
    monkeypatch.setattr(
        qa_service, "rewrite_query", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("cache hit 不应改写")
        )
    )
    plan = qa_service.prepare_ask(
        session, user_id=18, question="错位相减法怎么用",
        scope=_scope(), conversation_id=None, cache=cache,
    )
    assert plan.cached is not None
    assert plan.cached.answer == "缓存答案[1]"
    assert plan.prompt_version == "qa/v1"
    assert plan.citations[0].chunk_id == 101
    assert plan.kind == "rag"


def test_stream_events_cache_hit_emits_done_cached_without_llm(monkeypatch) -> None:
    cache = MemoryCache()
    _seed_cache(cache)
    plan = qa_service.prepare_ask(
        FakeSession(), user_id=18, question="错位相减法怎么用",
        scope=_scope(), conversation_id=None, cache=cache,
    )
    final_session = FakeSession()

    def no_stream(*args, **kwargs):
        raise AssertionError("缓存命中不应调用 LLM")

    monkeypatch.setattr(qa_service, "stream_answer", no_stream)
    events = list(qa_service.stream_events(
        plan, session_factory=lambda: final_session, cache=cache,
    ))
    assert [event.event for event in events] == ["meta", "delta", "done"]
    done = events[-1].data
    assert done["cached"] is True
    assert done["tokens"] == 0
    assert done["refused"] is False
    saved = [item for item in final_session.added if isinstance(item, Message)]
    assert saved[0].content_md == "缓存答案[1]"
    citations = [item for item in final_session.added if isinstance(item, MessageCitation)]
    assert citations[0].chunk_id == 101
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`
Expected: FAIL `TypeError: prepare_ask() got an unexpected keyword argument 'cache'`。

- [ ] **Step 3: 扩展 `QaPlan` 与 `_persist_assistant`**

```python
@dataclass(frozen=True)
class QaPlan:
    # ...原有字段保持不变
    cached: CachedAnswer | None = None
    cache_key: str | None = None
```

`_persist_assistant` 增加 `cached_citations: tuple[CachedCitation, ...] | None = None`；若提供：

```python
for citation in cached_citations:
    session.add(MessageCitation(
        message_id=message.id, chunk_id=citation.chunk_id, note_id=citation.note_id,
        score=citation.score, snippet=citation.snippet, page_no=citation.page_no,
        rank=citation.index,
    ))
```

否则走原有 `plan.prepared.built.items` 分支。`model` 在 `responses` 为空时用 `plan.cached.model if plan.cached else None`。

- [ ] **Step 4: `prepare_ask` 查缓存**

在 `session.commit()` 后、`rewrite_query` 前：

```python
cache_key = None
if cache is not None and get_settings().qa_cache_enabled:
    cache_key = qa_cache_service.cache_key(user_id, clean, resolved_scope)
    cached = qa_cache_service.get(
        cache, user_id=user_id, question=clean, scope=resolved_scope
    )
    if cached is not None:
        logger.info("qa_cache_hit", extra={"conversation_id": conversation.id})
        return QaPlan(
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            question=clean,
            kind=cached.kind,  # type: ignore[arg-type]
            prepared=None,
            chitchat_reply=None,
            citations=[
                QaCitationMeta(
                    index=item.index, note_id=item.note_id, chunk_id=item.chunk_id,
                    title=item.title, heading_path=item.heading_path,
                    page_no=item.page_no, snippet=item.snippet,
                )
                for item in cached.citations
            ],
            prompt_version=cached.prompt_version,
            rewrite=None,
            started_at=started,
            cached=cached,
            cache_key=cache_key,
        )
```

所有正常返回的 `QaPlan` 都加 `cache_key=cache_key`。`cache_key` 变量在函数开头初始化为 `None`。

- [ ] **Step 5: `stream_events` 处理命中与回写**

在 `meta` 之后、`chitchat` 分支之前：

```python
if plan.cached is not None:
    cached = plan.cached
    for part in _answer_parts(cached.answer):
        yield QaStreamEvent(event="delta", data={"text": part})
    try:
        message = _persist_assistant(
            session_factory=session_factory, plan=plan, content=cached.answer,
            responses=[], citation_indices=[],
            cached_citations=cached.citations,
        )
    except Exception:
        logger.exception("qa_persist_cached_failed")
        yield _error_event()
        return
    yield QaStreamEvent(event="done", data=_done_data(
        plan, message, refused=cached.refused, responses=[],
        refusal_reason=cached.refusal_reason,
        suggestions=[QaSuggestion(item.type, item.text, item.note_id)
                     for item in cached.suggestions],
        cached=True,
    ))
    return
```

新增 `_cache_put` 辅助函数：

```python
def _cache_put(plan: QaPlan, *, cache: Cache | None, answer: str,
               refused: bool, refusal_reason: str | None,
               suggestions: list[QaSuggestion], model: str | None) -> None:
    if cache is None or not plan.cache_key or not get_settings().qa_cache_enabled:
        return
    citations = []
    if not refused and plan.prepared is not None and plan.prepared.built is not None:
        for meta in plan.citations:
            score = plan.prepared.built.items[meta.index - 1].citation.rerank_score
            citations.append(CachedCitation(
                index=meta.index, note_id=meta.note_id, chunk_id=meta.chunk_id,
                title=meta.title, heading_path=meta.heading_path,
                page_no=meta.page_no, snippet=meta.snippet, score=score,
            ))
    qa_cache_service.put(
        cache, key=plan.cache_key, answer=answer,
        kind="refused" if refused else "rag", refused=refused,
        refusal_reason=refusal_reason,
        suggestions=tuple(CachedSuggestion(item.type, item.text, item.note_id)
                          for item in suggestions),
        citations=tuple(citations), prompt_version=plan.prompt_version,
        model=model, ttl_seconds=get_settings().qa_cache_ttl_seconds,
    )
```

在 chitchat 分支不写缓存。在 pre-refused 分支和 checker RAG 分支成功 `_persist_assistant` 后调用 `_cache_put`：

- pre-refused：`answer=REFUSAL_TEXT, refused=True, reason, suggestions=_suggestions(), model=None`
- RAG：`answer=final_text, refused=refused, reason, suggestions, model=responses[-1].model if responses else None`

`_done_data` 增加 `cached: bool = False` 并放进 dict 的 `"cached": cached`；所有现有调用位置补 `cached=False` 或默认。

- [ ] **Step 6: 路由注入 cache**

`qa.py`：

```python
from app.core.cache import get_cache
...
cache = get_cache()
plan = qa_service.prepare_ask(..., cache=cache)
return StreamingResponse(_stream(plan, request, cache=cache), ...)
```

`_stream(plan, request, *, cache)` 调 `stream_events(plan, cancel_event=cancel_event, cache=cache)`。

`schemas/qa.py` 的 `QaDoneData` 加 `cached: bool = False`。

- [ ] **Step 7: 更新 API 测试 fixture**

`test_qa_api.py` 的 done data 增加 `"cached": False`（以及新增一条 `cached=True` 的 schema 接受测试）。不要改已有断言含义。

- [ ] **Step 8: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py backend/tests/test_qa_api.py -q`
Expected: 新增 3 条通过（service 2 + API 1），原有 18+8 条通过。

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: `713 passed, 1 warning`。

- [ ] **Step 9: 提交**

```bash
git add backend/app/services/qa_service.py backend/app/api/v1/qa.py \
  backend/app/schemas/qa.py backend/tests/test_qa_service.py backend/tests/test_qa_api.py
git commit -m "feat(s3-7): QA 结果缓存与 done.cached"
```

---

### Task 7: 真实验收脚本与执行

**Files:**
- Create: `scripts/cache_eval.py`

**Interfaces:**
- CLI：`python scripts/cache_eval.py --user-id 18 [--question ...]`。
- 输出：两次耗时、两次 `llm_call_logs` 行数、第二次 `cached/tokens`、PASS/FAIL，失败退出 1。

- [ ] **Step 1: 写脚本**

脚本用真实 `new_session/get_cache/qa_service/LLMCallLog`：

```python
def _log_count(session) -> int:
    return int(session.scalar(select(func.count()).select_from(LLMCallLog)) or 0)

def run(user_id: int, question: str) -> int:
    cache = get_cache()
    # 先删 key，保证第一次 miss
    with new_session() as session:
        scope = None
        key = qa_cache_service.cache_key(user_id, question, scope)
        cache.delete(key)
        before = _log_count(session)
        plan1 = qa_service.prepare_ask(session, user_id=user_id, question=question,
                                       scope=scope, conversation_id=None, cache=cache)
        events1 = list(qa_service.stream_events(plan1, cache=cache))
        after_first = _log_count(session)
        plan2 = qa_service.prepare_ask(session, user_id=user_id, question=question,
                                       scope=scope, conversation_id=None, cache=cache)
        events2 = list(qa_service.stream_events(plan2, cache=cache))
        after_second = _log_count(session)
    done1 = events1[-1].data
    done2 = events2[-1].data
    print(f"first   latency={done1['latency_ms']}ms tokens={done1['tokens']} "
          f"logs={after_first - before} cached={done1['cached']}")
    print(f"second  latency={done2['latency_ms']}ms tokens={done2['tokens']} "
          f"logs={after_second - after_first} cached={done2['cached']}")
    ok = (after_second == after_first and done2["cached"] is True
          and done2["tokens"] == 0 and done1["cached"] is False)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1
```

注意：`prepare_ask` 的 session 与 `stream_events` 的 `new_session` 独立；脚本中不要在同一 session 里读 count 与写消息导致事务可见性问题，按上面顺序 commit 后再 count。

- [ ] **Step 2: 先迁移真实库**

Run: `.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head`
Expected: `Running upgrade 0007_s3_5 -> 0008_s3_7`。

- [ ] **Step 3: 跑真实缓存验收**

Run: `.\.venv\Scripts\python.exe scripts/cache_eval.py --user-id 18`
Expected: 第一次 `cached=False`、有日志；第二次 `cached=True`、`tokens=0`、`logs=0`、耗时明显更低；末行 `PASS`。

- [ ] **Step 4: 真实验收用量接口**

用真实 admin token 调：

```powershell
curl.exe -s -H "Authorization: Bearer <admin_token>" "http://127.0.0.1:8000/api/v1/admin/usage?range=7d"
```

若没有现成 admin 账号，先用 `scripts/ask.py`/数据库确认管理员；不得伪造 token。记录 HTTP 状态、`items` 首行 `date/scene/model/total_tokens/cost_yuan`、`totals`。

- [ ] **Step 5: 跑全量测试**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全部通过，记录实际 passed 数。

- [ ] **Step 6: 提交**

```bash
git add scripts/cache_eval.py
git commit -m "feat(s3-7): 缓存与调用日志验收脚本"
```

---

### Task 8: 文档同步、最终验证与提交

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/API.md`（若 Task 1 未覆盖 `cached`/usage 细节）
- Modify: `docs/SCHEMA.md`（若 Task 1 未覆盖 status/scene）
- Modify: `docs/spec/s3-7-cache-llm-logs-usage.md`（追加实施记录）
- Modify: `docs/plan/s3-7-cache-llm-logs-usage.md`（追加执行记录）

- [ ] **Step 1: 追加 spec/plan 实施记录**

记录：实际新增测试数、全量 passed、真实两次耗时、日志行数、`cached/tokens`、usage 接口真实返回、迁移 revision、发现的偏差。不得写未测数字。

- [ ] **Step 2: 更新 PROGRESS**

- 当前状态：S3-7 完成，下一卡 S3-8，测试数实际值。
- 变更日志新增 `### 2026-11-02（S3-7）`：交付文件、拍板（D-041、scene 扩展、缓存 key 忽略历史）、测试、真实验收、文档同步。
- 技术债新增/更新：缓存不随笔记/Prompt 失效、忽略历史、日志 best-effort 可能拖慢、失败调用 usage NULL、UTC 日切、Redis 无加密。

- [ ] **Step 3: 更新 DECISIONS**

新增 **D-041 缓存 + 调用日志 + 用量（S3-7）**，写清：

- 缓存 key 与命中时机；
- 缓存/日志旁路失败口径；
- `scene` 扩展与 `status=success/failed`；
- 用量 UTC 日切与 `cost_yuan` 口径；
- 已知限制。

- [ ] **Step 4: 勾选任务卡**

`docs/AI协作开发实施计划.md` 的 S3-7 标题加 ✅，追加实施记录（测试数、真实两次耗时、无新增日志、usage 结果、脚本路径）。

- [ ] **Step 5: 最终验证**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 实际记录 `N passed, 1 warning`，不得沿用计划估算。

Run: `.\.venv\Scripts\python.exe scripts/cache_eval.py --user-id 18`
Expected: `PASS`，记录真实耗时/日志。

Run: `git diff --check`
Expected: 无输出。

- [ ] **Step 6: 提交**

```bash
git add docs/PROGRESS.md docs/DECISIONS.md "docs/AI协作开发实施计划.md" \
  docs/API.md docs/SCHEMA.md docs/spec/s3-7-cache-llm-logs-usage.md \
  docs/plan/s3-7-cache-llm-logs-usage.md
git commit -m "docs(s3-7): 缓存、调用日志与用量验收记录"
```

---

## 自检

- **Spec 覆盖**：目标 1/2/3/4/5 分别由 Task 6、3、4、5、1/6 覆盖；契约 §3 在 Task 1；迁移 §7 在 Task 1；配置 §8 在 Task 1；测试 §9 分散在各任务；真实验收 §10 在 Task 7/8；D-041 与限制在 Task 8。
- **占位符扫描**：未使用 TODO/TBD；每个任务有测试代码、验证命令和提交命令。
- **类型一致性**：`CachedAnswer/CachedCitation/CachedSuggestion` 在 Task 2 定义，Task 6 使用；`get_usage/UsageReport` 在 Task 5 定义并使用；`record_llm_call` 在 Task 4 定义并被适配器使用。

## 执行记录（2026-11-02）

- Task 1–6 全部按 TDD 完成并分别提交；迁移 `0008_s3_7` 已对真实 Postgres 执行。
- 实际新增测试 33 条（模型 4、缓存 7、Embedding 缓存 4、调用日志/适配器 10、用量 5、QA 缓存流程 3），基线 686 → **719 passed, 1 warning**；与 plan 预估的 713 不同，按实测记录。
- 偏差：① 缓存层单测 4 条而非 3 条；② `done.cached` 的 true/false 由 `test_qa_cache_flow.py` 覆盖，未单独加 `test_qa_api.py`；③ 流式适配器拆出 `_chat_stream_impl`，外层包装器在 `GeneratorExit`/异常时补记 failed；④ 对齐测试 Fake 补 `scene` 形参。
- 真实验收：`scripts/cache_eval.py --user-id 18` 第一问 36.468s/4251 tokens/4 条日志；第二问 0.014s/0 tokens/0 条新增日志，`cached=true`、答案一致且落新消息。
- 用量接口：本机无 admin 账号，创建临时 admin 行并用真实 token 调 `GET /api/v1/admin/usage?range=7d`（TestClient + 真实 Postgres），返回 200 后立即删除临时账号；结果 `totals.calls=8`、`total_tokens=8433`、`cost_yuan=0.010392`，items 覆盖 embed/qa/query_rewrite。未伪造 token。
- 文档同步：SCHEMA、API、PROGRESS、DECISIONS D-041、实施计划、spec §13、本执行记录。