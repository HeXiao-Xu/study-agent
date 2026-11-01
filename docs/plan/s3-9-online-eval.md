# S3-9 在线链路抽查与三配置对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让评测从脚本层切到真实 HTTP 链路，用 40 条当前语料问题产出纯向量/混合/混合+rerank 三配置对照表，并完成 40 条引用/拒答逐题核对。

**Architecture:** `/retrieval/search` 增加可选 `retrieval` 模式，`/qa/ask` 的 `done` 增加真实费用；`eval/api_client.py` 封装 JWT 登录、检索 JSON、问答 SSE 与清理；`eval/run.py` 保留原脚本模式，新增 `--api-base-url` 在线模式与 `--config all` 三配置调度；数据集改为当前 chunk 的 40 条 M2 数据。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、httpx、pytest、现有 Vue 3（本轮不改前端）。

**Spec:** `docs/spec/s3-9-online-eval.md`

## Global Constraints

- 不新增依赖、不新增数据库表/迁移、不改前端页面。
- API 字段 snake_case；新增字段必须向后兼容。
- 在线评测脚本不得直接查库、不得直接调用 `retrieve_*` / `answer_question`。
- 不把 token/密码写进仓库、结果 JSON、Markdown、异常文本或日志。
- 数据集固定 40 条 = 30 应答题 + 10 应拒题，gold 必须来自当前真实 chunk 250–286。
- 回答只跑 `hybrid_rerank`；vector/hybrid 只测检索。
- 测试不得调用真实 LLM/网络；真实三配置跑数在 Task 6 单独执行。
- 用户负责 `git push` 与里程碑 tag；本轮不 push。
- 文档写“AI 预标注/初核 + 用户抽查”，不冒充独立人工标注。

---

## Task 1: 检索接口支持三配置

**Files:**
- Modify: `backend/app/schemas/retrieval.py`
- Modify: `backend/app/services/retrieval_service.py`
- Test: `backend/tests/test_retrieval_schema.py`（新建）
- Test: `backend/tests/test_retrieval_service.py`
- Test: `backend/tests/test_retrieval_api.py`

**Interfaces:**
- Produces: `RetrievalSearchRequest.retrieval: Literal["vector","hybrid","hybrid_rerank"] | None`
- Produces: `retrieval_service.search_chunks(..., retrieval: str | None = None, ...)`
- Response 仍为 `RetrievalSearchResponse`，`rerank` 表示实际是否重排。

- [ ] **Step 1: 写失败的 schema 测试**

新建 `backend/tests/test_retrieval_schema.py`：

```python
"""S3-9 检索模式 schema：三配置、冲突、向后兼容。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.retrieval import RetrievalSearchRequest


@pytest.mark.parametrize("mode", ["vector", "hybrid", "hybrid_rerank"])
def test_accepts_three_retrieval_modes(mode: str) -> None:
    payload = RetrievalSearchRequest(query="函数", retrieval=mode)
    assert payload.retrieval == mode


@pytest.mark.parametrize(
    ("mode", "rerank"),
    [("vector", True), ("hybrid", True), ("hybrid_rerank", False)],
)
def test_rejects_conflicting_rerank(mode: str, rerank: bool) -> None:
    with pytest.raises(ValidationError, match="retrieval"):
        RetrievalSearchRequest(query="函数", retrieval=mode, rerank=rerank)


def test_rejects_unknown_retrieval_mode() -> None:
    with pytest.raises(ValidationError):
        RetrievalSearchRequest(query="函数", retrieval="magic")


def test_default_request_keeps_old_behavior() -> None:
    payload = RetrievalSearchRequest(query="函数")
    assert payload.retrieval is None
    assert payload.rerank is None
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_schema.py -q
```

Expected: FAIL，`retrieval` 不是 `RetrievalSearchRequest` 字段。

- [ ] **Step 2.5: 先同步 API.md**

在 `docs/API.md` 的 `POST /api/v1/retrieval/search` 入参表加：

```markdown
| retrieval | string | 否 | `vector`/`hybrid`/`hybrid_rerank`；缺省保持原行为 |
```

备注加：

```markdown
- `retrieval` 与 `rerank` 冲突：vector/hybrid + rerank=true、hybrid_rerank + rerank=false 均 422。
- `vector` 复用混合检索的向量召回后取前 top_k，延迟口径偏保守。
```

- [ ] **Step 3: 实现 schema**

在 `backend/app/schemas/retrieval.py`：

```python
RetrievalMode = Literal["vector", "hybrid", "hybrid_rerank"]
```

在 `RetrievalSearchRequest` 加字段与校验：

```python
    retrieval: RetrievalMode | None = None

    @model_validator(mode="after")
    def _check_retrieval_conflict(self) -> "RetrievalSearchRequest":
        if self.retrieval == "vector" and self.rerank is True:
            raise ValueError("retrieval=vector 时 rerank 不能为 true")
        if self.retrieval == "hybrid" and self.rerank is True:
            raise ValueError("retrieval=hybrid 时 rerank 不能为 true")
        if self.retrieval == "hybrid_rerank" and self.rerank is False:
            raise ValueError("retrieval=hybrid_rerank 时 rerank 不能为 false")
        return self
```

注意文件已 import `model_validator`；若没有补上。

- [ ] **Step 4: 运行 schema 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_schema.py -q
```

Expected: 8 passed。

- [ ] **Step 5: 写失败的 service 模式测试**

在 `backend/tests/test_retrieval_service.py` 追加：

```python
def _mode_result() -> RetrievalResult:
    return RetrievalResult(
        query="函数",
        tsquery="函数",
        vector=[_chunk(1), _chunk(2), _chunk(3)],
        fulltext=[_chunk(2)],
        fused=[_chunk(2), _chunk(3)],
        reranked=[_chunk(4)],
        elapsed_ms=10,
        embedding_ms=8,
        vector_ms=1,
        fulltext_ms=1,
        rerank_info=RerankInfo(
            model="fake-rerank",
            candidates=2,
            top_k=1,
            tokens=4,
            latency_ms=5,
            cost_yuan=0.0,
        ),
    )


def test_search_vector_returns_vector_list_without_rerank(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _mode_result())
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: pytest.fail("vector 不应调用 rerank"),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=2, retrieval="vector"
    )

    assert [hit.chunk_id for hit in response.hits] == [1, 2]
    assert response.rerank is False
    assert response.rerank_info is None


def test_search_hybrid_returns_fused_list_without_rerank(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr(retrieval_service, "retrieve_hybrid", lambda *a, **k: _mode_result())
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: pytest.fail("hybrid 不应调用 rerank"),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=2, retrieval="hybrid"
    )

    assert [hit.chunk_id for hit in response.hits] == [2, 3]
    assert response.rerank is False


def test_search_hybrid_rerank_returns_reranked_list(monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr(
        retrieval_service,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _mode_result(),
    )

    response = retrieval_service.search_chunks(
        FakeSession(), user_id=1, query="函数", top_k=1, retrieval="hybrid_rerank"
    )

    assert [hit.chunk_id for hit in response.hits] == [4]
    assert response.rerank is True
    assert response.rerank_info is not None
```

- [ ] **Step 6: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_service.py -q
```

Expected: FAIL，`search_chunks()` 不接受 `retrieval`。

- [ ] **Step 7: 实现 service 模式**

在 `backend/app/services/retrieval_service.py` 修改 `search_chunks` 签名与分支：

```python
def search_chunks(
    session: Session,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
    rerank: bool | None = None,
    retrieval: str | None = None,
    scope: RetrievalScopeIn | None = None,
    debug: bool = False,
) -> RetrievalSearchResponse:
```

在 `use_rerank` 附近改为：

```python
    if retrieval not in (None, "vector", "hybrid", "hybrid_rerank"):
        raise InvalidParamError("retrieval 必须是 vector/hybrid/hybrid_rerank")

    if retrieval is None:
        use_rerank = settings.retrieval_rerank_enabled if rerank is None else rerank
        mode = "hybrid_rerank" if use_rerank else "hybrid"
    else:
        mode = retrieval
        use_rerank = mode == "hybrid_rerank"
```

检索分支改为：

```python
    if mode == "vector":
        result = retrieve_hybrid(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            final_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.vector[:resolved_top_k]
    elif mode == "hybrid":
        result = retrieve_hybrid(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            final_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.fused
    else:
        result = retrieve_hybrid_reranked(
            session,
            clean_query,
            user_id=user_id,
            top_k=settings.retrieval_recall_k,
            rerank_top_k=resolved_top_k,
            scope=retrieval_scope,
        )
        chosen = result.reranked
```

响应保持 `rerank=use_rerank`，`rerank_info=result.rerank_info if use_rerank else None`。

- [ ] **Step 8: 运行 service 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_service.py -q
```

Expected: 全部 passed；原有默认行为测试不回归。

- [ ] **Step 9: 写并通过 API 测试**

在 `backend/tests/test_retrieval_api.py` 追加：

```python
@pytest.mark.parametrize("mode", ["vector", "hybrid", "hybrid_rerank"])
def test_search_accepts_retrieval_mode(client: TestClient, mode: str) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "retrieval": mode},
        headers=_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0


@pytest.mark.parametrize(
    ("mode", "rerank"),
    [("vector", True), ("hybrid", True), ("hybrid_rerank", False)],
)
def test_search_rejects_conflicting_rerank(
    client: TestClient, mode: str, rerank: bool
) -> None:
    user = _user()
    _override_user(user)

    response = client.post(
        "/api/v1/retrieval/search",
        json={"query": "函数", "retrieval": mode, "rerank": rerank},
        headers=_headers(user),
    )

    assert response.status_code == 422
```

路由在 `backend/app/api/v1/retrieval.py` 调用处加：

```python
        retrieval=payload.retrieval,
```

- [ ] **Step 10: 运行检索相关测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_schema.py backend/tests/test_retrieval_service.py backend/tests/test_retrieval_api.py -q
```

Expected: 全部 passed。

- [ ] **Step 11: 提交**

```powershell
git add docs/API.md backend/app/schemas/retrieval.py backend/app/services/retrieval_service.py backend/app/api/v1/retrieval.py backend/tests/test_retrieval_schema.py backend/tests/test_retrieval_service.py backend/tests/test_retrieval_api.py
git commit -m "feat(s3-9): 检索接口支持三配置模式"
```

---

## Task 2: 问答完成事件返回真实费用

**Files:**
- Modify: `backend/app/schemas/qa.py`
- Modify: `backend/app/services/qa_service.py`
- Test: `backend/tests/test_qa_service.py`
- Test: `backend/tests/test_qa_api.py`

**Interfaces:**
- Produces: `QaDoneData.cost_yuan: float = 0.0`
- SSE `done` 新增 `cost_yuan`，等于回答 LLM 费用 + 查询改写费用；缓存/未调 LLM 为 0。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_qa_service.py` 末尾加（文件顶部补 `import time`，现有 import 没有它）：

```python
def test_done_data_sums_answer_and_rewrite_cost() -> None:
    from types import SimpleNamespace
    from app.services.qa_service import _done_data

    plan = SimpleNamespace(
        conversation_id=7,
        started_at=time.perf_counter(),
        rewrite=SimpleNamespace(total_tokens=3, cost_yuan=0.0003),
    )
    message = SimpleNamespace(id=9)
    responses = [
        SimpleNamespace(total_tokens=10, cost_yuan=0.001),
        SimpleNamespace(total_tokens=20, cost_yuan=0.002),
    ]

    data = _done_data(
        plan,
        message,
        refused=False,
        responses=responses,
        refusal_reason=None,
        suggestions=[],
    )

    assert data["cost_yuan"] == pytest.approx(0.0033)


def test_done_data_cost_is_zero_for_cached_answer() -> None:
    from types import SimpleNamespace
    from app.services.qa_service import _done_data

    plan = SimpleNamespace(
        conversation_id=7,
        started_at=time.perf_counter(),
        rewrite=None,
    )
    data = _done_data(
        plan,
        SimpleNamespace(id=9),
        refused=False,
        responses=[],
        refusal_reason=None,
        suggestions=[],
    )
    assert data["cost_yuan"] == 0.0
```

确认文件已有 `import time` 与 `pytest`；若没有补上。

- [ ] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q -k "done_data"
```

Expected: FAIL，`cost_yuan` 不在 done 数据。

- [ ] **Step 2.5: 先同步 API.md**

在 `docs/API.md` 的 `POST /api/v1/qa/ask` 的 done 字段说明加：

```markdown
- `cost_yuan`：本次回答真实 LLM 费用（含查询改写）；缓存/未调 LLM 为 0。
```

- [ ] **Step 3: 实现**

`backend/app/services/qa_service.py` 的 `_done_data` 返回体加：

```python
        "cost_yuan": sum(r.cost_yuan for r in responses)
        + (plan.rewrite.cost_yuan if plan.rewrite is not None else 0.0),
```

`backend/app/schemas/qa.py` 的 `QaDoneData` 加：

```python
    cost_yuan: float = 0.0
```

- [ ] **Step 4: 运行 QA 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py backend/tests/test_qa_api.py -q
```

Expected: 全部 passed。

- [ ] **Step 5: 提交**

```powershell
git add docs/API.md backend/app/schemas/qa.py backend/app/services/qa_service.py backend/tests/test_qa_service.py backend/tests/test_qa_api.py
git commit -m "feat(s3-9): 问答完成事件返回真实费用"
```

---

## Task 3: 40 条 M2 数据集

**Files:**
- Create: `eval/datasets/qa_set_m2.jsonl`
- Test: `backend/tests/test_eval_dataset.py`

**Interfaces:**
- Consumes: `load_dataset(path, min_items=40, max_items=40)`
- Produces: 40 条 `QACase`，id `q001`–`q040`；30 应答 + 10 应拒；gold 全部 250–286。

- [ ] **Step 1: 写失败的数据集测试**

在 `backend/tests/test_eval_dataset.py` 追加：

```python
def test_m2_dataset_has_30_answerable_and_10_refusal() -> None:
    path = ROOT / "eval" / "datasets" / "qa_set_m2.jsonl"
    cases = load_dataset(path, min_items=40, max_items=40)

    assert len(cases) == 40
    assert sum(1 for case in cases if not case.should_refuse) == 30
    assert sum(1 for case in cases if case.should_refuse) == 10
    assert cases[0].id == "q001"
    assert cases[-1].id == "q040"


def test_m2_gold_ids_are_current_chunks() -> None:
    path = ROOT / "eval" / "datasets" / "qa_set_m2.jsonl"
    cases = load_dataset(path, min_items=40, max_items=40)
    gold = {chunk for case in cases for chunk in case.gold_chunk_ids}
    assert gold
    assert gold <= set(range(250, 287))


def test_load_dataset_accepts_40_with_explicit_bounds(tmp_path) -> None:
    cases = [_case(i) for i in range(1, 31)] + [
        _case(i, refuse=True) for i in range(31, 41)
    ]
    loaded = load_dataset(
        _write_cases(tmp_path, cases), min_items=40, max_items=40
    )
    assert len(loaded) == 40


def test_load_dataset_rejects_39_for_m2_bounds(tmp_path) -> None:
    cases = [_case(i) for i in range(1, 31)] + [
        _case(i, refuse=True) for i in range(31, 40)
    ]
    with pytest.raises(DatasetError, match="40"):
        load_dataset(_write_cases(tmp_path, cases), min_items=40, max_items=40)
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_dataset.py -q -k "m2 or 40"
```

Expected: FAIL，数据集不存在（39/40 用例先通过也没关系，文件类必须失败）。

- [ ] **Step 3: 创建数据集**

按 spec §4.1 逐行创建 `eval/datasets/qa_set_m2.jsonl`，共 40 行；示例前 3 行：

```jsonl
{"id":"q001","question":"函数的定义域怎么求？","scope":"函数","gold_chunk_ids":[254],"should_refuse":false}
{"id":"q002","question":"函数的三要素是什么？","scope":"函数","gold_chunk_ids":[254],"should_refuse":false}
{"id":"q003","question":"单调性的定义是什么？","scope":"函数","gold_chunk_ids":[250,256],"should_refuse":false}
```

必须严格按 spec 表填完 q001–q040；应拒题 `gold_chunk_ids` 为 `[]`。

- [ ] **Step 4: 运行数据集测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_dataset.py -q
```

Expected: 全部 passed。

- [ ] **Step 5: 提交**

```powershell
git add eval/datasets/qa_set_m2.jsonl backend/tests/test_eval_dataset.py
git commit -m "feat(s3-9): 新增 40 条 M2 评测数据集"
```

---

## Task 4: 在线 API 客户端与 SSE 解析

**Files:**
- Create: `eval/api_client.py`
- Test: `backend/tests/test_eval_api_client.py`（新建）

**Interfaces:**
- Produces:
  - `normalize_base_url(value: str) -> str`
  - `parse_sse_events(lines: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]`
  - `class OnlineEvalError(RuntimeError)`
  - `@dataclass(frozen=True) class ApiCitation(chunk_id: int, title: str | None, heading_path: str | None, snippet: str)`
  - `@dataclass(frozen=True) class RetrievalResponse(chunk_ids: list[int], latency_ms: int, rerank: bool)`
  - `@dataclass(frozen=True) class AnswerResponse(text: str, refused: bool, refusal_reason: str | None, citations: list[ApiCitation], tokens: int, latency_ms: int, cost_yuan: float, conversation_id: str | None)`
  - `class OnlineClient(base_url: str, token: str, *, timeout: float = 180.0, transport: httpx.BaseTransport | None = None)`
    - `search(query: str, retrieval: str, *, top_k: int = 5) -> RetrievalResponse`
    - `ask(question: str) -> AnswerResponse`
    - `delete_conversation(conversation_id: str | None) -> bool`
    - `close() -> None`
  - `login(base_url: str, username: str, password: str, *, transport=None) -> str`

- [ ] **Step 1: 写失败的客户端测试**

新建 `backend/tests/test_eval_api_client.py`：

```python
"""S3-9 在线评测客户端：MockTransport，不触网。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.api_client import (  # noqa: E402
    OnlineClient,
    OnlineEvalError,
    login,
    normalize_base_url,
    parse_sse_events,
)


def test_normalize_base_url() -> None:
    assert normalize_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000/api/v1"
    assert normalize_base_url("http://127.0.0.1:8000/api/v1") == "http://127.0.0.1:8000/api/v1"


def test_parse_sse_events_meta_delta_done() -> None:
    lines = [
        "event: meta",
        'data: {"conversation_id":"7","citations":[]}',
        "",
        "event: delta",
        'data: {"text":"你"}',
        "",
        "event: delta",
        'data: {"text":"好"}',
        "",
        "event: done",
        'data: {"refused":false,"tokens":3}',
        "",
    ]
    events = list(parse_sse_events(lines))
    assert [event for event, _ in events] == ["meta", "delta", "delta", "done"]
    assert events[1][1]["text"] == "你"


def test_parse_sse_events_raises_on_bad_json() -> None:
    with pytest.raises(OnlineEvalError, match="SSE"):
        list(parse_sse_events(["event: delta", "data: not-json", ""]))


def _envelope(data: object, *, code: int = 0) -> httpx.Response:
    return httpx.Response(200, json={"code": code, "data": data, "trace_id": "t"})


def test_search_sends_auth_and_retrieval_mode() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _envelope(
            {
                "query": "函数",
                "top_k": 5,
                "rerank": False,
                "elapsed_ms": 12,
                "embedding_ms": 8,
                "hits": [{"chunk_id": 250}, {"chunk_id": 254}],
            }
        )

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    result = client.search("函数", "vector", top_k=5)
    client.close()

    assert result.chunk_ids == [250, 254]
    assert result.latency_ms == 12
    assert result.rerank is False
    assert captured[0].headers["authorization"] == "Bearer token-123"
    assert json.loads(captured[0].content)["retrieval"] == "vector"


def test_ask_collects_citations_text_and_cost() -> None:
    body = "\n".join(
        [
            "event: meta",
            'data: {"conversation_id":"7","citations":[{"chunk_id":250,"title":"属性","heading_path":"单调性","snippet":"定义"}]}',
            "",
            "event: delta",
            'data: {"text":"答"}',
            "",
            "event: done",
            'data: {"refused":false,"tokens":9,"latency_ms":120,"cost_yuan":0.0012,"conversation_id":"7"}',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/qa/ask"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    answer = client.ask("单调性是什么")
    client.close()

    assert answer.text == "答"
    assert answer.citations[0].chunk_id == 250
    assert answer.cost_yuan == pytest.approx(0.0012)
    assert answer.conversation_id == "7"


def test_ask_raises_on_error_event() -> None:
    body = "\n".join(
        [
            "event: error",
            'data: {"code":50000,"message":"生成失败"}',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = OnlineClient(
        "http://testserver", "token-123", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(OnlineEvalError, match="生成失败"):
        client.ask("q")
    client.close()


def test_login_returns_access_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/login"
        assert json.loads(request.content) == {"username": "test1", "password": "pw"}
        return _envelope({"access_token": "jwt-abc", "token_type": "bearer"})

    token = login(
        "http://testserver", "test1", "pw", transport=httpx.MockTransport(handler)
    )
    assert token == "jwt-abc"
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_api_client.py -q
```

Expected: FAIL，`eval.api_client` 不存在。

- [ ] **Step 3: 实现客户端**

新建 `eval/api_client.py`，核心代码：

```python
"""S3-9 在线评测 HTTP 客户端；本文件不导入 app 业务模块。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import httpx


class OnlineEvalError(RuntimeError):
    """在线接口/鉴权/SSE 错误；CLI 统一退出 5。"""


def normalize_base_url(value: str) -> str:
    base = value.rstrip("/")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def parse_sse_events(
    lines: Iterable[str],
) -> Iterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data_lines: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data_lines:
                try:
                    payload = json.loads("\n".join(data_lines))
                except json.JSONDecodeError as exc:
                    raise OnlineEvalError("SSE data 不是合法 JSON") from exc
                yield event, payload
            event = "message"
            data_lines = []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise OnlineEvalError("SSE data 不是合法 JSON") from exc
        yield event, payload


@dataclass(frozen=True)
class ApiCitation:
    chunk_id: int
    title: str | None
    heading_path: str | None
    snippet: str


@dataclass(frozen=True)
class RetrievalResponse:
    chunk_ids: list[int]
    latency_ms: int
    rerank: bool


@dataclass(frozen=True)
class AnswerResponse:
    text: str
    refused: bool
    refusal_reason: str | None
    citations: list[ApiCitation]
    tokens: int
    latency_ms: int
    cost_yuan: float
    conversation_id: str | None


class OnlineClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise OnlineEvalError("缺少访问 token")
        self._base = normalize_base_url(base_url)
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _data(response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnlineEvalError(
                f"HTTP {response.status_code}: 响应不是 JSON"
            ) from exc
        if response.status_code >= 400 or payload.get("code") != 0:
            message = payload.get("message") or payload.get("detail") or "接口失败"
            raise OnlineEvalError(f"HTTP {response.status_code}: {message}")
        return payload.get("data")

    def search(
        self, query: str, retrieval: str, *, top_k: int = 5
    ) -> RetrievalResponse:
        response = self._http.post(
            f"{self._base}/retrieval/search",
            json={"query": query, "top_k": top_k, "retrieval": retrieval},
        )
        data = self._data(response)
        return RetrievalResponse(
            chunk_ids=[int(hit["chunk_id"]) for hit in data["hits"]],
            latency_ms=int(data["elapsed_ms"]),
            rerank=bool(data["rerank"]),
        )

    def ask(self, question: str) -> AnswerResponse:
        citations: list[ApiCitation] = []
        text_parts: list[str] = []
        done: dict[str, Any] | None = None
        with self._http.stream(
            "POST", f"{self._base}/qa/ask", json={"question": question}
        ) as response:
            if response.status_code != 200:
                raise OnlineEvalError(f"HTTP {response.status_code}: 问答失败")
            for event, data in parse_sse_events(response.iter_lines()):
                if event == "meta":
                    citations = [
                        ApiCitation(
                            chunk_id=int(item["chunk_id"]),
                            title=item.get("title"),
                            heading_path=item.get("heading_path"),
                            snippet=str(item.get("snippet") or ""),
                        )
                        for item in data.get("citations", [])
                    ]
                elif event == "delta":
                    text_parts.append(str(data.get("text") or ""))
                elif event == "done":
                    done = data
                elif event == "error":
                    raise OnlineEvalError(
                        f"问答失败：{data.get('code')} {data.get('message')}"
                    )
        if done is None:
            raise OnlineEvalError("SSE 结束但没有 done 事件")
        return AnswerResponse(
            text="".join(text_parts),
            refused=bool(done.get("refused")),
            refusal_reason=done.get("refusal_reason"),
            citations=citations,
            tokens=int(done.get("tokens") or 0),
            latency_ms=int(done.get("latency_ms") or 0),
            cost_yuan=float(done.get("cost_yuan") or 0.0),
            conversation_id=done.get("conversation_id"),
        )

    def delete_conversation(self, conversation_id: str | None) -> bool:
        if not conversation_id:
            return False
        try:
            response = self._http.delete(
                f"{self._base}/qa/conversations/{conversation_id}"
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 204


def login(
    base_url: str,
    username: str,
    password: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    base = normalize_base_url(base_url)
    with httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0), transport=transport
    ) as http:
        response = http.post(
            f"{base}/auth/login",
            json={"username": username, "password": password},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnlineEvalError(f"HTTP {response.status_code}: 登录响应不是 JSON") from exc
        if response.status_code >= 400 or payload.get("code") != 0:
            raise OnlineEvalError("登录失败（检查账号、密码与服务）")
        token = payload.get("data", {}).get("access_token")
        if not token:
            raise OnlineEvalError("登录响应缺少 access_token")
        return str(token)
```

- [ ] **Step 4: 运行客户端测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_api_client.py -q
```

Expected: 7 passed。

- [ ] **Step 5: 提交**

```powershell
git add eval/api_client.py backend/tests/test_eval_api_client.py
git commit -m "feat(s3-9): 新增在线评测 API 客户端"
```

---

## Task 5: run.py 在线模式与三配置调度

**Files:**
- Modify: `eval/run.py`
- Test: `backend/tests/test_eval_run.py`
- Test: `backend/tests/test_eval_online_run.py`（新建）

**Interfaces:**
- Consumes: `OnlineClient`, `login`, `OnlineEvalError` from Task 4；`CaseAnswer`, `CaseRetrieval` from `eval.qa_eval`。
- Produces:
  - `_run_api_config(client, cases, cfg, *, answer_enabled) -> tuple[list[CaseRetrieval], list[CaseAnswer], list[dict[str, Any]]]`
  - `_render_compare_markdown(payloads: list[dict[str, Any]]) -> str`
  - `_build_payload(..., mode: str = "script", api_base_url: str | None = None)`
  - CLI `--api-base-url --token --username --password --min-items --max-items`；`--config all` 仅在线模式。
- 输出：`eval/results/s3-9-{config}.json|.md`；all 额外 `s3-9-compare.md`。

- [ ] **Step 1: 写失败的在线运行测试**

新建 `backend/tests/test_eval_online_run.py`：

```python
"""S3-9 在线运行编排：fake client，不触网、不触库。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval import run  # noqa: E402
from eval.api_client import (  # noqa: E402
    AnswerResponse,
    ApiCitation,
    RetrievalResponse,
)
from eval.qa_eval import QACase, load_config  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.searches: list[tuple[str, str]] = []
        self.asks: list[str] = []
        self.deleted: list[str | None] = []

    def search(self, query: str, retrieval: str, *, top_k: int = 5) -> RetrievalResponse:
        self.searches.append((query, retrieval))
        return RetrievalResponse(chunk_ids=[250, 251], latency_ms=5, rerank=retrieval == "hybrid_rerank")

    def ask(self, question: str) -> AnswerResponse:
        self.asks.append(question)
        return AnswerResponse(
            text="答案",
            refused=False,
            refusal_reason=None,
            citations=[ApiCitation(250, "属性", "单调性", "定义")],
            tokens=10,
            latency_ms=50,
            cost_yuan=0.001,
            conversation_id="99",
        )

    def delete_conversation(self, conversation_id: str | None) -> bool:
        self.deleted.append(conversation_id)
        return True


def _cases() -> list[QACase]:
    return [
        QACase(
            id="q001",
            question="单调性是什么？",
            scope="函数",
            gold_chunk_ids=[250],
            should_refuse=False,
        ),
        QACase(
            id="q002",
            question="今天天气？",
            scope="无关",
            gold_chunk_ids=[],
            should_refuse=True,
        ),
    ]


def test_run_api_config_vector_skips_answer() -> None:
    client = FakeClient()
    cfg = load_config(ROOT / "eval" / "configs" / "vector.json")

    retrieval, answers, rows = run._run_api_config(
        client, _cases(), cfg, answer_enabled=False
    )

    assert len(retrieval) == 2
    assert answers == []
    assert rows[0]["hit_at_5"] is True
    assert rows[0]["answer"] is None
    assert client.asks == []
    assert client.deleted == []


def test_run_api_config_production_answers_and_cleans_up() -> None:
    client = FakeClient()
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid_rerank.json")

    retrieval, answers, rows = run._run_api_config(
        client, _cases(), cfg, answer_enabled=True
    )

    assert len(answers) == 2
    assert rows[0]["answer"]["text"] == "答案"
    assert rows[0]["answer"]["citations"][0]["chunk_id"] == 250
    assert client.asks == ["单调性是什么？", "今天天气？"]
    assert client.deleted == ["99", "99"]


def test_render_compare_markdown_has_three_rows() -> None:
    payloads = [
        {
            "dataset": "qa_set_m2",
            "config": "vector",
            "case_count": 40,
            "retrieval": {"hit_at_5": 1.0, "mrr_at_5": 0.9, "avg_latency_ms": 100},
            "answer": None,
        },
        {
            "dataset": "qa_set_m2",
            "config": "hybrid",
            "case_count": 40,
            "retrieval": {"hit_at_5": 1.0, "mrr_at_5": 0.8, "avg_latency_ms": 90},
            "answer": None,
        },
        {
            "dataset": "qa_set_m2",
            "config": "hybrid_rerank",
            "case_count": 40,
            "retrieval": {"hit_at_5": 1.0, "mrr_at_5": 0.95, "avg_latency_ms": 300},
            "answer": {
                "citation_precision": 0.8,
                "citation_hit_rate": 1.0,
                "refusal_accuracy": 1.0,
                "confusion": {"tp": 10, "fp": 0, "fn": 0, "tn": 30},
                "avg_total_tokens": 500,
                "avg_latency_ms": 3000,
                "total_cost_yuan": 0.02,
            },
        },
    ]
    text = run._render_compare_markdown(payloads)
    assert text.count("| vector |") == 1
    assert text.count("| hybrid |") == 1
    assert text.count("| hybrid_rerank |") == 1
    assert "0.950" in text
    assert "¥0.020000" in text
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_online_run.py -q
```

Expected: FAIL，`_run_api_config` / `_render_compare_markdown` 不存在。

- [ ] **Step 3: 实现在线编排**

在 `eval/run.py` 顶部加：

```python
import os
from types import SimpleNamespace

from eval.api_client import (
    AnswerResponse,
    OnlineClient,
    OnlineEvalError,
    login,
    normalize_base_url,
)
```

新增函数（放在 `_answer_case` 后）：

```python
def _api_answer_row(case: QACase, result: AnswerResponse) -> CaseAnswer:
    cited = [item.chunk_id for item in result.citations]
    gold = set(case.gold_chunk_ids)
    if case.should_refuse:
        precision = None
        matched = None
    elif result.refused:
        precision = 0.0
        matched = False
    else:
        precision = citation_precision(cited, gold)
        matched = citation_hit(cited, gold)
    return CaseAnswer(
        case_id=case.id,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        cited_chunk_ids=cited,
        citation_precision=precision,
        citation_hit=matched,
        total_tokens=result.tokens,
        latency_ms=result.latency_ms,
        cost_yuan=result.cost_yuan,
    )


def _run_api_config(
    client: OnlineClient,
    cases: list[QACase],
    cfg: RetrievalConfig,
    *,
    answer_enabled: bool,
) -> tuple[list[CaseRetrieval], list[CaseAnswer], list[dict[str, Any]]]:
    retrieval_rows: list[CaseRetrieval] = []
    answer_rows: list[CaseAnswer] = []
    case_rows: list[dict[str, Any]] = []

    for case in cases:
        retrieved = client.search(case.question, cfg.retrieval, top_k=cfg.top_n)
        rank = (
            first_gold_rank(
                [SimpleNamespace(chunk_id=item) for item in retrieved.chunk_ids],
                set(case.gold_chunk_ids),
            )
            if not case.should_refuse
            else None
        )
        retrieval_rows.append(
            CaseRetrieval(
                case_id=case.id,
                hit_at_5=rank is not None,
                first_gold_rank=rank,
                latency_ms=retrieved.latency_ms,
            )
        )
        answer_row = None
        answer_payload = None
        if answer_enabled:
            answer = client.ask(case.question)
            answer_row = _api_answer_row(case, answer)
            answer_rows.append(answer_row)
            client.delete_conversation(answer.conversation_id)
            answer_payload = {
                "text": answer.text,
                "refused": answer.refused,
                "refusal_reason": answer.refusal_reason,
                "cited_chunk_ids": [item.chunk_id for item in answer.citations],
                "citations": [
                    {
                        "chunk_id": item.chunk_id,
                        "title": item.title,
                        "heading_path": item.heading_path,
                        "snippet": item.snippet,
                    }
                    for item in answer.citations
                ],
                "citation_precision": answer_row.citation_precision,
                "citation_hit": answer_row.citation_hit,
                "total_tokens": answer.tokens,
                "latency_ms": answer.latency_ms,
                "cost_yuan": answer.cost_yuan,
            }
        case_rows.append(
            {
                "id": case.id,
                "question": case.question,
                "scope": case.scope,
                "should_refuse": case.should_refuse,
                "gold_chunk_ids": case.gold_chunk_ids,
                "hit_at_5": rank is not None if not case.should_refuse else None,
                "first_gold_rank": rank,
                "retrieval_latency_ms": retrieved.latency_ms,
                "answer": answer_payload,
            }
        )
    return retrieval_rows, answer_rows, case_rows


def _render_compare_markdown(payloads: list[dict[str, Any]]) -> str:
    lines = [
        "# S3-9 三配置对照",
        "",
        f"- 数据集：`{payloads[0]['dataset']}`（{payloads[0]['case_count']} 条）",
        "",
        "| 配置 | hit@5 | MRR@5 | 引用精确率 | 引用命中率 | 拒答准确率 | 平均检索延迟 | 平均回答延迟 | 平均 tokens | 总费用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for payload in payloads:
        retrieval = payload["retrieval"]
        answer = payload["answer"]
        if answer is None:
            lines.append(
                f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
                f"{retrieval['mrr_at_5']:.3f} | — | — | — | "
                f"{retrieval['avg_latency_ms']:.0f}ms | — | — | — |"
            )
        else:
            lines.append(
                f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
                f"{retrieval['mrr_at_5']:.3f} | {answer['citation_precision']:.3f} | "
                f"{answer['citation_hit_rate']:.3f} | "
                f"{answer['refusal_accuracy'] * 100:.1f}% | "
                f"{retrieval['avg_latency_ms']:.0f}ms | "
                f"{answer['avg_latency_ms']:.0f}ms | "
                f"{answer['avg_total_tokens']:.1f} | "
                f"¥{answer['total_cost_yuan']:.6f} |"
            )
    lines.append("")
    return "\n".join(lines)
```

修改 `_build_payload` 签名与返回体：

```python
def _build_payload(
    *,
    dataset_name: str,
    config_name: str,
    user_id: int | None,
    cases: list[QACase],
    retrieval_summary,
    answer_summary: AnswerSummary | None,
    answer_skipped: bool,
    case_rows: list[dict[str, Any]],
    mode: str = "script",
    api_base_url: str | None = None,
) -> dict[str, Any]:
```

返回体加：

```python
        "mode": mode,
        "api_base_url": api_base_url,
```

`user_id` 类型改为 `int | None`，在线传 `None`。

- [ ] **Step 4: 实现 CLI 在线分支**

修改 `main()` 参数：

```python
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--skip-answer", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--md-output", type=Path, default=None)
    parser.add_argument("--api-base-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--min-items", type=int, default=20)
    parser.add_argument("--max-items", type=int, default=30)
```

读取后：

```python
    dataset_path = _resolve_dataset(args.dataset)
    try:
        cases = load_dataset(
            dataset_path, min_items=args.min_items, max_items=args.max_items
        )
    except DatasetError as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2

    if args.api_base_url:
        return _run_api(args, dataset_path, cases)

    if args.config == "all":
        print("--config all 只支持在线模式（--api-base-url）", file=sys.stderr)
        return 2

    config_path = _resolve_config(args.config)
    try:
        cfg = load_config(config_path)
    except EvalConfigError as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2
```

新增 `_resolve_token` 与 `_run_api`：

```python
def _resolve_token(args: argparse.Namespace, base_url: str) -> str:
    if args.token:
        return args.token
    env_token = os.environ.get("EVAL_TOKEN")
    if env_token:
        return env_token
    username = args.username or os.environ.get("EVAL_USERNAME")
    password = args.password or os.environ.get("EVAL_PASSWORD")
    if not username or not password:
        raise OnlineEvalError(
            "在线模式需要 --token，或 --username/--password（也支持 EVAL_TOKEN/EVAL_PASSWORD）"
        )
    return login(base_url, username, password)


def _run_api(
    args: argparse.Namespace, dataset_path: Path, cases: list[QACase]
) -> int:
    if args.config == "all" and (args.output or args.md_output):
        print("--config all 不支持 --output/--md-output", file=sys.stderr)
        return 2

    base_url = normalize_base_url(args.api_base_url)
    try:
        if args.config == "all":
            configs = [
                load_config(ROOT / "eval" / "configs" / f"{name}.json")
                for name in ("vector", "hybrid", "hybrid_rerank")
            ]
        else:
            configs = [load_config(_resolve_config(args.config))]
    except EvalConfigError as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2

    try:
        token = _resolve_token(args, base_url)
        client = OnlineClient(base_url, token)
        payloads: list[dict[str, Any]] = []
        try:
            for cfg in configs:
                answer_enabled = (
                    cfg.retrieval == "hybrid_rerank" and not args.skip_answer
                )
                retrieval_rows, answer_rows, case_rows = _run_api_config(
                    client, cases, cfg, answer_enabled=answer_enabled
                )
                retrieval_summary = summarize_retrieval(cases, retrieval_rows)
                answer_summary = (
                    None
                    if not answer_enabled
                    else summarize_answer(
                        cases,
                        answer_rows,
                        llm_calls=0,
                        citation_retry_count=0,
                    )
                )
                payload = _build_payload(
                    dataset_name=dataset_path.stem,
                    config_name=cfg.name,
                    user_id=None,
                    cases=cases,
                    retrieval_summary=retrieval_summary,
                    answer_summary=answer_summary,
                    answer_skipped=not answer_enabled,
                    case_rows=case_rows,
                    mode="api",
                    api_base_url=base_url,
                )
                payloads.append(payload)
                json_path = args.output if args.output and len(configs) == 1 else (
                    ROOT / "eval" / "results" / f"s3-9-{cfg.name}.json"
                )
                md_path = args.md_output if args.md_output and len(configs) == 1 else (
                    ROOT / "eval" / "results" / f"s3-9-{cfg.name}.md"
                )
                _write_outputs(payload, json_path, md_path)
                print(_render_summary_markdown(payload))
                print(f"JSON：{json_path}")
                print(f"Markdown：{md_path}")
            if len(configs) > 1:
                compare_path = ROOT / "eval" / "results" / "s3-9-compare.md"
                compare_path.write_text(
                    _render_compare_markdown(payloads), encoding="utf-8"
                )
                print(_render_compare_markdown(payloads))
                print(f"对照表：{compare_path}")
        finally:
            client.close()
        return 0
    except OnlineEvalError as exc:
        print(f"在线评测失败：{exc}", file=sys.stderr)
        return 5
```

- [ ] **Step 5: 修 `_render_summary_markdown` 标题**

改为：

```python
    title = "S3-9 在线评测结果" if payload.get("mode") == "api" else "S1-7 自测结果"
    lines = [f"# {title}", ...]
```

原有断言仍通过。

- [ ] **Step 6: 运行评测测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_online_run.py backend/tests/test_eval_run.py backend/tests/test_eval_dataset.py -q
```

Expected: 全部 passed。

- [ ] **Step 7: 运行 CLI help 冒烟**

```powershell
.\.venv\Scripts\python.exe eval/run.py --help
```

Expected: 退出 0，包含 `--api-base-url` 与 `--min-items`。

- [ ] **Step 8: 提交**

```powershell
git add eval/run.py backend/tests/test_eval_online_run.py backend/tests/test_eval_run.py
git commit -m "feat(s3-9): 在线评测与三配置对照输出"
```

---

## Task 6: 真实三配置跑数

**Files:**
- Create: `eval/results/s3-9-vector.json` / `.md`
- Create: `eval/results/s3-9-hybrid.json` / `.md`
- Create: `eval/results/s3-9-hybrid_rerank.json` / `.md`
- Create: `eval/results/s3-9-compare.md`
- Modify: code only if real run finds a bug（按 TDD 修复并补测试）

**Interfaces:**
- Consumes: Task 1–5 的接口与 CLI。
- Produces: 真实三配置数字与逐题原始输出，供 Task 7 核对。

- [ ] **Step 1: 启动依赖与服务**

```powershell
cd E:\BiShe-AIStudy\study-agent
docker compose -f deploy/docker-compose.dev.yml up -d
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

启动后端（后台 job）：

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

- [ ] **Step 2: 生成真实学生 token**

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'backend'); from app.core.security import create_access_token; print(create_access_token(user_id=18, role='student').token)"
```

只把输出放进 `$env:EVAL_TOKEN`，不要写文件、不要贴进提交。

- [ ] **Step 3: 预热检索**

```powershell
$headers = @{ Authorization = "Bearer $env:EVAL_TOKEN" }
$body = @{ query = "函数的定义域怎么求？"; top_k = 5; retrieval = "hybrid_rerank" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/retrieval/search -Headers $headers -ContentType 'application/json' -Body $body
```

Expected: 200，`hits` 非空。

- [ ] **Step 4: 跑三配置**

```powershell
.\.venv\Scripts\python.exe eval/run.py `
  --dataset qa_set_m2 --config all `
  --api-base-url http://127.0.0.1:8000 `
  --token $env:EVAL_TOKEN `
  --min-items 40 --max-items 40
```

Expected：三份 JSON/MD + `s3-9-compare.md`；vector/hybrid `answer_skipped=true`；hybrid_rerank 40 条回答；退出 0。

- [ ] **Step 5: 核对结果文件**

```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; [print(p.name, json.loads(p.read_text(encoding='utf-8'))['case_count'], json.loads(p.read_text(encoding='utf-8'))['answer_skipped']) for p in Path('eval/results').glob('s3-9-*.json')]"
```

Expected：3 个文件，case_count=40，vector/hybrid answer_skipped=true，hybrid_rerank false。

- [ ] **Step 6: 真实失败修复**

若出现 401/422/SSE/检索错误：

1. 先记录真实请求与响应（不记 token）；
2. 按 systematic-debugging 找根因；
3. 补失败测试 → 修 → 重跑；
4. 不接受“换 token 绕过”或“跳过题”。

- [ ] **Step 7: 提交真实结果**

```powershell
git add eval/results/s3-9-vector.json eval/results/s3-9-vector.md eval/results/s3-9-hybrid.json eval/results/s3-9-hybrid.md eval/results/s3-9-hybrid_rerank.json eval/results/s3-9-hybrid_rerank.md eval/results/s3-9-compare.md
git commit -m "test(s3-9): 记录三配置真实评测结果"
```

---

## Task 7: 逐题核对与 `docs/EVAL_M2.md`

**Files:**
- Create: `docs/EVAL_M2.md`

**Interfaces:**
- Consumes: `s3-9-hybrid_rerank.json` 的 `cases[].answer.text/citations/refused`，以及检索结果。
- Produces: 40 行核对表、三配置表、失败解释、局限。

- [ ] **Step 1: 生成核对用简表**

```powershell
.\.venv\Scripts\python.exe -c "import json; p=json.load(open('eval/results/s3-9-hybrid_rerank.json',encoding='utf-8')); [print(c['id'], c['should_refuse'], c['answer']['refused'], c['gold_chunk_ids'], c['answer']['cited_chunk_ids'], c['answer']['text'][:80].replace(chr(10),' ')) for c in p['cases']]"
```

Expected: 40 行，无异常。

- [ ] **Step 2: 逐条判读**

对每条记录：

- `citation_ok=true`：引用块确实能支撑答案，且没有明显无关引用；
- `citation_ok=false`：引用与答案不匹配、混入无关块、或应答题没有引用；
- `refusal_ok=true`：应拒题拒答、应答题作答，且拒绝/作答本身合理；
- `refusal_ok=false`：漏拒、误拒、或数据集标签本身可疑；
- `note`：写具体原因，不写“模型问题”。

至少检查：

- 应答题 30 条是否都有答案与引用；
- 应拒题 10 条是否全部拒答；
- 公式/试卷题是否引用了题目块 + 定义块；
- 有没有“引用命中 gold 但答案不支持”的情况。

- [ ] **Step 3: 写 `docs/EVAL_M2.md`**

结构：

```markdown
# S3-9 在线链路三配置评测

> 数字来自 2026-11-02 本机真实 HTTP 调用；不是估算。
> 数据集：eval/datasets/qa_set_m2.jsonl；结果：eval/results/s3-9-*。

## 1. 数据与方法
- 40 条 = 30 应答 + 10 应拒；当前 4 篇笔记/37 chunk。
- 全部经 /retrieval/search 与 /qa/ask；回答只跑 hybrid_rerank。
- gold 为 AI 预标注 + 用户抽查；vector 延迟为混合检索中的向量部分，偏保守。

## 2. 三配置结果
（真实表格，含 hit@5/MRR@5/引用/拒答/tokens/延迟/费用）

## 3. 逐题核对
（40 行表）

## 4. 失败与解释
（逐条列 citation_ok=false / refusal_ok=false）

## 5. 已知局限
（40 条样本、37 块、主观核对、在线依赖、费用口径）
```

必须填真实数字；占位符不能提交。

- [ ] **Step 4: 统计核对通过数**

```powershell
# 人工填完后，用表格计数核对；不写脚本伪造
```

Expected: 文档写明 `citation_ok` 通过数/30（应答题）与 `refusal_ok` 通过数/40；失败题均有 note。

- [ ] **Step 5: 提交**

```powershell
git add docs/EVAL_M2.md
git commit -m "docs(s3-9): M2 三配置评测与逐题核对"
```

---

## Task 8: 文档同步与全量回归

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-9-online-eval.md`
- Modify: `docs/plan/s3-9-online-eval.md`

- [ ] **Step 1: 核对 API.md**

Task 1/2 已先写契约；最后核对 `POST /api/v1/retrieval/search` 的 `retrieval` 字段/冲突规则与 `POST /api/v1/qa/ask` 的 `done.cost_yuan` 是否与实现一致，缺漏则补。

- [ ] **Step 2: 更新 PROGRESS**

- 当前状态加 S3-9 完成；
- 任务卡 `- [x] S3-9 ...`；
- 变更日志新增 S3-9：真实 40 条、三配置数字、pytest 数字、前端是否跑、已知限制；
- 下一步指向 S4-1 或 S3-9 收尾。

- [ ] **Step 3: 更新 DECISIONS D-043**

写：

- `retrieval` 三种模式与冲突规则；
- `done.cost_yuan` 口径（含 rewrite，缓存 0）；
- 在线评测不查库、凭据不落盘、回答只跑生产；
- M2 数据集重建原因（旧 gold 25–106 已失效，当前 250–286）；
- 逐条核对为 AI 初核 + 用户抽查，不冒充人工独立标注；
- 已知限制（vector 延迟保守、样本小、在线依赖）。

- [ ] **Step 4: 更新 AI 实施计划**

S3-9 任务卡加实施记录（真实数字、命令、数据集、限制），勾选 S3-9。

- [ ] **Step 5: spec/plan 实施记录**

- `docs/spec/s3-9-online-eval.md` 末尾加 §11 实施记录；
- `docs/plan/s3-9-online-eval.md` 末尾加实施记录；
- 记录实际偏差、测试数、真实结果、未做项。

- [ ] **Step 6: 全量后端测试**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: 全部 passed；记录精确 `passed` 数。

- [ ] **Step 7: 前端回归**

S3-9 若未改前端，仍跑一次确认接口文档变更没有影响：

```powershell
npm run test:run --prefix web
npm run build --prefix web
```

Expected: 114 passed / 29 files；build 0。若耗时过长，至少跑 `npm run test:run`，并在 PROGRESS 写明 build 未跑原因。

- [ ] **Step 8: 文档提交**

```powershell
git add docs/API.md docs/PROGRESS.md docs/DECISIONS.md docs/AI协作开发实施计划.md docs/spec/s3-9-online-eval.md docs/plan/s3-9-online-eval.md
git commit -m "docs(s3-9): 在线评测实施记录与接口同步"
```

- [ ] **Step 9: 最终状态检查**

```powershell
git status --short
git log --oneline -8
```

Expected: 工作区干净；无 `.tmp_*`、token、密码文件；未 push。

---

## 自检

- **Spec 覆盖**：§3 API → Task 1/2；§4 数据 → Task 3；§5 在线 → Task 4/5；§6 指标/核对 → Task 6/7；§7 测试 → 各任务；§8 验收 → Task 6/8；§9 风险 → Task 7/8；§10 文档 → Task 8。
- **占位符扫描**：无 TODO/TBD；所有测试与命令均给出实际内容；Task 7 的表格内容必须由真实输出填写，不是占位符。
- **类型一致性**：`retrieval` 在 schema/service/API/eval 统一为 `vector|hybrid|hybrid_rerank`；`AnswerResponse.citations` 是 `list[ApiCitation]`；`_run_api_config` 返回三元组；`_build_payload` 的 `user_id` 在线为 `None`。
- **已知风险**：在线真实跑数依赖本机服务与 Key；若网络失败，按 Task 6 Step 6 修，不伪造数字。

## 执行记录（2026-11-02）

- Task 1–5 按计划 TDD 落地；Task 6 真实跑数；Task 7 的 40 行表已由真实 JSON 生成并经用户抽查；Task 8 文档同步。
- 与计划的偏差：
  1. 在线客户端初版把 `meta.citations` 全量当引用，导致引用精确率 0.228；增加“正文 `[n]` 映射到 meta”逻辑并补测试，最终 0.897。
  2. 首次重跑命中 S3-7 QA 缓存（tokens=0/费用=0），清空 `qa:v1:*` 后重跑，报告采用清缓存结果。
  3. 计划中未预见 q028 正文“未使用 [2]–[6]”被正则计入引用，作为已知解析噪声记录。
  4. 真实 `--config all` 后台管道退出码显示 1，单配置前台验证 `EXIT=0`；输出完整，未影响结果。
- 最终：后端 **770 passed, 1 warning**；真实三配置与 40 行核对见 `docs/EVAL_M2.md`；未打 tag、未 push。