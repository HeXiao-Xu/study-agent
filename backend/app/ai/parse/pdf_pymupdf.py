"""PyMuPDF 兜底解析器 + 扫描版检测（spec §5.1 / §5.3）。

为什么 heading_path 恒为空：用字号/加粗猜标题是任务卡禁止的启发式；
兜底路径诚实降级——有页码、有文本、无层级（spec 设计决策 2）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pymupdf

from app.ai.parse.base import DocumentParser
from app.ai.parse.models import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

# 字体 ToUnicode 缺失时控制字符会漏进文本层（实测：reportlab+宋体的 ⊆ 提取为 \x00）。
# 保留 \t\n\r（正常空白），清掉其余 C0 控制符与 DEL。
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(text: str) -> str:
    """去掉文本层的控制字符噪声（对 RAG 是纯污染）。"""
    return _CTRL_RE.sub("", text)


def detect_scanned(path: Path, sample_pages: int = 10, min_chars: int = 50) -> bool:
    """前 N 页（不足取全部）严格多数页可抽文本 < min_chars → 判扫描版。

    先判断再决定（任务卡坑①）：扫描版不浪费 Docling 算力，直接留给下一任务的图片识别。
    """
    with pymupdf.open(path) as doc:
        count = min(len(doc), sample_pages)
        if count == 0:
            return True
        poor = sum(1 for i in range(count) if len(doc[i].get_text("text").strip()) < min_chars)
        return poor * 2 > count


class PyMuPDFParser(DocumentParser):
    name = "pymupdf"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        with pymupdf.open(path) as doc:
            for page_no, page in enumerate(doc, start=1):
                # get_text("blocks") 元组: (x0, y0, x1, y1, text, block_no, block_type)；0=文本块
                for raw in page.get_text("blocks"):
                    if raw[6] != 0:
                        continue
                    text = _sanitize(raw[4]).strip()
                    if text:
                        blocks.append(ParsedBlock(text=text, page_no=page_no))
        return ParsedDocument(source=str(path), parser="pymupdf", blocks=blocks)
