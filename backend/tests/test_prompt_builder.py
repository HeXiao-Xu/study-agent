"""S1-6 上下文组装 + Jinja2 Prompt 渲染。"""
from __future__ import annotations

import pytest

from app.ai.rag.prompt_builder import (
    PromptTemplateError,
    build_context,
    render_prompt,
)
from app.ai.rag.retriever import RetrievedChunk


def _chunk(
    chunk_id: int,
    score: float | None,
    content: str,
    *,
    note_id: int = 101,
    source_file_id: int | None = 12,
    page_no: int | None = 3,
    heading_path: str | None = "函数/单调性",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_id=note_id,
        source_file_id=source_file_id,
        chunk_index=chunk_id,
        content=content,
        heading_path=heading_path,
        page_no=page_no,
        rerank_score=score,
    )


def test_build_context_orders_by_rerank_and_dedupes() -> None:
    chunks = [
        _chunk(1, 0.2, "低分"),
        _chunk(2, 0.9, "高分"),
        _chunk(2, 0.8, "重复块"),
        _chunk(3, 0.5, "中分"),
    ]
    built = build_context(chunks)
    assert [item.citation.chunk_id for item in built.items] == [2, 3, 1]
    assert built.items[0].citation.index == 1
    assert built.items[0].citation.snippet == "高分"


def test_build_context_without_scores_keeps_input_order() -> None:
    built = build_context([_chunk(1, None, "一"), _chunk(2, None, "二")])
    assert [item.citation.chunk_id for item in built.items] == [1, 2]


def test_build_context_respects_token_budget() -> None:
    built = build_context(
        [_chunk(1, 0.9, "数学" * 400), _chunk(2, 0.8, "函数" * 400)],
        max_tokens=80,
    )
    assert built.tokens <= 80
    assert built.truncated is True
    assert len(built.items) == 1


def test_build_context_skips_when_header_exceeds_budget() -> None:
    assert build_context([_chunk(1, 0.9, "内容")], max_tokens=1).items == []


def test_build_context_empty_chunks() -> None:
    built = build_context([])
    assert built.items == []
    assert built.text == ""
    assert built.tokens == 0
    assert built.truncated is False


def test_build_context_citation_metadata() -> None:
    built = build_context(
        [
            _chunk(
                1,
                0.9,
                "正文",
                note_id=107,
                source_file_id=107,
                page_no=None,
                heading_path=None,
            )
        ]
    )
    citation = built.items[0].citation
    assert citation.note_id == 107
    assert citation.source_file_id == 107
    assert citation.page_no is None
    assert "页码未知" in built.text
    assert "章节未标注" in built.text
    assert "文件 #107" in built.text


def test_render_prompt_renders_context_and_question() -> None:
    rendered = render_prompt("[1] 来源：...\n正文", "错位相减法怎么用？")
    assert "[1] 来源" in rendered
    assert "错位相减法怎么用？" in rendered
    assert "{{" not in rendered


def test_render_prompt_missing_template_raises(tmp_path) -> None:
    with pytest.raises(PromptTemplateError):
        render_prompt("ctx", "q", template_path=tmp_path / "missing.md")