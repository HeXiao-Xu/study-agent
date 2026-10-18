"""S1-2 结构化切片器（契约：docs/spec/s1-2-chunker.md）。

RAG 检索质量的第一决定因素：题目一题一块、笔记按标题层级、
大小落在 300–600 软目标 / 800 硬上限（任务卡禁止"每 500 字硬切"）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

import tiktoken
from pydantic import BaseModel

from app.ai.parse.models import ParsedBlock, ParsedDocument

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


# 开题号：数字+点/顿号（全半角）、例N、第N题——样张实测模式；
# (?!\d) 保护章节号：教材"3.2.1 函数的单调性"、"1.5 倍"不能当题号（实测误伤）
_QUESTION_RE = re.compile(r"^(?:\d{1,3}[.．、](?!\d)|【?\s*例\s*\d{1,3}\s*】?|第\s*\d{1,3}\s*题)")
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


# 数学符号字符集（运算/关系/集合/逻辑/括号/标点）——拉丁字母不算：
# 英文单词会误伤（formula 规则要求中文≤2，单词句会全拉丁），宁漏勿错
_MATH_CHARS = set("=≠≥≤≈±−×÷·√∑∏∫∂∞∈∉∪∩⊂⊆⊃←→↔⇒⇔^_|<>{}[]()（）.,:;%°πθλσαβμ+-*/")
# 选项行（A-D + 分隔符）：实测密度规则会误伤纯数值选项——选项是题目组件，归 question
_OPTION_LINE_RE = re.compile(r"^\s*[A-DＡ-Ｄ][.．、]")


def is_formula_text(text: str) -> bool:
    """spec §4.5：中文≤2 且（数字+数学符号）占比≥40% 且长度≥10 → formula。

    以下行豁免（实测密度规则会误伤题目组件）：
    - 选项行（A．… B．…）：零中文+符号密集，但必须留在所属题目单元里
    - 小问行（（1）…（2）…）：同上
    """
    t = text.strip()
    if len(t) < 10:
        return False
    if _OPTION_LINE_RE.match(t) or _SUBQUESTION_RE.match(t):
        return False
    cn = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    if cn > 2:
        return False
    mathish = sum(1 for ch in t if ch.isdigit() or ch in _MATH_CHARS)
    return mathish / len(t) >= 0.4


# ---- 阶段 A：重组为逻辑单元 ----


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


_HEADING_JOIN = "/"  # SCHEMA note_chunks 展示格式（如"函数/单调性/例题2"）
# 纯答题线（下划线/横线/空白混合）：实测样张的填空作答区占位，零检索语义，丢弃
_FILL_LINE_RE = re.compile(r"^[_\s—－–-]{4,}$")


def _build_units(blocks: list[ParsedBlock]) -> list[_Unit]:
    units: list[_Unit] = []
    current: _Unit | None = None

    # 预处理 1：空/纯空白/纯答题线块直接丢（spec §4.6；答题线实测会假命中 formula）
    solid = [b for b in blocks if b.text.strip() and not _FILL_LINE_RE.match(b.text.strip())]
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


# ---- 阶段 B：尺寸调整与重叠 ----


@dataclass
class _Piece:
    """阶段 B 的产物：一段成品文本 + 它起始页码。"""

    text: str
    page_no: int | None


def _overlap_prefix(prev_text: str) -> str:
    """取上一块尾部（累计 ≤60 token）作为下一块开头——防止知识点恰在边界断开。

    必须返回原文的精确后缀（句子对齐）：lookbehind split 不消耗字符，
    按起点切片即可保真，不能用 join 重拼（会丢块间换行）。
    """
    parts = _SENTENCE_SPLIT_RE.split(prev_text)
    consumed = 0  # 从尾部累计的字符数（含空白部分，否则切片起点会晚）
    total_tokens = 0
    for s in reversed(parts):
        if not s.strip():
            consumed += len(s)  # 块间换行等：在后缀跨度内，但不计 token
            continue
        n = _count_tokens(s)
        if total_tokens + n > NOTE_OVERLAP_TOKENS:
            break  # 单句就超 60 也不带：宁缺勿碎
        total_tokens += n
        consumed += len(s)
    if total_tokens == 0:
        return ""  # 一个实句都没带上（尾部只有空白或超长单句）
    return prev_text[len(prev_text) - consumed :]


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


# ---- 门面 ----

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
