"""S5-2 组卷服务：约束归一化、候选装载、生成/换题/保存/读取（FakeSession，不连库）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.exceptions import InvalidParamError
from app.models.paper import Paper
from app.schemas.paper import PaperGenerateIn
from app.services import paper_plan_service

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


class FakeSession:
    """按调用顺序喂 execute 结果：服务查询顺序确定，顺序断言最直观。"""

    def __init__(self, *, results=None, paper=None) -> None:
        self.results = [list(rows) for rows in (results or [])]
        self.statements: list[object] = []
        self.added: list[object] = []
        self.committed = 0
        self.paper = paper

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper is not None and self.paper.id == pk else None
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        obj.id = 7
        obj.created_at = NOW


def make_payload(**overrides) -> PaperGenerateIn:  # noqa: ANN003
    data = {
        "kp_ids": [101],
        "total_questions": 2,
        "qtype_ratio": {"单选": 1.0},
        "difficulty_dist": {2: 1.0},
        "total_score": 6,
        "exclude_recent_days": 14,
        "seed": 7,
    }
    data.update(overrides)
    return PaperGenerateIn(**data)


def candidate_rows():
    """load_candidates 第一条 SQL 的行：(id, qtype, difficulty, verified, origin, kp_id, weight)。"""
    return [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (502, "单选", 2, False, "upload", 101, Decimal("0.800000")),
        (503, "解答", 3, True, "textbook", 101, Decimal("1.000000")),
    ]


def test_build_constraints_filters_zero_qtype_and_normalizes_seed():
    payload = make_payload(qtype_ratio={"单选": 0.5, "多选": 0.0, "解答": 0.5})
    constraints = paper_plan_service.build_constraints(payload)
    assert dict(constraints.qtype_ratio) == {"单选": 0.5, "解答": 0.5}
    assert constraints.seed == 7
    assert constraints.total_score_target == 6


def test_build_constraints_generates_seed_in_range():
    constraints = paper_plan_service.build_constraints(make_payload(seed=None))
    assert 0 <= constraints.seed <= 2**31 - 1


def test_generate_in_rejects_all_zero_qtype_ratio():
    # 零权重在 schema 层就被挡住，build_constraints 里那层过滤只是防御
    with pytest.raises(ValidationError, match="至少一个题型配比"):
        make_payload(qtype_ratio={"单选": 0})


def test_generate_in_rejects_kp_weight_outside_selection():
    with pytest.raises(ValidationError, match="kp_weights"):
        make_payload(kp_weights={999: 1.0})


def test_paper_save_in_rejects_duplicate_question_ids():
    from app.schemas.paper import PaperSaveIn

    with pytest.raises(ValidationError, match="重复"):
        PaperSaveIn(
            title="t",
            constraint=make_payload(),
            question_ids=[501, 501],
        )


def test_load_candidates_groups_multiple_kps_and_takes_latest_done():
    rows = [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (501, "单选", 2, True, "exam", 102, Decimal("0.600000")),
    ]
    old = NOW - timedelta(days=40)
    fresh = NOW - timedelta(days=3)
    session = FakeSession(
        results=[
            rows,
            [(501, fresh, old)],
            [],
        ]
    )
    constraints = paper_plan_service.build_constraints(make_payload(kp_ids=[101, 102]))
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert [item.question_id for item in data.candidates] == [501]
    assert dict(data.candidates[0].kp_weights) == {101: 1.0, 102: 0.6}
    assert data.candidates[0].last_done_at == fresh
    assert data.mastery_by_kp == {}


def test_load_candidates_empty_rows_yields_empty_pool():
    session = FakeSession(results=[[], [], []])
    constraints = paper_plan_service.build_constraints(make_payload())
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert data.candidates == ()
    assert data.mastery_by_kp == {}