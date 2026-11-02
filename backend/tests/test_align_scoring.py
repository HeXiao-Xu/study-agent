"""S2-10 打分纯函数（方案 6.2）。"""
from __future__ import annotations

import pytest

from app.ai.align.scoring import (
    Candidate,
    ancestor_names,
    classify,
    combine,
    cosine,
    keyword_score,
    tree_prior,
)


def test_combine_uses_fixed_weights() -> None:
    assert combine(1.0, 1.0, 1.0) == 1.0
    assert combine(0.0, 0.0, 0.0) == 0.0
    assert combine(0.5, 1.0, 0.0) == pytest.approx(0.6)


def test_classify_boundaries() -> None:
    assert classify(0.75) == "auto"
    assert classify(0.749) == "pending"
    assert classify(0.55) == "pending"
    assert classify(0.549) == "drop"


def test_keyword_score_full_name_hit() -> None:
    assert keyword_score("函数的单调性", "今天复习函数的单调性判定") == 1.0


def test_keyword_score_core_term_hit() -> None:
    assert keyword_score("函数的单调性", "讨论单调性时注意定义域") == 0.6
    assert keyword_score("平面向量的数量积", "数量积的几何意义") == 0.6


def test_keyword_score_miss() -> None:
    assert keyword_score("函数的单调性", "数列求和错位相减") == 0.0


def test_tree_prior_ancestor_in_tags() -> None:
    assert tree_prior(3, ["函数", "函数的单调性"], ["函数"], "单调性复习") == 1.0


def test_tree_prior_ancestor_in_title() -> None:
    assert tree_prior(3, ["三角函数", "解三角形"], [], "解三角形专题") == 1.0


def test_tree_prior_module_level_without_tags() -> None:
    assert tree_prior(2, ["函数"], [], "随手记") == 0.3


def test_tree_prior_leaf_without_tags() -> None:
    assert tree_prior(3, ["函数", "函数的单调性"], [], "随手记") == 0.0


def test_candidate_score_and_classify() -> None:
    candidate = Candidate(
        kp_id=1,
        code="MATH-FUNC-02",
        name="函数的单调性",
        path="函数 / 函数的单调性",
        cos=0.8,
        keyword=1.0,
        prior=0.3,
    )
    assert candidate.score == pytest.approx(0.81)
    assert classify(candidate.score) == "auto"


def test_cosine_identical_and_orthogonal() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_guards_empty_and_mismatch() -> None:
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 2.0], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_clamped_to_unit_interval() -> None:
    assert 0.0 <= cosine([3.0, 4.0], [3.0, 4.0]) <= 1.0


class _Node:
    def __init__(self, node_id: int, name: str, parent_id: int | None) -> None:
        self.id = node_id
        self.name = name
        self.parent_id = parent_id


def test_ancestor_names_walks_to_root() -> None:
    nodes = {1: _Node(1, "函数", None), 2: _Node(2, "单调性", 1), 3: _Node(3, "最值", 2)}
    assert ancestor_names(nodes[3], nodes) == ["单调性", "函数"]
    assert ancestor_names(nodes[1], nodes) == []


def test_ancestor_names_stops_on_cycle() -> None:
    # 成环数据不无限循环：靠 guard 10 层收敛，故长度上界是 10 而非 2。
    nodes = {1: _Node(1, "A", 2), 2: _Node(2, "B", 1)}
    assert len(ancestor_names(nodes[1], nodes)) <= 10