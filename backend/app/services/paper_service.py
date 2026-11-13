"""S5-1 自适应组卷内核（方案 §6.5）：纯函数、可脱库单测、同种子可复现。

候选题库与掌握度由调用方注入；落 papers 表与 HTTP 接口在 S5-2，PDF 在 S5-3。
参数是工程取值，不是拟合结果——答辩口径见 docs/spec/s5-1-paper-planning.md §7。
"""
from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TypeVar

QTYPE_ORDER: tuple[str, ...] = ("单选", "多选", "填空", "解答")
"""题型顺序同时决定配额取整的稳定补位与试卷输出顺序（与 QuestionType 一致）。"""

DEFAULT_SCORE_BY_QTYPE: Mapping[str, int] = {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
"""questions 表没有分值列：同一题型同分，总分因此是题型计数的函数（spec §3.1）。"""

NEUTRAL_MASTERY = 0.5
"""无 mastery 行 = 未评估；打分为中性，不当作 0 掌握（D-050）。"""

NOVELTY_WINDOW_DAYS = 30.0
MASTERY_LOW = 0.5
MASTERY_HIGH = 0.8
TARGET_DIFFICULTY_LOW = 2
TARGET_DIFFICULTY_MIDDLE = 3
TARGET_DIFFICULTY_HIGH = 5
DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 5
DEFAULT_SCORE_TOLERANCE_RATIO = 0.05
DEFAULT_EXCLUDE_RECENT_DAYS = 14
TRUSTED_ORIGINS = frozenset({"textbook", "exam"})
SCORE_PRECISION = 6

K = TypeVar("K")


class PaperPlanError(Exception):
    """组卷入参不合法（S5-2 映射 422/42200）；题库不足不抛这个，走 violation。"""


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    difficulty: float = 0.35
    mastery: float = 0.30
    novelty: float = 0.20
    quality: float = 0.15


SCORING_WEIGHTS = ScoringWeights()


@dataclass(frozen=True, slots=True)
class PaperConstraints:
    kp_ids: tuple[int, ...]
    total_questions: int
    qtype_ratio: Mapping[str, float]
    difficulty_dist: Mapping[int, float]
    total_score_target: int
    kp_weights: Mapping[int, float] | None = None
    score_by_qtype: Mapping[str, int] | None = None
    score_tolerance_ratio: float = DEFAULT_SCORE_TOLERANCE_RATIO
    exclude_recent_days: int = DEFAULT_EXCLUDE_RECENT_DAYS
    duration_min: int | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        if self.total_questions < 1:
            raise PaperPlanError("total_questions 必须 ≥ 1")
        if not self.kp_ids:
            raise PaperPlanError("kp_ids 不能为空")
        if len(set(self.kp_ids)) != len(self.kp_ids):
            raise PaperPlanError("kp_ids 不能包含重复知识点")
        if not self.qtype_ratio:
            raise PaperPlanError("qtype_ratio 不能为空")
        unknown_qtype = [qtype for qtype in self.qtype_ratio if qtype not in QTYPE_ORDER]
        if unknown_qtype:
            raise PaperPlanError(f"qtype_ratio 含未知题型：{unknown_qtype}")
        if any(float(weight) <= 0 for weight in self.qtype_ratio.values()):
            raise PaperPlanError("qtype_ratio 的权重必须大于 0")
        if not self.difficulty_dist:
            raise PaperPlanError("difficulty_dist 不能为空")
        unknown_difficulty = [
            difficulty
            for difficulty in self.difficulty_dist
            if difficulty not in range(DIFFICULTY_MIN, DIFFICULTY_MAX + 1)
        ]
        if unknown_difficulty:
            raise PaperPlanError(f"difficulty_dist 含 1–5 之外的难度：{unknown_difficulty}")
        if any(float(weight) < 0 for weight in self.difficulty_dist.values()):
            raise PaperPlanError("difficulty_dist 的权重不能为负")
        if sum(float(weight) for weight in self.difficulty_dist.values()) <= 0:
            raise PaperPlanError("difficulty_dist 的权重之和必须大于 0")
        scores = self.score_by_qtype or DEFAULT_SCORE_BY_QTYPE
        missing_qtype = [qtype for qtype in QTYPE_ORDER if qtype not in scores]
        if missing_qtype:
            raise PaperPlanError(f"score_by_qtype 缺少题型：{missing_qtype}")
        extra_qtype = [qtype for qtype in scores if qtype not in QTYPE_ORDER]
        if extra_qtype:
            raise PaperPlanError(f"score_by_qtype 含未知题型：{extra_qtype}")
        if any(int(score) <= 0 for score in scores.values()):
            raise PaperPlanError("score_by_qtype 的分值必须大于 0")
        if self.total_score_target < 1:
            raise PaperPlanError("total_score_target 必须 ≥ 1")
        if self.score_tolerance_ratio < 0:
            raise PaperPlanError("score_tolerance_ratio 不能为负")
        if self.exclude_recent_days < 0:
            raise PaperPlanError("exclude_recent_days 不能为负")
        if self.kp_weights is not None:
            unknown_kp = [kp_id for kp_id in self.kp_weights if kp_id not in self.kp_ids]
            if unknown_kp:
                raise PaperPlanError(f"kp_weights 含不在 kp_ids 里的知识点：{unknown_kp}")
            if any(float(weight) <= 0 for weight in self.kp_weights.values()):
                raise PaperPlanError("kp_weights 的权重必须大于 0")

    @property
    def score_map(self) -> dict[str, int]:
        return dict(self.score_by_qtype or DEFAULT_SCORE_BY_QTYPE)

    @property
    def kp_weight_map(self) -> dict[int, float]:
        weights = {kp_id: 1.0 for kp_id in self.kp_ids}
        if self.kp_weights:
            weights.update(
                {kp_id: float(weight) for kp_id, weight in self.kp_weights.items()}
            )
        return weights


@dataclass(frozen=True, slots=True)
class CandidateQuestion:
    question_id: int
    qtype: str
    difficulty: int
    kp_weights: tuple[tuple[int, float], ...]
    verified: bool
    origin: str
    last_done_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScoreParts:
    difficulty_match: float
    mastery_match: float
    novelty: float
    quality: float
    total: float


@dataclass(frozen=True, slots=True)
class PaperItem:
    question_id: int
    qtype: str
    difficulty: int
    score: int
    kp_ids: tuple[int, ...]
    parts: ScoreParts


@dataclass(frozen=True, slots=True)
class QuotaPlan:
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    target_by_difficulty: dict[int, int]
    target_by_kp: dict[int, int]
    planned_total_score: int
    score_out_of_tolerance: bool
    tolerance: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    message: str
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class PaperPlan:
    ok: bool
    items: tuple[PaperItem, ...]
    total_score: int
    target_score: int
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    counts_by_qtype: dict[str, int]
    counts_by_difficulty: dict[int, int]
    counts_by_kp: dict[int, int]
    violations: tuple[Violation, ...]
    warnings: tuple[str, ...]
    seed: int


def _as_utc(value: datetime) -> datetime:
    """naive 按 UTC 解释：题库里 last_done_at 可能来自不带时区的字段。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise PaperPlanError(f"{name} 必须带时区（UTC）")


def prepare_pool(
    constraints: PaperConstraints,
    candidates: Sequence[CandidateQuestion],
    *,
    now: datetime,
) -> tuple[tuple[CandidateQuestion, ...], int]:
    """过滤出可选题：同 id 取首条、去掉与约束 kp 无交集者、排除近期做过的题。"""
    _require_aware(now, "now")
    moment = _as_utc(now)
    cutoff = moment - timedelta(days=constraints.exclude_recent_days)
    kp_set = frozenset(constraints.kp_ids)
    pool: list[CandidateQuestion] = []
    seen: set[int] = set()
    excluded_recent = 0
    for candidate in candidates:
        if candidate.question_id in seen:
            continue
        seen.add(candidate.question_id)
        if candidate.qtype not in QTYPE_ORDER:
            raise PaperPlanError(
                f"候选题 {candidate.question_id} 的题型非法：{candidate.qtype}"
            )
        if candidate.difficulty not in range(DIFFICULTY_MIN, DIFFICULTY_MAX + 1):
            raise PaperPlanError(
                f"候选题 {candidate.question_id} 的难度非法：{candidate.difficulty}"
            )
        weights: dict[int, float] = {}
        for kp_id, weight in candidate.kp_weights:
            if kp_id in kp_set and kp_id not in weights:
                weights[kp_id] = float(weight)
        if not weights:
            continue
        if candidate.last_done_at is not None and _as_utc(candidate.last_done_at) >= cutoff:
            excluded_recent += 1
            continue
        pool.append(replace(candidate, kp_weights=tuple(weights.items())))
    return tuple(pool), excluded_recent