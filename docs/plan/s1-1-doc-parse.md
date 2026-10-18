# S1-1 文档解析为结构化文本 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 PDF/DOCX → 统一结构化文本（带页码/标题层级），Docling 优先 + PyMuPDF 自动降级，供 S1-2 切片器消费。

**Architecture:** 门面 `parse_document()` 按扩展名分发：PDF 先做 `is_scanned` 采样检测，再走 Docling 适配器（消费 DoclingDocument 结构化对象），失败/未安装则打 WARNING 降级 PyMuPDF；DOCX 走 python-docx（Heading 样式 → 层级栈）。所有适配器实现 `DocumentParser` 抽象接口（任务卡要求可替换）。

**Tech Stack:** Python 3.11（仓库 `.venv`）、Pydantic v2、docling、pymupdf、python-docx、pytest。

**Spec:** `docs/spec/s1-1-doc-parse.md`（本 plan 一切设计依据出自它，执行者两份都要读）。

## Global Constraints

- Python 解释器一律用 `E:\BiShe-AIStudy\study-agent\.venv\Scripts\python.exe`；pip 走华为云镜像（`-i https://repo.huaweicloud.com/repository/pypi/simple`）
- 测试命令一律从 `backend/` 目录用 `python -m pytest`（`-m` 会把 cwd 加进 sys.path，`import app` 才能成立；裸 `pytest` 会 import 失败）
- 阶段 1 只写命令行代码，不接 Web；`docs/API.md`、`docs/SCHEMA.md` 本卡不动
- 解析器代码只 import `app.core.*` 与第三方库，禁止 import `app.services` 等（分层红线）
- 可控错误一律用 `app.core.exceptions.InvalidParamError(message)`（单参构造，S0-5 体系）
- 本项目惯例：**整卡一个提交** `feat(s1-1)`（AGENTS §10.6），plan 各步骤不单独 commit；提交发生在 Task 9 用户验收之后
- 所有函数签名带类型标注；注释只写"为什么"
- Windows 控制台输出中文前设 `$env:PYTHONIOENCODING='utf-8'`
- docling **安装失败不卡进度**（任务卡坑②）：跳过 Task 1 的 docling 部分，后续照常（适配器代码照写，mock 测试照跑，验收走 PyMuPDF），并在 Task 9 的 PROGRESS 里记 TODO

---

### Task 1: 依赖安装与 docling 实地探测

**Files:**
- Create（用后即删）: `scripts/_probe_docling.py`
- Modify（Task 9 才写入正式文件）: 无

**Interfaces:**
- Produces: 实测记录（安装体积、首跑耗时、`iterate_items` 返回形状）——Task 5/9 依赖；环境里可用的 `pymupdf`、`python-docx`（、`docling`）

- [ ] **Step 1: 安装小依赖（必成）**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple pymupdf python-docx
```

Expected: `Successfully installed pymupdf-1.2x.x python-docx-1.1.x`（记下版本号，Task 9 要钉进 requirements.txt）。pip 若因 stderr 通知返回非零码，以"Successfully installed"为准。

- [ ] **Step 2: 安装 docling（时限 20 分钟，装不上就走降级预案）**

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple docling
```

Expected: `Successfully installed docling-2.x ...`（记版本与总下载量）。**失败/超时处理**：记下报错，跳过 Step 3-5 与 Task 5 的真实运行（mock 测试不受影响），Global Constraints 的降级预案生效。

- [ ] **Step 3: 写探针脚本** `scripts/_probe_docling.py`

```python
"""一次性探针：验证所装 docling 的真实 API 形状 + 首跑模型下载耗时。Task 1 用后即删。"""
from __future__ import annotations

import time
from pathlib import Path

import pymupdf

pdf = Path(__file__).resolve().parents[1] / "tmp_probe.pdf"
with pymupdf.open() as d:
    page = d.new_page()
    page.insert_text((72, 72), "第一章 数列", fontname="china-s")
    page.insert_text((72, 110), "1.1 等差数列", fontname="china-s")
    page.insert_text((72, 150), "通项公式 an = a1 + (n-1)d，前 n 项和 Sn 公式如下。", fontname="china-s")
    d.save(pdf)

from docling.document_converter import DocumentConverter  # noqa: E402

t0 = time.time()
document = DocumentConverter().convert(str(pdf)).document
print(f"首跑耗时（含模型下载）: {time.time() - t0:.1f}s")
print("document 类型:", type(document).__name__)
print("---- iterate_items 返回形状（前 12 个）----")
for i, raw in enumerate(document.iterate_items()):
    item = raw[0] if isinstance(raw, tuple) else raw
    if i >= 12:
        break
    print(
        f"raw={type(raw).__name__} item={type(item).__name__}",
        f"label={getattr(item, 'label', None)}",
        f"text={(getattr(item, 'text', '') or '')[:24]!r}",
        f"prov={getattr(item, 'prov', None)}",
    )
print("tables 数:", len(getattr(document, "tables", [])))
```

- [ ] **Step 4: 跑探针（时限 30 分钟——首次要下 100–300MB 模型）**

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\_probe_docling.py
```

Expected: 打印耗时、`iterate_items` 每个 item 的 `raw=`（tuple 或裸 item）、`label`（title/section_header/paragraph/page_footer…）、`prov`（含 page_no）。**把这些输出全文记录下来**（贴回会话），Task 5 的映射代码以此为准校正；若 `label`/`prov` 字段名与 plan 假设不符，在 Task 5 Step 3 调整并注明差异。

- [ ] **Step 5: 清理探针产物**

```powershell
Remove-Item scripts\_probe_docling.py, tmp_probe.pdf -ErrorAction SilentlyContinue
```

---

### Task 2: models.py —— 统一结构（TDD）

**Files:**
- Create: `backend/app/ai/parse/models.py`
- Test: `backend/tests/test_parse.py`

**Interfaces:**
- Produces: `BlockType`（str Enum: text/formula/question）、`ParsedBlock{text, page_no: int|None, heading_path: list[str]=[], type: BlockType=text}`、`ParsedDocument{source, parser: "docling"|"pymupdf"|"docx", is_scanned=False, degraded_reason: str|None=None, blocks: list[ParsedBlock]=[]}`、`ParserName` 类型别名

- [ ] **Step 1: 写失败测试**（`backend/tests/test_parse.py`，新建）

```python
"""S1-1 解析模块测试（spec §7）：自造 fixture，零网络零模型。"""
from __future__ import annotations

from pathlib import Path

import docx as python_docx
import pymupdf
import pytest

from app.ai.parse.models import BlockType, ParsedBlock, ParsedDocument


def test_block_defaults() -> None:
    """heading_path 抽不到默认空列表；type 默认 text（不瞎编）。"""
    b = ParsedBlock(text="通项公式", page_no=1)
    assert b.heading_path == []
    assert b.type is BlockType.text


def test_block_docx_page_none() -> None:
    """docx 无分页概念：page_no 允许 None（spec 设计决策 4）。"""
    b = ParsedBlock(text="错位相减法", page_no=None)
    assert b.page_no is None


def test_document_envelope() -> None:
    d = ParsedDocument(source="a.pdf", parser="pymupdf", blocks=[ParsedBlock(text="x", page_no=1)])
    assert d.is_scanned is False
    assert d.degraded_reason is None
    assert d.parser == "pymupdf"
    assert d.blocks[0].type.value == "text"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest tests/test_parse.py -v
```

Expected: 3 个 FAIL/ERROR，`ModuleNotFoundError: No module named 'app.ai.parse'`

- [ ] **Step 3: 实现** `backend/app/ai/parse/models.py`

```python
"""S1-1 解析统一结构（契约：docs/spec/s1-1-doc-parse.md §2）。

任务卡的 [{text, page_no, heading_path, type}] 列表 = ParsedDocument.blocks；
外层信封（parser/is_scanned/degraded_reason）是审计信息。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

ParserName = Literal["docling", "pymupdf", "docx"]


class BlockType(str, Enum):
    """块类型。question 枚举保留但由 S1-2 切片器填充（spec 设计决策 3：有依据才标）。"""

    text = "text"
    formula = "formula"
    question = "question"


class ParsedBlock(BaseModel):
    text: str  # 表格转 Markdown 后也塞这里
    page_no: int | None  # 1-based；None 仅用于 docx（Word 分页由渲染器决定，文件里不存在）
    heading_path: list[str] = []  # 标题层级链；抽不到就空列表，禁止编造
    type: BlockType = BlockType.text


class ParsedDocument(BaseModel):
    source: str
    parser: ParserName
    is_scanned: bool = False
    degraded_reason: str | None = None  # 仅降级（docling→pymupdf）或扫描版提示时非空
    blocks: list[ParsedBlock] = []
```

- [ ] **Step 4: 跑测试确认通过**

同 Step 2 命令。Expected: `3 passed`

---

### Task 3: base.py + PyMuPDF 兜底 + is_scanned 检测（TDD）

**Files:**
- Create: `backend/app/ai/parse/base.py`、`backend/app/ai/parse/pdf_pymupdf.py`
- Test: `backend/tests/test_parse.py`（追加）

**Interfaces:**
- Produces: `DocumentParser` 抽象基类（`name: ClassVar[str]`、`supports(path: Path) -> bool`、`parse(path: Path) -> ParsedDocument`）；`PyMuPDFParser`（name="pymupdf"）；`detect_scanned(path: Path, sample_pages: int = 10, min_chars: int = 50) -> bool`

- [ ] **Step 1: 追加失败测试**（`backend/tests/test_parse.py`）

```python
# ---- fixture 工厂：自造小文件（明显假、结构真；零网络零模型）----

def make_pdf(path: Path, texts: list[str | None]) -> Path:
    """texts 每页一项正文；None=空白页（扫描版模拟）。"""
    with pymupdf.open() as d:
        for t in texts:
            page = d.new_page()
            if t:
                page.insert_text((72, 72), t, fontname="china-s")
        d.save(path)
    return path


def test_pymupdf_blocks_and_pages(tmp_path: Path) -> None:
    from app.ai.parse.pdf_pymupdf import PyMuPDFParser

    pdf = make_pdf(tmp_path / "note.pdf", ["第一章 数列", "等差数列通项公式", "错位相减法适用差比混合"])
    doc = PyMuPDFParser().parse(pdf)
    assert doc.parser == "pymupdf"
    assert doc.is_scanned is False
    assert [b.page_no for b in doc.blocks] == [1, 2, 3]  # 1-based（spec 设计决策 5）
    assert all(b.heading_path == [] for b in doc.blocks)  # 兜底不猜层级（决策 2）
    assert all(b.type.value == "text" for b in doc.blocks)


def test_pymupdf_skips_blank_pages(tmp_path: Path) -> None:
    from app.ai.parse.pdf_pymupdf import PyMuPDFParser

    pdf = make_pdf(tmp_path / "mixed.pdf", ["有文字的页", None, "另一页"])
    doc = PyMuPDFParser().parse(pdf)
    assert [b.page_no for b in doc.blocks] == [1, 3]


def test_detect_scanned_blank_pdf(tmp_path: Path) -> None:
    from app.ai.parse.pdf_pymupdf import detect_scanned

    assert detect_scanned(make_pdf(tmp_path / "blank.pdf", [None, None, None])) is True
    assert detect_scanned(make_pdf(tmp_path / "text.pdf", ["这一页有足够多的文字内容" * 5])) is False
```

- [ ] **Step 2: 跑测试确认失败**（同 Task 2 Step 2 命令）。Expected: 3 个新测试 FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现** `backend/app/ai/parse/base.py`

```python
"""可替换解析器契约（任务卡要求 5：抽象接口，Docling/PyMuPDF/docx 都实现它）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from app.ai.parse.models import ParsedDocument


class DocumentParser(ABC):
    name: ClassVar[str]

    @abstractmethod
    def supports(self, path: Path) -> bool:
        """按扩展名判断本解析器是否处理该文件。"""

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """解析失败直接抛异常；降级决策统一由门面负责（spec §6）。"""
```

- [ ] **Step 4: 实现** `backend/app/ai/parse/pdf_pymupdf.py`

```python
"""PyMuPDF 兜底解析器 + 扫描版检测（spec §5.1 / §5.3）。

为什么 heading_path 恒为空：用字号/加粗猜标题是任务卡禁止的启发式；
兜底路径诚实降级——有页码、有文本、无层级（spec 设计决策 2）。
"""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from app.ai.parse.base import DocumentParser
from app.ai.parse.models import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)


def detect_scanned(path: Path, sample_pages: int = 10, min_chars: int = 50) -> bool:
    """前 N 页（不足取全部）严格多数页可抽文本 < min_chars → 判扫描版。

    先判断再决定（任务卡坑①）：扫描版不浪费 Docling 算力，直接留给下一任务的图片识别。
    """
    with pymupdf.open(path) as doc:
        count = min(len(doc), sample_pages)
        if count == 0:
            return True
        poor = sum(1 for i in range(count) if len(doc[i].get_text("text").strip()) < min_chars)
        return poor * 2 > count


class PyMuPDFParser(DocumentParser):
    name = "pymupdf"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        with pymupdf.open(path) as doc:
            for page_no, page in enumerate(doc, start=1):
                # get_text("blocks") 元组: (x0, y0, x1, y1, text, block_no, block_type)；0=文本块
                for raw in page.get_text("blocks"):
                    if raw[6] != 0:
                        continue
                    text = raw[4].strip()
                    if text:
                        blocks.append(ParsedBlock(text=text, page_no=page_no))
        return ParsedDocument(source=str(path), parser="pymupdf", blocks=blocks)
```

- [ ] **Step 5: 跑测试确认通过**。Expected: 累计 `6 passed`

---

### Task 4: docx_parser.py（TDD）

**Files:**
- Create: `backend/app/ai/parse/docx_parser.py`
- Test: `backend/tests/test_parse.py`（追加）

**Interfaces:**
- Produces: `DocxParser`（name="docx"）；纯函数 `heading_level(style_name: str | None) -> int | None`

- [ ] **Step 1: 追加失败测试**

```python
def make_docx(path: Path) -> Path:
    """标题 1 + 标题 2 + 正文 + 2x2 表格 的最小样张。"""
    d = python_docx.Document()
    d.add_paragraph("数列笔记", style="Heading 1")
    d.add_paragraph("错位相减法", style="Heading 2")
    d.add_paragraph("适用于等差乘等比型数列求和。")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "方法"
    t.cell(0, 1).text = "适用"
    t.cell(1, 0).text = "错位相减"
    t.cell(1, 1).text = "差比混合"
    d.save(path)
    return path


def test_heading_level_matches_cn_and_en() -> None:
    from app.ai.parse.docx_parser import heading_level

    assert heading_level("Heading 2") == 2
    assert heading_level("标题 3") == 3  # 中文 Word 样式名
    assert heading_level("heading 1") == 1  # 大小写不敏感
    assert heading_level("Normal") is None
    assert heading_level(None) is None


def test_docx_headings_table_and_no_page(tmp_path: Path) -> None:
    from app.ai.parse.docx_parser import DocxParser

    doc = DocxParser().parse(make_docx(tmp_path / "note.docx"))
    assert doc.parser == "docx"
    assert all(b.page_no is None for b in doc.blocks)  # spec 设计决策 4
    assert [b.text for b in doc.blocks[:3]] == ["数列笔记", "错位相减法", "适用于等差乘等比型数列求和。"]
    assert doc.blocks[0].heading_path == []  # h1 自己的路径不含自己
    assert doc.blocks[1].heading_path == ["数列笔记"]
    assert doc.blocks[2].heading_path == ["数列笔记", "错位相减法"]
    table_block = doc.blocks[3]
    assert "| 方法 |" in table_block.text and "| 差比混合 |" in table_block.text
    assert table_block.heading_path == ["数列笔记", "错位相减法"]
```

- [ ] **Step 2: 跑测试确认失败**。Expected: 2 个新测试 FAIL

- [ ] **Step 3: 实现** `backend/app/ai/parse/docx_parser.py`

```python
"""python-docx 解析器（spec §5.4）。

必须用 iter_inner_content()（python-docx ≥1.1）按文档顺序遍历段落与表格：
document.paragraphs 会丢表格位置，不可用。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import docx
import docx.table

from app.ai.parse.base import DocumentParser
from app.ai.parse.models import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

# "Heading 2" / "标题 2" / "heading 2"（中英文 Word 模板都用过）
_HEADING_RE = re.compile(r"^(?:heading|标题)\s*(\d)$", re.IGNORECASE)


def heading_level(style_name: str | None) -> int | None:
    """样式名 → 标题层级数字；非标题返回 None。"""
    if not style_name:
        return None
    m = _HEADING_RE.match(style_name.strip())
    return int(m.group(1)) if m else None


def _table_to_markdown(table: docx.table.Table) -> str:
    rows = [
        "| " + " | ".join(c.text.replace("\n", " ").strip() for c in r.cells) + " |"
        for r in table.rows
    ]
    if not rows:
        return ""
    sep = "| " + " | ".join(["---"] * len(table.rows[0].cells)) + " |"
    return "\n".join([rows[0], sep, *rows[1:]])


class DocxParser(DocumentParser):
    name = "docx"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".docx"

    def parse(self, path: Path) -> ParsedDocument:
        d = docx.Document(str(path))
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        skipped_images = 0
        for item in d.iter_inner_content():
            if isinstance(item, docx.table.Table):
                md = _table_to_markdown(item)
                if md:
                    blocks.append(ParsedBlock(text=md, page_no=None, heading_path=list(headings)))
                continue
            # Paragraph：图片以 drawing 形式内嵌，先数后跳（图片识别是下一任务）
            skipped_images += len(item._p.xpath(".//w:drawing"))
            level = heading_level(item.style.name if item.style is not None else None)
            text = item.text.strip()
            if level is not None:
                if text:
                    # 层级 1 重置栈、层级 n 截断到 n-1 再压入：h1→[h1]；h2→[h1,h2]
                    headings = headings[: level - 1] if level > 1 else []
                    headings.append(text)
                    blocks.append(ParsedBlock(text=text, page_no=None, heading_path=list(headings[:-1])))
                continue
            if text:
                blocks.append(ParsedBlock(text=text, page_no=None, heading_path=list(headings)))
        if skipped_images:
            logger.info("docx 跳过 %d 个图片对象（图片识别是下一任务）", skipped_images)
        return ParsedDocument(source=str(path), parser="docx", blocks=blocks)
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `8 passed`

---

### Task 5: pdf_docling.py —— Docling 适配器（mock TDD）

**Files:**
- Create: `backend/app/ai/parse/pdf_docling.py`
- Test: `backend/tests/test_parse.py`（追加）

**Interfaces:**
- Produces: `DocxParser` 无关——本文件产出 `DoclingParser`（name="docling"）；内部方法 `_items_to_blocks(doc: object) -> list[ParsedBlock]`（duck-typed，供 mock 测试）、`_page_of(item: object) -> int | None`、`_iter_items(doc: object) -> Iterator[tuple[object, int | None]]`
- Consumes: Task 1 Step 4 探针记录的真实 `iterate_items` 形状（若与下方假设不符，改映射并注明）

- [ ] **Step 1: 追加失败测试（假 doc 对象，不 import docling）**

```python
class _FakeProv:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _FakeItem:
    def __init__(self, label: str, text: str = "", page_no: int | None = 1) -> None:
        self.label = label
        self.text = text
        self.prov = [_FakeProv(page_no)] if page_no is not None else []


class _FakeTable:
    def __init__(self, page_no: int) -> None:
        self.label = "table"
        self.prov = [_FakeProv(page_no)]

    def export_to_markdown(self) -> str:
        return "| a | b |\n| --- | --- |\n| 1 | 2 |"


class _FakeDoc:
    def __init__(self, items: list) -> None:
        self._items = items

    def iterate_items(self) -> list:
        return self._items


def test_docling_mapping_and_heading_stack() -> None:
    from app.ai.parse.pdf_docling import DoclingParser

    fake = _FakeDoc(
        [
            (_FakeItem("title", "数学笔记"), 0),
            (_FakeItem("section_header", "数列"), 1),
            (_FakeItem("paragraph", "等差数列的通项公式。", page_no=2), None),
            (_FakeItem("page_footer", "第 2 页", page_no=2), None),  # 噪声，必须丢弃
            (_FakeTable(3), None),
        ]
    )
    blocks = DoclingParser()._items_to_blocks(fake)
    assert [b.text for b in blocks] == ["数学笔记", "数列", "等差数列的通项公式。",
                                        "| a | b |\n| --- | --- |\n| 1 | 2 |"]
    assert blocks[0].heading_path == []          # title 重置栈，自身路径为空
    assert blocks[1].heading_path == ["数学笔记"]
    assert blocks[2].heading_path == ["数学笔记", "数列"]
    assert blocks[3].heading_path == ["数学笔记", "数列"]  # 表格延续当前层级
    assert [b.page_no for b in blocks] == [1, 1, 2, 3]
    assert all(b.type.value == "text" for b in blocks)


def test_docling_non_tuple_iteration() -> None:
    """兼容只 yield 裸 item 的 docling 版本（spec：探针后校正）。"""
    from app.ai.parse.pdf_docling import DoclingParser

    fake = _FakeDoc([_FakeItem("paragraph", "裸 item")])  # 无 tuple 包装
    blocks = DoclingParser()._items_to_blocks(fake)
    assert [b.text for b in blocks] == ["裸 item"]
```

- [ ] **Step 2: 跑测试确认失败**。Expected: 2 个新测试 FAIL

- [ ] **Step 3: 实现** `backend/app/ai/parse/pdf_docling.py`

```python
"""Docling 适配器（spec §5.2 + 设计决策 1）。

消费 DoclingDocument 结构化对象而非其 Markdown 导出——统一结构需要每块
页码（prov），Markdown 序列化会丢页码。
docling 在 parse() 内延迟导入：未安装时 ImportError 才能被门面接住走降级链。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from app.ai.parse.base import DocumentParser
from app.ai.parse.models import ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

# 页眉页脚/脚注/图片是检索噪声，直接丢弃（spec §5.2）
_SKIP_LABELS = {"page_header", "page_footer", "footnote", "picture", "caption"}


class DoclingParser(DocumentParser):
    name: ClassVar[str] = "docling"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path) -> ParsedDocument:
        # 延迟导入（spec §6）：docling 缺失时让 ImportError 冒给门面降级
        from docling.document_converter import DocumentConverter

        document = DocumentConverter().convert(str(path)).document
        blocks = self._items_to_blocks(document)
        return ParsedDocument(source=str(path), parser="docling", blocks=blocks)

    # ---- 以下方法不 import docling 类型，用 duck-typing 便于 mock 测试 ----

    def _items_to_blocks(self, doc: object) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        headings: list[str] = []
        for item, level in self._iter_items(doc):
            label = getattr(item, "label", None)
            text = (getattr(item, "text", None) or "").strip()
            if label in ("title", "section_header"):
                if not text:
                    continue
                # title 视作第 0 层（重置栈）；section_header 按树深度截断再压入
                depth = 0 if label == "title" else (level if level is not None else 1)
                headings = headings[:depth]
                headings.append(text)
                blocks.append(ParsedBlock(text=text, page_no=self._page_of(item), heading_path=list(headings[:-1])))
                continue
            if label in _SKIP_LABELS:
                continue
            if hasattr(item, "export_to_markdown"):  # TableItem
                blocks.append(ParsedBlock(text=item.export_to_markdown(), page_no=self._page_of(item), heading_path=list(headings)))
                continue
            if text:
                blocks.append(ParsedBlock(text=text, page_no=self._page_of(item), heading_path=list(headings)))
        return blocks

    @staticmethod
    def _iter_items(doc: object) -> Iterator[tuple[object, int | None]]:
        """兼容两种 iterate_items 形状：(item, level) 元组 或 裸 item。"""
        for raw in doc.iterate_items():  # type: ignore[attr-defined]
            if isinstance(raw, tuple):
                item, level = raw[0], raw[1] if isinstance(raw[1], int) else None
                yield item, level
            else:
                yield raw, None

    @staticmethod
    def _page_of(item: object) -> int | None:
        prov = getattr(item, "prov", None)
        first = prov[0] if isinstance(prov, (list, tuple)) and prov else prov
        page = getattr(first, "page_no", None) or getattr(first, "pageno", None)
        return int(page) if page is not None else None
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `10 passed`

- [ ] **Step 5: 真实 docling 冒烟（仅 Task 1 装成功时）**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -c "from pathlib import Path; import pymupdf; p=Path('../tmp_s11.pdf'); d=pymupdf.open(); page=d.new_page(); page.insert_text((72,72),'第一章 数列',fontname='china-s'); page.insert_text((72,110),'1.1 等差数列',fontname='china-s'); page.insert_text((72,150),'通项公式 an=a1+(n-1)d。',fontname='china-s'); d.save(p); d.close(); from app.ai.parse.pdf_docling import DoclingParser; doc=DoclingParser().parse(p); [print(b.page_no, b.heading_path, repr(b.text[:30])) for b in doc.blocks]"
Remove-Item ..\tmp_s11.pdf -ErrorAction SilentlyContinue
```

Expected: 至少 3 个块；标题块 heading_path 正确、正文块带层级链。若 label/prov 与假设不符 → 按 Task 1 探针记录改 `_items_to_blocks` 的映射并注明改动。

---

### Task 6: 门面 + 配置开关（TDD）

**Files:**
- Create: `backend/app/ai/parse/__init__.py`
- Modify: `backend/app/core/config.py`（Settings 加字段）、根 `.env.example`
- Test: `backend/tests/test_parse.py`（追加）

**Interfaces:**
- Consumes: `PyMuPDFParser`、`detect_scanned`（Task 3）、`DocxParser`（Task 4）、`DoclingParser`（Task 5）、`InvalidParamError(message)`、`get_settings()`
- Produces: `parse_document(path: str | Path, *, force_pymupdf: bool | None = None) -> ParsedDocument`（全项目唯一解析入口）；`Settings.parse_force_pymupdf: bool = False`

- [ ] **Step 1: 追加失败测试**

```python
def test_facade_unsupported_ext(tmp_path: Path) -> None:
    from app.core.exceptions import InvalidParamError

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(InvalidParamError):
        parse_document(f)


def test_facade_missing_file(tmp_path: Path) -> None:
    from app.core.exceptions import InvalidParamError

    with pytest.raises(InvalidParamError):
        parse_document(tmp_path / "不存在.pdf")


def test_facade_scanned_early_return(tmp_path: Path) -> None:
    doc = parse_document(make_pdf(tmp_path / "blank.pdf", [None, None]))
    assert doc.is_scanned is True
    assert doc.blocks == []
    assert "扫描版" in (doc.degraded_reason or "")


def test_facade_force_pymupdf(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "note.pdf", ["快速路径内容"])
    doc = parse_document(pdf, force_pymupdf=True)
    assert doc.parser == "pymupdf"
    assert doc.degraded_reason and "PyMuPDF" in doc.degraded_reason


def test_facade_docx_dispatch(tmp_path: Path) -> None:
    doc = parse_document(make_docx(tmp_path / "note.docx"))
    assert doc.parser == "docx"


def test_facade_fallback_on_docling_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Docling 抛错 → 自动降级 PyMuPDF，degraded_reason 带原因（任务卡要求 5）。"""
    from app.ai.parse import pdf_docling

    def boom(self: object, path: Path) -> object:
        raise RuntimeError("docling 内部炸了")

    monkeypatch.setattr(pdf_docling.DoclingParser, "parse", boom)
    pdf = make_pdf(tmp_path / "note.pdf", ["降级链验证"])
    doc = parse_document(pdf)  # force=None 且 Settings 默认 False → 会先试 docling
    assert doc.parser == "pymupdf"
    assert doc.degraded_reason and doc.degraded_reason.startswith("Docling 降级")
    assert doc.blocks and doc.blocks[0].text == "降级链验证"
```

文件头部 import 处补：`from app.ai.parse import parse_document`（放在 `from app.ai.parse.models import ...` 之前）。

- [ ] **Step 2: 跑测试确认失败**。Expected: 6 个新测试 FAIL（`cannot import name 'parse_document'`）

- [ ] **Step 3: 实现** `backend/app/ai/parse/__init__.py`

```python
"""解析门面：parse_document 是全项目唯一解析入口（spec §3 架构图）。"""
from __future__ import annotations

import logging
from pathlib import Path

from app.ai.parse.models import ParsedDocument
from app.ai.parse.pdf_pymupdf import PyMuPDFParser, detect_scanned

logger = logging.getLogger(__name__)


def parse_document(path: str | Path, *, force_pymupdf: bool | None = None) -> ParsedDocument:
    """PDF/DOCX → 统一结构。降级决策集中在这里，适配器自身不吞异常（spec §6）。"""
    p = Path(path)
    if not p.exists():
        raise InvalidParamError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
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


from app.core.config import get_settings  # noqa: E402  延迟到尾部避免环
from app.core.exceptions import InvalidParamError  # noqa: E402
```

（若 import 环实际不存在，把两个尾部 import 挪到文件头部；门面已验证无环时优先正常顺序。）

- [ ] **Step 4: Settings 加字段**（`backend/app/core/config.py`，在 LLM 段之前插入）

```python
    # --- 解析（S1-1）---
    # True=跳过 Docling 走 PyMuPDF 快速路径（spec 设计决策 6：显式开关而非自动猜）
    parse_force_pymupdf: bool = False
```

- [ ] **Step 5: `.env.example` 追加**（读文件后追加到末尾）

```text
# --- 解析（S1-1）---
# true=PDF 解析跳过 Docling 直接走 PyMuPDF 快速路径（兜底质量：无标题层级）
PARSE_FORCE_PYMUPDF=false
```

- [ ] **Step 6: 跑全量测试**（含 S0-5 的 3 条，确认无回归）

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: `16 passed`（3 旧 + 13 新）

---

### Task 7: scripts/parse_demo.py 演示脚本

**Files:**
- Create: `scripts/parse_demo.py`
- 删除: `backend/app/ai/parse/.gitkeep`（有真实文件后）

**Interfaces:**
- Consumes: `parse_document`

- [ ] **Step 1: 实现** `scripts/parse_demo.py`

```python
"""S1-1 演示脚本：打印解析结果前 N 段（任务卡要求 6）。

用法（仓库根目录）：
    python scripts/parse_demo.py <文件> [--limit 50] [--force-pymupdf]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ai.parse import parse_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="文档解析演示（S1-1）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--limit", type=int, default=50, help="打印前 N 段（默认 50）")
    parser.add_argument("--force-pymupdf", action="store_true", help="跳过 Docling 走快速路径")
    args = parser.parse_args()

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    print(f"文件: {doc.source}")
    print(f"解析器: {doc.parser}    扫描版: {'是' if doc.is_scanned else '否'}")
    if doc.degraded_reason:
        print(f"降级/提示: {doc.degraded_reason}")
    print(f"块总数: {len(doc.blocks)}（打印前 {min(args.limit, len(doc.blocks))} 段）")
    print("-" * 72)
    for i, b in enumerate(doc.blocks[: args.limit], start=1):
        head = " > ".join(b.heading_path) if b.heading_path else "（无层级）"
        page = f"p.{b.page_no}" if b.page_no is not None else "p.无(docx)"
        text = b.text.replace("\n", " ")
        print(f"[{i}] {page}「{head}」({b.type.value})")
        print(f"    {text[:76]}{'…' if len(text) > 76 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 手验（fixture PDF，跑两条路径对比）**

```powershell
cd E:\BiShe-AIStudy\study-agent
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -c "import pymupdf; d=pymupdf.open(); p=d.new_page(); p.insert_text((72,72),'第一章 数列',fontname='china-s'); p.insert_text((72,110),'1.1 等差数列',fontname='china-s'); p.insert_text((72,150),'通项公式 an=a1+(n-1)d。',fontname='china-s'); d.save('tmp_demo.pdf'); d.close()"
.\.venv\Scripts\python.exe scripts\parse_demo.py tmp_demo.pdf
.\.venv\Scripts\python.exe scripts\parse_demo.py tmp_demo.pdf --force-pymupdf
Remove-Item tmp_demo.pdf
```

Expected: 第一次 `解析器: docling`（若装成）且层级链出现「第一章 数列 > 1.1 等差数列」；第二次 `解析器: pymupdf` 且「（无层级）」——直观体现兜底差异（spec §10.4）。

---

### Task 8: 用户验收（任务卡验收原文）

**Files:** 无新文件

- [ ] **Step 1: 向用户要 3 份真实 PDF 路径**（一份笔记、一份试卷、一份教材页；仅个人学习使用，方案附录 D 合规）
- [ ] **Step 2: 逐份跑** `.\.venv\Scripts\python.exe scripts\parse_demo.py <路径>`，把输出展示给用户
- [ ] **Step 3: 用户肉眼检查**标题层级与页码是否正确（任务卡验收标准）；每份记录 parser 与结论（预期 docling；若降级需给出真实原因）
- [ ] **Step 4: DOCX 验证**：用户有真实 Word 笔记就跑，没有就用 Task 4 fixture 演示
- [ ] **Step 5: 验收不通过项** → 修复后重跑本任务；全部通过才进 Task 9

---

### Task 9: 收尾归档（验收通过后）

**Files:**
- Modify: `backend/requirements.txt`、`docs/spec/s1-1-doc-parse.md`（§9 回填实测）、`AGENTS.md`（§9.6 锚点）、`docs/DECISIONS.md`（D-013）、`docs/PROGRESS.md`
- 删除: 其余 `backend/app/ai/*/.gitkeep`（本卡只动了 parse/，其他子目录保留）

- [ ] **Step 1: requirements.txt 钉版本**（用 Task 1 记录的实际版本）

```text
pymupdf==<Task1 实测版本>
python-docx==<Task1 实测版本>
docling==<Task1 实测版本>   # 若走降级预案：整行删除，注释 TODO 记入 PROGRESS
```

- [ ] **Step 2: 回填 spec §9 实测数字**（安装体积/耗时/首跑模型下载耗时，替换"预估"字样）
- [ ] **Step 3: AGENTS.md §9.6 锚点回填**：`ai 适配器样例：backend/app/ai/parse/pdf_docling.py（契约见 parse/base.py）`
- [ ] **Step 4: DECISIONS.md 追加 D-013**（内容要点：DoclingDocument 而非 Markdown 导出[丢页码]；PyMuPDF 兜底 heading 恒空[禁启发式]；docx page_no=None[Word 无分页]；parse_force_pymupdf 显式开关）
- [ ] **Step 5: PROGRESS.md**：S1-1 勾选 + 当前状态 + 变更日志（含验收证据摘要与降级实况）
- [ ] **Step 6: 提交**

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/ scripts/parse_demo.py docs/ .env.example
git commit -m "feat(s1-1): 文档解析为结构化文本（Docling 适配器 + PyMuPDF 降级链 + docx）"
git log --oneline -3
git status --short
```

Expected: 提交成功、工作区干净；提醒用户 `git push`

---

## Self-Review（写 plan 时已执行）

1. **Spec 覆盖**：§2 契约→Task 2；§3 架构图→Task 6；设计决策 1-6→Task 5/3/4/6 注释与实现；§5.1-5.4→Task 3/4/5；§6 错误处理→Task 6 门面；§7 测试→各 Task TDD 步骤；§8 交付物→全部任务；§9 依赖→Task 1/9；§10 验收→Task 7/8/9。无缺口。
2. **占位符扫描**：仅 Task 1 版本号与 Task 9 requirements 用 `<实测>` 占位——这是"记录实测后回填"的显式设计（数字不许编造，AGENTS §6），非 plan 失败。
3. **类型一致性**：`parse_document(path: str | Path, *, force_pymupdf: bool | None)` 在 Task 6 定义、Task 7/8 消费一致；`ParsedBlock/ParserName` 跨任务一致；`InvalidParamError(message)` 与现有签名一致（已核对 exceptions.py:82）。
