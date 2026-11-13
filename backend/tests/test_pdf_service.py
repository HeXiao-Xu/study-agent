"""S5-3 PDF 导出：上下文组装、模板转义、注入式渲染（不启浏览器）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import ConflictError, InvalidParamError, PdfRenderError
from app.models.subject import Subject
from app.schemas.paper import OptionOut, PaperDetailOut, PaperItemOut
from app.services import pdf_service

NOW = datetime(2026, 11, 13, 4, 0, tzinfo=timezone.utc)


def _item(
    question_id: int,
    qtype: str,
    *,
    score: int = 3,
    difficulty: int = 2,
    stem: str = "求 $x^2$ 的值",
    options: list[OptionOut] | None = None,
    answer: str | None = "答案",
    analysis: str | None = "解析",
) -> PaperItemOut:
    return PaperItemOut(
        question_id=question_id,
        qtype=qtype,
        difficulty=difficulty,
        score=score,
        kp_ids=[117],
        parts=None,
        subject_id=7,
        stem_md=stem,
        options=options or [],
        answer_md=answer,
        analysis_md=analysis,
        verified=True,
        origin="exam",
    )


def _detail(items: list[PaperItemOut], *, title: str = "期中卷") -> PaperDetailOut:
    return PaperDetailOut(
        id=7,
        title=title,
        status="草稿",
        total_score=sum(item.score for item in items),
        duration_min=60,
        question_ids=[item.question_id for item in items],
        created_at=NOW,
        constraint_json={"seed": 7},
        items=items,
        missing_question_ids=[],
    )


def test_build_context_questions_numbers_and_blanks() -> None:
    detail = _detail([_item(501, "单选"), _item(502, "填空"), _item(503, "解答", score=8)])

    context = pdf_service.build_context(
        detail, variant="questions", subject_name="高中数学", now=NOW
    )

    assert [question.number for question in context.questions] == [1, 2, 3]
    assert [question.blank_lines for question in context.questions] == [2, 2, 0]
    assert context.total_score == 3 + 3 + 8
    assert context.question_count == 3
    assert context.variant_label == "题干卷"
    assert context.subject_name == "高中数学"


def test_build_context_answers_keeps_stems_and_answers() -> None:
    detail = _detail([_item(501, "单选", stem="题干 A", answer="选 A", analysis="因为 A")])

    context = pdf_service.build_context(
        detail, variant="answers", subject_name=None, now=NOW
    )

    assert context.variant == "answers"
    assert context.variant_label == "答案卷"
    assert context.questions[0].stem_md == "题干 A"
    assert context.questions[0].answer_md == "选 A"
    assert context.questions[0].analysis_md == "因为 A"


def test_build_context_rejects_empty_items() -> None:
    with pytest.raises(ConflictError):
        pdf_service.build_context(
            _detail([]), variant="questions", subject_name=None, now=NOW
        )


def test_build_context_rejects_unknown_variant() -> None:
    with pytest.raises(InvalidParamError):
        pdf_service.build_context(
            _detail([_item(501, "单选")]), variant="both", subject_name=None, now=NOW
        )


def test_render_html_escapes_and_keeps_math() -> None:
    detail = _detail([_item(501, "单选", stem="<script>alert(1)</script> 求 $x^2$")])

    html_text = pdf_service.render_html(
        pdf_service.build_context(
            detail, variant="questions", subject_name=None, now=NOW
        )
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
    assert "<script>alert(1)</script>" not in html_text
    assert "$x^2$" in html_text


def test_render_html_variant_diff() -> None:
    detail = _detail([_item(501, "单选", answer="选 A", analysis="因为 A")])
    questions = pdf_service.render_html(
        pdf_service.build_context(detail, variant="questions", subject_name=None, now=NOW)
    )
    answers = pdf_service.render_html(
        pdf_service.build_context(detail, variant="answers", subject_name=None, now=NOW)
    )

    assert "答案：" not in questions
    assert "答案：" in answers
    assert "因为 A" in answers


def test_build_header_footer_has_page_numbers_and_escapes_title() -> None:
    detail = _detail([_item(501, "单选")], title="<期中>卷")

    header, footer = pdf_service.build_header_footer(
        pdf_service.build_context(detail, variant="answers", subject_name=None, now=NOW)
    )

    assert "&lt;期中&gt;卷" in header
    assert "答案卷" in header
    assert 'class="pageNumber"' in footer
    assert 'class="totalPages"' in footer


class FakeExportSession:
    def __init__(self, subject_name: str = "高中数学") -> None:
        self.subject_name = subject_name

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Subject:
            subject = Subject(name=self.subject_name, code="math")
            subject.id = pk
            return subject
        return None


def test_export_pdf_uses_injected_renderer(monkeypatch) -> None:
    detail = _detail([_item(501, "单选")], title="期中卷/高一")
    monkeypatch.setattr(pdf_service.paper_plan_service, "get_paper", lambda *a, **k: detail)
    captured: dict[str, str] = {}

    def fake_renderer(html_text: str, header: str, footer: str) -> bytes:
        captured["html"] = html_text
        captured["header"] = header
        captured["footer"] = footer
        return b"%PDF-1.4 fake"

    pdf_bytes, filename = pdf_service.export_pdf(
        FakeExportSession(),
        user_id=50,
        paper_id=7,
        variant="questions",
        now=NOW,
        renderer=fake_renderer,
    )

    assert pdf_bytes.startswith(b"%PDF")
    assert filename == "期中卷高一-题干卷.pdf"
    assert "求 $x^2$ 的值" in captured["html"]
    assert '第 <span class="pageNumber"></span>' in captured["footer"]


def test_export_pdf_wraps_renderer_failure(monkeypatch) -> None:
    detail = _detail([_item(501, "单选")])
    monkeypatch.setattr(pdf_service.paper_plan_service, "get_paper", lambda *a, **k: detail)

    def broken_renderer(html_text: str, header: str, footer: str) -> bytes:
        raise RuntimeError("chromium 崩了")

    with pytest.raises(PdfRenderError):
        pdf_service.export_pdf(
            FakeExportSession(),
            user_id=50,
            paper_id=7,
            variant="questions",
            now=NOW,
            renderer=broken_renderer,
        )
