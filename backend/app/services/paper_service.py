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

def largest_remainder(weights: Mapping[K, float], total: int) -> dict[K, int]:
    """最大余数法：先取整、再按小数部分补足；并列时按入参顺序（稳定排序）。"""
    if total < 0:
        raise PaperPlanError("配额总数不能为负")
    if not weights:
        raise PaperPlanError("配额权重不能为空")
    values = {key: float(weight) for key, weight in weights.items()}
    if any(weight < 0 for weight in values.values()):
        raise PaperPlanError("配额权重不能为负")
    weight_sum = sum(values.values())
    if weight_sum <= 0:
        raise PaperPlanError("配额权重之和必须大于 0")
    raw = {key: weight / weight_sum * total for key, weight in values.items()}
    result = {key: int(math.floor(raw[key])) for key in values}
    missing = total - sum(result.values())
    for key in sorted(values, key=lambda key: -(raw[key] - result[key]))[:missing]:
        result[key] += 1
    return result


def _score_tolerance(target: int, ratio: float) -> int:
    return max(1, math.ceil(target * ratio))


def _qtype_total(counts: Mapping[str, int], score_map: Mapping[str, int]) -> int:
    return sum(int(counts[qtype]) * int(score_map[qtype]) for qtype in counts)


def _adjust_qtype_counts(
    constraints: PaperConstraints, counts: Mapping[str, int]
) -> tuple[dict[str, int], int, bool]:
    """总分容差只能靠题型计数微调：题分按题型固定，换题不改总分（spec §3.2）。"""
    score_map = constraints.score_map
    target = constraints.total_score_target
    tolerance = _score_tolerance(target, constraints.score_tolerance_ratio)
    base = _qtype_total(counts, score_map)
    if abs(base - target) <= tolerance:
        return dict(counts), base, False
    keys = [qtype for qtype in QTYPE_ORDER if qtype in counts]
    best_rank: tuple[int, int, tuple[int, ...]] | None = None
    best_counts: dict[str, int] | None = None
    best_score = base
    for deltas in itertools.product((-1, 0, 1), repeat=len(keys)):
        if sum(deltas) != 0:
            continue
        candidate = dict(counts)
        valid = True
        for qtype, delta in zip(keys, deltas):
            candidate[qtype] += delta
            if candidate[qtype] < 0:
                valid = False
                break
        if not valid:
            continue
        achieved = _qtype_total(candidate, score_map)
        if abs(achieved - target) > tolerance:
            continue
        rank = (sum(abs(delta) for delta in deltas), abs(achieved - target), deltas)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_counts = candidate
            best_score = achieved
    if best_counts is None:
        return dict(counts), base, True
    return best_counts, best_score, False


def _count_by_qtype(pool: Sequence[CandidateQuestion]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in pool:
        counts[candidate.qtype] = counts.get(candidate.qtype, 0) + 1
    return counts


def _count_by_difficulty(pool: Sequence[CandidateQuestion]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for candidate in pool:
        counts[candidate.difficulty] = counts.get(candidate.difficulty, 0) + 1
    return counts


def _count_by_kp(pool: Sequence[CandidateQuestion]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for candidate in pool:
        for kp_id, _weight in candidate.kp_weights:
            counts[kp_id] = counts.get(kp_id, 0) + 1
    return counts


def _borrow_difficulty(
    alloc: Mapping[int, int], available: Mapping[int, int]
) -> dict[int, int]:
    """题库某难度不够时，把缺口借给相邻难度（先近距离、再富余多、再难度小）。"""
    target = dict(alloc)
    for difficulty in sorted(alloc):
        deficit = target[difficulty] - available.get(difficulty, 0)
        if deficit <= 0:
            continue
        target[difficulty] -= deficit
        while deficit > 0:
            donors = [
                other
                for other in target
                if other != difficulty and available.get(other, 0) - target[other] > 0
            ]
            if not donors:
                break
            donor = min(
                donors,
                key=lambda other: (
                    abs(other - difficulty),
                    -(available[other] - target[other]),
                    other,
                ),
            )
            target[donor] += 1
            deficit -= 1
    return target


def _borrow_kp(alloc: Mapping[int, int], available: Mapping[int, int]) -> dict[int, int]:
    """某个知识点候选不足时，把缺口借给富余最多的知识点（同富余按 kp 顺序）。"""
    target = dict(alloc)
    for kp_id in alloc:
        deficit = target[kp_id] - available.get(kp_id, 0)
        if deficit <= 0:
            continue
        target[kp_id] -= deficit
        while deficit > 0:
            donors = [
                other
                for other in target
                if other != kp_id and available.get(other, 0) - target[other] > 0
            ]
            if not donors:
                break
            donor = max(
                donors, key=lambda other: (available[other] - target[other], -other)
            )
            target[donor] += 1
            deficit -= 1
    return target


def allocate_quotas(
    constraints: PaperConstraints, pool: Sequence[CandidateQuestion]
) -> QuotaPlan:
    """题型/难度/kp 三份配额 + 总分邻域调整 + 缺口借位；只算不选。"""
    total = constraints.total_questions
    base_counts = largest_remainder(constraints.qtype_ratio, total)
    qtype_counts, planned_score, score_out = _adjust_qtype_counts(constraints, base_counts)
    difficulty_alloc = largest_remainder(constraints.difficulty_dist, total)
    kp_alloc = largest_remainder(constraints.kp_weight_map, total)
    target_by_difficulty = _borrow_difficulty(difficulty_alloc, _count_by_difficulty(pool))
    target_by_kp = _borrow_kp(kp_alloc, _count_by_kp(pool))
    warnings = tuple(
        f"题型「{qtype}」按配比取整为 0 题"
        for qtype in QTYPE_ORDER
        if qtype in constraints.qtype_ratio and qtype_counts.get(qtype, 0) == 0
    )
    return QuotaPlan(
        quota_by_qtype=qtype_counts,
        quota_by_difficulty=difficulty_alloc,
        quota_by_kp=kp_alloc,
        target_by_difficulty=target_by_difficulty,
        target_by_kp=target_by_kp,
        planned_total_score=planned_score,
        score_out_of_tolerance=score_out,
        tolerance=_score_tolerance(
            constraints.total_score_target, constraints.score_tolerance_ratio
        ),
        warnings=warnings,
    )


def difficulty_target(mastery: float | None) -> int:
    """掌握度联动（方案 §6.5）：薄弱配基础题、熟练配难题、未评估走中档。"""
    if mastery is None:
        return TARGET_DIFFICULTY_MIDDLE
    value = min(1.0, max(0.0, float(mastery)))
    if value < MASTERY_LOW:
        return TARGET_DIFFICULTY_LOW
    if value > MASTERY_HIGH:
        return TARGET_DIFFICULTY_HIGH
    return TARGET_DIFFICULTY_MIDDLE


def novelty_score(last_done_at: datetime | None, *, now: datetime) -> float:
    """30 天内做过的时间越近越不新颖；近期窗内的题在 prepare_pool 已被硬排除。"""
    if last_done_at is None:
        return 1.0
    _require_aware(now, "now")
    days = (_as_utc(now) - _as_utc(last_done_at)).total_seconds() / 86400.0
    return round(min(1.0, max(0.0, days / NOVELTY_WINDOW_DAYS)), SCORE_PRECISION)


def quality_score(*, verified: bool, origin: str) -> float:
    """答案可信度分档：真题/课本 > 其他已核对 > 未核对 > AI 未核对。"""
    if verified:
        return 1.0 if origin in TRUSTED_ORIGINS else 0.7
    return 0.4 if origin == "ai" else 0.5


def _candidate_mastery(
    candidate: CandidateQuestion, mastery_by_kp: Mapping[int, float]
) -> float:
    weighted = 0.0
    weight_sum = 0.0
    for kp_id, weight in candidate.kp_weights:
        value = max(0.0, float(weight))
        weighted += value * float(mastery_by_kp.get(kp_id, NEUTRAL_MASTERY))
        weight_sum += value
    if weight_sum <= 0:
        return NEUTRAL_MASTERY
    return min(1.0, max(0.0, weighted / weight_sum))


def score_parts(
    *,
    candidate: CandidateQuestion,
    constraints: PaperConstraints,
    mastery_by_kp: Mapping[int, float],
    now: datetime,
) -> ScoreParts:
    """四项加权：难度匹配 + 掌握度匹配 + 新颖度 + 质量（spec §4.4）。"""
    mastery = _candidate_mastery(candidate, mastery_by_kp)
    difficulty_match = round(
        1.0
        - abs(candidate.difficulty - difficulty_target(mastery))
        / (DIFFICULTY_MAX - DIFFICULTY_MIN),
        SCORE_PRECISION,
    )
    mastery_match = round(1.0 - mastery, SCORE_PRECISION)
    novelty = novelty_score(candidate.last_done_at, now=now)
    quality = quality_score(verified=candidate.verified, origin=candidate.origin)
    total = round(
        SCORING_WEIGHTS.difficulty * difficulty_match
        + SCORING_WEIGHTS.mastery * mastery_match
        + SCORING_WEIGHTS.novelty * novelty
        + SCORING_WEIGHTS.quality * quality,
        SCORE_PRECISION,
    )
    return ScoreParts(
        difficulty_match=difficulty_match,
        mastery_match=mastery_match,
        novelty=novelty,
        quality=quality,
        total=total,
    )
