"""S4-7 掌握度公式内核（方案 §6.6）：答对提升、答错下降、遗忘衰减、间隔变长。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.mastery_service import (
    INTERVAL_MAX_DAYS,
    INTERVAL_MIN_DAYS,
    K0,
    NEW_STATE,
    STABILITY_MAX,
    STABILITY_MIN,
    MasteryState,
    decayed_mastery,
    effective_k,
    next_mastery,
    next_stability,
    next_state,
    review_interval_days,
)

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def test_effective_k_divides_by_difficulty() -> None:
    assert K0 == 0.35
    assert effective_k(1) == pytest.approx(0.35)
    assert effective_k(3) == pytest.approx(0.1167, abs=1e-4)
    assert effective_k(5) == pytest.approx(0.07)


def test_effective_k_clamps_out_of_range_difficulty() -> None:
    # questions.difficulty 有 CHECK 1..5，但历史/脏数据不应让公式炸掉
    assert effective_k(0) == pytest.approx(0.35)
    assert effective_k(99) == pytest.approx(0.07)


def test_first_correct_raises_mastery_from_zero() -> None:
    """场景 1：答对提升（d=3 → K_eff=0.35/3）。"""
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    assert state.mastery == pytest.approx(0.117)
    assert state.attempts == 1
    assert state.correct_cnt == 1
    assert state.stability == pytest.approx(3.6)
    assert state.last_practice_at == NOW
    assert state.due_at > NOW


def test_second_correct_raises_again() -> None:
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=1))
    assert state.mastery == pytest.approx(0.220)


def test_wrong_answer_lowers_mastery() -> None:
    """场景 2：答错下降。"""
    state = MasteryState(
        mastery=0.5,
        attempts=3,
        correct_cnt=2,
        stability=5.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    after = next_state(state, s=0.0, difficulty=3, now=NOW + timedelta(days=2))
    assert after.mastery == pytest.approx(0.442)
    assert after.stability == pytest.approx(2.5)


def test_mastery_never_goes_negative() -> None:
    state = MasteryState(
        mastery=0.05,
        attempts=1,
        correct_cnt=0,
        stability=2.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    assert next_state(state, s=0.0, difficulty=3, now=NOW).mastery == pytest.approx(0.044)
    assert next_mastery(0.0, 0.0, 0.35) == 0.0


def test_mastery_caps_at_one() -> None:
    assert next_mastery(1.0, 1.0, 0.35) == 1.0
    assert next_mastery(0.99, 1.0, 0.35) <= 1.0


def test_decay_after_ten_days() -> None:
    """场景 3：长时间不练衰减。"""
    assert decayed_mastery(0.8, 10.0, days=10.0) == pytest.approx(0.294)
    assert decayed_mastery(0.8, 10.0, days=0.0) == pytest.approx(0.8)
    assert decayed_mastery(0.8, 10.0, days=-5.0) == pytest.approx(0.8)


def test_stability_growth_and_shrink_bounds() -> None:
    assert next_stability(2.0, 1.0) == pytest.approx(3.6)
    assert next_stability(40.0, 1.0) == pytest.approx(STABILITY_MAX)
    assert next_stability(2.0, 0.0) == pytest.approx(1.0)
    assert next_stability(1.2, 0.0) == pytest.approx(STABILITY_MIN)


def test_half_correct_keeps_stability_and_does_not_count() -> None:
    state = MasteryState(
        mastery=0.4,
        attempts=2,
        correct_cnt=1,
        stability=5.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    after = next_state(state, s=0.5, difficulty=2, now=NOW)
    assert after.stability == pytest.approx(5.0)
    assert after.correct_cnt == 1
    # d=2 → K_eff=0.175；M = 0.4 + 0.175×(0.5−0.4) = 0.4175 → 0.418
    assert after.mastery == pytest.approx(0.418)


def test_interval_grows_with_repeated_success() -> None:
    """场景 4：连续答对间隔变长。"""
    state = NEW_STATE
    intervals = []
    for day in range(5):
        state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=day))
        intervals.append((state.due_at - state.last_practice_at).days)
    assert state.mastery == pytest.approx(0.462)
    # 每步各自四舍五入：2 → 3.6 → 6.48 → 11.66 → 20.99 → 37.78
    assert state.stability == pytest.approx(37.78)
    assert intervals[0] == 1
    assert intervals[-1] == 17
    assert intervals == sorted(intervals)


def test_review_interval_clamps() -> None:
    assert review_interval_days(2.0, 0.0) == INTERVAL_MIN_DAYS
    assert review_interval_days(60.0, 1.0) == INTERVAL_MAX_DAYS
    assert review_interval_days(37.78, 0.462) == 17