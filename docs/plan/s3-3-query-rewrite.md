# S3-3 Query 改写与意图识别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把用户问题改写为可独立检索的查询、识别 4 类意图、用最近 3 轮补全指代，并在 LLM 失败时降级回原问题。

**Architecture:** LLM/Prompt/严格 JSON 放 `ai/rag/query_rewriter.py`；`services/query_rewrite.py` 只做历史裁剪、进程内 LRU/TTL 缓存、失败降级与日志；S3-5 将来读消息后传入 history，本轮不暴露 HTTP 接口。

**Tech Stack:** Python 3.11、Pydantic v2、Jinja2、现有 `LLMClient`（OpenAI 兼容）、pytest；不新增依赖、不加表/迁移。

**Spec:** `docs/spec/s3-3-query-rewrite.md`

## Global Constraints

- 不新增第三方依赖；不加表/迁移；不改 `answer_question`、`retrieval_service`、API.md/SCHEMA.md。
- AI 调用只在 `ai/` 层；service 不直接 import httpx/厂商 SDK。
- 4 类意图：`note_query` / `question_query` / `concept_explain` / `chitchat`；意图只做流程分支，不改检索 scope。
- 历史由调用方传入，不含当前问题，升序；只取最近 3 个 user 轮，单条截 300 字。
- LLM 失败（超时/非 JSON/字段非法）重试 2 次后降级：原问题 + `note_query` + `degraded=True`，检索继续。
- 缓存只在进程内，只缓存成功结果；`use_cache=False` 跳过读写。
- 测试禁止真实外部调用；pytest 全绿才提交；Conventional Commits 带 `(s3-3)`；`git push` 由用户执行。
- 真实数字必须来自实跑，不调样本、不改判定。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/ai/prompts/rewrite_v1.md` | 新建 | 4 类意图、指代补全、严格 JSON 指令 |
| `backend/app/ai/rag/query_rewriter.py` | 新建 | Prompt 渲染、JSON 解析、Pydantic 校验、2 次重试、`RewriteCall`/`RewriteError` |
| `backend/app/ai/llm/base.py`、`openai_compat.py` | 修改 | `chat(..., scene="qa")`，日志记录真实场景 |
| `backend/app/services/query_rewrite.py` | 新建 | `rewrite_query`、历史裁剪、LRU/TTL、降级、`clear_cache` |
| `backend/app/core/config.py`、`.env.example` | 修改 | 6 个 `QUERY_REWRITE_*` 配置 |
| `backend/tests/test_query_rewriter.py` | 新建 | AI 层 9 条 |
| `backend/tests/test_query_rewrite_service.py` | 新建 | service 层 10 条 |
| `backend/tests/test_llm.py` | 修改 | +1 条 scene 日志用例 |
| `scripts/rewrite_eval.py` | 新建 | 10 条指代追问真实改写 + 检索 hit@3 |
| `docs/*` | 修改 | DECISIONS/PROGRESS/AGENTS/实施计划/spec/plan |

---

### Task 1: AI 层改写器与 scene 日志

**Files:**
- Create: `backend/app/ai/prompts/rewrite_v1.md`
- Create: `backend/app/ai/rag/query_rewriter.py`
- Modify: `backend/app/ai/llm/base.py`
- Modify: `backend/app/ai/llm/openai_compat.py`
- Test: `backend/tests/test_query_rewriter.py`
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Produces: `Intent`、`HistoryTurn(role, content)`、`RewriteOutput`、`RewriteCall`、`RewriteError`、`REWRITE_PROMPT_VERSION="v1"`、`render_prompt(question, history)`、`rewrite_with_llm(question, *, history=None, llm_client=None, max_tokens=400, max_retries=2) -> RewriteCall`。
- 修改：`LLMClient.chat(..., scene: str = "qa")`；实现日志 `scene` 使用传入值。

- [ ] **Step 1: 写 Prompt 模板**

`backend/app/ai/prompts/rewrite_v1.md`：

```markdown
你是检索查询改写器，只输出 JSON，不要解释，不要 Markdown 围栏。

意图只能是以下 4 类：
- note_query：问学生自己笔记/资料里记过的内容
- question_query：要题、找题、问题目/练习题
- concept_explain：问定义、性质、方法、推导
- chitchat：问候、感谢、与学习无关的闲聊

规则：
1. 结合【最近对话】补全指代，把【当前问题】改写成脱离上下文也能检索的完整问题。
2. 只改写，不回答；不要添加资料中没有的信息。
3. 保留数学符号、公式、函数名、区间。
4. 无历史或当前问题已完整时，is_followup=false，rewritten_query 可与原问题相同。
5. chitchat 时 rewritten_query 为空串，reply 给 1–2 句轻量回复；其它意图 reply 为空串。

【最近对话】
{% for turn in history %}{{ "用户" if turn.role == "user" else "助手" }}：{{ turn.content }}
{% endfor %}
【当前问题】{{ question }}

只输出这个 JSON：
{"intent": "note_query", "rewritten_query": "...", "is_followup": false, "reply": ""}
```

- [ ] **Step 2: 改 `scene` 参数**

`backend/app/ai/llm/base.py` 的抽象方法改为：

```python
    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> LLMResponse:
        """发送一轮对话；网络重试由实现负责，逻辑重试由调用方负责。"""
```

`backend/app/ai/llm/openai_compat.py` 的 `chat` 签名加 `scene: str = "qa"`，日志改为：

```python
                "scene": scene,
```

- [ ] **Step 3: 写 AI 层测试（先失败）**

新建 `backend/tests/test_query_rewriter.py`：

```python
"""S3-3 改写器：FakeLLM，禁止真实网络。"""
from __future__ import annotations

import json

import pytest

from app.ai.llm import LLMClient, LLMResponse
from app.ai.rag.query_rewriter import (
    HistoryTurn,
    RewriteError,
    render_prompt,
    rewrite_with_llm,
)


class FakeLLM(LLMClient):
    def __init__(self, *texts: str, error: Exception | None = None) -> None:
        super().__init__(model="fake-llm")
        self.texts = list(texts)
        self.error = error
        self.calls: list[dict] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append(
            {
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "scene": scene,
            }
        )
        if self.error is not None:
            raise self.error
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return LLMResponse(
            text=text,
            model="fake-llm",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=1,
            cost_yuan=0.00001,
        )


def _output(
    *,
    intent: str = "note_query",
    query: str = "函数单调性的前提条件是什么？",
    followup: bool = True,
    reply: str = "",
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "rewritten_query": query,
            "is_followup": followup,
            "reply": reply,
        },
        ensure_ascii=False,
    )


def test_render_prompt_includes_history_and_question() -> None:
    prompt = render_prompt(
        "那它的前提条件呢？",
        [
            HistoryTurn(role="user", content="函数单调性是什么？"),
            HistoryTurn(role="assistant", content="单调递增。"),
        ],
    )

    assert "用户：函数单调性是什么？" in prompt
    assert "助手：单调递增。" in prompt
    assert "【当前问题】那它的前提条件呢？" in prompt
    assert "只输出这个 JSON" in prompt


def test_rewrite_returns_valid_output_and_metrics() -> None:
    client = FakeLLM(_output())

    call = rewrite_with_llm(
        "那它的前提条件呢？",
        history=[HistoryTurn(role="user", content="函数单调性是什么？")],
        llm_client=client,
        max_tokens=123,
    )

    assert call.output.intent == "note_query"
    assert call.output.rewritten_query == "函数单调性的前提条件是什么？"
    assert call.output.is_followup is True
    assert call.llm_calls == 1
    assert call.total_tokens == 15
    assert client.calls[0]["scene"] == "query_rewrite"
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["max_tokens"] == 123
    assert "函数单调性是什么" in client.calls[0]["messages"][0].content


def test_rewrite_accepts_json_fence() -> None:
    client = FakeLLM("```json\n" + _output() + "\n```")

    call = rewrite_with_llm("那它的前提条件呢？", llm_client=client)

    assert call.output.intent == "note_query"


def test_rewrite_retries_invalid_json_then_succeeds() -> None:
    client = FakeLLM("not json", _output())

    call = rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=2)

    assert call.llm_calls == 2
    assert len(client.calls) == 2
    retry_messages = client.calls[1]["messages"]
    assert retry_messages[-2].role == "assistant"
    assert retry_messages[-2].content == "not json"
    assert retry_messages[-1].role == "user"
    assert "只输出一个 JSON 对象" in retry_messages[-1].content


def test_rewrite_exhausts_retries_and_raises_with_metrics() -> None:
    client = FakeLLM("not json")

    with pytest.raises(RewriteError) as exc_info:
        rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=2)

    assert len(client.calls) == 3
    assert exc_info.value.llm_calls == 3
    assert exc_info.value.total_tokens == 45
    assert "not json" not in str(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        _output(query=""),
        _output(intent="chitchat", query="", reply=""),
        _output(intent="unknown_intent"),
    ],
)
def test_rewrite_rejects_invalid_output(payload: str) -> None:
    client = FakeLLM(payload)

    with pytest.raises(RewriteError):
        rewrite_with_llm("那它的前提条件呢？", llm_client=client, max_retries=0)


def test_rewrite_without_history_keeps_question() -> None:
    client = FakeLLM(_output(query="函数的定义域怎么求？", followup=False))

    call = rewrite_with_llm("函数的定义域怎么求？", llm_client=client)

    prompt = client.calls[0]["messages"][0].content
    assert "用户：" not in prompt
    assert call.output.is_followup is False


def test_render_prompt_missing_template_raises(monkeypatch, tmp_path) -> None:
    import app.ai.rag.query_rewriter as module

    monkeypatch.setattr(module, "PROMPT_PATH", tmp_path / "missing.md")

    with pytest.raises(RewriteError):
        render_prompt("问题", [])
```

`backend/tests/test_llm.py` 末尾加：

```python
def test_llm_chat_scene_is_logged(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="app.ai.llm.openai_compat")
    client = _client(lambda request: _ok())
    client.chat([LLMMessage("user", "问题")], scene="query_rewrite")

    record = next(item for item in caplog.records if item.message == "llm_call")
    assert record.scene == "query_rewrite"
```

- [ ] **Step 4: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_query_rewriter.py backend/tests/test_llm.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.ai.rag.query_rewriter`。

- [ ] **Step 5: 实现改写器**

新建 `backend/app/ai/rag/query_rewriter.py`：

```python
"""S3-3 查询改写 LLM 层：Prompt + 严格 JSON + 最多 2 次重试。

错误信息只带类型/次数；Prompt、历史、模型输出正文一律不进异常。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rewrite_v1.md"
REWRITE_PROMPT_VERSION = "v1"

Intent = Literal["note_query", "question_query", "concept_explain", "chitchat"]

_CORRECTION = (
    "你上一次输出不是合法结果。请只输出一个 JSON 对象，字段为 "
    "intent/rewritten_query/is_followup/reply；非 chitchat 的 rewritten_query 必须非空，"
    "chitchat 的 reply 必须非空。"
)


class RewriteError(Exception):
    """改写最终失败；附带已发生的调用量，便于降级时如实记账。"""

    def __init__(
        self,
        message: str,
        *,
        llm_calls: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost_yuan: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.llm_calls = llm_calls
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cost_yuan = cost_yuan


@dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


class RewriteOutput(BaseModel):
    intent: Intent
    rewritten_query: str = Field(default="", max_length=500)
    is_followup: bool = False
    reply: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check_shape(self) -> "RewriteOutput":
        if self.intent != "chitchat" and not self.rewritten_query.strip():
            raise ValueError("非 chitchat 的 rewritten_query 不能为空")
        if self.intent == "chitchat" and not self.reply.strip():
            raise ValueError("chitchat 的 reply 不能为空")
        return self


@dataclass(frozen=True)
class RewriteCall:
    output: RewriteOutput
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int


def render_prompt(question: str, history: list[HistoryTurn]) -> str:
    if not PROMPT_PATH.is_file():
        raise RewriteError(f"Rewrite 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(history=history, question=question)
    except Exception as exc:
        raise RewriteError("Rewrite 模板渲染失败") from exc


def rewrite_with_llm(
    question: str,
    *,
    history: list[HistoryTurn] | None = None,
    llm_client: LLMClient | None = None,
    max_tokens: int = 400,
    max_retries: int = 2,
) -> RewriteCall:
    clean = question.strip()
    if not clean:
        raise ValueError("question 不能为空")
    client = llm_client or get_llm_client()
    messages = [
        LLMMessage(
            role="user",
            content=render_prompt(clean, history or []),
        )
    ]
    started = time.perf_counter()
    llm_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_yuan = 0.0
    last_error: Exception | None = None

    for _ in range(max_retries + 1):
        response = client.chat(
            messages,
            temperature=0.0,
            max_tokens=max_tokens,
            scene="query_rewrite",
        )
        llm_calls += 1
        prompt_tokens += response.prompt_tokens
        completion_tokens += response.completion_tokens
        total_tokens += response.total_tokens
        cost_yuan += response.cost_yuan
        try:
            output = RewriteOutput.model_validate(_loads_json(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages = messages + [
                LLMMessage(role="assistant", content=response.text),
                LLMMessage(role="user", content=_CORRECTION),
            ]
            continue
        return RewriteCall(
            output=output,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_yuan=cost_yuan,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    raise RewriteError(
        f"改写失败（已重试 {max_retries} 次）：{type(last_error).__name__}",
        llm_calls=llm_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_yuan=cost_yuan,
    )


def _loads_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean[3:]
        if clean[:4].lower() == "json":
            clean = clean[4:]
        if clean.endswith("```"):
            clean = clean[:-3]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(clean[start : end + 1])
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_query_rewriter.py backend/tests/test_llm.py -q`
Expected: 19 passed（test_query_rewriter 10，test_llm 9）。

再跑全套：`.\.venv\Scripts\python.exe -m pytest -q`
Expected: 597 passed, 1 warning。

- [ ] **Step 7: 提交**

```bash
git add backend/app/ai/prompts/rewrite_v1.md backend/app/ai/rag/query_rewriter.py backend/app/ai/llm/base.py backend/app/ai/llm/openai_compat.py backend/tests/test_query_rewriter.py backend/tests/test_llm.py
git commit -m "feat(s3-3): 查询改写 AI 层与意图 JSON 校验"
```

---

### Task 2: 服务层历史裁剪、缓存与降级

**Files:**
- Create: `backend/app/services/query_rewrite.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_query_rewrite_service.py`

**Interfaces:**
- Consumes: Task 1 的 `HistoryTurn`、`RewriteCall`、`RewriteError`、`rewrite_with_llm`。
- Produces: `RewriteResult`、`rewrite_query(question, *, history=None, use_cache=True, llm_client=None)`、`clear_cache()`。
- 配置：`query_rewrite_enabled`、`query_rewrite_max_history_turns`、`query_rewrite_history_content_chars`、`query_rewrite_max_tokens`、`query_rewrite_cache_ttl_seconds`、`query_rewrite_cache_size`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_query_rewrite_service.py`：

```python
"""S3-3 改写服务：fake rewriter，不触库、不调外部 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.llm.errors import LLMError
from app.ai.rag.query_rewriter import HistoryTurn, RewriteCall, RewriteError, RewriteOutput
from app.services import query_rewrite


class FakeRewriter:
    def __init__(self, call: RewriteCall | None = None, error: Exception | None = None) -> None:
        self.call = call
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, question, *, history=None, llm_client=None, max_tokens=400, max_retries=2):
        self.calls.append(
            {
                "question": question,
                "history": list(history or []),
                "max_tokens": max_tokens,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.call is not None
        return self.call


def _settings(**overrides: object) -> SimpleNamespace:
    values = {
        "query_rewrite_enabled": True,
        "query_rewrite_max_history_turns": 3,
        "query_rewrite_history_content_chars": 300,
        "query_rewrite_max_tokens": 400,
        "query_rewrite_cache_ttl_seconds": 3600,
        "query_rewrite_cache_size": 256,
        "llm_model": "qwen-plus",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _call(
    *,
    intent: str = "note_query",
    query: str = "函数单调性的前提条件是什么？",
    followup: bool = True,
    reply: str = "",
) -> RewriteCall:
    return RewriteCall(
        output=RewriteOutput(
            intent=intent,
            rewritten_query=query,
            is_followup=followup,
            reply=reply,
        ),
        llm_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_yuan=0.00001,
        latency_ms=20,
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    query_rewrite.clear_cache()
    yield
    query_rewrite.clear_cache()


@pytest.mark.parametrize("question", ["", "   "])
def test_rewrite_rejects_blank_question(monkeypatch, question: str) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    with pytest.raises(ValueError, match="question"):
        query_rewrite.rewrite_query(question)


def test_rewrite_rejects_too_long_question(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    with pytest.raises(ValueError, match="过长"):
        query_rewrite.rewrite_query("x" * 501)


def test_rewrite_keeps_only_last_three_user_turns(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)
    history = []
    for index in range(5):
        history.append(HistoryTurn(role="user", content=f"u{index}"))
        history.append(HistoryTurn(role="assistant", content=f"a{index}"))

    query_rewrite.rewrite_query("那它呢？", history=history)

    sent = fake.calls[0]["history"]
    assert [turn.content for turn in sent if turn.role == "user"] == ["u2", "u3", "u4"]
    assert len(sent) == 6


def test_rewrite_truncates_long_history_content(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query(
        "那它呢？",
        history=[HistoryTurn(role="user", content="x" * 400)],
    )

    assert len(fake.calls[0]["history"][0].content) == 300


def test_rewrite_maps_success_and_caches(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    first = query_rewrite.rewrite_query("那它呢？")
    second = query_rewrite.rewrite_query("那它呢？")

    assert first.intent == "note_query"
    assert first.rewritten_query == "函数单调性的前提条件是什么？"
    assert first.degraded is False
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.llm_calls == 0
    assert second.total_tokens == 0
    assert second.latency_ms == 0
    assert len(fake.calls) == 1


def test_rewrite_cache_expires(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)
    now = [100.0]
    monkeypatch.setattr(query_rewrite.time, "monotonic", lambda: now[0])

    query_rewrite.rewrite_query("那它呢？")
    now[0] += 3601
    second = query_rewrite.rewrite_query("那它呢？")

    assert second.cache_hit is False
    assert len(fake.calls) == 2


def test_rewrite_cache_separates_history(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query("那它呢？", history=[HistoryTurn("user", "函数")])
    query_rewrite.rewrite_query("那它呢？", history=[HistoryTurn("user", "数列")])

    assert len(fake.calls) == 2


def test_rewrite_use_cache_false_always_calls(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    query_rewrite.rewrite_query("那它呢？", use_cache=False)
    query_rewrite.rewrite_query("那它呢？", use_cache=False)

    assert len(fake.calls) == 2


def test_rewrite_llm_error_falls_back_to_original(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        query_rewrite, "rewrite_with_llm", FakeRewriter(error=LLMError("boom"))
    )

    result = query_rewrite.rewrite_query("那它呢？")

    assert result.degraded is True
    assert result.intent == "note_query"
    assert result.rewritten_query == "那它呢？"
    assert result.reply == query_rewrite.FALLBACK_REPLY
    assert result.error == "LLMError"
    assert result.llm_calls == 0


def test_rewrite_error_preserves_metrics(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    error = RewriteError(
        "bad",
        llm_calls=3,
        prompt_tokens=30,
        completion_tokens=10,
        total_tokens=40,
        cost_yuan=0.001,
    )
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", FakeRewriter(error=error))

    result = query_rewrite.rewrite_query("那它呢？")

    assert result.degraded is True
    assert result.llm_calls == 3
    assert result.total_tokens == 40
    assert result.cost_yuan == 0.001
    assert result.error == "RewriteError"


def test_rewrite_disabled_passthrough_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite,
        "get_settings",
        lambda: _settings(query_rewrite_enabled=False),
    )
    fake = FakeRewriter(call=_call())
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    result = query_rewrite.rewrite_query(
        "  那它呢？  ",
        history=[HistoryTurn("user", "函数")],
    )

    assert result.intent == "note_query"
    assert result.rewritten_query == "那它呢？"
    assert result.is_followup is True
    assert result.degraded is False
    assert result.llm_calls == 0
    assert fake.calls == []


def test_rewrite_chitchat_keeps_reply(monkeypatch) -> None:
    monkeypatch.setattr(query_rewrite, "get_settings", lambda: _settings())
    fake = FakeRewriter(
        call=_call(intent="chitchat", query="", followup=False, reply="你好，我是学习助手。")
    )
    monkeypatch.setattr(query_rewrite, "rewrite_with_llm", fake)

    result = query_rewrite.rewrite_query("你好")

    assert result.intent == "chitchat"
    assert result.reply == "你好，我是学习助手。"
    assert result.rewritten_query == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_query_rewrite_service.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.services.query_rewrite`。

- [ ] **Step 3: 加配置**

`backend/app/core/config.py` 在检索服务配置块后加：

```python
    # --- Query 改写（S3-3）---
    query_rewrite_enabled: bool = True
    query_rewrite_max_history_turns: int = 3
    query_rewrite_history_content_chars: int = 300
    query_rewrite_max_tokens: int = 400
    query_rewrite_cache_ttl_seconds: int = 3600
    query_rewrite_cache_size: int = 256
```

`.env.example` 在检索服务段后加：

```dotenv
# ===== Query 改写（S3-3）=====
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_MAX_HISTORY_TURNS=3
QUERY_REWRITE_HISTORY_CONTENT_CHARS=300
QUERY_REWRITE_MAX_TOKENS=400
QUERY_REWRITE_CACHE_TTL_SECONDS=3600
QUERY_REWRITE_CACHE_SIZE=256
```

- [ ] **Step 4: 实现 service**

新建 `backend/app/services/query_rewrite.py`：

```python
"""S3-3 查询改写服务：历史裁剪 + 进程内 LRU/TTL 缓存 + 失败降级。

LLM/Prompt/JSON 校验在 ai/rag/query_rewriter.py；本层不写 Prompt、不直接调 httpx。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace

from app.ai.llm import LLMClient
from app.ai.llm.errors import LLMError
from app.ai.rag.query_rewriter import (
    REWRITE_PROMPT_VERSION,
    HistoryTurn,
    Intent,
    RewriteError,
    rewrite_with_llm,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
FALLBACK_REPLY = "我可以帮你查笔记、找题或解释概念。"


@dataclass(frozen=True)
class RewriteResult:
    intent: Intent
    rewritten_query: str
    reply: str | None
    is_followup: bool
    degraded: bool
    cache_hit: bool
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int
    error: str | None


@dataclass(frozen=True)
class _CacheEntry:
    created_at: float
    result: RewriteResult


_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _trim_history(
    history: list[HistoryTurn],
    *,
    turns: int,
    chars: int,
) -> list[HistoryTurn]:
    if not history:
        return []
    user_positions = [index for index, turn in enumerate(history) if turn.role == "user"]
    start = user_positions[-turns] if len(user_positions) > turns else 0
    trimmed: list[HistoryTurn] = []
    for turn in history[start:]:
        content = " ".join(turn.content.split())[:chars]
        trimmed.append(HistoryTurn(role=turn.role, content=content))
    return trimmed


def _cache_key(question: str, history: list[HistoryTurn], model: str) -> str:
    parts = [REWRITE_PROMPT_VERSION, model, question]
    parts.extend(f"{turn.role}:{turn.content}" for turn in history)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _cache_get(key: str, *, ttl: int, now: float) -> RewriteResult | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        if now - entry.created_at >= ttl:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return entry.result


def _cache_put(key: str, result: RewriteResult, *, size: int, now: float) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = _CacheEntry(created_at=now, result=result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > size:
            _CACHE.popitem(last=False)


def _fallback(
    question: str,
    *,
    history: list[HistoryTurn],
    error: Exception,
    started: float,
) -> RewriteResult:
    return RewriteResult(
        intent="note_query",
        rewritten_query=question,
        reply=FALLBACK_REPLY,
        is_followup=bool(history),
        degraded=True,
        cache_hit=False,
        llm_calls=getattr(error, "llm_calls", 0),
        prompt_tokens=getattr(error, "prompt_tokens", 0),
        completion_tokens=getattr(error, "completion_tokens", 0),
        total_tokens=getattr(error, "total_tokens", 0),
        cost_yuan=getattr(error, "cost_yuan", 0.0),
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=type(error).__name__,
    )


def _log(result: RewriteResult) -> None:
    logger.info(
        "query_rewrite_done",
        extra={
            "scene": "query_rewrite",
            "intent": result.intent,
            "is_followup": result.is_followup,
            "degraded": result.degraded,
            "cache_hit": result.cache_hit,
            "llm_calls": result.llm_calls,
            "latency_ms": result.latency_ms,
            "total_tokens": result.total_tokens,
            "cost_yuan": round(result.cost_yuan, 8),
        },
    )


def rewrite_query(
    question: str,
    *,
    history: list[HistoryTurn] | None = None,
    use_cache: bool = True,
    llm_client: LLMClient | None = None,
) -> RewriteResult:
    started = time.perf_counter()
    clean = question.strip()
    if not clean:
        raise ValueError("question 不能为空")
    if len(clean) > MAX_QUESTION_CHARS:
        raise ValueError(f"question 过长（最多 {MAX_QUESTION_CHARS} 字）")

    settings = get_settings()
    trimmed = _trim_history(
        history or [],
        turns=settings.query_rewrite_max_history_turns,
        chars=settings.query_rewrite_history_content_chars,
    )

    if not settings.query_rewrite_enabled:
        result = RewriteResult(
            intent="note_query",
            rewritten_query=clean,
            reply=None,
            is_followup=bool(trimmed),
            degraded=False,
            cache_hit=False,
            llm_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_yuan=0.0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=None,
        )
        _log(result)
        return result

    key = _cache_key(clean, trimmed, settings.llm_model)
    if use_cache:
        cached = _cache_get(
            key,
            ttl=settings.query_rewrite_cache_ttl_seconds,
            now=time.monotonic(),
        )
        if cached is not None:
            result = replace(
                cached,
                cache_hit=True,
                llm_calls=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_yuan=0.0,
                latency_ms=0,
            )
            _log(result)
            return result

    try:
        call = rewrite_with_llm(
            clean,
            history=trimmed,
            llm_client=llm_client,
            max_tokens=settings.query_rewrite_max_tokens,
        )
        result = RewriteResult(
            intent=call.output.intent,
            rewritten_query=call.output.rewritten_query.strip(),
            reply=call.output.reply.strip() or None,
            is_followup=call.output.is_followup,
            degraded=False,
            cache_hit=False,
            llm_calls=call.llm_calls,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            total_tokens=call.total_tokens,
            cost_yuan=call.cost_yuan,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=None,
        )
    except (LLMError, RewriteError) as exc:
        result = _fallback(clean, history=trimmed, error=exc, started=started)
    else:
        if use_cache:
            _cache_put(
                key,
                result,
                size=settings.query_rewrite_cache_size,
                now=time.monotonic(),
            )

    _log(result)
    return result
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_query_rewrite_service.py -q`
Expected: 13 passed（空问题参数化 2 + 其余 11）。

再跑全套：`.\.venv\Scripts\python.exe -m pytest -q`
Expected: 610 passed, 1 warning。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/query_rewrite.py backend/app/core/config.py .env.example backend/tests/test_query_rewrite_service.py
git commit -m "feat(s3-3): 改写服务的历史裁剪、缓存与降级"
```

---

### Task 3: 真实改写验收脚本

**Files:**
- Create: `scripts/rewrite_eval.py`

**Interfaces:**
- Consumes: Task 2 `rewrite_query`、`HistoryTurn`；S3-2 `retrieval_service.search_chunks`。
- Produces: 终端逐条 `intent / rewritten_query / top3 / hit` 与 hit@3 汇总；供 Task 4 验收。

- [ ] **Step 1: 写脚本**

`scripts/rewrite_eval.py`：

```python
"""S3-3 真实改写验收：10 条指代追问 → 改写 → S3-2 检索 top3 → 期望关键词命中。

用法（仓库根目录，需真实 .env 与已入库笔记）：
    python scripts/rewrite_eval.py --user-id 1 --top-k 3

判定：top3 任一命中内容包含该条期望关键词记为命中；目标 hit@3 ≥ 8/10。
结果不理想时不要改问题或关键词粉饰。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.services.query_rewrite import HistoryTurn, rewrite_query  # noqa: E402
from app.services.retrieval_service import search_chunks  # noqa: E402

# (上一轮用户问题, 当前指代追问, 期望关键词)；期望关键词沿用 S1-5 固定问题集
CASES: list[tuple[str, str, list[str]]] = [
    ("函数的定义域怎么求？", "再详细解释一下，具体怎么做？", ["定义域"]),
    ("函数单调性的定义是什么？", "那它的前提条件呢？", ["单调性"]),
    ("如何用定义证明函数在区间上单调递增？", "再详细说一下这个证明。", ["单调递增", "增函数"]),
    ("奇函数和偶函数有什么性质？", "那它的图象有什么特点？", ["奇函数", "偶函数"]),
    ("二次函数在闭区间上的最值怎么求？", "再详细解释一下。", ["最大值", "最小值"]),
    ("分段函数 f(f(-1)) 怎么求？", "那它的步骤呢？", ["f(f(-1))"]),
    ("函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？", "再详细说一下。", ["单调递增", "单调性"]),
    ("已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？", "那它的依据是什么？", ["解析式"]),
    ("函数图象关于原点对称说明什么？", "再详细解释一下。", ["原点", "奇函数"]),
    ("商品定价最大利润问题怎么建模？", "那它的步骤呢？", ["利润"]),
]

def _configure_stdio() -> None:
    """Windows 控制台默认 GBK；中文输出统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _snippet(text: str, limit: int = 70) -> str:
    return " ".join(text.split())[:limit]


def _contains(hits: list, keywords: list[str]) -> bool:
    return any(
        keyword.lower() in hit.content.lower()
        for hit in hits
        for keyword in keywords
    )


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S3-3 指代追问改写 + 检索 hit@3 验收")
    parser.add_argument("--user-id", type=int, default=1, help="用户 ID（默认 1）")
    parser.add_argument("--top-k", type=int, default=3, help="检索返回条数（默认 3）")
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k 必须为正整数")

    set_trace_id("rewrite-eval-" + uuid.uuid4().hex[:12])
    hits_total = 0
    degraded = 0
    total_tokens = 0
    total_cost = 0.0

    with new_session() as session:
        for index, (previous, followup, keywords) in enumerate(CASES, start=1):
            history = [
                HistoryTurn(role="user", content=previous),
                HistoryTurn(role="assistant", content="上一轮已解释相关概念。"),
            ]
            result = rewrite_query(followup, history=history, use_cache=False)
            total_tokens += result.total_tokens
            total_cost += result.cost_yuan
            degraded += 1 if result.degraded else 0

            print(
                f"\n[{index:02d}] {followup}\n"
                f"  上一轮: {previous}\n"
                f"  intent={result.intent} followup={result.is_followup} "
                f"degraded={result.degraded} cache={result.cache_hit}\n"
                f"  rewritten: {result.rewritten_query}"
            )

            if result.intent == "chitchat":
                print("  （闲聊，不检索）")
                continue

            response = search_chunks(
                session,
                user_id=args.user_id,
                query=result.rewritten_query or followup,
                top_k=args.top_k,
                rerank=False,
            )
            hit = _contains(response.hits, keywords)
            hits_total += 1 if hit else 0
            print(f"  hits={len(response.hits)} expected={keywords} hit={hit}")
            for rank, item in enumerate(response.hits, start=1):
                print(
                    f"    {rank}. note={item.note_id} chunk={item.chunk_index} "
                    f"type={item.chunk_type} {_snippet(item.content)}"
                )

        chitchat = rewrite_query("你好", use_cache=False)
        standalone = rewrite_query("函数的定义域怎么求？", use_cache=False)
        total_tokens += chitchat.total_tokens + standalone.total_tokens
        total_cost += chitchat.cost_yuan + standalone.cost_yuan
        print(
            f"\n[chitchat] intent={chitchat.intent} reply={chitchat.reply!r} "
            f"degraded={chitchat.degraded}"
        )
        print(
            f"[standalone] intent={standalone.intent} "
            f"followup={standalone.is_followup} rewritten={standalone.rewritten_query!r}"
        )

    print("\n" + "=" * 78)
    print(f"汇总：hit@3={hits_total}/{len(CASES)}  degraded={degraded}/{len(CASES)}")
    print(f"tokens={total_tokens}  cost=¥{total_cost:.6f}")
    checks_ok = (
        hits_total >= 8
        and chitchat.intent == "chitchat"
        and bool(chitchat.reply)
        and standalone.is_followup is False
    )
    print(f"目标 hit@3 ≥ 8/10 且闲聊/独立问题检查通过：{'PASS' if checks_ok else 'FAIL'}")
    return 0 if checks_ok else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 语法与帮助自检**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/rewrite_eval.py --help`
Expected: 打印 `--user-id/--top-k`，退出 0。

Run: `.\.venv\Scripts\python.exe -m py_compile scripts/rewrite_eval.py`
Expected: 退出 0。

- [ ] **Step 3: 提交**

```bash
git add scripts/rewrite_eval.py
git commit -m "feat(s3-3): 指代追问改写验收脚本"
```

---

### Task 4: 真实运行、验收与文档同步

**Files:**
- Modify: `docs/DECISIONS.md`、`docs/PROGRESS.md`、`AGENTS.md`、`docs/AI协作开发实施计划.md`
- Modify: `docs/spec/s3-3-query-rewrite.md`（测试数、实测结果、偏移）
- Modify: `docs/plan/s3-3-query-rewrite.md`（Execution Record）
- 不改：`docs/API.md`、`docs/SCHEMA.md`（无新接口/表）

- [ ] **Step 1: 跑全套测试**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`
Expected: 610 passed, 1 warning。

- [ ] **Step 2: 真实跑改写验收**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/rewrite_eval.py --user-id 18 --top-k 3`

记录：
- 每条 `intent / is_followup / rewritten_query / top3 / hit`；
- 汇总 `hit@3`、`degraded`、tokens、cost、PASS/FAIL；
- 闲聊条 `intent=chitchat` 且 `reply` 非空；
- 独立问题 `is_followup=false`。

若 FAIL：原样记录每条失败原因（改写偏移、检索未命中、意图误判），**不调关键词、不改样本**；必要时另开卡修 Prompt，不在本轮粉饰。

- [ ] **Step 3: 文档同步**

- `docs/DECISIONS.md` 追加 **D-037**：分层、4 类意图语义、history 契约、缓存策略（进程内 LRU/TTL，S3-7 换 Redis）、失败降级、实测 hit@3/成本、已知限制。
- `docs/PROGRESS.md`：状态改「S3-3 完成」、阶段 3 勾选 S3-3、下一步 S3-4、变更日志加 S3-3（含测试数、实测 hit@3、tokens/cost、降级次数）；遗留问题加：意图误判、缓存不跨进程、历史截断、失败 token 无法记账。
- `AGENTS.md` §9.2 加 Query 改写约束；§9.6 加「查询改写样例」锚点。
- `docs/AI协作开发实施计划.md` 第 14 章勾选 S3-3。
- `docs/spec/s3-3-query-rewrite.md`：§8 实测测试数、§9 实测结果、补 §11 实施记录。
- `docs/plan/s3-3-query-rewrite.md`：填 Execution Record（提交号、测试数、脚本输出、偏移）。

- [ ] **Step 4: 提交**

```bash
git add docs/DECISIONS.md docs/PROGRESS.md AGENTS.md docs/AI协作开发实施计划.md docs/spec/s3-3-query-rewrite.md docs/plan/s3-3-query-rewrite.md
git commit -m "docs(s3-3): 查询改写验收记录与文档同步"
```

---

## Self-Review

- **Spec coverage**：分层/接口 §4 → Task 1/2；Prompt/JSON/重试 §5 → Task 1；历史裁剪/缓存/降级/开关 §6 → Task 2；配置 §7 → Task 2；测试 §8 → Task 1/2；验收 §9 → Task 3/4；已知限制 §10 → Task 4 文档。
- **类型一致性**：`HistoryTurn` 定义在 `ai/rag/query_rewriter.py`，service 直接复用；`RewriteCall`/`RewriteError` 字段在 Task 1 定义、Task 2 使用；`rewrite_with_llm` 的 `max_tokens/max_retries` 与 service 调用一致；`RewriteResult` 字段与测试断言一致。
- **占位扫描**：无 TODO/TBD；“类似 Task N”未使用；重复测试已写全。
- **风险**：真实 hit@3 可能低于 8/10；Task 4 要求原样记录，不改样本/阈值。进程缓存不跨 worker，已在 spec/文档标注为 S3-7 迁移项。

---

## Execution Record

**状态：完成（2026-10-31）**

| 任务 | 提交 | 验证 |
|---|---|---|
| Task 1 AI 层 | `371f33e` | `test_query_rewriter.py` 10 + `test_llm.py` 9 = 19 passed；全量 597 |
| Task 2 service | `8c6db4e` | `test_query_rewrite_service.py` 13 passed；全量 **610 passed, 1 warning** |
| Task 3 脚本 | `9f7d47b` | `--help` 退出 0；`py_compile` 退出 0 |
| Task 4 验收/文档 | 文档提交 | 脚本 PASS；文档同步完成 |

**真实验收命令**

```bash
cd study-agent
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/rewrite_eval.py --user-id 18 --top-k 3
```

**结果**：hit@3 **9/10**、degraded **0/10**、tokens **3958**、cost **¥0.003802**、PASS；闲聊 `intent=chitchat` 且 reply 非空；独立问题 `is_followup=false`。10 条均 `intent=concept_explain`。

| # | 追问 | 改写（摘要） | hit |
|---|---|---|---|
| 1 | 再详细解释一下，具体怎么做？ | 函数定义域求法 + 常见类型步骤 | ✓ |
| 2 | 那它的前提条件呢？ | 函数单调性定义的前提条件 | ✓ |
| 3 | 再详细说一下这个证明。 | 定义证明区间单调递增的步骤/要点 | ✓ |
| 4 | 那它的图象有什么特点？ | 奇函数/偶函数图象特点 | ✓ |
| 5 | 再详细解释一下。 | 二次函数闭区间最值分类讨论 | ✓ |
| 6 | 那它的步骤呢？ | 分段函数 `f(f(-1))` 求解步骤 | ✗ |
| 7 | 再详细说一下。 | `f(x)=x+1/x` 在 `(1,+∞)` 单调性证明 | ✓ |
| 8 | 那它的依据是什么？ | 奇函数半区间解析式求另一侧的依据 | ✓ |
| 9 | 再详细解释一下。 | 图象关于原点对称的定义/充要条件/判断 | ✓ |
| 10 | 那它的步骤呢？ | 商品定价最大利润建模步骤 | ✓ |

**偏移与说明**

- 验收账号实际为 `test1` id=18（脚本默认仍 1）；未改样本或关键词。
- 第 6 条改写正确，但 top3 未召回目标块 `note 77/chunk 11`（块存在），属检索召回问题；按约定不粉饰。
- 文档：DECISIONS D-037、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-3、spec §9/§11；未改 API.md/SCHEMA.md/前端。