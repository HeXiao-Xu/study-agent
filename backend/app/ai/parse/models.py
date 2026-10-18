"""S1-1 解析统一结构（契约：docs/spec/s1-1-doc-parse.md §2）。

任务卡的 [{text, page_no, heading_path, type}] 列表 = ParsedDocument.blocks；
外层信封（parser/is_scanned/degraded_reason）是审计信息。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

ParserName = Literal["docling", "pymupdf", "docx"]


class BlockType(str, Enum):
    """块类型。question 枚举保留但由 S1-2 切片器填充（spec 设计决策 3：有依据才标）。"""

    text = "text"
    formula = "formula"
    question = "question"


class ParsedBlock(BaseModel):
    text: str  # 表格转 Markdown 后也塞这里
    page_no: int | None  # 1-based；None 仅用于 docx（Word 分页由渲染器决定，文件里不存在）
    heading_path: list[str] = []  # 标题层级链；抽不到就空列表，禁止编造
    type: BlockType = BlockType.text


class ParsedDocument(BaseModel):
    source: str
    parser: ParserName
    is_scanned: bool = False
    degraded_reason: str | None = None  # 仅降级（docling→pymupdf）或扫描版提示时非空
    blocks: list[ParsedBlock] = []
