"""S2-5 Markdown → 检索纯文本（spec §6）。

只服务检索，不追求渲染保真：公式符号搜不到且会污染关键词匹配，所以整段去掉；
代码块/行内代码先“冻结”，避免公式与强调规则把代码改坏。
"""
from __future__ import annotations

import re

_FENCED_CODE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_MATH_PATTERNS = (
    re.compile(r"\$\$(.+?)\$\$", re.S),
    re.compile(r"\\\[(.+?)\\\]", re.S),
    re.compile(r"\\\((.+?)\\\)", re.S),
    re.compile(r"\$(.+?)\$", re.S),
)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.M)
_HR = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
_TABLE_PIPE = re.compile(r"\|")
_EMPHASIS_PAIRS = (
    re.compile(r"\*\*(.+?)\*\*", re.S),
    re.compile(r"__(.+?)__", re.S),
    re.compile(r"~~(.+?)~~", re.S),
    re.compile(r"\*(.+?)\*", re.S),
    re.compile(r"(?<![\w])_([^_]+?)_(?![\w])", re.S),
)
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")


def to_plain_text(markdown: str) -> str:
    if not markdown:
        return ""
    stash: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        stash.append(match.group(1).strip())
        return f"\x00{len(stash) - 1}\x00"

    text = _FENCED_CODE.sub(stash_code, markdown)
    text = _INLINE_CODE.sub(stash_code, text)
    for pattern in _MATH_PATTERNS:
        text = pattern.sub(" ", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    for pattern in (_HEADING, _QUOTE, _LIST_MARKER, _HR):
        text = pattern.sub(" ", text)
    text = _TABLE_PIPE.sub(" ", text)
    for pattern in _EMPHASIS_PAIRS:
        text = pattern.sub(r"\1", text)
    text = _ESCAPE.sub(r"\1", text)

    def restore_code(match: re.Match[str]) -> str:
        return stash[int(match.group(1))]

    text = _PLACEHOLDER.sub(restore_code, text)
    return re.sub(r"\s+", " ", text).strip()