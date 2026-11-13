"""S5-3 PDF 导出：已保存卷子 → 题干卷/答案卷（Jinja2 + KaTeX + Playwright）。"""
from __future__ import annotations

import atexit
import html
import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, InvalidParamError, PdfRenderError
from app.models.subject import Subject
from app.schemas.paper import OptionOut, PaperDetailOut
from app.services import paper_plan_service

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

Renderer = Callable[[str, str, str], bytes]

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_playwright = None
_browser = None

_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


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

def render_html(context: PdfContext) -> str:
    """渲染模板；base_href 指向静态目录，KaTeX 的 CSS/字体按相对路径加载。"""
    template = _JINJA_ENV.get_template(TEMPLATE_NAME)
    return template.render(context=context, base_href=STATIC_DIR.as_uri() + "/")


def build_header_footer(context: PdfContext) -> tuple[str, str]:
    """Playwright 的页眉/页脚模板：页眉左标题右卷别，页脚页码。"""
    style = (
        "width:100%;font-size:9pt;color:#555;padding:0 16mm;"
        "font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif;"
    )
    title = html.escape(context.title)
    label = html.escape(context.variant_label)
    header = (
        f'<div style="{style}display:flex;justify-content:space-between;">'
        f"<span>{title}</span><span>{label}</span></div>"
    )
    footer = (
        f'<div style="{style}text-align:right;">第 '
        f'<span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>'
    )
    return header, footer


def _prepare_browser_env() -> Path | None:
    """Playwright/Chromium 的临时目录与浏览器缓存走配置（Windows 开发机默认路径不可写）。"""
    settings = get_settings()
    tmp_dir = Path(settings.pdf_tmp_dir) if settings.pdf_tmp_dir else None
    if tmp_dir is not None:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        for name in ("TMP", "TEMP", "TMPDIR"):
            os.environ[name] = str(tmp_dir)
    if settings.playwright_browsers_path:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.playwright_browsers_path)
    return tmp_dir


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-render")
        return _executor


def _reset_executor() -> None:
    """渲染线程坏了就整体丢弃重建；Playwright 对象不能跨线程复用。"""
    global _executor, _playwright, _browser
    with _executor_lock:
        executor, _executor = _executor, None
        _playwright, _browser = None, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def _render_in_worker(html_text: str, header_html: str, footer_html: str) -> bytes:
    """只在单渲染线程里跑：sync Playwright 有线程亲和性。"""
    global _playwright, _browser
    tmp_dir = _prepare_browser_env()
    from playwright.sync_api import sync_playwright

    if _playwright is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    with tempfile.TemporaryDirectory(prefix="paper-pdf-", dir=tmp_dir) as tmp:
        page_path = Path(tmp) / "paper.html"
        page_path.write_text(html_text, encoding="utf-8")
        page = _browser.new_page()
        page.set_default_timeout(RENDER_TIMEOUT_MS)
        try:
            page.goto(page_path.as_uri(), wait_until="load")
            page.wait_for_function("window.__katexReady === true")
            return page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                margin={"top": "22mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
                header_template=header_html,
                footer_template=footer_html,
            )
        finally:
            page.close()


def render_pdf(html_text: str, header_html: str, footer_html: str) -> bytes:
    if not (STATIC_DIR / "katex" / "katex.min.css").exists():
        raise PdfRenderError("导出所需的 KaTeX 静态资源缺失")
    try:
        future = _get_executor().submit(
            _render_in_worker, html_text, header_html, footer_html
        )
        return future.result(timeout=RENDER_TIMEOUT_MS / 1000 + 10)
    except PdfRenderError:
        _reset_executor()
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转业务错误并保留 cause
        _reset_executor()
        raise PdfRenderError("PDF 渲染失败") from exc


def _subject_name(session: Session, detail: PaperDetailOut) -> str | None:
    if not detail.items:
        return None
    subject = session.get(Subject, detail.items[0].subject_id)
    return getattr(subject, "name", None) if subject is not None else None


def _filename(context: PdfContext) -> str:
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", context.title).strip()
    safe = safe[:80] or f"试卷-{context.paper_id}"
    return f"{safe}-{context.variant_label}.pdf"


def export_pdf(
    session: Session,
    *,
    user_id: int,
    paper_id: int,
    variant: str,
    now: datetime | None = None,
    renderer: Renderer | None = None,
) -> tuple[bytes, str]:
    """读卷 → 组上下文 → 渲 HTML → 打印 PDF；不写库、不缓存。"""
    detail = paper_plan_service.get_paper(session, user_id=user_id, paper_id=paper_id)
    context = build_context(
        detail,
        variant=variant,
        subject_name=_subject_name(session, detail),
        now=now or datetime.now(timezone.utc),
    )
    html_text = render_html(context)
    header_html, footer_html = build_header_footer(context)
    render = renderer or render_pdf
    try:
        pdf_bytes = render(html_text, header_html, footer_html)
    except PdfRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - 渲染器（含注入的 fake）失败统一转 500
        raise PdfRenderError("PDF 渲染失败") from exc
    if not pdf_bytes.startswith(b"%PDF"):
        raise PdfRenderError("渲染结果不是有效 PDF")
    return pdf_bytes, _filename(context)


atexit.register(_reset_executor)
