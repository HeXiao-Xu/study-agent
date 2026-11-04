"""S4-7 掌握度模型（方案 §6.6）。

公式定位是「参考 SM-2 / FSRS 的工程化简化」：参数是工程取值，不是拟合结果。
本模块前半部分全是纯函数，便于单测与手推；DB 用例在文件末尾。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

K0 = 0.35
"""单次作答的基础更新幅度；难题带来更小的更新（避免一题定生死）。"""

INITIAL_STABILITY = 2.0
STABILITY_GROW = 1.8
STABILITY_SHRINK = 0.5
STABILITY_MAX = 60.0
STABILITY_MIN = 1.0

INTERVAL_MIN_DAYS = 1
INTERVAL_MAX_DAYS = 30

MASTERY_PRECISION = 3
STABILITY_PRECISION = 2


@dataclass(frozen=True, slots=True)
class MasteryState:
    """掌握度的一次快照；不可变，方便「读 → 算 → 写」而不共享状态。"""

    mastery: float
    attempts: int
    correct_cnt: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


NEW_STATE = MasteryState(
    mastery=0.0,
    attempts=0,
    correct_cnt=0,
    stability=INITIAL_STABILITY,
    last_practice_at=None,
    due_at=None,
)


def effective_k(difficulty: int) -> float:
    """K_eff = K0 / difficulty；难度越界按 1..5 收敛，不让脏数据把公式炸掉。"""
    safe = min(5, max(1, int(difficulty)))
    return K0 / safe


def next_mastery(mastery: float, s: float, k: float) -> float:
    """M ← clamp(M + K_eff·(s − M), 0, 1)。"""
    updated = mastery + k * (s - mastery)
    return round(min(1.0, max(0.0, updated)), MASTERY_PRECISION)


def next_stability(stability: float, s: float) -> float:
    """答对放大间隔、答错缩短；半对（s=0.5）方案没定义，按「不增不减」处理。"""
    if s >= 1.0:
        return round(min(STABILITY_MAX, stability * STABILITY_GROW), STABILITY_PRECISION)
    if s <= 0.0:
        return round(max(STABILITY_MIN, stability * STABILITY_SHRINK), STABILITY_PRECISION)
    return round(stability, STABILITY_PRECISION)


def decayed_mastery(mastery: float, stability: float, *, days: float) -> float:
    """M_t = M·exp(−Δt/S)；未来时间/负间隔按 0 天处理（时钟回拨不该抬高掌握度）。"""
    if days <= 0:
        return round(mastery, MASTERY_PRECISION)
    safe_stability = max(stability, 0.01)
    return round(mastery * math.exp(-days / safe_stability), MASTERY_PRECISION)


def review_interval_days(stability: float, mastery_t: float) -> int:
    """interval = clamp(round(S·M_t), 1, 30) 天。"""
    raw = int(round(stability * mastery_t))
    return max(INTERVAL_MIN_DAYS, min(INTERVAL_MAX_DAYS, raw))


def next_state(
    state: MasteryState, *, s: float, difficulty: int, now: datetime
) -> MasteryState:
    """一次作答后的新状态；刚作答时 Δt=0，到期间隔用当前 M 而不是衰减后的值。"""
    mastery = next_mastery(state.mastery, s, effective_k(difficulty))
    stability = next_stability(state.stability, s)
    due_at = now + timedelta(days=review_interval_days(stability, mastery))
    return MasteryState(
        mastery=mastery,
        attempts=state.attempts + 1,
        correct_cnt=state.correct_cnt + (1 if s >= 1.0 else 0),
        stability=stability,
        last_practice_at=now,
        due_at=due_at,
    )