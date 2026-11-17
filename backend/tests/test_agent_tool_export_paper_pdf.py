"""S6-1 export_paper_pdf：只给受权下载地址，不渲染 PDF。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.agents.tools import export_paper_pdf as tool
from app.ai.agents.tools.base import ToolContext
from app.core.exceptions import NotFoundError


def _ctx() -> ToolContext:
    return ToolContext(session=object(), user=SimpleNamespace(id=50))  # type: ignore[arg-type]


def test_export_paper_pdf_returns_url(monkeypatch):
    monkeypatch.setattr(
        tool,
        "get_paper",
        lambda *a, **k: SimpleNamespace(
            id=9, title="函数小卷", total_score=55, items=[1, 2, 3]
        ),
    )
    out = tool.export_paper_pdf(
        _ctx(), tool.ExportPaperPdfIn(paper_id=9, variant="answers")
    )
    assert out.download_url == "/api/v1/papers/9/export.pdf?variant=answers"
    assert out.filename == "试卷-9-答案卷.pdf"
    assert out.question_count == 3
    assert out.total_score == 55


def test_export_paper_pdf_default_variant(monkeypatch):
    monkeypatch.setattr(
        tool,
        "get_paper",
        lambda *a, **k: SimpleNamespace(id=9, title="卷", total_score=10, items=[]),
    )
    out = tool.export_paper_pdf(_ctx(), tool.ExportPaperPdfIn(paper_id=9))
    assert out.variant == "questions"
    assert out.filename == "试卷-9-题干卷.pdf"


def test_export_paper_pdf_not_found(monkeypatch):
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise NotFoundError("试卷不存在")

    monkeypatch.setattr(tool, "get_paper", boom)
    with pytest.raises(NotFoundError):
        tool.export_paper_pdf(_ctx(), tool.ExportPaperPdfIn(paper_id=404))