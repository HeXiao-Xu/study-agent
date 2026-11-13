# S5-3 PDF 导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已保存的卷子（`papers`）渲染成 A4 题干卷 / 答案卷 PDF，提供 `GET /papers/{id}/export.pdf?variant=questions|answers`，组卷页保存后可直接下载。

**Architecture:** 复用 S5-2 `paper_plan_service.get_paper` 读卷 → `build_context`（纯函数）→ `render_html`（Jinja2，转义 + KaTeX 占位）→ `render_pdf`（Playwright，单渲染线程独占 Chromium，A4 + 页眉页脚）→ `Response(application/pdf)`。渲染器通过参数注入，单测全 fake、不启浏览器。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、Pydantic v2、Jinja2、Playwright（Chromium）、KaTeX 0.19.1、pdfplumber（验收）、Vue 3 + TS + Vitest。

**Spec:** `docs/spec/s5-3-pdf-export.md`

## Global Constraints

- 提交规范：Conventional Commits，含任务号，如 `feat(s5-3): …`；用户负责 `git push`。
- 后端测试命令（在 `study-agent/backend/` 下）：`../.venv/Scripts/python.exe -m pytest tests/<file> -q`。
- 前端测试/构建（在 `study-agent/web/` 下）：`npm run test:run`、`npm run build`。
- 枚举/错误：业务错误一律 `AppError` 子类；PDF 渲染失败用新增 `PdfRenderError`（500/50000）。
- 二进制响应不套 `Envelope`（参照 `GET /files/{id}/image`）。
- 不新增数据表、不做迁移；导出不写库、不缓存。
- Playwright 同步 API 只能在创建它的线程使用；渲染只允许走 `_executor` 单线程。
- 单测禁止真实启动浏览器或外部网络；`render_pdf` 必须在测试里被替换。
- KaTeX 静态资源版本固定 0.19.1，来源 `web/node_modules/katex/dist`。
- Windows 路径用 `Path`；临时目录用 `tempfile.TemporaryDirectory`（异常也清理）。
- 中文文档、注释只解释「为什么」。

---

### Task 1: 依赖 + KaTeX 静态资源

**Files:**
- Create: `backend/app/static/katex/`（`katex.min.css`、`katex.min.js`、`contrib/auto-render.min.js`、`fonts/**`、`VERSION.txt`）
- Create: `scripts/sync_katex.py`（在 `study-agent/scripts/` 下）
- Modify: `backend/requirements.txt`
- Test: 命令验证（导入 + Chromium 启动 + 文件存在）

**Interfaces:**
- Produce: `backend/app/static/katex/` 目录结构（后续 `render_html` 的 `base_href` 与模板相对路径依赖它）；`playwright`、`pdfplumber` 可导入。

- [ ] **Step 1: 安装 Python 依赖**

```bash
cd /e/BiShe-AIStudy/study-agent
../study-agent/.venv/Scripts/python.exe -m pip install playwright pdfplumber
```

Expected: `Successfully installed playwright-… pdfplumber-…`（若已装则 `Requirement already satisfied`）。

- [ ] **Step 2: 下载 Chromium 内核**

```bash
../study-agent/.venv/Scripts/python.exe -m playwright install chromium
```

Expected: 下载 chromium 与 headless shell 到 `%LOCALAPPDATA%\ms-playwright`（首次约 170 MB）。

- [ ] **Step 3: 记录版本并写进 requirements.txt**

```bash
../study-agent/.venv/Scripts/python.exe -m pip show playwright pdfplumber | grep -E "^(Name|Version)"
```

把输出的两个版本用 `==` 追加到 `backend/requirements.txt` 末尾（放在新的分段注释下）：

```text
# --- S5-3 PDF 导出（Playwright 渲染 + pdfplumber 验收；2026-11-13 用户批准）---
playwright==1.55.0
pdfplumber==0.11.7
```

（上面两个版本号以 `pip show` 实测为准，不要照抄示例。）

- [ ] **Step 4: 拷贝 KaTeX 资源**

```bash
cd /e/BiShe-AIStudy/study-agent
mkdir -p backend/app/static/katex/contrib backend/app/static/katex/fonts
cp web/node_modules/katex/dist/katex.min.css backend/app/static/katex/
cp web/node_modules/katex/dist/katex.min.js backend/app/static/katex/
cp web/node_modules/katex/dist/contrib/auto-render.min.js backend/app/static/katex/contrib/
cp web/node_modules/katex/dist/fonts/* backend/app/static/katex/fonts/
printf 'katex@0.19.1 copied from web/node_modules/katex/dist (S5-3, 2026-11-13)\n' > backend/app/static/katex/VERSION.txt
```

- [ ] **Step 5: 写同步脚本 `scripts/sync_katex.py`**

```python
"""把 web/node_modules 里的 KaTeX dist 同步到后端静态目录（升级 KaTeX 时手动跑一次）。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "node_modules" / "katex"
DEST = ROOT / "backend" / "app" / "static" / "katex"
FILES = ("katex.min.css", "katex.min.js")
DIRS = ("fonts",)
EXTRA_FILES = (Path("contrib") / "auto-render.min.js",)


def main() -> None:
    version = json.loads((SOURCE / "package.json").read_text(encoding="utf-8"))["version"]
    DEST.mkdir(parents=True, exist_ok=True)
    dist = SOURCE / "dist"
    for name in FILES:
        shutil.copy2(dist / name, DEST / name)
    for name in DIRS:
        target = DEST / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(dist / name, target)
    for rel in EXTRA_FILES:
        (DEST / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dist / rel, DEST / rel)
    (DEST / "VERSION.txt").write_text(
        f"katex@{version} copied from web/node_modules/katex/dist (S5-3)\n", encoding="utf-8"
    )
    print(f"katex@{version} -> {DEST}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 验证依赖与资源**

```bash
cd /e/BiShe-AIStudy/study-agent
../study-agent/.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright
import pdfplumber

root = Path("backend/app/static/katex")
for rel in ("katex.min.css", "katex.min.js", "contrib/auto-render.min.js", "fonts/KaTeX_Main-Regular.woff2"):
    assert (root / rel).exists(), rel
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content("<p>中文 OK</p>")
    print("chromium", browser.version)
    browser.close()
print("pdfplumber", pdfplumber.__version__)
print("katex", (root / "VERSION.txt").read_text(encoding="utf-8").strip())
PY
```

Expected: 打印 chromium 版本、`pdfplumber 0.11.x`、`katex@0.19.1 …`，无异常。

- [ ] **Step 7: Commit**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/requirements.txt backend/app/static/katex scripts/sync_katex.py
git commit -m "feat(s5-3): PDF 导出依赖与本地 KaTeX 静态资源"
```

---

### Task 2: 上下文组装 `build_context` + `PdfRenderError`

**Files:**
- Create: `backend/app/services/pdf_service.py`
- Modify: `backend/app/core/exceptions.py`
- Test: `backend/tests/test_pdf_service.py`

**Interfaces:**
- Consumes: `PaperDetailOut` / `PaperItemOut` / `OptionOut`（`app.schemas.paper`）。
- Produces（后续任务依赖，签名固定）：
  - `class PdfQuestion`：`number: int, qtype: str, score: int, difficulty: int, stem_md: str, options: tuple[OptionOut, ...], answer_md: str | None, analysis_md: str | None, blank_lines: int`
  - `class PdfContext`：`paper_id: int, title: str, subject_name: str | None, variant: str, variant_label: str, total_score: int, duration_min: int | None, question_count: int, questions: tuple[PdfQuestion, ...], generated_at: datetime`
  - `build_context(detail: PaperDetailOut, *, variant: str, subject_name: str | None, now: datetime) -> PdfContext`
  - `PdfRenderError(message: str = "PDF 渲染失败")`（500/50000）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_pdf_service.py`：

```python
"""S5-3 PDF 导出：上下文组装、模板转义、注入式渲染（不启浏览器）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import ConflictError, InvalidParamError
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.pdf_service'`（4 failed/collection error）。

- [ ] **Step 3: 加 `PdfRenderError`**

在 `backend/app/core/exceptions.py` 的 `TaskQueueUnavailableError` 之后加：

```python
class PdfRenderError(AppError):
    """PDF 渲染失败：对外固定话术，不泄露浏览器路径/堆栈。"""

    def __init__(self, message: str = "PDF 渲染失败") -> None:
        super().__init__(message, code=CODE_INTERNAL, http_status=500)
```

- [ ] **Step 4: 写 `pdf_service.py` 的数据类与 `build_context`**

```python
"""S5-3 PDF 导出：已保存卷子 → 题干卷/答案卷（Jinja2 + KaTeX + Playwright）。"""
from __future__ import annotations

import re
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
```

（`re`、`STATIC_DIR`、`TEMPLATE_*` 在 Task 3/4 才用；本轮可以先只留实际用到的导入，若 `python -W error` 不报未使用导入则无妨。）

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: `4 passed`。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/pdf_service.py backend/app/core/exceptions.py backend/tests/test_pdf_service.py
git commit -m "feat(s5-3): PDF 上下文组装与渲染错误类型"
```

---

### Task 3: Jinja2 模板 + `render_html` + 页眉页脚

**Files:**
- Create: `backend/app/templates/paper_pdf.html`
- Modify: `backend/app/services/pdf_service.py`
- Test: `backend/tests/test_pdf_service.py`（追加 3 条）

**Interfaces:**
- Consumes: `PdfContext`（Task 2）。
- Produces:
  - `render_html(context: PdfContext) -> str`
  - `build_header_footer(context: PdfContext) -> tuple[str, str]`（Playwright 的 header/footer 模板）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_pdf_service.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: 3 failed（`AttributeError: module 'app.services.pdf_service' has no attribute 'render_html'`）。

- [ ] **Step 3: 写模板 `backend/app/templates/paper_pdf.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <base href="{{ base_href }}" />
    <title>{{ context.title }} · {{ context.variant_label }}</title>
    <link rel="stylesheet" href="katex/katex.min.css" />
    <style>
      @page {
        size: A4;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        font-family: "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", sans-serif;
        font-size: 12pt;
        line-height: 1.65;
        color: #111;
      }
      .paper-head {
        border-bottom: 2px solid #222;
        padding-bottom: 8px;
        margin-bottom: 16px;
      }
      .paper-title {
        margin: 0 0 6px;
        font-size: 20pt;
        text-align: center;
        letter-spacing: 2px;
      }
      .paper-meta {
        margin: 0;
        text-align: center;
        font-size: 10.5pt;
        color: #333;
      }
      .question {
        break-inside: avoid;
        page-break-inside: avoid;
        margin-bottom: 14px;
      }
      .stem {
        white-space: pre-wrap;
      }
      .options {
        margin: 6px 0 0;
        padding-left: 18px;
      }
      .options li {
        list-style: none;
      }
      .blank-2 {
        height: 34px;
      }
      .blank-solve {
        height: 60mm;
        border-bottom: 1px dotted #bbb;
      }
      .answer,
      .analysis {
        margin-top: 6px;
        padding: 4px 8px;
        border-left: 3px solid #4a7;
        background: #f6fbf8;
        font-size: 11pt;
        white-space: pre-wrap;
      }
      .analysis {
        border-left-color: #999;
        background: #fafafa;
      }
    </style>
  </head>
  <body>
    <header class="paper-head">
      <h1 class="paper-title">{{ context.title }}</h1>
      <p class="paper-meta">
        {% if context.subject_name %}{{ context.subject_name }} · {% endif %}
        总分 {{ context.total_score }} 分
        {% if context.duration_min %} · {{ context.duration_min }} 分钟{% endif %}
        · 共 {{ context.question_count }} 题 · {{ context.generated_at.strftime("%Y-%m-%d") }}
      </p>
    </header>

    {% for question in context.questions %}
    <section class="question">
      <div class="stem">{{ question.number }}.（{{ question.qtype }}，{{ question.score }} 分）{{ question.stem_md }}</div>
      {% if question.options %}
      <ul class="options">
        {% for option in question.options %}
        <li>{{ option.key }}. {{ option.text }}</li>
        {% endfor %}
      </ul>
      {% endif %}
      {% if context.variant == "answers" %}
        {% if question.answer_md %}
        <div class="answer">答案：{{ question.answer_md }}</div>
        {% endif %}
        {% if question.analysis_md %}
        <div class="analysis">解析：{{ question.analysis_md }}</div>
        {% endif %}
      {% else %}
        {% if question.blank_lines %}
        <div class="blank-2"></div>
        {% endif %}
        {% if question.qtype == "解答" %}
        <div class="blank-solve"></div>
        {% endif %}
      {% endif %}
    </section>
    {% endfor %}

    <script src="katex/katex.min.js"></script>
    <script src="katex/contrib/auto-render.min.js"></script>
    <script>
      renderMathInElement(document.body, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
        ],
        throwOnError: false,
      })
      document.fonts.ready.then(function () {
        window.__katexReady = true
      })
    </script>
  </body>
</html>
```

- [ ] **Step 4: 实现 `render_html` 与 `build_header_footer`**

在 `pdf_service.py` 顶部补导入：

```python
import html
import re

from jinja2 import Environment, FileSystemLoader, select_autoescape
```

在常量区补：

```python
_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
```

在 `build_context` 之后追加：

```python
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
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: `7 passed`。

- [ ] **Step 6: 提交**

```bash
git add backend/app/templates/paper_pdf.html backend/app/services/pdf_service.py backend/tests/test_pdf_service.py
git commit -m "feat(s5-3): 试卷 PDF 模板与 HTML 渲染（转义 + KaTeX）"
```

---

### Task 4: Playwright 渲染线程 + `export_pdf`

**Files:**
- Modify: `backend/app/services/pdf_service.py`
- Test: `backend/tests/test_pdf_service.py`（追加 2 条）

**Interfaces:**
- Consumes: `build_context`、`render_html`、`build_header_footer`、`PdfRenderError`；`paper_plan_service.get_paper(session, user_id=…, paper_id=…)`。
- Produces:
  - `Renderer = Callable[[str, str, str], bytes]`
  - `render_pdf(html_text: str, header_html: str, footer_html: str) -> bytes`
  - `export_pdf(session, *, user_id: int, paper_id: int, variant: str, now: datetime | None = None, renderer: Renderer | None = None) -> tuple[bytes, str]`（返回 `(pdf_bytes, filename)`）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_pdf_service.py` 顶部补导入：

```python
from app.core.exceptions import PdfRenderError
from app.models.subject import Subject
```

追加测试（`FakeExportSession` 只服务 `export_pdf` 用到的 `session.get`）：

```python
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
    assert "第 <span class=\"pageNumber\"></span>" in captured["footer"]


def test_export_pdf_wraps_renderer_failure() -> None:
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: 2 failed（`export_pdf` 不存在）。

- [ ] **Step 3: 实现渲染与导出**

`pdf_service.py` 顶部补导入：

```python
import atexit
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.core.exceptions import PdfRenderError
from app.models.subject import Subject
from app.services import paper_plan_service

Renderer = Callable[[str, str, str], bytes]
```

在常量区补：

```python
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_playwright = None
_browser = None
```

在文件末尾追加：

```python
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
    from playwright.sync_api import sync_playwright

    if _playwright is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    with tempfile.TemporaryDirectory(prefix="paper-pdf-") as tmp:
        page_path = Path(tmp) / "paper.html"
        page_path.write_text(html_text, encoding="utf-8")
        page = _browser.new_page()
        try:
            page.goto(page_path.as_uri(), wait_until="load", timeout=RENDER_TIMEOUT_MS)
            page.wait_for_function("window.__katexReady === true", timeout=RENDER_TIMEOUT_MS)
            return page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                margin={"top": "22mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
                header_template=header_html,
                footer_template=footer_html,
                timeout=RENDER_TIMEOUT_MS,
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
```

注意：
- 不要在模块顶层 `import playwright`（保持单测无需浏览器即可 import）。
- `datetime` 已在 Task 2 导入；这里只补 `timezone`。
- `paper_plan_service` 导入用于 `export_pdf`，测试用 `monkeypatch.setattr` 打桩。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_service.py -q
```

Expected: `9 passed`。

- [ ] **Step 5: 真机 smoke（可选但建议）**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe - <<'PY'
from datetime import datetime, timezone
from app.services import pdf_service

html_text = pdf_service.render_html(
    pdf_service.build_context(
        __import__("app.schemas.paper", fromlist=["PaperDetailOut"]).PaperDetailOut(
            id=1, title="smoke", status="草稿", total_score=3, duration_min=10,
            question_ids=[1], created_at=datetime.now(timezone.utc), constraint_json={},
            items=[__import__("app.schemas.paper", fromlist=["PaperItemOut"]).PaperItemOut(
                question_id=1, qtype="单选", difficulty=2, score=3, kp_ids=[1], parts=None,
                subject_id=7, stem_md="若 $x=2$，则 $x^2$ 等于", options=[],
                answer_md="4", analysis_md=None, verified=True, origin="exam",
            )],
            missing_question_ids=[],
        ),
        variant="questions", subject_name=None, now=datetime.now(timezone.utc),
    )
)
header, footer = pdf_service.build_header_footer(
    pdf_service.build_context(
        __import__("app.schemas.paper", fromlist=["PaperDetailOut"]).PaperDetailOut(
            id=1, title="smoke", status="草稿", total_score=3, duration_min=10,
            question_ids=[1], created_at=datetime.now(timezone.utc), constraint_json={},
            items=[__import__("app.schemas.paper", fromlist=["PaperItemOut"]).PaperItemOut(
                question_id=1, qtype="单选", difficulty=2, score=3, kp_ids=[1], parts=None,
                subject_id=7, stem_md="若 $x=2$，则 $x^2$ 等于", options=[],
                answer_md="4", analysis_md=None, verified=True, origin="exam",
            )],
            missing_question_ids=[],
        ),
        variant="questions", subject_name=None, now=datetime.now(timezone.utc),
    )
)
data = pdf_service.render_pdf(html_text, header, footer)
print("bytes", len(data), data[:8])
PY
```

Expected: 打印 `bytes > 10000` 且以 `b'%PDF-1.'` 开头（首次启动 Chromium 会慢几秒）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/pdf_service.py backend/tests/test_pdf_service.py
git commit -m "feat(s5-3): Playwright 单线程渲染与 export_pdf（渲染器可注入）"
```

---

### Task 5: 导出路由 + 契约文档 + 后端全量回归

**Files:**
- Modify: `backend/app/api/v1/papers.py`
- Modify: `docs/API.md §8`
- Modify: `docs/SCHEMA.md`（`papers` 小节备注）
- Create: `backend/tests/test_pdf_api.py`
- Test: `backend/tests/test_pdf_api.py`、全量 `pytest`

**Interfaces:**
- Consumes: `pdf_service.export_pdf`、`require_role("student")`、`get_db`。
- Produces: `GET /api/v1/papers/{paper_id}/export.pdf?variant=questions|answers`（200 PDF / 401 / 403 / 404 / 409 / 422 / 500）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_pdf_api.py`：

```python
"""S5-3 导出接口：鉴权、状态码、PDF 响应头与渲染失败。"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.paper import Paper
from app.models.subject import Subject
from app.models.user import User
from app.services import pdf_service

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _user(role: str = "student", user_id: int = 50) -> User:
    user = User(username=f"{role}_s53", nickname=role, grade="高二", role=role, password_hash="x")
    user.id = user_id
    return user


def _paper(paper_id: int = 7, *, user_id: int = 50, question_ids: list[int] | None = None) -> Paper:
    paper = Paper(
        user_id=user_id,
        title="期中卷",
        constraint_json={"seed": 7},
        question_ids=question_ids if question_ids is not None else [501],
        total_score=3,
        duration_min=60,
        status="草稿",
        generated_by="manual",
    )
    paper.id = paper_id
    paper.created_at = NOW
    return paper


class ExportSession:
    """get_paper 查询顺序：get(Paper) → details rows → kp rows；导出再 get(Subject)。"""

    def __init__(self, *, paper: Paper, detail_rows: list[tuple]) -> None:
        self.paper = paper
        self.results = [list(detail_rows), [(501, 117)]]
        self.user = _user()

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper.id == pk else None
        if model is Subject:
            subject = Subject(name="高中数学", code="math")
            subject.id = pk
            return subject
        return None

    def execute(self, statement):  # noqa: ANN001, ANN201
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user if "users" in str(statement) else None


def _detail_rows() -> list[tuple]:
    return [
        (501, 7, "单选", 2, "题干 501 $x^2$", [{"key": "A", "text": "选项 A"}], "答案 501", None, True, "exam")
    ]


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session: ExportSession, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture()
def fake_renderer(monkeypatch):
    calls: dict[str, str] = {}

    def _render(html_text: str, header: str, footer: str) -> bytes:
        calls["html"] = html_text
        return b"%PDF-1.4 fake pdf"

    monkeypatch.setattr(pdf_service, "render_pdf", _render)
    return calls


def test_export_requires_login_returns_401(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    app.dependency_overrides[get_db] = lambda: session
    response = TestClient(app).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 401


def test_export_forbids_other_user_returns_403(fake_renderer) -> None:
    session = ExportSession(paper=_paper(user_id=99), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_export_missing_paper_returns_404(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/999/export.pdf")
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_export_empty_paper_returns_409(fake_renderer) -> None:
    session = ExportSession(paper=_paper(question_ids=[]), detail_rows=[])
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 409
    assert response.json()["message"] == "试卷没有可导出的题目"


def test_export_questions_returns_pdf_bytes(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert 'filename="paper-7-questions.pdf"' in disposition
    assert f"filename*=UTF-8''{quote('期中卷-题干卷.pdf')}" in disposition
    assert "答案：" not in fake_renderer["html"]


def test_export_answers_returns_filename_with_answer_label(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf?variant=answers")

    assert response.status_code == 200
    assert f"filename*=UTF-8''{quote('期中卷-答案卷.pdf')}" in response.headers["content-disposition"]
    assert "答案：" in fake_renderer["html"]


def test_export_invalid_variant_returns_422(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf?variant=both")
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_export_renderer_error_returns_500(monkeypatch) -> None:
    def _boom(html_text: str, header: str, footer: str) -> bytes:
        raise RuntimeError("浏览器崩了")

    monkeypatch.setattr(pdf_service, "render_pdf", _boom)
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")

    assert response.status_code == 500
    assert response.json()["code"] == 50000
    assert "浏览器崩了" not in response.text
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_api.py -q
```

Expected: 8 failed（404/405，路由不存在）。

- [ ] **Step 3: 加路由**

`backend/app/api/v1/papers.py` 顶部补：

```python
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status
```

（保留已有的 `from fastapi import APIRouter, Depends, status` 时不要重复导入，合并成一行。）

补 service 导入：

```python
from app.services import paper_plan_service, pdf_service
```

在 `@router.get("/{paper_id}")` **之前**插入：

```python
@router.get("/{paper_id}/export.pdf")
def export_paper_pdf(
    paper_id: int,
    variant: Literal["questions", "answers"] = Query(default="questions"),
    session: Session = Depends(get_db),
    user: User = Depends(require_role("student")),
) -> Response:
    """导出题干卷/答案卷；实时渲染，不写库、不缓存。"""
    content, filename = pdf_service.export_pdf(
        session,
        user_id=user.id,
        paper_id=paper_id,
        variant=variant,
        now=datetime.now(timezone.utc),
    )
    disposition = (
        f'attachment; filename="paper-{paper_id}-{variant}.pdf"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )
```

- [ ] **Step 4: 跑接口测试**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_pdf_api.py -q
```

Expected: `8 passed`。

- [ ] **Step 5: 更新契约文档**

`docs/API.md` 里把 `### GET /api/v1/papers/{id}/export.pdf` 整段替换为：

```markdown
### GET /api/v1/papers/{id}/export.pdf
- 权限：student（本人）；不存在 404/40400，别人的 403/40300
- 查询参数：`variant`，`questions`（默认，题干卷）| `answers`（答案卷）；其他值 422/42200
- 类型：同步（Playwright 渲染 A4 PDF，超时 30s；失败 500/50000；空卷 409/40900）
- 出参：`application/pdf` 字节流（**不套 Envelope**）；`Content-Disposition` 同时给 ASCII 名 `paper-{id}-{variant}.pdf` 与 RFC 5987 中文名 `{标题}-题干卷.pdf` / `{标题}-答案卷.pdf`
- 说明：实时渲染、不落库不缓存；题干卷单选/填空留 2 行、解答留 60mm，答案卷给题干 + 答案 + 解析；题干先 HTML 转义再由 KaTeX 渲染 `$...$`
```

`docs/SCHEMA.md` 的 `papers` 小节（§6.1）末尾追加一行：

```markdown
> PDF 导出（S5-3）不落库、不缓存文件：每次按 `question_ids` 顺序实时渲染，缺题跳过并在 `missing_question_ids` 体现（与 `GET /papers/{id}` 一致）。
```

- [ ] **Step 6: 全量后端回归**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest -q
```

Expected: `1307 passed, 2 warnings`（1298 基线 + 9 + 8 = 1315？实测数字为准，只要全绿、无新增 warning 即可；在提交信息里写实测值）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/papers.py backend/tests/test_pdf_api.py docs/API.md docs/SCHEMA.md
git commit -m "feat(s5-3): 导出接口与 PDF 下载契约"
```

---

### Task 6: 前端导出按钮

**Files:**
- Modify: `web/src/api/papers.ts`
- Modify: `web/src/api/papers.spec.ts`
- Modify: `web/src/views/papers/Generate.vue`
- Modify: `web/src/views/papers/Generate.spec.ts`

**Interfaces:**
- Consumes: `GET /papers/{id}/export.pdf`（Task 5）。
- Produces: `exportPaperPdf(id: number, variant: 'questions' | 'answers'): Promise<Blob>`；页面 `data-testid="export-questions"` / `data-testid="export-answers"`。

- [ ] **Step 1: 写失败测试（API 层）**

在 `web/src/api/papers.spec.ts` 追加：

```ts
it('requests the export as a blob with the chosen variant', async () => {
  const blob = new Blob(['%PDF-1.4'], { type: 'application/pdf' })
  httpGet.mockResolvedValue({ data: blob })

  const result = await exportPaperPdf(7, 'answers')

  expect(httpGet).toHaveBeenCalledWith('/papers/7/export.pdf', {
    params: { variant: 'answers' },
    responseType: 'blob',
    timeout: 60_000,
  })
  expect(result).toBe(blob)
})
```

并在文件顶部 import 里补 `exportPaperPdf`；确认该测试文件里 mock 的 `httpGet` 变量名与既有用例一致（若不是 `httpGet`，按现有名字替换）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run test:run -- src/api/papers.spec.ts
```

Expected: `exportPaperPdf is not a function`（或 TS 报错）。

- [ ] **Step 3: 实现 API**

`web/src/api/papers.ts` 末尾追加：

```ts
export async function exportPaperPdf(
  id: number,
  variant: 'questions' | 'answers',
): Promise<Blob> {
  const resp = await http.get<Blob>(`${API_PREFIX}/papers/${id}/export.pdf`, {
    params: { variant },
    responseType: 'blob',
    timeout: 60_000,
  })
  return resp.data
}
```

- [ ] **Step 4: 跑 API 测试确认通过**

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run test:run -- src/api/papers.spec.ts
```

Expected: 该文件全绿（原 4 条 + 新 1 条）。

- [ ] **Step 5: 写失败测试（页面）**

在 `web/src/views/papers/Generate.spec.ts` 的 `papers` mock 里加：

```ts
exportPaperPdf: vi.fn(),
```

追加测试：

```ts
it('shows export buttons only after the paper is saved', async () => {
  papers.generatePaper.mockResolvedValue(preview())
  papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
  vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
  const wrapper = await mountView()
  await generate(wrapper)
  expect(wrapper.find('[data-testid="export-questions"]').exists()).toBe(false)

  await wrapper.find('[data-testid="save-button"]').trigger('click')
  await flushPromises()

  expect(wrapper.find('[data-testid="export-questions"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="export-answers"]').exists()).toBe(true)
})

it('downloads the saved paper as an answer PDF', async () => {
  papers.generatePaper.mockResolvedValue(preview())
  papers.savePaper.mockResolvedValue({ id: 7, title: '我的卷', status: '草稿' })
  papers.exportPaperPdf.mockResolvedValue(new Blob(['%PDF-1.4']))
  vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '我的卷' } as never)
  const createObjectURL = vi.fn(() => 'blob:paper')
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
  const wrapper = await mountView()
  await generate(wrapper)
  await wrapper.find('[data-testid="save-button"]').trigger('click')
  await flushPromises()

  await wrapper.find('[data-testid="export-answers"]').trigger('click')
  await flushPromises()

  expect(papers.exportPaperPdf).toHaveBeenCalledWith(7, 'answers')
  expect(createObjectURL).toHaveBeenCalledTimes(1)
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:paper')
})
```

- [ ] **Step 6: 跑测试确认失败**

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run test:run -- src/views/papers/Generate.spec.ts
```

Expected: 2 failed（按钮不存在）。

- [ ] **Step 7: 改页面**

`Generate.vue` 的 import 行改为：

```ts
import { exportPaperPdf, generatePaper, replacePaperItem, savePaper } from '@/api/papers'
```

在 `saving` 附近加状态：

```ts
const savedPaperId = ref<number | null>(null)
const exporting = ref<'questions' | 'answers' | null>(null)
```

`onSave` 里把成功提示改为记录 id：

```ts
    savedPaperId.value = paper.id
    ElMessage.success(`已保存试卷 #${paper.id}`)
```

在 `onSave` 之后加：

```ts
async function onExport(variant: 'questions' | 'answers'): Promise<void> {
  if (!savedPaperId.value) return
  exporting.value = variant
  try {
    const blob = await exportPaperPdf(savedPaperId.value, variant)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `试卷-${savedPaperId.value}-${variant === 'answers' ? '答案卷' : '题干卷'}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = null
  }
}
```

模板里 `preview-actions` 的保存按钮之后插入：

```html
          <el-button
            v-if="savedPaperId"
            data-testid="export-questions"
            :loading="exporting === 'questions'"
            @click="onExport('questions')"
          >
            导出题干卷
          </el-button>
          <el-button
            v-if="savedPaperId"
            data-testid="export-answers"
            :loading="exporting === 'answers'"
            @click="onExport('answers')"
          >
            导出答案卷
          </el-button>
          <span v-if="savedPaperId" class="export-hint">导出的为已保存版本</span>
```

样式区补：

```css
.export-hint {
  font-size: 12px;
  color: #909399;
}
```

- [ ] **Step 8: 跑页面测试 + 前端全量 + 构建**

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run test:run -- src/views/papers/Generate.spec.ts
npm run test:run
npm run build
```

Expected: 页面 13 passed；全量 `285 passed / 45 files`（282 + 1 + 2）；build 退出 0。

- [ ] **Step 9: Commit**

```bash
git add web/src/api/papers.ts web/src/api/papers.spec.ts web/src/views/papers/Generate.vue web/src/views/papers/Generate.spec.ts
git commit -m "feat(s5-3): 组卷页导出题干卷/答案卷按钮"
```

---

### Task 7: 真机验收 + 文档同步 + 全量回归

**Files:**
- Create: `.sdd/s5-3/export_check.py`（真机 HTTP + pdfplumber 抽文字）
- Create: `.sdd/s5-3/check.cjs`（Chrome CDP 点按钮下载）
- Create: `.sdd/s5-3/acceptance-evidence.md`
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-060）、`AGENTS.md §9.6`、`docs/AI协作开发实施计划.md`

**Interfaces:**
- Consumes: 全部已交付代码；环境 `backend/.env` 的真实库；学生 50 的 token。

- [ ] **Step 1: 起服务**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --log-level warning
```

（后台 job；另起一个 8032 也可，按既有两个端口的做法。前端 `web/.env.development` 指向 `http://127.0.0.1:8000`，CORS 只放行 `http://localhost:5173`，所以浏览器验收必须前端跑 5173。）

```bash
cd /e/BiShe-AIStudy/study-agent/web
npm run dev    # 5173
```

- [ ] **Step 2: 写并跑 `export_check.py`（真机导出 + pdfplumber）**

```python
"""S5-3 真机验收：保存一份卷 → 导出两卷 → pdfplumber 抽文字核对。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pdfplumber

BASE = "http://127.0.0.1:8000/api/v1"
OUT = Path(__file__).resolve().parent
TOKEN = Path(OUT / "token.txt").read_text(encoding="utf-8").strip()

client = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {TOKEN}"})


def save_paper() -> int:
    candidates = client.post(
        f"{BASE}/papers/generate",
        json={
            "kp_ids": [117, 128, 133],
            "total_questions": 5,
            "qtype_ratio": {"解答": 1.0},
            "difficulty_dist": {"2": 0.2, "3": 0.6, "4": 0.2},
            "total_score": 40,
            "seed": 424242,
        },
    ).json()["data"]
    assert candidates["items"], "候选为空，先确认题库/排除天数"
    saved = client.post(
        f"{BASE}/papers",
        json={
            "title": "S5-3 验收卷",
            "constraint": candidates["constraint"],
            "question_ids": [item["question_id"] for item in candidates["items"]],
            "duration_min": candidates["constraint"]["duration_min"],
        },
    )
    assert saved.status_code == 201, saved.text
    return saved.json()["data"]["id"]


def export(paper_id: int, variant: str) -> tuple[Path, dict[str, str]]:
    resp = client.get(f"{BASE}/papers/{paper_id}/export.pdf", params={"variant": variant})
    assert resp.status_code == 200, (resp.status_code, resp.text[:200])
    path = OUT / f"paper-{paper_id}-{variant}.pdf"
    path.write_bytes(resp.content)
    return path, dict(resp.headers)


def extract(path: Path) -> tuple[str, int]:
    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        return text, len(pdf.pages)


def main() -> None:
    paper_id = save_paper()
    report: dict[str, object] = {"paper_id": paper_id, "variants": {}}
    for variant in ("questions", "answers"):
        path, headers = export(paper_id, variant)
        text, pages = extract(path)
        report["variants"][variant] = {
            "path": path.name,
            "bytes": path.stat().st_size,
            "pages": pages,
            "chars": len(text),
            "has_title": "S5-3 验收卷" in text,
            "has_q1": "1." in text,
            "has_math_text": "x" in text,
            "has_answer": "答案：" in text,
            "has_page_footer": "第 1" in text,
            "content_disposition": headers.get("content-disposition"),
        }
    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    (OUT / "accept.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

运行前先把 token 写到 `.sdd/s5-3/token.txt`（生成方式）：

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
from app.core.security import create_access_token
Path("/e/BiShe-AIStudy/.sdd/s5-3/token.txt").write_text(
    create_access_token(user_id=50, role="student").token, encoding="utf-8"
)
print("token written")
PY
```

跑：

```bash
cd /e/BiShe-AIStudy/.sdd/s5-3
/e/BiShe-AIStudy/study-agent/.venv/Scripts/python.exe export_check.py
```

Expected：`accept.json` 里 `questions` 与 `answers` 都是 `pages >= 1`、`bytes > 20000`、`has_title=true`、`has_page_footer=true`；`answers.has_answer=true`、`questions.has_answer=false`。若 `chars < 200`，优先怀疑中文字体/KaTeX 字体未加载，按 `docs/spec/s5-3-pdf-export.md` §11 排查，**不要**改断言凑通过。

- [ ] **Step 3: 浏览器点按钮下载（CDP）**

写 `.sdd/s5-3/check.cjs`（复用 S5-2 的 CDP 骨架：连 9222、注入 token、操作页面、下载目录轮询）：

```js
// 真浏览器验收：生成 → 保存 → 点两个导出按钮 → 检查下载文件
const fs = require('node:fs')
const path = require('node:path')

const TOKEN = fs.readFileSync(path.join(__dirname, 'token.txt'), 'utf8').trim()
const DOWNLOADS = path.join(__dirname, 'downloads')
fs.mkdirSync(DOWNLOADS, { recursive: true })
for (const name of fs.readdirSync(DOWNLOADS)) fs.unlinkSync(path.join(DOWNLOADS, name))

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const log = (...args) => console.log(new Date().toISOString().slice(11, 19), ...args)

async function main() {
  const targets = await (await fetch('http://127.0.0.1:9222/json/list')).json()
  const page = targets.find((target) => target.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message)
      pending.delete(message.id)
    }
  })
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const current = ++id
      const timer = setTimeout(() => {
        pending.delete(current)
        reject(new Error(`CDP timeout: ${method}`))
      }, 30000)
      pending.set(current, (message) => {
        clearTimeout(timer)
        resolve(message)
      })
      ws.send(JSON.stringify({ id: current, method, params }))
    })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    return result.result?.result?.value
  }

  await new Promise((resolve) => ws.addEventListener('open', resolve))
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: DOWNLOADS })

  await send('Page.navigate', { url: 'http://localhost:5173/papers/generate' })
  await sleep(2500)
  await evaluate(`localStorage.setItem('study-agent-token', ${JSON.stringify(TOKEN)}); 'ok'`)
  await send('Page.navigate', { url: 'http://localhost:5173/papers/generate' })
  await sleep(5000)
  log('url', await evaluate(`location.href`))

  await evaluate(
    `document.querySelector('[data-testid="kp-tree"] .el-tree-node__expand-icon').click(); 'ok'`,
  )
  await sleep(800)
  await evaluate(
    `document.querySelectorAll('[data-testid="kp-tree"] input[type="checkbox"]')[3].click(); 'ok'`,
  )
  await sleep(400)
  await evaluate(`(() => {
    const input = document.querySelector('[data-testid="total-questions"] input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, '3')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
    return input.value
  })()`)
  await sleep(300)
  await evaluate(`document.querySelector('[data-testid="generate-button"]').click(); 'ok'`)
  await sleep(4000)
  const rowCount = await evaluate(`document.querySelectorAll('.el-table__row').length`)
  log('preview rows', rowCount)

  await evaluate(`document.querySelector('[data-testid="save-button"]').click(); 'ok'`)
  await sleep(1000)
  await evaluate(`(() => {
    const input = document.querySelector('.el-message-box__input input')
    input.value = 'S5-3 浏览器验收卷'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    const confirm = [...document.querySelectorAll('.el-message-box__btns button')]
      .find((button) => button.textContent.includes('保存'))
    confirm?.click()
    return 'submitted'
  })()`)
  await sleep(3000)
  const savedHint = /已保存试卷 #(\d+)/.exec(await evaluate('document.body.innerText'))?.[0] ?? ''
  log('saved', savedHint)

  const buttonsVisible = await evaluate(`Boolean(
    document.querySelector('[data-testid="export-questions"]') &&
    document.querySelector('[data-testid="export-answers"]')
  )`)
  log('buttons visible', buttonsVisible)
  if (!buttonsVisible) throw new Error('保存后没有出现导出按钮')

  await evaluate(`document.querySelector('[data-testid="export-questions"]').click(); 'ok'`)
  await sleep(4000)
  await evaluate(`document.querySelector('[data-testid="export-answers"]').click(); 'ok'`)

  let files = []
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await sleep(500)
    files = fs
      .readdirSync(DOWNLOADS)
      .filter((name) => name.endsWith('.pdf'))
      .map((name) => ({ name, bytes: fs.statSync(path.join(DOWNLOADS, name)).size }))
    if (files.length >= 2) break
  }
  log('downloads', files)

  const shot = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(path.join(__dirname, 'pdf-buttons.png'), Buffer.from(shot.result.data, 'base64'))

  const report = {
    url: 'http://localhost:5173/papers/generate',
    rowCount,
    savedHint,
    buttonsVisible,
    downloads: files,
    screenshot: 'pdf-buttons.png',
  }
  fs.writeFileSync(path.join(__dirname, 'browser.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  if (files.length < 2) throw new Error('两个导出按钮没有产生两个 PDF 下载')
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error('ERR', error.message)
    process.exit(1)
  })
```

Headless Chrome 起法（与 S5-2 相同）：

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new \
  --remote-debugging-port=9222 --user-data-dir=/tmp/s53-chrome about:blank
```

```bash
cd /e/BiShe-AIStudy/.sdd/s5-3
node check.cjs
```

Expected：`browser.json` 里 `buttonsVisible=true`、`downloads` 两条且大小 > 20000；无 `ERR` 输出。

- [ ] **Step 4: 写 `acceptance-evidence.md`**

至少包含：环境（服务端口/依赖版本/真实库题量）、`accept.json` 的真实数字（两卷页数/字节/字符数/关键断言）、浏览器下载结果、失败路径实测（404/409/422/500 的原始状态码）、耗时（首次/第二次导出）、已知问题（Docker 字体/chromium 未做、不支持并行导出、空 `missing_question_ids` 行为）。

- [ ] **Step 5: 文档同步**

`docs/PROGRESS.md`：
- 阶段行加 S5-3；
- 最近完成改为 S5-3（数字用实测）；S5-2 顺延为「上一完成」；
- 加「关键口径（S5-3）」「验收（S5-3）」两条；
- 下一步改为 S5-4；
- 任务清单 `- [ ] S5-3 PDF 导出` → `- [x]`；
- 待解决问题追加：Docker 预装 chromium + `fonts-noto-cjk` 未落地；导出串行（单渲染线程）；不缓存；
- 变更日志顶部加 `### 2026-11-13（S5-3）`（交付/拍板/测试/真实验收/文档同步）。

`docs/DECISIONS.md` 追加 `## D-060 PDF 导出管线（S5-3）`，写：Jinja2+KaTeX+Playwright 的三层拆分；`variant` 单接口；同步与 500 口径；KaTeX 静态资源进仓库；单渲染线程（线程亲和性）；不缓存；A4 留白与页眉页脚；Docker 字体/chromium 待办；测试全 mock。

`AGENTS.md §9.6` 在组卷 API 锚点后加：
`- PDF 导出样例：backend/app/services/pdf_service.py + backend/app/templates/paper_pdf.html + backend/app/static/katex（build_context/render_html 纯函数、render_pdf 单渲染线程、export_pdf 注入 renderer；variant=questions|answers；空卷 409、渲染失败 500）`

`docs/AI协作开发实施计划.md`：`[ ] S5-3 PDF 导出` → `[x] S5-3 PDF 导出`。

- [ ] **Step 6: 全量回归**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest -q
cd ../web
npm run test:run
npm run build
```

Expected：后端全绿（实测值贴进报告）；前端全绿；build 退出 0。

- [ ] **Step 7: Commit**

```bash
cd /e/BiShe-AIStudy/study-agent
git add docs/PROGRESS.md docs/DECISIONS.md AGENTS.md "docs/AI协作开发实施计划.md"
git commit -m "docs(s5-3): PDF 导出验收记录与口径定稿（D-060）"
```

（`.sdd/` 不进 git；`backend/tmp*.pdf`、`.sdd/s5-3/*.pdf` 不要提交。）