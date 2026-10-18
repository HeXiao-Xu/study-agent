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


# ---- Task 3：题号 / 小问号 / 大题标题检测 ----


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
    assert is_question_start("3.2.1 函数的单调性 我们在初中已经…") is False  # 章节号不是题号
    assert is_question_start("1.5 倍增长") is False  # 小数不是题号
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


# ---- Task 4：formula 密度判定 ----


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
    # 选项行豁免：纯数值选项零中文+符号密集，但选项必须归题目（实测驱动）
    assert is_formula_text("A．[-1,3]　B．(-1,3]　C．[-3,1]　D．(-3,1)") is False


# ---- Task 5：阶段 A 重组为逻辑单元 ----


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


def test_fill_lines_dropped_and_question_kept_whole() -> None:
    """答题线（实测样张的填空占位）零语义且会假命中 formula——丢弃且不拆题。"""
    from app.ai.rag.chunker import _build_units

    blocks = [
        blk("13．（15 分）求下列函数的定义域："),
        blk("______________________________________"),
        blk("（1）f(x)=1/(x^2-4)；"),
        blk("__________ __________"),
        blk("14．（18 分）用定义证明：函数单调递增。"),
    ]
    units = _build_units(blocks)
    assert [u.kind for u in units] == ["question", "question"]
    assert len(units[0].blocks) == 2  # 题干+小问；答题线被丢
    assert all("____" not in b.text for u in units for b in u.blocks)


# ---- Task 6：阶段 B 尺寸调整与重叠 ----


def test_count_tokens_uses_tiktoken() -> None:
    import tiktoken

    from app.ai.rag.chunker import _count_tokens

    enc = tiktoken.get_encoding("cl100k_base")
    text = "错位相减法适用于差比混合型数列的求和，需通项非零。"
    assert _count_tokens(text) == len(enc.encode(text))  # 与 tiktoken 直算一致，不是字符数


def test_overlap_prefix_sentence_aligned_and_capped() -> None:
    from app.ai.rag.chunker import _count_tokens, _overlap_prefix

    text = "句子一的内容。句子二的内容。句子三的内容。"
    prefix = _overlap_prefix(text)
    assert prefix.startswith("句子") and prefix.endswith("。")
    assert _count_tokens(prefix) <= 60  # spec §4.3：≤60 token
    assert text.endswith(prefix)  # 必是原文尾部后缀（句子对齐）


def _last_sentence(text: str) -> str:
    """取文本最后一个完整句子（测试辅助：断言重叠用）。"""
    stripped = text.rstrip()
    cut = stripped.rfind("。", 0, len(stripped) - 1) + 1  # 倒数第二个句号之后
    return stripped[cut:].strip()


def test_note_unit_over_800_splits_with_overlap() -> None:
    from app.ai.rag.chunker import _build_units, _count_tokens, _split_unit

    # 每块 ~20 token，40 块 ≈ 800+，必须切
    blocks = [blk(f"判定方法之{i}：作差法判断单调性，注意定义域限制。") for i in range(40)]
    units = _build_units(blocks)
    pieces = _split_unit(units[0])
    assert len(pieces) >= 2
    assert all(_count_tokens(p.text) <= 800 for p in pieces)  # 硬上限
    # 笔记块间重叠：重叠段（含最后一句）= 上一块的尾部后缀，≤60 token
    last = _last_sentence(pieces[0].text)
    assert last in pieces[1].text
    head = pieces[1].text[: pieces[1].text.find(last) + len(last)]
    assert pieces[0].text.endswith(head)
    assert _count_tokens(head) <= 60


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
    # 无重叠：上一块的最后一句不在下一块里
    assert _last_sentence(pieces[0].text) not in pieces[1].text


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
    long_text = "判断函数单调性的基本方法。" * 120  # 每句 ~9 token，共 >800
    blocks = [blk(long_text)]
    units = _build_units(blocks)
    pieces = _split_unit(units[0])
    assert len(pieces) >= 2
    assert all(_count_tokens(p.text) <= 800 for p in pieces)


# ---- Task 7：门面 chunk_document + 端到端 ----


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
    # 标题并入小节且同节正文合并 → 1 个 note 块；题号开新块且吞并选项
    assert [c.chunk_type.value for c in chunks] == ["note", "question"]
    assert chunks[0].heading_path == "数学笔记/一、函数的概念"
    assert chunks[0].page_no == 1  # 首块页码
    assert "设 A、B 是非空数集。" in chunks[0].content  # 同节正文与标题合并
    assert [c.chunk_index for c in chunks] == [0, 1]  # 递增
    assert chunks[1].token_count > 0  # tiktoken 实测
    assert "A．[-1,3]" in chunks[1].content  # 选项与题干同块（formula 不截胡）


def test_chunk_document_empty_and_scanned() -> None:
    from app.ai.rag.chunker import chunk_document

    assert chunk_document(make_doc([])) == []
    scanned = ParsedDocument(source="scan.pdf", parser="pymupdf", is_scanned=True, blocks=[])
    assert chunk_document(scanned) == []  # 扫描版不抛异常（spec §4.6）
