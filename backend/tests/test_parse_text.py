"""S2-8 md/txt 文本解析支路。"""
from __future__ import annotations

from pathlib import Path

from app.ai.parse import parse_document, parse_plain_text


def test_parse_plain_text_returns_single_block(tmp_path: Path) -> None:
    path = tmp_path / "笔记.md"
    path.write_bytes("# 标题\n函数单调性\n".encode("utf-8"))
    doc = parse_plain_text(path)
    assert doc.parser == "text"
    assert len(doc.blocks) == 1
    assert "函数单调性" in doc.blocks[0].text
    assert doc.blocks[0].page_no is None


def test_parse_document_dispatches_text_file(tmp_path: Path) -> None:
    path = tmp_path / "笔记.txt"
    path.write_bytes(b"\xff\xfeabc")  # 非法 UTF-8：替换不抛
    doc = parse_document(path)
    assert doc.parser == "text"
    assert len(doc.blocks) == 1