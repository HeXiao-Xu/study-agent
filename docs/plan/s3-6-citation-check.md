# S3-6 拒答与引用校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在生成后检测越界引用与无引用知识陈述，最多重试一次；仍不合格时按情况拒答或给未引用块加模型补充声明，并通过 SSE `done` 返回结构化拒答建议。

**Architecture:** 新增纯函数 `services/citation_checker.py`；`qa_service` 静默消费完整回答、校验、必要时重试，再按块发 `delta`；`done` 增加 `refusal_reason/suggestions`；只改 SSE 链路，`answer_question` 保持不变。无新表、迁移、依赖。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2.0、pytest、现有 OpenAI 兼容 LLM 适配器。

**Spec:** `docs/spec/s3-6-citation-check.md`

## Global Constraints

- 不新增依赖、表、迁移、配置项。
- 外部 LLM/DB 在单元测试中全部 mock；真实调用只放验收。
- 固定前缀必须逐字为 `【以下为模型补充，未在你的资料中找到依据】`。
- 只给未引用块加前缀，不得给整篇已引用回答误加。
- 第二轮仍无任何合法引用才拒答；有合法引用时保留回答并去越界编号。
- `answer_question` / `scripts/ask.py` 不改行为。
- 所有数字来自实跑；`git push` 由用户执行。
- 项目测试命令：`cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/services/citation_checker.py` | 新建 | 分块、引用校验、去越界编号、加声明、纠错消息 |
| `backend/tests/test_citation_checker.py` | 新建 | checker 纯函数 12 条 |
| `backend/app/ai/rag/answerer.py` | 修改 | `stream_answer` 接受可选 `messages` 供重试 |
| `backend/tests/test_answerer.py` | 修改 | 重试消息 1 条 |
| `backend/app/services/qa_service.py` | 修改 | 聚合 usage、校验/重试/标注、done 新字段、cancel_event |
| `backend/app/api/v1/qa.py` | 修改 | SSE 路由创建/置位 cancel_event，断连关闭上游 |
| `backend/tests/test_qa_service.py` | 修改 | SSE 集成 7 条 + 既有用例适配 |
| `backend/app/schemas/qa.py` | 修改 | `QaSuggestion` 与 `QaDoneData` 新字段 |
| `backend/tests/test_qa_api.py` | 修改 | done 契约 2 条 |
| `scripts/citation_eval.py` | 新建 | 真实 5+5 验收脚本 |
| `docs/API.md`、`docs/PROGRESS.md`、`docs/DECISIONS.md`、任务卡 | 修改 | 契约/进度/决策/勾选 |

---

### Task 1: `citation_checker` 纯函数

**Files:**
- Create: `backend/app/services/citation_checker.py`
- Test: `backend/tests/test_citation_checker.py`

**Interfaces:**
- Produces:
  - `SUPPLEMENT_PREFIX: str`
  - `CitationCheck(context_size:int, valid_indices:list[int], invalid_indices:list[int], uncited_blocks:list[str], has_content:bool)`
  - `split_blocks(answer: str) -> list[str]`
  - `check_answer(answer: str, *, context_size: int) -> CitationCheck`
  - `strip_invalid_citations(answer: str, *, context_size: int) -> str`
  - `annotate_uncited(answer: str, *, context_size: int) -> str`
  - `build_correction(check: CitationCheck) -> str`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_citation_checker.py`：

```python
"""S3-6 引用检查器：纯函数，不连库/不调外部。"""
from __future__ import annotations

import pytest

from app.services.citation_checker import (
    SUPPLEMENT_PREFIX,
    annotate_uncited,
    build_correction,
    check_answer,
    split_blocks,
    strip_invalid_citations,
)


def test_split_blocks_keeps_paragraphs_headings_and_lists() -> None:
    answer = "第一段[1]。\n\n## 标题\n- 列表一[2]\n- 列表二"

    assert split_blocks(answer) == [
        "第一段[1]。",
        "## 标题",
        "- 列表一[2]",
        "- 列表二",
    ]


def test_check_skips_heading_code_and_math() -> None:
    answer = (
        "# 标题\n\n"
        "```python\n[99]\n```\n\n"
        "$$ E = mc^2 $$\n\n"
        "这是需要引用的知识陈述内容。"
    )
    check = check_answer(answer, context_size=3)

    assert check.valid_indices == []
    assert check.invalid_indices == []
    assert check.uncited_blocks == ["这是需要引用的知识陈述内容。"]
    assert check.has_content is True


def test_check_records_valid_and_invalid_indices() -> None:
    check = check_answer("结论[1]，错误引用[9]。", context_size=2)

    assert check.valid_indices == [1]
    assert check.invalid_indices == [9]
    assert check.uncited_blocks == []
    assert check.has_content is True
    assert check.needs_retry is True


def test_check_marks_only_uncited_blocks() -> None:
    answer = "已引用[1]的内容。\n\n没有引用的知识陈述内容。"
    check = check_answer(answer, context_size=2)

    assert check.valid_indices == [1]
    assert check.uncited_blocks == ["没有引用的知识陈述内容。"]
    assert check.needs_retry is True


def test_check_no_citations_is_not_clean() -> None:
    check = check_answer("这是没有任何引用的知识陈述内容。", context_size=2)

    assert check.valid_indices == []
    assert check.uncited_blocks == ["这是没有任何引用的知识陈述内容。"]
    assert check.has_valid_citation is False
    assert check.needs_retry is True


def test_check_empty_answer_has_no_content() -> None:
    check = check_answer("", context_size=2)

    assert check.has_content is False
    assert check.needs_retry is True


def test_check_rejects_nonpositive_context() -> None:
    with pytest.raises(ValueError):
        check_answer("回答", context_size=0)


def test_strip_invalid_citations_keeps_valid() -> None:
    assert strip_invalid_citations("答[1]和[9]", context_size=2) == "答[1]和"


def test_annotate_only_uncited_block() -> None:
    answer = "已引用[1]。\n\n无引用块。"
    annotated = annotate_uncited(answer, context_size=2)

    assert annotated == f"已引用[1]。\n\n{SUPPLEMENT_PREFIX}\n无引用块。"


def test_annotate_skips_existing_prefix() -> None:
    answer = f"{SUPPLEMENT_PREFIX}\n补充内容"
    assert annotate_uncited(answer, context_size=2) == answer


def test_annotate_does_not_touch_code_block() -> None:
    answer = "正文需要引用[1]。\n\n```python\nprint(1)\n```"
    annotated = annotate_uncited(answer, context_size=2)

    assert annotated == answer
    assert annotated.count(SUPPLEMENT_PREFIX) == 0


def test_build_correction_contains_range_and_prefix() -> None:
    check = check_answer("没有引用的知识陈述内容。", context_size=3)
    correction = build_correction(check)

    assert "[1]..[3]" in correction
    assert SUPPLEMENT_PREFIX in correction
    assert "不要解释校验过程" in correction
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_citation_checker.py -q`

Expected: collection error，`No module named 'app.services.citation_checker'`。

- [ ] **Step 3: 实现 checker**

`backend/app/services/citation_checker.py`：

```python
"""S3-6 引用校验：分块、越界编号、未引用块与补充声明。

本模块只做纯文本判断，不连库、不调 LLM；重试由 qa_service 编排。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

CITATION_RE = re.compile(r"\[(\d+)\]")
SUPPLEMENT_PREFIX = "【以下为模型补充，未在你的资料中找到依据】"
LEGACY_SUPPLEMENT_PREFIX = "【补充说明｜非你的资料】"

_HEADING_RE = re.compile(r"^#{1,6}\s")
_LIST_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_FENCE_RE = re.compile(r"^(?:```|~~~)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_MATH_TOKENS = ("$", "\\", "=", "^", "_", "{")
_REFUSAL_MARKERS = ("在你的笔记中没找到相关内容",)
_SEPARATORS = {"---", "***", "___"}


@dataclass(frozen=True)
class CitationCheck:
    context_size: int
    valid_indices: list[int]
    invalid_indices: list[int]
    uncited_blocks: list[str]
    has_content: bool

    @property
    def has_valid_citation(self) -> bool:
        return bool(self.valid_indices)

    @property
    def needs_retry(self) -> bool:
        return bool(
            self.invalid_indices
            or self.uncited_blocks
            or not self.valid_indices
        )

    @property
    def is_clean(self) -> bool:
        return not self.needs_retry


def _normalize(answer: str) -> str:
    return answer.replace("\r\n", "\n").replace("\r", "\n")


def split_blocks(answer: str) -> list[str]:
    """按空行/标题/列表项切块，保留代码围栏整块。"""
    lines = _normalize(answer).split("\n")
    blocks: list[str] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        raw = "\n".join(buffer).strip("\n")
        if raw.strip():
            blocks.append(raw)
        buffer.clear()

    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            if in_fence:
                buffer.append(line)
                flush()
                in_fence = False
            else:
                flush()
                buffer.append(line)
                in_fence = True
            continue
        if in_fence:
            buffer.append(line)
            continue
        if not stripped:
            flush()
            continue
        if (
            _HEADING_RE.match(stripped)
            or _LIST_RE.match(stripped)
            or stripped.startswith(">")
        ):
            flush()
            buffer.append(line)
            continue
        buffer.append(line)

    flush()
    return blocks


def _has_supplement_marker(block: str) -> bool:
    stripped = block.strip()
    if stripped.startswith(">"):
        stripped = stripped.lstrip(">").strip()
    return stripped.startswith(
        (SUPPLEMENT_PREFIX, LEGACY_SUPPLEMENT_PREFIX)
    )


def _is_math_only(block: str) -> bool:
    stripped = block.strip()
    if not stripped or _CJK_RE.search(stripped):
        return False
    if not any(token in stripped for token in _MATH_TOKENS):
        return False
    compact = re.sub(r"\s+", "", stripped)
    if len(compact) < 12:
        return False
    math_chars = set(
        "$\\{}_^=+-*/()[]|.,;:0123456789"
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )
    hits = sum(char in math_chars for char in compact)
    return hits / len(compact) >= 0.9


def _is_skipped(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return True
    if _FENCE_RE.match(stripped) or _HEADING_RE.match(stripped):
        return True
    if _has_supplement_marker(block):
        return True
    if any(marker in stripped for marker in _REFUSAL_MARKERS):
        return True
    if stripped in _SEPARATORS:
        return True
    return _is_math_only(stripped)


def _is_substantive(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return False
    if _CJK_RE.search(stripped):
        return True
    return len(re.sub(r"\s+", "", stripped)) >= 20


def _indices(block: str) -> list[int]:
    return [int(match.group(1)) for match in CITATION_RE.finditer(block)]


def check_answer(answer: str, *, context_size: int) -> CitationCheck:
    if context_size < 1:
        raise ValueError("context_size 必须 >= 1")

    valid: set[int] = set()
    invalid: set[int] = set()
    uncited: list[str] = []
    has_content = False

    for block in split_blocks(answer):
        if _is_skipped(block):
            continue
        numbers = _indices(block)
        block_valid = [n for n in numbers if 1 <= n <= context_size]
        block_invalid = [n for n in numbers if not 1 <= n <= context_size]
        valid.update(block_valid)
        invalid.update(block_invalid)
        if not _is_substantive(block):
            continue
        has_content = True
        if not block_valid:
            uncited.append(block)

    return CitationCheck(
        context_size=context_size,
        valid_indices=sorted(valid),
        invalid_indices=sorted(invalid),
        uncited_blocks=uncited,
        has_content=has_content,
    )


def strip_invalid_citations(answer: str, *, context_size: int) -> str:
    text = _normalize(answer)

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return match.group(0) if 1 <= number <= context_size else ""

    return CITATION_RE.sub(replace, text)


```python
def _map_blocks(answer: str, transform: Callable[[str], str]) -> str:
    blocks = split_blocks(answer)
    if not blocks:
        return answer
    out: list[str] = []
    cursor = 0
    for block in blocks:
        start = answer.find(block, cursor)
        if start < 0:
            return transform(answer)
        out.append(answer[cursor:start])
        out.append(transform(block))
        cursor = start + len(block)
    out.append(answer[cursor:])
    return "".join(out)


def annotate_uncited(answer: str, *, context_size: int) -> str:
    text = _normalize(answer)
    check = check_answer(text, context_size=context_size)
    if not check.uncited_blocks:
        return text
    uncited = set(check.uncited_blocks)

    def transform(block: str) -> str:
        if block in uncited and not _has_supplement_marker(block):
            return f"{SUPPLEMENT_PREFIX}\n{block}"
        return block

    return _map_blocks(text, transform)


def build_correction(check: CitationCheck) -> str:
    details: list[str] = []
    if not check.valid_indices:
        details.append("整篇没有合法引用")
    if check.uncited_blocks:
        details.append(f"{len(check.uncited_blocks)} 个实质块没有合法引用")
    if check.invalid_indices:
        joined = "、".join(f"[{n}]" for n in check.invalid_indices[:5])
        details.append(f"存在越界编号 {joined}")
    return (
        "上一次回答未通过引用校验："
        + "；".join(details)
        + f"。本轮只能使用 [1]..[{check.context_size}] 中的编号；"
        "每个知识陈述后必须标注引用；资料不足的补充内容另起一段，"
        f"并以“{SUPPLEMENT_PREFIX}”开头；不要解释校验过程。"
    )
```

- [ ] **Step 4: 跑 checker 与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_citation_checker.py -q`

Expected: `12 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: `678 passed, 1 warning`（666+12）。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/citation_checker.py backend/tests/test_citation_checker.py
git commit -m "feat(s3-6): 引用检查器与块级补充声明"
```

---

### Task 2: `stream_answer` 支持重试消息

**Files:**
- Modify: `backend/app/ai/rag/answerer.py:270-288`
- Test: `backend/tests/test_answerer.py`（追加）

**Interfaces:**
- Consumes: 现有 `FakeStreamLLM`、`PreparedAnswer`。
- Produces: `stream_answer(prepared, *, llm_client=None, messages: list[LLMMessage] | None = None)`；`messages` 缺省仍用 `[LLMMessage("user", prepared.prompt)]`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_answerer.py` 末尾追加：

```python
def test_stream_answer_accepts_retry_messages() -> None:
    prepared = PreparedAnswer(
        retrieval=_retrieval([_chunk()]),
        built=None,
        prompt="原始 prompt",
        refused=None,
        retrieval_ms=1,
        top_score=0.9,
        degraded=False,
    )
    fake = FakeStreamLLM(["答[1]"])
    retry = [LLMMessage(role="user", content="重试 prompt")]

    chunks = list(stream_answer(prepared, llm_client=fake, messages=retry))

    assert "".join(chunk.text for chunk in chunks) == "答[1]"
    assert fake.calls[0] == retry
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_answerer.py::test_stream_answer_accepts_retry_messages -q`

Expected: `TypeError: stream_answer() got an unexpected keyword argument 'messages'`。

- [ ] **Step 3: 实现可选 messages**

把 `stream_answer` 改为：

```python
def stream_answer(
    prepared: PreparedAnswer,
    *,
    llm_client: LLMClient | None = None,
    messages: list[LLMMessage] | None = None,
) -> Iterator[AnswerChunk]:
    if prepared.refused is not None:
        return
    client = llm_client if llm_client is not None else get_llm_client()
    request_messages = messages or [
        LLMMessage(role="user", content=prepared.prompt)
    ]
    for chunk in client.chat_stream(
        request_messages,
        temperature=get_settings().llm_temperature,
        max_tokens=get_settings().llm_max_output_tokens,
        scene="qa",
    ):
        if chunk.response is not None:
            yield AnswerChunk(response=chunk.response)
        elif chunk.text:
            yield AnswerChunk(text=chunk.text)
```

- [ ] **Step 4: 跑 answerer 与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_answerer.py -q`

Expected: `20 passed`（现有 19 +1）。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: `679 passed, 1 warning`。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/ai/rag/answerer.py backend/tests/test_answerer.py
git commit -m "feat(s3-6): stream_answer 支持重试消息"
```

---

### Task 3: `qa_service` 校验、重试、标注与聚合

**Files:**
- Modify: `backend/app/services/qa_service.py`
- Modify: `backend/app/api/v1/qa.py`
- Test: `backend/tests/test_qa_service.py`

**Interfaces:**
- Consumes: `citation_checker` 的 `check_answer/strip_invalid_citations/annotate_uncited/build_correction`；`stream_answer(..., messages=...)`。
- Produces:
  - `QaSuggestion(type: Literal["rephrase","note"], text: str, note_id: int | None = None)`
  - `stream_events(..., cancel_event: threading.Event | None = None)`，`done.data` 含 `refusal_reason`、`suggestions`。
  - `_usage_payload(responses: list[LLMResponse])` 聚合；`_persist_assistant(..., responses: list[LLMResponse])`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_qa_service.py` 追加（同时把既有 `stream_events` 用例的 `_persist_assistant` 语义适配为新签名；若只调公共接口则无需改）：

既有两条断言必须同步改，否则会把新行为误判为回归：

```python
# test_stream_events_rag_persists_assistant_and_citations
# S3-6 起整段校验后一次/按块发 delta，"答"+"[1]" 合并为一个 delta
assert [event.event for event in events] == ["meta", "delta", "done"]
```

```python
# test_stream_events_disconnect_does_not_persist_assistant
# S3-6 起校验前不向客户端发 delta，断连时只有 meta
assert next(generator).event == "meta"
with pytest.raises(StopIteration):
    next(generator)
assert closed == [True]
```

新用例：

```python
import threading

from app.services.citation_checker import SUPPLEMENT_PREFIX


def _response(text: str, total: int = 10) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="qwen-plus",
        prompt_tokens=total - 2,
        completion_tokens=2,
        total_tokens=total,
        latency_ms=1,
        cost_yuan=0.0001,
    )


def test_stream_events_clean_answer_does_not_retry(monkeypatch) -> None:
    calls: list[list[object]] = []

    def fake_stream(prepared, *, llm_client=None, messages=None):
        calls.append(list(messages or []))
        yield AnswerChunk(text="答[1]")
        yield AnswerChunk(response=_response("答[1]"))

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(), session_factory=lambda: final_session
        )
    )

    assert len(calls) == 1
    assert events[-1].data["refused"] is False
    assert events[-1].data["refusal_reason"] is None
    assert events[-1].data["suggestions"] == []
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == "答[1]"
    assert SUPPLEMENT_PREFIX not in assistant.content_md


def test_stream_events_no_citation_retries_then_refuses(monkeypatch) -> None:
    calls = 0

    def fake_stream(prepared, *, llm_client=None, messages=None):
        nonlocal calls
        calls += 1
        text = "第一版无引用内容。" if calls == 1 else "第二版仍无引用。"
        yield AnswerChunk(text=text)
        yield AnswerChunk(response=_response(text, total=20 + calls))

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(), session_factory=lambda: final_session
        )
    )

    assert calls == 2
    assert events[-1].data["refused"] is True
    assert events[-1].data["refusal_reason"] == "no_valid_citation"
    assert len(events[-1].data["suggestions"]) == 2
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert assistant.content_md == REFUSAL_TEXT
    assert assistant.token_usage["total_tokens"] == 43


def test_stream_events_partial_retry_annotates_uncited_block(monkeypatch) -> None:
    calls = 0

    def fake_stream(prepared, *, llm_client=None, messages=None):
        nonlocal calls
        calls += 1
        text = "已引用[1]。\n\n没有引用的补充内容。"
        yield AnswerChunk(text=text)
        yield AnswerChunk(response=_response(text))

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(), session_factory=lambda: final_session
        )
    )

    assert calls == 2
    assert events[-1].data["refused"] is False
    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert SUPPLEMENT_PREFIX in assistant.content_md
    assert "没有引用的补充内容。" in assistant.content_md
    deltas = "".join(
        str(item.data["text"])
        for item in events
        if item.event == "delta"
    )
    assert deltas == assistant.content_md
    assert events[-1].data["suggestions"] == []


def test_stream_events_strips_invalid_citation_after_retry(monkeypatch) -> None:
    def fake_stream(prepared, *, llm_client=None, messages=None):
        text = "有效[1]，越界[9]。"
        yield AnswerChunk(text=text)
        yield AnswerChunk(response=_response(text))

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(), session_factory=lambda: final_session
        )
    )

    assistant = next(
        item for item in final_session.added if isinstance(item, Message)
    )
    assert "[9]" not in assistant.content_md
    assert "[1]" in assistant.content_md
    citations = [
        item for item in final_session.added if isinstance(item, MessageCitation)
    ]
    assert [row.rank for row in citations] == [1]
    assert events[-1].data["refused"] is False


def test_stream_events_cancel_event_does_not_persist(monkeypatch) -> None:
    cancel = threading.Event()

    def fake_stream(prepared, *, llm_client=None, messages=None):
        yield AnswerChunk(text="第一段")
        cancel.set()
        yield AnswerChunk(text="第二段")

    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    final_session = FakeAssistantSession()
    events = list(
        qa_service.stream_events(
            _plan(),
            session_factory=lambda: final_session,
            cancel_event=cancel,
        )
    )

    assert [event.event for event in events] == ["meta"]
    assert not any(isinstance(item, Message) for item in final_session.added)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`

Expected: 新用例因 `cancel_event` 不存在、无重试/前缀/新 done 字段而失败。

- [ ] **Step 3: 实现聚合与 checker 集成**

在 `qa_service.py` 顶部 import 加：

```python
import re
import threading

from app.ai.llm import LLMClient, LLMMessage, LLMResponse
from app.services.citation_checker import (
    SUPPLEMENT_PREFIX,
    annotate_uncited,
    build_correction,
    check_answer,
    strip_invalid_citations,
)
```

`QaSuggestion`：

```python
@dataclass(frozen=True)
class QaSuggestion:
    type: Literal["rephrase", "note"]
    text: str
    note_id: int | None = None
```

用以下版本替换 `_usage_payload` / `_token_usage` / `_total_tokens` / `_persist_assistant` / `_done_data`：

```python
def _usage_payload(responses: list[LLMResponse]) -> dict[str, object]:
    return {
        "prompt_tokens": sum(r.prompt_tokens for r in responses),
        "completion_tokens": sum(r.completion_tokens for r in responses),
        "total_tokens": sum(r.total_tokens for r in responses),
        "cost_yuan": sum(r.cost_yuan for r in responses),
    }


def _token_usage(
    responses: list[LLMResponse], rewrite: RewriteResult | None
) -> dict[str, object]:
    payload = _usage_payload(responses)
    payload["rewrite"] = (
        {
            "prompt_tokens": rewrite.prompt_tokens,
            "completion_tokens": rewrite.completion_tokens,
            "total_tokens": rewrite.total_tokens,
            "cost_yuan": rewrite.cost_yuan,
            "degraded": rewrite.degraded,
            "cache_hit": rewrite.cache_hit,
        }
        if rewrite is not None
        else None
    )
    return payload


def _total_tokens(
    responses: list[LLMResponse], rewrite: RewriteResult | None
) -> int:
    return sum(r.total_tokens for r in responses) + (
        rewrite.total_tokens if rewrite is not None else 0
    )


def _persist_assistant(
    *,
    session_factory: Callable[[], Session],
    plan: QaPlan,
    content: str,
    responses: list[LLMResponse],
    citation_indices: list[int],
) -> Message:
    latency_ms = int((time.perf_counter() - plan.started_at) * 1000)
    model = responses[-1].model if responses else None
    session = session_factory()
    try:
        message = Message(
            conversation_id=plan.conversation_id,
            role="assistant",
            content_md=content,
            token_usage=_token_usage(responses, plan.rewrite),
            latency_ms=latency_ms,
            model=model,
            prompt_version=plan.prompt_version,
        )
        session.add(message)
        session.flush()
        if plan.prepared is not None and plan.prepared.built is not None:
            for index in citation_indices:
                citation = plan.prepared.built.items[index - 1].citation
                session.add(
                    MessageCitation(
                        message_id=message.id,
                        chunk_id=citation.chunk_id,
                        note_id=citation.note_id,
                        score=citation.rerank_score,
                        snippet=citation.snippet,
                        page_no=citation.page_no,
                        rank=index,
                    )
                )
        session.commit()
        return message
    finally:
        session.close()


def _suggestions() -> list[QaSuggestion]:
    return [
        QaSuggestion("rephrase", "换个问法，把问题拆得更具体"),
        QaSuggestion("note", "先补充相关笔记，或缩小检索范围"),
    ]


def _done_data(
    plan: QaPlan,
    message: Message,
    *,
    refused: bool,
    responses: list[LLMResponse],
    refusal_reason: str | None,
    suggestions: list[QaSuggestion],
) -> dict[str, object]:
    return {
        "message_id": message.id,
        "conversation_id": str(plan.conversation_id),
        "tokens": _total_tokens(responses, plan.rewrite),
        "latency_ms": int((time.perf_counter() - plan.started_at) * 1000),
        "refused": refused,
        "refusal_reason": refusal_reason,
        "suggestions": [asdict(item) for item in suggestions],
    }
```

新增 helpers：

```python
def _answer_parts(text: str) -> list[str]:
    if not text:
        return [""]
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"\n{2,}", text):
        parts.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        parts.append(text[start:])
    return parts


def _consume_answer(
    prepared: PreparedAnswer,
    *,
    llm_client: LLMClient | None,
    messages: list[LLMMessage] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[LLMResponse], bool]:
    parts: list[str] = []
    responses: list[LLMResponse] = []
    if messages is None:
        stream = stream_answer(prepared, llm_client=llm_client)
    else:
        stream = stream_answer(
            prepared, llm_client=llm_client, messages=messages
        )
    cancelled = False
    try:
        for chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if chunk.text:
                parts.append(chunk.text)
            if chunk.response is not None:
                responses.append(chunk.response)
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()
    return "".join(parts), responses, cancelled
```

替换 RAG 分支（`if plan.prepared is None` 之后）：

```python
    if plan.prepared.built is None:
        logger.warning(
            "qa_context_missing",
            extra={"conversation_id": plan.conversation_id},
        )
        yield _error_event()
        return

    context_size = len(plan.prepared.built.items)
    try:
        first_text, first_responses, cancelled = _consume_answer(
            plan.prepared,
            llm_client=llm_client,
            cancel_event=cancel_event,
        )
    except GeneratorExit:
        return
    except LLMError:
        logger.warning(
            "qa_stream_llm_failed",
            extra={"conversation_id": plan.conversation_id},
        )
        yield _error_event()
        return
    except Exception:
        logger.exception(
            "qa_stream_failed",
            extra={"conversation_id": plan.conversation_id},
        )
        yield _error_event()
        return
    if cancelled:
        logger.info(
            "qa_stream_disconnected",
            extra={"conversation_id": plan.conversation_id},
        )
        return

    check = check_answer(first_text, context_size=context_size)
    responses = list(first_responses)
    final_text = first_text
    if check.needs_retry and get_settings().qa_citation_max_retries >= 1:
        correction = build_correction(check)
        retry_messages = [
            LLMMessage(role="user", content=plan.prepared.prompt),
            LLMMessage(role="assistant", content=first_text or "(空回答)"),
            LLMMessage(role="user", content=correction),
        ]
        try:
            retry_text, retry_responses, cancelled = _consume_answer(
                plan.prepared,
                llm_client=llm_client,
                messages=retry_messages,
                cancel_event=cancel_event,
            )
        except GeneratorExit:
            return
        except LLMError:
            logger.warning(
                "qa_stream_retry_llm_failed",
                extra={"conversation_id": plan.conversation_id},
            )
            yield _error_event()
            return
        except Exception:
            logger.exception(
                "qa_stream_retry_failed",
                extra={"conversation_id": plan.conversation_id},
            )
            yield _error_event()
            return
        if cancelled:
            logger.info(
                "qa_stream_disconnected",
                extra={"conversation_id": plan.conversation_id},
            )
            return
        responses.extend(retry_responses)
        final_text = retry_text
        check = check_answer(final_text, context_size=context_size)

    refused = False
    refusal_reason: str | None = None
    suggestions: list[QaSuggestion] = []
    if not check.has_content:
        refused = True
        refusal_reason = "empty_answer"
        final_text = REFUSAL_TEXT
        suggestions = _suggestions()
    elif not check.has_valid_citation:
        refused = True
        refusal_reason = "no_valid_citation"
        final_text = REFUSAL_TEXT
        suggestions = _suggestions()
    else:
        final_text = annotate_uncited(
            strip_invalid_citations(final_text, context_size=context_size),
            context_size=context_size,
        )

    indices = [] if refused else _valid_citation_indices(plan, final_text)
    for part in _answer_parts(final_text):
        yield QaStreamEvent(event="delta", data={"text": part})

    try:
        message = _persist_assistant(
            session_factory=session_factory,
            plan=plan,
            content=final_text,
            responses=responses,
            citation_indices=indices,
        )
    except Exception:
        logger.exception("qa_persist_assistant_failed")
        yield _error_event()
        return

    yield QaStreamEvent(
        event="done",
        data=_done_data(
            plan,
            message,
            refused=refused,
            responses=responses,
            refusal_reason=refusal_reason,
            suggestions=suggestions,
        ),
    )
```

同时更新 chitchat/refused 分支与 `stream_events` 签名：

```python
def stream_events(
    plan: QaPlan,
    *,
    llm_client: LLMClient | None = None,
    session_factory: Callable[[], Session] = new_session,
    cancel_event: threading.Event | None = None,
) -> Iterator[QaStreamEvent]:
```

chitchat 分支改为：

```python
        message = _persist_assistant(
            session_factory=session_factory,
            plan=plan,
            content=text,
            responses=[],
            citation_indices=[],
        )
        yield QaStreamEvent(
            event="done",
            data=_done_data(
                plan,
                message,
                refused=False,
                responses=[],
                refusal_reason=None,
                suggestions=[],
            ),
        )
```

`plan.kind == "refused"` 分支改为：

```python
        reason = (
            getattr(plan.prepared.refused, "refusal_reason", None)
            if plan.prepared is not None and plan.prepared.refused is not None
            else "no_context"
        ) or "no_context"
        message = _persist_assistant(
            session_factory=session_factory,
            plan=plan,
            content=REFUSAL_TEXT,
            responses=[],
            citation_indices=[],
        )
        yield QaStreamEvent(
            event="done",
            data=_done_data(
                plan,
                message,
                refused=True,
                responses=[],
                refusal_reason=reason,
                suggestions=_suggestions(),
            ),
        )
```

`backend/app/api/v1/qa.py` 的 `_stream` 改为：

```python
import threading

async def _stream(
    plan: qa_service.QaPlan, request: Request
) -> AsyncIterator[str]:
    cancel_event = threading.Event()
    events = qa_service.stream_events(plan, cancel_event=cancel_event)
    try:
        while True:
            event = await run_in_threadpool(next, events, None)
            if event is None:
                break
            if await request.is_disconnected():
                break
            yield _sse(event)
    finally:
        cancel_event.set()
        close = getattr(events, "close", None)
        if close is not None:
            try:
                close()
            except ValueError:
                # 生成器正在工作线程里执行；cancel_event 会让它收尾关闭上游。
                pass
```

- [ ] **Step 4: 跑 service 与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_service.py -q`

Expected: 既有 13 + 新增 5 → `18 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: 全绿，记录实际数字。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/services/qa_service.py backend/tests/test_qa_service.py
git commit -m "feat(s3-6): SSE 回答校验、重试与补充声明"
```

---

### Task 4: `done` 契约与 API 测试

**Files:**
- Modify: `backend/app/schemas/qa.py`
- Modify: `backend/tests/test_qa_api.py`
- Test: 同上

**Interfaces:**
- Consumes: `done` 新字段；无新路由。
- Produces: `QaSuggestion`、`QaDoneData(refusal_reason, suggestions)`；SSE fixture 断言。

- [ ] **Step 1: 写失败测试**

在 `test_qa_api.py` 的 `client` fixture 中把 done data 改为：

```python
qa_service.QaStreamEvent(
    event="done",
    data={
        "message_id": 31,
        "conversation_id": "12",
        "tokens": 15,
        "latency_ms": 20,
        "refused": False,
        "refusal_reason": None,
        "suggestions": [],
    },
),
```

并在 `test_qa_ask_streams_sse_frames` 末尾加：

```python
assert '"refusal_reason":null' in body
assert '"suggestions":[]' in body
```

新增：

```python
def test_qa_done_contract_supports_refusal_suggestions() -> None:
    from app.schemas.qa import QaDoneData, QaSuggestion

    data = QaDoneData(
        message_id=31,
        conversation_id="12",
        tokens=15,
        latency_ms=20,
        refused=True,
        refusal_reason="no_valid_citation",
        suggestions=[
            QaSuggestion(type="rephrase", text="换问法"),
            QaSuggestion(type="note", text="补笔记"),
        ],
    )
    assert data.suggestions[0].type == "rephrase"
    assert data.refusal_reason == "no_valid_citation"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_api.py -q`

Expected: body 缺字段 / `ImportError: QaSuggestion`。

- [ ] **Step 3: 实现 schema**

在 `backend/app/schemas/qa.py` 顶部补 `from typing import Literal`，在 `QaDoneData` 前加：

```python
class QaSuggestion(BaseModel):
    type: Literal["rephrase", "note"]
    text: str
    note_id: int | None = None
```

并把 `QaDoneData` 改为：

```python
class QaDoneData(BaseModel):
    message_id: int
    conversation_id: str
    tokens: int
    latency_ms: int
    refused: bool
    refusal_reason: str | None = None
    suggestions: list[QaSuggestion] = Field(default_factory=list)
```

顶部 import 补 `Literal`。

- [ ] **Step 4: 跑 API 与全套**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest backend/tests/test_qa_api.py -q`

Expected: `8 passed`。

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: 全绿，记录实际数字。

- [ ] **Step 5: 提交**

```bash
cd study-agent
git add backend/app/schemas/qa.py backend/tests/test_qa_api.py
git commit -m "feat(s3-6): done 事件增加拒答原因与建议"
```

---

### Task 5: 真实 5+5 验收、文档与最终提交

**Files:**
- Create: `scripts/citation_eval.py`
- Modify: `docs/API.md` §5
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/AI协作开发实施计划.md` S3-6
- Modify: `docs/spec/s3-6-citation-check.md`（实施记录）
- Test: 脚本实跑

**Interfaces:**
- Consumes: `qa_service.prepare_ask` + `qa_service.stream_events` + `citation_checker.check_answer`。
- Produces: 10 条逐条验收输出与退出码。

- [ ] **Step 1: 写验收脚本**

`scripts/citation_eval.py`：

```python
"""S3-6 引用校验 5+5 真实验收。

用法：
    python scripts/citation_eval.py --user-id 18
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import new_session  # noqa: E402
from app.services import qa_service  # noqa: E402
from app.services.citation_checker import (  # noqa: E402
    SUPPLEMENT_PREFIX,
    check_answer,
)

NO_ANSWER_QUESTIONS = [
    "牛顿第二定律的适用条件是什么？",
    "如何用洛必达法则求极限？",
    "细胞有丝分裂各阶段的主要特征是什么？",
    "英语虚拟语气中过去完成时怎么用？",
    "化学平衡常数如何计算？",
]
PARTIAL_QUESTIONS = [
    "错位相减法的步骤是什么？它的历史起源是什么？",
    "错位相减法的适用条件是什么？三项乘积的数列怎么求和？",
    "函数奇偶性怎么判断？函数的最小正周期怎么求？",
    "函数单调性的定义是什么？含参函数单调性怎么讨论？",
    "错位相减法怎么用？它和倒序相加法有什么区别？",
]


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


def run_case(question: str, *, user_id: int) -> dict[str, object]:
    session = new_session()
    try:
        plan = qa_service.prepare_ask(
            session,
            user_id=user_id,
            question=question,
            scope=None,
            conversation_id=None,
        )
    finally:
        session.close()

    events = list(qa_service.stream_events(plan))
    done = next(event for event in events if event.event == "done")
    text = "".join(
        str(event.data["text"])
        for event in events
        if event.event == "delta"
    )
    context_size = (
        len(plan.prepared.built.items)
        if plan.prepared is not None and plan.prepared.built is not None
        else 0
    )
    check = check_answer(text, context_size=context_size) if context_size else None
    return {
        "conversation_id": plan.conversation_id,
        "refused": done.data["refused"],
        "refusal_reason": done.data["refusal_reason"],
        "suggestions": len(done.data["suggestions"]),
        "has_prefix": SUPPLEMENT_PREFIX in text,
        "valid": check.valid_indices if check else [],
        "invalid": check.invalid_indices if check else [],
        "uncited": len(check.uncited_blocks) if check else 0,
        "message_id": done.data["message_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    _configure_stdio()

    rows: list[tuple[str, str, dict[str, object]]] = []
    for question in NO_ANSWER_QUESTIONS:
        rows.append(("no_answer", question, run_case(question, user_id=args.user_id)))
    for question in PARTIAL_QUESTIONS:
        rows.append(("partial", question, run_case(question, user_id=args.user_id)))

    failures = 0
    for kind, question, result in rows:
        expected_refused = kind == "no_answer"
        ok = bool(result["refused"]) == expected_refused
        if kind == "partial":
            ok = ok and not result["refused"] and bool(result["has_prefix"])
        if not ok:
            failures += 1
        print(
            f"[{'PASS' if ok else 'FAIL'}] {kind} {question}\n"
            f"  refused={result['refused']} reason={result['refusal_reason']} "
            f"prefix={result['has_prefix']} suggestions={result['suggestions']} "
            f"valid={result['valid']} invalid={result['invalid']} "
            f"uncited={result['uncited']} conversation={result['conversation_id']} "
            f"message={result['message_id']}"
        )

    print(f"\n结果：{len(rows) - failures}/{len(rows)} 通过")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 先跑单元测试**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: 全绿；记录实际数字（预计 686）。

- [ ] **Step 3: 跑真实 5+5**

Run: `cd study-agent && .\.venv\Scripts\python.exe scripts/citation_eval.py --user-id 18`

Expected：逐条 PASS，最后 `10/10 通过`；若某条不通过，保留原始输出并调整测试问题（不得修改判定口径或伪造结果）。

- [ ] **Step 4: 真实 SSE 抽查**

启动后端，发一次部分缺失问题（可用上面的 partial 问题），确认：

- `meta` 先到；
- 完整生成后收到按块 `delta`；
- `done` 含新字段；
- DB `messages.content_md` 有前缀，`message_citations` 只含合法 rank。

```powershell
cd study-agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

另开终端生成 token 后 `curl -N`；记录 conversation_id/message_id。验收后停服务。

- [ ] **Step 5: 更新文档**

`docs/API.md` §5 `done` 改为：

```markdown
- `done`：`{message_id, conversation_id(字符串), tokens, latency_ms, refused, refusal_reason, suggestions}`
  - `refusal_reason`：`null` / `no_context` / `low_score` / `empty_answer` / `no_valid_citation`
  - `suggestions`：[{type:"rephrase"|"note", text, note_id}]；正常回答为空数组
```

并补一句：S3-6 起先完整生成、校验/最多重试一次后再按块发 `delta`，首字延迟增加；未引用块前会加固定声明。

`docs/PROGRESS.md` 更新当前状态、S3-6 勾选、变更日志、遗留（新增建议不落库、块级启发式、首字延迟、断连不能立即停计费）。

`docs/DECISIONS.md` 追加 D-040（实际最大编号以文件为准；若 D-040 已占用则顺延），记录：校验后输出、块级检测/前缀、两轮后拒答或标注、done 新字段、不落库建议、只接 SSE。

任务卡 S3-6 标题加 ✅，记录实测数字和脚本路径。

spec 追加 §10 实施记录：实际测试数、5+5 结果、真实 SSE 证据、偏差。

- [ ] **Step 6: 最终全套与提交**

Run: `cd study-agent && .\.venv\Scripts\python.exe -m pytest -q`

Expected: 全绿；把实际数字回填 PROGRESS/spec/plan。

```bash
cd study-agent
git add scripts/citation_eval.py docs/API.md docs/PROGRESS.md docs/DECISIONS.md docs/AI协作开发实施计划.md docs/spec/s3-6-citation-check.md docs/plan/s3-6-citation-check.md
git commit -m "docs(s3-6): 引用校验验收记录与文档同步"
```

---

## Self-Review

- **Spec coverage**：目标/非目标（Task 1-5 边界）、已确认决策 1-7（Task 3-5）、checker 契约（Task 1）、重试/拒答/标注（Task 3）、API done（Task 4）、5+5 验收（Task 5）、断连 cancel（Task 3）。
- **类型一致性**：`CitationCheck` 字段、`QaSuggestion` 字段、`responses: list[LLMResponse]`、`stream_events(cancel_event=...)` 在 Task 1/3/4 名称一致；`done.suggestions` 始终为 dict 列表。
- **占位符扫描**：无 TBD/TODO；每个测试都有断言，每个实现步骤都有代码。
- **已知偏差**：测试数字为估算，执行时回填；真实 5+5 若个别问题被检索命中，只调整问题不改判定口径。

## 执行记录（2026-11-01）

- Task 1：12 checker 测试，全量 678 passed。
- Task 2：1 条重试消息测试，全量 679 passed。
- Task 3：5 条 SSE 集成测试，service 18 passed，全量 684 passed；路由增加 `cancel_event`。
- Task 4：2 条 API 契约测试，API 8 passed，全量 **686 passed, 1 warning**。
- Task 5：真实 5+5 **10/10 通过**；真实 SSE `meta` 3.10s、首个 `delta` 15.06s、done 15.10s；消息 32 前缀 2 处、citations rank 1–3。
- 偏差：无代码范围偏离；S3-5 两条断言按新行为调整并保留测试；测试数字与计划一致（686）。