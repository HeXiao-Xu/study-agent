# S1-4 混合检索 + RRF 融合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `note_chunks` 上实现向量检索 + jieba 全文检索，用 RRF 融合成统一排序，并提供 10 问三路对照评测脚本。

**Architecture:** `retriever.py` 用 SQLAlchemy ORM + pgvector 生成两条带 `user_id` 过滤的 SQL；`rrf_fuse()` 是只吃有序列表的纯函数，按 `chunk_id` 去重、按 `Σ 1/(60+rank)` 排序；`retrieval_eval.py` 复用同一检索器打印纯向量/纯全文/混合三路 top5。

**Tech Stack:** Python 3.11、SQLAlchemy 2.1、pgvector 0.5.1、PostgreSQL 16、jieba 0.42.1、Pydantic v2、pytest。

**Spec:** `docs/spec/s1-4-retrieval.md`

## Global Constraints

- 不改 SCHEMA、不加 Alembic 迁移；`subject_id` / `kp_ids` 过滤留到 S2-1。
- S1-3 的 `build_tsquery()` 与验收 SQL（`函数 & 单调性`）保持 `&` 语义，不改。
- S1-4 全文查询用 OR：`build_tsquery_or()`，token 去重后 ` | ` 连接。
- RRF 公式固定 `Σ 1/(60 + rank)`，**只认排名，不归一化原始分数**。
- `user_id` 是必填过滤条件，两条 SQL 都必须显式带 `WHERE user_id = ...`（AGENTS §4）。
- 所有测试零真实网络/数据库；真实调用只发生在 `retrieval_eval.py`。
- 不引入新依赖；不打印/提交任何 API Key；`.env` 不提交。
- 本项目按任务卡一次提交：各任务用测试做检查点，**只在 Task 7 统一 commit**，不逐个任务 commit。
- Windows 命令统一在 `backend/` 下执行：`..\.venv\Scripts\python.exe -m pytest ...`。
- 真实评测的问题与关键词在运行前固定；结果不好**不得改问题/关键词粉饰**，如实报告。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/app/core/config.py` | 默认 `DATABASE_URL` 用 `127.0.0.1`（IPv6 修复） |
| `backend/app/core/db.py` | engine 增加 `connect_timeout=5`（IPv6 卡死兜底） |
| `.env.example` | 同步 `DATABASE_URL` 为 `127.0.0.1` |
| `backend/app/utils/zh_tokenizer.py` | 追加 `build_tsquery_or()`，复用已有 `tokenize_zh` |
| `backend/app/ai/rag/retriever.py` | 检索数据模型、向量/全文查询、RRF 纯函数、`retrieve_hybrid()` |
| `backend/tests/test_db.py` | 守卫 `connect_timeout` 回归 |
| `backend/tests/test_zh_tokenizer.py` | 追加 OR 分词查询测试 |
| `backend/tests/test_retriever.py` | RRF 纯函数 + fake session 集成测试 |
| `scripts/retrieval_eval.py` | 10 问三路 top5 对照 + hit@5/MRR@5 |
| `docs/spec/s1-4-retrieval.md` | 追加实测回填 |
| `docs/DECISIONS.md` | 新增 D-017 |
| `docs/PROGRESS.md` | 进度、测试数、评测结论 |
| `AGENTS.md` | §9.6 回填 retriever 锚点 |

---

### Task 1: 修复 Windows localhost IPv6 连接卡死

**Files:**
- Modify: `backend/app/core/config.py:40`
- Modify: `backend/app/core/db.py:17-27`
- Modify: `.env.example` 的 `DATABASE_URL`
- Create: `backend/tests/test_db.py`
- Local only: `.env` 的 `DATABASE_URL`（不提交）

**Interfaces:**
- Consumes: `get_settings().database_url`
- Produces: `get_engine()` 创建的 engine 带 `connect_args={"connect_timeout": 5}`

**背景（已实测）：** `localhost` 先解析 `::1`，Docker 只发布 `127.0.0.1:5432`；psycopg 无超时会卡在 `wait_conn`。探针阶段已把 URL 改 `127.0.0.1`、engine 加 `connect_timeout=5`；本任务补回归测试并核对文件内容。

- [ ] **Step 1: 写回归测试**

Create `backend/tests/test_db.py`:

```python
"""S1-3/S1-4 数据库基座回归：Windows 下必须带连接超时，避免 IPv6 卡死。"""
from __future__ import annotations

from app.core import db


def test_engine_sets_connect_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    monkeypatch.setattr(db, "_engine", None)

    db.get_engine()

    assert captured["connect_args"] == {"connect_timeout": 5}
```

- [ ] **Step 2: 跑测试**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_db.py -v
```

Expected: `1 passed`（前置修复已落地；若失败，按 Step 3 核对代码）。

- [ ] **Step 3: 核对/补齐实现**

`backend/app/core/config.py` 第 40 行必须是：

```python
database_url: str = "postgresql+psycopg://study:study123@127.0.0.1:5432/study_agent"
```

`backend/app/core/db.py` 的 `get_engine()` 必须是：

```python
def get_engine() -> Engine:
    """惰性建引擎：import 模型/跑纯单测时不触发任何数据库连接。"""
    global _engine
    if _engine is None:
        # hide_parameters=True：异常信息里不出现连接参数（含密码）
        # connect_timeout：Windows 下 localhost 先解析 ::1，而 Docker 只发布 IPv4，
        # 无超时会卡死在 IPv6 的 wait_conn；5 秒后让 psycopg 回退 IPv4。
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
    return _engine
```

`.env.example` 的 `DATABASE_URL` 必须是：

```dotenv
DATABASE_URL=postgresql+psycopg://study:study123@127.0.0.1:5432/study_agent
```

本地 `.env` 只改 `DATABASE_URL` 行；本机已改为 `127.0.0.1`。换机时用编辑器改，
**不要用 `Set-Content` 重写整个 `.env`**（可能改变编码，中文注释/Key 有风险）：

```powershell
# 只读核对（密码打码），不要写回
Select-String -Path .env -Pattern '^DATABASE_URL=' |
    ForEach-Object { $_.Line -replace '(://)[^@]+@', '$1***@' }
```

Expected: `DATABASE_URL=postgresql+psycopg://***@127.0.0.1:5432/study_agent`。

- [ ] **Step 4: 真实连接冒烟**

```powershell
cd backend
..\.venv\Scripts\python.exe -c "from app.core.db import new_session; from sqlalchemy import text; s=new_session(); print(s.execute(text('select 1')).scalar()); s.close()"
```

Expected: 1 秒内输出 `1`（不再卡 60 秒）。

---

### Task 2: `build_tsquery_or()`：自然问句的 OR 全文查询

**Files:**
- Modify: `backend/app/utils/zh_tokenizer.py`
- Test: `backend/tests/test_zh_tokenizer.py`

**Interfaces:**
- Consumes: `tokenize_zh(text: str) -> list[str]`
- Produces: `build_tsquery_or(text: str) -> str`，token 去重、` | ` 连接、空文本返回 `""`

- [ ] **Step 1: 写失败测试**

Append to `backend/tests/test_zh_tokenizer.py`:

```python
def test_build_tsquery_or_dedupes_and_uses_or() -> None:
    query = build_tsquery_or("函数的定义域，函数的定义域")
    assert "|" in query
    assert "&" not in query
    parts = [part.strip() for part in query.split("|")]
    assert len(parts) == len(set(parts))
    assert parts.count("函数") == 1
    assert parts.count("定义域") == 1


def test_build_tsquery_or_empty() -> None:
    assert build_tsquery_or("  ，。！？ ") == ""
```

同时把文件顶部 import 改为：

```python
from app.utils.zh_tokenizer import build_tsquery, build_tsquery_or, join_for_tsv, tokenize_zh
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_zh_tokenizer.py -v
```

Expected: FAIL，`ImportError: cannot import name 'build_tsquery_or'`。

- [ ] **Step 3: 写最小实现**

在 `backend/app/utils/zh_tokenizer.py` 末尾追加：

```python
def build_tsquery_or(text: str) -> str:
    """查询侧：token 去重后 | 连接；用于自然问句全文检索（S1-4）。

    为什么用 OR：自然问句含“的/在/上/怎么”等词，AND 会要求所有词同块出现，
    实测 10 个问题全部 0 命中；OR 先召回，再由 ts_rank_cd 按覆盖密度排序。
    """
    return " | ".join(dict.fromkeys(tokenize_zh(text)))
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_zh_tokenizer.py -v
```

Expected: `9 passed`（原 7 + 新 2）。

---

### Task 3: 检索数据模型 + RRF 纯函数

**Files:**
- Create: `backend/app/ai/rag/retriever.py`
- Test: `backend/tests/test_retriever.py`

**Interfaces:**
- Produces:
  - `RetrievedChunk`（Pydantic）：`chunk_id, note_id, chunk_index, content, heading_path, page_no, chunk_type, vector_rank, vector_distance, fulltext_rank, fulltext_score, rrf_score`
  - `RetrievalResult`（Pydantic）：`query, tsquery, vector, fulltext, fused, elapsed_ms`
  - `rrf_fuse(vector_hits, fulltext_hits, *, k=60, final_k=None) -> list[RetrievedChunk]`
  - `RetrievalFilterUnavailable(ValueError)`

- [ ] **Step 1: 写失败测试（RRF 4 条）**

Create `backend/tests/test_retriever.py`:

```python
"""S1-4 检索器测试：RRF 纯函数 + fake session（spec §11）。"""
from __future__ import annotations

import pytest

from app.ai.rag.retriever import RetrievedChunk, rrf_fuse


def _hit(chunk_id: int, *, distance: float | None = None, ts: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=1,
        chunk_index=chunk_id,
        content=f"合成块 {chunk_id}",
        vector_distance=distance,
        fulltext_score=ts,
    )


def test_rrf_fuse_dedupes_and_sums_overlap() -> None:
    vector_hits = [_hit(i) for i in range(1, 21)]          # 1..20
    fulltext_hits = [_hit(i, ts=1.0) for i in range(16, 36)]  # 16..35，5 条重叠
    fused = rrf_fuse(vector_hits, fulltext_hits)

    assert len(fused) == 35
    by_id = {hit.chunk_id: hit for hit in fused}
    assert by_id[16].vector_rank == 16
    assert by_id[16].fulltext_rank == 1
    assert by_id[16].rrf_score == pytest.approx(1 / 76 + 1 / 61)
    assert by_id[1].rrf_score == pytest.approx(1 / 61)
    assert by_id[35].rrf_score == pytest.approx(1 / 80)


def test_rrf_fuse_keeps_single_path_hits() -> None:
    fused = rrf_fuse([_hit(1), _hit(2)], [_hit(3), _hit(4)])
    assert [hit.chunk_id for hit in fused] == [1, 3, 2, 4]
    assert {hit.chunk_id for hit in fused} == {1, 2, 3, 4}


def test_rrf_fuse_uses_rank_not_raw_score() -> None:
    vector_hits = [_hit(1, distance=0.99), _hit(2, distance=0.01)]
    fulltext_hits = [_hit(3, ts=0.01), _hit(4, ts=0.99)]

    assert [hit.chunk_id for hit in rrf_fuse(vector_hits, [])] == [1, 2]
    assert [hit.chunk_id for hit in rrf_fuse([], fulltext_hits)] == [3, 4]


def test_rrf_fuse_tie_break_is_stable() -> None:
    # 两条都是单路第 1，RRF 同分；最优单路名次也相同，按 chunk_id 升序
    fused = rrf_fuse([_hit(5)], [_hit(3)])
    assert [hit.chunk_id for hit in fused] == [3, 5]
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'app.ai.rag.retriever'`。

- [ ] **Step 3: 写最小实现**

Create `backend/app/ai/rag/retriever.py`:

```python
"""S1-4 混合检索：向量 + jieba 全文 + RRF 融合（spec docs/spec/s1-4-retrieval.md）。

RRF 只用排名，不归一化 distance / ts_rank；公式 score = Σ 1/(60 + rank_i)。
"""
from __future__ import annotations

import logging
import time

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.ai.embedding.errors import EmbeddingError
from app.core.config import get_settings
from app.models.note_chunk import NoteChunk
from app.utils.zh_tokenizer import build_tsquery_or

logger = logging.getLogger(__name__)

RRF_K = 60
DEFAULT_TOP_K = 20


class RetrievalFilterUnavailable(ValueError):
    """S1-4 只能下推 user_id；subject/kp 依赖 S2-1 的 notes/note_kps。"""


class RetrievedChunk(BaseModel):
    chunk_id: int
    note_id: int
    chunk_index: int
    content: str
    heading_path: str | None = None
    page_no: int | None = None
    chunk_type: str | None = None
    vector_rank: int | None = None
    vector_distance: float | None = None
    fulltext_rank: int | None = None
    fulltext_score: float | None = None
    rrf_score: float = 0.0


class RetrievalResult(BaseModel):
    query: str
    tsquery: str
    vector: list[RetrievedChunk]
    fulltext: list[RetrievedChunk]
    fused: list[RetrievedChunk]
    elapsed_ms: int


def rrf_fuse(
    vector_hits: list[RetrievedChunk],
    fulltext_hits: list[RetrievedChunk],
    *,
    k: int = RRF_K,
    final_k: int | None = None,
) -> list[RetrievedChunk]:
    """按 chunk_id 去重并融合两路排名；只认排名，不认原始分数。"""
    if k <= 0:
        raise ValueError("k 必须为正整数")
    if final_k is not None and final_k <= 0:
        raise ValueError("final_k 必须为正整数")

    merged: dict[int, RetrievedChunk] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        item = hit.model_copy(deep=True)
        item.vector_rank = rank
        item.rrf_score = 1.0 / (k + rank)
        merged[item.chunk_id] = item

    for rank, hit in enumerate(fulltext_hits, start=1):
        item = merged.get(hit.chunk_id)
        if item is None:
            item = hit.model_copy(deep=True)
            item.rrf_score = 0.0
            merged[item.chunk_id] = item
        item.fulltext_rank = rank
        item.fulltext_score = hit.fulltext_score
        item.rrf_score += 1.0 / (k + rank)

    def best_rank(item: RetrievedChunk) -> int:
        ranks = [r for r in (item.vector_rank, item.fulltext_rank) if r is not None]
        return min(ranks) if ranks else 10**9

    fused = sorted(
        merged.values(),
        key=lambda item: (-item.rrf_score, best_rank(item), item.chunk_id),
    )
    return fused[:final_k] if final_k is not None else fused
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -v
```

Expected: `4 passed`。

---

### Task 4: 向量/全文 SQL + `retrieve_hybrid()`

**Files:**
- Modify: `backend/app/ai/rag/retriever.py`
- Test: `backend/tests/test_retriever.py`

**Interfaces:**
- Consumes: Task 3 的 `RetrievedChunk` / `RetrievalResult` / `rrf_fuse`；S1-3 的 `EmbeddingClient`、`NoteChunk`、`build_tsquery_or`
- Produces: `retrieve_hybrid(session, query, *, user_id, top_k=20, final_k=None, client=None, subject_id=None, kp_ids=None) -> RetrievalResult`

- [ ] **Step 1: 追加失败测试（8 条集成/边界）**

在 `backend/tests/test_retriever.py` 顶部 import 改为：

```python
from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.ai.embedding.errors import EmbeddingError
from app.ai.rag.retriever import (
    RetrievalFilterUnavailable,
    RetrievedChunk,
    retrieve_hybrid,
    rrf_fuse,
)
from app.models.note_chunk import NoteChunk
```

在文件末尾追加：

```python
class FakeResult:
    def __init__(self, rows: list[tuple[NoteChunk, float]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[NoteChunk, float]]:
        return list(self._rows)


class FakeSession:
    def __init__(self, *results: FakeResult) -> None:
        self._results = list(results)
        self.statements: list[object] = []

    def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return self._results.pop(0)


class FakeClient:
    model = "fake-embed"
    dim = 1024

    def __init__(self, *, dim: int = 1024) -> None:
        self.dim = dim
        self.usage_tokens = 0
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], *, on_batch=None) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1] * self.dim for _ in texts]


def make_chunk(chunk_id: int, *, note_id: int = 1, index: int = 0, content: str = "函数的定义域") -> NoteChunk:
    return NoteChunk(
        id=chunk_id,
        note_id=note_id,
        user_id=1,
        chunk_index=index,
        content=content,
        token_count=10,
        chunk_type="note",
        heading_path="函数/定义域",
        page_no=1,
        embedding=[0.0] * 1024,
    )


def test_retrieve_hybrid_both_paths_hit() -> None:
    c1, c2, c3 = make_chunk(1), make_chunk(2), make_chunk(3)
    session = FakeSession(
        FakeResult([(c1, 0.1), (c2, 0.2)]),
        FakeResult([(c2, 0.9), (c3, 0.5)]),
    )
    client = FakeClient()

    result = retrieve_hybrid(session, "函数的定义域", user_id=1, client=client)

    assert [hit.chunk_id for hit in result.vector] == [1, 2]
    assert [hit.chunk_id for hit in result.fulltext] == [2, 3]
    assert result.fused[0].chunk_id == 2
    assert result.fused[0].vector_rank == 2
    assert result.fused[0].fulltext_rank == 1
    assert result.fused[0].rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert "|" in result.tsquery
    assert client.calls == [["函数的定义域"]]


def test_query_filters_use_user_id_and_limits() -> None:
    session = FakeSession(FakeResult([]), FakeResult([]))
    retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(), top_k=20)

    vector_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    fulltext_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    vector_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    fulltext_params = session.statements[1].compile(dialect=postgresql.dialect()).params

    assert "<=>" in vector_sql
    assert "@@" in fulltext_sql
    assert "ts_rank_cd" in fulltext_sql.lower()
    assert "LIMIT" in vector_sql.upper()
    assert "LIMIT" in fulltext_sql.upper()
    assert 1 in vector_params.values()
    assert 1 in fulltext_params.values()


def test_rejects_subject_and_kp_filters() -> None:
    client = FakeClient()
    with pytest.raises(RetrievalFilterUnavailable, match="S2-1"):
        retrieve_hybrid(FakeSession(), "函数的定义域", user_id=1, client=client, subject_id=3)
    with pytest.raises(RetrievalFilterUnavailable, match="S2-1"):
        retrieve_hybrid(FakeSession(), "函数的定义域", user_id=1, client=client, kp_ids=[1, 2])
    assert client.calls == []


def test_empty_query_returns_empty_without_embedding() -> None:
    session = FakeSession()
    client = FakeClient()
    result = retrieve_hybrid(session, "   ", user_id=1, client=client)
    assert result.vector == []
    assert result.fulltext == []
    assert result.fused == []
    assert result.elapsed_ms == 0
    assert session.statements == []
    assert client.calls == []


def test_skips_fulltext_when_no_tokens() -> None:
    session = FakeSession(FakeResult([(make_chunk(1), 0.1)]))
    result = retrieve_hybrid(session, "！！！？？？", user_id=1, client=FakeClient())
    assert len(session.statements) == 1
    assert result.fulltext == []
    assert result.tsquery == ""
    assert [hit.chunk_id for hit in result.fused] == [1]


def test_final_k_truncates_fused_only() -> None:
    session = FakeSession(
        FakeResult([(make_chunk(1), 0.1), (make_chunk(2), 0.2), (make_chunk(3), 0.3)]),
        FakeResult([(make_chunk(4), 0.9), (make_chunk(5), 0.8)]),
    )
    result = retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(), final_k=2)
    assert len(result.fused) == 2
    assert len(result.vector) == 3
    assert len(result.fulltext) == 2


def test_dimension_mismatch_raises_embedding_error() -> None:
    session = FakeSession()
    with pytest.raises(EmbeddingError, match="维度"):
        retrieve_hybrid(session, "函数的定义域", user_id=1, client=FakeClient(dim=8))
    assert session.statements == []


def test_invalid_top_k_raises_value_error() -> None:
    with pytest.raises(ValueError, match="top_k"):
        retrieve_hybrid(FakeSession(), "函数", user_id=1, client=FakeClient(), top_k=0)
    with pytest.raises(ValueError, match="final_k"):
        retrieve_hybrid(FakeSession(), "函数", user_id=1, client=FakeClient(), final_k=0)
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -v
```

Expected: FAIL，`ImportError: cannot import name 'RetrievalFilterUnavailable'` / `retrieve_hybrid`。

- [ ] **Step 3: 实现两条 SQL 与编排**

在 `backend/app/ai/rag/retriever.py` 末尾追加：

```python
def _to_chunk(
    chunk: NoteChunk,
    *,
    vector_rank: int | None = None,
    vector_distance: float | None = None,
    fulltext_rank: int | None = None,
    fulltext_score: float | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        note_id=chunk.note_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        heading_path=chunk.heading_path,
        page_no=chunk.page_no,
        chunk_type=chunk.chunk_type,
        vector_rank=vector_rank,
        vector_distance=vector_distance,
        fulltext_rank=fulltext_rank,
        fulltext_score=fulltext_score,
    )


def _vector_search(
    session: Session,
    query_vector: list[float],
    *,
    user_id: int,
    top_k: int,
) -> list[RetrievedChunk]:
    distance = NoteChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(NoteChunk, distance)
        .where(NoteChunk.user_id == user_id)
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
) -> list[RetrievedChunk]:
    tsquery = func.to_tsquery("simple", tsquery_str)
    score = func.ts_rank_cd(NoteChunk.tsv, tsquery).label("fulltext_score")
    stmt = (
        select(NoteChunk, score)
        .where(NoteChunk.user_id == user_id, NoteChunk.tsv.op("@@")(tsquery))
        .order_by(score.desc(), NoteChunk.id.asc())
        .limit(top_k)
    )
    rows = session.execute(stmt).all()
    return [
        _to_chunk(row[0], fulltext_rank=rank, fulltext_score=float(row[1]))
        for rank, row in enumerate(rows, start=1)
    ]


def retrieve_hybrid(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    final_k: int | None = None,
    client: EmbeddingClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult:
    """两路检索 + RRF；user_id 必填，subject/kp 在 S2-1 前不可用。"""
    if subject_id is not None or kp_ids:
        raise RetrievalFilterUnavailable(
            "S1-4 仅支持 user_id 过滤；subject_id/kp_ids 需要 S2-1 的 notes/note_kps 表"
        )
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")
    if final_k is not None and final_k <= 0:
        raise ValueError("final_k 必须为正整数")

    query = query.strip()
    if not query:
        return RetrievalResult(
            query="",
            tsquery="",
            vector=[],
            fulltext=[],
            fused=[],
            elapsed_ms=0,
        )

    started = time.perf_counter()
    settings = get_settings()
    embedding_client = client or get_embedding_client()
    query_vector = embedding_client.encode([query])[0]
    if len(query_vector) != settings.embedding_dim:
        raise EmbeddingError(
            f"查询向量维度不符：期望 {settings.embedding_dim}，实际 {len(query_vector)}",
            retryable=False,
        )

    vector_hits = _vector_search(session, query_vector, user_id=user_id, top_k=top_k)
    tsquery_str = build_tsquery_or(query)
    fulltext_hits = (
        _fulltext_search(session, tsquery_str, user_id=user_id, top_k=top_k)
        if tsquery_str
        else []
    )
    fused = rrf_fuse(vector_hits, fulltext_hits, final_k=final_k)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    logger.info(
        "retrieval_done",
        extra={
            "scene": "retrieve",
            "user_id": user_id,
            "top_k": top_k,
            "vector_hits": len(vector_hits),
            "fulltext_hits": len(fulltext_hits),
            "fused_hits": len(fused),
            "tsquery": tsquery_str,
            "latency_ms": elapsed_ms,
        },
    )
    return RetrievalResult(
        query=query,
        tsquery=tsquery_str,
        vector=vector_hits,
        fulltext=fulltext_hits,
        fused=fused,
        elapsed_ms=elapsed_ms,
    )
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -v
```

Expected: `12 passed`。

- [ ] **Step 5: 全量回归**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: `93 passed`（78 + 15）；若数量不同，以实际为准但不得 FAIL。

---

### Task 5: `retrieval_eval.py` 三路对照评测

**Files:**
- Create: `scripts/retrieval_eval.py`

**Interfaces:**
- Consumes: `retrieve_hybrid()`、`get_embedding_client()`、`new_session()`
- Produces: CLI 输出三路 top5 + hit@5/MRR@5；只读，不写库

- [ ] **Step 1: 写评测脚本**

Create `scripts/retrieval_eval.py`:

```python
"""S1-4 评测：10 个真实问题，纯向量 / 纯全文 / 混合三路 top5 对照（spec §10）。

用法（仓库根目录）：
    python scripts/retrieval_eval.py [--user-id 1] [--top-k 20] [--debug]

注意：问题与关键词在运行前固定；结果不理想时不要改它们粉饰。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.rag.retriever import RetrievalResult, retrieve_hybrid  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402

QUESTIONS: list[tuple[str, list[str]]] = [
    ("函数的定义域怎么求？", ["定义域"]),
    ("函数单调性的定义是什么？", ["单调性"]),
    ("如何用定义证明函数在区间上单调递增？", ["单调递增", "增函数"]),
    ("奇函数和偶函数有什么性质？", ["奇函数", "偶函数"]),
    ("二次函数在闭区间上的最值怎么求？", ["最大值", "最小值"]),
    ("分段函数 f(f(-1)) 怎么求？", ["f(f(-1))"]),
    ("函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？", ["单调递增", "单调性"]),
    ("已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？", ["解析式"]),
    ("函数图象关于原点对称说明什么？", ["原点", "奇函数"]),
    ("商品定价最大利润问题怎么建模？", ["利润"]),
]


def _snippet(text: str, limit: int = 80) -> str:
    return " ".join(text.split())[:limit]


def _print_hits(title: str, hits: list, *, limit: int, kind: str) -> None:
    print(f"  {title}")
    if not hits:
        print("    （无命中）")
        return
    for rank, hit in enumerate(hits[:limit], start=1):
        if kind == "vector":
            score = f"d={hit.vector_distance:.4f}" if hit.vector_distance is not None else "d=-"
        elif kind == "fulltext":
            score = f"ts={hit.fulltext_score:.4f}" if hit.fulltext_score is not None else "ts=-"
        else:
            score = (
                f"rrf={hit.rrf_score:.5f} "
                f"v={hit.vector_rank or '-'} f={hit.fulltext_rank or '-'}"
            )
        heading = (hit.heading_path or "-")[:40]
        print(
            f"    {rank}. note={hit.note_id} chunk={hit.chunk_index} "
            f"heading={heading} {score}"
        )
        print(f"       {_snippet(hit.content)}")


def _first_hit_rank(hits: list, keywords: list[str], *, limit: int = 5) -> int:
    for rank, hit in enumerate(hits[:limit], start=1):
        content = hit.content.lower()
        if any(keyword.lower() in content for keyword in keywords):
            return rank
    return 0


def _print_summary(ranks: dict[str, list[int]]) -> None:
    total = len(QUESTIONS)
    print("=" * 78)
    print(f"汇总（{total} 问，hit@5 / MRR@5）")
    for name in ("vector", "fulltext", "hybrid"):
        values = ranks[name]
        hits = sum(1 for rank in values if rank)
        mrr = sum(1 / rank for rank in values if rank) / total
        print(f"  {name:9s} hit@5={hits}/{total}  MRR@5={mrr:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-4 混合检索三路对照评测")
    parser.add_argument("--user-id", type=int, default=1, help="用户 ID（默认 1）")
    parser.add_argument("--top-k", type=int, default=20, help="每路候选数（默认 20）")
    parser.add_argument("--debug", action="store_true", help="打印每路完整 top_k 与 RRF 明细")
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k 必须为正整数")

    set_trace_id("retrieval-eval-" + uuid.uuid4().hex[:12])
    limit = args.top_k if args.debug else 5
    ranks: dict[str, list[int]] = {"vector": [], "fulltext": [], "hybrid": []}

    try:
        client = get_embedding_client()
        with new_session() as session:
            for index, (question, keywords) in enumerate(QUESTIONS, start=1):
                result: RetrievalResult = retrieve_hybrid(
                    session,
                    question,
                    user_id=args.user_id,
                    top_k=args.top_k,
                    client=client,
                )
                vector_rank = _first_hit_rank(result.vector, keywords)
                fulltext_rank = _first_hit_rank(result.fulltext, keywords)
                hybrid_rank = _first_hit_rank(result.fused, keywords)
                ranks["vector"].append(vector_rank)
                ranks["fulltext"].append(fulltext_rank)
                ranks["hybrid"].append(hybrid_rank)

                print(f"\n[{index}/{len(QUESTIONS)}] {question}")
                print(f"  tsquery: {result.tsquery or '（空）'}")
                _print_hits("纯向量 top5", result.vector, limit=limit, kind="vector")
                _print_hits("纯全文 top5", result.fulltext, limit=limit, kind="fulltext")
                _print_hits("混合 top5", result.fused, limit=limit, kind="hybrid")
                print(
                    f"  命中: vector={vector_rank or '-'} "
                    f"fulltext={fulltext_rank or '-'} hybrid={hybrid_rank or '-'}"
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

    _print_summary(ranks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 语法与帮助冒烟**

```powershell
cd E:\BiShe-AIStudy\study-agent
..\.venv\Scripts\python.exe scripts\retrieval_eval.py --help
```

Expected: 打印 `--user-id / --top-k / --debug`，退出码 0，不连接数据库。

- [ ] **Step 3: 跑真实 10 问**

```powershell
cd E:\BiShe-AIStudy\study-agent
..\.venv\Scripts\python.exe scripts\retrieval_eval.py
```

Expected: 10 题各打印三路 top5；末尾三行 `hit@5 / MRR@5`；无异常。**记录实际数字，不要预设。**

- [ ] **Step 4: 空用户过滤冒烟**

```powershell
..\.venv\Scripts\python.exe scripts\retrieval_eval.py --user-id 999
```

Expected: 三路都无命中（`hit@5=0/10`），证明 `user_id` 下推生效；仍会调用 10 次 Embedding，属正常。

---

### Task 6: 真实验收与用户肉眼判断

**Files:** 无代码改动

**Interfaces:**
- Consumes: Task 5 的真实输出
- Produces: 用户对“混合是否更好”的确认；实测数字供 Task 7 回填

- [ ] **Step 1: 核对基础服务**

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
docker exec study-agent-postgres psql -U study -d study_agent -c "SELECT count(*) FROM note_chunks;"
```

Expected: `study-agent-postgres` 为 `Up (healthy)`；`note_chunks` 38 行。

- [ ] **Step 2: 跑全量测试**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: 全绿（预期 93 passed）。

- [ ] **Step 3: 跑三路评测并保存输出**

```powershell
cd E:\BiShe-AIStudy\study-agent
..\.venv\Scripts\python.exe scripts\retrieval_eval.py | Tee-Object -FilePath eval\results\s1-4-retrieval-eval.txt
```

Expected: 生成 `eval/results/s1-4-retrieval-eval.txt`；同时终端可见三路对照。
该文件提交（是真实评测记录，不含 Key；若含学生姓名/学校，先脱敏再提交）。

- [ ] **Step 4: 用户肉眼验收**

把三路 top5 与汇总贴给用户，逐题看：
- 纯向量是否语义相关
- 纯全文是否命中术语
- 混合是否至少不差于两路中较好者；若更好，指出具体题号
- 若混合没有更好，如实说明原因（38 块太小/两路都命中），不修改问题或关键词

等待用户明确认可后进入 Task 7。

---

### Task 7: 文档归档与提交

**Files:**
- Modify: `docs/spec/s1-4-retrieval.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/PROGRESS.md`
- Modify: `AGENTS.md` §9.6
- Modify: `docs/plan/s1-4-retrieval.md`（若实测测试数不同，回填实际值）
- Add: `eval/results/s1-4-retrieval-eval.txt`（Task 6 生成）
- Add: `eval/results/s1-4-retrieval-eval-empty-user.txt`（空用户过滤对照）
- Commit: 全部 S1-4 变更

**Interfaces:**
- Consumes: Task 6 的真实输出与测试数
- Produces: 可追溯的 spec/plan/DECISIONS/PROGRESS/AGENTS 记录 + 一次提交

- [ ] **Step 1: spec 追加实测回填**

在 `docs/spec/s1-4-retrieval.md` 末尾追加 `## 18. 实施回填（实测）`，写入 Task 6 的真实数据：

```markdown
## 18. 实施回填（实测）

- 日期：2026-10-20
- 测试：`pytest` 实际 N passed（现有 78 + 新增 M）
- 真实数据：note_chunks 38 块（试卷 23 / 笔记 6 / 教材页 9），user_id=1
- 10 问三路汇总：vector hit@5=a/10 MRR@5=x；fulltext hit@5=b/10 MRR@5=y；hybrid hit@5=c/10 MRR@5=z
- 混合结论：<逐题/整体判断；若未超过两路，写明具体原因，禁止粉饰>
- 典型差异题：<题号 + 三路 top1 的 note/chunk + 为什么>
- 空用户：`--user-id 999` 三路均 0 命中
- RRF 抽查：<至少 1 个重叠块的 v_rank/f_rank/rrf，验证 1/(60+v)+1/(60+f)>
- 备注：<停用词/噪声/38 块规模等观察>
```

数字必须来自 Task 6 的实际输出，禁止编造。

- [ ] **Step 2: DECISIONS 新增 D-017**

在 `docs/DECISIONS.md` 的 D-016 之后追加：

```markdown
## D-017 S1-4 混合检索与 RRF 实现决策（spec §8/§10/§14 归档）

- 日期：2026-10-20（S1-4 实现验收后归档；spec 见 docs/spec/s1-4-retrieval.md）
- 决策 1（RRF 只认排名）：`score = Σ 1/(60 + rank_i)`，按 chunk_id 去重；不把 cosine distance 与 ts_rank_cd 归一化相加（量纲不同、可被单路高分绑架）。公式与数值例子写入 spec §8。
- 决策 2（全文 OR 语义）：S1-3 的 `build_tsquery()` 保持 `&`（验收 SQL 不变）；S1-4 新增 `build_tsquery_or()`，token 去重后 ` | ` 连接，`ts_rank_cd` 排序。实测自然问句用 AND 10/10 零命中，OR 才有召回。
- 决策 3（subject_id/kp_ids 延后）：note_chunks 无这两列，notes/note_kps 属 S2-1；S1-4 只下推 user_id，传入 subject/kp 时抛 `RetrievalFilterUnavailable`，不静默忽略。
- 决策 4（两路串行）：任务卡“并行”理解为两路都执行；同一 Session 非线程安全，38 块下串行延迟可忽略，S1-5/S3 再考虑多连接并发。
- 决策 5（无新依赖）：复用 SQLAlchemy/pgvector/jieba/Pydantic；不引入 rerank/框架。
- 已知观察（环境）：Windows localhost 先解析 ::1，Docker 只发布 IPv4，psycopg 无超时会卡死；DATABASE_URL 改 127.0.0.1 + engine `connect_timeout=5`，`test_db.py` 守卫。
- 验证：pytest 实际 N/N；10 问三路 hit@5/MRR@5；空 user 0 命中；RRF 抽查（详见 PROGRESS 2026-10-20）。
```

- [ ] **Step 3: PROGRESS 更新**

- 顶部“最近完成”改为 S1-4，下一步 S1-5
- 勾选 `- [ ] S1-4 混合检索 + RRF 融合`
- 末尾追加 `### 2026-10-20` 条目，写交付、测试数、10 问实测数字、混合结论、发现的问题/偏离

- [ ] **Step 4: AGENTS §9.6 回填**

在“ai Embedding 适配器样例”之后追加：

```markdown
- RAG 检索器样例：backend/app/ai/rag/retriever.py（向量 + 全文 + RRF；user_id 过滤下推；RRF 纯函数只认排名）
```

- [ ] **Step 5: 最终回归**

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: 与 Task 6 相同的全绿数字；不得新增 FAIL。

- [ ] **Step 6: 检查无 Key/无敏感信息**

```powershell
cd E:\BiShe-AIStudy\study-agent
git diff --stat
git diff -- .env.example backend/app/core/config.py backend/app/core/db.py
```

- 确认 `.env` 没有被 `git add`
- 确认评测输出不含学生姓名/学校/联系方式；若有，脱敏或删除该行
- 确认没有 `sk-` 开头的真实 Key

- [ ] **Step 7: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add .env.example backend/app/core/config.py backend/app/core/db.py `
        backend/app/utils/zh_tokenizer.py backend/app/ai/rag/retriever.py `
        backend/tests/test_db.py backend/tests/test_zh_tokenizer.py backend/tests/test_retriever.py `
        scripts/retrieval_eval.py eval/results/s1-4-retrieval-eval.txt `
        eval/results/s1-4-retrieval-eval-empty-user.txt `
        docs/spec/s1-4-retrieval.md docs/plan/s1-4-retrieval.md `
        docs/DECISIONS.md docs/PROGRESS.md AGENTS.md
git commit -m "feat(s1-4): 混合检索与 RRF 融合（向量 + jieba 全文）"
git status --short
```

Expected: 提交成功，工作区干净；`.env` 不在提交中。

---

## Plan Self-Review

**Spec coverage：**

- §1 目标：Task 3–6 覆盖向量/全文/RRF/10 问
- §2 范围：Task 1–7；无 rerank/API/SCHEMA
- §3 冲突：subject/kp 异常在 Task 4；OR 在 Task 2；IPv6 在 Task 1
- §4 架构：Task 3–4
- §5 模型/接口：Task 3–4 精确签名
- §6 向量 SQL：Task 4 `_vector_search`
- §7 全文 SQL/OR：Task 2 + Task 4 `_fulltext_search`
- §8 RRF：Task 3 `rrf_fuse` + 4 条测试
- §9 过滤/错误/日志：Task 4
- §10 评测：Task 5–6
- §11 测试：Task 3–4 + 2 + 1
- §12 配置/依赖：Task 1、无新依赖
- §13 验收：Task 6–7
- §14 偏离：Task 1–4 + Task 7 D-017
- §15 风险：Task 6 如实记录 + Task 7 备注
- §16 契约关系：Task 7 docs

**Placeholder scan：** 代码步骤均给出可执行代码；无 TBD/TODO。Task 7 的 `<...>` 是实测数据占位，必须由 Task 6 真实输出替换，不属于代码占位。

**Type consistency：**

- `RetrievedChunk` 字段在 Task 3 定义，Task 4 `_to_chunk` / eval 使用一致
- `RetrievalResult` 字段在 Task 3 定义，Task 4 返回、Task 5 消费一致
- `rrf_fuse(vector_hits, fulltext_hits, *, k, final_k)` 在 Task 3 定义，Task 4 调用一致
- `retrieve_hybrid` 参数在 Task 4 定义，Task 5 调用一致
- `build_tsquery_or` 在 Task 2 定义，Task 4 调用一致
- `FakeSession.execute` 返回 `FakeResult`，与 `_vector_search` / `_fulltext_search` 的 `.all()` 一致
- `NoteChunk` 字段与 `make_chunk` 一致

**测试数自检：** 现有 78 + Task 1 1 + Task 2 2 + Task 3 4 + Task 4 8 = 93。若实际新增用例拆分不同，以实测为准并回填 plan/spec。