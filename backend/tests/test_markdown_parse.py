"""S3-1 笔记 Markdown → ParsedBlock（spec §4）。"""
from __future__ import annotations

from app.ai.parse.markdown import parse_markdown_text


def _blocks(text: str):
    return parse_markdown_text(text, source="note:1").blocks


def test_parse_markdown_text_headings_set_heading_path() -> None:
    blocks = _blocks("# 函数\n\n导数是变化率。\n\n## 单调性\n\n设区间 D。")
    assert [b.heading_path for b in blocks] == [
        ["函数"],
        ["函数"],
        ["函数", "单调性"],
        ["函数", "单调性"],
    ]
    assert blocks[0].text == "函数"
    assert blocks[1].text == "导数是变化率。"


def test_parse_markdown_text_level_skip_keeps_ancestor_path() -> None:
    blocks = _blocks("# 一\n\n### 三层\n\n正文")
    assert blocks[-1].heading_path == ["一", "三层"]


def test_parse_markdown_text_lower_heading_pops_stack() -> None:
    blocks = _blocks("# A\n\n## B\n\n# C\n\n正文")
    assert blocks[-1].heading_path == ["C"]


def test_parse_markdown_text_code_fence_is_single_block() -> None:
    blocks = _blocks("```python\n# 不是标题\nprint(1)\n```\n")
    assert len(blocks) == 1
    assert blocks[0].text.startswith("```python")
    assert "# 不是标题" in blocks[0].text


def test_parse_markdown_text_table_is_single_block() -> None:
    blocks = _blocks("| a | b |\n| --- | --- |\n| 1 | 2 |")
    assert len(blocks) == 1
    assert blocks[0].text.startswith("|")
    assert "\n" in blocks[0].text


def test_parse_markdown_text_blank_line_splits_paragraphs() -> None:
    blocks = _blocks("第一段\n\n第二段")
    assert [b.text for b in blocks] == ["第一段", "第二段"]


def test_parse_markdown_text_image_keeps_alt_only() -> None:
    blocks = _blocks("![函数图](note-file://12)")
    assert blocks[0].text == "函数图"


def test_parse_markdown_text_keeps_latex_and_list() -> None:
    blocks = _blocks("公式 $x^2$ 与 $$\\int_0^1 x dx$$\n\n- 第一条\n- 第二条")
    assert "$x^2$" in blocks[0].text
    assert blocks[1].text.startswith("- 第一条")


def test_parse_markdown_text_drops_empty_section_headings() -> None:
    blocks = _blocks("# 空节\n\n# 有内容\n\n正文")
    assert [b.text for b in blocks] == ["有内容", "正文"]


def test_parse_markdown_text_empty_returns_no_blocks() -> None:
    assert _blocks("   \n\n") == []


def test_parse_markdown_text_strips_closing_hashes() -> None:
    blocks = _blocks("# 标题 ###\n\n正文")
    assert blocks[0].text == "标题"


def test_parse_markdown_text_sets_text_parser_and_no_page() -> None:
    document = parse_markdown_text("# 标题\n\n正文", source="note:7")
    assert document.parser == "text"
    assert document.source == "note:7"
    assert document.is_scanned is False
    assert all(block.page_no is None for block in document.blocks)