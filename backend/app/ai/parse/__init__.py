"""解析门面：parse_document 是全项目唯一解析入口（spec §3 架构图）。

降级决策集中在这里，适配器自身不吞异常（spec §6）：
Docling ImportError / 运行异常 → 打 WARNING（带原因与文件）→ PyMuPDF 兜底。
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.ai.parse.pdf_pymupdf import PyMuPDFParser, detect_scanned
from app.core.config import get_settings
from app.core.exceptions import InvalidParamError

logger = logging.getLogger(__name__)


def parse_plain_text(path: str | Path) -> ParsedDocument:
    """md/txt → 单个 text block；UTF-8，非法字节替换不抛。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument(
        source=str(p),
        parser="text",
        blocks=[ParsedBlock(text=text, page_no=None)],
    )


def parse_document(path: str | Path, *, force_pymupdf: bool | None = None) -> ParsedDocument:
    """PDF/DOCX → 统一结构化文本（S1-2 切片器的输入契约）。"""
    p = Path(path)
    if not p.exists():
        raise InvalidParamError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix in {".md", ".txt"}:
        return parse_plain_text(p)
    if suffix == ".docx":
        from app.ai.parse.docx_parser import DocxParser

        return DocxParser().parse(p)
    if suffix != ".pdf":
        raise InvalidParamError(f"不支持的文件类型: {suffix}（本卡支持 .pdf/.docx）")

    if detect_scanned(p):
        logger.warning("扫描版 PDF，跳过解析", extra={"file": str(p)})
        return ParsedDocument(
            source=str(p),
            parser="pymupdf",
            is_scanned=True,
            degraded_reason="扫描版 PDF：无可抽取文本，请走图片识别（下一任务）",
        )

    force = force_pymupdf if force_pymupdf is not None else get_settings().parse_force_pymupdf
    if not force:
        try:
            from app.ai.parse.pdf_docling import DoclingParser

            return DoclingParser().parse(p)
        except Exception as exc:  # noqa: BLE001 —— 降级链必须接住 docling 的一切故障
            logger.warning(
                "Docling 解析失败，降级 PyMuPDF",
                extra={"file": str(p), "reason": f"{type(exc).__name__}: {exc}"},
            )
            result = PyMuPDFParser().parse(p)
            result.degraded_reason = f"Docling 降级（{type(exc).__name__}: {str(exc)[:180]}）"
            return result

    result = PyMuPDFParser().parse(p)
    result.degraded_reason = "强制 PyMuPDF 快速路径（parse_force_pymupdf）"
    return result
