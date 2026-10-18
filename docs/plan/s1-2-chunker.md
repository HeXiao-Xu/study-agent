# S1-2 结构化切片器 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 S1-1 的 ParsedDocument 切成检索原子块——题目一题一块、笔记按标题层级、300–600 token 软目标、60-token 笔记重叠。

**Architecture:** 两阶段管道：阶段 A 把 ParsedBlock 流重组成逻辑单元（题目/笔记/公式/表格），阶段 B 做尺寸调整（>800 切分、笔记重叠）。规则解耦，各自单测。

**Tech Stack:** Python 3.11（`.venv`）、Pydantic v2、tiktoken（cl100k_base）、pytest。

**Spec:** `docs/spec/s1-2-chunker.md`（执行者两份都要读；spec §4 规则细则是本 plan 的依据）。

## Global Constraints

- 解释器 `E:\BiShe-AIStudy\study-agent\.venv\Scripts\python.exe`；pip 走华为云镜像
- 测试一律从 `backend/` 目录跑 `python -m pytest`（`-m` 才会把 cwd 加进 sys.path）
- 阶段 1 命令行阶段，不动 API.md；SCHEMA.md 本卡只加一列（Task 1，契约先行）
- 本项目惯例：整卡一个提交 `feat(s1-2)`，各任务不单独 commit
- 所有函数签名带类型标注；注释只写"为什么"
- 常量集中放模块顶部（论文对照实验的调参变量）
- AGENTS §2.1：不引入 tiktoken 之外的新依赖（tiktoken 为任务卡点名，已入 spec §7）

---

### Task 1: 契约先行（SCHEMA 加列）+ tiktoken 安装实测

**Files:**
- Modify: `docs/SCHEMA.md`（note_chunks 表加一行）
- Modify: `backend/requirements.txt`（钉版）

**Interfaces:**
- Produces: 环境里可用的 tiktoken + cl100k_base 编码缓存；SCHEMA 契约与 chunker 输出对齐

- [ ] **Step 1: SCHEMA.md note_chunks 表加 chunk_type 行**（在 `token_count` 行后插入）

```markdown
| chunk_type | TEXT | 是 | 'note' | question/note/formula（切片器判定，S4 错题诊断按 question 过滤） | — |
```

- [ ] **Step 2: 安装 tiktoken 并验证（含 BPE 下载坑探测）**

```powershell
cd E:\BiShe-AIStudy\study-agent
.\.venv\Scripts\python.exe -m pip install -i https://repo.huaweicloud.com/repository/pypi/simple tiktoken
.\.venv\Scripts\python.exe -c "import tiktoken; e=tiktoken.get_encoding('cl100k_base'); print('版本ok, \"单调递增的定义\" tokens=', len(e.encode('单调递增的定义')))"
```

Expected: 打印 tokens 数（约 6–8）。**首次调用会从 openaipublic.blob.core.windows.net 拉 ~2MB BPE 文件并缓存**；若超时（被墙），预案：浏览器手动下载 `https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken` 与 `cl100k_base.tiktoken` 放入 `%TEMP%\data-gym-cache\`（文件名前缀 `cl100k_base.`），再跑一次——实测结果记入 spec §7 回填。记下安装版本号。

- [ ] **Step 3: requirements.txt 追加**（用 Step 2 实测版本）

```text
# --- S1-2 切片（任务卡点名；cl100k_base 为 DeepSeek 无官方库时的通用近似）---
tiktoken==<Step2 实测版本>
```

---

### Task 2: Chunk 模型（TDD）

**Files:**
- Create: `backend/app/ai/rag/__init__.py`、`backend/app/ai/rag/chunker.py`
- Delete: `backend/app/ai/rag/.gitkeep`（若有）
- Test: `backend/tests/test_chunker.py`

**Interfaces:**
- Consumes: 无（纯模型）
- Produces: `ChunkType`（str Enum：question/note/formula）、`Chunk{content: str, chunk_index: int, heading_path: str = "", page_no: int | None = None, token_count: int = 0, chunk_type: ChunkType = note}`

- [ ] **Step 1: 写失败测试**（新建 `backend/tests/test_chunker.py`）

```python
"""S1-2 切片器测试（spec §5）：手工构造 ParsedDocument，零网络零模型。"""
from __future__ import annotations

from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.ai.rag.chunker import Chunk, ChunkType


def blk(text: str, page_no: int | None = 1, path: list[str] | None = None) -> ParsedBlock:
    """fixture 工厂：明显假、结构真。"""
    return ParsedBlock(text=text, page_no=page_no, heading_path=path or [])


def make_doc(blocks: list[ParsedBlock]) -> ParsedDocument:
    return ParsedDocument(source="测试样张.docx", parser="docx", blocks=blocks)


def test_chunk_defaults() -> None:
    c = Chunk(content="单调递增的定义。")
    assert c.chunk_type is ChunkType.note
    assert c.heading_path == ""
    assert c.page_no is None
    assert c.token_count == 0
    assert c.chunk_index == 0


def test_chunk_type_enum_values() -> None:
    assert {t.value for t in ChunkType} == {"question", "note", "formula"}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd E:\BiShe-AIStudy\study-agent\backend
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -m pytest tests/test_chunker.py -v
```

Expected: 2 FAIL（`No module named 'app.ai.rag'`）

- [ ] **Step 3: 实现** `backend/app/ai/rag/__init__.py`（空文件占位）与 `backend/app/ai/rag/chunker.py` 首版：

```python
"""S1-2 结构化切片器（契约：docs/spec/s1-2-chunker.md）。

RAG 检索质量的第一决定因素：题目一题一块、笔记按标题层级、
大小落在 300–600 软目标 / 800 硬上限（任务卡禁止"每 500 字硬切"）。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ChunkType(str, Enum):
    question = "question"  # 题号检测命中（S4 错题诊断按此过滤）
    note = "note"
    formula = "formula"  # 简单密度规则判定（spec §4.5，宁漏勿错）


class Chunk(BaseModel):
    content: str
    chunk_index: int = 0  # 0 起，文档内递增
    heading_path: str = ""  # "/" 连接（与 SCHEMA note_chunks 展示格式一致）
    page_no: int | None = None  # 取首块页码；docx 无分页概念
    token_count: int = 0
    chunk_type: ChunkType = ChunkType.note
```

- [ ] **Step 4: 跑测试确认通过**。Expected: `2 passed`

---

### Task 3: 题号检测（纯函数，TDD）

**Files:**
- Modify: `backend/app/ai/rag/chunker.py`
- Test: `backend/tests/test_chunker.py`（追加）

**Interfaces:**
- Produces: `is_question_start(text: str) -> bool`、`is_subquestion_start(text: str) -> bool`、`is_section_title(text: str) -> bool`

- [ ] **Step 1: 追加失败测试**

```python
def test_question_start_hits() -> None:
    from app.ai.rag.chunker import is_question_start

    # 模式全部取自真实样张（全角点/半角点/顿号/例题/第N题）
    assert is_question_start("1．下列对应关系中，能构成函数的是（　）") is True
    assert is_question_start("12．设 f(x) 是 R 上的增函数") is True
    assert is_question_start("9. 已知函数 f(x)") is True
    assert is_question_start("【例2】求定义域") is True
    assert is_question_start("例 3 证明：函数单调递增") is True
    assert is_question_start("第7题") is True


def test_question_start_misses() -> None:
    from app.ai.rag.chunker import is_question_start

    assert is_question_start("2026 年 10 月 18 日") is False  # 数字后是"年"
    assert is_question_start("（1）求 f(x) 的解析式") is False  # 小问不开题
    assert is_question_start("A．-3　B．3　C．0　D．无法确定") is False  # 选项
    assert is_question_start("二、填空题（本题共 4 小题）") is False  # 大题标题另判
    assert is_question_start("定义域优先") is False


def test_subquestion_and_section_title() -> None:
    from app.ai.rag.chunker import is_section_title, is_subquestion_start

    assert is_subquestion_start("（1）求 f(x) 的解析式") is True
    assert is_subquestion_start("(2) 当 x<0 时") is True
    assert is_subquestion_start("1．下列") is False
    assert is_section_title("一、选择题（本题共 8 小题）") is True
    assert is_section_title("三、解答题（本题共 5 小题") is True
    assert is_section_title("12．设 f(x)") is False  # 阿拉伯数字题号不是大题标题
    assert is_section_title("单调递增的定义") is False
```

- [ ] **Step 2: 跑测试确认失败**（ImportError is_question_start）

- [ ] **Step 3: 实现**（chunker.py 追加）

```python
import re

# 开题号：数字+点/顿号（全半角）、例N、第N题——样张实测模式
_QUESTION_RE = re.compile(r"^(?:\d{1,3}[.．、]|【?\s*例\s*\d{1,3}\s*】?|第\s*\d{1,3}\s*题)")
# 小问号：（N）——不新开题，是超长题的优先切分点
_SUBQUESTION_RE = re.compile(r"^[（(]\d{1,3}[)）]")
# 大题标题：中文数字+顿号——S1-1 实测试卷样张里 Docling 未把它标成 heading，必须自判
_SECTION_TITLE_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]")


def is_question_start(text: str) -> bool:
    return bool(_QUESTION_RE.match(text.strip()))


def is_subquestion_start(text: str) -> bool:
    return bool(_SUBQUESTION_RE.match(text.strip()))


def is_section_title(text: str) -> bool:
    return bool(_SECTION_TITLE_RE.match(text.strip()))
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `5 passed`

---

### Task 4: formula 密度判定（纯函数，TDD）

**Files:**
- Modify: `backend/app/ai/rag/chunker.py`
- Test: `backend/tests/test_chunker.py`（追加）

**Interfaces:**
- Produces: `is_formula_text(text: str) -> bool`

- [ ] **Step 1: 追加失败测试**

```python
def test_formula_density_hit() -> None:
    from app.ai.rag.chunker import is_formula_text

    assert is_formula_text("f(x)=2x^2-4x+1/x+sqrt(3-x)+ln(x+1)") is True
    assert is_formula_text("x1-x2<0 => f(x1)-f(x2)<0 => f(x1)<f(x2)") is True


def test_formula_density_misses() -> None:
    from app.ai.rag.chunker import is_formula_text

    # 中文多——宁漏勿错：误判成 note 无害，误判成 formula 丢语义
    assert is_formula_text("定义：区间 D 内任意 x1<x2，都有 f(x1)<f(x2)") is False
    assert is_formula_text("在 R 上单调递增，且 f(1)=0") is False
    assert is_formula_text("f(x)=2x") is False  # 长度 <10
    assert is_formula_text("A．-3　B．3　C．0　D．无法确定") is False
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**（chunker.py 追加）

```python
# 数学符号字符集（运算/关系/集合/逻辑/括号/标点）——拉丁字母不算：
# 英文单词会误伤（formula 规则要求中文≤2，单词句会全拉丁），宁漏勿错
_MATH_CHARS = set("=≠≥≤≈±−×÷·√∑∏∫∂∞∈∉∪∩⊂⊆⊃←→↔⇒⇔^_|<>{}[]()（）.,:;%°πθλσαβμ+-*/")


def is_formula_text(text: str) -> bool:
    """spec §4.5：中文≤2 且（数字+数学符号）占比≥40% 且长度≥10 → formula。"""
    t = text.strip()
    if len(t) < 10:
        return False
    cn = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    if cn > 2:
        return False
    mathish = sum(1 for ch in t if ch.isdigit() or ch in _MATH_CHARS)
    return mathish / len(t) >= 0.4
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `7 passed`

---

### Task 5: 阶段 A —— 重组为逻辑单元（TDD）

**Files:**
- Modify: `backend/app/ai/rag/chunker.py`
- Test: `backend/tests/test_chunker.py`（追加）

**Interfaces:**
- Consumes: Task 3/4 的三个判定函数
- Produces: `_Unit`（dataclass：`kind: str`、`blocks: list[ParsedBlock]`、`heading_path: list[str]`、`splittable: bool`）、`_build_units(blocks: list[ParsedBlock]) -> list[_Unit]`

- [ ] **Step 1: 追加失败测试**

```python
def test_question_unit_swallows_following_blocks() -> None:
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("1．下列对应关系中，能构成函数的是（　）"),
        blk("A．f: x→x+2　B．f: x→2x　C．f: x→x-1　D．f: x→x/2"),
        blk("2．函数 f(x) 的定义域为（　）"),
    ]
    units = _build_units(blocks)
    assert [u.kind for u in units] == ["question", "question"]
    assert len(units[0].blocks) == 2  # 题干+选项同单元


def test_section_title_ends_question_unit() -> None:
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("8．定义在 R 上的奇函数（　）"),
        blk("二、填空题（本题共 4 小题，每小题 5 分）"),
        blk("9．已知函数 f(x)"),
    ]
    units = _build_units(blocks)
    assert [u.kind for u in units] == ["question", "note", "question"]


def test_note_units_merge_by_heading() -> None:
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("定义域优先。", path=["一、概念"]),
        blk("三要素：定义域、对应关系、值域。", path=["一、概念"]),
        blk("单调性定义。", path=["一、单调性"]),
    ]
    units = _build_units(blocks)
    assert len(units) == 2
    assert len(units[0].blocks) == 2
    assert units[1].heading_path == ["一、单调性"]


def test_heading_block_leads_its_section() -> None:
    """标题块文本 == 下一块 heading_path 末元素 → 并入下一单元（S1-1 结构约定）。"""
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("二、单调性", path=["第三章"]),
        blk("定义：区间 D 内。", path=["第三章", "二、单调性"]),
    ]
    units = _build_units(blocks)
    assert len(units) == 1
    assert units[0].heading_path == ["第三章", "二、单调性"]
    assert units[0].blocks[0].text == "二、单调性"


def test_empty_dropped_table_unsplittable() -> None:
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk(""),
        blk("　　"),  # 纯空白也丢
        blk("| 方法 | 适用 |\n| --- | --- |\n| 错位相减 | 差比混合 |"),
        blk("正文跟在表格后。"),
    ]
    units = _build_units(blocks)
    assert len(units) == 2
    assert units[0].splittable is False  # 表格永不拦腰切
    assert units[0].kind == "note"
    assert units[1].splittable is True


def test_formula_block_becomes_unsplittable_unit() -> None:
    from app.ai.rag.chunker import _build_units

    units = _build_units([blk("f(x)=2x^3-3x^2+4x-1/x+sqrt(9-x^2)+log(2,x)")])
    assert units[0].kind == "formula"
    assert units[0].splittable is False


def test_heading_path_change_ends_question_unit() -> None:
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("7．函数（　）", path=["一、选择题"]),
        blk("A．y=1/x", path=["一、选择题"]),
        blk("正文进了新章节。", path=["二、填空题"]),
    ]
    units = _build_units(blocks)
    assert [u.kind for u in units] == ["question", "note"]
    assert len(units[0].blocks) == 2
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**（chunker.py 追加）

```python
from dataclasses import dataclass, field

from app.ai.parse.models import ParsedBlock


@dataclass
class _Unit:
    """阶段 A 的逻辑单元：题/小节/表格/公式。kind ∈ question|note|formula。"""

    kind: str
    blocks: list[ParsedBlock] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)
    splittable: bool = True  # False = 表格/公式，永不拦腰切


def _is_table(text: str) -> bool:
    """Markdown 表格块（S1-1 的 docling/docx 表格导出形态）。"""
    t = text.strip()
    return t.startswith("|") and "\n" in t


def _build_units(blocks: list[ParsedBlock]) -> list[_Unit]:
    units: list[_Unit] = []
    current: _Unit | None = None

    # 预处理 1：空/纯空白块直接丢（spec §4.6）
    solid = [b for b in blocks if b.text.strip()]
    # 预处理 2：标题块并入它领的小节——判定依据是 S1-1 的结构约定
    # （标题块文本 == 下一块 heading_path 末元素），不是字号启发式
    effective_path: list[list[str]] = [list(b.heading_path) for b in solid]
    for i in range(len(solid) - 1):
        nxt = solid[i + 1].heading_path
        if nxt and solid[i].text.strip() == nxt[-1]:
            effective_path[i] = list(nxt)

    for b, path in zip(solid, effective_path):
        text = b.text.strip()
        if _is_table(text):
            units.append(_Unit(kind="note", blocks=[b], heading_path=path, splittable=False))
            current = None
            continue
        if is_formula_text(text):
            units.append(_Unit(kind="formula", blocks=[b], heading_path=path, splittable=False))
            current = None
            continue
        if is_question_start(text):
            current = _Unit(kind="question", blocks=[b], heading_path=path)
            units.append(current)
            continue
        if is_section_title(text):
            current = _Unit(kind="note", blocks=[b], heading_path=path)
            units.append(current)
            continue
        # 普通块：并入当前单元（题目吞并选项/解析；笔记合并同节）；否则新开笔记单元
        if current is not None and current.heading_path == path and current.splittable:
            current.blocks.append(b)
        else:
            current = _Unit(kind="note", blocks=[b], heading_path=path)
            units.append(current)
    return units
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `14 passed`

---

### Task 6: 阶段 B —— 尺寸调整与重叠（TDD）

**Files:**
- Modify: `backend/app/ai/rag/chunker.py`
- Test: `backend/tests/test_chunker.py`（追加）

**Interfaces:**
- Consumes: `_Unit`、tiktoken
- Produces: `_count_tokens(text: str) -> int`、`_overlap_prefix(prev_text: str) -> str`、`_split_unit(unit: _Unit) -> list[_Piece]`；`_Piece`（dataclass：`text: str`、`page_no: int | None`）

- [ ] **Step 1: 追加失败测试**

```python
def test_count_tokens_uses_tiktoken() -> None:
    import tiktoken

    from app.ai.rag.chunker import _count_tokens

    enc = tiktoken.get_encoding("cl100k_base")
    text = "错位相减法适用于差比混合型数列的求和，需通项非零。"
    assert _count_tokens(text) == len(enc.encode(text))  # 与 tiktoken 直算一致，不是字符数


def test_overlap_prefix_sentence_aligned_and_capped() -> None:
    from app.ai.rag.chunker import _overlap_prefix

    text = "句子一的内容。句子二的内容。句子三的内容。"
    prefix = _overlap_prefix(text)
    assert prefix.startswith("句子") and prefix.endswith("。")
    assert _count_tokens(prefix) <= 60  # spec §4.3：≤60 token
    assert "句子一" not in prefix or _count_tokens(prefix) < 60  # 从尾部取，短文才会全带


def test_note_unit_over_800_splits_with_overlap() -> None:
    from app.ai.rag.chunker import _build_units, _count_tokens, _split_unit

    # 每块 ~20 token，40 块 ≈ 800+，必须切
    blocks = [blk(f"判定方法之{i}：作差法判断单调性，注意定义域限制。") for i in range(40)]
    units = _build_units(blocks)
    pieces = _split_unit(units[0])
    assert len(pieces) >= 2
    assert all(_count_tokens(p.text) <= 800 for p in pieces)  # 硬上限
    # 笔记块间重叠：第二块的第一行必须是第一块文本的尾部后缀（句子对齐）
    first_line = pieces[1].text.split("\n", 1)[0]
    assert first_line and pieces[0].text.endswith(first_line)
    assert _count_tokens(first_line) <= 60


def test_question_unit_splits_without_overlap() -> None:
    from app.ai.rag.chunker import _build_units, _count_tokens, _split_unit

    # 题干 + 大量同路径后续块 → 超限切分；题目块不带重叠
    blocks = [blk("1．解答题：证明下列各题。")] + [
        blk(f"证明过程第{i}步，利用定义作差并化简整理。") for i in range(40)
    ]
    units = _build_units(blocks)
    assert units[0].kind == "question"
    pieces = _split_unit(units[0])
    assert len(pieces) >= 2
    assert all(_count_tokens(p.text) <= 800 for p in pieces)
    first_line = pieces[1].text.split("\n", 1)[0]
    assert not pieces[0].text.endswith(first_line)  # 无重叠：不是上一块的后缀


def test_unsplittable_unit_stays_whole() -> None:
    from app.ai.rag.chunker import _build_units, _split_unit

    row = "| 列一 | 列二 |\n| --- | --- |" + "\n| 数据内容比较长的一些填充文字 | 另一列数据 |" * 30
    blocks = [blk(row)]
    units = _build_units(blocks)
    assert units[0].splittable is False
    pieces = _split_unit(units[0])
    assert len(pieces) == 1  # 表格超长也整块保留


def test_small_unit_stays_whole_under_300() -> None:
    from app.ai.rag.chunker import _build_units, _split_unit

    blocks = [blk("小节标题内的一小段话。")]  # <300 token，不硬凑
    units = _build_units(blocks)
    assert len(_split_unit(units[0])) == 1


def test_oversized_single_block_sentence_split() -> None:
    from app.ai.rag.chunker import _build_units, _count_tokens, _split_unit

    # 单块超 800（无块边界可切）→ 按句边界切
    long_text = "判断函数单调性的基本方法。".replace("。", "。") * 120  # 每句 ~9 token，共 >800
    blocks = [blk(long_text)]
    units = _build_units(blocks)
    pieces = _split_unit(units[0])
    assert len(pieces) >= 2
    assert all(_count_tokens(p.text) <= 800 for p in pieces)
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**（chunker.py 追加；模块顶部常量区一并落）

```python
import tiktoken

# ---- 可调参数（论文对照实验的变量，集中一处）----
TARGET_MIN_TOKENS = 300   # 软目标下限：块越过 300 后在下一个边界切（块最终落 300–800）
HARD_MAX_TOKENS = 800     # 硬上限：超过必切（题目块同限）
NOTE_OVERLAP_TOKENS = 60  # 笔记块重叠；题目块不重叠（题与题天然独立）
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")

_encoding: tiktoken.Encoding | None = None


def _count_tokens(text: str) -> int:
    """cl100k_base 近似计数（DeepSeek 无公开 tokenizer；预算用途误差可接受）。"""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return len(_encoding.encode(text))


@dataclass
class _Piece:
    """阶段 B 的产物：一段成品文本 + 它起始页码。"""

    text: str
    page_no: int | None


def _overlap_prefix(prev_text: str) -> str:
    """取上一块尾部句子（累计 ≤60 token）作为下一块开头——防止知识点恰在边界断开。"""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(prev_text) if s.strip()]
    picked: list[str] = []
    total = 0
    for s in reversed(sentences):
        n = _count_tokens(s)
        if total + n > NOTE_OVERLAP_TOKENS:
            break  # 单句就超 60 也不带：宁缺勿碎
        picked.insert(0, s)
        total += n
    return "".join(picked)


def _split_by_boundary(texts: list[str], pages: list[int | None]) -> list[_Piece]:
    """贪心装包：越过软目标下限后在下一边界切；加下一块会超硬上限则先切。"""
    pieces: list[_Piece] = []
    buf: list[str] = []
    buf_tokens = 0
    buf_page: int | None = pages[0] if pages else None
    for text, page in zip(texts, pages):
        n = _count_tokens(text)
        if buf and (buf_tokens >= TARGET_MIN_TOKENS or buf_tokens + n > HARD_MAX_TOKENS):
            pieces.append(_Piece("\n".join(buf), buf_page))
            buf, buf_tokens, buf_page = [], 0, page
        buf.append(text)
        buf_tokens += n
    if buf:
        pieces.append(_Piece("\n".join(buf), buf_page))
    return pieces


def _split_long_text(text: str, page_no: int | None) -> list[_Piece]:
    """单块超 HARD_MAX 时按句边界切（块边界无路可走的兜底）。"""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return [_Piece(text, page_no)]  # 一整句超长：不切（拦腰切毁语义）
    return _split_by_boundary(sentences, [page_no] * len(sentences))


def _split_unit(unit: _Unit) -> list[_Piece]:
    if not unit.blocks:
        return []
    texts = [b.text.strip() for b in unit.blocks]
    pages = [b.page_no for b in unit.blocks]
    total = sum(_count_tokens(t) for t in texts)
    if not unit.splittable or total <= HARD_MAX_TOKENS:
        return [_Piece("\n".join(texts), pages[0])]

    # 先展开"单块本身超限"的块（按句切），再统一贪心装包
    expanded: list[tuple[str, int | None]] = []
    for text, page in zip(texts, pages):
        if _count_tokens(text) > HARD_MAX_TOKENS:
            expanded.extend((p.text, page) for p in _split_long_text(text, page))
        else:
            expanded.append((text, page))
    pieces = _split_by_boundary([t for t, _ in expanded], [p for _, p in expanded])

    if unit.kind != "note":
        return pieces  # 题目块不重叠
    # 笔记块：每块头部接上一块尾部 ≤60 token 的句子
    overlapped: list[_Piece] = []
    for i, p in enumerate(pieces):
        if i == 0:
            overlapped.append(p)
            continue
        prefix = _overlap_prefix(overlapped[-1].text)
        overlapped.append(_Piece((prefix + "\n" + p.text) if prefix else p.text, p.page_no))
    return overlapped
```

- [ ] **Step 4: 跑测试确认通过**。Expected: 累计 `21 passed`（如有失败，优先检查 `_split_unit` 与测试断言的边界语义，不许改断言迁就实现）

---

### Task 7: 门面 chunk_document + 端到端（TDD）

**Files:**
- Modify: `backend/app/ai/rag/chunker.py`
- Test: `backend/tests/test_chunker.py`（追加）

**Interfaces:**
- Consumes: `_build_units`、`_split_unit`、`Chunk`
- Produces: `chunk_document(doc: ParsedDocument) -> list[Chunk]`（全项目唯一切片入口）

- [ ] **Step 1: 追加失败测试**

```python
def test_chunk_document_end_to_end() -> None:
    from app.ai.rag.chunker import chunk_document

    doc = make_doc(
        [
            blk("一、函数的概念", path=["数学笔记"]),
            blk("设 A、B 是非空数集。", path=["数学笔记", "一、函数的概念"], page_no=1),
            blk("三要素：定义域、对应关系、值域。", path=["数学笔记", "一、函数的概念"], page_no=2),
            blk("2．函数 f(x) 的定义域为（　）", path=["数学笔记", "一、函数的概念"], page_no=2),
            blk("A．[-1,3]　B．(-1,3]", path=["数学笔记", "一、函数的概念"], page_no=2),
        ]
    )
    chunks = chunk_document(doc)
    # 标题并入小节 → 2 个 note 块 + 1 个 question 块
    assert [c.chunk_type.value for c in chunks] == ["note", "note", "question"]
    assert chunks[0].heading_path == "数学笔记/一、函数的概念"
    assert chunks[0].page_no == 1  # 首块页码
    assert chunks[1].page_no == 2
    assert [c.chunk_index for c in chunks] == [0, 1, 2]  # 递增
    assert chunks[2].token_count > 0  # tiktoken 实测
    assert "A．[-1,3]" in chunks[2].content  # 选项与题干同块


def test_chunk_document_empty_and_scanned() -> None:
    from app.ai.rag.chunker import chunk_document

    assert chunk_document(make_doc([])) == []
    scanned = ParsedDocument(source="scan.pdf", parser="pymupdf", is_scanned=True, blocks=[])
    assert chunk_document(scanned) == []  # 扫描版不抛异常（spec §4.6）
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**（chunker.py 追加）

```python
from app.ai.parse.models import ParsedDocument

_HEADING_JOIN = "/"  # SCHEMA note_chunks 展示格式（如"函数/单调性/例题2"）


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    """ParsedDocument → 检索原子块。空文档（含扫描版）返回 []，不抛异常。"""
    chunks: list[Chunk] = []
    for unit in _build_units(doc.blocks):
        for piece in _split_unit(unit):
            text = piece.text.strip()
            if not text:
                continue
            chunks.append(
                Chunk(
                    content=text,
                    chunk_index=len(chunks),
                    heading_path=_HEADING_JOIN.join(unit.heading_path),
                    page_no=piece.page_no,
                    token_count=_count_tokens(text),
                    chunk_type=ChunkType(unit.kind),
                )
            )
    return chunks
```

- [ ] **Step 4: 跑全量测试**（含 S1-1 的 20 条）

Expected: `23 passed`

---

### Task 8: scripts/chunk_demo.py（演示 + 直方图）

**Files:**
- Create: `scripts/chunk_demo.py`

**Interfaces:**
- Consumes: `parse_document`（S1-1）、`chunk_document`

- [ ] **Step 1: 实现**

```python
"""S1-2 演示：解析→切片→逐块摘要 + token 分布直方图（任务卡验收）。

用法（仓库根目录）：
    python scripts/chunk_demo.py <文件> [--limit 30] [--force-pymupdf]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ai.parse import parse_document  # noqa: E402
from app.ai.rag.chunker import chunk_document  # noqa: E402


def histogram(tokens: list[int]) -> str:
    buckets = [(0, 100), (101, 200), (201, 300), (301, 400), (401, 500),
               (501, 600), (601, 700), (701, 800), (801, 10**9)]
    lines = []
    for lo, hi in buckets:
        n = sum(1 for t in tokens if lo <= t <= hi)
        bar = "█" * min(n, 40)
        label = f">{hi}" if hi == 10**9 else f"{lo}-{hi}"
        lines.append(f"{label:>8} | {bar} {n}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化切片演示（S1-2）")
    parser.add_argument("file", help="PDF/DOCX 文件路径")
    parser.add_argument("--limit", type=int, default=30, help="打印前 N 块（默认 30）")
    parser.add_argument("--force-pymupdf", action="store_true", help="解析走快速路径")
    args = parser.parse_args()

    doc = parse_document(args.file, force_pymupdf=args.force_pymupdf)
    chunks = chunk_document(doc)
    questions = [c for c in chunks if c.chunk_type.value == "question"]
    print(f"文件: {doc.source}    解析器: {doc.parser}    块数: {len(chunks)}（question {len(questions)}）")
    print("-" * 72)
    for c in chunks[: args.limit]:
        print(f"[{c.chunk_index}] ({c.chunk_type.value}) {c.token_count}t p.{c.page_no}「{c.heading_path}」")
        text = c.content.replace("\n", " ")
        print(f"    {text[:70]}{'…' if len(text) > 70 else ''}")
    print("-" * 72)
    print("token 分布直方图：")
    print(histogram([c.token_count for c in chunks]))
    if chunks:
        avg = sum(c.token_count for c in chunks) / len(chunks)
        print(f"均值 {avg:.0f} token / 块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 手验（试卷样张，Docling 路径）**

```powershell
cd E:\BiShe-AIStudy\study-agent
$env:HF_ENDPOINT='https://hf-mirror.com'; $env:HF_HUB_DISABLE_XET='1'
.\.venv\Scripts\python.exe scripts\chunk_demo.py "E:\BiShe-AIStudy\测试数据\高中数学试卷-函数单元测试.pdf"
```

Expected: question 块数 ≈ 17（一题一块；超 800 的题会有续块）；直方图主体落在 101–400；无 >800 桶。若题目块数远偏，回查 `_build_units` 的题号边界。

---

### Task 9: 用户验收（任务卡原文：必须亲眼看切片结果）

- [ ] Step 1: 给用户看 Task 8 输出（题目块数、直方图、逐块摘要）
- [ ] Step 2: 用户核对：题目一题一块不拦腰（抽查 2-3 题原文对照）、笔记/教材层级正确
- [ ] Step 3: 不通过 → 修复重跑；通过 → 进 Task 10

---

### Task 10: 收尾归档 + 提交

**Files:**
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-015）、`docs/spec/s1-2-chunker.md`（tiktoken 实测回填 §7）

- [ ] Step 1: spec §7 回填 tiktoken 实测（版本号、BPE 下载是否顺畅、坑与解法）
- [ ] Step 2: DECISIONS D-015（两阶段管道 / 软硬目标 300-600-800 / formula 密度规则 / 大题标题自判 / heading 前置并入 / 60-token 重叠仅笔记）
- [ ] Step 3: PROGRESS：S1-2 勾选 + 当前状态 + 变更日志（验收证据摘要）
- [ ] Step 4: 提交

```powershell
cd E:\BiShe-AIStudy\study-agent
git add backend/app/ai/rag backend/tests/test_chunker.py backend/requirements.txt scripts/chunk_demo.py docs/SCHEMA.md docs/spec/s1-2-chunker.md docs/plan/s1-2-chunker.md docs/DECISIONS.md docs/PROGRESS.md
git commit -m "feat(s1-2): 结构化切片器——题目一题一块、笔记按标题、300-600 软目标与 60-token 重叠"
git log --oneline -3 && git status --short
```

---

## Self-Review（写 plan 时已执行）

1. **Spec 覆盖**：§2 契约→T2/T7；§3 架构→T5/T6/T7；§4.1 题号→T3/T5；§4.2 标题切+前置并入→T5；§4.3 尺寸/重叠→T6；§4.4 tiktoken→T1/T6；§4.5 formula→T4/T5；§4.6 边界→T5/T6/T7；§5 测试→各任务（21+ 条 ≥ 14）；§6 交付物→T8/T10；§8 验收→T8/T9/T10；§7 契约变更→T1。无缺口。
2. **占位符扫描**：仅 `<Step2 实测版本>` 一处——tiktoken 版本号实测回填（AGENTS §6 禁编造），非 plan 失败。
3. **类型一致性**：`chunk_document(doc: ParsedDocument) -> list[Chunk]` 在 T7 定义、T8 消费一致；`_Unit/_Piece/_build_units/_split_unit` 跨任务签名一致；`ChunkType(unit.kind)` 要求 kind ∈ 三值——T5 的单元 kind 只产 question/note/formula ✓。
