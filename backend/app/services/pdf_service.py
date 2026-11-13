"""S5-3 PDF 导出：已保存卷子 → 题干卷/答案卷（Jinja2 + KaTeX + Playwright）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.exceptions import ConflictError, InvalidParamError
from app.schemas.paper import OptionOut, PaperDetailOut

VARIANT_QUESTIONS = "questions"
VARIANT_ANSWERS = "answers"
VARIANTS = (VARIANT_QUESTIONS, VARIANT_ANSWERS)
VARIANT_LABELS = {VARIANT_QUESTIONS: "题干卷", VARIANT_ANSWERS: "答案卷"}
BLANK_LINES_BY_QTYPE = {"单选": 2, "填空": 2}

APP_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = APP_DIR / "app" / "templates"
STATIC_DIR = APP_DIR / "app" / "static"
TEMPLATE_NAME = "paper_pdf.html"
RENDER_TIMEOUT_MS = 30_000


@dataclass(frozen=True, slots=True)
class PdfQuestion:
    number: int
    qtype: str
    score: int
    difficulty: int
    stem_md: str
    options: tuple[OptionOut, ...]
    answer_md: str | None
    analysis_md: str | None
    blank_lines: int


@dataclass(frozen=True, slots=True)
class PdfContext:
    paper_id: int
    title: str
    subject_name: str | None
    variant: str
    variant_label: str
    total_score: int
    duration_min: int | None
    question_count: int
    questions: tuple[PdfQuestion, ...]
    generated_at: datetime


def build_context(
    detail: PaperDetailOut,
    *,
    variant: str,
    subject_name: str | None,
    now: datetime,
) -> PdfContext:
    """把卷面 DTO 转成模板上下文；空卷与非法变体在这里就拦掉。"""
    if variant not in VARIANTS:
        raise InvalidParamError(f"variant 只能是 {'/'.join(VARIANTS)}")
    if not detail.items:
        raise ConflictError("试卷没有可导出的题目")
    questions = tuple(
        PdfQuestion(
            number=number,
            qtype=item.qtype,
            score=item.score,
            difficulty=item.difficulty,
            stem_md=item.stem_md,
            options=tuple(item.options),
            answer_md=item.answer_md,
            analysis_md=item.analysis_md,
            blank_lines=BLANK_LINES_BY_QTYPE.get(item.qtype, 0),
        )
        for number, item in enumerate(detail.items, start=1)
    )
    return PdfContext(
        paper_id=detail.id,
        title=detail.title,
        subject_name=subject_name,
        variant=variant,
        variant_label=VARIANT_LABELS[variant],
        total_score=detail.total_score,
        duration_min=detail.duration_min,
        question_count=len(questions),
        questions=questions,
        generated_at=now,
    )