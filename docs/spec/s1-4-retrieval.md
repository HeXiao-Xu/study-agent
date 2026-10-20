# S1-4 混合检索 + RRF 融合（spec）

> 任务卡：`docs/AI协作开发实施计划.md` S1-4（第 410–425 行）
> 前置：S1-1 解析、S1-2 切片、S1-3 Embedding + pgvector 入库已完成
> 状态：设计已获用户认可，待评审本 spec 后写 plan
> 日期：2026-10-20

## 1. 背景与目标

S1-3 已把三份真实样张（试卷 23 块、笔记 6 块、教材页 9 块，共 38 块）写入
`note_chunks`，每块同时具备：

- `embedding VECTOR(1024)`：DashScope `text-embedding-v4` 语义向量
- `tsv TSVECTOR`：jieba 分词后 `to_tsvector('simple', ...)` 的全文索引

S1-4 的目标是**把两种检索能力合并成一个可调用的检索器**：

1. 向量检索：pgvector cosine，`top_k=20`
2. 全文检索：jieba 查询 + `ts_rank_cd`，`top_k=20`
3. RRF 融合：`score = Σ 1/(60 + rank_i)`，按 `chunk_id` 去重
4. debug 模式：保留两路原始排名与分数，便于肉眼判断
5. `scripts/retrieval_eval.py`：10 个真实问题，打印纯向量 / 纯全文 / 混合三路 top5

S1-4 是 S1-5 Rerank 的输入层：S1-5 会在本卡融合结果上取 top-30 再重排；
因此本卡必须保留完整候选列表与两路排名，不能只返回一个已经截断的 top5。

## 2. 范围与非目标

### 2.1 本卡做

- 新增 `backend/app/ai/rag/retriever.py`
- 新增 `backend/tests/test_retriever.py`
- 新增 `scripts/retrieval_eval.py`
- 在 `backend/app/utils/zh_tokenizer.py` 增加 `build_tsquery_or()`（复用已有 `tokenize_zh`）
- 修复 S1-3 遗留的数据库连接配置（见 §3.4）
- 更新 PROGRESS、DECISIONS、spec/plan 的实测回填

### 2.2 本卡不做

- **不做 Rerank**：S1-5 才接重排模型
- **不做 API/前端**：S1-4 是 CLI 验证阶段，无 `docs/API.md` 变更
- **不改 SCHEMA、不加迁移**：`note_chunks` 现有列足够
- **不提前做 S2-1**：`notes` / `note_kps` 不建，`subject_id` / `kp_ids` 过滤只预留
- **不引入新依赖**：SQLAlchemy / pgvector / jieba / tiktoken 均已在 requirements
- **不做查询改写、HyDE、多路召回扩展**：保持最小可解释管线

## 3. 任务卡对应与契约冲突

### 3.1 任务卡要求

| 任务卡原文 | 本卡执行 |
|---|---|
| 向量检索：pgvector cosine，top_k=20，支持 user_id / subject_id / kp_ids 过滤下推 | 向量路 `top_k=20`；`user_id` 下推；`subject_id`/`kp_ids` 因表未建，传入时明确报未启用 |
| 全文检索：tsv 上的 jieba 分词查询（复用 S1-3 分词工具），top_k=20 | 复用 `tokenize_zh`，新增 OR 语义 `build_tsquery_or`；`top_k=20`；`ts_rank_cd` 排序 |
| RRF：`score = Σ 1/(60 + rank_i)`，去重，保留两路原始排名 | `rrf_fuse()` 纯函数；按 `chunk_id` 去重；保留 `vector_rank` / `fulltext_rank` / 原始距离/分数 |
| debug 模式：打印每路命中的标题与分数 | `retrieval_eval.py --debug`；默认也打印三路 top5 |
| 10 个问题打印三路 top5 对照 | 脚本内置 10 问 + 期望关键词，打印 hit@5 / MRR@5 汇总 |
| 合成 20 条假数据，验证两路命中、RRF 顺序 | `test_retriever.py` 用 20 条合成命中 + fake session，零真实 DB/网络 |

### 3.2 冲突：subject_id / kp_ids 没有可下推的列

- `note_chunks` 只有 `user_id`，没有 `subject_id` / `kp_ids`
- `notes.subject_id` 在 `notes` 表，`note_kps` 是独立的 many-to-many 表，二者都属 S2-1
- 本卡若强行加列或建表，会改动 SCHEMA、需要回填/重索引，并提前吃 S2-1 的设计

**用户已拍板**：S1-4 只做 `user_id` 下推；`retrieve_hybrid()` 保留
`subject_id: int | None = None`、`kp_ids: list[int] | None = None` 参数，
传入非空值时抛 `RetrievalFilterUnavailable`，消息明确写“需要 S2-1 的
notes/note_kps，S1-4 仅支持 user_id”。**不静默忽略、不伪造过滤能力。**

### 3.3 全文查询语义：AND 改为 OR

S1-3 的 `build_tsquery()` 用 ` & ` 连接，用于验收 SQL
`to_tsquery('simple','函数 & 单调性')`，保持不变。

但 S1-4 的输入是自然问句，实测 10 个问题用 AND **全部 0 命中**：

```text
函数的定义域怎么求？      tokens=函数/的/定义域/怎么/求        AND 0 | OR 28
函数单调性的定义是什么？   tokens=函数/单调性/的/定义/是/什么   AND 0 | OR 29
如何用定义证明……单调递增？ tokens=如何/用/定义/证明/...         AND 0 | OR 30
```

原因是“的 / 在 / 上 / 怎么 / 如何”等词要求同块出现，条件过严。
**用户已拍板**：S1-4 全文路用 OR（`|`）召回，再由 `ts_rank_cd` 按覆盖密度排序；
S1-3 的 `build_tsquery()` 与验收 SQL 不动。

### 3.4 前置修复：Windows 下 localhost 的 IPv6 连接卡死

实现前技术探针发现 `new_session()` 在 psycopg `wait_conn` 无限卡住：

- Windows `localhost` 先解析 `::1`，Docker Compose 只发布 `127.0.0.1:5432`
- 无超时参数时 psycopg 一直等 IPv6，不自动回退
- 实测：`localhost + connect_timeout=5` 5.12s 成功；`127.0.0.1` 0.04s 成功

修复（属于 S1-3 遗留环境问题，随本卡提交）：

- `backend/app/core/config.py` 默认 `DATABASE_URL` 改 `127.0.0.1`
- `backend/app/core/db.py` engine 增加 `connect_args={"connect_timeout": 5}`
- `.env.example` 的 `DATABASE_URL` 改 `127.0.0.1`；本地 `.env` 同步（不提交）
- 增加一条 `tests/test_db.py` 守卫 `connect_timeout`，防止回归

## 4. 架构与数据流

```text
query: str
  │
  ├─ 空串？ ──是──> 返回空 RetrievalResult（不调用 Embedding）
  │
  ├─ subject_id / kp_ids 非空？ ──是──> RetrievalFilterUnavailable
  │
  ├─ EmbeddingClient.encode([query]) -> query_vector[1024]
  │
  ├─ 向量路 SQL
  │    SELECT note_chunks.*, embedding <=> :vec AS distance
  │    WHERE user_id = :uid
  │    ORDER BY embedding <=> :vec, id
  │    LIMIT 20
  │
  ├─ build_tsquery_or(query) -> "词1 | 词2 | ..."
  │    ├─ 空 token 串 ──> 跳过全文路
  │    └─ 全文路 SQL
  │         SELECT note_chunks.*, ts_rank_cd(tsv, to_tsquery('simple', :q)) AS score
  │         WHERE user_id = :uid AND tsv @@ to_tsquery('simple', :q)
  │         ORDER BY score DESC, id
  │         LIMIT 20
  │
  └─ rrf_fuse(vector_hits, fulltext_hits, k=60, final_k=None)
       -> 按 chunk_id 去重、分数相加、稳定排序
       -> RetrievalResult(vector, fulltext, fused, tsquery, elapsed_ms)
```

两路查询串行执行。任务卡写“并行”，本卡理解为“两路都执行、结果融合”；
同一 SQLAlchemy `Session` 不是线程安全的，38 块数据下串行开销可忽略。
S1-5/S3 数据量或延迟上来后，再拆两个 Session/连接做并发，不在本卡引入线程池。

## 5. 检索器接口与数据模型

`backend/app/ai/rag/retriever.py`：

```python
RRF_K = 60
DEFAULT_TOP_K = 20

class RetrievalFilterUnavailable(ValueError):
    """S1-4 只能下推 user_id；subject/kp 依赖 S2-1。"""

class RetrievedChunk(BaseModel):
    chunk_id: int
    note_id: int
    chunk_index: int
    content: str
    heading_path: str | None = None
    page_no: int | None = None
    chunk_type: str | None = None
    vector_rank: int | None = None
    vector_distance: float | None = None
    fulltext_rank: int | None = None
    fulltext_score: float | None = None
    rrf_score: float = 0.0

class RetrievalResult(BaseModel):
    query: str
    tsquery: str
    vector: list[RetrievedChunk]
    fulltext: list[RetrievedChunk]
    fused: list[RetrievedChunk]
    elapsed_ms: int

def retrieve_hybrid(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    final_k: int | None = None,
    client: EmbeddingClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult: ...

def rrf_fuse(
    vector_hits: list[RetrievedChunk],
    fulltext_hits: list[RetrievedChunk],
    *,
    k: int = RRF_K,
    final_k: int | None = None,
) -> list[RetrievedChunk]: ...
```

设计约束：

- `RetrievedChunk` 只带检索与调试需要的字段，不复制整行 ORM 对象
- `RetrievalResult` 同时保留三份列表：纯向量、纯全文、融合
- `final_k` 只截断 `fused`；`vector` / `fulltext` 始终保留 `top_k` 条
- `rrf_fuse()` 是纯函数：不读数据库、不调用 Embedding、不改输入对象

## 6. 向量检索

```python
distance = NoteChunk.embedding.cosine_distance(query_vector).label("distance")
stmt = (
    select(NoteChunk, distance)
    .where(NoteChunk.user_id == user_id)
    .order_by(distance.asc(), NoteChunk.id.asc())
    .limit(top_k)
)
rows = session.execute(stmt).all()
```

- 使用 pgvector SQLAlchemy 的 `cosine_distance`，生成 `<=>`，不手写向量字符串
- `ORDER BY distance, id`：距离相同按 id 稳定排序
- `user_id` 在同一个 `WHERE` 中，满足“过滤下推”
- 查询向量来自 `EmbeddingClient.encode([query])`；维度必须等于配置的 1024，
  否则抛 `EmbeddingError`（不把错误向量送进 SQL）
- 当前 38 行数据下 HNSW 是否命中不影响正确性；S2 数据量上来后再用
  `EXPLAIN` 检查 `ix_note_chunks_embedding_hnsw` 的使用情况

## 7. 全文检索（OR + ts_rank_cd）

### 7.1 查询构造

在 `backend/app/utils/zh_tokenizer.py` 增加：

```python
def build_tsquery_or(text: str) -> str:
    """查询侧：token 去重后 | 连接；用于自然问句全文检索（S1-4）。"""
    return " | ".join(dict.fromkeys(tokenize_zh(text)))
```

- 复用 `tokenize_zh`，保留 S1-3 的领域词典与操作符过滤
- 去重避免 `x | x | 1 | 1` 这类重复 lexeme
- 空文本返回 `""`，调用方跳过全文查询
- **不修改** `build_tsquery()`；S1-3 验收 SQL 继续用 `&`

### 7.2 SQL

```python
tsquery = func.to_tsquery("simple", tsquery_str)
score = func.ts_rank_cd(NoteChunk.tsv, tsquery).label("fulltext_score")
stmt = (
    select(NoteChunk, score)
    .where(NoteChunk.user_id == user_id, NoteChunk.tsv.op("@@")(tsquery))
    .order_by(score.desc(), NoteChunk.id.asc())
    .limit(top_k)
)
```

- `ts_rank_cd` 是覆盖密度排名，适合“问句多个词命中多少”的场景
- 原始 `fulltext_score` 保留在 `RetrievedChunk.fulltext_score`，只用于 debug，
  **不参与 RRF 分数计算**
- 全文路无命中返回空列表，不视为错误

### 7.3 为什么不加停用词表

- 先保持最小实现：OR 召回 + `ts_rank_cd` 排序
- 10 问评测会暴露“的/在/怎么”等噪声；若确实明显，再在 S1-4 内加
  最小停用词表并记录到 DECISIONS，不提前猜
- 不把“如何/怎么”等词硬编码进 tokenizer，避免影响 S1-3 的写入侧分词

## 8. RRF 融合

### 8.1 公式

```text
RRF(d) = Σ_i 1 / (k + rank_i(d))
```

- `k = 60`（任务卡指定；Cormack et al. 2009 的常用取值）
- `rank_i(d)` 从 1 开始；不在第 i 路结果中则该项为 0
- **只用排名，不用 distance / ts_rank 原始分数**
- 两路都命中的块分数相加；只在一路命中的块保留单路分数

### 8.2 去重与排序

1. 按 `chunk_id` 建 `dict`
2. 先遍历向量路：`rank=1..n`，`rrf_score = 1/(k+rank)`
3. 再遍历全文路：命中已有块则加分；新块插入并加分
4. 排序键：
   - `rrf_score` 降序
   - 最优单路排名升序（`min(vector_rank, fulltext_rank)`）
   - `chunk_id` 升序（最终稳定）
5. 可选 `final_k` 截断

### 8.3 数值例子

`k=60`：

| 情况 | 分数 |
|---|---|
| 两路都第 1 | `1/61 + 1/61 ≈ 0.032787` |
| 向量第 1、全文第 10 | `1/61 + 1/70 ≈ 0.030679` |
| 只有向量第 1 | `1/61 ≈ 0.016393` |
| 只有全文第 1 | `1/61 ≈ 0.016393` |

因此“两路都命中”的块天然排在“只命中一路”的块之前；这正是 RRF 的意图。

### 8.4 反例（测试必须覆盖）

不能写成：

```python
score = 0.5 * cosine_similarity + 0.5 * ts_rank  # 错：量纲不同
```

`distance` 越小越好、`ts_rank` 越大越好，直接归一化相加既不稳又可被单路高分绑架。
测试用“原始分数高但排名低”的构造证明实现只认排名。

## 9. 过滤、错误处理、日志

### 9.1 过滤

- `user_id`：必填，向量路/全文路都在 `WHERE` 中显式过滤（AGENTS §4）
- `subject_id` / `kp_ids`：非空即抛 `RetrievalFilterUnavailable`；消息包含
  “S2-1 / notes / note_kps / 仅支持 user_id”，不静默忽略
- `top_k <= 0`、`final_k <= 0`：抛 `ValueError`
- 空 query：返回空结果，`vector` / `fulltext` / `fused` 都是 `[]`，`elapsed_ms=0`

### 9.2 错误

- `EmbeddingError`：查询向量维度不符、厂商调用失败，原样上抛
- `OperationalError`：数据库连接失败，原样上抛；CLI 负责给可读提示
- 不吞异常、不返回半成品结果

### 9.3 日志

`retrieval_done`（INFO，结构化）：

```json
{
  "event": "retrieval_done",
  "scene": "retrieve",
  "user_id": 1,
  "top_k": 20,
  "vector_hits": 20,
  "fulltext_hits": 20,
  "fused_hits": 35,
  "tsquery": "函数 | 定义域 | 怎么 | 求",
  "latency_ms": 420
}
```

不记录块原文、不记录 Key；`tsquery` 只含分词后的检索词。

## 10. 评测脚本与 10 个问题

`scripts/retrieval_eval.py`：

```text
python scripts/retrieval_eval.py [--user-id 1] [--top-k 20] [--debug]
```

流程：

1. `set_trace_id("retrieval-eval-" + uuid4().hex[:12])`
2. 取 Embedding 客户端（未配置 Key 时给可读错误）
3. 逐题调用 `retrieve_hybrid(..., top_k=top_k, final_k=None)`
4. 每题打印：
   - 问题、`tsquery`
   - 纯向量 top5：`rank / note_id / chunk_index / heading / distance / snippet`
   - 纯全文 top5：`rank / note_id / chunk_index / heading / ts_rank / snippet`
   - 混合 top5：`rank / note_id / chunk_index / heading / rrf / v_rank / f_rank / snippet`
5. 汇总：
   - `hit@5`：top5 中至少一块包含任一期望关键词
   - `MRR@5`：首个命中块的排名倒数，未命中为 0
   - 三路各一行：`vector x/10 (MRR 0.xxx)` 等
6. `--debug` 额外打印每路完整 `top_k` 条与 RRF 明细

### 10.1 10 个问题与期望关键词（运行前固定）

| # | 问题 | 期望关键词（任一命中） |
|---|---|---|
| 1 | 函数的定义域怎么求？ | 定义域 |
| 2 | 函数单调性的定义是什么？ | 单调性 |
| 3 | 如何用定义证明函数在区间上单调递增？ | 单调递增、增函数 |
| 4 | 奇函数和偶函数有什么性质？ | 奇函数、偶函数 |
| 5 | 二次函数在闭区间上的最值怎么求？ | 最大值、最小值 |
| 6 | 分段函数 f(f(-1)) 怎么求？ | f(f(-1)) |
| 7 | 函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？ | 单调递增、单调性 |
| 8 | 已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？ | 解析式 |
| 9 | 函数图象关于原点对称说明什么？ | 原点、奇函数 |
| 10 | 商品定价最大利润问题怎么建模？ | 利润 |

约束：

- 关键词在**运行前**固定；跑完发现混合不好，**不改问题/关键词**，如实报告
- 关键词必须能在真实样张的某块内容中找到，否则 hit 定义失效
- 关键词区分度：避免用“函数”“数学”这类全库高频词
- 评测只读；不写库、不改数据

### 10.2 输出判读

- 纯向量强在语义相近但字面不同的问句
- 纯全文强在定义、术语、公式名等精确词
- 混合应至少不差于两路中较好者；理想情况是两路互补，`hit@5`/`MRR@5` 更高
- 若样张只有 38 块、两路都容易命中，混合可能只提升排名而非 hit@5；
  这是可接受的结果，但必须如实记录，不宣称“明显更好”

## 11. 测试策略（零真实网络/DB）

### 11.1 `backend/tests/test_retriever.py`

Fake 组件：

- `FakeSession`：按调用顺序返回预设 `FakeResult`，记录 SQL 语句
- `FakeResult`：`.all()` 返回预设行
- `FakeClient`：`encode()` 记录输入，返回固定 1024 维向量；可配置维度错误
- `make_chunk()`：构造带 id/note_id/chunk_index/content/heading 的假块
- `make_hits(n, prefix)`：生成 20 条 `RetrievedChunk`

用例：

1. `test_rrf_fuse_dedupes_and_sums_overlap`：20+20 条、5 条重叠 → 35 条；
   重叠块 `rrf_score` 等于两路名次分数之和
2. `test_rrf_fuse_keeps_single_path_hits`：只在向量/只在全文的块都保留
3. `test_rrf_fuse_uses_rank_not_raw_score`：构造“原始分数高但排名低”的输入，
   证明排序只由排名决定
4. `test_rrf_fuse_tie_break_is_stable`：同分时按最优单路名次、再按 chunk_id
5. `test_retrieve_hybrid_both_paths_hit`：两路各返回块，融合后含两路块；
   重叠块同时有 `vector_rank` 与 `fulltext_rank`
6. `test_query_filters_use_user_id_and_limits`：编译两条 SQL，断言
   `user_id` 参数、`LIMIT`、向量 `<=>`、全文 `@@` / `ts_rank_cd`
7. `test_rejects_subject_and_kp_filters`：抛 `RetrievalFilterUnavailable`，
   不执行 SQL、不调用 Embedding
8. `test_empty_query_returns_empty_without_embedding`：`vector/fulltext/fused` 空，
   `client.calls == []`
9. `test_skips_fulltext_when_no_tokens`：query 只有标点 → `tsquery=""`，
   只执行向量 SQL，`fulltext=[]`
10. `test_final_k_truncates_fused_only`：`final_k=3` 时 `fused` 3 条，
    `vector`/`fulltext` 仍各 20 条
11. `test_dimension_mismatch_raises_embedding_error`：FakeClient 返回 8 维 →
    `EmbeddingError`
12. `test_invalid_top_k_raises_value_error`：`top_k=0` / `final_k=0`

### 11.2 `backend/tests/test_zh_tokenizer.py` 追加

- `test_build_tsquery_or_dedupes_and_uses_or`：
  `build_tsquery_or("函数的定义域，函数的定义域")` 含 `|`、无 `&`、token 去重
- `test_build_tsquery_or_empty`：空文本返回 `""`

### 11.3 `backend/tests/test_db.py`

- `test_engine_sets_connect_timeout`：monkeypatch `create_engine`，断言
  `connect_args["connect_timeout"] == 5`，防止再退回“无超时卡死”

### 11.4 测试数量

- 现有 78 条全部保持绿
- 新增预计 15 条（retriever 12 + tokenizer 2 + db 1）
- 最终预计 **93 passed**；以实测为准，不得有 FAIL，不得跳过

## 12. 配置与依赖

- 无新增环境变量
- 无新增依赖
- 新增常量：`RRF_K=60`、`DEFAULT_TOP_K=20`（retriever 顶部，便于论文调参）
- 复用：`EmbeddingClient` / `get_embedding_client`、`NoteChunk`、`new_session`、
  `tokenize_zh`、`build_tsquery_or`
- 修复：`DATABASE_URL` 默认 `127.0.0.1`、engine `connect_timeout=5`

## 13. 验收标准

1. **单测**：`cd backend && ..\.venv\Scripts\python.exe -m pytest -q` 全绿
   （现有 78 + 新增 15；预期 **93 passed**，以实测为准）
2. **真实评测**：`python scripts/retrieval_eval.py` 对 38 块真实数据跑完 10 问，
   打印三路 top5 与 hit@5/MRR@5；无异常、无 Key 泄漏
3. **RRF 正确性**：抽查至少 3 题，融合结果中重叠块的 `rrf_score` 等于
   `1/(60+v_rank) + 1/(60+f_rank)`；排序符合公式
4. **过滤**：`--user-id 999` 返回空；直接传 `subject_id`/`kp_ids` 抛
   `RetrievalFilterUnavailable`，不静默忽略
5. **两路可用**：至少 1 题纯全文命中、至少 1 题纯向量命中；混合结果包含两路块
6. **肉眼判断**：用户查看 10 问三路 top5，确认混合是否更好；如实记录结论
7. **代码质量**：函数带类型标注；不吞异常；不新增未确认依赖；无硬编码 Key
8. **文档**：PROGRESS、DECISIONS D-017、spec/plan 实测回填；API.md 不动

## 14. 与任务卡的偏离（已确认）

| # | 任务卡原文 | 本卡执行 | 原因 |
|---|---|---|---|
| 1 | 支持 user_id / subject_id / kp_ids 过滤下推 | 只下推 user_id；subject/kp 传入时抛明确异常 | notes/note_kps 属 S2-1，当前无列可过滤；用户已拍板 |
| 2 | 全文检索复用 S1-3 分词工具 | 复用 `tokenize_zh`，新增 OR 语义 `build_tsquery_or` | 自然问句用 AND 实测 10/10 零命中；用户已确认 OR |
| 3 | 10 问 top5 肉眼判断 | 额外输出 hit@5 / MRR@5 汇总 | 让“混合是否更好”有可复现依据，不替代肉眼 |
| 4 | 合成 20 条假数据 | 20 条 RRF 假数据 + fake session 行 | 纯 RRF 用 20 条验证两路命中与顺序；SQL 路径用少量行验证结构 |
| 5 | — | 修复 localhost IPv6/连接超时 | S1-3 遗留环境问题，阻塞 S1-4 真实查询 |
| 6 | 向量检索 + 全文检索并行 | 两路都执行，但同一 Session 串行 | Session 非线程安全；38 块下延迟可忽略，避免为并行引入多连接 |

## 15. 风险与处理

| 风险 | 处理 |
|---|---|
| 38 块太小，三路都命中，混合看不出优势 | 如实报告 hit@5/MRR@5 与具体排名；不修改问题/关键词粉饰 |
| OR 召回噪声大（的/在/怎么） | 先看 10 问结果；若 top5 明显被噪声占据，再加最小停用词表并记录 D-017 |
| `to_tsquery` 对超长查询报错 | CLI 问题短；若后续 API 接长文本，在 `build_tsquery_or` 截断 token 数并记录 |
| HNSW + user_id 过滤未走索引 | 38 行不影响正确性；S2 数据量上来后用 `EXPLAIN` 检查，必要时建 partial index |
| Embedding API 失败/限流 | 客户端已有重试与 `EmbeddingError`；CLI 给可读提示，不打印 Key |
| Windows localhost IPv6 卡死 | URL 改 `127.0.0.1` + `connect_timeout=5`；`test_db.py` 守卫 |
| RRF 被误写成归一化相加 | 单测反例 + spec §8.4 + DECISIONS 记录公式 |

## 16. 与契约文档的关系

- **SCHEMA.md 不动**：`note_chunks` 现有列足够；subject/kp 过滤留 S2-1
- **API.md 不动**：S1-4 无 HTTP 接口
- **AGENTS §9.6**：本卡完成后把 `backend/app/ai/rag/retriever.py` 作为
  “RAG 检索器锚点”回填
- **DECISIONS**：新增 D-017，记录 RRF 公式、OR 语义、subject/kp 延后、
  IPv6/connect_timeout 修复
- **PROGRESS**：记录 10 问实测 hit@5/MRR@5、三路差异、混合结论

## 17. 实施顺序（给 plan 的输入，不在本文件展开）

1. 前置修复：DATABASE_URL/connect_timeout + test_db
2. `build_tsquery_or` + 测试
3. `retriever.py` 数据模型与纯函数 RRF + 测试
4. 向量/全文 SQL + fake session 测试
5. `retrieve_hybrid` 编排 + 错误/边界测试
6. `retrieval_eval.py` + 10 问真实运行
7. 用户肉眼验收
8. 文档归档 + 提交

## 18. 实施回填（实测）

- 日期：2026-10-20
- 测试：`pytest` **93 passed**（现有 78 + S1-4 新增 15：`test_retriever` 12 + `test_zh_tokenizer` 2 + `test_db` 1）
- 真实数据：`note_chunks` 38 块（试卷 23 / 笔记 6 / 教材页 9），`user_id=1`
- 运行：`.venv\Scripts\python.exe scripts\retrieval_eval.py`
- 原始输出：`eval/results/s1-4-retrieval-eval.txt`（学校名已脱敏为“某中学”）；
  空用户对照：`eval/results/s1-4-retrieval-eval-empty-user.txt`

### 18.1 三路汇总

| 路径 | hit@5 | MRR@5 |
|---|---:|---:|
| 纯向量 | 10/10 | 0.900 |
| 纯全文 | 9/10 | 0.725 |
| 混合 RRF | **10/10** | **0.933** |

### 18.2 逐题首命中名次

| # | 问题 | vector | fulltext | hybrid |
|---|---|---|---:|---:|
| 1 | 函数的定义域怎么求？ | 1 | 1 | 1 |
| 2 | 函数单调性的定义是什么？ | 1 | 1 | 1 |
| 3 | 如何用定义证明函数在区间上单调递增？ | 1 | 1 | 1 |
| 4 | 奇函数和偶函数有什么性质？ | 2 | 2 | **1** |
| 5 | 二次函数在闭区间上的最值怎么求？ | 1 | 4 | **1** |
| 6 | 分段函数 f(f(-1)) 怎么求？ | **1** | - | 3 |
| 7 | 函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？ | 2 | 1 | **1** |
| 8 | 已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？ | 1 | 1 | 1 |
| 9 | 函数图象关于原点对称说明什么？ | 1 | 2 | 1 |
| 10 | 商品定价最大利润问题怎么建模？ | 1 | 1 | 1 |

### 18.3 具体差异

- **Q4**：纯向量/纯全文都排第 2，混合把目标块 `note=102 chunk=3`
  提到第 1；RRF 同时利用了两路的一致性。
- **Q5**：纯全文第 4，混合第 1（`note=103 chunk=4`，函数最大（小）值定义）。
- **Q7**：纯向量第 2，混合第 1（`note=103 chunk=1`，单调性定义）。
- **Q6 回退**：纯向量第 1，混合第 3。全文 OR 的 token 含 `f`、`1`，
  大量数学块都含这两个符号，全文票把 `note=102 chunk=1/3` 抬到目标块
  `note=101 chunk=12` 前面（目标块在混合里 `v=1 f=14`）。这是当前
  “只按排名、不加权/不 rerank”的真实代价。

### 18.4 RRF 抽查

- Q1 `note=102 chunk=1`：`v=1, f=1` → `1/61 + 1/61 = 0.0327869`，
  输出 `rrf=0.03279`。
- Q3 `note=101 chunk=19`：`v=1, f=5` → `1/61 + 1/65 = 0.031778`，
  输出 `rrf=0.03178`。

### 18.5 空用户过滤

`--user-id 999`：三路均 `hit@5=0/10`、`MRR@5=0.000`，证明 `user_id`
过滤下推生效，不是“先取全库再在 Python 里过滤”。

### 18.6 结论（不粉饰）

- 混合在三路中最好（MRR 0.933），但只比纯向量高 **0.033**，未达到
  任务卡“明显更好”的强度；38 块使 hit@5 饱和，三路都容易进 top5。
- 功能与测试完成；质量目标**部分达成**。不修改问题/关键词/事后调参。
- Q6 是唯一回退题；S1-5 可用 rerank 或查询停用词（`f`/`1` 等）改善，
  但不在 S1-4 范围。
- 学校名脱敏不改变任何排名与分数。