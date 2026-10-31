"""S3-6 引用检查器：纯函数，不连库/不调外部。"""
from __future__ import annotations

import pytest

from app.services.citation_checker import (
    SUPPLEMENT_PREFIX,
    annotate_uncited,
    build_correction,
    check_answer,
    split_blocks,
    strip_invalid_citations,
)


def test_split_blocks_keeps_paragraphs_headings_and_lists() -> None:
    answer = "第一段[1]。\n\n## 标题\n- 列表一[2]\n- 列表二"

    assert split_blocks(answer) == [
        "第一段[1]。",
        "## 标题",
        "- 列表一[2]",
        "- 列表二",
    ]


def test_check_skips_heading_code_and_math() -> None:
    answer = (
        "# 标题\n\n"
        "```python\n[99]\n```\n\n"
        "$$ E = mc^2 $$\n\n"
        "这是需要引用的知识陈述内容。"
    )
    check = check_answer(answer, context_size=3)

    assert check.valid_indices == []
    assert check.invalid_indices == []
    assert check.uncited_blocks == ["这是需要引用的知识陈述内容。"]
    assert check.has_content is True


def test_check_records_valid_and_invalid_indices() -> None:
    check = check_answer("结论[1]，错误引用[9]。", context_size=2)

    assert check.valid_indices == [1]
    assert check.invalid_indices == [9]
    assert check.uncited_blocks == []
    assert check.has_content is True
    assert check.needs_retry is True


def test_check_marks_only_uncited_blocks() -> None:
    answer = "已引用[1]的内容。\n\n没有引用的知识陈述内容。"
    check = check_answer(answer, context_size=2)

    assert check.valid_indices == [1]
    assert check.uncited_blocks == ["没有引用的知识陈述内容。"]
    assert check.needs_retry is True


def test_check_no_citations_is_not_clean() -> None:
    check = check_answer("这是没有任何引用的知识陈述内容。", context_size=2)

    assert check.valid_indices == []
    assert check.uncited_blocks == ["这是没有任何引用的知识陈述内容。"]
    assert check.has_valid_citation is False
    assert check.needs_retry is True


def test_check_empty_answer_has_no_content() -> None:
    check = check_answer("", context_size=2)

    assert check.has_content is False
    assert check.needs_retry is True


def test_check_rejects_nonpositive_context() -> None:
    with pytest.raises(ValueError):
        check_answer("回答", context_size=0)


def test_strip_invalid_citations_keeps_valid() -> None:
    assert strip_invalid_citations("答[1]和[9]", context_size=2) == "答[1]和"


def test_annotate_only_uncited_block() -> None:
    answer = "已引用[1]。\n\n无引用块。"
    annotated = annotate_uncited(answer, context_size=2)

    assert annotated == f"已引用[1]。\n\n{SUPPLEMENT_PREFIX}\n无引用块。"


def test_annotate_skips_existing_prefix() -> None:
    answer = f"{SUPPLEMENT_PREFIX}\n补充内容"
    assert annotate_uncited(answer, context_size=2) == answer


def test_annotate_does_not_touch_code_block() -> None:
    answer = "正文需要引用[1]。\n\n```python\nprint(1)\n```"
    annotated = annotate_uncited(answer, context_size=2)

    assert annotated == answer
    assert annotated.count(SUPPLEMENT_PREFIX) == 0


def test_build_correction_contains_range_and_prefix() -> None:
    check = check_answer("没有引用的知识陈述内容。", context_size=3)
    correction = build_correction(check)

    assert "[1]..[3]" in correction
    assert SUPPLEMENT_PREFIX in correction
    assert "不要解释校验过程" in correction