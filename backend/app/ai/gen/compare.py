"""S4-4 复算自检的比对层：只做"确定等价"的规范化，不做数学变形。

判定顺序（spec §5.3）：选择题 key 集合 → 数值容差 → 同义词组 → 多解集合 → 字符串。
一致即放行；不一致返回原因，写进 `rejected[].reason` 供验收追查。
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

REL_TOL = Decimal("1e-6")

_FENCE = re.compile(r"```[a-zA-Z]*")
_TEXT_WRAP = re.compile(r"\\(?:text|mathrm)\{([^{}]*)\}")
_PREFIX = re.compile(r"^(?:答案|答|所以|因此|故|综上)\s*[:：]?\s*")
_SPACE = re.compile(r"\s+")
_TRAILING = re.compile(r"[。.;；]+$")
_PERCENT = re.compile(r"^(-?\d+(?:\.\d+)?)\\?%$")
_SIMPLE_FRAC = re.compile(r"^(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)$")
_LATEX_FRAC = re.compile(r"^\\frac\{(-?\d+(?:\.\d+)?)\}\{(-?\d+(?:\.\d+)?)\}$")
_SQRT = re.compile(r"^\\sqrt\{(\d+(?:\.\d+)?)\}$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_OPTION_KEYS = re.compile(r"^[A-H]{1,8}$")
_SET_SEP = re.compile(r"[或,、;；]")
_KEY_SEP = re.compile(r"[,、;；]")

_SYNONYM_GROUPS = (
    frozenset({"无解", "没有解", "不存在", "无实数解"}),
    frozenset({"全体实数", "任意实数", "R", "\\mathbb{R}", "(-∞,+∞)"}),
    frozenset({"无穷多解", "无数解"}),
)


def normalize_answer(text: str) -> str:
    # NFKC 一次性把全角数字/字母/括号/逗号/百分号折成半角；
    # 自己维护 translate 表会漏（首版就漏了全角数字，测试直接抓到）。
    clean = unicodedata.normalize("NFKC", (text or "").strip())
    clean = _FENCE.sub("", clean).replace("$", "")
    clean = clean.replace("−", "-").replace("－", "-")
    clean = _TEXT_WRAP.sub(r"\1", clean)
    clean = clean.replace("\\left", "").replace("\\right", "")
    clean = clean.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    clean = clean.replace("\\cdot", "*").replace("×", "*").replace("÷", "/")
    clean = re.sub(r"\\[,;:!]", "", clean)
    clean = clean.replace("√", "\\sqrt")
    clean = _SPACE.sub("", clean)
    clean = _PREFIX.sub("", clean)
    return _TRAILING.sub("", clean)


def parse_number(text: str) -> Decimal | None:
    clean = normalize_answer(text)
    if not clean:
        return None
    match = _PERCENT.match(clean)
    if match:
        return _to_decimal(match.group(1)) / 100
    match = _LATEX_FRAC.match(clean) or _SIMPLE_FRAC.match(clean)
    if match:
        numerator, denominator = _to_decimal(match.group(1)), _to_decimal(match.group(2))
        if denominator == 0:
            return None
        return numerator / denominator
    if _NUMBER.match(clean):
        return _to_decimal(clean)
    match = _SQRT.match(clean)
    if match:
        root = _to_decimal(match.group(1)).sqrt()
        # 只有完全平方才当数值比，否则留给字符串比较（3√3 这类不要硬算成近似值）
        return root if root == root.to_integral_value() else None
    return None


def match_answers(expected: str, actual: str) -> tuple[bool, str]:
    left, right = normalize_answer(expected), normalize_answer(actual)
    if not left or not right:
        return False, "有一边答案为空"
    left_keys, right_keys = _option_key_set(left), _option_key_set(right)
    if left_keys is not None and right_keys is not None:
        return (left_keys == right_keys), f"选择题 key：{left} vs {right}"
    left_num, right_num = parse_number(left), parse_number(right)
    if left_num is not None and right_num is not None:
        return _numbers_close(left_num, right_num), f"数值：{left} vs {right}"
    left_group, right_group = _synonym_group(left), _synonym_group(right)
    if left_group is not None and right_group is not None:
        return (left_group is right_group), f"同义词：{left} vs {right}"
    left_parts, right_parts = _solution_parts(left), _solution_parts(right)
    if len(left_parts) > 1 or len(right_parts) > 1:
        return (left_parts == right_parts), f"多解集合：{left} vs {right}"
    return (left == right), f"复算答案不一致：{expected} ≠ {actual}"


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:  # pragma: no cover - 正则已限定形态
        raise ValueError(f"不是数值：{raw}") from None


def _numbers_close(left: Decimal, right: Decimal) -> bool:
    diff = abs(left - right)
    if left == 0 or right == 0:
        return diff <= REL_TOL
    return diff / max(abs(left), abs(right)) <= REL_TOL


def _option_key_set(text: str) -> frozenset[str] | None:
    """`AC` / `A,C` / `A、C` 都归一成 key 集合；非纯 key 返回 None 交给后续规则。"""
    compact = _KEY_SEP.sub("", text)
    if _OPTION_KEYS.match(compact):
        return frozenset(compact)
    return None


def _synonym_group(text: str) -> frozenset[str] | None:
    for group in _SYNONYM_GROUPS:
        if text in group:
            return group
    return None


def _solution_parts(text: str) -> frozenset[str]:
    parts = [part for part in _SET_SEP.split(text) if part]
    return frozenset(parts)