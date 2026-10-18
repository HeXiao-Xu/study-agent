# S1-2 结构化切片器 — 功能 spec

- 任务卡：docs/AI协作开发实施计划.md「S1-2 结构化切片器（关键算法）」
- 上游契约：docs/spec/s1-1-doc-parse.md（ParsedDocument/ParsedBlock 是本卡输入，spec §11 已约定引用）
- 拍板记录：chunk_type 入库加列（2026-10-19 用户确认）；formula 简单密度规则（2026-10-19 用户确认）
- 状态：待用户评审

## 1. 目标

把 S1-1 的解析结果重组成「检索原子块」：**题目一题一块**（题干+选项+解析聚齐）、
**笔记按标题层级切**、块大小落在合理区间。这是 RAG 检索质量的第一决定因素
（任务卡坑：禁止退化为"每 500 字硬切一刀"）。

## 2. 输入与输出契约

输入：`ParsedDocument`（S1-1 `parse_document()` 的返回值；扫描版/空 blocks 也可能进来）。

输出：`list[Chunk]`（新模型，放 `backend/app/ai/rag/chunker.py`）：

```python
class ChunkType(str, Enum):
    question = "question"
    note = "note"
    formula = "formula"

class Chunk(BaseModel):
    content: str                 # 块文本（多块合并时用换行连接）
    chunk_index: int             # 0 起，文档内递增
    heading_path: str            # "/" 连接，如 "第三章/一、函数的概念"；无层级时 ""
    page_no: int | None          # 取首块页码（docx → None，随 S1-1 决策）
    token_count: int             # tiktoken cl100k_base 实测
    chunk_type: ChunkType
```

与 SCHEMA.md note_chunks 对齐：content/chunk_index/token_count/heading_path/page_no
一一对应（heading_path 用 "/" 连接即 SCHEMA 示例「函数/单调性/例题2」的格式）；
`chunk_type` 为本卡新增列（见 §7 契约变更）。

## 3. 架构：两阶段管道

```
阶段 A（重组）：ParsedBlock 流 → 逻辑单元
  ├─ 题目单元：开题号块起，吞并后续块（选项/解析/答题线），
  │   到下一开题号或标题块为止
  └─ 笔记单元：同一 heading_path 下的连续非题目块合并
阶段 B（尺寸调整）：逻辑单元 → Chunk
  ├─ ≤600 token → 直接成块
  ├─ >800 token → 递归切（题目：小问号→块边界；笔记：块边界→句边界）；
  │   笔记切分时新块头部带上一块尾部 ≤60 token 的句子重叠；题目块不重叠
  └─ formula/表格单元 → 整块保留，永不拦腰切
```

决策理由：规则解耦——题目完整性全在阶段 A、尺寸约束全在阶段 B，
两阶段各自可单测（任务卡「5 条规则 × ≥2 用例」的天然骨架）；
单遍扫描方案（边扫边出块）会把两件事纠缠在一起，测试爆炸。

## 4. 关键规则细则

### 4.1 题号检测（规则 1）

两类，分开处理：

| 类别 | 正则（匹配块首，忽略前导空白） | 例（来自样张） | 行为 |
|---|---|---|---|
| 开题号 | `^\d+[.．、](?!\d)` | `2．函数 f(x)…`、`9．已知函数…` | 新题目单元 |
| 开题号 | `^【?\s*例\s*\d+\s*】?` | `【例2】`、`例 1` | 新题目单元 |
| 开题号 | `^第\s*\d+\s*题` | `第7题` | 新题目单元 |
| 小问号 | `^[（(]\d+[)）]` | `（1）求 f(x)…` | **不**新开题；是超长题切分时的优先切分点 |

- 「一、选择题」这类大题标题：理想情况 Docling 已标为 heading；**但 S1-1 实测
  试卷样张里未被识别**（笔记里识别了，模型行为不一致）——因此切片器自判
  大题标题模式 `^[一二三四五六七八九十]+[、.．]` 作为单元边界：终止当前题目
  单元、开启新笔记单元
- 题目单元吞并后续块直到：下一开题号 / 大题标题 / 下一标题块 / 单元超限（§4.3）

### 4.2 笔记切块（规则 2）

- 同一 heading_path 的连续块合并成一个笔记单元
- **标题块前置并入**：若某块的文本恰为下一块 heading_path 的末元素（S1-1 的
  结构约定，非字号启发式），该标题块并入下一单元开头——标题领着自己的小节
- 单元 >800 token：先按原块边界切，单块仍超 800 再按句边界（。！？；）切
- 300–600 是**软目标**：小于 300 的小节保持独立（跨标题合并会污染 heading_path，
  小块对检索无害）；上限 800 是**硬约束**

### 4.3 尺寸与重叠（规则 3）

- 目标区间 300–600 token；上限 800（题目块同限）
- 60-token 重叠**仅笔记块**：切分时，新块以「上一块尾部句子累计 ≤60 token」开头
- 题目块不重叠（题与题天然独立）

### 4.4 token 计数（规则 4）

tiktoken `cl100k_base`。DeepSeek 无公开 tokenizer 库，cl100k_base 为业界通用
近似；token_count 用途是上下文预算而非计费，误差可接受。S1-3 起若厂商提供
官方 tokenizer 可换（接口收敛在 `_count_tokens()` 单点）。

### 4.5 formula 判定（用户拍板：简单密度规则）

块同时满足：**中文字符 ≤2**、**数学符号+数字字符占比 ≥40%**、**长度 ≥10**
→ chunk_type=formula。宁漏勿错：误判成 note 无害，误判成 formula 丢语义。
题目单元永远 question（优先级高于 formula）。

**三类豁免（实测驱动，2026-10-19 验收补充）**：
- 选项行（`A．…` / `Ａ．…`）——纯数值选项零中文+符号密集会命中密度，但必须留在题目里
- 小问行（`（1）…` / `(1)…`）——同理
- 纯答题线（`________` 下划线段）——在 _build_units 预处理直接丢弃（见 §4.6）

### 4.6 边界情况（规则 5，全部不抛异常）

| 情况 | 处理 |
|---|---|
| blocks 为空（含扫描版 PDF） | 返回 `[]` |
| 空文本块 | 阶段 A 直接丢弃 |
| 纯答题线块（下划线/横线/空白占位） | 阶段 A 丢弃（零检索语义；实测假命中 formula） |
| 纯表格块（Markdown 表） | note 整块保留，永不切（切表格=毁结构） |
| 超长单行公式 | formula 整块保留，永不切 |
| 题目块超 800 | 按小问号→块边界降级切；续块仍标 question |
| heading_path 为空列表的块 | heading_path=""，照常处理 |

## 5. 测试策略（backend/tests/test_chunker.py，≥12 用例）

fixture **手工构造 ParsedDocument**（输入是 S1-1 的输出对象，不必跑真 docling——
快、确定、零网络）。5 条规则 × ≥2：

1. 题号：①完整题（题干+选项两块合并成一 question）②题号到下一题号边界正确
2. 标题切：③同节多块合并 ④节超 800 按块边界切
3. 尺寸/重叠：⑤笔记块间重叠 ≈60 token ⑥题目块无重叠 ⑦小节 <300 保持独立
4. tiktoken：⑧token_count 与 tiktoken 直算一致（非字符数）
5. 边界：⑨空 blocks → [] ⑩表格块整块保留 ⑪超长公式块 formula 不切 ⑫空文本块被丢弃
   ⑬formula 密度规则命中/不命中各一 ⑭小问号不新开题

## 6. 交付物

| 文件 | 内容 |
|---|---|
| `backend/app/ai/rag/chunker.py` | Chunk/ChunkType 模型 + `chunk_document(doc: ParsedDocument) -> list[Chunk]` |
| `backend/tests/test_chunker.py` | §5 用例 |
| `scripts/chunk_demo.py` | `python scripts/chunk_demo.py <文件> [--limit N]`：跑解析+切片，打印每块摘要 + **token 分布 ASCII 直方图**（区间计数，如 0-100/101-200/…；不引 matplotlib，AGENTS §2.1） |
| `docs/SCHEMA.md` | note_chunks 加 `chunk_type TEXT 可空 默认 'note'`（契约先行，S1-3 建表用） |
| `backend/requirements.txt` | +tiktoken（钉版） |

## 7. 契约变更与依赖说明

- **SCHEMA.md 加列**：note_chunks 新增 chunk_type（question/note/formula），
  契约先行（AGENTS §9.1）——已获用户确认
- **新依赖 tiktoken**（任务卡点名）：OpenAI 官方分词库，纯 wheel 几 MB、无大模型
  下载。**实测（2026-10-19）：tiktoken 0.14.0 安装顺利，cl100k_base 的 BPE 文件
  从 openaipublic（Azure CDN）下载正常、「单调递增的定义」= 7 tokens，未触发
  被墙预案；缓存后离线可用。**

## 8. 验收标准（任务卡原文 + 补充）

1. `pytest backend/tests -q` 全绿（含 S1-1 的 20 条，无回归）
2. 样例试卷跑 `scripts/chunk_demo.py`：**题目块数 = 实际题数**（一题一块验证，
   17 题样张应为 17 个 question 块 ± 超限续块），打印 token 分布直方图
3. **用户亲眼检查切片结果**（任务卡原文强调）：题目完整不拦腰、笔记块层级正确
4. 文档同步：SCHEMA 加列、requirements、PROGRESS、DECISIONS（设计决策归档 D-015）

## 9. 与契约文档的关系

- 本卡**动 SCHEMA.md**（加 chunk_type 列）——加列在先，建表在 S1-3
- API.md 不动（CLI 阶段）；ParsedDocument 契约沿用 s1-1 spec §2，冲突时以 S1-1 spec 为准
