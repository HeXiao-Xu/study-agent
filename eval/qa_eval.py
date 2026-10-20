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


def _records_by_id(
    records: Sequence[CaseRetrieval | CaseAnswer],
) -> dict[str, object]:
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