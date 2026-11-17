"""S6-1 calculator：只对数字算式求值，AST 白名单拒绝一切可执行内容。"""
from __future__ import annotations

import ast
import math

from pydantic import Field

from app.ai.agents.tools.base import ToolContext, ToolInput, ToolOutput, ToolSpec
from app.core.exceptions import InvalidParamError

MAX_LENGTH = 200
MAX_EXPONENT = 100
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


class CalculatorIn(ToolInput):
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)


class CalculatorOut(ToolOutput):
    expression: str
    value: float
    text: str
    exact: bool


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        # bool 是 int 的子类，必须显式排除，避免 True + 1 被当成 2
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise InvalidParamError("只支持数字算式")
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left, right = _eval(node.left), _eval(node.right)
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return float(left // right)
            if isinstance(node.op, ast.Mod):
                return float(left % right)
            if abs(right) > MAX_EXPONENT:
                raise InvalidParamError("乘方指数过大")
            return float(left**right)
        except ZeroDivisionError as exc:
            raise InvalidParamError("不能除以 0") from exc
        except OverflowError as exc:
            raise InvalidParamError("计算结果超出范围") from exc
    raise InvalidParamError("只支持四则、整除、取模与乘方")


def evaluate_expression(expression: str) -> CalculatorOut:
    clean = expression.strip()
    if not clean:
        raise InvalidParamError("expression 不能为空")
    try:
        tree = ast.parse(clean, mode="eval")
    except SyntaxError as exc:
        raise InvalidParamError("算式格式不正确") from exc
    value = _eval(tree)
    if not math.isfinite(value):
        raise InvalidParamError("计算结果超出范围")
    return CalculatorOut(
        expression=clean,
        value=value,
        text=format(value, ".12g"),
        exact=float(value).is_integer(),
    )


def _handler(ctx: ToolContext, data: CalculatorIn) -> CalculatorOut:
    return evaluate_expression(data.expression)


SPEC = ToolSpec(
    name="calculator",
    description=(
        "用途：对算术表达式求值，避免心算错误。"
        "参数 expression 只支持数字、括号、+ - * / // % ** 与一元正负号，不接受变量或函数。"
        "返回 value（浮点）、text（12 位有效数字）与 exact（是否为整数）。"
    ),
    input_model=CalculatorIn,
    output_model=CalculatorOut,
    handler=_handler,
)