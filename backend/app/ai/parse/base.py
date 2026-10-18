"""可替换解析器契约（任务卡要求 5：抽象接口，Docling/PyMuPDF/docx 都实现它）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from app.ai.parse.models import ParsedDocument


class DocumentParser(ABC):
    name: ClassVar[str]

    @abstractmethod
    def supports(self, path: Path) -> bool:
        """按扩展名判断本解析器是否处理该文件。"""

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """解析失败直接抛异常；降级决策统一由门面负责（spec §6）。"""
