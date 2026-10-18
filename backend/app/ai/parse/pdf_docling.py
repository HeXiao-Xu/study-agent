"""Docling 适配器（spec §5.2 + 设计决策 1）。

消费 DoclingDocument 结构化对象而非其 Markdown 导出——统一结构需要每块
页码（prov），Markdown 序列化会丢页码。
docling 在 parse() 内延迟导入：未安装时 ImportError 才能被门面接住走降级链。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from app.ai.parse.base import DocumentParser
from app.ai.parse.models import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

# 页眉页脚/脚注/图片/题注是检索噪声，直接丢弃（spec §5.2）
_SKIP_LABELS = {"page_header", "page_footer", "footnote", "picture", "caption"}


class DoclingParser(DocumentParser):
    name: ClassVar[str] = "docling"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        # 延迟导入（spec §6）：docling 缺失时让 ImportError 冒给门面降级
        from docling.document_converter import DocumentConverter

        document = DocumentConverter().convert(str(path)).document
        blocks = self._items_to_blocks(document)
        return ParsedDocument(source=str(path), parser="docling", blocks=blocks)

    # ---- 以下方法不 import docling 类型，用 duck-typing 便于 mock 测试 ----

    def _items_to_blocks(self, doc: object) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        for item, level in self._iter_items(doc):
            label = getattr(item, "label", None)
            text = (getattr(item, "text", None) or "").strip()
            if label in ("title", "section_header"):
                if not text:
                    continue
                # title 视作第 0 层（重置栈）；section_header 按树深度截断再压入
                depth = 0 if label == "title" else (level if level is not None else 1)
                headings = headings[:depth]
                headings.append(text)
                blocks.append(
                    ParsedBlock(text=text, page_no=self._page_of(item), heading_path=list(headings[:-1]))
                )
                continue
            if label in _SKIP_LABELS:
                continue
            if hasattr(item, "export_to_markdown"):  # TableItem
                blocks.append(
                    ParsedBlock(
                        text=item.export_to_markdown(),
                        page_no=self._page_of(item),
                        heading_path=list(headings),
                    )
                )
                continue
            if text:
                blocks.append(ParsedBlock(text=text, page_no=self._page_of(item), heading_path=list(headings)))
        return blocks

    @staticmethod
    def _iter_items(doc: object) -> Iterator[tuple[object, int | None]]:
        """兼容两种 iterate_items 形状：(item, level) 元组 或 裸 item。"""
        for raw in doc.iterate_items():  # type: ignore[attr-defined]
            if isinstance(raw, tuple):
                item, level = raw[0], raw[1] if isinstance(raw[1], int) else None
                yield item, level
            else:
                yield raw, None

    @staticmethod
    def _page_of(item: object) -> int | None:
        prov = getattr(item, "prov", None)
        first = prov[0] if isinstance(prov, (list, tuple)) and prov else prov
        page = getattr(first, "page_no", None) or getattr(first, "pageno", None)
        return int(page) if page is not None else None
