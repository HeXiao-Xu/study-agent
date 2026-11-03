"""S4-4 答案比对：规范化、数值容差、选择题 key、多解集合、同义词组。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.gen.compare import match_answers, normalize_answer, parse_number


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$31$", "31"),
        ("$$\\frac{3}{5}$$", "\\frac{3}{5}"),
        (" 答案：$x=2$ 。", "x=2"),
        ("８０％", "80%"),
        ("（２，３）", "(2,3)"),
        ("\\left( x \\right)", "(x)"),
        ("\\dfrac{1}{2}", "\\frac{1}{2}"),
        ("\\text{无解}", "无解"),
        ("3×4", "3*4"),
    ],
)
def test_normalize_answer_variants(raw, expected):
    assert normalize_answer(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("31", Decimal("31")),
        ("-4/5", Decimal("-0.8")),
        ("\\frac{3}{5}", Decimal("0.6")),
        ("80\\%", Decimal("0.8")),
        ("80%", Decimal("0.8")),
        ("0.8", Decimal("0.8")),
        ("\\sqrt{25}", Decimal("5")),
    ],
)
def test_parse_number_supported_forms(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["x=2", "\\sqrt{3}", "3\\sqrt{3}", ""])
def test_parse_number_rejects_non_numeric(raw):
    assert parse_number(raw) is None


def test_match_answers_numbers_with_tolerance():
    assert match_answers("$0.8$", "$0.8000001$")[0] is True


def test_match_answers_numbers_different():
    ok, reason = match_answers("$31$", "$30$")
    assert ok is False
    assert "31" in reason and "30" in reason


def test_match_answers_choice_keys_sets():
    assert match_answers("AC", "A、C")[0] is True
    assert match_answers("AC", "A,C")[0] is True
    assert match_answers("AC", "A")[0] is False


def test_match_answers_multi_solution_sets_ignoring_order():
    assert match_answers("$x=2$ 或 $x=3$", "$x=3$，$x=2$")[0] is True


def test_match_answers_synonyms():
    assert match_answers("无解", "没有解")[0] is True
    assert match_answers("全体实数", "R")[0] is True
    assert match_answers("无解", "全体实数")[0] is False


def test_match_answers_plain_text():
    assert match_answers("单调递减", "单调 递减")[0] is True
    assert match_answers("单调递减", "单调递增")[0] is False