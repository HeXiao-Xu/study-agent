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