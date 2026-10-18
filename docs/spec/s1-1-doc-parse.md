# S1-1 文档解析为结构化文本 — 设计 Spec

> 状态：**待用户评审** ｜ 任务卡：docs/AI协作开发实施计划.md S1-1 ｜ 撰写：2026-10-18
> 本卡为 AGENTS.md §10 生效后首个走 spec→plan 全流程的功能卡。阶段 1 代码只在命令行跑，不接 Web。

## 1. 目标与非目标

**目标**：输入本地文件路径（PDF / DOCX），输出带页码与标题层级的统一结构化文本，
供 S1-2 切片器消费。

**非目标（明确不做）**：
- 图片/扫描件 OCR（下一任务，走多模态 API）——本卡只**检测**出扫描版并提示
- 切片、向量化、入库（S1-2 / S1-3）
- Web 接口与异步任务（S2）；`docs/API.md` 本卡不动
- 手写"按字号/加粗猜标题"启发式（任务卡红线；理由：不稳，Docling 的版面模型才是干这个的）

## 2. 输出契约（数据结构）

`backend/app/ai/parse/models.py`（Pydantic v2，AGENTS §4"所有出入参用 Pydantic"）：

```python
class BlockType(str, Enum):
    text = "text"
    formula = "formula"
    question = "question"   # 枚举保留，但由 S1-2 切片器填充（见设计决策 3）

class ParsedBlock(BaseModel):
    text: str                      # 块文本；表格转 Markdown 塞入
    page_no: int | None            # 1-based；None 仅出现在 docx（见设计决策 4）
    heading_path: list[str] = []   # 标题层级链，抽不到就空列表，禁止编造
    type: BlockType = BlockType.text

class ParsedDocument(BaseModel):
    source: str                    # 输入文件路径（原样）
    parser: Literal["docling", "pymupdf", "docx"]   # 实际使用的解析器
    is_scanned: bool = False       # 扫描版检测（见 §5.1）
    degraded_reason: str | None = None  # 降级原因（仅 docling→pymupdf 时非空）
    blocks: list[ParsedBlock]      # 任务卡要求的统一结构就是这个列表
```

任务卡原文的 `[{text, page_no, heading_path, type}]` = `ParsedDocument.blocks`；
外层信封（parser/is_scanned/degraded_reason）是审计信息，供切片与日志使用。

## 3. 架构：适配器与降级链

```
parse_document(path)                      # __init__.py 唯一入口（门面）
  ├─ .pdf → ① PyMuPDF 快速采样判断 is_scanned
  │          ├─ is_scanned=True → 直接返回（空 blocks + 标记 + 提示语）
  │          ├─ 否则 ② Docling 适配器解析
  │          │     ├─ 未安装(import 失败)/解析抛错 → 打 WARNING 日志（含原因）
  │          │     │    → ③ PyMuPDF 兜底解析（degraded_reason 记原因）
  │          └─ 配置 parse_force_pymupdf=True → 跳过 ② 直接 ③（快速路径）
  └─ .docx → ④ python-docx 适配器
  其他扩展名 → InvalidParamError（S0-5 异常体系）
```

`base.py` 定义可替换适配器契约（任务卡要求 5 的"抽象接口"）：

```python
class DocumentParser(ABC):
    name: ClassVar[str]                      # "docling" | "pymupdf" | "docx"
    def supports(self, path: Path) -> bool   # 按扩展名
    def parse(self, path: Path) -> ParsedDocument
```

文件布局：`parse/{__init__.py, models.py, base.py, pdf_docling.py, pdf_pymupdf.py, docx_parser.py}`。

## 4. 关键设计决策

1. **消费 Docling 的结构化文档对象，而非它导出的 Markdown**
   任务卡说"得到带标题层级的表格的 Markdown 再转换"，但统一结构需要**每段的 page_no**，
   Markdown 序列化会丢页码。Docling 的 DoclingDocument 本身就是带 label/prov（页码）
   的结构化数据，Markdown 只是它的一种导出。取同一数据的上游，不违背任务卡意图。
   → **实现时需对照实际安装的 docling 版本验证 API**，偏差记入实现日志。
2. **PyMuPDF 兜底路径 heading_path 一律空列表**
   用字号/加粗猜标题正是任务卡禁止的启发式；兜底路径诚实降级：
   有页码、有文本、无层级（不瞎编）。Docx 的 Heading 样式是文档里真实存在的
   结构信息，所以 docx 路径可以给出层级——两者依据不同。
3. **type 字段：有依据才标**
   - `formula`：仅当解析器显式给出公式标注（Docling 启用公式识别时）才填
   - `question`：S1-1 不填（题号模式检测是 S1-2 切片器的职责，那里有上下文），
     枚举值保留占位，避免 S1-2 改契约
   - 其余全部 `text`（表格转 Markdown 后也是 text）
4. **docx 的 page_no = None**：Word 的分页由渲染器决定、文件里不存在；
   硬编一个假页码违反"不瞎编"。切片器与前端需容忍 None。
   （与任务卡 `page_no: int` 的偏差，理由如上，此处留痕。）
5. **页码统一 1-based**：与人类阅读习惯一致（试卷引用页码对人有意义）。
6. **"简单纯文本快速路径"用显式开关而非自动猜测**：判断"是否简单 PDF"的
   廉价信号本身就要靠字体统计（被禁止的启发式）。默认全部走 Docling（质量优先，
   CLI 阶段可接受慢）；`parse_force_pymupdf`（Settings/env）提供快速路径开关，
   测试与无 docling 环境也靠它。已知代价：大 PDF 全走 Docling 偏慢，S2 接入
   异步任务前再优化。

## 5. 各解析器行为细则

### 5.1 is_scanned 检测（PDF 门面步骤，任务卡坑①）
用 PyMuPDF 取前 10 页（不足取全部）文本字符数，**多数页 < 50 字符**判定扫描版：
返回 `ParsedDocument(is_scanned=True, blocks=[], parser="pymupdf")`，
degraded_reason 写明"扫描版 PDF，请走图片识别（下一任务）"。**不做 OCR**。
（先判断再决定——扫描版不浪费 Docling 算力。）

### 5.2 Docling 适配器（pdf_docling.py）
- `DocumentConverter().convert(path).document` → 遍历文本项与表格：
  - `title` / `section_header(level)` → 维护标题栈，后续块带 `heading_path`
  - `paragraph` / `list_item` / `caption` → text 块
  - 表格 → `export_to_markdown()` 塞入一个 text 块
  - `page_header` / `page_footer` → 丢弃（页眉页脚是噪声）
  - 页眉标题栈在**换页时不清空**（文档级层级跨页延续）
- 项的 `prov` 取 `page_no`（1-based 直接对齐）
- 公式项存在且被标注 → type=formula；未启用/没有 → 全 text（决策 3）
- 适配器内部不 catch 异常，由门面统一降级（见 §6）

### 5.3 PyMuPDF 兜底（pdf_pymupdf.py）
- 逐页 `get_text("text")`，按空行分段，每段一个块
- `heading_path=[]`（决策 2）、`type=text`、page_no=页号+1（转 1-based）
- 空页跳过；页内无文本但 is_scanned=False（混合型文档）→ 该页产出 0 块，不报错

### 5.4 docx 适配器（docx_parser.py）
- `python-docx` 的 `iter_inner_content()` 按文档顺序遍历段落与表格
  （普通 `document.paragraphs` 会丢表格位置，不可用）
- 样式名 `Heading N` / `中文 Word 的"标题 N"` → 层级 N，维护标题栈
- 表格 → 简单 Markdown 表格块；`page_no=None`（决策 4）
- 图片/公式对象：跳过并 log 数量（图片识别是下一任务）

## 6. 错误处理与日志

- 门面 catch Docling 的 ImportError 与运行异常 → `logger.warning("降级到 PyMuPDF",
  原因=…, 文件=…, trace_id=…)`（AGENTS §4：异常带上下文）→ 走兜底，
  `degraded_reason` 记录给下游与 demo 展示
- 文件不存在 / 不支持的扩展名 → `InvalidParamError`（core/exceptions 体系，§9.2）
- PyMuPDF/docx 自身异常不吞：直接上抛（它们的失败没有降级路径）
- 结构化日志走 S0-5 的 JSON 行格式，trace_id 自动注入

## 7. 测试策略（backend/tests/test_parse.py）

自造 fixture（明显假、结构真，AGENTS §9.4；**零网络零模型下载**）：
- **PyMuPDF 生成** 3 页小 PDF（纯文本段落）→ 测兜底路径：块数/页码 1-based/空
  heading_path/is_scanned=False
- **PyMuPDF 生成** 空白页 PDF → is_scanned=True + 空块 + 提示语
- **python-docx 生成** 含"标题1/标题2+正文+表格"的 docx → heading_path 正确、
  表格成块、page_no=None
- **Docling 适配器 mock**（monkeypatch DocumentConverter，喂构造的假 document
  对象）→ 测 label→type/heading 栈/prov 页码映射
- **降级链**：模拟 docling import 失败 → 自动落到 pymupdf，parser=="pymupdf"
  且 degraded_reason 非空
- 门面：`.xyz` 扩展名 → InvalidParamError

## 8. 交付物清单

| 文件 | 内容 |
|---|---|
| `backend/app/ai/parse/{__init__,models,base,pdf_docling,pdf_pymupdf,docx_parser}.py` | 模块本体 |
| `scripts/parse_demo.py` | CLI：`python scripts/parse_demo.py <文件> [--limit N=50] [--force-pymupdf]`，打印 parser/is_scanned/降级原因/块总数 + 前 N 段（页码+层级+类型+80 字预览） |
| `backend/tests/test_parse.py` | §7 的测试 |
| `backend/requirements.txt` + 根 `.env.example` | +pymupdf/python-docx/docling（视安装结果，见 §9）；+PARSE_FORCE_PYMUPDF |
| 删除 parse/ 等子目录的 .gitkeep | 有真实文件后清掉 |

## 9. 依赖与安装实测（2026-10-18 本机数字，全部实测）

| 依赖 | 用途 | 实测 | 耗时（实测） |
|---|---|---|---|
| docling 2.140.0 | PDF 版面模型（标题层级/表格/页码） | 含传递依赖（torch CPU 等），装完后 site-packages 总量 1404MB（含 S0 基础包） | 华为云源后台安装约 15 分钟 |
| docling 模型（docling-project/docling-models） | 首跑下载进 HF 缓存 | 342MB | 首跑 466.2s（含模型下载与推理），之后离线可跑 |
| pymupdf 1.28.2 | 兜底 + is_scanned 采样 + fixture 生成 | 小（MB 级） | 秒级 |
| python-docx 1.2.0 | Word 解析 + fixture 生成 | 小（MB 级） | 秒级 |

**模型下载坑与解法（换机复用，已记 README FAQ）**：HuggingFace 直连超时；
只设 `HF_ENDPOINT=https://hf-mirror.com` 还会撞 Xet 块存储 401；
**需同时设 `HF_HUB_DISABLE_XET=1`** 才能走普通 HTTP 下载。模型已缓存本机
（`~/.cache/huggingface`）。Windows 下 HF 缓存无符号链接权限，仅警告（多占磁盘，无害）。

三者在技术栈（AGENTS §2 / 方案）中已点名，属卡内确认范围。
**安装预案（任务卡坑②：装不上不卡进度）**：docling 安装/模型下载设时限尝试；
失败则 PyMuPDF-only 交付（适配器照写、降级链天然生效），requirements 暂不加
docling 并在 PROGRESS 记 TODO，后续可无痕补装——这正是适配器设计的意义。
`parse_force_pymupdf=True` 期间即为纯 PyMuPDF 形态。
**本次实测结果：安装与模型下载均成功，未触发降级预案。**

## 10. 验收标准

1. `pytest backend/tests/ -q` 全绿（含原有 3 条 S0-5 测试）
2. `python scripts/parse_demo.py` 跑 3 份真实 PDF（笔记/试卷/教材页，用户提供
   路径）：**肉眼检查**标题层级与页码正确（任务卡验收原文）；
   每份打印 parser 用的是哪个（预期 docling，若降级需给出真实原因）
3. 一份真实 DOCX（用户有就测，没有用 fixture 演示）heading_path 正确
4. 降级演示：`--force-pymupdf` 跑同一份试卷，对比 Docling 效果（体现兜底差异）
5. 实测体积/耗时回填 §9；AGENTS §9.6 锚点回填 ai 适配器样例

## 11. 与契约文档的关系

- `docs/SCHEMA.md` / `docs/API.md` 本卡**不改**（CLI 阶段，未到建表与接口）
- `ParsedBlock` 是 S1-2 切片器的输入契约；若评审中调整字段，须在此 spec 定稿，
  S1-2 的 spec 引用本文件
- 实现验收后，设计决策 1/2/4 择要归档进 docs/DECISIONS.md（D-013 起）
