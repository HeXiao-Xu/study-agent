# S1-6 带引用的回答生成 + 拒答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 CLI 跑通“检索 → 上下文 → qwen-plus 带引用回答 → 引用校验 → 低分/非法引用拒答”，并留下真实运行证据。

**Architecture:** 新增 `ai/llm` HTTP 适配器、`ai/rag/prompt_builder.py`、`ai/rag/answerer.py`、`ai/prompts/qa_v1.md` 和 `scripts/ask.py`；复用 S1-5 `retrieve_hybrid_reranked()`。Answerer 先按 rerank 最高分做阈值拒答，再组装 4,000 token 上下文，LLM 输出后校验 `[n]`，非法重试一次，仍非法则拒答。rerank 回退时跳过阈值并标记 degraded。

**Tech Stack:** Python 3.11、FastAPI 既有工程、httpx、Jinja2 3.1.6、tiktoken、pytest、DashScope compatible-mode (`qwen-plus`)。

**Spec:** `docs/spec/s1-6-answer.md`

## Global Constraints

- 所有命令在 `E:\BiShe-AIStudy\study-agent` 下执行；Python 用 `E:\BiShe-AIStudy\study-agent\.venv\Scripts\python.exe`。
- **一个任务卡只做一次提交**：各 Task 只跑测试/验证，不单独 commit；Task 8 最后统一提交。
- 测试套件禁止真实网络：LLM/Embedding/Rerank 全部 mock；真实调用只在 Task 7 人工验收。
- 不改 `docs/API.md`、`docs/SCHEMA.md`、已提交 Alembic 迁移。
- 不引入 `openai` SDK；只显式声明 Jinja2 3.1.6（已随 FastAPI 安装）。
- 不记录 question/context/answer 正文到日志；不打印 API Key。
- 合成样张 note 107 不是真实学生数据，验收输出必须带此限定。
- 引用只能使用现有字段：`note_id/source_file_id/page_no/heading_path/content`，不伪造标题。
- 失败就如实报告，不伪造测试通过、阈值或费用。

---

### Task 1: 配置、依赖与 `.env.example`

**Files:**
- Modify: `backend/app/core/config.py:51-53`
- Modify: `backend/app/core/config.py:81-92`
- Modify: `backend/requirements.txt`
- Modify: `.env.example`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: 现有 `Settings`、`_fallback_dashscope_key`。
- Produces:
  - `Settings.llm_model: str`
  - `Settings.llm_timeout_seconds: float`
  - `Settings.llm_max_retries: int`
  - `Settings.llm_temperature: float`
  - `Settings.llm_max_output_tokens: int`
  - `Settings.llm_price_input_per_million: float`
  - `Settings.llm_price_output_per_million: float`
  - `Settings.qa_context_max_tokens: int`
  - `Settings.qa_refuse_threshold: float`
  - `Settings.qa_citation_max_retries: int`
  - `Settings.llm_base_url` 空字符串时回退 DashScope compatible URL
  - `Settings.llm_api_key` 空字符串时回退 `DASHSCOPE_API_KEY`

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_config.py` 末尾追加：

```python
def test_llm_defaults(monkeypatch) -> None:
    for name in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_TEMPERATURE",
        "LLM_MAX_OUTPUT_TOKENS",
        "LLM_PRICE_INPUT_PER_MILLION",
        "LLM_PRICE_OUTPUT_PER_MILLION",
        "QA_CONTEXT_MAX_TOKENS",
        "QA_REFUSE_THRESHOLD",
        "QA_CITATION_MAX_RETRIES",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_model == "qwen-plus"
    assert s.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert s.llm_timeout_seconds == 60.0
    assert s.llm_max_retries == 2
    assert s.llm_temperature == 0.3
    assert s.llm_max_output_tokens == 1200
    assert s.llm_price_input_per_million == 0.8
    assert s.llm_price_output_per_million == 2.0
    assert s.qa_context_max_tokens == 4000
    assert s.qa_refuse_threshold == 0.45
    assert s.qa_citation_max_retries == 1


def test_llm_key_falls_back_to_dashscope(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-llm-fallback")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "sk-test-llm-fallback"
    assert "sk-test-llm-fallback" not in repr(s)


def test_llm_base_url_empty_falls_back(monkeypatch) -> None:
    """真实 .env 里 LLM_BASE_URL= 是空字符串，不能把配置覆盖成空 URL。"""
    monkeypatch.setenv("LLM_BASE_URL", "")
    s = Settings(_env_file=None)
    assert s.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_llm_key_explicit_wins_and_repr_hides(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test-llm-explicit")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "sk-test-llm-explicit"
    assert "sk-test-llm-explicit" not in repr(s)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: FAIL，`Settings` 没有 `llm_model` / 断言默认值不等。

- [ ] **Step 3: Add the settings fields**

把 `backend/app/core/config.py` 的 LLM 段替换为：

```python
    # --- LLM（S1-6；厂商 API，OpenAI 兼容接口）---
    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.3
    llm_max_output_tokens: int = 1200
    # 元/百万 token；北京区 qwen-plus 列表价，只用于估算展示
    llm_price_input_per_million: float = 0.8
    llm_price_output_per_million: float = 2.0
```

在 `rerank_price_per_million` 后追加：

```python
    # --- QA（S1-6）---
    qa_context_max_tokens: int = 4000
    qa_refuse_threshold: float = 0.45
    qa_citation_max_retries: int = 1
```

把 `_fallback_dashscope_key()` 替换为：

```python
    @model_validator(mode="after")
    def _fallback_dashscope_key(self) -> "Settings":
        """空值回退：.env 里显式写 `KEY=` 也算已设置，不能依赖默认值。"""
        if not self.embedding_api_key:
            self.embedding_api_key = self.dashscope_api_key
        if not self.rerank_api_key:
            self.rerank_api_key = self.dashscope_api_key
        if not self.llm_api_key:
            self.llm_api_key = self.dashscope_api_key
        if not self.llm_base_url:
            self.llm_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return self
```

- [ ] **Step 4: Update requirements and `.env.example`**

在 `backend/requirements.txt` 的 S1-5 段后追加：

```text
# --- S1-6 问答 Prompt 渲染（随 FastAPI 已安装，显式锁定）---
jinja2==3.1.6
```

把 `.env.example` 的 LLM 段替换为：

```env
# ===== LLM（S1-6；OpenAI 兼容接口）=====
# 留空时回退 DASHSCOPE_API_KEY；本地实际 Key 只放 .env，不提交
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
LLM_TEMPERATURE=0.3
LLM_MAX_OUTPUT_TOKENS=1200
# 元/百万 token；qwen-plus 北京区列表价，仅估算
LLM_PRICE_INPUT_PER_MILLION=0.8
LLM_PRICE_OUTPUT_PER_MILLION=2.0

# ===== QA（S1-6）=====
QA_CONTEXT_MAX_TOKENS=4000
QA_REFUSE_THRESHOLD=0.45
QA_CITATION_MAX_RETRIES=1
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
```

Expected: PASS（原 S1-3/S1-5 配置用例 + 新增 4 条）。

---

### Task 2: 让 `RetrievedChunk` 暴露 `source_file_id`

**Files:**
- Modify: `backend/app/ai/rag/retriever.py:38-52`
- Modify: `backend/app/ai/rag/retriever.py:127-139`
- Test: `backend/tests/test_retriever.py`

**Interfaces:**
- Consumes: `NoteChunk.source_file_id`（S1-3 已有列）。
- Produces: `RetrievedChunk.source_file_id: int | None`，供 Citation 使用。

- [ ] **Step 1: Write the failing test**

在 `backend/tests/test_retriever.py` 末尾追加（文件已有 `from types import SimpleNamespace` 时复用；没有就补导入）：

```python
def test_to_chunk_includes_source_file_id() -> None:
    from types import SimpleNamespace

    from app.ai.rag.retriever import _to_chunk

    row = SimpleNamespace(
        id=7,
        note_id=101,
        chunk_index=0,
        content="函数定义域",
        heading_path="函数/定义域",
        page_no=2,
        chunk_type="note",
        source_file_id=12,
    )
    result = _to_chunk(row)
    assert result.source_file_id == 12
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py::test_to_chunk_includes_source_file_id -q
```

Expected: FAIL，`RetrievedChunk` 没有 `source_file_id`。

- [ ] **Step 3: Add the field**

在 `RetrievedChunk` 的 `note_id` 后加：

```python
    source_file_id: int | None = None
```

在 `_to_chunk()` 的返回参数里 `note_id=chunk.note_id` 后加：

```python
        source_file_id=chunk.source_file_id,
```

- [ ] **Step 4: Run tests**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_retriever.py -q
```

Expected: PASS（原检索用例不回归 + 新用例通过）。

---

### Task 3: LLM 适配器

**Files:**
- Create: `backend/app/ai/llm/__init__.py`
- Create: `backend/app/ai/llm/base.py`
- Create: `backend/app/ai/llm/errors.py`
- Create: `backend/app/ai/llm/openai_compat.py`
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Consumes: `Settings`（Task 1）。
- Produces:
  - `LLMMessage(role, content)`
  - `LLMResponse(text, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, cost_yuan)`
  - `LLMClient.chat(messages, *, temperature=None, max_tokens=None) -> LLMResponse`
  - `get_llm_client() -> LLMClient`
  - `LLMError(message, *, provider="openai_compat", status_code=None, retryable=False)`

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_llm.py`：

```python
"""S1-6 LLM 适配器：全部用 httpx.MockTransport，禁止真实网络。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.ai.llm import LLMError, LLMMessage, OpenAICompatibleLLMClient


def _ok(content: str = "答[1]", usage: dict | None = None) -> httpx.Response:
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": usage,
    }
    return httpx.Response(200, json=payload)


def _client(handler, **kwargs) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def test_llm_chat_success_parses_usage_and_cost() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _ok(
            "结论[1]",
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

    client = _client(handler)
    response = client.chat(
        [LLMMessage("user", "问题")],
        temperature=0.1,
        max_tokens=200,
    )

    assert response.text == "结论[1]"
    assert response.model == "qwen-plus"
    assert response.prompt_tokens == 100
    assert response.completion_tokens == 20
    assert response.total_tokens == 120
    assert response.cost_yuan == pytest.approx(0.00012)
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://example.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test-llm"
    body = json.loads(req.content)
    assert body["model"] == "qwen-plus"
    assert body["messages"] == [{"role": "user", "content": "问题"}]
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 200


def test_llm_chat_retries_500_then_success() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return _ok()

    client = OpenAICompatibleLLMClient(
        api_key="sk-test-llm",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    response = client.chat([LLMMessage("user", "问题")])

    assert response.text == "答[1]"
    assert calls == 2
    assert len(sleeps) == 1


def test_llm_chat_400_not_retried_and_does_not_leak_body() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"error": {"message": "PROMPT_SECRET_SHOULD_NOT_LEAK"}},
        )

    client = _client(handler)
    with pytest.raises(LLMError) as exc_info:
        client.chat([LLMMessage("user", "问题")])

    assert calls == 1
    assert "HTTP 400" in str(exc_info.value)
    assert "PROMPT_SECRET_SHOULD_NOT_LEAK" not in str(exc_info.value)
    assert exc_info.value.retryable is False


def test_llm_chat_malformed_response_raises() -> None:
    client = _client(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LLMError):
        client.chat([LLMMessage("user", "问题")])


def test_llm_chat_missing_usage_defaults_zero() -> None:
    client = _client(lambda request: _ok("答[1]", None))
    response = client.chat([LLMMessage("user", "问题")])
    assert response.prompt_tokens == 0
    assert response.completion_tokens == 0
    assert response.total_tokens == 0
    assert response.cost_yuan == 0.0


def test_llm_missing_key_raises() -> None:
    with pytest.raises(LLMError):
        OpenAICompatibleLLMClient(
            api_key="",
            base_url="https://example.test/v1",
            transport=httpx.MockTransport(lambda request: _ok()),
        )


def test_llm_chat_3xx_not_success() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "https://evil.test"})

    client = _client(handler)
    with pytest.raises(LLMError) as exc_info:
        client.chat([LLMMessage("user", "问题")])
    assert calls == 1
    assert "HTTP 302" in str(exc_info.value)


def test_llm_chat_top_level_not_object_raises() -> None:
    client = _client(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(LLMError):
        client.chat([LLMMessage("user", "问题")])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_llm.py -q
```

Expected: FAIL，`ModuleNotFoundError: app.ai.llm`。

- [ ] **Step 3: Create `errors.py`**

```python
"""S1-6 LLM 错误：不携带响应正文，避免 Prompt/正文回显。"""
from __future__ import annotations


class LLMError(RuntimeError):
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

- [ ] **Step 4: Create `base.py`**

```python
"""S1-6 LLM 契约：Answerer 只依赖本文件，不直接依赖 httpx/厂商。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0


class LLMClient(ABC):
    def __init__(self, *, model: str) -> None:
        self.model = model
        self.usage_tokens = 0
        self.request_count = 0

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """发送一轮对话；网络重试由实现负责，逻辑重试由 Answerer 负责。"""
```

- [ ] **Step 5: Create `openai_compat.py`**

```python
"""OpenAI 兼容 /chat/completions 适配器（S1-6，默认 DashScope qwen-plus）。

错误信息只保留状态码/异常类型；厂商响应正文、Prompt、Key 一律不进异常/日志。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen-plus",
        timeout: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 1200,
        price_input_per_million: float = 0.8,
        price_output_per_million: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(model=model)
        if not api_key:
            raise LLMError("LLM_API_KEY 未配置", retryable=False)
        if not base_url:
            raise LLMError("LLM_BASE_URL 未配置", retryable=False)
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._price_in = price_input_per_million
        self._price_out = price_output_per_million
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages 不能为空")
        payload = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
        }
        started = time.perf_counter()
        data = self._post_with_retry(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = self._extract_text(data)
        prompt_tokens, completion_tokens, total_tokens = self._parse_usage(data)
        cost = (
            prompt_tokens * self._price_in / 1_000_000
            + completion_tokens * self._price_out / 1_000_000
        )
        self.usage_tokens += total_tokens
        self.request_count += 1
        logger.info(
            "llm_call",
            extra={
                "scene": "qa",
                "model": self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "cost_yuan": round(cost, 8),
            },
        )
        return LLMResponse(
            text=text,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_yuan=cost,
        )

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise LLMError(
                        f"LLM 网络错误（重试耗尽）：{type(exc).__name__}",
                        retryable=True,
                    ) from exc
                self._sleep(self._backoff(attempt, None))
                continue

            status = response.status_code
            if 200 <= status < 300:
                return self._json_object(response)
            if status in _RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep(self._backoff(attempt, response))
                continue
            raise LLMError(
                f"LLM 请求失败：HTTP {status}",
                status_code=status,
                retryable=status in _RETRYABLE_STATUS,
            )

        raise LLMError("LLM 请求失败：未知重试状态", retryable=True)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise LLMError("LLM 返回非 JSON", retryable=False) from exc
        if not isinstance(payload, dict):
            raise LLMError("LLM 响应顶层不是对象", retryable=False)
        return payload

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("LLM 响应缺少 choices", retryable=False)
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMError("LLM choices[0] 不是对象", retryable=False)
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMError("LLM 响应缺少 message", retryable=False)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回空回答", retryable=False)
        return content.strip()

    @staticmethod
    def _parse_usage(data: dict[str, Any]) -> tuple[int, int, int]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return 0, 0, 0

        def _int(value: object) -> int:
            try:
                number = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0
            return max(0, number)

        prompt = _int(usage.get("prompt_tokens"))
        completion = _int(usage.get("completion_tokens"))
        total_raw = usage.get("total_tokens")
        total = _int(total_raw) if total_raw is not None else prompt + completion
        return prompt, completion, total

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return min(2.0**attempt, 8.0)

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return f"OpenAICompatibleLLMClient(model={self.model!r}, url={self._url!r})"
```

- [ ] **Step 6: Create `__init__.py`**

```python
"""S1-6 LLM 门面：业务层只 import 这里。"""
from __future__ import annotations

from functools import lru_cache

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError
from app.ai.llm.openai_compat import OpenAICompatibleLLMClient
from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        price_input_per_million=settings.llm_price_input_per_million,
        price_output_per_million=settings.llm_price_output_per_million,
    )


__all__ = [
    "LLMClient",
    "LLMError",
    "LLMMessage",
    "LLMResponse",
    "OpenAICompatibleLLMClient",
    "get_llm_client",
]
```

- [ ] **Step 7: Run tests**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_llm.py -q
```

Expected: PASS（8 条）。

---

### Task 4: 上下文组装与 Prompt 渲染

**Files:**
- Create: `backend/app/ai/prompts/qa_v1.md`
- Create: `backend/app/ai/rag/prompt_builder.py`
- Test: `backend/tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: `RetrievedChunk`（含 Task 2 的 `source_file_id`）。
- Produces:
  - `Citation(index, note_id, chunk_id, source_file_id, heading_path, page_no, snippet, rerank_score)`
  - `ContextItem(citation, content, tokens)`
  - `BuiltContext(text, items, tokens, truncated)`
  - `build_context(chunks, *, max_tokens=4000) -> BuiltContext`
  - `render_prompt(context, question, *, template_path=None) -> str`
  - `PromptTemplateError`

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_prompt_builder.py`：

```python
"""S1-6 上下文组装 + Jinja2 Prompt 渲染。"""
from __future__ import annotations

import pytest

from app.ai.rag.prompt_builder import (
    PromptTemplateError,
    build_context,
    render_prompt,
)
from app.ai.rag.retriever import RetrievedChunk


def _chunk(
    chunk_id: int,
    score: float | None,
    content: str,
    *,
    note_id: int = 101,
    source_file_id: int | None = 12,
    page_no: int | None = 3,
    heading_path: str | None = "函数/单调性",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=note_id,
        source_file_id=source_file_id,
        chunk_index=chunk_id,
        content=content,
        heading_path=heading_path,
        page_no=page_no,
        rerank_score=score,
    )


def test_build_context_orders_by_rerank_and_dedupes() -> None:
    chunks = [
        _chunk(1, 0.2, "低分"),
        _chunk(2, 0.9, "高分"),
        _chunk(2, 0.8, "重复块"),
        _chunk(3, 0.5, "中分"),
    ]
    built = build_context(chunks)
    assert [item.citation.chunk_id for item in built.items] == [2, 3, 1]
    assert built.items[0].citation.index == 1
    assert built.items[0].citation.snippet == "高分"


def test_build_context_without_scores_keeps_input_order() -> None:
    built = build_context([_chunk(1, None, "一"), _chunk(2, None, "二")])
    assert [item.citation.chunk_id for item in built.items] == [1, 2]


def test_build_context_respects_token_budget() -> None:
    built = build_context(
        [_chunk(1, 0.9, "数学" * 400), _chunk(2, 0.8, "函数" * 400)],
        max_tokens=80,
    )
    assert built.tokens <= 80
    assert built.truncated is True
    assert len(built.items) == 1


def test_build_context_skips_when_header_exceeds_budget() -> None:
    assert build_context([_chunk(1, 0.9, "内容")], max_tokens=1).items == []


def test_build_context_empty_chunks() -> None:
    built = build_context([])
    assert built.items == []
    assert built.text == ""
    assert built.tokens == 0
    assert built.truncated is False


def test_build_context_citation_metadata() -> None:
    built = build_context(
        [
            _chunk(
                1,
                0.9,
                "正文",
                note_id=107,
                source_file_id=107,
                page_no=None,
                heading_path=None,
            )
        ]
    )
    citation = built.items[0].citation
    assert citation.note_id == 107
    assert citation.source_file_id == 107
    assert citation.page_no is None
    assert "页码未知" in built.text
    assert "章节未标注" in built.text
    assert "文件 #107" in built.text


def test_render_prompt_renders_context_and_question() -> None:
    rendered = render_prompt("[1] 来源：...\n正文", "错位相减法怎么用？")
    assert "[1] 来源" in rendered
    assert "错位相减法怎么用？" in rendered
    assert "{{" not in rendered


def test_render_prompt_missing_template_raises(tmp_path) -> None:
    with pytest.raises(PromptTemplateError):
        render_prompt("ctx", "q", template_path=tmp_path / "missing.md")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_prompt_builder.py -q
```

Expected: FAIL，`ModuleNotFoundError: app.ai.rag.prompt_builder`。

- [ ] **Step 3: Create the prompt template**

`backend/app/ai/prompts/qa_v1.md`：

```markdown
你是该学生的私人学习助理。请严格按以下规则回答：
1. 只能依据【参考资料】回答；资料中没有的内容，明确说"你的资料里没有相关内容"。
2. 每个来自资料的结论后必须标注引用编号，如 [1][2]；编号必须对应参考资料。
3. 若你要补充资料之外的通用知识，必须另起一段并加前缀"【补充说明｜非你的资料】"。
4. 数学推导分步骤写，公式用 LaTeX（行内 $...$，独立 $$...$$）。
5. 不要编造页码、题号、数据。

【参考资料】
{{ context }}

【学生提问】{{ question }}
```

- [ ] **Step 4: Create `prompt_builder.py`**

```python
"""S1-6 上下文组装 + Prompt 渲染。

预算按 tiktoken cl100k_base 计；排序只认 rerank 分，没有分数时保持输入顺序。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tiktoken
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.ai.rag.retriever import RetrievedChunk

CONTEXT_MAX_TOKENS = 4000
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
PROMPT_PATH = _PROMPT_DIR / "qa_v1.md"


class PromptTemplateError(RuntimeError):
    """模板缺失或渲染失败；不携带上下文正文。"""


@dataclass(frozen=True)
class Citation:
    index: int
    note_id: int
    chunk_id: int
    source_file_id: int | None
    heading_path: str | None
    page_no: int | None
    snippet: str
    rerank_score: float | None


@dataclass(frozen=True)
class ContextItem:
    citation: Citation
    content: str
    tokens: int


@dataclass(frozen=True)
class BuiltContext:
    text: str
    items: list[ContextItem]
    tokens: int
    truncated: bool


_encoding: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def _format_header(citation: Citation) -> str:
    source = (
        f"文件 #{citation.source_file_id}"
        if citation.source_file_id is not None
        else "文件未知"
    )
    page = (
        f"第 {citation.page_no} 页"
        if citation.page_no is not None
        else "页码未知"
    )
    heading = citation.heading_path or "章节未标注"
    return (
        f"[{citation.index}] 来源：笔记 #{citation.note_id} / {source} / "
        f"{page} / 章节：{heading}\n"
    )


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int = CONTEXT_MAX_TOKENS,
) -> BuiltContext:
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须为正整数")

    indexed = list(enumerate(chunks))
    indexed.sort(
        key=lambda pair: (
            pair[1].rerank_score is None,
            -(pair[1].rerank_score or 0.0),
            pair[0],
        )
    )
    ordered: list[RetrievedChunk] = []
    seen: set[int] = set()
    for _, chunk in indexed:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        ordered.append(chunk)

    enc = _encoder()
    parts: list[str] = []
    items: list[ContextItem] = []
    used = 0
    truncated = False

    for chunk in ordered:
        index = len(items) + 1
        prefix = "" if not parts else "\n\n"
        placeholder = Citation(
            index=index,
            note_id=chunk.note_id,
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            heading_path=chunk.heading_path,
            page_no=chunk.page_no,
            snippet="",
            rerank_score=chunk.rerank_score,
        )
        header = _format_header(placeholder)
        header_tokens = len(enc.encode(prefix + header))
        if used + header_tokens >= max_tokens:
            truncated = True
            break

        body_tokens = enc.encode(chunk.content)
        available = max_tokens - used - header_tokens
        if len(body_tokens) <= available:
            content = chunk.content
        else:
            lo, hi = 0, min(len(body_tokens), available)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                candidate = enc.decode(body_tokens[:mid])
                if len(enc.encode(prefix + header + candidate)) <= max_tokens - used:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                truncated = True
                break
            content = enc.decode(body_tokens[:lo])
            truncated = True

        citation = Citation(
            index=index,
            note_id=chunk.note_id,
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            heading_path=chunk.heading_path,
            page_no=chunk.page_no,
            snippet=content[:200],
            rerank_score=chunk.rerank_score,
        )
        item_text = prefix + _format_header(citation) + content
        item_tokens = len(enc.encode(item_text))
        if used + item_tokens > max_tokens:
            truncated = True
            break
        parts.append(item_text)
        items.append(ContextItem(citation=citation, content=content, tokens=item_tokens))
        used += item_tokens
        if truncated:
            break

    text = "".join(parts)
    return BuiltContext(
        text=text,
        items=items,
        tokens=len(enc.encode(text)) if text else 0,
        truncated=truncated,
    )


def render_prompt(
    context: str,
    question: str,
    *,
    template_path: Path | None = None,
) -> str:
    path = PROMPT_PATH if template_path is None else template_path
    if not path.is_file():
        raise PromptTemplateError(f"Prompt 模板不存在：{path}")
    env = Environment(
        loader=FileSystemLoader(str(path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(path.name)
        return template.render(context=context, question=question)
    except Exception as exc:  # Jinja2 的 TemplateNotFound/UndefinedError 统一收口
        raise PromptTemplateError(f"Prompt 模板渲染失败：{path}") from exc
```

- [ ] **Step 5: Run tests**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_prompt_builder.py -q
```

Expected: PASS（8 条）。

---

### Task 5: Answerer（阈值拒答、引用校验、重试、统计）

**Files:**
- Create: `backend/app/ai/rag/answerer.py`
- Test: `backend/tests/test_answerer.py`

**Interfaces:**
- Consumes:
  - `retrieve_hybrid_reranked(session, question, *, user_id, top_k, client=None, rerank_client=None) -> RetrievalResult`
  - `build_context()` / `render_prompt()` / `Citation`
  - `LLMClient` / `LLMMessage` / `LLMError`
  - `Settings`（Task 1）
- Produces:
  - `REFUSAL_TEXT: str`
  - `AnswerResult`
  - `extract_citation_indices(answer) -> list[int]`
  - `validate_citations(answer, *, context_size) -> tuple[bool, list[int]]`
  - `answer_question(session, question, *, user_id, top_k=20, threshold=None, embedding_client=None, rerank_client=None, llm_client=None) -> AnswerResult`

- [ ] **Step 1: Write the failing tests**

创建 `backend/tests/test_answerer.py`：

```python
"""S1-6 Answerer：阈值/引用/重试/统计；全部 fake，禁止真实网络。"""
from __future__ import annotations

import pytest

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError
from app.ai.rag import answerer
from app.ai.rag.answerer import (
    REFUSAL_TEXT,
    answer_question,
    extract_citation_indices,
    validate_citations,
)
from app.ai.rag.retriever import RerankInfo, RetrievalResult, RetrievedChunk


def _chunk(chunk_id: int = 1, score: float | None = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=107,
        source_file_id=107,
        chunk_index=0,
        content="错位相减法：乘公比、错位减、等比求和、再化简。",
        heading_path="数列/错位相减法",
        page_no=2,
        rerank_score=score,
    )


def _retrieval(chunks: list[RetrievedChunk], *, fallback: bool = False) -> RetrievalResult:
    info = RerankInfo(
        model="qwen3-rerank",
        candidates=30,
        top_k=6,
        tokens=10,
        latency_ms=5,
        cost_yuan=0.0,
        fallback=fallback,
    )
    return RetrievalResult(
        query="错位相减法怎么用？",
        tsquery="错位 & 相减",
        vector=chunks,
        fulltext=chunks,
        fused=chunks,
        reranked=chunks,
        elapsed_ms=7,
        rerank_info=info,
    )


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str] | None = None, error: Exception | None = None) -> None:
        super().__init__(model="fake")
        self.texts = list(texts or [])
        self.error = error
        self.calls: list[list[LLMMessage]] = []

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        text = self.texts.pop(0) if self.texts else ""
        return LLMResponse(
            text=text,
            model="fake",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=1,
            cost_yuan=0.00001,
        )


def _patch(monkeypatch, result: RetrievalResult) -> None:
    monkeypatch.setattr(
        answerer,
        "retrieve_hybrid_reranked",
        lambda *args, **kwargs: result,
    )


def test_extract_citation_indices_dedupes_and_sorts() -> None:
    assert extract_citation_indices("[2][1][2]") == [1, 2]


def test_validate_citations_accepts_valid() -> None:
    ok, indices = validate_citations("[1][2]", context_size=2)
    assert ok is True
    assert indices == [1, 2]


def test_validate_citations_rejects_out_of_range() -> None:
    ok, indices = validate_citations("[3]", context_size=2)
    assert ok is False
    assert indices == [3]


def test_validate_citations_rejects_missing() -> None:
    ok, indices = validate_citations("没有引用", context_size=2)
    assert ok is False
    assert indices == []


def test_answer_question_refuses_no_context_without_llm(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([]))
    fake = FakeLLM(["不应调用"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "no_context"
    assert result.llm_calls == 0
    assert fake.calls == []


def test_answer_question_refuses_low_score_without_llm(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=0.1)]))
    fake = FakeLLM(["不应调用"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.45, llm_client=fake
    )
    assert result.refused is True
    assert result.refusal_reason == "low_score"
    assert result.llm_calls == 0
    assert fake.calls == []


def test_answer_question_answers_with_citations(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["错位相减法：乘公比、错位减、等比求和、再化简。[1]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is False
    assert result.answer.endswith("[1]")
    assert len(result.citations) == 1
    assert result.citations[0].note_id == 107
    assert result.citations[0].index == 1
    assert result.llm_calls == 1
    assert result.citation_retry_count == 0


def test_answer_question_retries_invalid_citation_once(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["错误引用[99]", "正确引用[1]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is False
    assert result.citation_retry_count == 1
    assert result.llm_calls == 2
    assert len(fake.calls) == 2
    assert "[1]..[1]" in fake.calls[1][-1].content


def test_answer_question_refuses_after_citation_retry(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["[99]", "[98]"])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "citation_invalid"
    assert result.answer == REFUSAL_TEXT
    assert result.citations == []
    assert result.citation_retry_count == 1


def test_answer_question_empty_answer_retries_then_refuses(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(["", ""])
    result = answer_question(object(), "问题", user_id=1, llm_client=fake)
    assert result.refused is True
    assert result.refusal_reason == "empty_answer"
    assert result.llm_calls == 2


def test_answer_question_rerank_fallback_skips_threshold(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=None)], fallback=True))
    fake = FakeLLM(["回答[1]"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.99, llm_client=fake
    )
    assert result.refused is False
    assert result.degraded is True
    assert result.top_rerank_score is None
    assert result.llm_calls == 1


def test_answer_question_no_scores_degrades(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk(score=None)], fallback=False))
    fake = FakeLLM(["回答[1]"])
    result = answer_question(
        object(), "问题", user_id=1, threshold=0.99, llm_client=fake
    )
    assert result.refused is False
    assert result.degraded is True
    assert result.llm_calls == 1


def test_answer_question_does_not_swallow_llm_error(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    fake = FakeLLM(error=LLMError("boom"))
    with pytest.raises(LLMError):
        answer_question(object(), "问题", user_id=1, llm_client=fake)


def test_answer_question_rejects_invalid_threshold(monkeypatch) -> None:
    _patch(monkeypatch, _retrieval([_chunk()]))
    with pytest.raises(ValueError):
        answer_question(object(), "问题", user_id=1, threshold=1.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_answerer.py -q
```

Expected: FAIL，`ModuleNotFoundError: app.ai.rag.answerer`。

- [ ] **Step 3: Create `answerer.py`**

```python
"""S1-6 带引用回答与拒答。

流程：检索 → 阈值 → 上下文 → LLM → 引用校验 → 一次重试 → 拒答。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.ai.embedding import EmbeddingClient
from app.ai.llm import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponse,
    get_llm_client,
)
from app.ai.rag.prompt_builder import (
    Citation,
    build_context,
    render_prompt,
)
from app.ai.rag.retriever import RetrievalResult, retrieve_hybrid_reranked
from app.ai.rerank import RerankClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "在你的笔记中没找到相关内容。可以换个问法，或先补充相关笔记。"
_CITATION_RE = re.compile(r"\[(\d+)\]")

RefusalReason = Literal[
    "no_context",
    "low_score",
    "citation_invalid",
    "empty_answer",
]


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    refused: bool
    refusal_reason: RefusalReason | None
    citations: list[Citation]
    context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    retrieval_ms: int
    llm_ms: int
    latency_ms: int
    cost_yuan: float
    llm_calls: int
    citation_retry_count: int
    degraded: bool
    top_rerank_score: float | None


def extract_citation_indices(answer: str) -> list[int]:
    return sorted({int(match.group(1)) for match in _CITATION_RE.finditer(answer)})


def validate_citations(
    answer: str,
    *,
    context_size: int,
) -> tuple[bool, list[int]]:
    indices = extract_citation_indices(answer)
    if not indices:
        return False, []
    if any(index < 1 or index > context_size for index in indices):
        return False, indices
    return True, indices


def _refused(
    reason: RefusalReason,
    *,
    retrieval_ms: int,
    context_tokens: int = 0,
    top_rerank_score: float | None = None,
    degraded: bool = False,
    llm_calls: int = 0,
    citation_retry_count: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    llm_ms: int = 0,
    cost_yuan: float = 0.0,
) -> AnswerResult:
    return AnswerResult(
        answer=REFUSAL_TEXT,
        refused=True,
        refusal_reason=reason,
        citations=[],
        context_tokens=context_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        latency_ms=retrieval_ms + llm_ms,
        cost_yuan=cost_yuan,
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        degraded=degraded,
        top_rerank_score=top_rerank_score,
    )


def _cited(context_items, indices: list[int]) -> list[Citation]:
    return [context_items[index - 1].citation for index in indices]


def _call_llm(
    client: LLMClient,
    messages: list[LLMMessage],
    *,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    return client.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def answer_question(
    session: Session,
    question: str,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    llm_client: LLMClient | None = None,
) -> AnswerResult:
    if not question.strip():
        raise ValueError("question 不能为空")
    settings = get_settings()
    threshold_value = settings.qa_refuse_threshold if threshold is None else threshold
    if not 0.0 <= threshold_value <= 1.0:
        raise ValueError("threshold 必须在 [0, 1]")

    retrieval_started = time.perf_counter()
    retrieval: RetrievalResult = retrieve_hybrid_reranked(
        session,
        question,
        user_id=user_id,
        top_k=top_k,
        client=embedding_client,
        rerank_client=rerank_client,
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    if not retrieval.reranked:
        return _refused("no_context", retrieval_ms=retrieval_ms)

    scores = [
        chunk.rerank_score
        for chunk in retrieval.reranked
        if chunk.rerank_score is not None
    ]
    top_score = max(scores) if scores else None
    degraded = bool(
        (retrieval.rerank_info and retrieval.rerank_info.fallback)
        or top_score is None
    )
    if not degraded and top_score is not None and top_score < threshold_value:
        return _refused(
            "low_score",
            retrieval_ms=retrieval_ms,
            top_rerank_score=top_score,
        )

    built = build_context(
        retrieval.reranked,
        max_tokens=settings.qa_context_max_tokens,
    )
    if not built.items:
        return _refused(
            "no_context",
            retrieval_ms=retrieval_ms,
            top_rerank_score=top_score,
            degraded=degraded,
        )

    prompt = render_prompt(built.text, question)
    client = llm_client if llm_client is not None else get_llm_client()
    messages = [LLMMessage(role="user", content=prompt)]
    started = time.perf_counter()
    first = _call_llm(
        client,
        messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms = first.latency_ms
    prompt_tokens = first.prompt_tokens
    completion_tokens = first.completion_tokens
    total_tokens = first.total_tokens
    cost_yuan = first.cost_yuan
    llm_calls = 1

    ok, indices = validate_citations(first.text, context_size=len(built.items))
    citation_retry_count = 0
    if ok:
        return AnswerResult(
            answer=first.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(built.items, indices),
            context_tokens=built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=degraded,
            top_rerank_score=top_score,
        )

    if settings.qa_citation_max_retries < 1:
        return _refused(
            "citation_invalid",
            retrieval_ms=retrieval_ms,
            context_tokens=built.tokens,
            top_rerank_score=top_score,
            degraded=degraded,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            llm_ms=llm_ms,
            cost_yuan=cost_yuan,
        )

    correction = (
        f"你上一次回答的引用编号不合法或缺失。本次可用的引用编号只有 "
        f"[1]..[{len(built.items)}]。请重写回答，只使用这些编号；"
        "如果资料不足，直接回答“你的资料里没有相关内容”。"
        "不要解释校验过程，不要使用不存在的编号。"
    )
    retry_messages = messages + [
        LLMMessage(role="assistant", content=first.text or "(空回答)"),
        LLMMessage(role="user", content=correction),
    ]
    second = _call_llm(
        client,
        retry_messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_output_tokens,
    )
    llm_ms += second.latency_ms
    prompt_tokens += second.prompt_tokens
    completion_tokens += second.completion_tokens
    total_tokens += second.total_tokens
    cost_yuan += second.cost_yuan
    llm_calls += 1
    citation_retry_count = 1

    ok, indices = validate_citations(second.text, context_size=len(built.items))
    if ok:
        return AnswerResult(
            answer=second.text,
            refused=False,
            refusal_reason=None,
            citations=_cited(built.items, indices),
            context_tokens=built.tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
            latency_ms=retrieval_ms + llm_ms,
            cost_yuan=cost_yuan,
            llm_calls=llm_calls,
            citation_retry_count=citation_retry_count,
            degraded=degraded,
            top_rerank_score=top_score,
        )

    reason: RefusalReason = (
        "empty_answer" if not second.text.strip() else "citation_invalid"
    )
    return _refused(
        reason,
        retrieval_ms=retrieval_ms,
        context_tokens=built.tokens,
        top_rerank_score=top_score,
        degraded=degraded,
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        llm_ms=llm_ms,
        cost_yuan=cost_yuan,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_answerer.py -q
```

Expected: PASS（10 条）。

---

### Task 6: CLI、日志流与校准脚本

**Files:**
- Modify: `backend/app/core/logging.py:47-58`
- Create: `scripts/ask.py`
- Create: `scripts/calibrate_refusal.py`
- Test: `backend/tests/test_s1_6_scripts.py`

**Interfaces:**
- Consumes: `answer_question()`、`AnswerResult`、`Settings`、`new_session()`。
- Produces:
  - `setup_logging(level="INFO", *, stream=None)`
  - `python scripts/ask.py [question]`
  - `python scripts/calibrate_refusal.py`

- [ ] **Step 1: Write the failing test**

创建 `backend/tests/test_s1_6_scripts.py`：

```python
"""S1-6 脚本冒烟：只跑 --help，不连库、不调外部 API。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_s1_6_scripts_help() -> None:
    for name in ("ask.py", "calibrate_refusal.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
        assert "usage" in result.stdout.lower() or "用法" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_s1_6_scripts.py -q
```

Expected: FAIL，脚本不存在。

- [ ] **Step 3: Add `stream` to `setup_logging`**

把 `backend/app/core/logging.py` 的 `setup_logging` 替换为：

```python
def setup_logging(level: str = "INFO", *, stream=None) -> None:
    """进程入口调用一次；CLI 传 stderr，避免 JSON 日志混进答案 stdout。"""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.propagate = False
```

- [ ] **Step 4: Create `scripts/ask.py`**

```python
"""S1-6 带引用问答 CLI。

用法：
    python scripts/ask.py "我笔记里关于错位相减法是怎么总结的？"
    python scripts/ask.py --user-id 1 "今天北京天气怎么样？"
    python scripts/ask.py          # 交互循环
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.llm.errors import LLMError  # noqa: E402
from app.ai.rag.answerer import AnswerResult, answer_question  # noqa: E402
from app.ai.rag.prompt_builder import PromptTemplateError  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402


def _format_citation(citation) -> str:
    source = f"文件 #{citation.source_file_id}" if citation.source_file_id is not None else "文件未知"
    page = f"第 {citation.page_no} 页" if citation.page_no is not None else "页码未知"
    heading = citation.heading_path or "章节未标注"
    return (
        f"[{citation.index}] 笔记 #{citation.note_id} / {source} / "
        f"{page} / 章节：{heading}"
    )


def _print_result(question: str, result: AnswerResult, *, debug: bool) -> None:
    print(f"问题：{question}")
    print("回答：")
    print(result.answer)
    if result.citations:
        print("\n引用：")
        for citation in result.citations:
            print(_format_citation(citation))
            print(f"    片段：{citation.snippet.replace(chr(10), ' ')[:160]}")
    if debug:
        print(
            f"\n调试：refused={result.refused} reason={result.refusal_reason} "
            f"degraded={result.degraded} top_score={result.top_rerank_score} "
            f"context_tokens={result.context_tokens} llm_calls={result.llm_calls}"
        )
    print(
        f"\n统计：refused={'是' if result.refused else '否'} "
        f"tokens={result.prompt_tokens}/{result.completion_tokens}/{result.total_tokens} "
        f"latency=retrieval {result.retrieval_ms}ms + llm {result.llm_ms}ms "
        f"= {result.latency_ms}ms "
        f"cost=¥{result.cost_yuan:.6f}"
    )


def _ask_one(question: str, *, user_id: int, top_k: int, threshold: float | None, debug: bool) -> int:
    try:
        with new_session() as session:
            result = answer_question(
                session,
                question,
                user_id=user_id,
                top_k=top_k,
                threshold=threshold,
            )
            _print_result(question, result, debug=debug)
            return 0
    except LLMError as exc:
        print(f"LLM 调用失败：{exc}", file=sys.stderr)
        return 2
    except PromptTemplateError as exc:
        print(f"Prompt 模板错误：{exc}", file=sys.stderr)
        return 3
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 4
    except EmbeddingError as exc:
        print(f"Embedding 调用失败：{exc}", file=sys.stderr)
        return 5


def main() -> int:
    parser = argparse.ArgumentParser(description="S1-6 带引用问答 CLI")
    parser.add_argument("question", nargs="?", help="问题；不传则进入交互循环")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, stream=sys.stderr)
    set_trace_id("qa-" + uuid.uuid4().hex[:12])

    if args.question:
        return _ask_one(
            args.question,
            user_id=args.user_id,
            top_k=args.top_k,
            threshold=args.threshold,
            debug=args.debug,
        )

    last_code = 0
    while True:
        try:
            question = input("问题（exit 退出）> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return last_code
        if question.lower() in {"exit", "quit"}:
            return last_code
        if not question:
            continue
        last_code = _ask_one(
            question,
            user_id=args.user_id,
            top_k=args.top_k,
            threshold=args.threshold,
            debug=args.debug,
        )


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Create `scripts/calibrate_refusal.py`**

```python
"""S1-6 小校准：10 个应答题 + 5 个应拒题，只跑检索/rerank，不调 LLM。

用法：
    python scripts/calibrate_refusal.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.rag.retriever import retrieve_hybrid_reranked  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402

ANSWERABLE_QUESTIONS = [
    "函数的定义域怎么求？",
    "函数单调性的定义是什么？",
    "如何用定义证明函数在区间上单调递增？",
    "奇函数和偶函数有什么性质？",
    "二次函数在闭区间上的最值怎么求？",
    "分段函数 f(f(-1)) 怎么求？",
    "函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？",
    "已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？",
    "函数图象关于原点对称说明什么？",
    "商品定价最大利润问题怎么建模？",
]

REFUSAL_QUESTIONS = [
    "今天北京天气怎么样？",
    "怎么用 Python 写一个网页爬虫？",
    "《红楼梦》的作者是谁？",
    "出国留学需要准备哪些材料？",
    "今天股市行情怎么样？",
]


def _top_score(result) -> float | None:
    scores = [
        chunk.rerank_score
        for chunk in result.reranked
        if chunk.rerank_score is not None
    ]
    return max(scores) if scores else None


def _print_result(label: str, question: str, result, score: float | None) -> None:
    top = result.reranked[0] if result.reranked else None
    fallback = bool(result.rerank_info and result.rerank_info.fallback)
    source = (
        f"note={top.note_id} page={top.page_no} heading={top.heading_path}"
        if top is not None
        else "无结果"
    )
    score_text = f"{score:.4f}" if score is not None else "N/A"
    print(f"[{label}] top1={score_text} fallback={fallback} {source}")
    print(f"  {question}")


def main() -> int:
    set_trace_id("calibrate-" + uuid.uuid4().hex[:12])
    answerable: list[float] = []
    refusal: list[float] = []
    try:
        with new_session() as session:
            for index, question in enumerate(ANSWERABLE_QUESTIONS, start=1):
                result = retrieve_hybrid_reranked(
                    session,
                    question,
                    user_id=1,
                    top_k=20,
                )
                score = _top_score(result)
                _print_result(f"应答题 {index}/10", question, result, score)
                if score is not None:
                    answerable.append(score)

            for index, question in enumerate(REFUSAL_QUESTIONS, start=1):
                result = retrieve_hybrid_reranked(
                    session,
                    question,
                    user_id=1,
                    top_k=20,
                )
                score = _top_score(result)
                _print_result(f"应拒题 {index}/5", question, result, score)
                if score is not None:
                    refusal.append(score)
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

    print("\n汇总：")
    print(f"  应答题 top1 最低：{min(answerable):.4f}" if answerable else "  应答题 top1 最低：N/A")
    print(f"  应拒题 top1 最高：{max(refusal):.4f}" if refusal else "  应拒题 top1 最高：N/A")
    if answerable and refusal and min(answerable) > max(refusal):
        print(
            f"  建议 τ 可取间隔中点：{(min(answerable) + max(refusal)) / 2:.4f}"
        )
    else:
        print("  0.45 无法分开：需扩充语料/换分数口径，不能伪造通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run tests**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest tests/test_s1_6_scripts.py -q
```

Expected: PASS（1 条，内部跑两个 `--help`）。

---

### Task 7: 合成样张、真实校准与 CLI 验收

**Files:**
- Create outside repo: `E:\BiShe-AIStudy\测试数据\高中数学笔记-数列求和错位相减.docx`
- Create: `eval/results/s1-6-qa-demo.txt`
- Create: `eval/results/s1-6-refusal-calibration.txt`
- Modify: `docs/spec/s1-6-answer.md` §15（回填实测）

**Interfaces:**
- Consumes: Task 1–6 全部代码。
- Produces: 真实 qwen-plus 调用证据与 note 107 语料。

- [ ] **Step 1: Generate the synthetic DOCX outside the repo**

用仓库 `.venv` 的 python-docx 生成（脚本可放 `E:\BiShe-AIStudy\测试数据\_make_s1_6_sample.py`，不提交）：

```python
from docx import Document

path = r"E:\BiShe-AIStudy\测试数据\高中数学笔记-数列求和错位相减.docx"
doc = Document()
doc.add_heading("高中数学笔记：数列求和（错位相减法）", level=1)

doc.add_heading("一、适用条件", level=2)
doc.add_paragraph(
    "当数列的通项是“等差 × 等比”的形式，例如 a_n=(2n-1)·2^n，"
    "直接求和没有现成公式，可以优先考虑错位相减法。"
)

doc.add_heading("二、错位相减法的步骤", level=2)
doc.add_paragraph("第一步：写出 S_n = a_1 + a_2 + ... + a_n。")
doc.add_paragraph("第二步：两边同时乘等比部分的公比 q，得到 qS_n。")
doc.add_paragraph("第三步：把 S_n 与 qS_n 按相同次幂对齐，错位相减。")
doc.add_paragraph("第四步：中间项构成等比数列，用等比数列求和公式化简。")
doc.add_paragraph("第五步：解出 S_n，并检查首项、末项和常数项。")

doc.add_heading("三、例题", level=2)
doc.add_paragraph("求和 S_n = 1·2 + 3·2^2 + 5·2^3 + ... + (2n-1)·2^n。")
doc.add_paragraph("两边乘 2：2S_n = 1·2^2 + 3·2^3 + ... + (2n-3)·2^n + (2n-1)·2^{n+1}。")
doc.add_paragraph("错位相减：S_n - 2S_n = 2 + 2·(2^2+2^3+...+2^n) - (2n-1)·2^{n+1}。")
doc.add_paragraph("化简得 S_n = (2n-3)·2^{n+1} + 6。")

doc.add_heading("四、易错点", level=2)
doc.add_paragraph("乘公比后要对齐指数，不能漏项。")
doc.add_paragraph("中间项是等比数列求和，注意项数和首项。")
doc.add_paragraph("最后解 S_n 时符号容易错，建议代 n=1 检验。")

doc.add_heading("五、总结口诀", level=2)
doc.add_paragraph("错位相减法口诀：乘公比、错位减、等比求和、再化简。")

doc.save(path)
print(path)
```

运行：

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe "E:\BiShe-AIStudy\测试数据\_make_s1_6_sample.py"
```

- [ ] **Step 2: Index note 107**

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe scripts/index_demo.py "E:\BiShe-AIStudy\测试数据\高中数学笔记-数列求和错位相减.docx" --note-id 107 --user-id 1 --source-file-id 107
```

Expected: 入库成功，块数 8；记录真实块数/tokens/费用。

- [ ] **Step 3: Verify corpus by SQL**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c "select note_id, count(*) from note_chunks group by note_id order by note_id;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select heading_path, left(content,50) from note_chunks where note_id=107 order by chunk_index;"
docker exec study-agent-postgres psql -U study -d study_agent -c "select count(*) from note_chunks where content like '%错位相减%';"
```

Expected: note 107 存在；`错位相减` 命中至少 1 行。

- [ ] **Step 4: Run small calibration and save real output**

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe scripts/calibrate_refusal.py | tee eval/results/s1-6-refusal-calibration.txt
```

Expected: 15 题都有 top1 分；记录应答题最低/应拒题最高。若 0.45 分不开，**先停**，把真实分布报告给用户，不伪造。

- [ ] **Step 5: Run real CLI acceptance and save output**

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe scripts/ask.py "我笔记里关于错位相减法是怎么总结的？" | tee eval/results/s1-6-qa-demo.txt
.venv\Scripts\python.exe scripts/ask.py "今天北京天气怎么样？" | tee -a eval/results/s1-6-qa-demo.txt
```

Expected:

- 第一条：`refused=否`，答案含 `[1]` 等引用，引用能追到 note 107；`llm_calls` 1 或 2。
- 第二条：`refused=是`，`llm_calls=0`，`reason` 为 `low_score` 或 `no_context`。

如果第一条真实调用失败：记录 `LLMError` / HTTP 状态，检查 `.env` 的 `DASHSCOPE_API_KEY`、base URL、模型名；不得伪造输出，也不得把失败写成通过。

- [ ] **Step 6: Backfill spec §15**

把实际结果写入 `docs/spec/s1-6-answer.md` §15：

```markdown
- 实际测试数量：<真实 pytest 数量>
- note 107 实际块数：<SQL 实测>
- 真实 CLI 输出：eval/results/s1-6-qa-demo.txt
- 校准 15 题分数：应答题最低 <x>，应拒题最高 <y>，τ=<实际使用值>
- 与 plan 的偏离：<无/具体>
- 已知问题：<无/具体>
```

所有 `<...>` 必须替换为真实数字/文字，禁止保留占位符。

---

### Task 8: 文档同步、全量验证与最终提交

**Files:**
- Modify: `docs/PROGRESS.md:9-11,29-31,102+`
- Modify: `docs/DECISIONS.md`（追加 D-019）
- Modify: `AGENTS.md:9.6`（追加 LLM/QA 锚点）
- Modify: `docs/spec/s1-6-answer.md` §15
- Modify: `docs/plan/s1-6-answer.md`（勾选完成 + 实测回填）
- Test: 全量 pytest

**Interfaces:**
- Consumes: Task 1–7 全部产物。
- Produces: 可提交的单次 commit。

- [ ] **Step 1: Update PROGRESS**

把“当前状态”改成：

```markdown
- 阶段：阶段 1（RAG 技术验证，M0）——阶段 0 已完成（tag `m0-env-ready`）
- 最近完成：S1-6 带引用回答 + 拒答（qwen-plus / 4,000 token 上下文 / 引用校验重试 / τ 小校准；真实 CLI 证据见 eval/results/s1-6-qa-demo.txt；pytest <实测数量>）
- 下一步：S1-7 自测用例与效果抽查 20–30 条 ★
- 已知阻塞：无
```

任务清单：

```markdown
- [x] S1-6 带引用回答 + 拒答 ★
- [ ] S1-7 自测用例与效果抽查 20–30 条 ★
```

变更日志追加（日期用实际运行日期）：

```markdown
### 2026-10-20
- S1-6 完成（按 §10 全流程：spec docs/spec/s1-6-answer.md + plan docs/plan/s1-6-answer.md，均经用户确认后实施）。交付：backend/app/ai/llm/（base/errors/openai_compat/门面）、backend/app/ai/rag/prompt_builder.py、backend/app/ai/rag/answerer.py、backend/app/ai/prompts/qa_v1.md、scripts/ask.py、scripts/calibrate_refusal.py；Settings + .env.example + requirements（jinja2 3.1.6）；note 107 合成数列样张
- 验收证据：pytest <实测>；真实 qwen-plus CLI 回答带引用、天气问题拒答且 llm_calls=0；15 题小校准 top1 分布与 τ 见 eval/results/s1-6-refusal-calibration.txt
- 已知限制：引用无标题/文件名（S2 补）；note 107 为合成样张，不是真实学生数据；完整 20+10 校准留 S1-7
```

- [ ] **Step 2: Add DECISIONS D-019**

在 `docs/DECISIONS.md` 末尾追加：

```markdown
## D-019 S1-6 带引用回答与拒答实现决策（spec §4/§7/§15 归档）

- 日期：<实际日期>
- 背景：S1-5 已有 rerank top6，需要在 CLI 证明“回答能溯源、无依据会拒答”。
- 决策：
  1. LLM 用 DashScope compatible-mode + qwen-plus，httpx 手写适配器；不引入 openai SDK。
  2. Prompt 用 Jinja2 + `ai/prompts/qa_v1.md`；上下文预算 4,000 token，按 rerank 分排序截断。
  3. 引用校验只认本次上下文编号；非法/缺失重试一次，仍非法拒答。
  4. 默认 τ=0.45；用 10 应答题 + 5 应拒题小校准；完整 20+10 留 S1-7。
  5. rerank 失败回退时跳过阈值，继续用 RRF 顺序并标记 degraded。
  6. note 107 是为验收问题补的合成样张，不是真实学生数据；引用暂不显示标题/文件名。
- 回退：LLM Key/模型不可用则 CLI 明确报错；引用校验可降级为人工抽查；S2 建表后补标题。
```

- [ ] **Step 3: Update AGENTS §9.6**

在“RAG 检索器样例”后追加：

```markdown
- ai LLM 适配器样例：backend/app/ai/llm/openai_compat.py（OpenAI 兼容 /chat/completions；httpx；超时/重试/usage/费用；错误不带响应正文；门面 `get_llm_client()`）
- RAG 回答器样例：backend/app/ai/rag/answerer.py（阈值拒答 → 上下文 → LLM → 引用校验 → 一次重试；日志只记计数/耗时/费用）
```

- [ ] **Step 4: Run full test suite**

```bash
cd E:\BiShe-AIStudy\study-agent\backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: 全绿；记录真实 `N passed`，不得写“应该通过”。

- [ ] **Step 5: Check diff and privacy**

```bash
cd E:\BiShe-AIStudy\study-agent
git status --short
git diff --stat
git diff --check
git diff | findstr /I "sk- DASHSCOPE_API_KEY LLM_API_KEY"
```

Expected: 无 Key 泄漏；无 `.env` 被跟踪；无 DOCX 样张进入仓库；无 API.md/SCHEMA.md 改动。

- [ ] **Step 6: Commit once**

```bash
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/llm backend/app/ai/rag/prompt_builder.py backend/app/ai/rag/answerer.py backend/app/ai/prompts/qa_v1.md backend/app/core/config.py backend/app/core/logging.py backend/app/ai/rag/retriever.py backend/requirements.txt backend/tests scripts/ask.py scripts/calibrate_refusal.py docs/spec/s1-6-answer.md docs/plan/s1-6-answer.md docs/PROGRESS.md docs/DECISIONS.md AGENTS.md .env.example eval/results/s1-6-qa-demo.txt eval/results/s1-6-refusal-calibration.txt
git commit -m "feat(s1-6): 带引用回答与拒答（qwen-plus + 引用校验 + CLI）"
```

不要 push；用户负责 push。

- [ ] **Step 7: Final report**

向用户报告：

- 实际 pytest 数量与结果；
- 两条验收命令的真实输出摘要；
- note 107 块数、τ、校准应答题最低/应拒题最高；
- 与 spec 的偏离/已知限制；
- commit hash；提醒用户 push。

---

## 执行记录（2026-10-20）

- 实际测试：**160 passed, 1 warning**（基线 124 + 新增 36）。
- note 107：**8 块**；全库 **83 块 / 7 note**；`错位相减` 命中 5 行。
- 真实 CLI：`eval/results/s1-6-qa-demo.txt`；错位相减 `refused=否`、4 条引用、`llm_calls=1`；天气 `refused=是`、`reason=low_score`、`llm_calls=0`。
- 校准：应答题 top1 最低 0.4586，应拒题最高 0.4347，中点 0.4467；经用户确认 τ 由 0.35 改为 **0.45**。
- 偏离：
  1. τ 0.35 → 0.45（真实小校准不支持 0.35）。
  2. note 107 预计 5–7 块 → 实测 8 块。
  3. `ask.py`/`calibrate_refusal.py` 增加 `_configure_stdio()`；`calibrate_refusal.py` 补 argparse，避免 `--help` 误跑真实检索。
  4. `index_demo.py` 在 GBK 控制台打印 `¥` 报 UnicodeEncodeError（数据已入库）；S1-6 脚本已规避，未改 index_demo。
  5. 校准输出的 note 101 标题含真实校名，脚本用通用正则替换为“某学校”，不在代码里维护真实名单。
- 已知：τ 与应答题最低分间隔仅 0.0086；引用校验只查编号存在性；无标题/文件名；无 API/SCHEMA/迁移改动。

## Self-Review

### Spec coverage

| Spec 要求 | 对应 Task |
|---|---|
| LLM 适配器、qwen-plus、httpx、重试/超时/费用 | Task 3 |
| 上下文去重/排序/4,000 token/编号 | Task 4 |
| Prompt 模板 C1、Jinja2 | Task 4 |
| 阈值拒答、无 LLM 调用 | Task 5 |
| 引用校验、非法重试一次、仍非法拒答 | Task 5 |
| rerank 回退跳过阈值、degraded | Task 5 |
| 引用字段（note_id/source_file_id/page_no/heading_path/snippet） | Task 2 + Task 4 |
| CLI 单问/交互、token/耗时/费用 | Task 6 |
| 15 题小校准 | Task 6 + Task 7 |
| 配置/.env.example/requirements | Task 1 |
| 测试全 mock、真实 CLI 验收 | Task 3–7 |
| PROGRESS/DECISIONS/AGENTS/spec 回填 | Task 8 |
| 合成 note 107 | Task 7 |
| 不改 API.md/SCHEMA.md/迁移 | Global Constraints + Task 8 diff check |

### Placeholder scan

Task 7 Step 6 / Task 8 的 `<...>` 是执行时必须替换的实测值，不是实现占位；实现代码块中没有 TBD/TODO。若执行时无法得到真实值，必须报告失败，不得填假数字。

### Type consistency

- `Citation` 字段在 Task 4 定义，Task 5/6 使用一致。
- `AnswerResult.citation_retry_count`、`llm_calls`、`degraded`、`top_rerank_score` 在 Task 5/6 一致。
- `LLMClient.chat(messages, *, temperature, max_tokens)` 在 Task 3/5 一致。
- `build_context(chunks, *, max_tokens)` 在 Task 4/5 一致。
- `retrieve_hybrid_reranked(..., client=..., rerank_client=...)` 与 S1-5 现有签名一致。
- `setup_logging(level, *, stream=None)` 在 Task 6 定义并被 `ask.py` 使用。