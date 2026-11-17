"""S6-1 calculator：AST 白名单求值。"""
from __future__ import annotations

import pytest

from app.ai.agents.tools import calculator
from app.core.exceptions import InvalidParamError


def test_calculator_arithmetic_precedence_and_parens():
    out = calculator.evaluate_expression("2 + 3 * (4 - 1)")
    assert out.value == pytest.approx(11)
    assert out.exact is True


def test_calculator_supports_floor_mod_power_and_unary():
    assert calculator.evaluate_expression("-7 // 2").value == -4
    assert calculator.evaluate_expression("2 ** 10").value == 1024
    assert calculator.evaluate_expression("7 % 4").value == 3


def test_calculator_returns_text_with_twelve_significant_digits():
    out = calculator.evaluate_expression("1 / 3")
    assert out.value == pytest.approx(1 / 3)
    assert out.text == "0.333333333333"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "sqrt(4)",
        "x + 1",
        "1 if 1 else 2",
        "'a' + 'b'",
        "True + 1",
        "1j + 1",
        "1 << 2",
    ],
)
def test_calculator_rejects_non_whitelisted_nodes(expression):
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression(expression)


def test_calculator_rejects_division_by_zero_and_overflow():
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression("1 / 0")
    with pytest.raises(InvalidParamError):
        calculator.evaluate_expression("9 ** 101")