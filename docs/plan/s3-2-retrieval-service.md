# S3-2 检索服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 S1-4/S1-5 的混合检索封装成带 scope 过滤、可调试、可度量的 `services/retrieval_service.py`，并暴露 student 检索接口。

**Architecture:** retriever 负责 SQL 下推与 RRF/rerank（复用 S1-4/S1-5，不重写）；service 负责参数校验、rerank 开关、标题批查与 DTO 组装；route 只做 Pydantic → service → Envelope。scope 通过 join `notes` 实现，恒带 `user_id` 与 `deleted_at IS NULL`。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2.0、Pydantic v2、pytest；不新增依赖、不新增表/迁移。

**Spec:** `docs/spec/s3-2-retrieval-service.md`（执行时与 spec 一起读）

## Global Constraints

- 不新增第三方依赖；不新增表/迁移。
- 检索 SQL 只能改 `backend/app/ai/rag/retriever.py`，禁止在 service/route 里另写检索 SQL。
- 所有查询显式过滤 `user_id`；接口 `require_role("student")`，teacher/parent/admin 一律 403。
- 路由函数 ≤30 行；业务逻辑在 `services/retrieval_service.py`；出入参一律 Pydantic。
- 测试禁止真实外部调用：FakeSession/FakeClient/monkeypatch；pytest 全绿是提交前提。
- 配置只放 `core/config.py` 的 `Settings`，同步 `.env.example`；新变量大写。
- 每个任务结束跑一次全套 pytest；提交信息用 Conventional Commits 且带 `(s3-2)`；`git push` 由用户执行。
- 文档同步：`API.md`、`PROGRESS.md`、`DECISIONS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md` 第 14 章。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/ai/rag/retriever.py` | 修改 | `RetrievalScope`、scope 条件、两路 SQL join、`embedding_ms` |
| `backend/app/schemas/retrieval.py` | 新建 | 请求/scope/命中/debug/响应 Pydantic 模型 |
| `backend/app/services/retrieval_service.py` | 新建 | `search_chunks`：校验、rerank 开关、标题批查、DTO 组装 |
| `backend/app/api/v1/retrieval.py` | 新建 | `POST /retrieval/search`，student only |
| `backend/app/api/router.py` | 修改 | 挂载 retrieval 路由 |
| `backend/app/core/config.py`、`.env.example` | 修改 | `retrieval_top_k/recall_k/rerank_enabled` |
| `backend/tests/test_retriever.py` | 修改 | scope SQL 断言、`embedding_ms`；删除旧占位拒参用例 |
| `backend/tests/test_retrieval_service.py` | 新建 | 空库、开关、标题、debug、scope 转换 |
| `backend/tests/test_retrieval_api.py` | 新建 | 401/403/200/422 |
| `scripts/retrieval_bench.py` | 新建 | HTTP P50/P95 压测 |
| `docs/*` | 修改 | API/PROGRESS/DECISIONS/AGENTS/实施计划/spec/plan |

---

### Task 1: Retriever scope 过滤与向量耗时

**Files:**
- Modify: `backend/app/ai/rag/retriever.py`
- Test: `backend/tests/test_retriever.py`

**Interfaces:**
- Produces: `RetrievalScope(subject_id, folder, start_date, end_date, chunk_types)`；`retrieve_hybrid(..., scope=None)`；`retrieve_hybrid_reranked(..., scope=None)`；`RetrievalResult.embedding_ms: int`。
- 移除：`RetrievalFilterUnavailable`、`retrieve_hybrid` 的 `subject_id/kp_ids` 参数。

- [ ] **Step 1: 改测试（先失败）**

把 `backend/tests/test_retriever.py` 顶部 import 改成：

```python
from datetime import date

from app.ai.embedding.errors import EmbeddingError
from app.ai.rerank import (
    RerankCandidate,
    RerankClient,
    RerankError,
    RerankResponse,
    RerankScore,
)
from app.ai.rag.retriever import (
    RetrievalScope,
    RetrievedChunk,
    _scope_conditions,
    rerank_fused,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
    rrf_fuse,
)
from app.models.note import Note
from app.models.note_chunk import NoteChunk
```

删除 `test_rejects_subject_and_kp_filters`，在 `test_query_filters_use_user_id_and_limits` 后加入：

```python
def _compiled(statement: object) -> str:
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_retrieve_hybrid_joins_notes_and_guards_owner() -> None:
    session = FakeSession(FakeResult([]), FakeResult([]))
    retrieve_hybrid(session, "函数的定义域", user_id=7, client=FakeClient())

    for statement in session.statements:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "JOIN notes" in sql
        assert "notes.user_id" in sql
        assert "notes.deleted_at IS NULL" in sql


def test_scope_conditions_include_all_filters() -> None:
    from sqlalchemy import select

    scope = RetrievalScope(
        subject_id=7,
        folder="函数",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        chunk_types=["question", "note"],
    )
    sql = _compiled(select(NoteChunk.id).where(*_scope_conditions(scope, 7)))

    assert "notes.user_id = 7" in sql
    assert "notes.deleted_at IS NULL" in sql
    assert "notes.subject_id = 7" in sql
    assert "notes.folder = '函数'" in sql
    assert "notes.created_at >=" in sql
    # end_date 含当天：下界是次日 00:00 UTC
    assert "2026-11-01 00:00:00+00:00" in sql
    assert "chunk_type IN ('question', 'note')" in sql


def test_scope_none_keeps_only_owner_and_deleted_guard() -> None:
    from sqlalchemy import select

    sql = _compiled(select(NoteChunk.id).where(*_scope_conditions(None, 7)))

    assert "notes.user_id = 7" in sql
    assert "notes.deleted_at IS NULL" in sql
    assert "notes.subject_id" not in sql
    assert "notes.folder" not in sql
    assert "chunk_type IN" not in sql


def test_retrieval_result_reports_embedding_ms() -> None:
    session = FakeSession(FakeResult([]), FakeResult([]))
    result = retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient())
    assert result.embedding_ms >= 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retriever.py -q`
Expected: FAIL —— `ImportError: cannot import name 'RetrievalScope'` / `_scope_conditions`。

- [ ] **Step 3: 实现 retriever 改动**

`backend/app/ai/rag/retriever.py`：

1. import 增加：

```python
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from app.models.note import Note
```

2. 删除 `class RetrievalFilterUnavailable`。

3. 在 `RetrievedChunk` 前加 scope 模型：

```python
class RetrievalScope(BaseModel):
    subject_id: int | None = None
    folder: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    chunk_types: list[Literal["question", "note", "formula"]] | None = None


def _utc_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _scope_conditions(scope: RetrievalScope | None, user_id: int) -> list[object]:
    """owner + 未删是恒有条件；其余 scope 条件全部下推 SQL。"""
    conditions: list[object] = [
        NoteChunk.user_id == user_id,
        Note.user_id == user_id,
        Note.deleted_at.is_(None),
    ]
    if scope is None:
        return conditions
    if scope.subject_id is not None:
        conditions.append(Note.subject_id == scope.subject_id)
    if scope.folder:
        conditions.append(Note.folder == scope.folder)
    if scope.start_date is not None:
        conditions.append(Note.created_at >= _utc_start(scope.start_date))
    if scope.end_date is not None:
        conditions.append(Note.created_at < _utc_start(scope.end_date + timedelta(days=1)))
    if scope.chunk_types:
        conditions.append(NoteChunk.chunk_type.in_(scope.chunk_types))
    return conditions
```

4. `RetrievalResult` 增加字段：

```python
    elapsed_ms: int
    embedding_ms: int = 0
    vector_ms: int = 0
```

5. `_vector_search` / `_fulltext_search` 增加 `scope` 参数并 join：

```python
def _vector_search(
    session: Session,
    query_vector: list[float],
    *,
    user_id: int,
    top_k: int,
    scope: RetrievalScope | None = None,
) -> list[RetrievedChunk]:
    distance = NoteChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(NoteChunk, distance)
        .join(Note, Note.id == NoteChunk.note_id)
        .where(*_scope_conditions(scope, user_id))
        .order_by(distance.asc(), NoteChunk.id.asc())
        .limit(top_k)
    )
    rows = session.execute(stmt).all()
    return [
        _to_chunk(row[0], vector_rank=rank, vector_distance=float(row[1]))
        for rank, row in enumerate(rows, start=1)
    ]


def _fulltext_search(
    session: Session,
    tsquery_str: str,
    *,
    user_id: int,
    top_k: int,
    scope: RetrievalScope | None = None,
) -> list[RetrievedChunk]:
    tsquery = func.to_tsquery("simple", tsquery_str)
    score = func.ts_rank_cd(NoteChunk.tsv, tsquery).label("fulltext_score")
    stmt = (
        select(NoteChunk, score)
        .join(Note, Note.id == NoteChunk.note_id)
        .where(NoteChunk.tsv.op("@@")(tsquery), *_scope_conditions(scope, user_id))
        .order_by(score.desc(), NoteChunk.id.asc())
        .limit(top_k)
    )
    rows = session.execute(stmt).all()
    return [
        _to_chunk(row[0], fulltext_rank=rank, fulltext_score=float(row[1]))
        for rank, row in enumerate(rows, start=1)
    ]
```

6. `retrieve_hybrid` 签名改为：

```python
def retrieve_hybrid(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    final_k: int | None = None,
    client: EmbeddingClient | None = None,
    scope: RetrievalScope | None = None,
) -> RetrievalResult:
```

删除开头的 `RetrievalFilterUnavailable` 抛错块；空 query 返回值补 `embedding_ms=0`；embedding 调用改为：

```python
    embed_started = time.perf_counter()
    query_vector = embedding_client.encode([query])[0]
    embedding_ms = int((time.perf_counter() - embed_started) * 1000)
```

两路调用传 `scope=scope`；返回的 `RetrievalResult` 增加 `embedding_ms=embedding_ms`；日志 extra 增加 `"embedding_ms": embedding_ms`。

7. `retrieve_hybrid_reranked` 签名用 `scope` 替换 `subject_id/kp_ids`，并透传给 `retrieve_hybrid(..., scope=scope)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retriever.py -q`
Expected: PASS（约 21 passed）。

再跑全套：`.\.venv\Scripts\python.exe -m pytest -q`
Expected: 567 passed 左右（564 - 1 旧用例 + 4 新用例），全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/ai/rag/retriever.py backend/tests/test_retriever.py
git commit -m "feat(s3-2): 检索器支持 scope 过滤与向量耗时"
```

---

### Task 2: 检索 schemas、配置与服务

**Files:**
- Create: `backend/app/schemas/retrieval.py`
- Create: `backend/app/services/retrieval_service.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_retrieval_service.py`

**Interfaces:**
- Consumes: Task 1 的 `RetrievalScope`、`retrieve_hybrid`、`retrieve_hybrid_reranked`。
- Produces: `search_chunks(session, *, user_id, query, top_k=None, rerank=None, scope=None, debug=False) -> RetrievalSearchResponse`；`RetrievalSearchRequest`、`RetrievalScopeIn`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_retrieval_service.py`：

```python
"""S3-2 检索服务测试（spec §5）：fake retriever/session，不触库、不调外部 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.rag.retriever import RerankInfo, RetrievalResult, RetrievedChunk
from app.core.exceptions import InvalidParamError
from app.schemas.retrieval import RetrievalScopeIn
from app.services import retrieval_service


class FakeResult:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[int, str]]:
        return list(self._rows)


class FakeSession:
    def __init__(self, rows: list[tuple[int, str]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[object] = []

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)


def _chunk(chunk_id: int, *, note_id: int = 1, rrf: float = 0.1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=note_id,
        source_file_id=None,
        chunk_index=chunk_id,
        content=f"  函数的定义域  第 {chunk_id} 块  ",
        heading_path="函数/定义域",
        page_no=1,
        chunk_type="note",
        vector_rank=chunk_id,
        vector_distance=0.1,
        rrf_score=rrf,
    )


def _result(*, fused: list[RetrievedChunk] | None = None, reranked: list[RetrievedChunk] | None = None) -> RetrievalResult:
    hits = fused or []
    return RetrievalResult(
        query="函数的定义域",
        tsquery="函数 | 定义域",
        vector=hits,
        fulltext=hits,
        fused=hits,
        reranked=reranked or [],
        elapsed_ms=12,
        embedding_ms=9,
        vector_ms=2,
        fulltext_ms=1,
        rerank_info=RerankInfo(
            model="fake-rerank",
            candidates=2,
            top_k=2,
            tokens=10,
            latency_ms=3,
            cost_yuan=0.0,
        ),
    )


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    values = {
        "retrieval_top_k": 6,
        "retrieval_recall_k": 20,
        "retrieval_rerank_enabled": True,
    }
    values.update(overrides)
    monkeypatch.setattr(
        retrieval_service, "get_settings", lambda: SimpleNamespace(**values)
    )


def test_search_rejects_blank_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    with pytest.raises(InvalidParamError, match="query"):
        retrieval_service.search_chunks(FakeSession(), user_id=1, query="   ")


def test_search_rejects_top_k_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    for value in (0, 21):
        with pytest.raises(InvalidParamError, match="top_k"):
            retrieval_service.search_chunks(
                FakeSession(), user_id=1, query="函数", top_k=value
            )


def test_search_empty_knowledge_base_returns_empty_without_title_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    session = FakeSession()
    monkeypatch.setattr(
        retrieval_service, "retrieve_hybrid", lambda *a, **k: _result(fused=[])
    )
    monkeypatch.setattr(
        retrieval_service, "retrieve_hybrid_reranked", lambda *a, **k: _result()
    )

    response = retrieval_service.search_chunks(
        session, user_id=1, query="函数", rerank=False
    )

    assert response.hits == []
    assert response.debug is None
    assert session.statements == []


def test_search_rerank_false_uses_fused_and_skips_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    fused = [_chunk(1), _chunk(2)]
    captured: dict[str, object] = {}

    def fake_hybrid(session, query, **kwargs):
        captured.update(kwargs)
        return _result(fused=fused)

    def fake_reranked(*args, **kwargs):
        raise AssertionError("rerank=false 不应调用 retrieve_hybrid_reranked")

    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", fake_hybrid)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid_reranked", fake_reranked)

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", rerank=False
    )

    assert [hit.chunk_id for hit in response.hits] == [1, 2]
    assert response.rerank is False
    assert response.rerank_info is None
    assert response.embedding_ms == 9
    assert captured["top_k"] == 20
    assert captured["final_k"] == 6
    assert captured["user_id"] == 1


def test_search_rerank_true_uses_reranked(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _result(fused=[_chunk(1)], reranked=[_chunk(2)]),
    )
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应走无重排路径")),
    )

    response = retrieval_service.search_chunks(FakeSession(), user_id=1, query="函数")

    assert [hit.chunk_id for hit in response.hits] == [2]
    assert response.rerank is True
    assert response.rerank_info is not None
    assert response.rerank_info.fallback is False


def test_search_loads_titles_in_one_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    session = FakeSession([(1, "函数笔记"), (2, "数列笔记")])
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=[_chunk(1, note_id=1), _chunk(2, note_id=2)]),
    )

    response = retrieval_service.search_chunks(
        session, user_id=1, query="函数", rerank=False
    )

    assert len(session.statements) == 1
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "IN" in sql.upper()
    assert "notes.user_id" in sql
    assert [hit.note_title for hit in response.hits] == ["函数笔记", "数列笔记"]


def test_search_missing_title_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=[_chunk(1, note_id=1)]),
    )

    response = retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="函数", rerank=False
    )

    assert response.hits[0].note_title is None


def test_search_debug_only_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    hits = [_chunk(1), _chunk(2)]
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=hits),
    )

    plain = retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="函数", rerank=False
    )
    debug = retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="函数", rerank=False, debug=True
    )

    assert plain.debug is None
    assert debug.debug is not None
    assert debug.debug.tsquery == "函数 | 定义域"
    assert len(debug.debug.vector) == 2
    assert len(debug.debug.fused) == 2


def test_search_converts_scope_and_trims_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    captured: dict[str, object] = {}

    def fake_hybrid(session, query, **kwargs):
        captured["query"] = query
        captured["scope"] = kwargs.get("scope")
        return _result()

    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", fake_hybrid)
    scope = RetrievalScopeIn(subject_id=7, folder=" 函数 ", chunk_types=["note"])

    retrieval_service.search_chunks(
        FakeSession([]),
        user_id=1,
        query="  函数的定义域  ",
        rerank=False,
        scope=scope,
    )

    assert captured["query"] == "函数的定义域"
    assert captured["scope"].subject_id == 7
    assert captured["scope"].folder == "函数"
    assert captured["scope"].chunk_types == ["note"]


def test_search_snippet_collapses_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid",
        lambda *a, **k: _result(fused=[_chunk(1)]),
    )

    response = retrieval_service.search_chunks(
        FakeSession([]), user_id=1, query="函数", rerank=False
    )

    assert response.hits[0].snippet == "函数的定义域 第 1 块"
    assert response.hits[0].content.strip().startswith("函数的定义域")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.schemas.retrieval`。

- [ ] **Step 3: 新建 schemas**

`backend/app/schemas/retrieval.py`：

```python
"""S3-2 检索接口出入参（API.md §5）。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.rag.retriever import RerankInfo

RetrievalChunkType = Literal["question", "note", "formula"]


class RetrievalScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: int | None = Field(None, ge=1)
    folder: str | None = Field(None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    chunk_types: list[RetrievalChunkType] | None = Field(None, min_length=1)

    @field_validator("folder")
    @classmethod
    def _strip_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _check_range_and_dedupe(self) -> "RetrievalScopeIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        if self.chunk_types:
            self.chunk_types = list(dict.fromkeys(self.chunk_types))
        return self


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(None, ge=1, le=20)
    rerank: bool | None = None
    debug: bool = False
    scope: RetrievalScopeIn | None = None


class RetrievalHit(BaseModel):
    chunk_id: int
    note_id: int
    note_title: str | None = None
    source_file_id: int | None = None
    chunk_index: int
    chunk_type: str | None = None
    content: str
    snippet: str
    heading_path: str | None = None
    page_no: int | None = None
    vector_rank: int | None = None
    vector_distance: float | None = None
    fulltext_rank: int | None = None
    fulltext_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


class RetrievalDebug(BaseModel):
    tsquery: str
    vector_ms: int
    fulltext_ms: int
    vector: list[RetrievalHit]
    fulltext: list[RetrievalHit]
    fused: list[RetrievalHit]


class RetrievalSearchResponse(BaseModel):
    query: str
    top_k: int
    rerank: bool
    elapsed_ms: int
    embedding_ms: int
    rerank_info: RerankInfo | None = None
    hits: list[RetrievalHit]
    debug: RetrievalDebug | None = None
```

- [ ] **Step 4: 加配置**

`backend/app/core/config.py` 在 Rerank 配置块后加：

```python
    # --- 检索服务（S3-2）---
    retrieval_top_k: int = 6
    retrieval_recall_k: int = 20
    retrieval_rerank_enabled: bool = True
```

`.env.example` 加（放在 RAG/Rerank 段附近）：

```dotenv
# 检索服务（S3-2）
RETRIEVAL_TOP_K=6
RETRIEVAL_RECALL_K=20
RETRIEVAL_RERANK_ENABLED=true
```

- [ ] **Step 5: 新建 service**

`backend/app/services/retrieval_service.py`：

```python
"""S3-2 检索服务（spec §5）：scope 校验 + S1-4/S1-5 复用 + 标题批查。

检索 SQL 只在 ai/rag/retriever.py；本层只做业务编排，不写 SQL 检索逻辑。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.retriever import (
    RetrievalScope,
    RetrievalResult,
    RetrievedChunk,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
)
from app.core.config import get_settings
from app.core.exceptions import InvalidParamError
from app.models.note import Note
from app.schemas.retrieval import (
    RetrievalDebug,
    RetrievalHit,
    RetrievalScopeIn,
    RetrievalSearchResponse,
)

logger = logging.getLogger(__name__)

MAX_TOP_K = 20
SNIPPET_LIMIT = 200


def search_chunks(
    session: Session,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
    rerank: bool | None = None,
    scope: RetrievalScopeIn | None = None,
    debug: bool = False,
) -> RetrievalSearchResponse:
    settings = get_settings()
    clean_query = query.strip()
    if not clean_query:
        raise InvalidParamError("query 不能为空")

    resolved_top_k = settings.retrieval_top_k if top_k is None else top_k
    if not 1 <= resolved_top_k <= MAX_TOP_K:
        raise InvalidParamError(f"top_k 必须在 1–{MAX_TOP_K} 之间")

    use_rerank = settings.retrieval_rerank_enabled if rerank is None else rerank
    retrieval_scope = RetrievalScope(**scope.model_dump()) if scope else None

    if use_rerank:
        result = retrieve_hybrid_reranked(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            rerank_top_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.reranked
    else:
        result = retrieve_hybrid(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            final_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.fused

    titles = _load_titles(session, user_id, _note_ids(result))
    debug_out = None
    if debug:
        debug_out = RetrievalDebug(
            tsquery=result.tsquery,
            vector_ms=result.vector_ms,
            fulltext_ms=result.fulltext_ms,
            vector=[_to_hit(item, titles) for item in result.vector],
            fulltext=[_to_hit(item, titles) for item in result.fulltext],
            fused=[_to_hit(item, titles) for item in result.fused],
        )

    return RetrievalSearchResponse(
        query=clean_query,
        top_k=resolved_top_k,
        rerank=use_rerank,
        elapsed_ms=result.elapsed_ms,
        embedding_ms=result.embedding_ms,
        rerank_info=result.rerank_info,
        hits=[_to_hit(item, titles) for item in chosen],
        debug=debug_out,
    )


def _note_ids(result: RetrievalResult) -> list[int]:
    ids = {
        item.note_id
        for item in (
            *result.vector,
            *result.fulltext,
            *result.fused,
            *result.reranked,
        )
    }
    return sorted(ids)


def _load_titles(session: Session, user_id: int, note_ids: list[int]) -> dict[int, str]:
    """一次 IN 查询取标题；禁止在命中循环里查库。"""
    if not note_ids:
        return {}
    rows = session.execute(
        select(Note.id, Note.title).where(
            Note.user_id == user_id, Note.id.in_(note_ids)
        )
    ).all()
    return {int(row[0]): row[1] for row in rows}


def _to_hit(item: RetrievedChunk, titles: dict[int, str]) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=item.chunk_id,
        note_id=item.note_id,
        note_title=titles.get(item.note_id),
        source_file_id=item.source_file_id,
        chunk_index=item.chunk_index,
        chunk_type=item.chunk_type,
        content=item.content,
        snippet=" ".join(item.content.split())[:SNIPPET_LIMIT],
        heading_path=item.heading_path,
        page_no=item.page_no,
        vector_rank=item.vector_rank,
        vector_distance=item.vector_distance,
        fulltext_rank=item.fulltext_rank,
        fulltext_score=item.fulltext_score,
        rrf_score=item.rrf_score,
        rerank_score=item.rerank_score,
    )
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_service.py -q`
Expected: 10 passed。

再跑全套：`.\.venv\Scripts\python.exe -m pytest -q`
Expected: 577 passed 左右，全绿。

- [ ] **Step 7: 提交**

```bash
git add backend/app/schemas/retrieval.py backend/app/services/retrieval_service.py backend/app/core/config.py .env.example backend/tests/test_retrieval_service.py
git commit -m "feat(s3-2): 检索服务与 scope 参数校验"
```

---

### Task 3: 学生检索接口

**Files:**
- Create: `backend/app/api/v1/retrieval.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_retrieval_api.py`

**Interfaces:**
- Consumes: Task 2 的 `RetrievalSearchRequest`、`RetrievalSearchResponse`、`search_chunks`。
- Produces: `POST /api/v1/retrieval/search`，200 `Envelope[RetrievalSearchResponse]`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_retrieval_api.py`：

```python
"""S3-2 检索接口测试（spec §6）：TestClient + 依赖覆盖，不触库、不调外部 API。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.retrieval import (
    RetrievalDebug,
    RetrievalHit,
    RetrievalSearchResponse,
)
from app.services import retrieval_service


class FakeSession:
    def __init__(self, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")

    def execute(self, statement: object):
        raise AssertionError("搜索路径不应触库（service 已被替换）")


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_1") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade=None,
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _hit() -> RetrievalHit:
    return RetrievalHit(
        chunk_id=25,
        note_id=54,
        note_title="函数笔记",
        chunk_index=4,
        chunk_type="note",
        content="函数的单调性",
        snippet="函数的单调性",
        heading_path="函数/单调性",
        page_no=3,
        rrf_score=0.03,
    )


def _response() -> RetrievalSearchResponse:
    return RetrievalSearchResponse(
        query="函数",
        top_k=6,
        rerank=False,
        elapsed_ms=12,
        embedding_ms=9,
        hits=[_hit()],
    )


def _debug() -> RetrievalDebug:
    return RetrievalDebug(
        tsquery="函数",
        vector_ms=2,
        fulltext_ms=1,
        vector=[_hit()],
        fulltext=[_hit()],
        fused=[_hit()],
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def fake_search(session: object, **kwargs: Any) -> RetrievalSearchResponse:
        response = _response()
        if kwargs.get("debug"):
            return response.model_copy(update={"debug": _debug()})
        return response

    monkeypatch.setattr(retrieval_service, "search_chunks", fake_search)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override_user(user: User) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(user)


def test_search_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/retrieval/search", json={"query": "函数"})
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_search_rejects_teacher(client: TestClient) -> None:
    user = _user(role="teacher", username="teacher_1")
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数"},
        headers=_headers(user),
    )

    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_search_returns_hits(client: TestClient) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "top_k": 6, "rerank": False},
        headers=_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["query"] == "函数"
    assert data["hits"][0]["chunk_id"] == 25
    assert data["hits"][0]["note_title"] == "函数笔记"
    assert data["debug"] is None
    assert data["rerank"] is False


def test_search_debug_returns_candidates(client: TestClient) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "debug": True, "rerank": False},
        headers=_headers(user),
    )

    data = response.json()["data"]
    assert data["debug"]["vector"][0]["chunk_id"] == 25
    assert data["debug"]["fused"][0]["snippet"] == "函数的单调性"


def test_search_empty_query_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": ""},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_invalid_top_k_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "top_k": 0},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_inverted_dates_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "函数",
            "scope": {"start_date": "2026-10-31", "end_date": "2026-10-01"},
        },
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_unknown_scope_field_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "scope": {"notebook_id": 1}},
        headers=_headers(user),
    )
    assert response.status_code == 422


def test_search_empty_chunk_types_is_422(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "scope": {"chunk_types": []}},
        headers=_headers(user),
    )
    assert response.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_api.py -q`
Expected: FAIL —— 404（路由不存在）。

- [ ] **Step 3: 新建路由并挂载**

`backend/app/api/v1/retrieval.py`：

```python
"""S3-2 检索接口（API.md §5）：仅 student，检索本人切片。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.permissions import require_role
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.retrieval import RetrievalSearchRequest, RetrievalSearchResponse
from app.services import retrieval_service

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/search",
    response_model=Envelope[RetrievalSearchResponse],
    summary="检索本人笔记切片（带 scope 与可选重排）",
)
def search_chunks(
    payload: RetrievalSearchRequest,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
) -> Envelope[RetrievalSearchResponse]:
    data = retrieval_service.search_chunks(
        session,
        user_id=current_user.id,
        query=payload.query,
        top_k=payload.top_k,
        rerank=payload.rerank,
        scope=payload.scope,
        debug=payload.debug,
    )
    return Envelope(trace_id=get_trace_id(), data=data)
```

`backend/app/api/router.py` 改为：

```python
from app.api.v1 import admin, auth, files, kp, notes, retrieval, tasks

...
api_router.include_router(kp.router)
api_router.include_router(retrieval.router)
api_router.include_router(admin.router)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_api.py -q`
Expected: 9 passed。

再跑全套：`.\.venv\Scripts\python.exe -m pytest -q`
Expected: 586 passed 左右，全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/v1/retrieval.py backend/app/api/router.py backend/tests/test_retrieval_api.py
git commit -m "feat(s3-2): 学生检索接口"
```

---

### Task 4: P95 压测脚本

**Files:**
- Create: `scripts/retrieval_bench.py`

**Interfaces:**
- Consumes: `POST /api/v1/auth/login`、`POST /api/v1/retrieval/search`。
- Produces: 终端 P50/P95/分项报告；供 Task 5 验收。

- [ ] **Step 1: 写脚本**

`scripts/retrieval_bench.py`：

```python
"""S3-2 检索接口压测：HTTP 端到端、默认关闭重排，输出 P50/P95。

用法（仓库根目录，需 uvicorn 已启动）：
    .\.venv\Scripts\python.exe scripts/retrieval_bench.py \
        --username test1 --password *** --runs 20 --warmup 3 --no-rerank

口径：wall_ms 含网络+服务端；server_ms 取响应 data.elapsed_ms（含查询 Embedding）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

QUESTIONS = Path("eval/datasets/qa_set.jsonl")


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；问题含中文，统一转 UTF-8 防 print 崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _load_questions(limit: int) -> list[str]:
    rows = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = [row["question"] for row in rows]
    if len(questions) < limit:
        raise ValueError(f"问题不足：需要 {limit}，实际 {len(questions)}")
    return questions[:limit]


def _percentile(values: list[int], ratio: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    response = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["data"]["access_token"]


def _search(
    client: httpx.Client,
    base_url: str,
    token: str,
    question: str,
    *,
    top_k: int,
    rerank: bool,
) -> tuple[int, int, int]:
    started = time.perf_counter()
    response = client.post(
        f"{base_url}/api/v1/retrieval/search",
        json={"query": question, "top_k": top_k, "rerank": rerank},
        headers={"Authorization": f"Bearer {token}"},
    )
    wall_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    data = response.json()["data"]
    return wall_ms, int(data["elapsed_ms"]), int(data["embedding_ms"])


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S3-2 检索接口 P50/P95 压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--no-rerank", action="store_true", help="关闭重排（验收口径）")
    args = parser.parse_args()
    if args.runs <= 0 or args.warmup < 0:
        parser.error("--runs 必须 >0，--warmup 必须 >=0")

    questions = _load_questions(max(args.runs, args.warmup, 1))
    rerank = not args.no_rerank

    with httpx.Client(timeout=60.0) as client:
        token = _login(client, args.base_url, args.username, args.password)
        for index in range(args.warmup):
            _search(
                client,
                args.base_url,
                token,
                questions[index % len(questions)],
                top_k=args.top_k,
                rerank=rerank,
            )

        walls: list[int] = []
        servers: list[int] = []
        embeds: list[int] = []
        print(f"{'#':>3} {'wall_ms':>8} {'server_ms':>10} {'embedding_ms':>13}  question")
        for index in range(args.runs):
            question = questions[index % len(questions)]
            wall, server, embedding = _search(
                client,
                args.base_url,
                token,
                question,
                top_k=args.top_k,
                rerank=rerank,
            )
            walls.append(wall)
            servers.append(server)
            embeds.append(embedding)
            print(f"{index + 1:>3} {wall:>8} {server:>10} {embedding:>13}  {question}")

    p50 = _percentile(walls, 0.50)
    p95 = _percentile(walls, 0.95)
    s_p50 = _percentile(servers, 0.50)
    s_p95 = _percentile(servers, 0.95)
    e_p50 = _percentile(embeds, 0.50)
    print(
        f"\nwall   P50={p50}ms P95={p95}ms\n"
        f"server P50={s_p50}ms P95={s_p95}ms  (含查询 Embedding)\n"
        f"embed  P50={e_p50}ms\n"
        f"rerank={rerank} runs={args.runs} warmup={args.warmup}"
    )
    target = 500
    print(f"P95 目标 < {target}ms：{'PASS' if p95 < target else 'FAIL'}")
    return 0 if p95 < target else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 语法与帮助自检**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/retrieval_bench.py --help`
Expected: 打印参数说明，退出 0。

Run: `.\.venv\Scripts\python.exe -m py_compile scripts/retrieval_bench.py`
Expected: 退出 0。

- [ ] **Step 3: 提交**

```bash
git add scripts/retrieval_bench.py
git commit -m "feat(s3-2): 检索 P95 压测脚本"
```

---

### Task 5: 真实验收与文档同步

**Files:**
- Modify: `docs/API.md`、`docs/SCHEMA.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-2-retrieval-service.md`（§11 实测限制、§12 实施记录）
- Modify: `docs/plan/s3-2-retrieval-service.md`（Execution Record）

- [ ] **Step 1: 起服务并跑全套测试**

```bash
docker compose -f deploy/docker-compose.dev.yml up -d
cd study-agent
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 586 passed 左右，全绿。

另开两个窗口（后台）：

```bash
cd study-agent/backend && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd study-agent/backend && ..\.venv\Scripts\python.exe -m arq app.tasks.worker.WorkerSettings
```

`GET http://127.0.0.1:8000/health` 返回 200。

- [ ] **Step 2: 空知识库**

注册 `s32_empty`（无笔记）→ 登录拿 token →：

```bash
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/retrieval/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"函数的单调性"}'
```

Expected: `code=0`、`data.hits=[]`、HTTP 200。

- [ ] **Step 3: 验收笔记与 scope**

注册 `s32_student`，用其 token 创建笔记（`subject_id=7`、`folder="函数"`）：

```markdown
## 函数单调性

函数的单调性可以通过定义判断：任取 x1<x2，比较 f(x1) 与 f(x2)。

1. 已知函数 f(x)=x^2 在区间 [0,+∞) 上，判断其单调性并证明。
2. 求函数 f(x)=2x+1 的单调区间。
```

等 `index.note` 成功（psql 查 `async_tasks` 或轮询 `note_chunks` 数量 >0）。然后依次验证并记录命中块 id：

- 无 scope：命中；
- `subject_id=7`：命中；`subject_id=8`：空；
- `folder="函数"`：命中；`folder="数列"`：空；
- `start_date` 取创建日之后：空；覆盖当天：命中；
- `chunk_types=["question"]`：全部 `chunk_type=question`；`["formula"]`：不含 note 块。

- [ ] **Step 4: 重排、debug、权限**

- `rerank=false`：`rerank_info=null`，hits 顺序等于 fused 顺序；
- `rerank=true`：`rerank_info` 非空（记录 fallback 与 latency）；
- `debug=true`：`debug.vector/fulltext/fused` 非空；`debug` 缺省为 null；
- 匿名 401/40100；teacher 403/40300；student 200。

- [ ] **Step 5: P95 压测**

```bash
.\.venv\Scripts\python.exe scripts/retrieval_bench.py \
  --username s32_student --password *** --runs 20 --warmup 3 --no-rerank
```

把终端整段输出（每条 wall/server/embedding 与 P50/P95、PASS/FAIL）贴进 plan 执行记录。若 FAIL，记录实际 P95 与 `embedding_ms` 占比，不改口径、不删样本。

- [ ] **Step 6: 回归**

```bash
.\.venv\Scripts\python.exe scripts/ask.py --user-id <s32_student_id> "怎么判断函数的单调性？"
.\.venv\Scripts\python.exe scripts/retrieval_eval.py --user-id <s32_student_id>
```

Expected: 均能命中并正常结束；`ask.py` 引用块来自验收笔记。

- [ ] **Step 7: 文档同步**

- `docs/API.md` §5 新增 `POST /api/v1/retrieval/search`（字段表、响应、错误）；`POST /qa/ask` 的 scope 示例同步为 `{subject_id?, folder?, start_date?, end_date?}`，并注明检索实现见 S3-2。
- `docs/SCHEMA.md`：`note_chunks` 备注加「S3-2 检索 join `notes` 取 subject/folder/created_at，不在切片冗余」；无迁移。
- `docs/DECISIONS.md`：追加 **D-036**，含 8 条决策、scope 语义、P95 口径与实测数字、已知限制。
- `docs/PROGRESS.md`：状态改「S3-2 完成」、勾选 S3-2、变更日志（含实测 P95 与分项）、遗留问题（subject 为 NULL 的文档笔记、folder 自由文本、debug 体积、rerank 静默回退）。
- `AGENTS.md` §9.2 增补检索服务约定；§9.6 增补检索服务锚点（retriever/service/route 三件套）。
- `docs/AI协作开发实施计划.md` 第 14 章勾选 S3-2。
- `docs/spec/s3-2-retrieval-service.md`：§10 更新为实测限制（P95 实际值、样本数）；补 §11 实施记录。
- `docs/plan/s3-2-retrieval-service.md`：填 Execution Record（提交号、测试数、验收数字、偏移）。

- [ ] **Step 8: 清理验收数据**

删除 `s32_*` 账号、验收笔记、其 `note_chunks` 与 `async_tasks`；删除 token/临时 json 文件。库回到验收前基线（4 篇笔记）。

- [ ] **Step 9: 提交**

```bash
git add docs/API.md docs/SCHEMA.md docs/DECISIONS.md docs/PROGRESS.md AGENTS.md docs/AI协作开发实施计划.md docs/spec/s3-2-retrieval-service.md docs/plan/s3-2-retrieval-service.md
git commit -m "docs(s3-2): 检索服务验收记录与文档同步"
```

---

## Self-Review

- **Spec coverage**：接口契约 §6 → Task 3；scope 语义 → Task 1/2；service 编排 → Task 2；配置 → Task 2；P95 → Task 4/5；权限/空库 → Task 3/5；文档 → Task 5；已知限制 → Task 5。
- **类型一致性**：`RetrievalScope`（ai 层） vs `RetrievalScopeIn`（schema 层）命名已区分；`search_chunks` 参数与 route 调用一致；`RetrievalResult.embedding_ms` 在 Task 1 定义、Task 2 使用。
- **占位扫描**：无 TODO/TBD；每个代码步骤给出完整实现；重复测试已写全。
- **风险**：P95 可能因外部 Embedding 超标；Task 5 要求如实记录，不修改样本或口径。
---

## Execution Record（2026-10-31，本会话内联执行）

- 状态：Task 1–5 完成；实现按 plan，无范围外改动；无迁移、无新依赖、无前端改动。
- 提交：
  - `89bd774` feat(s3-2): 检索器支持 scope 过滤与向量耗时
  - `9bb5264` feat(s3-2): 检索服务与 scope 参数校验
  - `274361f` feat(s3-2): 学生检索接口
  - `25831db` feat(s3-2): 检索 P95 压测脚本
  - 文档提交：`docs(s3-2): 检索服务验收记录与文档同步`（本记录所在提交）
- 测试：`pytest -q` → **586 passed, 1 warning**；分文件 retriever 26、service 10、API 9。Task 1 全量 567、Task 2 全量 577、Task 3 全量 586。
- 验收数据（真实 Postgres/Redis + 真实 Embedding/Rerank；验收账号 `s32_student`，笔记 81，subject=7/folder=函数）：
  - `index.note` succeeded：2 块（note 287、question 288），80 tokens。
  - scope：no-scope / subject7 / folder-func / date-today → 2 命中（287、288）；subject8 / folder-seq / date-before / type-formula → 0；type-question → 仅 288。
  - rerank：`false` → `rerank_info=null`；`true` → qwen3-rerank、fallback=false、candidates=2、tokens=120、latency=193ms、scores 0.832/0.528。
  - debug：vector/fulltext/fused 各 2；vector_ms=3、fulltext_ms=2、embedding_ms=148。
  - 空库（`s32_empty`）：200 + 0 命中；匿名 401/40100（未提供认证凭据）；teacher 403/40300（无权访问该资源）。
  - P95（`--runs 20 --warmup 3 --no-rerank`）：wall P50=172ms / P95=229ms；server P50=163 / P95=223；embedding P50=154ms；PASS <500ms。
  - 回归：`ask.py --user-id 28` refused=否、llm_calls=1、引用 #81 两块、cost ¥0.001431；`retrieval_eval.py --user-id 28` 10 问完成（hit@5 2/10，rerank fallback 0/10，avg latency 155ms）。
- 偏移/偏差：
  1. 验收 Markdown 实际只产生 note+question 两块，没有 formula 块，故 `chunk_types=["formula"]` 为 0 命中；过滤语义仍成立。
  2. 首轮冷启动单次 441ms（jieba/连接冷），预热后 130–280ms；bench 按 spec 用预热 3 次后的 20 次样本。
  3. 计划代码主体无改写；service 实现时补了 `rerank_info` 仅在 `use_rerank` 时返回，避免 fake/异常路径泄漏（测试 `test_search_rerank_false_...` 覆盖）。
- 清理：验收用户 28/29/30、笔记 81、note_chunks、async_tasks、`llm_call_logs` 中对应 trace 保留（日志不删），临时 token/输出文件删除；库回到 4 篇笔记/37 块基线。
