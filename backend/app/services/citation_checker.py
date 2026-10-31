"""S3-6 引用校验：分块、越界编号、未引用块与补充声明。

本模块只做纯文本判断，不连库、不调 LLM；重试由 qa_service 编排。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

CITATION_RE = re.compile(r"\[(\d+)\]")
SUPPLEMENT_PREFIX = "【以下为模型补充，未在你的资料中找到依据】"
LEGACY_SUPPLEMENT_PREFIX = "【补充说明｜非你的资料】"

_HEADING_RE = re.compile(r"^#{1,6}\s")
_LIST_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_FENCE_RE = re.compile(r"^(?:```|~~~)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_MATH_TOKENS = ("$", "\\", "=", "^", "_", "{")
_REFUSAL_MARKERS = ("在你的笔记中没找到相关内容",)
_SEPARATORS = {"---", "***", "___"}


@dataclass(frozen=True)
class CitationCheck:
    context_size: int
    valid_indices: list[int]
    invalid_indices: list[int]
    uncited_blocks: list[str]
    has_content: bool

    @property
    def has_valid_citation(self) -> bool:
        return bool(self.valid_indices)

    @property
    def needs_retry(self) -> bool:
        return bool(
            self.invalid_indices
            or self.uncited_blocks
            or not self.valid_indices
        )

    @property
    def is_clean(self) -> bool:
        return not self.needs_retry


def _normalize(answer: str) -> str:
    return answer.replace("\r\n", "\n").replace("\r", "\n")


def split_blocks(answer: str) -> list[str]:
    """按空行/标题/列表项切块，保留代码围栏整块。"""
    lines = _normalize(answer).split("\n")
    blocks: list[str] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        raw = "\n".join(buffer).strip("\n")
        if raw.strip():
            blocks.append(raw)
        buffer.clear()

    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            if in_fence:
                buffer.append(line)
                flush()
                in_fence = False
            else:
                flush()
                buffer.append(line)
                in_fence = True
            continue
        if in_fence:
            buffer.append(line)
            continue
        if not stripped:
            flush()
            continue
        if (
            _HEADING_RE.match(stripped)
            or _LIST_RE.match(stripped)
            or stripped.startswith(">")
        ):
            flush()
            buffer.append(line)
            continue
        buffer.append(line)

    flush()
    return blocks


def _has_supplement_marker(block: str) -> bool:
    stripped = block.strip()
    if stripped.startswith(">"):
        stripped = stripped.lstrip(">").strip()
    return stripped.startswith(
        (SUPPLEMENT_PREFIX, LEGACY_SUPPLEMENT_PREFIX)
    )


def _is_math_only(block: str) -> bool:
    stripped = block.strip()
    if not stripped or _CJK_RE.search(stripped):
        return False
    if not any(token in stripped for token in _MATH_TOKENS):
        return False
    compact = re.sub(r"\s+", "", stripped)
    if len(compact) < 12:
        return False
    math_chars = set(
        "$\\{}_^=+-*/()[]|.,;:0123456789"
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )
    hits = sum(char in math_chars for char in compact)
    return hits / len(compact) >= 0.9


def _is_skipped(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return True
    if _FENCE_RE.match(stripped) or _HEADING_RE.match(stripped):
        return True
    if _has_supplement_marker(block):
        return True
    if any(marker in stripped for marker in _REFUSAL_MARKERS):
        return True
    if stripped in _SEPARATORS:
        return True
    return _is_math_only(stripped)


def _is_substantive(block: str) -> bool:
    stripped = block.strip()
    if not stripped:
        return False
    if _CJK_RE.search(stripped):
        return True
    return len(re.sub(r"\s+", "", stripped)) >= 20


def _indices(block: str) -> list[int]:
    return [int(match.group(1)) for match in CITATION_RE.finditer(block)]


def check_answer(answer: str, *, context_size: int) -> CitationCheck:
    if context_size < 1:
        raise ValueError("context_size 必须 >= 1")

    valid: set[int] = set()
    invalid: set[int] = set()
    uncited: list[str] = []
    has_content = False

    for block in split_blocks(answer):
        if _is_skipped(block):
            continue
        numbers = _indices(block)
        block_valid = [n for n in numbers if 1 <= n <= context_size]
        block_invalid = [n for n in numbers if not 1 <= n <= context_size]
        valid.update(block_valid)
        invalid.update(block_invalid)
        if not _is_substantive(block):
            continue
        has_content = True
        if not block_valid:
            uncited.append(block)

    return CitationCheck(
        context_size=context_size,
        valid_indices=sorted(valid),
        invalid_indices=sorted(invalid),
        uncited_blocks=uncited,
        has_content=has_content,
    )


def strip_invalid_citations(answer: str, *, context_size: int) -> str:
    text = _normalize(answer)

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return match.group(0) if 1 <= number <= context_size else ""

    return CITATION_RE.sub(replace, text)


def _map_blocks(answer: str, transform: Callable[[str], str]) -> str:
    blocks = split_blocks(answer)
    if not blocks:
        return answer
    out: list[str] = []
    cursor = 0
    for block in blocks:
        start = answer.find(block, cursor)
        if start < 0:
            return transform(answer)
        out.append(answer[cursor:start])
        out.append(transform(block))
        cursor = start + len(block)
    out.append(answer[cursor:])
    return "".join(out)


def annotate_uncited(answer: str, *, context_size: int) -> str:
    text = _normalize(answer)
    check = check_answer(text, context_size=context_size)
    if not check.uncited_blocks:
        return text
    uncited = set(check.uncited_blocks)

    def transform(block: str) -> str:
        if block in uncited and not _has_supplement_marker(block):
            return f"{SUPPLEMENT_PREFIX}\n{block}"
        return block

    return _map_blocks(text, transform)


def build_correction(check: CitationCheck) -> str:
    details: list[str] = []
    if not check.valid_indices:
        details.append("整篇没有合法引用")
    if check.uncited_blocks:
        details.append(f"{len(check.uncited_blocks)} 个实质块没有合法引用")
    if check.invalid_indices:
        joined = "、".join(f"[{n}]" for n in check.invalid_indices[:5])
        details.append(f"存在越界编号 {joined}")
    return (
        "上一次回答未通过引用校验："
        + "；".join(details)
        + f"。本轮只能使用 [1]..[{check.context_size}] 中的编号；"
        "每个知识陈述后必须标注引用；资料不足的补充内容另起一段，"
        f"并以“{SUPPLEMENT_PREFIX}”开头；不要解释校验过程。"
    )