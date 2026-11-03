"""S4-5 图谱关系 LLM 适配器：只做「给定候选 → 结构化结论」，不碰数据库。

两个职责：
1. `infer_prerequisites`：一次调用判定一个知识点的直接前置（候选由向量召回限定）；
2. `review_pairs`：批量复核 related / confusable 配对。

共同约定：严格 JSON + Pydantic + 最多 2 次逻辑重试；候选白名单之外的一律丢弃
（LLM 编 id 是常见幻觉，不能让它直接落库）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.ai.gen.json_repair import loads_lenient_json
from app.ai.graph.candidates import KpBrief, KpCandidate, Pair
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

SCENE = "graph"
MAX_TOKENS = 600
PAIR_MAX_TOKENS = 800
TEMPERATURE = 0.2
MIN_CONFIDENCE = 0.5
MAX_PREREQ = 2
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
RELATION_LABELS = {"related": "相关", "confusable": "易混"}

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class GraphBuildError(AppError):
    """图谱构建失败（LLM 输出不可用 / 重试耗尽）。"""

    def __init__(self, message: str = "知识图谱构建失败") -> None:
        super().__init__(message, code=50000, http_status=500)


class _PrereqItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    src_kp_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class _PrereqOut(BaseModel):
    items: list[_PrereqItem] = Field(default_factory=list)


class _PairItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pair_id: int
    accept: bool
    reason: str = ""


class _PairOut(BaseModel):
    items: list[_PairItem] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InferredPrereq:
    src_kp_id: int
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class PairVerdict:
    pair_id: int
    accept: bool
    reason: str


@lru_cache(maxsize=4)
def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _render(template: str, mapping: dict[str, str]) -> str:
    text = template
    for key, value in mapping.items():
        text = text.replace("{{ " + key + " }}", value)
    return text


def _parse(model: type[_ModelT], text: str) -> _ModelT | None:
    """解析失败返回 None 交给调用方重试；只吞解析/校验错误，不吞编程错误。"""
    try:
        data = loads_lenient_json(text)
    except (ValueError, TypeError):
        return None
    try:
        return model.model_validate(data)
    except Exception:  # noqa: BLE001 - 结构不符统一走重试
        return None


def _chat(llm: LLMClient, prompt: str, *, max_tokens: int) -> Any:
    return llm.chat(
        [LLMMessage(role="user", content=prompt)],
        temperature=TEMPERATURE,
        max_tokens=max_tokens,
        scene=SCENE,
    )


def infer_prerequisites(
    *,
    target: KpBrief,
    candidates: list[KpCandidate],
    client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[InferredPrereq]:
    if not candidates:
        return []
    llm = client or get_llm_client()
    allowed = {item.kp_id for item in candidates}
    listing = "\n".join(
        f"{index}. id={item.kp_id} {item.name}（{item.path}）相似度 {item.cos:.2f}"
        for index, item in enumerate(candidates, start=1)
    )
    prompt = _render(
        _load_prompt("graph_prereq_v1.md"),
        {
            "target_name": target.name,
            "target_path": target.path or target.name,
            "children": "、".join(item.name for item in candidates[:6]),
            "candidates": listing,
        },
    )
    for attempt in range(max_retries + 1):
        parsed = _parse(_PrereqOut, _chat(llm, prompt, max_tokens=MAX_TOKENS).text)
        if parsed is not None:
            picked: list[InferredPrereq] = []
            for item in parsed.items:
                if item.src_kp_id not in allowed:
                    logger.info(
                        "graph_prereq_dropped",
                        extra={"reason": "out_of_candidates", "kp_id": item.src_kp_id},
                    )
                    continue
                if item.confidence < MIN_CONFIDENCE:
                    logger.info(
                        "graph_prereq_dropped",
                        extra={"reason": "low_confidence", "kp_id": item.src_kp_id},
                    )
                    continue
                picked.append(
                    InferredPrereq(
                        src_kp_id=item.src_kp_id,
                        confidence=item.confidence,
                        reason=item.reason[:60],
                    )
                )
            picked.sort(key=lambda entry: (-entry.confidence, entry.src_kp_id))
            return picked[:MAX_PREREQ]
        logger.warning(
            "graph_prereq_retry",
            extra={"attempt": attempt + 1, "target": target.name},
        )
    raise GraphBuildError(f"前置推断重试耗尽：{target.name}")


def review_pairs(
    *,
    pairs: list[tuple[int, Pair]],
    relation: str,
    client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[PairVerdict]:
    if not pairs:
        return []
    llm = client or get_llm_client()
    listing = "\n".join(
        f"{pair_id}. {pair.src_kp_id} ↔ {pair.dst_kp_id}（相似度 {pair.cos:.2f}）"
        for pair_id, pair in pairs
    )
    prompt = _render(
        _load_prompt("graph_pair_v1.md"),
        {
            "relation_label": RELATION_LABELS.get(relation, relation),
            "pairs": listing,
        },
    )
    allowed = {pair_id for pair_id, _ in pairs}
    for attempt in range(max_retries + 1):
        parsed = _parse(_PairOut, _chat(llm, prompt, max_tokens=PAIR_MAX_TOKENS).text)
        if parsed is not None:
            verdicts = [
                PairVerdict(
                    pair_id=item.pair_id, accept=item.accept, reason=item.reason[:60]
                )
                for item in parsed.items
                if item.pair_id in allowed
            ]
            if verdicts:
                return verdicts
        logger.warning(
            "graph_pair_retry", extra={"attempt": attempt + 1, "relation": relation}
        )
    raise GraphBuildError(f"关系复核重试耗尽：{relation}")