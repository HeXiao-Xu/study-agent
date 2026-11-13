"""S5-1 组卷内核单测：纯函数、无数据库、无网络。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.paper_service import (
    DEFAULT_SCORE_BY_QTYPE,
    CandidateQuestion,
    PaperConstraints,
    PaperPlanError,
    prepare_pool,
)

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
KP_A, KP_B = 101, 102


def cand(
    qid: int,
    *,
    qtype: str = "解答",
    difficulty: int = 3,
    kps: list[tuple[int, float]] | None = None,
    verified: bool = True,
    origin: str = "exam",
    last_done_at: datetime | None = None,
) -> CandidateQuestion:
    return CandidateQuestion(
        question_id=qid,
        qtype=qtype,
        difficulty=difficulty,
        kp_weights=tuple(kps if kps is not None else [(KP_A, 1.0)]),
        verified=verified,
        origin=origin,
        last_done_at=last_done_at,
    )


def make_constraints(**overrides) -> PaperConstraints:
    params = dict(
        kp_ids=(KP_A,),
        total_questions=10,
        qtype_ratio={"解答": 1.0},
        difficulty_dist={3: 1.0},
        total_score_target=80,
        seed=7,
    )
    params.update(overrides)
    return PaperConstraints(**params)


def many(count: int, *, start: int = 1, **kwargs) -> list[CandidateQuestion]:
    return [cand(start + index, **kwargs) for index in range(count)]


def mixed_pool() -> list[CandidateQuestion]:
    """12 单选 + 6 填空 + 9 解答，全部 d=3、同挂 KP_A（够 20 题配额）。"""
    pool: list[CandidateQuestion] = []
    next_id = 1
    for qtype, count in (("单选", 12), ("填空", 6), ("解答", 9)):
        for _ in range(count):
            pool.append(cand(next_id, qtype=qtype, difficulty=3))
            next_id += 1
    return pool


def test_constraints_expose_default_score_map_and_kp_weights() -> None:
    constraints = make_constraints()
    assert constraints.score_map == DEFAULT_SCORE_BY_QTYPE
    assert constraints.kp_weight_map == {KP_A: 1.0}


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"total_questions": 0}, "total_questions"),
        ({"kp_ids": ()}, "kp_ids"),
        ({"kp_ids": (KP_A, KP_A)}, "kp_ids"),
        ({"qtype_ratio": {}}, "qtype_ratio"),
        ({"qtype_ratio": {"判断题": 1.0}}, "qtype_ratio"),
        ({"qtype_ratio": {"单选": 0.0}}, "qtype_ratio"),
        ({"difficulty_dist": {}}, "difficulty_dist"),
        ({"difficulty_dist": {6: 1.0}}, "difficulty_dist"),
        ({"difficulty_dist": {3: -1.0}}, "difficulty_dist"),
        ({"score_by_qtype": {"单选": 3, "填空": 4, "解答": 8}}, "score_by_qtype"),
        ({"score_by_qtype": {"单选": 3, "多选": 4, "填空": 4, "解答": 0}}, "score_by_qtype"),
        ({"score_tolerance_ratio": -0.1}, "score_tolerance_ratio"),
        ({"exclude_recent_days": -1}, "exclude_recent_days"),
        ({"total_score_target": 0}, "total_score_target"),
        ({"kp_weights": {999: 1.0}}, "kp_weights"),
        ({"kp_weights": {KP_A: 0.0}}, "kp_weights"),
    ],
)
def test_constraints_reject_invalid_input(overrides, message) -> None:
    with pytest.raises(PaperPlanError, match=message):
        make_constraints(**overrides)


def test_prepare_pool_dedupes_and_keeps_first() -> None:
    constraints = make_constraints(difficulty_dist={2: 1.0})
    pool, excluded = prepare_pool(
        constraints,
        [cand(1, difficulty=2), cand(1, difficulty=3), cand(2, difficulty=2)],
        now=NOW,
    )
    assert [item.question_id for item in pool] == [1, 2]
    assert pool[0].difficulty == 2
    assert excluded == 0


def test_prepare_pool_drops_candidates_without_constrained_kp() -> None:
    constraints = make_constraints(kp_ids=(KP_A,))
    pool, _ = prepare_pool(
        constraints,
        [cand(1, kps=[(KP_B, 1.0)]), cand(2, kps=[(KP_A, 0.8), (KP_B, 0.5)])],
        now=NOW,
    )
    assert [item.question_id for item in pool] == [2]
    assert pool[0].kp_weights == ((KP_A, 0.8),)


def test_prepare_pool_excludes_recent_and_keeps_old() -> None:
    constraints = make_constraints()
    candidates = many(7, start=1, last_done_at=NOW - timedelta(days=20)) + many(
        3, start=101, last_done_at=NOW - timedelta(days=3)
    )
    pool, excluded = prepare_pool(constraints, candidates, now=NOW)
    assert [item.question_id for item in pool] == list(range(1, 8))
    assert excluded == 3


def test_candidate_with_unknown_qtype_raises() -> None:
    with pytest.raises(PaperPlanError, match="题型"):
        prepare_pool(make_constraints(), [cand(1, qtype="判断题")], now=NOW)


def test_candidate_with_invalid_difficulty_raises() -> None:
    with pytest.raises(PaperPlanError, match="难度"):
        prepare_pool(make_constraints(), [cand(1, difficulty=6)], now=NOW)


def test_prepare_pool_rejects_naive_now() -> None:
    with pytest.raises(PaperPlanError, match="now"):
        prepare_pool(make_constraints(), [cand(1)], now=datetime(2026, 11, 13, 9, 0))


def test_prepare_pool_treats_naive_last_done_at_as_utc() -> None:
    constraints = make_constraints()
    naive = (NOW - timedelta(days=3)).replace(tzinfo=None)
    pool, excluded = prepare_pool(constraints, [cand(1, last_done_at=naive)], now=NOW)
    assert pool == ()
    assert excluded == 1