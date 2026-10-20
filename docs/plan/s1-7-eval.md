# S1-7 自测用例与效果抽查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 30 条人工标注 gold 的问答集，跑出纯向量 / 混合 / 混合+Rerank 的 hit@5、MRR、引用正确率、拒答准确率、延迟与 token 成本，并留下可复现的 JSON/Markdown 证据。

**Architecture:** `eval/qa_eval.py` 只做数据校验、指标与聚合（纯函数，不碰 DB/网络）；`eval/run.py` 负责读库、调检索/回答、落盘。三配置只影响检索；回答指标只在生产配置 `hybrid_rerank` 上跑，避免无意义的三次 LLM 调用。

**Tech Stack:** Python 3.11、Pydantic v2、SQLAlchemy 2、现有 `retrieve_hybrid()` / `retrieve_hybrid_reranked()` / `answer_question()`；不引入新依赖。

**Spec:** `docs/spec/s1-7-eval.md`

## Global Constraints

- 一次任务卡只做**一个** Conventional Commit；用户负责 `git push`。
- `gold_chunk_ids` 必须由用户人工勾选；实现者不生成、不猜、不按排名反推。
- 数据集固定 **30 条 = 20 应答题 + 10 应拒题**；`should_refuse=true` 的 gold 必须为空。
- 三种检索配置：`vector` / `hybrid` / `hybrid_rerank`；`top_n` 固定 5。
- 回答/引用/拒答指标只在 `hybrid_rerank` 上计算；vector/hybrid 的 answer 字段写 `null`。
- 测试禁止真实 DB/网络；真实验收单独跑 CLI。
- JSON/结果不写 chunk 正文、Prompt、Key、真实校名/姓名。
- 纯向量延迟复用同一次混合检索调用，论文中必须注明是保守口径。
- 验收线：`hybrid_rerank` 的 `hit@5 >= 0.6`；不达标如实报告，不调问题粉饰。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `eval/__init__.py` | 让 `eval` 可被测试 import |
| `eval/qa_eval.py` | Pydantic 数据模型、JSONL/配置加载、gold 校验、指标与聚合 |
| `eval/run.py` | CLI 编排：DB 查询、三配置路由、调用 answerer、JSON/Markdown 落盘 |
| `eval/configs/vector.json` | 纯向量配置 |
| `eval/configs/hybrid.json` | RRF 混合配置 |
| `eval/configs/hybrid_rerank.json` | 混合 + qwen3-rerank 配置 |
| `eval/datasets/qa_set.candidates.md` | 候选块清单（未标注，给用户勾 gold） |
| `eval/datasets/qa_set.jsonl` | 用户确认 gold 后的 30 条数据集 |
| `eval/results/s1-7-*.json` | 真实结果（脚本生成） |
| `eval/results/s1-7-*.md` | 真实结果表格（脚本生成） |
| `docs/EVAL_S1.md` | 评测方法、真实数字、失败题、局限 |
| `backend/tests/test_eval_dataset.py` | 数据集/配置校验测试 |
| `backend/tests/test_eval_metrics.py` | 指标纯函数测试 |
| `backend/tests/test_eval_run.py` | 配置路由/渲染/CLI 冒烟测试 |

---

## Task 1: eval 包、数据模型与校验

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/qa_eval.py`
- Create: `backend/tests/test_eval_dataset.py`
- Create: `eval/configs/vector.json`
- Create: `eval/configs/hybrid.json`
- Create: `eval/configs/hybrid_rerank.json`

**Interfaces:**
- Produces:
  - `QACase`
  - `RetrievalConfig`
  - `DatasetError`, `EvalConfigError`
  - `load_dataset(path, *, min_items=20, max_items=30) -> list[QACase]`
  - `load_config(path) -> RetrievalConfig`
  - `validate_gold_chunks(cases: list[QACase], chunk_note_ids: dict[int, int]) -> None`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_eval_dataset.py`：

```python
"""S1-7 数据集与配置校验；不连 DB、不调网络。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import (  # noqa: E402
    DatasetError,
    EvalConfigError,
    QACase,
    load_config,
    load_dataset,
    validate_gold_chunks,
)


def _case(index: int, *, refuse: bool = False) -> dict:
    return {
        "id": f"q{index:03d}",
        "question": f"问题 {index}",
        "scope": "函数",
        "gold_chunk_ids": [] if refuse else [index],
        "should_refuse": refuse,
    }


def _write_cases(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "qa_set.jsonl"
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in cases) + "\n",
        encoding="utf-8",
    )
    return path


def _valid_cases() -> list[dict]:
    return [_case(i) for i in range(1, 21)] + [
        _case(i, refuse=True) for i in range(21, 31)
    ]


def test_load_dataset_accepts_30_cases(tmp_path) -> None:
    cases = load_dataset(_write_cases(tmp_path, _valid_cases()))
    assert len(cases) == 30
    assert cases[0].id == "q001"
    assert cases[-1].should_refuse is True


def test_load_dataset_rejects_too_few(tmp_path) -> None:
    with pytest.raises(DatasetError, match="20"):
        load_dataset(_write_cases(tmp_path, _valid_cases()[:19]))


def test_load_dataset_rejects_too_many(tmp_path) -> None:
    cases = _valid_cases() + [_case(31)]
    with pytest.raises(DatasetError, match="30"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_duplicate_id(tmp_path) -> None:
    cases = _valid_cases()
    cases[1]["id"] = cases[0]["id"]
    with pytest.raises(DatasetError, match="重复"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_missing_field(tmp_path) -> None:
    cases = _valid_cases()
    del cases[0]["scope"]
    with pytest.raises(DatasetError, match="scope"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_bad_json_line(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(_case(1), ensure_ascii=False) + "\nnot-json\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match="2"):
        load_dataset(path)


def test_load_dataset_rejects_answerable_without_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[0]["gold_chunk_ids"] = []
    with pytest.raises(DatasetError, match="gold"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_refusal_with_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[20]["gold_chunk_ids"] = [1]
    with pytest.raises(DatasetError, match="gold"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_duplicate_or_nonpositive_gold(tmp_path) -> None:
    cases = _valid_cases()
    cases[0]["gold_chunk_ids"] = [1, 1]
    with pytest.raises(DatasetError, match="重复"):
        load_dataset(_write_cases(tmp_path, cases))
    cases[0]["gold_chunk_ids"] = [0]
    with pytest.raises(DatasetError, match="正整数"):
        load_dataset(_write_cases(tmp_path, cases))


def test_load_dataset_rejects_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(path)


def test_load_config_accepts_three_configs() -> None:
    for name in ("vector", "hybrid", "hybrid_rerank"):
        cfg = load_config(ROOT / "eval" / "configs" / f"{name}.json")
        assert cfg.name == name
        assert cfg.top_n == 5


def test_load_config_rejects_top_n_not_5(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {"name": "vector", "retrieval": "vector", "top_k": 20, "top_n": 4}
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError, match="top_n"):
        load_config(path)


def test_load_config_rejects_invalid_retrieval(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {"name": "x", "retrieval": "magic", "top_k": 20, "top_n": 5}
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError):
        load_config(path)


def test_load_config_rejects_rerank_top_k_below_top_n(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "name": "hybrid_rerank",
                "retrieval": "hybrid_rerank",
                "top_k": 20,
                "top_n": 5,
                "rerank_candidates": 30,
                "rerank_top_k": 4,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError, match="rerank_top_k"):
        load_config(path)


def test_validate_gold_chunks_rejects_missing() -> None:
    cases = [QACase(**_case(1))]
    with pytest.raises(DatasetError, match="不存在"):
        validate_gold_chunks(cases, {2: 102})


def test_validate_gold_chunks_accepts_present() -> None:
    cases = [QACase(**_case(1))]
    validate_gold_chunks(cases, {1: 102})
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_dataset.py -q
```

Expected: collection error `No module named 'eval'` / `cannot import name 'QACase'`.

- [ ] **Step 3: 写最小实现**

`eval/__init__.py`：

```python
"""S1-7 评测包。"""
```

`eval/qa_eval.py`：

```python
"""S1-7 数据模型、校验与指标纯函数；本文件不连 DB、不调外部 API。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class DatasetError(ValueError):
    """数据集格式/条数/gold 引用错误。"""


class EvalConfigError(ValueError):
    """评测配置错误。"""


class QACase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    question: str
    scope: str
    gold_chunk_ids: list[int] = Field(default_factory=list)
    should_refuse: bool

    @field_validator("id", "question", "scope")
    @classmethod
    def _non_empty(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} 不能为空")
        return value

    @field_validator("gold_chunk_ids")
    @classmethod
    def _gold_ids(cls, value: list[int]) -> list[int]:
        for item in value:
            if item <= 0:
                raise ValueError("gold_chunk_ids 必须是正整数")
        if len(set(value)) != len(value):
            raise ValueError("gold_chunk_ids 不能重复")
        return value

    @model_validator(mode="after")
    def _gold_matches_refusal(self) -> "QACase":
        if self.should_refuse and self.gold_chunk_ids:
            raise ValueError("应拒题的 gold_chunk_ids 必须为空")
        if not self.should_refuse and not self.gold_chunk_ids:
            raise ValueError("应答题的 gold_chunk_ids 不能为空")
        return self


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Literal["vector", "hybrid", "hybrid_rerank"]
    retrieval: Literal["vector", "hybrid", "hybrid_rerank"]
    top_k: int = 20
    top_n: int = 5
    rerank_candidates: int = 30
    rerank_top_k: int = 6

    @model_validator(mode="after")
    def _valid(self) -> "RetrievalConfig":
        if self.name != self.retrieval:
            raise ValueError("name 与 retrieval 必须一致")
        if self.top_k <= 0:
            raise ValueError("top_k 必须为正整数")
        if self.top_n != 5:
            raise ValueError("S1-7 固定 top_n=5")
        if self.retrieval == "hybrid_rerank":
            if self.rerank_candidates <= 0:
                raise ValueError("rerank_candidates 必须为正整数")
            if self.rerank_top_k < self.top_n:
                raise ValueError("rerank_top_k 不能小于 top_n")
        return self


def load_dataset(
    path: str | Path,
    *,
    min_items: int = 20,
    max_items: int = 30,
) -> list[QACase]:
    source = Path(path)
    if not source.is_file():
        raise DatasetError(f"数据集不存在：{source}")
    cases: list[QACase] = []
    seen: set[str] = set()
    with source.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                raise DatasetError(f"{source}:{line_no}: 空行")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{source}:{line_no}: JSON 解析失败") from exc
            if not isinstance(payload, dict):
                raise DatasetError(f"{source}:{line_no}: 每行必须是 JSON 对象")
            try:
                case = QACase.model_validate(payload)
            except ValidationError as exc:
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first.get("loc", ()))
                raise DatasetError(
                    f"{source}:{line_no}: {location}: {first.get('msg', '字段非法')}"
                ) from exc
            if case.id in seen:
                raise DatasetError(f"{source}:{line_no}: id 重复：{case.id}")
            seen.add(case.id)
            cases.append(case)
    if not min_items <= len(cases) <= max_items:
        raise DatasetError(
            f"数据集条数必须在 {min_items}–{max_items} 之间，实际 {len(cases)}"
        )
    return cases


def load_config(path: str | Path) -> RetrievalConfig:
    source = Path(path)
    if not source.is_file():
        raise EvalConfigError(f"配置不存在：{source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalConfigError(f"{source}: JSON 解析失败") from exc
    if not isinstance(payload, dict):
        raise EvalConfigError(f"{source}: 配置必须是 JSON 对象")
    try:
        return RetrievalConfig.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise EvalConfigError(f"{source}: {first.get('msg', '字段非法')}") from exc


def validate_gold_chunks(
    cases: list[QACase],
    chunk_note_ids: dict[int, int],
) -> None:
    all_gold = {chunk_id for case in cases for chunk_id in case.gold_chunk_ids}
    missing = sorted(all_gold - set(chunk_note_ids))
    if missing:
        raise DatasetError(
            "以下 gold_chunk_ids 不存在或不属于当前用户："
            + ", ".join(str(item) for item in missing)
        )
```

三份配置：

`eval/configs/vector.json`：

```json
{
  "name": "vector",
  "retrieval": "vector",
  "top_k": 20,
  "top_n": 5
}
```

`eval/configs/hybrid.json`：

```json
{
  "name": "hybrid",
  "retrieval": "hybrid",
  "top_k": 20,
  "top_n": 5
}
```

`eval/configs/hybrid_rerank.json`：

```json
{
  "name": "hybrid_rerank",
  "retrieval": "hybrid_rerank",
  "top_k": 20,
  "top_n": 5,
  "rerank_candidates": 30,
  "rerank_top_k": 6
}
```

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_dataset.py -q
```

Expected: `all passed`（约 15 条）。

---

## Task 2: 指标与聚合

**Files:**
- Modify: `eval/qa_eval.py`
- Create: `backend/tests/test_eval_metrics.py`

**Interfaces:**
- Produces:
  - `ChunkLike` Protocol
  - `CaseRetrieval`, `CaseAnswer`
  - `RetrievalSummary`, `AnswerSummary`
  - `first_gold_rank(hits, gold_ids, k=5) -> int | None`
  - `hit_at_k(hits, gold_ids, k=5) -> bool`
  - `citation_precision(cited_ids, gold_ids) -> float`
  - `citation_hit(cited_ids, gold_ids) -> bool`
  - `refusal_confusion(cases, refused_by_id) -> dict[str, int]`
  - `summarize_retrieval(cases, records) -> RetrievalSummary`
  - `summarize_answer(cases, records, *, llm_calls, citation_retry_count) -> AnswerSummary`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_eval_metrics.py`：

```python
"""S1-7 指标纯函数。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import (  # noqa: E402
    AnswerSummary,
    CaseAnswer,
    CaseRetrieval,
    QACase,
    RetrievalSummary,
    citation_hit,
    citation_precision,
    first_gold_rank,
    hit_at_k,
    refusal_confusion,
    summarize_answer,
    summarize_retrieval,
)


@dataclass
class FakeHit:
    chunk_id: int


def _case(index: int, *, refuse: bool = False) -> QACase:
    return QACase(
        id=f"q{index:03d}",
        question=f"问题 {index}",
        scope="函数",
        gold_chunk_ids=[] if refuse else [index],
        should_refuse=refuse,
    )


def test_hit_at_5_true_false_and_empty() -> None:
    gold = {7}
    assert hit_at_k([FakeHit(1), FakeHit(7)], gold) is True
    assert hit_at_k([FakeHit(1), FakeHit(2)], gold) is False
    assert hit_at_k([], gold) is False


def test_first_gold_rank_returns_first_or_none() -> None:
    assert first_gold_rank([FakeHit(1), FakeHit(2), FakeHit(7)], {7}) == 3
    assert first_gold_rank([FakeHit(1)], {7}) is None
    assert first_gold_rank([FakeHit(1), FakeHit(2), FakeHit(3)], {1}, k=1) == 1


def test_first_gold_rank_rejects_bad_k() -> None:
    with pytest.raises(ValueError):
        first_gold_rank([], {1}, k=0)


def test_citation_precision_all_partial_zero() -> None:
    assert citation_precision([1, 2], {1, 2}) == 1.0
    assert citation_precision([1, 3], {1, 2}) == 0.5
    assert citation_precision([], {1}) == 0.0
    assert citation_precision([3], {1}) == 0.0


def test_citation_hit() -> None:
    assert citation_hit([1], {1, 2}) is True
    assert citation_hit([3], {1, 2}) is False
    assert citation_hit([], {1}) is False


def test_refusal_confusion_counts() -> None:
    cases = [_case(1), _case(2, refuse=True), _case(3, refuse=True), _case(4)]
    confused = refusal_confusion(
        cases,
        {"q001": False, "q002": True, "q003": False, "q004": True},
    )
    assert confused == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}


def test_summarize_retrieval_excludes_refusal_denominator() -> None:
    cases = [_case(1), _case(2), _case(3, refuse=True)]
    records = [
        CaseRetrieval("q001", True, 1, 100),
        CaseRetrieval("q002", False, None, 300),
        CaseRetrieval("q003", False, None, 200),
    ]
    summary = summarize_retrieval(cases, records)
    assert isinstance(summary, RetrievalSummary)
    assert summary.hit_at_5 == 0.5
    assert summary.mrr_at_5 == 0.5
    assert summary.avg_latency_ms == 200.0


def test_summarize_answer_metrics_and_refusals() -> None:
    cases = [_case(1), _case(2), _case(3, refuse=True)]
    records = [
        CaseAnswer("q001", False, None, [1], 1.0, True, 100, 1000, 0.01),
        CaseAnswer("q002", True, "low_score", [], None, None, 0, 50, 0.0),
        CaseAnswer("q003", True, "low_score", [], None, None, 0, 50, 0.0),
    ]
    summary = summarize_answer(
        cases, records, llm_calls=1, citation_retry_count=0
    )
    assert isinstance(summary, AnswerSummary)
    assert summary.citation_precision == 0.5
    assert summary.citation_hit_rate == 0.5
    assert summary.refusal_accuracy == pytest.approx(2 / 3)
    assert summary.confusion == {"tp": 1, "fp": 1, "fn": 0, "tn": 1}
    assert summary.avg_total_tokens == pytest.approx(33.3333, rel=1e-3)
    assert summary.avg_latency_ms == pytest.approx(366.6667, rel=1e-3)
    assert summary.answered_count == 1
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_metrics.py -q
```

Expected: import error for `first_gold_rank` / `CaseRetrieval`.

- [ ] **Step 3: 追加实现（放在 `load_config` 之后）**

```python
class ChunkLike(Protocol):
    chunk_id: int


@dataclass(frozen=True)
class CaseRetrieval:
    case_id: str
    hit_at_5: bool
    first_gold_rank: int | None
    latency_ms: int


@dataclass(frozen=True)
class CaseAnswer:
    case_id: str
    refused: bool
    refusal_reason: str | None
    cited_chunk_ids: list[int]
    citation_precision: float | None
    citation_hit: bool | None
    total_tokens: int
    latency_ms: int
    cost_yuan: float


@dataclass(frozen=True)
class RetrievalSummary:
    hit_at_5: float
    mrr_at_5: float
    avg_latency_ms: float


@dataclass(frozen=True)
class AnswerSummary:
    citation_precision: float
    citation_hit_rate: float
    refusal_accuracy: float
    confusion: dict[str, int]
    avg_total_tokens: float
    avg_latency_ms: float
    total_cost_yuan: float
    llm_calls: int
    citation_retry_count: int
    answered_count: int


def _rank_or_none(
    hits: Sequence[ChunkLike],
    gold_ids: set[int],
    *,
    k: int,
) -> int | None:
    for rank, hit in enumerate(hits[:k], start=1):
        if hit.chunk_id in gold_ids:
            return rank
    return None


def first_gold_rank(
    hits: Sequence[ChunkLike],
    gold_ids: set[int],
    *,
    k: int = 5,
) -> int | None:
    if k <= 0:
        raise ValueError("k 必须为正整数")
    return _rank_or_none(hits, gold_ids, k=k)


def hit_at_k(
    hits: Sequence[ChunkLike],
    gold_ids: set[int],
    *,
    k: int = 5,
) -> bool:
    return first_gold_rank(hits, gold_ids, k=k) is not None


def citation_precision(cited_ids: Sequence[int], gold_ids: set[int]) -> float:
    unique = list(dict.fromkeys(cited_ids))
    if not unique:
        return 0.0
    return sum(1 for item in unique if item in gold_ids) / len(unique)


def citation_hit(cited_ids: Sequence[int], gold_ids: set[int]) -> bool:
    return any(item in gold_ids for item in set(cited_ids))


def refusal_confusion(
    cases: Sequence[QACase],
    refused_by_id: dict[str, bool],
) -> dict[str, int]:
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for case in cases:
        if case.id not in refused_by_id:
            raise DatasetError(f"缺少 {case.id} 的拒答结果")
        refused = refused_by_id[case.id]
        if case.should_refuse and refused:
            counts["tp"] += 1
        elif case.should_refuse and not refused:
            counts["fn"] += 1
        elif not case.should_refuse and refused:
            counts["fp"] += 1
        else:
            counts["tn"] += 1
    return counts


def _records_by_id(records: Sequence[CaseRetrieval | CaseAnswer]) -> dict[str, object]:
    return {record.case_id: record for record in records}


def summarize_retrieval(
    cases: Sequence[QACase],
    records: Sequence[CaseRetrieval],
) -> RetrievalSummary:
    answerable = [case for case in cases if not case.should_refuse]
    if not answerable:
        raise ValueError("没有应答题，无法计算 hit@5")
    by_id = _records_by_id(records)
    ranks: list[int | None] = []
    for case in answerable:
        record = by_id.get(case.id)
        if not isinstance(record, CaseRetrieval):
            raise DatasetError(f"缺少 {case.id} 的检索结果")
        ranks.append(record.first_gold_rank)
    hit_count = sum(1 for rank in ranks if rank is not None)
    mrr = sum(1 / rank for rank in ranks if rank is not None) / len(ranks)
    latencies = [record.latency_ms for record in records]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    return RetrievalSummary(
        hit_at_5=hit_count / len(ranks),
        mrr_at_5=mrr,
        avg_latency_ms=avg_latency,
    )


def summarize_answer(
    cases: Sequence[QACase],
    records: Sequence[CaseAnswer],
    *,
    llm_calls: int,
    citation_retry_count: int,
) -> AnswerSummary:
    answerable = [case for case in cases if not case.should_refuse]
    if not answerable:
        raise ValueError("没有应答题，无法计算引用指标")
    by_id = _records_by_id(records)
    precision_sum = 0.0
    citation_hits = 0
    for case in answerable:
        record = by_id.get(case.id)
        if not isinstance(record, CaseAnswer):
            raise DatasetError(f"缺少 {case.id} 的回答结果")
        precision_sum += record.citation_precision or 0.0
        citation_hits += int(record.citation_hit is True)
    refused_by_id = {record.case_id: record.refused for record in records}
    confusion = refusal_confusion(cases, refused_by_id)
    total = len(cases)
    return AnswerSummary(
        citation_precision=precision_sum / len(answerable),
        citation_hit_rate=citation_hits / len(answerable),
        refusal_accuracy=(confusion["tp"] + confusion["tn"]) / total,
        confusion=confusion,
        avg_total_tokens=sum(record.total_tokens for record in records) / total,
        avg_latency_ms=sum(record.latency_ms for record in records) / total,
        total_cost_yuan=sum(record.cost_yuan for record in records),
        llm_calls=llm_calls,
        citation_retry_count=citation_retry_count,
        answered_count=sum(1 for record in records if not record.refused),
    )
```

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_metrics.py -q
```

Expected: `all passed`（约 9 条）。

---

## Task 3: 运行器与落盘

**Files:**
- Create: `eval/run.py`
- Create: `backend/tests/test_eval_run.py`

**Interfaces:**
- Consumes: `load_dataset`, `load_config`, `validate_gold_chunks`, `CaseRetrieval`, `CaseAnswer`, summaries.
- Produces:
  - `_resolve_dataset(value: str) -> Path`
  - `_resolve_config(value: str) -> Path`
  - `_retrieve(session, question, cfg, *, user_id, embedding_client, rerank_client) -> tuple[list[RetrievedChunk], int]`
  - `_render_summary_markdown(payload: dict) -> str`
  - `main() -> int`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_eval_run.py`：

```python
"""S1-7 运行器：只测路由/渲染/CLI 冒烟，不连 DB、不调外部。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.qa_eval import RetrievalConfig, load_config  # noqa: E402
from eval import run  # noqa: E402


class FakeEmbedding:
    pass


class FakeRerank:
    model = "fake-rerank"


def _result(*, vector=None, fused=None, reranked=None, elapsed=10, rerank_ms=5):
    return SimpleNamespace(
        vector=vector or [],
        fused=fused or [],
        reranked=reranked or [],
        elapsed_ms=elapsed,
        rerank_info=SimpleNamespace(latency_ms=rerank_ms),
    )


def test_resolve_dataset_and_config() -> None:
    assert run._resolve_dataset("qa_set").name == "qa_set.jsonl"
    assert run._resolve_config("hybrid_rerank").name == "hybrid_rerank.json"


def test_retrieve_vector_uses_vector_list(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "vector.json")
    calls = []

    def fake_retrieve(session, question, **kwargs):
        calls.append(kwargs)
        return _result(vector=[SimpleNamespace(chunk_id=1)], fused=[SimpleNamespace(chunk_id=2)])

    monkeypatch.setattr(run, "retrieve_hybrid", fake_retrieve)
    hits, latency = run._retrieve(
        object(), "q", cfg, user_id=1,
        embedding_client=FakeEmbedding(), rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [1]
    assert latency == 10
    assert calls[0]["top_k"] == 20


def test_retrieve_hybrid_uses_fused_list(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid.json")
    monkeypatch.setattr(
        run,
        "retrieve_hybrid",
        lambda *a, **k: _result(vector=[SimpleNamespace(chunk_id=1)], fused=[SimpleNamespace(chunk_id=2)]),
    )
    hits, _ = run._retrieve(
        object(), "q", cfg, user_id=1,
        embedding_client=FakeEmbedding(), rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [2]


def test_retrieve_rerank_adds_rerank_latency(monkeypatch) -> None:
    cfg = load_config(ROOT / "eval" / "configs" / "hybrid_rerank.json")
    monkeypatch.setattr(
        run,
        "retrieve_hybrid_reranked",
        lambda *a, **k: _result(
            reranked=[SimpleNamespace(chunk_id=3)], elapsed=20, rerank_ms=7
        ),
    )
    hits, latency = run._retrieve(
        object(), "q", cfg, user_id=1,
        embedding_client=FakeEmbedding(), rerank_client=FakeRerank(),
    )
    assert [hit.chunk_id for hit in hits] == [3]
    assert latency == 27


def test_render_markdown_uses_dash_for_null_answer() -> None:
    payload = {
        "dataset": "qa_set",
        "config": "vector",
        "case_count": 30,
        "retrieval": {"hit_at_5": 0.5, "mrr_at_5": 0.4, "avg_latency_ms": 120.0},
        "answer": None,
        "answer_skipped": True,
        "cases": [],
    }
    text = run._render_summary_markdown(payload)
    assert "| 配置 |" in text
    assert "vector" in text
    assert "—" in text


def test_render_markdown_includes_answer_metrics() -> None:
    payload = {
        "dataset": "qa_set",
        "config": "hybrid_rerank",
        "case_count": 30,
        "retrieval": {"hit_at_5": 0.8, "mrr_at_5": 0.6, "avg_latency_ms": 100.0},
        "answer": {
            "citation_precision": 0.9,
            "citation_hit_rate": 0.85,
            "refusal_accuracy": 1.0,
            "confusion": {"tp": 10, "fp": 0, "fn": 0, "tn": 20},
            "avg_total_tokens": 1200.0,
            "avg_latency_ms": 3000.0,
            "total_cost_yuan": 0.01,
            "llm_calls": 20,
            "citation_retry_count": 0,
            "answered_count": 20,
        },
        "answer_skipped": False,
        "cases": [],
    }
    text = run._render_summary_markdown(payload)
    assert "0.900" in text
    assert "0.850" in text
    assert "100.0%" in text
    assert "¥0.010000" in text


def test_eval_run_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_run.py -q
```

Expected: `No module named 'eval.run'`.

- [ ] **Step 3: 写实现**

`eval/run.py`：

```python
"""S1-7 评测 CLI：三配置检索 + 生产链路回答指标。

用法（仓库根目录）：
    python eval/run.py --dataset qa_set --config hybrid_rerank
    python eval/run.py --dataset qa_set --config vector --skip-answer
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.ai.embedding import get_embedding_client  # noqa: E402
from app.ai.embedding.errors import EmbeddingError  # noqa: E402
from app.ai.llm import get_llm_client  # noqa: E402
from app.ai.llm.errors import LLMError  # noqa: E402
from app.ai.rag.answerer import answer_question  # noqa: E402
from app.ai.rag.retriever import (  # noqa: E402
    RetrievalResult,
    RetrievedChunk,
    retrieve_hybrid,
    retrieve_hybrid_reranked,
)
from app.ai.rerank import RerankError, get_rerank_client  # noqa: E402
from app.core.context import set_trace_id  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.models.note_chunk import NoteChunk  # noqa: E402
from eval.qa_eval import (  # noqa: E402
    AnswerSummary,
    CaseAnswer,
    CaseRetrieval,
    DatasetError,
    EvalConfigError,
    QACase,
    RetrievalConfig,
    citation_hit,
    citation_precision,
    first_gold_rank,
    load_config,
    load_dataset,
    summarize_answer,
    summarize_retrieval,
    validate_gold_chunks,
)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def _resolve_dataset(value: str) -> Path:
    path = Path(value)
    if path.suffix == ".jsonl" or path.is_file():
        return path
    return ROOT / "eval" / "datasets" / f"{value}.jsonl"


def _resolve_config(value: str) -> Path:
    path = Path(value)
    if path.suffix == ".json" or path.is_file():
        return path
    return ROOT / "eval" / "configs" / f"{value}.json"


def _retrieve(
    session,
    question: str,
    cfg: RetrievalConfig,
    *,
    user_id: int,
    embedding_client,
    rerank_client,
) -> tuple[list[RetrievedChunk], int]:
    if cfg.retrieval == "vector":
        result: RetrievalResult = retrieve_hybrid(
            session,
            question,
            user_id=user_id,
            top_k=cfg.top_k,
            client=embedding_client,
        )
        return result.vector[: cfg.top_n], result.elapsed_ms
    if cfg.retrieval == "hybrid":
        result = retrieve_hybrid(
            session,
            question,
            user_id=user_id,
            top_k=cfg.top_k,
            client=embedding_client,
        )
        return result.fused[: cfg.top_n], result.elapsed_ms
    result = retrieve_hybrid_reranked(
        session,
        question,
        user_id=user_id,
        top_k=cfg.top_k,
        rerank_candidates=cfg.rerank_candidates,
        rerank_top_k=cfg.rerank_top_k,
        client=embedding_client,
        rerank_client=rerank_client,
    )
    extra = result.rerank_info.latency_ms if result.rerank_info else 0
    return result.reranked[: cfg.top_n], result.elapsed_ms + extra


def _answer_case(
    session,
    case: QACase,
    cfg: RetrievalConfig,
    *,
    user_id: int,
    embedding_client,
    rerank_client,
    llm_client,
) -> tuple[CaseAnswer, int, int]:
    result = answer_question(
        session,
        case.question,
        user_id=user_id,
        top_k=cfg.top_k,
        embedding_client=embedding_client,
        rerank_client=rerank_client,
        llm_client=llm_client,
    )
    cited = [citation.chunk_id for citation in result.citations]
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
    answer = CaseAnswer(
        case_id=case.id,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        cited_chunk_ids=cited,
        citation_precision=precision,
        citation_hit=matched,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
        cost_yuan=result.cost_yuan,
    )
    return answer, result.llm_calls, result.citation_retry_count


def _render_summary_markdown(payload: dict[str, Any]) -> str:
    retrieval = payload["retrieval"]
    answer = payload["answer"]
    lines = [
        "# S1-7 自测结果",
        "",
        f"- 数据集：`{payload['dataset']}`（{payload['case_count']} 条）",
        f"- 配置：`{payload['config']}`",
        f"- 生成时间：{payload.get('generated_at', '—')}",
        "",
        "| 配置 | hit@5 | MRR@5 | 引用精确率 | 引用命中率 | 拒答准确率 | 平均延迟 | 平均 tokens | 总费用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if answer is None:
        lines.append(
            f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
            f"{retrieval['mrr_at_5']:.3f} | — | — | — | "
            f"{retrieval['avg_latency_ms']:.0f}ms | — | — |"
        )
    else:
        lines.append(
            f"| {payload['config']} | {retrieval['hit_at_5']:.3f} | "
            f"{retrieval['mrr_at_5']:.3f} | {answer['citation_precision']:.3f} | "
            f"{answer['citation_hit_rate']:.3f} | "
            f"{answer['refusal_accuracy'] * 100:.1f}% | "
            f"{answer['avg_latency_ms']:.0f}ms | "
            f"{answer['avg_total_tokens']:.1f} | "
            f"¥{answer['total_cost_yuan']:.6f} |"
        )
    lines += [
        "",
        f"- 检索平均延迟：{retrieval['avg_latency_ms']:.0f}ms",
    ]
    if answer is not None:
        lines += [
            f"- 拒答混淆矩阵：{answer['confusion']}",
            f"- answered_count：{answer['answered_count']}",
            f"- llm_calls：{answer['llm_calls']}",
            f"- citation_retry_count：{answer['citation_retry_count']}",
        ]
    else:
        lines.append("- 回答指标：未运行（--skip-answer 或非生产配置）")
    lines.append("")
    return "\n".join(lines)


def _write_outputs(payload: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_summary_markdown(payload)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")


def _build_payload(
    *,
    dataset_name: str,
    config_name: str,
    user_id: int,
    cases: list[QACase],
    retrieval_summary,
    answer_summary: AnswerSummary | None,
    answer_skipped: bool,
    case_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "dataset": dataset_name,
        "config": config_name,
        "user_id": user_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "answerable_count": sum(1 for case in cases if not case.should_refuse),
        "refusal_count": sum(1 for case in cases if case.should_refuse),
        "answer_skipped": answer_skipped,
        "retrieval": {
            "hit_at_5": retrieval_summary.hit_at_5,
            "mrr_at_5": retrieval_summary.mrr_at_5,
            "avg_latency_ms": retrieval_summary.avg_latency_ms,
        },
        "answer": None
        if answer_summary is None
        else {
            "citation_precision": answer_summary.citation_precision,
            "citation_hit_rate": answer_summary.citation_hit_rate,
            "refusal_accuracy": answer_summary.refusal_accuracy,
            "confusion": answer_summary.confusion,
            "avg_total_tokens": answer_summary.avg_total_tokens,
            "avg_latency_ms": answer_summary.avg_latency_ms,
            "total_cost_yuan": answer_summary.total_cost_yuan,
            "llm_calls": answer_summary.llm_calls,
            "citation_retry_count": answer_summary.citation_retry_count,
            "answered_count": answer_summary.answered_count,
        },
        "cases": case_rows,
    }


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="S1-7 自测问答评测")
    parser.add_argument("--dataset", required=True, help="qa_set 或 .jsonl 路径")
    parser.add_argument("--config", required=True, help="vector/hybrid/hybrid_rerank 或 .json 路径")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--skip-answer", action="store_true", help="只跑检索，不调 LLM")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--md-output", type=Path, default=None)
    args = parser.parse_args()

    dataset_path = _resolve_dataset(args.dataset)
    config_path = _resolve_config(args.config)
    try:
        cases = load_dataset(dataset_path)
        cfg = load_config(config_path)
    except (DatasetError, EvalConfigError) as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2

    answer_enabled = cfg.retrieval == "hybrid_rerank" and not args.skip_answer
    set_trace_id("s1-7-eval-" + uuid.uuid4().hex[:12])

    try:
        embedding_client = get_embedding_client()
        rerank_client = get_rerank_client() if cfg.retrieval == "hybrid_rerank" else None
        llm_client = get_llm_client() if answer_enabled else None
        retrieval_rows: list[CaseRetrieval] = []
        answer_rows: list[CaseAnswer] = []
        case_rows: list[dict[str, Any]] = []
        llm_calls = 0
        citation_retry_count = 0
        with new_session() as session:
            owner_rows = session.execute(
                select(NoteChunk.id, NoteChunk.note_id).where(
                    NoteChunk.user_id == args.user_id
                )
            ).all()
            validate_gold_chunks(cases, {row.id: row.note_id for row in owner_rows})

            for case in cases:
                hits, latency_ms = _retrieve(
                    session,
                    case.question,
                    cfg,
                    user_id=args.user_id,
                    embedding_client=embedding_client,
                    rerank_client=rerank_client,
                )
                rank = first_gold_rank(hits, set(case.gold_chunk_ids)) if not case.should_refuse else None
                retrieval_rows.append(
                    CaseRetrieval(
                        case_id=case.id,
                        hit_at_5=rank is not None,
                        first_gold_rank=rank,
                        latency_ms=latency_ms,
                    )
                )
                answer_row = None
                if answer_enabled:
                    answer_row, calls, retries = _answer_case(
                        session,
                        case,
                        cfg,
                        user_id=args.user_id,
                        embedding_client=embedding_client,
                        rerank_client=rerank_client,
                        llm_client=llm_client,
                    )
                    answer_rows.append(answer_row)
                    llm_calls += calls
                    citation_retry_count += retries
                case_rows.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "scope": case.scope,
                        "should_refuse": case.should_refuse,
                        "gold_chunk_ids": case.gold_chunk_ids,
                        "hit_at_5": rank is not None if not case.should_refuse else None,
                        "first_gold_rank": rank,
                        "retrieval_latency_ms": latency_ms,
                        "answer": None
                        if answer_row is None
                        else {
                            "refused": answer_row.refused,
                            "refusal_reason": answer_row.refusal_reason,
                            "cited_chunk_ids": answer_row.cited_chunk_ids,
                            "citation_precision": answer_row.citation_precision,
                            "citation_hit": answer_row.citation_hit,
                            "total_tokens": answer_row.total_tokens,
                            "latency_ms": answer_row.latency_ms,
                            "cost_yuan": answer_row.cost_yuan,
                        },
                    }
                )

        retrieval_summary = summarize_retrieval(cases, retrieval_rows)
        answer_summary = (
            None
            if not answer_enabled
            else summarize_answer(
                cases,
                answer_rows,
                llm_calls=llm_calls,
                citation_retry_count=citation_retry_count,
            )
        )
        config_name = cfg.name
        json_path = args.output or (ROOT / "eval" / "results" / f"s1-7-{config_name}.json")
        md_path = args.md_output or (ROOT / "eval" / "results" / f"s1-7-{config_name}.md")
        payload = _build_payload(
            dataset_name=dataset_path.stem,
            config_name=config_name,
            user_id=args.user_id,
            cases=cases,
            retrieval_summary=retrieval_summary,
            answer_summary=answer_summary,
            answer_skipped=not answer_enabled,
            case_rows=case_rows,
        )
        _write_outputs(payload, json_path, md_path)
        print(_render_summary_markdown(payload))
        print(f"JSON：{json_path}")
        print(f"Markdown：{md_path}")
        return 0
    except DatasetError as exc:
        print(f"数据/配置错误：{exc}", file=sys.stderr)
        return 2
    except OperationalError:
        print(
            "数据库连接失败：请先启动基础服务 "
            "docker compose -f deploy/docker-compose.dev.yml up -d",
            file=sys.stderr,
        )
        return 3
    except (EmbeddingError, RerankError, LLMError) as exc:
        print(f"外部调用失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
```

> 说明：`_answer_case` 已直接返回 `(CaseAnswer, llm_calls, citation_retry_count)`；`llm_calls` 使用 `result.llm_calls`，不再用“有 token 的回答条数”近似。

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_eval_run.py -q
```

Expected: `all passed`（约 6 条）。

---

## Task 4: 生成候选清单（不写 gold）

**Files:**
- Create (temporary, not commit): `/tmp/s1_7_candidates.py`
- Create: `eval/datasets/qa_set.candidates.md`

**Interfaces:**
- Consumes: 20 个候选问题（spec §3.1）、`retrieve_hybrid_reranked()`。
- Produces: 每道应答题 top5 候选块（`chunk_id/note_id/heading/片段`），供用户勾选 gold。

- [ ] **Step 1: 写一次性候选脚本**

`/tmp/s1_7_candidates.py`：

```python
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"E:\BiShe-AIStudy\study-agent")
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.embedding import get_embedding_client
from app.ai.rag.retriever import retrieve_hybrid_reranked
from app.core.context import set_trace_id
from app.core.db import new_session

QUESTIONS = [
    ("q001", "函数的定义域怎么求？", "函数"),
    ("q002", "函数单调性的定义是什么？", "函数"),
    ("q003", "如何用定义证明函数在区间上单调递增？", "函数"),
    ("q004", "奇函数和偶函数有什么性质？", "函数"),
    ("q005", "二次函数在闭区间上的最值怎么求？", "函数"),
    ("q006", "分段函数 f(f(-1)) 怎么求？", "函数"),
    ("q007", "函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？", "函数"),
    ("q008", "已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？", "函数"),
    ("q009", "函数图象关于原点对称说明什么？", "函数"),
    ("q010", "商品定价最大利润问题怎么建模？", "函数"),
    ("q011", "指数函数的定义域和值域是什么？", "指对函数"),
    ("q012", "对数函数的定义域和值域是什么？", "指对函数"),
    ("q013", "指数式 a^b=N 和对数式怎么互化？", "指对函数"),
    ("q014", "y=log_0.5(x^2-2x-3) 的单调区间怎么求？", "指对函数"),
    ("q015", "导数大于 0 说明函数在区间上什么性质？", "导数"),
    ("q016", "函数 f(x)=x^3-3x 的单调区间是什么？", "导数"),
    ("q017", "函数 f(x)=x ln x 的极小值是多少？", "导数"),
    ("q018", "等差数列 a_1=2，d=3，a_10 等于多少？", "数列"),
    ("q019", "等比数列 a_1=1，q=2，前 5 项和 S_5 是多少？", "数列"),
    ("q020", "错位相减法的口诀是什么？", "数列"),
]

_SCHOOL = re.compile(r"[\u4e00-\u9fa5]{2,}(?:大学|中学|学校)")


def safe(text: str | None) -> str:
    cleaned = _SCHOOL.sub("某学校", text or "未标注").replace("\n", " ")
    return cleaned.replace("|", "\\|")[:120]


def main() -> None:
    set_trace_id("s1-7-candidates")
    client = get_embedding_client()
    lines = ["# S1-7 qa_set 候选块（未标注，不是 gold）", ""]
    with new_session() as session:
        for case_id, question, scope in QUESTIONS:
            result = retrieve_hybrid_reranked(
                session, question, user_id=1, top_k=20, client=client
            )
            lines.append(f"## {case_id} · {scope}")
            lines.append("")
            lines.append(f"问题：{question}")
            lines.append("")
            lines.append("| chunk_id | note_id | heading | 片段（前 80 字） |")
            lines.append("|---:|---:|---|---|")
            for rank, hit in enumerate(result.reranked[:5], start=1):
                lines.append(
                    f"| {hit.chunk_id} | {hit.note_id} | {safe(hit.heading_path)} | "
                    f"{safe(hit.content[:80])} |"
                )
            lines.append("")
    (ROOT / "eval" / "datasets" / "qa_set.candidates.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑一次生成候选清单**

```bash
.venv\Scripts\python.exe /tmp/s1_7_candidates.py
```

Expected: 生成 `eval/datasets/qa_set.candidates.md`，每道应答题 5 行候选；无真实校名。

- [ ] **Step 3: 请用户勾选 gold**

把候选清单交给用户，要求逐题给出：

```text
q001: [chunk_id, ...]
q002: [chunk_id, ...]
...
q020: [chunk_id, ...]
q021–q030: 全部应拒，gold=[]
```

**禁止**：根据 top1/rerank 分自动填 gold；用户未确认的 ID 不写入。

- [ ] **Step 4: 校验用户标注（先不写正式 JSONL）**

用一次性脚本检查：

```python
# /tmp/s1_7_check_gold.py
from pathlib import Path
import sys
ROOT = Path(r"E:\BiShe-AIStudy\study-agent")
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import select
from app.core.db import new_session
from app.models.note_chunk import NoteChunk

gold = {
    # 用户确认后粘贴，例如 "q001": [25, 26],
}
with new_session() as session:
    rows = session.execute(
        select(NoteChunk.id, NoteChunk.note_id, NoteChunk.heading_path)
        .where(NoteChunk.user_id == 1)
    ).all()
    owner = {row.id: row.note_id for row in rows}
    missing = sorted({i for ids in gold.values() for i in ids} - set(owner))
    print("missing:", missing)
    for qid, ids in gold.items():
        print(qid, [(i, owner.get(i)) for i in ids])
```

Expected: `missing: []`。

---

## Task 5: 写正式 qa_set 并跑三配置

**Files:**
- Create: `eval/datasets/qa_set.jsonl`
- Create: `eval/results/s1-7-vector.json` / `.md`
- Create: `eval/results/s1-7-hybrid.json` / `.md`
- Create: `eval/results/s1-7-hybrid_rerank.json` / `.md`
- Create: `docs/EVAL_S1.md`

**Interfaces:**
- Consumes: 用户确认的 20 组 gold + 10 条拒答；`eval/run.py`。
- Produces: 真实评测数字与文档。

- [ ] **Step 1: 写 qa_set.jsonl**

按 spec §3.2 写 30 行，`gold_chunk_ids` 只用 Task 4 用户确认的 ID；`q021–q030` 为应拒题、gold 为空。

- [ ] **Step 2: 先跑数据校验（不跑真实检索）**

```bash
.venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.')
from eval.qa_eval import load_dataset
cases = load_dataset('eval/datasets/qa_set.jsonl')
print(len(cases), sum(1 for c in cases if c.should_refuse))
"
```

Expected: `30 10`。

- [ ] **Step 3: 跑三配置**

```bash
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config vector --skip-answer
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config hybrid --skip-answer
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config hybrid_rerank
```

Expected:
- 三份 JSON/Markdown 生成；
- `hybrid_rerank` 的 `answer` 非 null，含 citation/refusal/tokens/cost；
- `vector`/`hybrid` 的 `answer` 为 null；
- 终端没有异常/未捕获 traceback。

- [ ] **Step 4: 检查验收线**

```bash
.venv\Scripts\python.exe -c "
import json
for name in ('vector','hybrid','hybrid_rerank'):
    p=json.load(open(f'eval/results/s1-7-{name}.json', encoding='utf-8'))
    print(name, p['retrieval'])
    print('answer', p['answer'])
"
```

判定：

- `hybrid_rerank.retrieval.hit_at_5 >= 0.6` 才算通过；
- 若低于 0.6：**停**，如实报告，回 S1-2 检查切片/重新标注；不改问题、不删失败题；
- 引用精确率/拒答准确率如实记录，0 就是 0。

- [ ] **Step 5: 写 `docs/EVAL_S1.md`**

必须包含：

```markdown
# S1-7 自测与效果抽查

## 1. 数据
- 30 条 = 20 应答题 + 10 应拒题
- 83 块 / 7 note；note 107 为合成样张
- gold 由用户人工标注，标注日期：2026-10-20

## 2. 方法
- 三配置：vector / hybrid / hybrid_rerank
- 指标定义：...
- 复现命令：...

## 3. 结果
（贴真实表格，不填占位）

## 4. 失败题
（逐条列 id/question/原因，不隐藏）

## 5. 与 S1-5 的差异
（样本从 10 条扩到 30 条；数字不可直接混用）

## 6. 已知局限
（30 条/83 块、延迟口径、citation 不等于答案正确）
```

- [ ] **Step 6: 跑全量测试**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: 现有 160 条 + 新增评测测试全绿；如有失败，先修复再继续。

---

## Task 6: 文档同步、单次提交与 tag

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DECISIONS.md`
- Modify: `AGENTS.md` §9.6（如评测运行器适合作为锚点）
- Modify: `docs/spec/s1-7-eval.md` §实际回填
- Create/Modify: `docs/EVAL_S1.md`

- [ ] **Step 1: 回填真实数字**

在 spec 末尾增加：

```markdown
## 15. 实施回填

- 实际测试数量：
- qa_set：30 条（20 应答题 + 10 应拒题），gold 由用户标注
- 三配置真实 hit@5/MRR：
- 引用/拒答/tokens/cost：
- 与 plan 的偏离：
- 已知问题：
```

只填真实运行结果，不写“预计”。

- [ ] **Step 2: 更新 PROGRESS / DECISIONS**

PROGRESS 增加 S1-7 完成项：数据、三配置数字、失败题、测试数、commit。
DECISIONS 增加 D-020：

```markdown
## D-020 S1-7 评测集与指标口径

- gold 必须人工标注，不由检索结果反推
- 三配置只比检索；回答指标只在 hybrid_rerank 上算
- 纯向量延迟复用同次混合检索，属于保守口径
- 样本 30 条/83 块，数字不外推
```

- [ ] **Step 3: 隐私与 diff 检查**

```bash
git diff --check
git status --short
grep -RIn "附属中学\|命题人：\|审核人：" eval docs backend 2>/dev/null || true
grep -RIn "sk-\|DASHSCOPE_API_KEY=" eval docs backend 2>/dev/null || true
```

Expected: 无真实校名、无 Key、无 `.env`、无 DOCX 入库。

- [ ] **Step 4: 单次提交**

```bash
git add eval docs/PROGRESS.md docs/DECISIONS.md docs/EVAL_S1.md docs/spec/s1-7-eval.md docs/plan/s1-7-eval.md AGENTS.md
git commit -m "feat(s1-7): 建立 30 条问答评测集与三配置抽查"
```

- [ ] **Step 5: tag**

```bash
git tag m0-rag-validated
```

> tag 在本地；用户负责 push（`git push` + `git push --tags`）。若验收未过，不打 tag。

- [ ] **Step 6: 最终验证**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
cd ..
git status --short
git log -1 --oneline
```

Expected: 全绿、工作区干净、commit 可读。

---

## Self-Review

### Spec coverage

| Spec 要求 | 对应 Task |
|---|---|
| 30 条数据集格式/校验 | Task 1 |
| 三份配置 | Task 1 |
| hit@5/MRR/引用/拒答指标 | Task 2 |
| `eval/run.py` 三配置路由 | Task 3 |
| gold 预标注/确认流程 | Task 4 |
| 真实三配置数字 | Task 5 |
| `docs/EVAL_S1.md` | Task 5 |
| 文档/PROGRESS/DECISIONS/commit/tag | Task 6 |

### Placeholder scan

- 无 TBD/TODO；gold ID 明确要求用户填写，不是占位符。
- 所有代码步骤都有可执行片段。
- Task 3 的 `_answer_case` 直接返回 `(CaseAnswer, result.llm_calls, result.citation_retry_count)`，没有近似值。

### Type consistency

- `CaseAnswer(...)` 参数顺序与 dataclass 一致；
- `_answer_case` 最终返回 `tuple[CaseAnswer, int, int]`；
- `summarize_answer` 接受 `llm_calls`/`citation_retry_count`；
- `retrieve_hybrid()` 返回 `RetrievalResult`，`_retrieve()` 返回 `(list[RetrievedChunk], int)`；
- `QACase.gold_chunk_ids` 是 DB `note_chunks.id`，与 `citation.chunk_id` 同域。

## 执行记录（2026-10-21）

- Task 1–3 按 plan 实现，新增测试 31 条（16 + 8 + 7），全量 pytest **191 passed, 1 warning**。
- 偏离 1（gold 标注）：用户认为逐题勾选过多，改为“AI 预标注 + 用户确认”；用户已确认预标注版本。数据集/文档明确写该来源，不宣称纯人工标注。
- 偏离 2（候选清单）：Task 4 原定 top5，实际输出 `fused` top10 + 全量 83 块目录，避免 gold 不在 top5 时无法勾选；候选中的校名/命题人已泛化。
- 测试修正：`test_load_dataset_rejects_bad_json_line` 首行改为合法 case，否则会先报字段缺失；`test_summarize_answer_metrics_and_refusals` 的拒答准确率由错误断言 `1.0` 改为 `2/3`（数据含 1 个 FP），实现未改。
- 真实结果：vector hit@5=1.000/MRR=0.917；hybrid 1.000/0.827；hybrid_rerank 1.000/0.938、引用精确率 0.827、引用命中率 1.000、拒答准确率 100%、回答 6243ms/945.5 tokens/¥0.0317224；详见 `docs/EVAL_S1.md`。
- 验收：30 条/10 拒答；三份 JSON/Markdown 落盘；tag `m0-rag-validated`；用户负责 push。