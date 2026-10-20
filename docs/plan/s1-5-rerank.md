# S1-5 Rerank 接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在 S1-4 混合检索之后接入 qwen3-rerank：RRF 取 top-30 → 一次批量重排 → 返回 top-6；失败回退 RRF 顺序，并在 75 块样张上跑四路对照。

**Architecture:** 新增 `app/ai/rerank/client.py`（契约 + DashScope 适配器 + 本地占位 + 门面）；`retrieve_hybrid()` 保持 S1-4 行为不变，新增 `retrieve_hybrid_reranked()` 做“RRF 全量 → top30 → rerank → top6”；结果增加 `reranked`、`rerank_info`、`rerank_score` 与两路 SQL 耗时。失败只降级，不拖垮检索。

**Tech Stack:** Python 3.11、httpx、tiktoken、Pydantic v2、SQLAlchemy 2.0、pytest；厂商 API 为 DashScope qwen3-rerank。无新增依赖。

**Spec:** `docs/spec/s1-5-rerank.md`（用户已确认；语料已扩到 75 块）

## Global Constraints

- 解释器：`E:\BiShe-AIStudy\study-agent\.venv\Scripts\python.exe`；测试命令在 `backend/` 下执行。
- 不新增依赖：只用已有的 `httpx`、`tiktoken`、`pydantic`、`pytest`。
- 默认模型 `qwen3-rerank`；单条 4,000 tokens，代码截断到 **3,600**；候选最多 30；最终 top-6。
- 重排失败/超时/无 Key/本地占位/坏响应：回退 `fused[:6]`，`fallback=True`，打日志，不抛给调用方。
- 所有 HTTP 测试用 `httpx.MockTransport`，测试套件零真实网络；真实 API 只在 Task 6 评测脚本里调用。
- 不改 SCHEMA/API；`rerank_score` 只在内存；不写库、不做拒答阈值。
- 不改 S1-4 `retrieve_hybrid()` 的默认结果；新增字段全部有默认值。
- 不提交 `.env`、Key、真实校名/姓名、仓库外生成的 DOCX。
- 项目约定：**所有子任务完成后只提交一次**（Conventional Commit，用户负责 `git push`）。
- 语料现状：75 块 / 6 个 note（101–106）；新增 104–106 是合成样张，评测结论必须标注“样张”。
- 真实评测输出中的真实校名/姓名要人工替换为“某中学/某同学”后才能入库；不要把真实字符串写进脚本或文档。
- 任何一步失败：先报告实际输出，不跳过测试、不伪造数字。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `backend/app/ai/rerank/client.py` | `RerankError`、`RerankCandidate`、`RerankScore`、`RerankResponse`、`RerankClient`、`DashScopeRerankClient`、`LocalRerankClient`、`get_rerank_client` |
| `backend/app/ai/rerank/__init__.py` | 门面导出，业务层只从这里 import |
| `backend/app/core/config.py` | `RERANK_*` 配置与 Key 回退 |
| `.env.example` | 新增 Rerank 环境变量模板 |
| `backend/app/ai/rag/retriever.py` | 结果模型扩展、`rerank_fused()`、`retrieve_hybrid_reranked()`、两路计时 |
| `backend/tests/test_rerank.py` | Client / 截断 / 重试 / 解析 / 本地占位（计划 10 条；实际 17，补了坏响应、越界、429、正文泄漏、tokenizer、结果不足等边界） |
| `backend/tests/test_retriever.py` | `rerank_fused` 与新入口（8 条，叠加在 S1-4 12 条上） |
| `backend/tests/test_config.py` | Rerank 默认值与 Key 回退（3 条，叠加在 S1-3 5 条上） |
| `backend/tests/test_eval_script.py` | 执行中补的 Windows UTF-8 输出回归（1 条，真实运行发现） |
| `scripts/retrieval_eval.py` | 四路评测 + 耗时/tokens/费用/fallback 汇总 |
| `docs/spec/s1-5-rerank.md` | 已写；Task 7 追加实测回填 |
| `docs/PROGRESS.md` | S1-5 完成状态与实测数字 |
| `docs/DECISIONS.md` | D-018 |
| `AGENTS.md` | §9.6 增加 rerank 适配器锚点 |
| `eval/results/s1-5-rerank-eval.txt` | 真实四路评测输出（脱敏后提交） |

---

### Task 1: Rerank 配置与 `.env.example`

**Files:**
- Modify: `backend/app/core/config.py:55-78`
- Modify: `.env.example:42-51`
- Test: `backend/tests/test_config.py`（追加 3 条）

**Interfaces:**
- Produces: `Settings.rerank_provider`、`rerank_api_key`、`rerank_base_url`、`rerank_model`、`rerank_timeout_seconds`、`rerank_max_retries`、`rerank_max_doc_tokens`、`rerank_candidates`、`rerank_top_k`、`rerank_price_per_million`
- Consumes: 现有 `Settings` / `_fallback_dashscope_key` 模式

- [x] **Step 1: 写失败测试**

在 `backend/tests/test_config.py` 追加：

```python
def test_rerank_defaults(monkeypatch) -> None:
    for name in ("RERANK_API_KEY", "DASHSCOPE_API_KEY", "RERANK_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.rerank_provider == "dashscope"
    assert s.rerank_model == "qwen3-rerank"
    assert s.rerank_base_url == "https://dashscope.aliyuncs.com/api/v1"
    assert s.rerank_timeout_seconds == 30.0
    assert s.rerank_max_retries == 2
    assert s.rerank_max_doc_tokens == 3600
    assert s.rerank_candidates == 30
    assert s.rerank_top_k == 6
    assert s.rerank_price_per_million == 0.5


def test_rerank_key_falls_back_to_dashscope(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-rerank-fallback")
    s = Settings(_env_file=None)
    assert s.rerank_api_key == "sk-test-rerank-fallback"
    assert "sk-test-rerank-fallback" not in repr(s)


def test_rerank_key_explicit_wins_and_repr_hides(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_API_KEY", "sk-test-rerank-explicit")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    s = Settings(_env_file=None)
    assert s.rerank_api_key == "sk-test-rerank-explicit"
    assert "sk-test-rerank-explicit" not in repr(s)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: FAIL，`AttributeError: 'Settings' object has no attribute 'rerank_provider'`。

- [x] **Step 3: 实现配置**

在 `backend/app/core/config.py` 的 Embedding 字段之后加：

```python
    # --- Rerank（S1-5；厂商 API，本地仅占位）---
    rerank_provider: Literal["dashscope", "local"] = "dashscope"
    rerank_api_key: str = Field(default="", repr=False)
    rerank_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    rerank_model: str = "qwen3-rerank"
    rerank_timeout_seconds: float = 30.0
    rerank_max_retries: int = 2
    rerank_max_doc_tokens: int = 3600
    rerank_candidates: int = 30
    rerank_top_k: int = 6
    rerank_price_per_million: float = 0.5
```

在现有 `_fallback_dashscope_key()` 末尾、`return self` 之前追加：

```python
        if not self.rerank_api_key:
            self.rerank_api_key = self.dashscope_api_key
```

- [x] **Step 4: 同步 `.env.example`**

在 Embedding 段之后追加：

```dotenv
# ===== Rerank（S1-5；Key 只放 .env，禁止提交）=====
RERANK_PROVIDER=dashscope
RERANK_API_KEY=
RERANK_BASE_URL=https://dashscope.aliyuncs.com/api/v1
RERANK_MODEL=qwen3-rerank
RERANK_TIMEOUT_SECONDS=30
RERANK_MAX_RETRIES=2
RERANK_MAX_DOC_TOKENS=3600
RERANK_CANDIDATES=30
RERANK_TOP_K=6
RERANK_PRICE_PER_MILLION=0.5
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: `8 passed`（原 5 + 新 3）。

---

### Task 2: Rerank 契约、异常与本地占位

**Files:**
- Create: `backend/app/ai/rerank/client.py`
- Create: `backend/app/ai/rerank/__init__.py`
- Test: `backend/tests/test_rerank.py`（先建文件，1 条用例）

**Interfaces:**
- Produces:
  - `RerankError(message: str, *, provider: str = "dashscope", status_code: int | None = None, retryable: bool = False)`
  - `RerankCandidate(id: int, content: str)`
  - `RerankScore(id: int, score: float)`
  - `RerankResponse(model: str, scores: list[RerankScore], tokens: int, latency_ms: int, cost_yuan: float)`
  - `RerankClient.rerank(query: str, candidates: list[RerankCandidate], *, top_n: int | None = None) -> RerankResponse`
  - `LocalRerankClient`
- Consumes: 无

- [x] **Step 1: 写失败测试**

新建 `backend/tests/test_rerank.py`：

```python
"""S1-5 Rerank 适配器测试：HTTP 全 mock（spec §8.1）。"""
from __future__ import annotations

import pytest

from app.ai.rerank import LocalRerankClient, RerankCandidate, RerankError


def test_local_rerank_raises() -> None:
    with pytest.raises(RerankError, match="占位"):
        LocalRerankClient().rerank("查询", [RerankCandidate(id=1, content="候选")])
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_rerank.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'app.ai.rerank'`。

- [x] **Step 3: 实现契约与本地占位**

创建 `backend/app/ai/rerank/client.py`：

```python
"""S1-5 Rerank 适配器：DashScope qwen3-rerank + 本地占位（spec §5）。

截断/重试/解析/降级全部在适配器边界处理；业务层只依赖 RerankClient。
"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
import tiktoken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0
_MAX_DOCUMENTS = 500
_encoding: tiktoken.Encoding | None = None


class RerankError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "dashscope",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class RerankCandidate:
    id: int
    content: str


@dataclass(frozen=True)
class RerankScore:
    id: int
    score: float


@dataclass(frozen=True)
class RerankResponse:
    model: str
    scores: list[RerankScore] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0


class RerankClient(ABC):
    model: str

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        """一次请求重排全部候选；返回按 score 降序的 [(id, score)]。"""


class LocalRerankClient(RerankClient):
    model = "local"

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        raise RerankError(
            "LocalRerankClient 为占位实现：本次不引入本地重排模型",
            provider="local",
            retryable=False,
        )
```

创建 `backend/app/ai/rerank/__init__.py`（Task 3 再补 DashScope 与门面的导出）：

```python
"""Rerank 适配器（AGENTS §3/§9.6）：业务层只从这里 import。"""
from app.ai.rerank.client import (
    LocalRerankClient,
    RerankCandidate,
    RerankClient,
    RerankError,
    RerankResponse,
    RerankScore,
)

__all__ = [
    "LocalRerankClient",
    "RerankCandidate",
    "RerankClient",
    "RerankError",
    "RerankResponse",
    "RerankScore",
]
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_rerank.py -q
```

Expected: `1 passed`。

---

### Task 3: DashScopeRerankClient（批量、截断、重试、解析、费用）

**Files:**
- Modify: `backend/app/ai/rerank/client.py`
- Modify: `backend/app/ai/rerank/__init__.py`
- Test: `backend/tests/test_rerank.py`（再追加 9 条，总计 10 条）

**Interfaces:**
- Produces:
  - `DashScopeRerankClient(api_key, base_url, model="qwen3-rerank", timeout=30.0, max_retries=2, max_doc_tokens=3600, price_per_million=0.5, transport=None, sleep=time.sleep)`
  - `get_rerank_client() -> RerankClient`
  - `DashScopeRerankClient.request_count`、`usage_tokens`
- Consumes: Task 2 的契约；`Settings` 的 Rerank 字段

- [x] **Step 1: 追加失败测试**

在 `backend/tests/test_rerank.py` 补 import 与测试：

```python
import json

import httpx
import tiktoken

from app.ai.rerank import (
    DashScopeRerankClient,
    LocalRerankClient,
    RerankCandidate,
    RerankError,
)


def _client(handler, **kwargs) -> DashScopeRerankClient:
    return DashScopeRerankClient(
        api_key="sk-test",
        base_url="https://example.test/api/v1",
        model="qwen3-rerank",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def _ok(results: list[dict], tokens: int = 79) -> httpx.Response:
    return httpx.Response(200, json={"output": {"results": results}, "usage": {"total_tokens": tokens}})


def test_rerank_success_sends_one_batch_and_sorts() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _ok([
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.4},
        ])

    client = _client(handler)
    candidates = [
        RerankCandidate(id=11, content="块一"),
        RerankCandidate(id=12, content="块二"),
        RerankCandidate(id=13, content="块三"),
    ]
    response = client.rerank("函数的单调性", candidates, top_n=2)

    assert len(seen) == 1
    assert seen[0]["model"] == "qwen3-rerank"
    assert seen[0]["input"]["query"] == "函数的单调性"
    assert seen[0]["input"]["documents"] == ["块一", "块二", "块三"]
    assert seen[0]["parameters"] == {"return_documents": False, "top_n": 2}
    assert [item.id for item in response.scores] == [13, 11]
    assert [item.score for item in response.scores] == [0.9, 0.4]
    assert response.tokens == 79
    assert response.cost_yuan == pytest.approx(79 * 0.5 / 1_000_000)
    assert client.request_count == 1


def test_rerank_truncates_query_and_documents() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok([{"index": 0, "relevance_score": 0.8}])

    client = _client(handler, max_doc_tokens=20)
    long_text = "数学函数单调性" * 500
    client.rerank(long_text, [RerankCandidate(id=1, content=long_text)], top_n=1)

    enc = tiktoken.get_encoding("cl100k_base")
    assert len(enc.encode(seen["input"]["query"])) <= 20
    assert len(enc.encode(seen["input"]["documents"][0])) <= 20


def test_rerank_retries_500_then_success() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json={"message": "temporary"})
        return _ok([{"index": 0, "relevance_score": 0.7}])

    client = _client(handler, max_retries=2, sleep=sleeps.append)
    response = client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert len(calls) == 2
    assert len(sleeps) == 1
    assert client.request_count == 2
    assert response.scores[0].score == 0.7


def test_rerank_timeout_exhausts_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectTimeout("boom")

    client = _client(handler, max_retries=1)
    with pytest.raises(RerankError) as exc_info:
        client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert exc_info.value.retryable is True
    assert len(calls) == 2


def test_rerank_400_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"message": "bad request"})

    client = _client(handler, max_retries=2)
    with pytest.raises(RerankError) as exc_info:
        client.rerank("q", [RerankCandidate(id=1, content="c")])

    assert len(calls) == 1
    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False


def test_rerank_malformed_response_raises() -> None:
    client = _client(lambda request: _ok([]))
    with pytest.raises(RerankError, match="results"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])


def test_rerank_empty_candidates_no_request() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _ok([{"index": 0, "relevance_score": 1.0}])

    client = _client(handler)
    response = client.rerank("q", [])

    assert response.scores == []
    assert response.tokens == 0
    assert calls == []


def test_rerank_invalid_top_n() -> None:
    client = _client(lambda request: _ok([{"index": 0, "relevance_score": 1.0}]))
    with pytest.raises(ValueError, match="top_n"):
        client.rerank("q", [RerankCandidate(id=1, content="c")], top_n=0)


def test_rerank_duplicate_index_raises() -> None:
    client = _client(lambda request: _ok([
        {"index": 0, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.8},
    ]))
    with pytest.raises(RerankError, match="重复"):
        client.rerank("q", [RerankCandidate(id=1, content="c")])
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_rerank.py -q
```

Expected: FAIL，`ImportError: cannot import name 'DashScopeRerankClient'`。

- [x] **Step 3: 实现 DashScope 客户端与门面**

在 `client.py` 追加（放在 `LocalRerankClient` 之后）：

```python
def _encoding_get() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    enc = _encoding_get()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text, False
    return enc.decode(tokens[:max_tokens]), True


class DashScopeRerankClient(RerankClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen3-rerank",
        timeout: float = 30.0,
        max_retries: int = 2,
        max_doc_tokens: int = 3600,
        price_per_million: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise RerankError(
                "RERANK_API_KEY / DASHSCOPE_API_KEY 未配置：请在仓库根 .env 填入 Key（spec §5.6）",
                provider="dashscope",
            )
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/services/rerank/text-rerank/text-rerank"
        self._max_retries = max_retries
        self._max_doc_tokens = max_doc_tokens
        self._price_per_million = price_per_million
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self.request_count = 0
        self.usage_tokens = 0

    def __repr__(self) -> str:
        return f"DashScopeRerankClient(model={self.model!r}, url={self._url!r})"

    def close(self) -> None:
        self._http.close()

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        if top_n is not None and top_n <= 0:
            raise ValueError("top_n 必须为正整数")
        if not candidates:
            return RerankResponse(model=self.model)
        if len(candidates) > _MAX_DOCUMENTS:
            raise RerankError(
                f"候选数 {len(candidates)} 超过厂商上限 {_MAX_DOCUMENTS}",
                retryable=False,
            )

        started = time.perf_counter()
        query_text, query_truncated = _truncate_to_tokens(query, self._max_doc_tokens)
        documents: list[str] = []
        documents_truncated = 0
        for candidate in candidates:
            text, truncated = _truncate_to_tokens(candidate.content, self._max_doc_tokens)
            documents.append(text)
            documents_truncated += int(truncated)
        if query_truncated or documents_truncated:
            logger.warning(
                "rerank_truncated",
                extra={
                    "scene": "rerank",
                    "query_truncated": query_truncated,
                    "documents_truncated": documents_truncated,
                    "max_doc_tokens": self._max_doc_tokens,
                },
            )

        effective_top_n = min(top_n or len(candidates), len(candidates))
        payload = {
            "model": self.model,
            "input": {"query": query_text, "documents": documents},
            "parameters": {"return_documents": False, "top_n": effective_top_n},
        }
        response_payload = self._post_with_retry(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        tokens = int((response_payload.get("usage") or {}).get("total_tokens", 0))
        self.usage_tokens += tokens
        cost_yuan = tokens * self._price_per_million / 1_000_000
        scores = self._parse_scores(response_payload, candidates=candidates)

        logger.info(
            "rerank_call",
            extra={
                "scene": "rerank",
                "model": self.model,
                "candidates": len(candidates),
                "top_n": effective_top_n,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "cost_yuan": cost_yuan,
                "truncated": query_truncated or documents_truncated > 0,
            },
        )
        return RerankResponse(
            model=self.model,
            scores=scores,
            tokens=tokens,
            latency_ms=latency_ms,
            cost_yuan=cost_yuan,
        )

    def _post_with_retry(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise RerankError(
                        f"Rerank 网络错误（重试耗尽）：{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                delay = self._backoff(attempt, None)
                logger.warning(
                    "rerank_retry",
                    extra={"attempt": attempt + 1, "reason": type(exc).__name__, "delay_s": delay},
                )
                self._sleep(delay)
                continue

            self.request_count += 1
            if response.status_code < 400:
                return self._json_or_raise(response)
            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    raise RerankError(
                        f"Rerank 请求重试耗尽（HTTP {response.status_code}）",
                        status_code=response.status_code,
                        retryable=True,
                    )
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "rerank_retry",
                    extra={
                        "attempt": attempt + 1,
                        "status": response.status_code,
                        "delay_s": delay,
                    },
                )
                self._sleep(delay)
                continue
            raise RerankError(
                f"Rerank 请求失败：HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
                retryable=False,
            )
        raise RerankError("Rerank 请求失败：未知重试状态", retryable=False)

    @staticmethod
    def _json_or_raise(response: httpx.Response) -> dict:
        try:
            return response.json()
        except ValueError as exc:
            raise RerankError("Rerank 响应不是合法 JSON", retryable=False) from exc

    @staticmethod
    def _parse_scores(payload: dict, *, candidates: list[RerankCandidate]) -> list[RerankScore]:
        output = payload.get("output")
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list) or not results:
            raise RerankError("Rerank 响应缺少 output.results 或为空", retryable=False)

        parsed: list[tuple[int, float]] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise RerankError("Rerank 响应结果项不是对象", retryable=False)
            index = item.get("index")
            score = item.get("relevance_score")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= len(candidates)
            ):
                raise RerankError(f"Rerank 返回 index 越界：{index!r}", retryable=False)
            if index in seen:
                raise RerankError(f"Rerank 返回重复 index：{index}", retryable=False)
            seen.add(index)
            try:
                value = float(score)
            except (TypeError, ValueError) as exc:
                raise RerankError(f"Rerank 返回非法分数：{score!r}", retryable=False) from exc
            if value != value or value in (float("inf"), float("-inf")):
                raise RerankError(f"Rerank 返回非有限分数：{score!r}", retryable=False)
            parsed.append((index, value))

        parsed.sort(key=lambda item: (-item[1], item[0]))
        return [RerankScore(id=candidates[index].id, score=value) for index, value in parsed]

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        base = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
        return base + random.uniform(0, base * 0.25)


@lru_cache
def get_rerank_client() -> RerankClient:
    """按配置返回单例；Key 缺失时构造阶段抛 RerankError，由 retriever 回退。"""
    settings = get_settings()
    if settings.rerank_provider == "local":
        return LocalRerankClient()
    return DashScopeRerankClient(
        api_key=settings.rerank_api_key,
        base_url=settings.rerank_base_url,
        model=settings.rerank_model,
        timeout=settings.rerank_timeout_seconds,
        max_retries=settings.rerank_max_retries,
        max_doc_tokens=settings.rerank_max_doc_tokens,
        price_per_million=settings.rerank_price_per_million,
    )
```

更新 `backend/app/ai/rerank/__init__.py` 导出：

```python
from app.ai.rerank.client import (
    DashScopeRerankClient,
    LocalRerankClient,
    RerankCandidate,
    RerankClient,
    RerankError,
    RerankResponse,
    RerankScore,
    get_rerank_client,
)

__all__ = [
    "DashScopeRerankClient",
    "LocalRerankClient",
    "RerankCandidate",
    "RerankClient",
    "RerankError",
    "RerankResponse",
    "RerankScore",
    "get_rerank_client",
]
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_rerank.py -q
```

Expected: `10 passed`。

- [x] **Step 5: 跑配置测试确认没有回归**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_rerank.py -q
```

Expected: `18 passed`（8 config + 10 rerank）。

---

### Task 4: Retriever 模型扩展 + `rerank_fused()`

**Files:**
- Modify: `backend/app/ai/rag/retriever.py:1-52, 161-233`
- Test: `backend/tests/test_retriever.py`（追加 4 条）

**Interfaces:**
- Consumes: Task 2/3 的 `RerankClient`、`RerankCandidate`、`RerankError`、`get_rerank_client`
- Produces:
  - `RetrievedChunk.rerank_score: float | None`
  - `RerankInfo(model, candidates, top_k, tokens, latency_ms, cost_yuan, fallback=False, error=None)`
  - `RetrievalResult.vector_ms`、`fulltext_ms`、`reranked`、`rerank_info`
  - `rerank_fused(query, fused, *, candidates=30, top_k=6, client=None) -> tuple[list[RetrievedChunk], RerankInfo | None]`
- 注意：本任务先不改 `retrieve_hybrid()` 的调用方式，只加字段与计时。

- [x] **Step 1: 写失败测试**

在 `backend/tests/test_retriever.py` 补充 import：

```python
from app.ai.rerank import (
    RerankCandidate,
    RerankClient,
    RerankError,
    RerankResponse,
    RerankScore,
)
from app.ai.rag.retriever import (
    RetrievalFilterUnavailable,
    RetrievedChunk,
    rerank_fused,
    retrieve_hybrid,
    rrf_fuse,
)
```

追加 fake 与 4 条测试：

```python
class FakeRerankClient(RerankClient):
    model = "fake-rerank"

    def __init__(self, *, scores: dict[int, float] | None = None, error: Exception | None = None) -> None:
        self.scores = scores or {}
        self.error = error
        self.calls: list[tuple[str, list[int], int | None]] = []

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        self.calls.append((query, [candidate.id for candidate in candidates], top_n))
        if self.error is not None:
            raise self.error
        scored = [
            RerankScore(id=candidate.id, score=self.scores.get(candidate.id, 0.0))
            for candidate in candidates
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return RerankResponse(
            model=self.model,
            scores=scored[:top_n] if top_n is not None else scored,
            tokens=10,
            latency_ms=3,
            cost_yuan=0.000005,
        )


def test_rerank_fused_orders_by_score() -> None:
    fused = [_hit(1), _hit(2), _hit(3)]
    client = FakeRerankClient(scores={1: 0.2, 2: 0.9, 3: 0.5})

    reranked, info = rerank_fused("q", fused, candidates=3, top_k=2, client=client)

    assert [hit.chunk_id for hit in reranked] == [2, 3]
    assert reranked[0].rerank_score == 0.9
    assert info is not None
    assert info.model == "fake-rerank"
    assert info.candidates == 3
    assert info.top_k == 2
    assert info.fallback is False
    assert client.calls == [("q", [1, 2, 3], 2)]


def test_rerank_fused_falls_back_on_error() -> None:
    fused = [_hit(1), _hit(2), _hit(3)]
    client = FakeRerankClient(error=RerankError("模拟失败"))

    reranked, info = rerank_fused("q", fused, candidates=3, top_k=2, client=client)

    assert [hit.chunk_id for hit in reranked] == [1, 2]
    assert info is not None
    assert info.fallback is True
    assert "模拟失败" in (info.error or "")
    assert info.tokens == 0


def test_rerank_fused_caps_candidates_at_30() -> None:
    fused = [_hit(i) for i in range(1, 41)]
    client = FakeRerankClient(scores={i: 0.1 for i in range(1, 41)})

    _, info = rerank_fused("q", fused, candidates=30, top_k=6, client=client)

    assert len(client.calls[0][1]) == 30
    assert info is not None
    assert info.candidates == 30


def test_rerank_fused_empty_returns_none() -> None:
    client = FakeRerankClient()
    reranked, info = rerank_fused("q", [], candidates=30, top_k=6, client=client)
    assert reranked == []
    assert info is None
    assert client.calls == []
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -q
```

Expected: FAIL，`ImportError: cannot import name 'rerank_fused'` / `NameError`。

- [x] **Step 3: 实现模型、计时与 `rerank_fused`**

修改 `retriever.py` 顶部 import：

```python
from pydantic import BaseModel, Field

from app.ai.rerank import (
    RerankCandidate,
    RerankClient,
    RerankError,
    get_rerank_client,
)
```

常量区追加：

```python
DEFAULT_RERANK_CANDIDATES = 30
DEFAULT_RERANK_TOP_K = 6
```

`RetrievedChunk` 末尾加：

```python
    rerank_score: float | None = None
```

在 `RetrievalResult` 前加：

```python
class RerankInfo(BaseModel):
    model: str
    candidates: int
    top_k: int
    tokens: int
    latency_ms: int
    cost_yuan: float
    fallback: bool = False
    error: str | None = None
```

`RetrievalResult` 追加：

```python
    vector_ms: int = 0
    fulltext_ms: int = 0
    reranked: list[RetrievedChunk] = Field(default_factory=list)
    rerank_info: RerankInfo | None = None
```

`retrieve_hybrid()` 中给两路 SQL 计时：

```python
    vector_started = time.perf_counter()
    vector_hits = _vector_search(session, query_vector, user_id=user_id, top_k=top_k)
    vector_ms = int((time.perf_counter() - vector_started) * 1000)

    tsquery_str = build_tsquery_or(query)
    fulltext_started = time.perf_counter()
    fulltext_hits = (
        _fulltext_search(session, tsquery_str, user_id=user_id, top_k=top_k)
        if tsquery_str
        else []
    )
    fulltext_ms = int((time.perf_counter() - fulltext_started) * 1000)
```

`retrieval_done` 日志 extra 加 `"vector_ms": vector_ms, "fulltext_ms": fulltext_ms`；
返回值加 `vector_ms=vector_ms, fulltext_ms=fulltext_ms`。
空查询返回值不需要改（默认 0）。

在 `retrieve_hybrid()` 之后加：

```python
def rerank_fused(
    query: str,
    fused: list[RetrievedChunk],
    *,
    candidates: int = DEFAULT_RERANK_CANDIDATES,
    top_k: int = DEFAULT_RERANK_TOP_K,
    client: RerankClient | None = None,
) -> tuple[list[RetrievedChunk], RerankInfo | None]:
    """取 fused[:candidates] 重排；失败回退 fused[:top_k]，不抛给调用方。"""
    if candidates <= 0:
        raise ValueError("candidates 必须为正整数")
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")
    if not fused:
        return [], None

    selected = fused[: min(candidates, len(fused))]
    started = time.perf_counter()
    rerank_client: RerankClient | None = None
    try:
        rerank_client = client or get_rerank_client()
        response = rerank_client.rerank(
            query,
            [RerankCandidate(id=hit.chunk_id, content=hit.content) for hit in selected],
            top_n=min(top_k, len(selected)),
        )
        if not response.scores:
            raise RerankError("Rerank 返回空分数", provider=rerank_client.model)
        score_by_id = {item.id: item.score for item in response.scores}
        original_order = {hit.chunk_id: index for index, hit in enumerate(selected)}
        scored = [
            hit.model_copy(update={"rerank_score": score_by_id[hit.chunk_id]})
            for hit in selected
            if hit.chunk_id in score_by_id
        ]
        if not scored:
            raise RerankError("Rerank 分数与候选完全对不上", provider=rerank_client.model)
        scored.sort(
            key=lambda hit: (-score_by_id[hit.chunk_id], original_order[hit.chunk_id])
        )
        return scored[:top_k], RerankInfo(
            model=response.model,
            candidates=len(selected),
            top_k=top_k,
            tokens=response.tokens,
            latency_ms=response.latency_ms,
            cost_yuan=response.cost_yuan,
            fallback=False,
        )
    except RerankError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        model = rerank_client.model if rerank_client is not None else "unavailable"
        logger.warning(
            "rerank_fallback",
            extra={
                "scene": "rerank",
                "model": model,
                "candidates": len(selected),
                "top_k": top_k,
                "error": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return fused[:top_k], RerankInfo(
            model=model,
            candidates=len(selected),
            top_k=top_k,
            tokens=0,
            latency_ms=latency_ms,
            cost_yuan=0.0,
            fallback=True,
            error=str(exc),
        )
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -q
```

Expected: `16 passed`（S1-4 12 + 新 4）。

---

### Task 5: `retrieve_hybrid_reranked()` 新入口

**Files:**
- Modify: `backend/app/ai/rag/retriever.py`（在 `rerank_fused` 之后）
- Test: `backend/tests/test_retriever.py`（再追加 4 条，总计 20 条）

**Interfaces:**
- Consumes: `retrieve_hybrid()`、`rerank_fused()`、`get_settings()`
- Produces: `retrieve_hybrid_reranked(session, query, *, user_id, top_k=20, rerank_candidates=None, rerank_top_k=None, client=None, rerank_client=None, subject_id=None, kp_ids=None) -> RetrievalResult`

- [x] **Step 1: 追加失败测试**

在 `backend/tests/test_retriever.py` 追加：

```python
def test_retrieve_hybrid_reranked_integrates_and_times() -> None:
    c1, c2, c3 = make_chunk(1), make_chunk(2), make_chunk(3)
    session = FakeSession(
        FakeResult([(c1, 0.1), (c2, 0.2), (c3, 0.3)]),
        FakeResult([(c2, 0.9), (c3, 0.5)]),
    )
    rerank_client = FakeRerankClient(scores={1: 0.2, 2: 0.9, 3: 0.5})

    result = retrieve_hybrid_reranked(
        session,
        "函数的定义域",
        user_id=1,
        client=FakeClient(),
        rerank_client=rerank_client,
        rerank_candidates=3,
        rerank_top_k=2,
    )

    assert [hit.chunk_id for hit in result.fused] == [2, 3, 1]
    assert [hit.chunk_id for hit in result.reranked] == [2, 3]
    assert result.rerank_info is not None
    assert result.rerank_info.fallback is False
    assert result.vector_ms >= 0
    assert result.fulltext_ms >= 0
    assert result.reranked[0].rerank_score == 0.9
    # fused 不因重排被截断；重排只影响 reranked
    assert len(result.fused) == 3


def test_retrieve_hybrid_reranked_fallback_keeps_rrf_order() -> None:
    chunks = [make_chunk(i) for i in range(1, 8)]
    session = FakeSession(
        FakeResult([(chunk, 0.1 * index) for index, chunk in enumerate(chunks, start=1)]),
        FakeResult([]),
    )
    rerank_client = FakeRerankClient(error=RerankError("模拟失败"))

    result = retrieve_hybrid_reranked(
        session,
        "函数",
        user_id=1,
        client=FakeClient(),
        rerank_client=rerank_client,
    )

    assert [hit.chunk_id for hit in result.reranked] == [hit.chunk_id for hit in result.fused[:6]]
    assert result.rerank_info is not None
    assert result.rerank_info.fallback is True


def test_retrieve_hybrid_reranked_empty_query_skips_all() -> None:
    session = FakeSession()
    embed_client = FakeClient()
    rerank_client = FakeRerankClient()

    result = retrieve_hybrid_reranked(
        session,
        "   ",
        user_id=1,
        client=embed_client,
        rerank_client=rerank_client,
    )

    assert result.reranked == []
    assert result.rerank_info is None
    assert session.statements == []
    assert embed_client.calls == []
    assert rerank_client.calls == []


def test_retrieve_hybrid_reranked_invalid_params() -> None:
    with pytest.raises(ValueError, match="rerank_candidates"):
        retrieve_hybrid_reranked(
            FakeSession(), "函数", user_id=1, client=FakeClient(),
            rerank_client=FakeRerankClient(), rerank_candidates=0,
        )
    with pytest.raises(ValueError, match="rerank_top_k"):
        retrieve_hybrid_reranked(
            FakeSession(), "函数", user_id=1, client=FakeClient(),
            rerank_client=FakeRerankClient(), rerank_top_k=0,
        )
```

补 import：

```python
from app.ai.rag.retriever import (
    RetrievalFilterUnavailable,
    RetrievedChunk,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
    rrf_fuse,
    rerank_fused,
)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -q
```

Expected: FAIL，`ImportError: cannot import name 'retrieve_hybrid_reranked'`。

- [x] **Step 3: 实现新入口**

在 `rerank_fused()` 之后追加：

```python
def retrieve_hybrid_reranked(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    rerank_candidates: int | None = None,
    rerank_top_k: int | None = None,
    client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult:
    """S1-4 混合检索 → top30 → rerank → top6；rerank 失败只回退。"""
    settings = get_settings()
    candidates = settings.rerank_candidates if rerank_candidates is None else rerank_candidates
    final_top_k = settings.rerank_top_k if rerank_top_k is None else rerank_top_k
    if candidates <= 0:
        raise ValueError("rerank_candidates 必须为正整数")
    if final_top_k <= 0:
        raise ValueError("rerank_top_k 必须为正整数")

    result = retrieve_hybrid(
        session,
        query,
        user_id=user_id,
        top_k=top_k,
        final_k=None,
        client=client,
        subject_id=subject_id,
        kp_ids=kp_ids,
    )
    if not result.fused:
        return result

    reranked, info = rerank_fused(
        result.query,
        result.fused,
        candidates=candidates,
        top_k=final_top_k,
        client=rerank_client,
    )
    if info is not None:
        logger.info(
            "retrieval_reranked",
            extra={
                "scene": "retrieve",
                "user_id": user_id,
                "rerank_used": not info.fallback,
                "rerank_fallback": info.fallback,
                "rerank_tokens": info.tokens,
                "rerank_ms": info.latency_ms,
                "rerank_cost_yuan": info.cost_yuan,
                "reranked_hits": len(reranked),
            },
        )
    return result.model_copy(update={"reranked": reranked, "rerank_info": info})
```

- [x] **Step 4: 跑 retriever 测试确认通过**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -q
```

Expected: `20 passed`（S1-4 12 + 新 8）。

- [x] **Step 5: 跑全量测试**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: `114 passed`（原 93 + config 3 + rerank 10 + retriever 8）。
若有 warning，记录并确认是否为既有 `StarletteDeprecationWarning`；不得有 FAIL。

---

### Task 6: 四路评测脚本 + 真实运行

**Files:**
- Modify: `scripts/retrieval_eval.py`
- Create: `eval/results/s1-5-rerank-eval.txt`（真实运行产物，脱敏后提交）

**Interfaces:**
- Consumes: `retrieve_hybrid_reranked()`、`RerankInfo`
- Produces: 四路 top5、hit@5/MRR@5、rerank 耗时/tokens/费用/fallback

- [x] **Step 1: 改脚本（不跑真实 API 前先做静态检查）**

把 import 改为：

```python
from app.ai.rag.retriever import RetrievalResult, retrieve_hybrid_reranked
```

`_print_hits` 增加 `kind == "rerank"` 分支：

```python
        elif kind == "rerank":
            score = (
                f"rerank={hit.rerank_score:.4f} "
                f"rrf={hit.rrf_score:.5f} "
                f"v={hit.vector_rank or '-'} f={hit.fulltext_rank or '-'}"
            )
```

主循环改为：

```python
                result: RetrievalResult = retrieve_hybrid_reranked(
                    session,
                    question,
                    user_id=args.user_id,
                    top_k=args.top_k,
                    client=client,
                )
                vector_rank = _first_hit_rank(result.vector, keywords)
                fulltext_rank = _first_hit_rank(result.fulltext, keywords)
                hybrid_rank = _first_hit_rank(result.fused, keywords)
                rerank_rank = _first_hit_rank(result.reranked, keywords)
                ranks["vector"].append(vector_rank)
                ranks["fulltext"].append(fulltext_rank)
                ranks["hybrid"].append(hybrid_rank)
                ranks["rerank"].append(rerank_rank)
```

`ranks` 初始化加 `"rerank": []`，输出加：

```python
                _print_hits("混合+Rerank top5", result.reranked, limit=limit, kind="rerank")
                info = result.rerank_info
                if info is None:
                    print("  rerank: 无候选，未调用")
                else:
                    print(
                        f"  rerank: model={info.model} fallback={'是' if info.fallback else '否'} "
                        f"candidates={info.candidates} top_k={info.top_k} "
                        f"tokens={info.tokens} latency={info.latency_ms}ms "
                        f"cost=¥{info.cost_yuan:.6f}"
                    )
                    if info.error:
                        print(f"  rerank_error: {info.error}")
                print(
                    f"  耗时: total={result.elapsed_ms}ms "
                    f"vector={result.vector_ms}ms fulltext={result.fulltext_ms}ms "
                    f"rerank={info.latency_ms if info else 0}ms"
                )
                print(
                    f"  命中: vector={vector_rank or '-'} "
                    f"fulltext={fulltext_rank or '-'} hybrid={hybrid_rank or '-'} "
                    f"rerank={rerank_rank or '-'}"
                )
```

`_print_summary` 改为：

```python
def _print_summary(ranks: dict[str, list[int]], rerank_infos: list) -> None:
    total = len(QUESTIONS)
    print("=" * 78)
    print(f"汇总（{total} 问，hit@5 / MRR@5）")
    for name in ("vector", "fulltext", "hybrid", "rerank"):
        values = ranks[name]
        hits = sum(1 for rank in values if rank)
        mrr = sum(1 / rank for rank in values if rank) / total
        print(f"  {name:9s} hit@5={hits}/{total}  MRR@5={mrr:.3f}")
    fallback = sum(1 for info in rerank_infos if info is not None and info.fallback)
    used = [info for info in rerank_infos if info is not None]
    avg_latency = sum(info.latency_ms for info in used) / len(used) if used else 0
    total_cost = sum(info.cost_yuan for info in used)
    print(
        f"  rerank fallback={fallback}/{total}  "
        f"avg_latency={avg_latency:.0f}ms  total_cost=¥{total_cost:.6f}"
    )
```

主循环收集 `rerank_infos.append(result.rerank_info)`；调用 `_print_summary(ranks, rerank_infos)`。

- [x] **Step 2: 语法检查**

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe -m py_compile scripts/retrieval_eval.py
```

Expected: exit code 0，无输出。

- [x] **Step 3: 确认 Key 存在（不打印 Key）**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -c "from app.core.config import get_settings; s=get_settings(); print('rerank_key_set=', bool(s.rerank_api_key)); print('model=', s.rerank_model)"
```

Expected: `rerank_key_set= True`、`model= qwen3-rerank`。
若为 False：停止，向用户报告“未配置 Key”，不要用假数据继续。

- [x] **Step 4: 跑真实四路评测**

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe scripts/retrieval_eval.py > eval/results/s1-5-rerank-eval.txt 2>&1
```

Expected：10 题都输出四路；`rerank fallback=0/10`；有 tokens/latency/cost。
若 fallback >0：查看 `rerank_error`，先报告 API/模型权限问题；不能把 fallback 结果当重排结果。

- [x] **Step 5: 清理输出文件**

```bash
cd E:\BiShe-AIStudy\study-agent
sed -i 's/[[:space:]]*$//' eval/results/s1-5-rerank-eval.txt
```

人工把输出中的真实校名/姓名替换为“某中学/某同学”（不要把真实字符串写进脚本或文档）。
确认没有 Key、没有 `.env` 内容、没有仓库外 DOCX 路径进入提交。

- [x] **Step 6: 人工验收**

把 `eval/results/s1-5-rerank-eval.txt` 的“混合 top5”和“混合+Rerank top5”
逐题给用户看，记录：

- 哪几题 Rerank 后更相关（目标 ≥7/10）
- 哪几题变差/不变，原因
- rerank 平均耗时、总费用、fallback 次数

若 <7/10：先报告，不修改问题/关键词/事后调参；由用户决定是否接受并记录局限。
若 ≥7/10：进入 Task 7。

---

### Task 7: 文档归档 + 一次提交

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `AGENTS.md:§9.6`
- Modify: `docs/spec/s1-5-rerank.md`（追加实测回填）
- Add: `eval/results/s1-5-rerank-eval.txt`（脱敏后）

**Interfaces:**
- Consumes: Task 6 的真实输出与用户验收结论
- Produces: 可提交的 S1-5 变更

- [x] **Step 1: 更新 PROGRESS**

- S1-5 复选框改为 `[x]`
- 新增 2026-10-20 变更日志，写：
  - 交付文件：`ai/rerank/client.py`、retriever 新入口、eval 四路、测试
  - 语料：75 块 / 6 note（原 38 + 新增 37；新增为合成样张）
  - 真实数字：四路 hit@5/MRR@5、rerank fallback、平均耗时、总费用
  - 人工验收：≥7/10 的题号与理由；不足则如实写“未达 7/10”及局限
  - 已知局限：合成语料、qwen3-rerank 单条 4,000 token、重排慢
- 下一步指向 S1-6。

- [x] **Step 2: 更新 DECISIONS**

新增 `D-018`：
- 选 qwen3-rerank 的原因（gte 下线）
- 30→6、3,600 token、30s、2 次重试
- 失败回退，不抛业务层
- 四路评测与实测数字
- 合成语料局限（不冒充真实数据）

- [x] **Step 3: 更新 AGENTS §9.6**

在 ai 适配器锚点后加：

```markdown
- ai Rerank 适配器样例：backend/app/ai/rerank/client.py（契约 + 厂商适配器 + 本地占位 + 门面；批量、截断、超时、降级；失败由 retriever 回退）
```

- [x] **Step 4: spec 追加实测回填**

在 `docs/spec/s1-5-rerank.md` 末尾加 `## 15. 实施回填（实测）`：
- 测试通过数
- 75 块语料四路数字
- rerank fallback / 平均耗时 / 总费用
- 人工 7/10 结论（逐题）
- 与 spec 的偏离（如有）

- [x] **Step 5: 最终验证**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: `114 passed`（无 FAIL；warning 记录）。

```bash
cd E:\BiShe-AIStudy\study-agent
git diff --check
git status --short
```

Expected: `git diff --check` 无输出；`git status` 只包含本任务文件，无 `.env`、无仓库外 DOCX、无临时文件。

- [x] **Step 6: 提交（只一次）**

```bash
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/rerank backend/app/core/config.py .env.example \
  backend/app/ai/rag/retriever.py backend/tests/test_rerank.py \
  backend/tests/test_retriever.py backend/tests/test_config.py \
  backend/tests/test_eval_script.py \
  scripts/retrieval_eval.py eval/results/s1-5-rerank-eval.txt \
  docs/spec/s1-5-rerank.md docs/plan/s1-5-rerank.md \
  docs/PROGRESS.md docs/DECISIONS.md AGENTS.md
git diff --cached --check
git commit -m "feat(s1-5): Rerank 接入（qwen3-rerank + 失败降级 + 四路评测）"
```

Expected: commit 成功；`git status` 干净；用户负责 `git push`。

---

## 验收清单（全部满足才算完成）

- [x] `pytest -q` 全绿，预期 114 passed；S1-4 原 12 条 retriever 测试未改断言
- [x] 真实 eval 跑完 10 问，四路 top5/hit@5/MRR@5/耗时/费用/fallback 都有
- [x] 用户人工判断 ≥7/10 题 Rerank 后 top5 更相关；不足则如实记录
- [x] 重排失败回退 `fused[:6]`，`fallback=True`，不抛异常
- [x] 一次 HTTP 传全部候选；测试断言 1 次请求 / 30 条 documents
- [x] 超长 query/doc 截到 3,600 tokens，不是 512
- [x] 无 Key 泄漏；测试零真实网络；`.env` 未提交
- [x] 文档同步；最后只提交一次；用户负责 push

## 自检记录（写 plan 后）

- [x] 每个 spec 要求都能指向 Task 1–7
- [x] 没有 TBD/TODO/“类似 Task N”
- [x] 类型/函数名一致：`RerankCandidate`、`RerankResponse`、`rerank_fused`、`retrieve_hybrid_reranked`
- [x] 测试数量：计划 config 3 + rerank 10 + retriever 8 = 21；原 93 → 114；实际多 10 条边界回归 = 31/124（见执行回填）
- [x] 真实 API 只在 Task 6 调用；其余测试 MockTransport
- [x] 一个最终 commit，符合项目“一卡一提交”约定

## 执行回填（2026-10-20）

- 实际测试：**124 passed, 1 warning**（原 93 + config 3 + rerank 17 + retriever 10 + eval 编码回归 1）。多出的 10 条是执行中补的边界回归：Windows GBK 控制台、响应顶层非对象、usage.total_tokens 异常、index 越界、429 Retry-After、4xx 不回显正文、tiktoken 加载失败可降级、非 RerankError 不吞、门面构造失败回退、返回条数不足。
- 真实四路：vector `10/10, 0.900`；fulltext `9/10, 0.720`；hybrid `10/10, 0.920`；rerank `10/10, 0.950`；fallback `0/10`；平均 rerank `194ms`；10 问总费用 `¥0.015630`。
- 人工验收：用户确认 **7/10 更相关**（Q1/2/3/5/6/7/10），Q4/Q9 更差，Q8 持平；刚好达到验收线。
- 偏离：多 10 条边界回归测试；候选数按 `min(30, len(fused))` 实际为 21–30；评测输出已脱敏并去掉 jieba 缓存的机器路径噪声。详见 spec §15。
- 提交前验证：`git diff --check` 无输出；`eval/results/s1-5-rerank-eval.txt` 为 UTF-8、无尾随空白、无 Key 泄漏。