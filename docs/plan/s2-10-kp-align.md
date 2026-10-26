# S2-10 知识点对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把笔记内容对齐到已有知识点树：向量召回 + 关键词 + 树先验打分，LLM 只在候选内选择，自动/待确认两档落库，并交付待确认队列的列表/确认/忽略接口。

**Architecture:** `ai/align` 放纯打分与 LLM 抽取；`kp_align_service` 负责向量补全、候选召回、落库与队列操作；`tasks/kp_align` 复用 S2-7 任务框架异步执行；笔记创建/更新与解析完成时入队。

**Tech Stack:** FastAPI、SQLAlchemy 2.1、Pydantic 2、pgvector、Jinja2、现有 Embedding/LLM 适配器、pytest。

**Spec:** `docs/spec/s2-10-kp-align.md`

## Global Constraints

- 不新增迁移；`note_kps` 四列 + 现有 `knowledge_points.embedding` 足够。
- 公式固定：`0.6*cos + 0.3*keyword + 0.1*tree_prior`；阈值 0.75/0.55；LLM `confidence<0.5` 丢弃。
- LLM 只能从候选 `kp_id` 中选，禁止输出新知识点名；严格 JSON + Pydantic + 最多 2 次重试。
- 自动行 `source='ai', confirmed=true`；待确认行 `source='ai', confirmed=false`；用户确认改 `source='manual'`。
- 重跑先删该笔记全部 `source='ai'` 行，保留 `manual`。
- 任务 handler 不 commit，由 runner 提交；对齐失败抛 `AlignError`。
- 自动触发失败只记 WARNING，不影响笔记保存/解析结果。
- 测试禁止真实 LLM/Embedding/DB；用 Fake 客户端与 FakeSession。

---

### Task 1: 打分与 LLM 抽取

**Files:**
- Create: `backend/app/ai/align/__init__.py`
- Create: `backend/app/ai/align/scoring.py`
- Create: `backend/app/ai/align/extractor.py`
- Create: `backend/app/ai/prompts/kp_align_v1.md`
- Test: `backend/tests/test_align_scoring.py`
- Test: `backend/tests/test_align_extractor.py`

**Interfaces:**
- Consumes: `LLMClient`/`LLMMessage`/`LLMResponse`（`app.ai.llm`）
- Produces: `Candidate`、`keyword_score`/`tree_prior`/`combine`/`classify`、`extract_matches`/`LlmMatch`/`AlignError`

- [ ] **Step 1: 写 scoring 失败测试**

`backend/tests/test_align_scoring.py`：

```python
"""S2-10 打分纯函数（方案 6.2）。"""
from __future__ import annotations

import pytest

from app.ai.align.scoring import (
    Candidate,
    classify,
    combine,
    keyword_score,
    tree_prior,
)


def test_combine_uses_fixed_weights() -> None:
    assert combine(1.0, 1.0, 1.0) == 1.0
    assert combine(0.0, 0.0, 0.0) == 0.0
    assert combine(0.5, 1.0, 0.0) == pytest.approx(0.6)


def test_classify_boundaries() -> None:
    assert classify(0.75) == "auto"
    assert classify(0.749) == "pending"
    assert classify(0.55) == "pending"
    assert classify(0.549) == "drop"


def test_keyword_score_full_name_hit() -> None:
    assert keyword_score("函数的单调性", "今天复习函数的单调性判定") == 1.0


def test_keyword_score_core_term_hit() -> None:
    assert keyword_score("函数的单调性", "讨论单调性时注意定义域") == 0.6
    assert keyword_score("平面向量的数量积", "数量积的几何意义") == 0.6


def test_keyword_score_miss() -> None:
    assert keyword_score("函数的单调性", "数列求和错位相减") == 0.0


def test_tree_prior_ancestor_in_tags() -> None:
    assert tree_prior(3, ["函数", "函数的单调性"], ["函数"], "单调性复习") == 1.0


def test_tree_prior_ancestor_in_title() -> None:
    assert tree_prior(3, ["三角函数", "解三角形"], [], "解三角形专题") == 1.0


def test_tree_prior_module_level_without_tags() -> None:
    assert tree_prior(2, ["函数"], [], "随手记") == 0.3


def test_tree_prior_leaf_without_tags() -> None:
    assert tree_prior(3, ["函数", "函数的单调性"], [], "随手记") == 0.0


def test_candidate_score_and_classify() -> None:
    candidate = Candidate(
        kp_id=1,
        code="MATH-FUNC-02",
        name="函数的单调性",
        path="函数 / 函数的单调性",
        cos=0.8,
        keyword=1.0,
        prior=0.3,
    )
    assert candidate.score == pytest.approx(0.81)
    assert classify(candidate.score) == "auto"
```

- [ ] **Step 2: 写 extractor 失败测试**

`backend/tests/test_align_extractor.py`：

```python
"""S2-10 LLM 候选内抽取：FakeLLM，不真实调用。"""
from __future__ import annotations

import pytest

from app.ai.align.extractor import AlignError, extract_matches
from app.ai.align.scoring import Candidate
from app.ai.llm import LLMClient, LLMResponse


class FakeLLM(LLMClient):
    def __init__(self, texts: list[str]) -> None:
        super().__init__(model="fake-llm")
        self.texts = list(texts)
        self.calls: list[list] = []

    def chat(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        self.calls.append(messages)
        text = self.texts.pop(0)
        return LLMResponse(text=text, model="fake-llm", total_tokens=10)


def _candidates() -> list[Candidate]:
    return [
        Candidate(1, "MATH-FUNC-02", "函数的单调性", "函数 / 函数的单调性", 0.8, 1.0, 0.3),
        Candidate(2, "MATH-FUNC-03", "函数的奇偶性", "函数 / 函数的奇偶性", 0.6, 0.0, 0.3),
    ]


def test_extract_valid_json_returns_matches() -> None:
    llm = FakeLLM(['{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"单调性"}]}'])
    matches = extract_matches(
        note_title="单调性", note_excerpt="讨论单调性", candidates=_candidates(), llm_client=llm
    )
    assert [(m.kp_id, m.confidence) for m in matches] == [(1, 0.9)]


def test_extract_drops_unknown_kp_id() -> None:
    llm = FakeLLM(['{"matches":[{"kp_id":99,"confidence":0.9,"evidence":"x"}]}'])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    ) == []


def test_extract_dedupes_same_kp() -> None:
    llm = FakeLLM(
        ['{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"a"},'
         '{"kp_id":1,"confidence":0.8,"evidence":"b"}]}']
    )
    matches = extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    )
    assert len(matches) == 1
    assert matches[0].confidence == 0.9


def test_extract_retries_after_invalid_confidence() -> None:
    llm = FakeLLM(
        [
            '{"matches":[{"kp_id":1,"confidence":1.5,"evidence":"a"}]}',
            '{"matches":[{"kp_id":1,"confidence":0.8,"evidence":"a"}]}',
        ]
    )
    matches = extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    )
    assert len(matches) == 1
    assert len(llm.calls) == 2


def test_extract_retries_after_invalid_json() -> None:
    llm = FakeLLM(["不是 JSON", '{"matches":[]}'])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
    ) == []
    assert len(llm.calls) == 2


def test_extract_raises_after_three_invalid_responses() -> None:
    llm = FakeLLM(["bad", "bad", "bad"])
    with pytest.raises(AlignError, match="抽取失败"):
        extract_matches(
            note_title="t", note_excerpt="x", candidates=_candidates(), llm_client=llm
        )
    assert len(llm.calls) == 3


def test_extract_prompt_contains_candidates_and_excerpt() -> None:
    llm = FakeLLM(['{"matches":[]}'])
    extract_matches(
        note_title="单调性复习",
        note_excerpt="讨论单调性",
        candidates=_candidates(),
        llm_client=llm,
    )
    prompt = llm.calls[0][0].content
    assert "MATH-FUNC-02" in prompt
    assert "讨论单调性" in prompt
    assert "只能" in prompt


def test_extract_empty_candidates_skips_llm() -> None:
    llm = FakeLLM([])
    assert extract_matches(
        note_title="t", note_excerpt="x", candidates=[], llm_client=llm
    ) == []
    assert llm.calls == []
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_scoring.py tests/test_align_extractor.py -q`
Expected: FAIL，`ModuleNotFoundError: app.ai.align`

- [ ] **Step 4: 实现 scoring**

`backend/app/ai/align/scoring.py`：

```python
"""S2-10 对齐打分（方案 6.2）：0.6 向量 + 0.3 关键词 + 0.1 树位置先验。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AUTO_THRESHOLD = 0.75
PENDING_THRESHOLD = 0.55
LLM_MIN_CONFIDENCE = 0.5
TOP_K = 10

_CORE_PREFIXES = (
    "函数的",
    "数列的",
    "集合的",
    "三角函数的",
    "平面向量的",
    "一元二次",
    "空间的",
    "复数的",
)

AlignLevel = Literal["auto", "pending", "drop"]


@dataclass(frozen=True)
class Candidate:
    kp_id: int
    code: str
    name: str
    path: str
    cos: float
    keyword: float
    prior: float

    @property
    def score(self) -> float:
        return combine(self.cos, self.keyword, self.prior)


def combine(cos: float, keyword: float, prior: float) -> float:
    return round(0.6 * cos + 0.3 * keyword + 0.1 * prior, 6)


def classify(score: float) -> AlignLevel:
    if score >= AUTO_THRESHOLD:
        return "auto"
    if score >= PENDING_THRESHOLD:
        return "pending"
    return "drop"


def keyword_score(kp_name: str, text: str) -> float:
    if kp_name and kp_name in text:
        return 1.0
    core = kp_name
    for prefix in _CORE_PREFIXES:
        if core.startswith(prefix) and len(core) > len(prefix):
            core = core[len(prefix) :]
            break
    if len(core) >= 2 and core != kp_name and core in text:
        return 0.6
    return 0.0


def tree_prior(
    level: int, ancestor_names: list[str], tags: list[str], title: str
) -> float:
    anchors = list(tags) + [title]
    if any(name and any(name in anchor for anchor in anchors) for name in ancestor_names):
        return 1.0
    if level <= 2:
        return 0.3
    return 0.0
```

- [ ] **Step 5: 实现 prompt 与 extractor**

`backend/app/ai/prompts/kp_align_v1.md`：

```markdown
你是高中数学教研员，需要判断一段学生笔记对应哪些**已有**知识点。

规则：
1. 只能从下面候选知识点里选择，禁止创造新知识点、禁止改写名称；
2. 每条匹配给出 kp_id、0–1 的 confidence、以及不超过 120 字的原文证据；
3. 没有匹配就返回空数组；
4. 只输出 JSON，不要解释、不要 Markdown 代码块。

输出格式：
{"matches": [{"kp_id": 12, "confidence": 0.86, "evidence": "原文片段"}]}

笔记标题：{{ note_title }}

笔记摘要：
{{ note_excerpt }}

候选知识点：
{% for c in candidates -%}
- kp_id={{ c.kp_id }}｜{{ c.code }}｜{{ c.path }}｜余弦={{ "%.3f"|format(c.cos) }}｜关键词={{ "%.2f"|format(c.keyword) }}
{% endfor -%}
```

`backend/app/ai/align/extractor.py`：

```python
"""S2-10 LLM 候选内抽取：严格 JSON + Pydantic 校验 + 最多 2 次重试。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError

from app.ai.align.scoring import Candidate
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "kp_align_v1.md"


class AlignError(Exception):
    """LLM 抽取最终失败；任务层据此重试/失败。"""


class AlignItem(BaseModel):
    kp_id: int
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=200)


class AlignOutput(BaseModel):
    matches: list[AlignItem] = Field(default_factory=list)


@dataclass(frozen=True)
class LlmMatch:
    kp_id: int
    confidence: float
    evidence: str


def render_prompt(*, note_title: str, note_excerpt: str, candidates: list[Candidate]) -> str:
    if not PROMPT_PATH.is_file():
        raise AlignError(f"Prompt 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(
            note_title=note_title, note_excerpt=note_excerpt, candidates=candidates
        )
    except Exception as exc:
        raise AlignError(f"Prompt 渲染失败：{exc}") from exc


def extract_matches(
    *,
    note_title: str,
    note_excerpt: str,
    candidates: list[Candidate],
    llm_client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[LlmMatch]:
    if not candidates:
        return []
    client = llm_client or get_llm_client()
    allowed = {c.kp_id for c in candidates}
    prompt = render_prompt(
        note_title=note_title, note_excerpt=note_excerpt, candidates=candidates
    )
    messages = [LLMMessage(role="user", content=prompt)]
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        response = client.chat(messages, temperature=0.0, max_tokens=800)
        try:
            output = AlignOutput.model_validate(_loads_json(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            continue
        seen: set[int] = set()
        matches: list[LlmMatch] = []
        for item in output.matches:
            if item.kp_id not in allowed or item.kp_id in seen:
                continue
            seen.add(item.kp_id)
            matches.append(LlmMatch(item.kp_id, item.confidence, item.evidence))
        return matches
    raise AlignError(f"知识点抽取失败（已重试 {max_retries} 次）：{last_error}")


def _loads_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(clean[start : end + 1])
```

`backend/app/ai/align/__init__.py`：

```python
"""S2-10 知识点对齐：打分与 LLM 候选内抽取。"""
from app.ai.align.extractor import AlignError, LlmMatch, extract_matches
from app.ai.align.scoring import (
    AUTO_THRESHOLD,
    LLM_MIN_CONFIDENCE,
    PENDING_THRESHOLD,
    TOP_K,
    Candidate,
    classify,
    combine,
    keyword_score,
    tree_prior,
)

__all__ = [
    "AUTO_THRESHOLD",
    "LLM_MIN_CONFIDENCE",
    "PENDING_THRESHOLD",
    "TOP_K",
    "AlignError",
    "Candidate",
    "LlmMatch",
    "classify",
    "combine",
    "extract_matches",
    "keyword_score",
    "tree_prior",
]
```

- [ ] **Step 6: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_scoring.py tests/test_align_extractor.py -q`
Expected: `18 passed`

- [ ] **Step 7: 提交**

```bash
git add backend/app/ai/align backend/app/ai/prompts/kp_align_v1.md backend/tests/test_align_scoring.py backend/tests/test_align_extractor.py
git commit -m "feat(s2-10): 对齐打分与 LLM 候选抽取"
```

---

### Task 2: 对齐服务与待确认队列

**Files:**
- Create: `backend/app/schemas/kp_align.py`
- Modify: `backend/app/models/note_kp.py`（加 `note` / `knowledge_point` 关系）
- Create: `backend/app/services/kp_align_service.py`
- Test: `backend/tests/test_align_service.py`

**Interfaces:**
- Consumes: `Candidate`/`LlmMatch`/`extract_matches`、`EmbeddingClient`、`Note`/`NoteKp`/`KnowledgePoint`/`Subject`、`Paginate`
- Produces: `ensure_kp_embeddings`/`retrieve_candidates`/`align_note`/`list_pending`/`confirm_pairs`/`reject_pairs`、`AlignStats`、`AlignPair`/`PendingAlignOut`/`AlignBatchOut`

- [ ] **Step 1: 写服务失败测试**

`backend/tests/test_align_service.py`：

```python
"""S2-10 对齐服务：FakeSession 按表名分派，Fake 客户端不真实调用。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ai.align.scoring import Candidate
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.subject import Subject
from app.models.user import User
from app.services import kp_align_service


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = list(vectors)
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        return self.vectors.pop(0)


class FakeLLM:
    model = "fake-llm"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None):
        from app.ai.llm import LLMResponse

        self.calls += 1
        return LLMResponse(text=self.text, model="fake-llm")


class FakeSession:
    def __init__(
        self,
        *,
        kps: list[KnowledgePoint] | None = None,
        note_kps: list[NoteKp] | None = None,
        note: Note | None = None,
        user: User | None = None,
    ) -> None:
        self.kps = kps or []
        self.note_kps = note_kps or []
        self.note = note
        self.user = user
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0

    def scalars(self, statement: object):
        sql = str(statement)
        if "FROM note_kps" in sql:
            return list(self.note_kps)
        if "FROM knowledge_points" in sql:
            return list(self.kps)
        raise AssertionError(f"unexpected SQL: {sql}")

    def scalar(self, statement: object):
        raise AssertionError("unexpected scalar")

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    def flush(self) -> None:
        for row in self.added:
            if isinstance(row, NoteKp) and getattr(row, "note_id", None) is None:
                row.note_id = 1

    def commit(self) -> None:
        self.commits += 1


def _subject() -> Subject:
    subject = Subject(name="高中数学", code="math", stage="高中")
    subject.id = 1
    return subject


def _kp(
    kp_id: int,
    code: str,
    name: str,
    level: int,
    parent_id: int | None,
    embedding: list[float] | None,
) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1,
        parent_id=parent_id,
        name=name,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=0,
        embedding=embedding,
    )
    kp.id = kp_id
    return kp


def _note(text: str, *, subject_id: int | None = 1) -> Note:
    note = Note(
        user_id=1,
        subject_id=subject_id,
        title="函数单调性复习",
        content_md=text,
        content_text=text,
        tags=["函数"],
        folder=None,
    )
    note.id = 1
    note.deleted_at = None
    return note


def _user() -> User:
    user = User(
        username="align_student",
        password_hash="hash",
        nickname="测试用户_1",
        grade="高一",
        role="student",
    )
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def test_ensure_kp_embeddings_only_fills_missing() -> None:
    missing = _kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, None)
    present = _kp(2, "MATH-FUNC-03", "函数的奇偶性", 2, None, [1.0, 0.0])
    embedder = FakeEmbedder([[0.5, 0.5]])
    session = FakeSession(kps=[missing, present])
    count = kp_align_service.ensure_kp_embeddings(
        session, subject_id=1, embedder=embedder  # type: ignore[arg-type]
    )
    assert count == 1
    assert missing.embedding == [0.5, 0.5]
    assert embedder.calls and len(embedder.calls[0]) == 1


def test_ensure_kp_embeddings_skips_when_none_missing() -> None:
    embedder = FakeEmbedder([])
    session = FakeSession(
        kps=[_kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, [1.0, 0.0])]
    )
    assert kp_align_service.ensure_kp_embeddings(
        session, subject_id=1, embedder=embedder  # type: ignore[arg-type]
    ) == 0
    assert embedder.calls == []


def test_retrieve_candidates_computes_cosine_and_path() -> None:
    root = _kp(1, "MATH", "高中数学", 1, None, [1.0, 0.0])
    child = _kp(2, "MATH-FUNC", "函数", 2, 1, [1.0, 0.0])
    leaf = _kp(3, "MATH-FUNC-02", "函数的单调性", 3, 2, [0.8, 0.6])
    session = FakeSession(kps=[root, child, leaf])
    note = _note("讨论函数的单调性")
    candidates = kp_align_service.retrieve_candidates(
        session, note=note, note_vec=[1.0, 0.0]  # type: ignore[arg-type]
    )
    by_id = {c.kp_id: c for c in candidates}
    assert by_id[3].cos == pytest.approx(0.8)
    assert by_id[3].path == "高中数学 / 函数 / 函数的单调性"
    assert by_id[3].keyword == 1.0
    assert by_id[3].prior == 1.0  # 祖先「函数」命中标签


def test_align_note_empty_text_returns_zeros() -> None:
    embedder = FakeEmbedder([])
    session = FakeSession(kps=[])
    stats = kp_align_service.align_note(
        session, note=_note(""), embedder=embedder, llm_client=FakeLLM("{}")  # type: ignore[arg-type]
    )
    assert (stats.candidates, stats.auto, stats.pending, stats.dropped) == (0, 0, 0, 0)
    assert embedder.calls == []


def test_align_note_classifies_auto_pending_drop() -> None:
    root = _kp(1, "MATH", "高中数学", 1, None, [1.0, 0.0])
    func = _kp(2, "MATH-FUNC", "函数", 2, 1, [1.0, 0.0])
    auto = _kp(3, "MATH-FUNC-02", "函数的单调性", 3, 2, [1.0, 0.0])
    pending = _kp(4, "MATH-FUNC-03", "函数的奇偶性", 3, 2, [0.8, 0.6])
    drop = _kp(5, "MATH-SEQ-01", "数列的概念与表示", 2, 1, [0.1, 0.995])
    session = FakeSession(kps=[root, func, auto, pending, drop])
    embedder = FakeEmbedder([[1.0, 0.0]])
    llm = FakeLLM(
        '{"matches":[{"kp_id":3,"confidence":0.9,"evidence":"单调性"},'
        '{"kp_id":4,"confidence":0.9,"evidence":"奇偶性"},'
        '{"kp_id":5,"confidence":0.9,"evidence":"数列"}]}'
    )
    stats = kp_align_service.align_note(
        session,
        note=_note("讨论函数的单调性与奇偶性"),  # type: ignore[arg-type]
        embedder=embedder,
        llm_client=llm,
    )
    assert (stats.candidates, stats.auto, stats.pending, stats.dropped) == (5, 1, 1, 3)
    rows = {(r.note_id, r.kp_id): r for r in session.added if isinstance(r, NoteKp)}
    assert rows[(1, 3)].confirmed is True
    assert rows[(1, 3)].source == "ai"
    assert rows[(1, 4)].confirmed is False
    assert Decimal("0.55") <= Decimal(str(rows[(1, 4)].confidence)) < Decimal("0.75")


def test_align_note_replaces_ai_rows_but_keeps_manual() -> None:
    kp = _kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, [1.0, 0.0])
    old_ai = NoteKp(note_id=1, kp_id=9, confidence=Decimal("0.6"), source="ai", confirmed=False)
    manual = NoteKp(note_id=1, kp_id=8, confidence=Decimal("0.9"), source="manual", confirmed=True)
    session = FakeSession(kps=[kp], note_kps=[old_ai, manual])
    kp_align_service.align_note(
        session,
        note=_note("函数的单调性"),  # type: ignore[arg-type]
        embedder=FakeEmbedder([[1.0, 0.0]]),
        llm_client=FakeLLM('{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"x"}]}'),
    )
    assert old_ai in session.deleted
    assert manual not in session.deleted


def test_confirm_pairs_updates_owned_rows_only() -> None:
    mine = NoteKp(note_id=1, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    mine.note = _note("x")
    mine.note.user_id = 1
    other = NoteKp(note_id=2, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    other.note = _note("y")
    other.note.user_id = 2
    session = FakeSession(note_kps=[mine, other])
    result = kp_align_service.confirm_pairs(
        session, viewer=_user(), pairs=[kp_align_service.AlignPair(note_id=1, kp_id=1),
                                        kp_align_service.AlignPair(note_id=2, kp_id=1)]
    )
    assert result.confirmed == 1
    assert result.skipped == 1
    assert mine.confirmed is True
    assert mine.source == "manual"
    assert other.confirmed is False


def test_reject_pairs_deletes_only_unconfirmed_ai_rows() -> None:
    pending = NoteKp(note_id=1, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    confirmed = NoteKp(note_id=1, kp_id=2, confidence=Decimal("0.9"), source="manual", confirmed=True)
    pending.note = _note("x")
    confirmed.note = pending.note
    session = FakeSession(note_kps=[pending, confirmed])
    result = kp_align_service.reject_pairs(
        session,
        viewer=_user(),
        pairs=[kp_align_service.AlignPair(note_id=1, kp_id=1),
               kp_align_service.AlignPair(note_id=1, kp_id=2)],
    )
    assert result.deleted == 1
    assert result.skipped == 1
    assert pending in session.deleted
    assert confirmed not in session.deleted
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_service.py -q`
Expected: FAIL，`ModuleNotFoundError: app.services.kp_align_service`

- [ ] **Step 3: 加 NoteKp 关系与 schemas**

`backend/app/models/note_kp.py` 在字段后追加：

```python
    note: Mapped["Note"] = relationship("Note", lazy="joined")
    knowledge_point: Mapped["KnowledgePoint"] = relationship(
        "KnowledgePoint", lazy="joined"
    )
```

并在文件头部导入：

```python
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.knowledge_point import KnowledgePoint
    from app.models.note import Note
```

`backend/app/schemas/kp_align.py`：

```python
"""S2-10 对齐队列出入参。"""
from __future__ import annotations

from pydantic import AliasPath, BaseModel, ConfigDict, Field


class AlignPair(BaseModel):
    note_id: int = Field(ge=1)
    kp_id: int = Field(ge=1)


class AlignBatchIn(BaseModel):
    items: list[AlignPair] = Field(min_length=1, max_length=100)


class AlignBatchOut(BaseModel):
    confirmed: int = 0
    deleted: int = 0
    skipped: int = 0


class PendingAlignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    note_id: int
    kp_id: int
    confidence: float
    note_title: str = Field(validation_alias=AliasPath("note", "title"))
    kp_name: str = Field(validation_alias=AliasPath("knowledge_point", "name"))
    kp_code: str = Field(validation_alias=AliasPath("knowledge_point", "code"))
```

- [ ] **Step 4: 实现服务**

`backend/app/services/kp_align_service.py`：

```python
"""S2-10 对齐服务：向量补全、候选召回、打分落库、待确认队列。"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.align.extractor import extract_matches
from app.ai.align.scoring import (
    AUTO_THRESHOLD,
    LLM_MIN_CONFIDENCE,
    PENDING_THRESHOLD,
    TOP_K,
    Candidate,
    classify,
    combine,
    keyword_score,
    tree_prior,
)
from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.ai.llm import LLMClient
from app.core.exceptions import InvalidParamError
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.kp_align import AlignBatchOut, AlignPair, PendingAlignOut
from app.utils.pagination import PageParams, paginate_query

_MAX_NOTE_CHARS = 2000


@dataclass(frozen=True)
class AlignStats:
    candidates: int
    matched: int
    auto: int
    pending: int
    dropped: int


def ensure_kp_embeddings(
    session: Session,
    *,
    subject_id: int | None,
    embedder: EmbeddingClient | None = None,
) -> int:
    client = embedder or get_embedding_client()
    stmt = select(KnowledgePoint)
    if subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    rows = list(session.scalars(stmt.order_by(KnowledgePoint.id)))
    missing = [row for row in rows if row.embedding is None]
    if not missing:
        return 0
    by_id = {row.id: row for row in rows}
    texts = [_embedding_text(row, by_id) for row in missing]
    vectors = client.encode(texts)
    for row, vector in zip(missing, vectors, strict=True):
        row.embedding = vector
    session.flush()
    return len(missing)


def retrieve_candidates(
    session: Session,
    *,
    note: Note,
    note_vec: list[float],
    top_k: int = TOP_K,
    embedder: EmbeddingClient | None = None,
) -> list[Candidate]:
    stmt = select(KnowledgePoint)
    if note.subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == note.subject_id)
    rows = list(session.scalars(stmt.order_by(KnowledgePoint.id)))
    rows = [row for row in rows if row.embedding is not None]
    by_id = {row.id: row for row in rows}
    children: dict[int, list[KnowledgePoint]] = defaultdict(list)
    for row in rows:
        if row.parent_id is not None:
            children[row.parent_id].append(row)
    text = _note_text(note)
    scored: list[Candidate] = []
    for row in rows:
        ancestors = _ancestor_names(row, by_id)
        scored.append(
            Candidate(
                kp_id=row.id,
                code=row.code,
                name=row.name,
                path=" / ".join([*reversed(ancestors), row.name]),
                cos=_cosine(note_vec, list(row.embedding or [])),
                keyword=keyword_score(row.name, text),
                prior=tree_prior(row.level, ancestors, list(note.tags or []), note.title),
            )
        )
    scored.sort(key=lambda item: item.cos, reverse=True)
    return scored[:top_k]


def align_note(
    session: Session,
    *,
    note: Note,
    embedder: EmbeddingClient | None = None,
    llm_client: LLMClient | None = None,
) -> AlignStats:
    text = _note_text(note)
    if not text.strip():
        return AlignStats(0, 0, 0, 0, 0)
    client = embedder or get_embedding_client()
    ensure_kp_embeddings(session, subject_id=note.subject_id, embedder=client)
    note_vec = client.encode([text[:_MAX_NOTE_CHARS]])[0]
    candidates = retrieve_candidates(session, note=note, note_vec=note_vec)
    old_rows = list(
        session.scalars(
            select(NoteKp).where(NoteKp.note_id == note.id, NoteKp.source == "ai")
        )
    )
    if not candidates:
        for row in old_rows:
            session.delete(row)
        return AlignStats(0, 0, 0, 0, 0)
    matches = extract_matches(
        note_title=note.title,
        note_excerpt=text[:_MAX_NOTE_CHARS],
        candidates=candidates,
        llm_client=llm_client,
    )
    selected = {match.kp_id: match for match in matches}
    auto = pending = 0
    new_rows: list[NoteKp] = []
    for candidate in candidates:
        match = selected.get(candidate.kp_id)
        if match is None or match.confidence < LLM_MIN_CONFIDENCE:
            continue
        score = combine(candidate.cos, candidate.keyword, candidate.prior)
        level = classify(score)
        if level == "drop":
            continue
        if level == "auto":
            auto += 1
        else:
            pending += 1
        new_rows.append(
            NoteKp(
                note_id=note.id,
                kp_id=candidate.kp_id,
                confidence=Decimal(str(round(score, 3))),
                source="ai",
                confirmed=level == "auto",
            )
        )
    for row in old_rows:
        session.delete(row)
    for row in new_rows:
        session.add(row)
    session.flush()
    return AlignStats(
        candidates=len(candidates),
        matched=len(selected),
        auto=auto,
        pending=pending,
        dropped=len(candidates) - auto - pending,
    )


def list_pending(
    session: Session,
    *,
    viewer: User,
    params: PageParams,
    note_id: int | None = None,
) -> PageData[PendingAlignOut]:
    stmt = (
        select(NoteKp)
        .join(Note, NoteKp.note_id == Note.id)
        .where(
            NoteKp.source == "ai",
            NoteKp.confirmed.is_(False),
            NoteKp.confidence >= PENDING_THRESHOLD,
            NoteKp.confidence < AUTO_THRESHOLD,
            Note.user_id == viewer.id,
            Note.deleted_at.is_(None),
        )
    )
    if note_id is not None:
        stmt = stmt.where(NoteKp.note_id == note_id)
    stmt = stmt.order_by(NoteKp.note_id.desc(), NoteKp.kp_id)
    return paginate_query(session, stmt, params, item_model=PendingAlignOut)


def confirm_pairs(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> AlignBatchOut:
    rows = _owned_rows(session, viewer=viewer, pairs=pairs)
    confirmed = skipped = 0
    for pair in pairs:
        row = rows.get((pair.note_id, pair.kp_id))
        if row is None or row.confirmed:
            skipped += 1
            continue
        row.confirmed = True
        row.source = "manual"
        confirmed += 1
    session.commit()
    return AlignBatchOut(confirmed=confirmed, skipped=skipped)


def reject_pairs(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> AlignBatchOut:
    rows = _owned_rows(session, viewer=viewer, pairs=pairs)
    deleted = skipped = 0
    for pair in pairs:
        row = rows.get((pair.note_id, pair.kp_id))
        if row is None or row.confirmed or row.source != "ai":
            skipped += 1
            continue
        session.delete(row)
        deleted += 1
    session.commit()
    return AlignBatchOut(deleted=deleted, skipped=skipped)


def _owned_rows(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> dict[tuple[int, int], NoteKp]:
    note_ids = {pair.note_id for pair in pairs}
    if not note_ids:
        raise InvalidParamError("items 不能为空")
    stmt = (
        select(NoteKp)
        .join(Note, NoteKp.note_id == Note.id)
        .where(
            NoteKp.note_id.in_(note_ids),
            Note.user_id == viewer.id,
            Note.deleted_at.is_(None),
        )
    )
    return {(row.note_id, row.kp_id): row for row in session.scalars(stmt)}


def _note_text(note: Note) -> str:
    return f"{note.title}\n{note.content_text or ''}"


def _embedding_text(kp: KnowledgePoint, by_id: dict[int, KnowledgePoint]) -> str:
    path = " / ".join([*reversed(_ancestor_names(kp, by_id)), kp.name])
    return f"{path} {kp.description or ''}".strip()


def _ancestor_names(kp: KnowledgePoint, by_id: dict[int, KnowledgePoint]) -> list[str]:
    names: list[str] = []
    parent_id = kp.parent_id
    guard = 0
    while parent_id is not None and parent_id in by_id and guard < 10:
        parent = by_id[parent_id]
        names.append(parent.name)
        parent_id = parent.parent_id
        guard += 1
    return names


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / norm))
```

- [ ] **Step 5: 运行服务测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_service.py -q`
Expected: `8 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/note_kp.py backend/app/schemas/kp_align.py backend/app/services/kp_align_service.py backend/tests/test_align_service.py
git commit -m "feat(s2-10): 对齐服务与待确认队列"
```

---

### Task 3: 任务、接口与自动触发

**Files:**
- Create: `backend/app/tasks/kp_align.py`
- Modify: `backend/app/tasks/__init__.py`
- Modify: `backend/app/api/v1/kp.py`
- Modify: `backend/app/api/v1/notes.py`
- Modify: `backend/app/tasks/parse_document.py`
- Test: `backend/tests/test_align_task.py`
- Test: `backend/tests/test_align_api.py`

**Interfaces:**
- Consumes: `kp_align_service`、`task_service.create_task`、`TASK_KP_ALIGN`
- Produces: `kp.align` 任务与 4 个 `/kp/align` 接口；笔记/解析自动入队

- [ ] **Step 1: 写任务与接口失败测试**

`backend/tests/test_align_task.py`：

```python
"""S2-10 对齐任务 handler：不连库、不调 LLM。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.note import Note
from app.services.kp_align_service import AlignStats
from app.tasks import kp_align as task_module


class FakeSession:
    def __init__(self, note: Note | None) -> None:
        self.note = note

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        raise AssertionError(entity)


def _note(*, deleted: bool = False) -> Note:
    note = Note(
        user_id=1,
        subject_id=1,
        title="单调性",
        content_md="内容",
        content_text="内容",
        tags=None,
        folder=None,
    )
    note.id = 7
    note.deleted_at = datetime.now(timezone.utc) if deleted else None
    return note


def test_kp_align_task_returns_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        task_module, "align_note", lambda session, *, note: AlignStats(3, 2, 1, 1, 1)
    )
    result = task_module.kp_align_task(FakeSession(_note()), {"note_id": 7})  # type: ignore[arg-type]
    assert result == {
        "note_id": 7,
        "candidates": 3,
        "matched": 2,
        "auto": 1,
        "pending": 1,
        "dropped": 1,
    }


def test_kp_align_task_skips_missing_note() -> None:
    assert task_module.kp_align_task(FakeSession(None), {"note_id": 7}) == {  # type: ignore[arg-type]
        "note_id": 7,
        "skipped": True,
    }


def test_kp_align_task_skips_deleted_note() -> None:
    result = task_module.kp_align_task(FakeSession(_note(deleted=True)), {"note_id": 7})  # type: ignore[arg-type]
    assert result["skipped"] is True


def test_kp_align_task_rejects_missing_note_id() -> None:
    with pytest.raises(ValueError, match="note_id"):
        task_module.kp_align_task(FakeSession(None), {})  # type: ignore[arg-type]
```

`backend/tests/test_align_api.py`：

```python
"""S2-10 对齐接口：TestClient + FakeSession/依赖覆盖。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.note import Note
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.kp_align import AlignBatchOut, PendingAlignOut
from app.services import kp_align_service
from app.tasks.queue import get_task_queue


class FakeSession:
    def __init__(self, *, user: User | None = None, note: Note | None = None) -> None:
        self.user = user
        self.note = note
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(entity)

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        raise AssertionError(entity)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, instance: object) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 42


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    def enqueue(self, name: str, task_id: int) -> None:
        self.enqueued.append((name, task_id))


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(
        username=f"{role}_align",
        password_hash="hash",
        nickname="测试用户_1",
        grade="高一",
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _note(user_id: int = 1) -> Note:
    note = Note(
        user_id=user_id,
        subject_id=1,
        title="单调性",
        content_md="内容",
        content_text="内容",
        tags=None,
        folder=None,
    )
    note.id = 7
    note.deleted_at = None
    return note


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def test_manual_align_returns_202_task(client: TestClient) -> None:
    user = _user()
    queue = FakeQueue()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=_note())
    app.dependency_overrides[get_task_queue] = lambda: queue
    resp = client.post("/api/v1/kp/align/notes/7", headers=_headers(user))
    assert resp.status_code == 202
    assert resp.json()["data"]["name"] == "kp.align"
    assert queue.enqueued[0][0] == "kp.align"


def test_manual_align_other_note_returns_403(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=_note(user_id=2))
    resp = client.post("/api/v1/kp/align/notes/7", headers=_headers(user))
    assert resp.status_code == 403


def test_manual_align_missing_note_returns_404(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user, note=None)
    resp = client.post("/api/v1/kp/align/notes/999", headers=_headers(user))
    assert resp.status_code == 404


def test_pending_list_returns_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "list_pending",
        lambda session, *, viewer, params, note_id=None: PageData(
            items=[
                PendingAlignOut(
                    note_id=3,
                    kp_id=12,
                    confidence=0.68,
                    note_title="函数单调性笔记",
                    kp_name="函数的单调性",
                    kp_code="MATH-FUNC-02",
                )
            ],
            total=1,
            page=1,
            page_size=20,
        ),
    )
    resp = client.get("/api/v1/kp/align/pending", headers=_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["kp_code"] == "MATH-FUNC-02"


def test_pending_list_filters_note_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    captured: dict[str, object] = {}

    def fake_list(session, *, viewer, params, note_id=None):
        captured["note_id"] = note_id
        return PageData(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(kp_align_service, "list_pending", fake_list)
    resp = client.get("/api/v1/kp/align/pending?note_id=9", headers=_headers(user))
    assert resp.status_code == 200
    assert captured["note_id"] == 9


def test_confirm_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "confirm_pairs",
        lambda session, *, viewer, pairs: AlignBatchOut(confirmed=len(pairs), skipped=0),
    )
    resp = client.post(
        "/api/v1/kp/align/confirm",
        json={"items": [{"note_id": 3, "kp_id": 12}]},
        headers=_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["confirmed"] == 1


def test_reject_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    monkeypatch.setattr(
        kp_align_service,
        "reject_pairs",
        lambda session, *, viewer, pairs: AlignBatchOut(deleted=len(pairs), skipped=0),
    )
    resp = client.post(
        "/api/v1/kp/align/reject",
        json={"items": [{"note_id": 3, "kp_id": 12}]},
        headers=_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 1


def test_confirm_empty_items_returns_422(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user=user)
    resp = client.post(
        "/api/v1/kp/align/confirm", json={"items": []}, headers=_headers(user)
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_task.py tests/test_align_api.py -q`
Expected: FAIL，路由/任务不存在

- [ ] **Step 3: 实现任务**

`backend/app/tasks/kp_align.py`：

```python
"""S2-10 知识点对齐任务（同步 handler，不自行 commit）。"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.note import Note
from app.services.kp_align_service import align_note
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_KP_ALIGN = "kp.align"


@register(TASK_KP_ALIGN)
def kp_align_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = int(payload.get("note_id") or 0)
    if note_id <= 0:
        raise ValueError("payload 缺少 note_id")
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        return {"note_id": note_id, "skipped": True}
    stats = align_note(session, note=note)
    result = asdict(stats) | {"note_id": note_id}
    logger.info("kp_align_done", extra=result)
    return result
```

`backend/app/tasks/__init__.py`：

```python
from app.tasks import demo as _demo  # noqa: F401  注册 demo.sleep
from app.tasks import kp_align as _kp_align  # noqa: F401  注册 kp.align
from app.tasks import parse_document as _parse_document  # noqa: F401  注册 parse.document

__all__ = ["_demo", "_kp_align", "_parse_document"]
```

- [ ] **Step 4: 实现接口**

在 `backend/app/api/v1/kp.py` 末尾追加：

```python
from app.schemas.kp_align import AlignBatchIn, AlignBatchOut, PendingAlignOut
from app.schemas.tasks import TaskOut
from app.services import kp_align_service, task_service
from app.services.kp_align_service import AlignPair
from app.tasks.kp_align import TASK_KP_ALIGN
from app.tasks.queue import TaskQueue, get_task_queue
from app.utils.pagination import PageParams, page_params


@router.post(
    "/align/notes/{note_id}",
    status_code=202,
    response_model=Envelope[TaskOut],
    summary="手动重跑笔记对齐",
)
def align_note_endpoint(
    note_id: int,
    current_user: User = Depends(require_role("student")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        raise NotFoundError("笔记不存在")
    if note.user_id != current_user.id:
        raise ForbiddenError("无权访问该资源")
    task = task_service.create_task(
        session,
        owner=current_user,
        name=TASK_KP_ALIGN,
        payload={"note_id": note_id},
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get(
    "/align/pending",
    response_model=Envelope[PageData[PendingAlignOut]],
    summary="待确认队列",
)
def list_pending(
    note_id: int | None = Query(None, ge=1),
    params: PageParams = Depends(page_params),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[PageData[PendingAlignOut]]:
    page = kp_align_service.list_pending(
        session, viewer=current_user, params=params, note_id=note_id
    )
    return Envelope(trace_id=get_trace_id(), data=page)


@router.post(
    "/align/confirm", response_model=Envelope[AlignBatchOut], summary="批量确认对齐"
)
def confirm_align(
    payload: AlignBatchIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[AlignBatchOut]:
    result = kp_align_service.confirm_pairs(
        session,
        viewer=current_user,
        pairs=[AlignPair(**item.model_dump()) for item in payload.items],
    )
    return Envelope(trace_id=get_trace_id(), data=result)


@router.post(
    "/align/reject", response_model=Envelope[AlignBatchOut], summary="批量忽略对齐"
)
def reject_align(
    payload: AlignBatchIn,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[AlignBatchOut]:
    result = kp_align_service.reject_pairs(
        session,
        viewer=current_user,
        pairs=[AlignPair(**item.model_dump()) for item in payload.items],
    )
    return Envelope(trace_id=get_trace_id(), data=result)
```

并补 import：

```python
from app.models.note import Note
from app.schemas.common import PageData
from app.core.exceptions import ForbiddenError, NotFoundError
```

- [ ] **Step 5: 笔记自动入队**

`backend/app/api/v1/notes.py`：在文件顶部补：

```python
import logging

from app.core.exceptions import TaskQueueUnavailableError
from app.services import task_service
from app.tasks.kp_align import TASK_KP_ALIGN
from app.tasks.queue import TaskQueue, get_task_queue

logger = logging.getLogger(__name__)


def _enqueue_align(session, *, user: User, note_id: int, queue: TaskQueue) -> None:
    try:
        task_service.create_task(
            session,
            owner=user,
            name=TASK_KP_ALIGN,
            payload={"note_id": note_id},
            queue=queue,
        )
    except TaskQueueUnavailableError as exc:
        logger.warning("kp_align_enqueue_failed", extra={"note_id": note_id, "error": str(exc)})
```

`create_note` 路由签名加 `queue: TaskQueue = Depends(get_task_queue)`，在 service 返回后调用 `_enqueue_align(session, user=current_user, note_id=note.id, queue=queue)`；`update_note` 路由同样加 queue 与调用。

- [ ] **Step 6: 解析完成自动入队**

`backend/app/tasks/parse_document.py` 在成功分支 `session.commit()` 与 `logger.info` 之后调用：

```python
        _enqueue_align(file)
```

并在文件末尾追加：

```python
def _enqueue_align(file: File) -> None:
    """解析成功后入队对齐；独立 session，避免把任务提交混进 handler 主事务。"""
    from app.core.db import get_session_factory
    from app.models.user import User
    from app.services import task_service
    from app.tasks.kp_align import TASK_KP_ALIGN
    from app.tasks.queue import get_task_queue

    session = get_session_factory()()
    try:
        user = session.get(User, file.user_id)
        note = session.scalar(
            select(Note).where(
                Note.user_id == file.user_id, Note.source_file_id == file.id
            )
        )
        if user is None or note is None:
            return
        task_service.create_task(
            session,
            owner=user,
            name=TASK_KP_ALIGN,
            payload={"note_id": note.id},
            queue=get_task_queue(),
        )
    except Exception as exc:  # noqa: BLE001 —— 对齐是增强能力，不能影响解析结果
        logger.warning(
            "kp_align_enqueue_failed", extra={"file_id": file.id, "error": str(exc)}
        )
    finally:
        session.close()
```

- [ ] **Step 7: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_align_task.py tests/test_align_api.py -q`
Expected: `12 passed`

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `500 passed, 1 warning`

- [ ] **Step 8: 提交**

```bash
git add backend/app/tasks/kp_align.py backend/app/tasks/__init__.py backend/app/api/v1/kp.py backend/app/api/v1/notes.py backend/app/tasks/parse_document.py backend/tests/test_align_task.py backend/tests/test_align_api.py
git commit -m "feat(s2-10): 对齐任务、队列接口与自动触发"
```

---

### Task 4: 30 条验收笔记与真实链路验收

**Files:**
- Create: `backend/data/align_demo_notes.json`

- [ ] **Step 1: 生成验收笔记**

`backend/data/align_demo_notes.json` 结构按 spec §8；30 条，`expected_codes` 为人工判定可接受节点（验收统计用）。覆盖：

| key | 主题 | expected_codes |
|---|---|---|
| set-ops | 集合运算 | MATH-SET-03 |
| logic-cond | 充分必要条件 | MATH-SET-04 |
| ineq-basic | 基本不等式 | MATH-QUAD-02 |
| func-domain | 定义域值域 | MATH-FUNC-01-01 |
| func-monotonic | 单调性 | MATH-FUNC-02 |
| func-parity | 奇偶性 | MATH-FUNC-03 |
| exp-log | 指数对数 | MATH-FUNC-06, MATH-FUNC-07 |
| trig-identity | 三角恒等变换 | MATH-TRIG-04 |
| trig-graph | 三角函数图象 | MATH-TRIG-05 |
| solve-triangle | 解三角形 | MATH-TRIG-07 |
| vector-dot | 向量数量积 | MATH-VEC-03 |
| complex | 复数运算 | MATH-VEC-05 |
| seq-ap | 等差数列 | MATH-SEQ-02 |
| seq-gp | 等比数列 | MATH-SEQ-03 |
| seq-sum | 数列求和 | MATH-SEQ-04 |
| solid-parallel | 线面平行 | MATH-GEO-03 |
| solid-perp | 线面垂直 | MATH-GEO-04 |
| solid-angle | 空间角 | MATH-GEO-06 |
| line-circle | 直线与圆 | MATH-ANA-01, MATH-ANA-02 |
| ellipse | 椭圆 | MATH-ANA-03 |
| hyperbola | 双曲线 | MATH-ANA-04 |
| parabola | 抛物线 | MATH-ANA-05 |
| deriv-basic | 导数运算 | MATH-DER-01 |
| deriv-monotonic | 导数与单调性 | MATH-DER-02 |
| deriv-extreme | 极值最值 | MATH-DER-03 |
| prob-classic | 古典概型 | MATH-PROB-02 |
| prob-conditional | 条件概率 | MATH-PROB-03 |
| random-variable | 随机变量分布 | MATH-PROB-04 |
| regression | 回归分析 | MATH-PROB-07 |
| binomial | 二项式定理 | MATH-COUNT-03 |

每条 `content_md` 80–250 字，含主题词与一个具体例子/公式；不得出现其他主题的强干扰词（验收要可判定）。

- [ ] **Step 2: 静态校验**

Run:

```bash
cd backend && ../.venv/Scripts/python.exe - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("data/align_demo_notes.json").read_text(encoding="utf-8"))
notes = data["notes"]
assert len(notes) == 30, len(notes)
keys = {n["key"] for n in notes}
assert len(keys) == 30
assert all(n["content_md"].strip() for n in notes)
print("notes", len(notes))
PY
```

Expected：`notes 30`

- [ ] **Step 3: 起服务与 Worker**

```bash
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
cd backend && ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
```

- [ ] **Step 4: 真实对齐 30 条**

注册/登录 student，逐条 POST /notes（body：title/content_md），记录 note_id；轮询 async_tasks 直到全部终态：

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select status, count(*) from async_tasks where name='kp.align' group by status;"
```

校验：`succeeded=30`、`failed=0`；`note_kps` 行数、auto/pending 分布：

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select source, confirmed, count(*) from note_kps group by source, confirmed;"
```

- [ ] **Step 5: 人工准确率**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "select n.title, k.code, k.name, nk.confidence from note_kps nk join notes n on n.id=nk.note_id join knowledge_points k on k.id=nk.kp_id where nk.source='ai' and nk.confirmed order by n.id;"
```

逐条对照 `expected_codes`（或人工判断主题是否匹配），统计自动关联准确率；把数字与错误清单写进执行记录。目标 ≥80%。

- [ ] **Step 6: 队列批量操作**

取 3 条待确认 → `POST /kp/align/confirm`；取 2 条 → `POST /kp/align/reject`；psql 校验 confirmed/source 与删除行数。

- [ ] **Step 7: 手动重跑**

对一条已有 manual 行的笔记 `POST /kp/align/notes/{id}`，等待任务成功；确认 ai 行被替换、manual 行仍在。

- [ ] **Step 8: 清理与回归**

```bash
docker exec study-agent-postgres psql -U study -d study_agent -c \
 "delete from note_kps; delete from notes; delete from async_tasks; delete from users where username like 'align\\_%';"
cd backend && ../.venv/Scripts/python.exe -m pytest -q
```

Expected：knowledge_points/subjects 保持 108/1；pytest `500 passed, 1 warning`。

- [ ] **Step 9: 提交**

```bash
git add backend/data/align_demo_notes.json
git commit -m "feat(s2-10): 30 条对齐验收笔记"
```

---

### Task 5: 文档同步

**Files:** `docs/API.md`、`docs/SCHEMA.md`、`AGENTS.md`、`docs/DECISIONS.md`、`docs/PROGRESS.md`、`docs/AI协作开发实施计划.md`、spec/plan

- [ ] **Step 1: API.md §4** 补 4 个接口（权限/入参/出参/错误码）。
- [ ] **Step 2: SCHEMA.md §4.4** 注记自动/待确认/手工三种行语义与重跑规则。
- [ ] **Step 3: AGENTS.md** §9.2 对齐规则、§9.3 LLM 抽取约束、§9.6 对齐锚点。
- [ ] **Step 4: DECISIONS D-030** 决策、真实验收数字、准确率、已知不足。
- [ ] **Step 5: PROGRESS** 状态、S2-10 勾选、遗留（无时间列/无审计/LLM 依赖/阈值未跨模型校准）、日志。
- [ ] **Step 6: spec/plan 执行记录**（commit、pytest、30 条任务结果、准确率、偏差）。
- [ ] **Step 7: 提交** `docs(s2-10)`。

---

## Self-Review

- 覆盖 spec：打分/抽取（Task 1）、服务/队列（Task 2）、任务/接口/自动触发（Task 3）、验收（Task 4）、文档（Task 5）。
- 类型一致：`Candidate`、`AlignStats`、`AlignPair`、`AlignBatchOut`、`PendingAlignOut` 跨任务一致。
- 测试数：10+8（Task1）+ 8（Task2）+ 4+8（Task3）= 38 → 全量 462 + 38 = 500。
- 风险：`paginate_query` + `AliasPath` 依赖 Pydantic v2 的 from_attributes 别名解析；若失败，Task 2 可改为返回 `(NoteKp, Note, KnowledgePoint)` 元组并在 service 手工组 `PageData`（不改接口）。
- 风险：`NoteKp` 加 `lazy="joined"` 后 `select(NoteKp).join(Note)` 可能产生重复 join；执行时若 SQL 报错，改用 `selectinload`。

---

## 执行记录（2026-10-27）

- 按 Task 1–5 顺序实施；commit：`2a0f4eb`（打分/抽取）、`42aa7cd`（服务/队列）、`13a3510`（任务/接口/自动触发）、`2fb9dd1`（重跑保留 manual 修复）、`eb751f5`（30 条验收笔记）、`docs(s2-10)`（文档）。
- 测试：新增 38 条，全量 **500 passed, 1 warning**。
- 真实验收（DashScope Embedding text-embedding-v4 + qwen-plus + Postgres + Redis + ARQ）：
  - 30 条笔记创建成功，30 个 `kp.align` 任务 `succeeded=30 / failed=0`；`knowledge_points.embedding` 108/108 补齐。
  - `note_kps` 36 行：自动 28、待确认 8；逐条人工核对 28 条自动关联全部正确 → 精确率 100%，覆盖 25/30 条笔记。
  - 5 条未关联（集合运算/复数/直线与圆/抛物线/导数与单调性）LLM 各命中 1 个候选，但最终分 <0.55 被丢弃（`matched=1, dropped=10`），记入已知不足。
  - 待确认列表 8 条；批量确认 3 条（note 15/17/19）→ `manual+confirmed=3`；批量忽略 2 条（note 20/26）→ 删除成功，剩余 3 条。
  - 手动重跑 note 15：任务成功（`auto=1, matched=2, dropped=9`），manual 行保留、ai 行替换。
- 偏差：Task 2 计划中“`retrieve_candidates` 由 SQL 直接返回 cos”改为「SQL 取同 subject 全量后按 embedding 在内存算余弦并排序」——FakeSession 下可测、108 节点规模足够；仍走 pgvector 列与索引，未手写 SQL 距离。其余按 plan。
- 实测抓修：重跑时未排除 manual 导致 pkey 冲突（note 15）→ 候选命中 manual 即跳过，补单测。
- 清理：notes/note_kps/async_tasks/users 清零，保留 subjects 1 + knowledge_points 108 + 已补齐 embedding。
