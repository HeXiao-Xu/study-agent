# S1-3 Embedding 与 pgvector 入库 — 功能 spec

- 任务卡：docs/AI协作开发实施计划.md「S1-3 Embedding 与 pgvector 入库」
- 上游契约：docs/spec/s1-1-doc-parse.md（ParsedDocument）、docs/spec/s1-2-chunker.md（Chunk）
- 数据契约：docs/SCHEMA.md §4.3 note_chunks、§9 索引与检索策略
- 拍板记录（2026-10-19 用户确认）：
  1. Embedding 供应商：阿里云百炼 **DashScope text-embedding-v4**（OpenAI 兼容，默认 1024 维）
  2. 首个迁移只建 **note_chunks**，不建 notes/files/users，也**不加外键**；S2-1 建齐后再补
  3. 新增依赖：`sqlalchemy`、`alembic`、`psycopg[binary]`、`jieba`、`pgvector`
  4. Embedding 调用先落**结构化日志**，`llm_call_logs` 表到 S3-7 再建并切换（临时偏离 AGENTS §5，已明记）
- 状态：待用户评审

## 1. 目标

把 S1-2 的切片结果**批量向量化并写入 `note_chunks`**，同时建 HNSW 向量索引与
GIN 全文索引，使 S1-4 能做「向量 + 全文」混合检索。验收以真实样张、真实
Embedding API、真实 Postgres 为准，禁止假数据。

## 2. 输入与输出契约

输入：
- `list[Chunk]`（S1-2 `chunk_document()` 输出：content / chunk_index /
  heading_path / page_no / token_count / chunk_type）
- `note_id`、`user_id`（S1-3 为合成长整型，S2-8 起由真实笔记/用户传入）
- 可选 `source_file_id`

输出：
- `IndexingResult`（Pydantic 模型）：
  `chunk_count / vector_dim / total_tokens / elapsed_ms / cost_cny`
- 数据库中 `note_chunks` 的 N 行（含 embedding 与 tsv）

Embedding 客户端契约（任务卡原文）：

```python
def encode(
    self,
    texts: list[str],
    *,
    on_batch: Callable[[BatchStats], None] | None = None,
) -> list[list[float]]: ...
```

`BatchStats`（dataclass）：`batch_index`、`batch_count`、`batch_size`、`tokens`、
`latency_ms`。`on_batch` 是可选进度回调，不改变任务卡要求的返回值语义。

## 3. 架构与分层

```
scripts/index_demo.py
  └─ parse_document (S1-1) → chunk_document (S1-2)
       └─ app/services/indexing.py  ← 唯一入库编排入口
            ├─ app/utils/zh_tokenizer.py   jieba 切词 → tsv / tsquery（S1-4 复用）
            ├─ app/ai/embedding/           厂商适配器（批量 / 重试 / 维度校验）
            └─ app/models/note_chunk.py    SQLAlchemy 模型（Alembic 迁移同源）
```

- 业务编排放 `services/`，路由/脚本只做参数与打印（AGENTS §4）。
- Embedding 只在 `ai/` 层调用 HTTP；业务层只 import 门面 `get_embedding_client()`（AGENTS §9.3）。
- S2-8 文档解析 Worker、S3-1 索引服务必须复用 `index_chunks`，不得另写一份。

## 4. Embedding 适配器

### 4.1 接口与实现

| 文件 | 内容 |
|---|---|
| `ai/embedding/base.py` | `EmbeddingClient` 抽象类：`model`、`dim`、`encode()` |
| `ai/embedding/openai_compat.py` | 默认实现：OpenAI 兼容 `/embeddings`，同时适配 DashScope / OpenAI / 硅基流动 |
| `ai/embedding/local.py` | `LocalEmbeddingClient` 占位：`encode()` 抛 `NotImplementedError`，文档标注「后期成本优化再填」 |
| `ai/embedding/__init__.py` | 门面 `get_embedding_client()`：按 `EMBEDDING_PROVIDER` 返回实现 |
| `ai/embedding/errors.py` | `EmbeddingError`（provider/status_code/retryable），不携带 Key |

### 4.2 请求参数

- endpoint：`{EMBEDDING_BASE_URL}/embeddings`
- 默认 base_url：`https://dashscope.aliyuncs.com/compatible-mode/v1`（百炼旧域名仍可用；
  业务空间专属域名通过配置覆盖）
- 默认 model：`text-embedding-v4`
- `dimensions=1024`、`encoding_format="float"`
- Header：`Authorization: Bearer <Key>`；Key 只从 Settings 读
- `EMBEDDING_PROVIDER` 取值：`dashscope`（默认）/ `openai_compat` / `local`；
  前两者共用同一 OpenAI 兼容实现，只影响默认 base_url 与 model 提示

### 4.3 批处理与重试

- **批大小默认 10**：DashScope 官方限制 text-embedding-v4 单次最多 **10 行**、单行
  ≤8192 token；任务卡的「32 条/次」在厂商侧不成立，以厂商硬上限为准（spec §11 偏离表）。
  批大小可配置 `EMBEDDING_BATCH_SIZE`，代码不写死 10。
- 可重试：HTTP 429、500/502/503/504、连接错误、超时。
- 退避：指数退避 + 抖动，尊重 `Retry-After`（上限 30s）；默认最多重试 4 次。
- 不可重试：400/401/403 等 4xx 立即抛 `EmbeddingError`，消息截断且不含 Key。
- 超时：默认 60s，`EMBEDDING_TIMEOUT_SECONDS` 可配。
- 空输入：直接返回 `[]`，不发请求。
- 响应解析：按 `data[].index` 还原顺序；条数不符或单条维度不符立即报错。

### 4.4 维度核对（任务卡坑 ①）

- 客户端按响应实测长度校验 `embedding_dim`；服务入库前再断言每行维度。
- **建迁移前先跑一次真实调用**（`index_demo.py --probe-only`），打印实测维度。
  实测必须为 1024 才执行迁移；若不是，**停止并报告契约冲突**，不自行改 SCHEMA。

### 4.5 日志与成本

- 每个 HTTP 批次记录结构化日志：`scene=embed`、`model`、`tokens`、`latency_ms`、
  `trace_id`、`batch_size`。
- 入库服务汇总：总 token、总耗时、估算花费 = `tokens / 1_000_000 × 单价`。
- 单价从配置读（默认 0.5 元/百万 token，即 0.0005 元/千 token），**不硬编码在代码里**。
- S1-3 不建 `llm_call_logs` 表（S3-7 建表后切换写入）；此为已确认的临时偏离。

## 5. 数据模型与迁移

### 5.1 模型（`backend/app/models/note_chunk.py`）

按 SCHEMA §4.3 全字段，只建 `note_chunks` 一张表：

| 列 | 类型 | 可空 | 说明 |
|---|---|---|---|
| id | BIGINT identity | 否 | PK |
| note_id | BIGINT | 否 | S1-3 无 FK；S2-1 补 FK→notes |
| user_id | BIGINT | 否 | 冗余过滤列，S2-1 补 FK→users；索引 |
| chunk_index | INTEGER | 否 | 与 note_id 复合唯一 |
| content | TEXT | 否 | 块文本 |
| token_count | INTEGER | 否 | S1-2 的 tiktoken 计数 |
| chunk_type | TEXT | 是 | 默认 `'note'`；question/note/formula |
| heading_path | TEXT | 是 | `"/"` 连接 |
| embedding | VECTOR(1024) | 否 | HNSW cosine |
| tsv | TSVECTOR | 是 | jieba 切词后写入；GIN |
| source_file_id | BIGINT | 是 | S1-3 无 FK；S2-1 补 |
| page_no | INTEGER | 是 | 引用定位 |
| bbox_json | JSONB | 是 | 本期恒 NULL（解析层尚未产出框） |

约束/索引：
- `UNIQUE(note_id, chunk_index)` → `uq_note_chunks_note_chunk_index`
- `ix_note_chunks_user_id`
- `ix_note_chunks_embedding_hnsw`：`USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`
- `ix_note_chunks_tsv_gin`：`USING gin (tsv)`

### 5.2 Alembic（`backend/alembic/`）

- 首次接入：`alembic.ini`、`alembic/env.py`、`alembic/script.py.mako`、`alembic/versions/0001_create_note_chunks.py`
- 迁移先 `CREATE EXTENSION IF NOT EXISTS vector`，再建表与索引；降级只删表，不删扩展。
- `target_metadata = Base.metadata`；`app/models/__init__.py` 显式导入 `NoteChunk` 供自动生成。
- 迁移中维度**硬编码 1024**（迁移必须可复现，不读运行时配置）；模型 `Vector(1024)` 与 Settings 的 `embedding_dim=1024` 三处需一致，模型测试守住。
- 生产/本地连接串取 `Settings.database_url`；engine 设 `hide_parameters=True`，避免异常日志带出密码。

## 6. 全文检索（jieba）

### 6.1 分词工具（`backend/app/utils/zh_tokenizer.py`）

- `tokenize_zh(text) -> list[str]`：`jieba.cut(text, cut_all=False)`，保留中文/字母/数字
  token（小写），过滤空白、纯标点与 tsquery 操作符（`& | ! ( ) : * ' \`）。
- **领域词典（实测补充）**：jieba 默认把「单调性」切成「单调/性」，任务卡验收 SQL
  `函数 & 单调性` 会 0 命中；用 jieba 标准 userdict 机制加载
  `backend/app/utils/math_dict.txt`（45 个高中数学高频词，freq=100000），不改分词算法。
- `join_for_tsv(text) -> str`：token 以单空格连接，写入 `to_tsvector('simple', ...)`。
- `build_tsquery(text) -> str`：token 以 ` & ` 连接，供 `to_tsquery('simple', ...)`；
  空文本返回 `""`，调用方应跳过全文查询（S1-4）。
- 不使用 `to_tsquery('chinese', ...)`，不手写 bigram（任务卡坑 ②）。

### 6.2 写入方式

- 应用层算好 `join_for_tsv(content)`，插入时 `tsv = to_tsvector('simple', <token串>)`。
- 不用生成列/触发器：SCHEMA 未约定，且 S2-8 需要显式控制分词版本。

## 7. 入库服务（`backend/app/services/indexing.py`）

```python
def index_chunks(
    session: Session,
    chunks: list[Chunk],
    *,
    note_id: int,
    user_id: int,
    source_file_id: int | None = None,
    replace: bool = True,
    client: EmbeddingClient | None = None,
    progress: Callable[[BatchStats], None] | None = None,
) -> IndexingResult:
```

流程：
1. 空 chunks：`replace=True` 时仍删除该 note 的旧块，返回零值结果。
2. 取客户端（未配置 Key 时抛出可读错误，提示配置项，不打印 Key）。
3. `client.encode(texts, on_batch=progress)` 批量向量化；每批由客户端记日志。
4. 校验条数与每行维度；不符抛 `EmbeddingError`，不写库。
5. `replace=True`：`DELETE FROM note_chunks WHERE note_id=:id AND user_id=:uid`
   （显式过滤 user_id，AGENTS §4）。
6. 构造 `NoteChunk` 行：`tsv=func.to_tsvector('simple', join_for_tsv(content))`；
   `chunk_type=chunk.chunk_type.value`；`bbox_json=None`。
7. `add_all` → `flush` → `commit`；任何异常 `rollback` 后原样抛出（不吞异常）。
8. 汇总 token/耗时/花费，返回 `IndexingResult`。

幂等性：同一 `note_id + user_id` 重复跑会先删后插，结果一致；`UNIQUE(note_id, chunk_index)`
兜底防止脏数据。

## 8. 演示脚本（`scripts/index_demo.py`）

```text
python scripts/index_demo.py <文件> [--note-id 1] [--user-id 1]
       [--source-file-id N] [--force-pymupdf] [--probe-only] [--no-replace]
```

- `--probe-only`：只发一次真实 Embedding 请求，打印实测维度/模型/耗时，不写库；
  维度 ≠ 配置时退出码非 0。
- 正常流程：解析→切片→入库，逐批打印 `[batch i/n] 条数 / tokens / 耗时`；
  结束打印块数、维度、总 token、总耗时、估算花费、平均每块 token。
- 打印三条验收 SQL 与建议的 `psql` 命令。
- 数据库连接失败时给出「启动 deploy/docker-compose.dev.yml」的提示，不打印连接串。
- CLI 启动时 `set_trace_id("index-" + uuid4().hex[:12])`，让调用日志可串联。

## 9. 配置与依赖

### 9.1 新增环境变量（`.env.example` 同步）

```dotenv
# ===== Embedding（S1-3；Key 只放 .env，禁止提交）=====
EMBEDDING_PROVIDER=dashscope
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=10
EMBEDDING_TIMEOUT_SECONDS=60
EMBEDDING_MAX_RETRIES=4
EMBEDDING_PRICE_PER_MILLION=0.5
```

- 同时接受标准名 `DASHSCOPE_API_KEY` 与项目名 `EMBEDDING_API_KEY`；两个字段分开收，
  `EMBEDDING_API_KEY` 为空时回退 `DASHSCOPE_API_KEY`（避免 .env 里空的
  `EMBEDDING_API_KEY=` 把标准名覆盖成空 Key）。
- Key 字段 `repr=False`；配置日志不输出 Key。

### 9.2 依赖（钉版写入 requirements.txt）

`sqlalchemy`、`alembic`、`psycopg[binary]`、`jieba`、`pgvector`。
均为已确认依赖；不引入 sentence-transformers / FlagEmbedding / openai SDK。
实测钉版：SQLAlchemy 2.1.5 / alembic 1.20.0 / psycopg[binary] 3.3.6 / jieba 0.42.1 / pgvector 0.5.1。

## 10. 测试策略（backend/tests/，全部零真实网络）

| 文件 | 用例要点 |
|---|---|
| `test_config.py` | Embedding 默认值（1024/批 10/单价）与 `EMBEDDING_API_KEY`/`DASHSCOPE_API_KEY` 两个 Key 别名；repr 不泄漏 Key |
| `test_embedding_client.py` | 25 条按 10/10/5 分 3 批且顺序保持；429 后重试成功；重试耗尽抛 `EmbeddingError`；401 不重试；维度不符报错；空输入不发请求；Key 不出现在异常/repr；`on_batch` 回调次数 |
| `test_zh_tokenizer.py` | 中文切词；标点/操作符过滤；空文本；`&` 连接；大小写；领域词典整词；公式文本不产生非法 tsquery |
| `test_indexing.py` | fake session + fake client：replace 删除条件含 user_id；插入行数与字段；tsv 使用 `to_tsvector`；维度断言；token/花费汇总；空 chunks 行为；异常回滚 |
| `test_note_chunk_model.py` | 表名/列集合/可空性/唯一约束/`Vector(1024)`/`TSVECTOR`，防模型漂移 |
| 既有测试 | S1-1 20 条 + S1-2 24 条全部保持绿 |

- httpx 用 `MockTransport`，不引入 respx 等新依赖。
- DB 集成不在 pytest 里做（避免测试依赖 Docker）；由 §12 的真实命令验收。
- **实测合计 78 passed**（既有 44 + 新增 34：config 5 / embedding 9 / tokenizer 7 / model 6 / indexing 7）。

## 11. 与任务卡的偏离（已确认，需在 DECISIONS 归档）

| # | 任务卡原文 | 本卡执行 | 原因 |
|---|---|---|---|
| 1 | 批处理 32 条/次 | 默认 10 条/次，可配置 | DashScope text-embedding-v4 单次最多 10 行（官方文档硬限制） |
| 2 | 每次调用落 `llm_call_logs` | 先落结构化日志，S3-7 建表后切换 | 本卡迁移范围只含 note_chunks；避免提前吃 S3-7 |
| 3 | 按 SCHEMA 建 note_chunks | 只建 note_chunks，无 FK | notes/files/users 属 S2-1；合成 id 完成 S1-3 验收 |
| 4 | 向量维度「别照抄 1024」 | 先真实探测；预期 1024 | 与 SCHEMA 一致才迁移，不一致停下报告 |
| 5 | 中文全文 jieba | 应用层 jieba + `to_tsvector('simple')` | 与 SCHEMA §9 一致；不用 pg_jieba/生成列 |
| 6 | 中文全文 jieba（默认词典） | 追加 `math_dict.txt` 领域 userdict | 默认把「单调性」切成「单调/性」，验收 SQL 会 0 命中；属词典调优，不改算法 |

## 12. 验收标准（任务卡原文 + 补充）

1. **迁移**：`alembic upgrade head` 成功；`\d note_chunks` 可见
   `embedding vector(1024)`、HNSW、GIN、`UNIQUE(note_id, chunk_index)`。
2. **维度**：`index_demo.py --probe-only` 打印实测 1024，与配置一致。
3. **真实入库**：三份样张（试卷/笔记/教材页）分别 `--note-id 101/102/103` 跑通；
   打印块数、token、耗时、花费；重复跑同一 note_id 结果不重复。
4. **任务卡 SQL**：
   ```sql
   SELECT count(*) FROM note_chunks;
   SELECT heading_path, left(content,30) FROM note_chunks LIMIT 5;
   SELECT content FROM note_chunks WHERE tsv @@ to_tsquery('simple','函数 & 单调性') LIMIT 3;
   ```
   数量与脚本打印一致；全文查询有命中（若样张确实无同块共现，如实报告，不造假）。
5. **代码质量**：`pytest` 全绿（实测 78/78：既有 44 + 新增 34）；所有函数带类型标注；
   异常不吞；Key 不进代码/日志/提交历史。
6. **文档同步**：SCHEMA §0 维度定稿、DECISIONS D-016、PROGRESS、.env.example、
   requirements；API.md 不动（CLI 阶段无接口）。

## 13. 已知风险与处理

| 风险 | 处理 |
|---|---|
| 未配置 Key / Key 无效 | 脚本启动即报可读错误并提示 .env 配置项；不打印 Key |
| 厂商限流 429 | 指数退避 + `Retry-After`，默认重试 4 次；耗尽后报错并保留已完成批次日志 |
| 实测维度 ≠ 1024 | 停止迁移与入库，报告 SCHEMA 冲突，由用户决定改契约 |
| 样张全文查询无命中 | 打印分词结果排查；如实报告，不调整验收 SQL 造假 |
| Docker 未启动 | 脚本捕获连接错误，提示 `docker compose -f deploy/docker-compose.dev.yml up -d` |
| 大文件多批次 | S1-3 样张规模小；S2-8 Worker 复用服务时按文件分批调用，避免长事务 |

## 14. 与契约文档的关系

- 本卡**不改表结构**（note_chunks 已在 S1-2 定稿 chunk_type），只把 SCHEMA §0 的
  `VECTOR(1024)` 从「⚠ 待定」更新为「✅ S1-3 定稿」。
- 无新 API；API.md 不动。
- 与 S1-1/S1-2 spec 冲突时，输入结构以它们为准；本卡不修改上游代码。

## 15. 实施回填（实测）

- 日期：2026-10-19
- 环境：Windows + Python 3.11.9；PostgreSQL 16.3 + pgvector（Docker `pgvector/pgvector:pg16`）
- Embedding：DashScope `text-embedding-v4`，实测 `维度=1024`（与配置/SCHEMA 一致）
- 依赖实测：SQLAlchemy 2.1.5 / alembic 1.20.0 / psycopg 3.3.6 / jieba 0.42.1 / pgvector 0.5.1
- 分词实测：`tokenize_zh("函数的单调性：设 f(x) 在区间 D 内。")` →
  `['函数','的','单调性','设','f','x','在','区间','d','内']`（领域词典生效；默认词典为 `单调/性`）

| 样张 | note_id | 块数 | question | tokens | Embedding 批次 | 脚本总耗时 | 估算花费 |
|---|---|---|---|---|---|---|---|
| 高中数学试卷-函数单元测试.pdf | 101 | 23 | 17 | 1169 | 10/10/3 | 131326 ms | ¥0.000584 |
| 高中数学笔记-函数与导数.pdf | 102 | 6 | 0 | 588 | 6 | 130537 ms | ¥0.000294 |
| 高中数学教材页-函数的单调性.pdf | 103 | 9 | 5 | 706 | 9 | 130699 ms | ¥0.000353 |

- 总块数 38；首轮总 tokens 2463；首轮估算花费合计 **¥0.001231**（Embedding API 实际耗时每批 0.2–0.7s，脚本总耗时主要由 Docling 解析约 130s 构成）
- 迁移：`alembic upgrade head` 成功；`\d note_chunks` 含 `embedding vector(1024)`、`tsv tsvector`；
  索引 `ix_note_chunks_embedding_hnsw`（hnsw, cosine, m=16, ef_construction=64）、
  `ix_note_chunks_tsv_gin`（gin）、`ix_note_chunks_user_id`、唯一约束 `uq_note_chunks_note_chunk_index`
- 全文验收：`tsv @@ to_tsquery('simple','函数 & 单调性')` 命中 3 行（note 102/103）
- 幂等：note 101 复跑后仍 23 块，总表仍 38 块
- 向量冒烟：以 note 102 首块为查询向量，最近邻距离 0.0000 / 0.3247 / 0.4063（HNSW 可用）
- 环境插曲：Windows 下 Alembic 首次 psycopg 连接偶发无响应挂起；`alembic/env.py` 已加
  `connect_args={"connect_timeout": 5}`，后续迁移正常

