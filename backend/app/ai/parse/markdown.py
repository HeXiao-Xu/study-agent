"""S3-1 笔记 Markdown → 解析块（spec §4）。

笔记没有可解析的文件，但 S1-2 切片器只认 ParsedBlock；这里把 Markdown
拆成标题块 + 段落/表格/代码块，标题路径交给切片器组织章节。
标题块文本必须等于所属小节 heading_path 的末元素，S1-2 才会把它并进小节。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.parse.models import ParsedBlock, ParsedDocument

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_CLOSING_HASH_RE = re.compile(r"[ \t]+#+[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


@dataclass
class _Item:
    """内部条目：heading 只为等 S1-2 合并；空小节的 heading 最后丢弃。"""

    kind: str  # heading / body
    text: str
    path: list[str]


def _strip_images(text: str) -> str:
    """图片 URL 不进入检索正文；alt 保留，避免整段空掉。"""
    return _IMAGE_RE.sub(lambda match: match.group(1), text)


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def _current_path(stack: list[tuple[int, str]]) -> list[str]:
    return [title for _, title in stack]


def parse_markdown_text(text: str, *, source: str) -> ParsedDocument:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    items: list[_Item] = []
    stack: list[tuple[int, str]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading is not None:
            level = len(heading.group(1))
            title = _CLOSING_HASH_RE.sub("", heading.group(2)).strip()
            index += 1
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            items.append(_Item("heading", title, _current_path(stack)))
            continue

        fence = _FENCE_RE.match(line)
        if fence is not None:
            char = fence.group(1)[0]
            buffer = [line]
            index += 1
            while index < len(lines):
                buffer.append(lines[index])
                closing = lines[index].strip()
                index += 1
                if closing.startswith(char * 3):
                    break
            items.append(_Item("body", "\n".join(buffer).strip(), _current_path(stack)))
            continue

        if _is_table_line(line):
            buffer = []
            while index < len(lines) and _is_table_line(lines[index]):
                buffer.append(lines[index].rstrip())
                index += 1
            items.append(_Item("body", "\n".join(buffer), _current_path(stack)))
            continue

        buffer = []
        while index < len(lines):
            current = lines[index]
            if not current.strip() or _HEADING_RE.match(current) or _FENCE_RE.match(current):
                break
            buffer.append(current.rstrip())
            index += 1
        body = _strip_images("\n".join(buffer)).strip()
        if body:
            items.append(_Item("body", body, _current_path(stack)))

    blocks: list[ParsedBlock] = []
    for position, item in enumerate(items):
        if item.kind == "heading":
            following = items[position + 1] if position + 1 < len(items) else None
            if following is None or following.kind == "heading":
                continue
        blocks.append(
            ParsedBlock(text=item.text, page_no=None, heading_path=list(item.path))
        )
    return ParsedDocument(source=source, parser="text", blocks=blocks)