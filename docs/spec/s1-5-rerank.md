# S1-5 Rerank 接入 Spec

> 对应任务卡：`docs/AI协作开发实施计划.md` §S1-5（第 429–446 行）
> 状态：已确认并实施（2026-10-20）；实测见 §15
> 前置：S1-4 混合检索 + RRF 已提交（`3ee7a4a`）

## 1. 目标

在 S1-4 的混合检索之后增加厂商 Rerank：

1. RRF 融合后取 **top-30** 候选
2. 一次请求批量送给 Rerank API
3. 按 `relevance_score` 重排，返回 **top-6**
4. 保留 `rerank_score`、模型、tokens、耗时、估算费用
5. 失败/超时/无 Key/本地占位时**回退到融合顺序**，不能拖垮检索链路
6. `retrieval_eval.py` 增加“混合+Rerank”第四路，打印四路对照
7. 人工验收：10 个问题中至少 7 个 Rerank 后 top5 更相关

## 2. 非目标

- 不引入本地 Rerank 模型（sentence-transformers / FlagEmbedding / BGE 本地权重）
- 不改 SCHEMA、不加表/列；`rerank_score` 只在内存结果里
- 不改 API.md（S1-5 无 HTTP 接口）
- 不改变 S1-4 `retrieve_hybrid()` 的默认行为（见 §3 决策 1）
- 不做 query 改写、上下文组装、引用回答（S1-6）
- 不把 rerank 分数写库或用于拒答阈值（S1-6 再校准）

## 3. 关键决策

### 3.1 决策 1：新增 `retrieve_hybrid_reranked()`，不改 `retrieve_hybrid()`

S1-4 的 12 条 retriever 测试和 10 问评测都依赖 `retrieve_hybrid()` 返回完整
`fused` 列表。S1-5 新增入口：

```python
retrieve_hybrid_reranked(...) -> RetrievalResult
```

- `retrieve_hybrid()` 保持原样，S1-4 单测/评测零改动
- 新入口内部调用 `retrieve_hybrid()`，再取 `fused[:30]` 重排
- 返回结果中：
  - `fused`：RRF 全量（调试/对照）
  - `reranked`：重排后的 top-6（最终结果）
  - `rerank_info`：本次重排元数据
- S1-6 及后续服务使用 `retrieve_hybrid_reranked()`

这样既满足“集成进 retriever”，又不破坏已验收的 S1-4 契约。

### 3.2 决策 2：默认模型用 `qwen3-rerank`，不用 `gte-rerank-v2`

阿里云文档明确 `gte-rerank` 系列将于 **2026-05-30** 下线，当前日期已过；
默认使用 `qwen3-rerank`。参考：

- [文本排序 API](https://www.alibabacloud.com/help/zh/model-studio/text-rerank-api)
- [qwen3-rerank 模型信息](https://help.aliyun.com/zh/model-studio/qwen3-rerank)

`qwen3-rerank` 限制（北京地域）：

| 项 | 值 |
|---|---:|
| 单条 Query / Document 最大输入 | 4,000 tokens |
| 单次请求最大文档数 | 500 |
| 单次请求最大输入 | 120,000 tokens |
| 价格 | 0.5 元 / 百万 tokens |
| RPM | 5,400 |

本卡只用 30 条候选，远低于 500；但请求 token 需守住 120k（见 §5.2）。

### 3.3 决策 3：一次请求传全部候选

任务卡明确“支持一次传多条候选（批量调用），不要一条一次请求”。
`DashScopeRerankClient.rerank()` 将 30 条候选放进一个 `documents` 数组，
只发一次 HTTP 请求；重试也只重发整批，不拆成逐条。

### 3.4 决策 4：重排失败只降级，不抛给调用方

重排是加分项。以下情况统一回退 `fused[:6]`：

- 未配置 Key / 本地占位
- 网络超时、429/5xx 重试耗尽
- 4xx 参数错误
- 响应 JSON 非法、`output.results` 为空、index 越界/重复
- 有效分数为空

回退时：

- `reranked = fused[:6]`（保持 RRF 顺序）
- `rerank_info.fallback = True`
- `rerank_info.error` 写简短原因（不含 Key/正文）
- 打 `rerank_fallback` WARNING 日志
- 不抛异常，不影响 `retrieve_hybrid_reranked()` 返回

### 3.5 决策 5：截断到 3,600 tokens，不默认 512

任务卡要求“查文档确认，不要默认 512”。qwen3-rerank 单条上限 4,000
tokens；代码用 **3,600** 留 10% 安全余量：

- 30 条 × 3,600 + 查询 3,600 = **111,600 tokens** < 120,000
- 用 `tiktoken cl100k_base` 近似计数（项目已有依赖；Qwen tokenizer 不公开，
  近似误差由 10% 余量吸收）
- 超长时截断并记 `rerank_truncated` 日志（只记 token 数，不记正文）

### 3.6 与任务卡的偏离

| # | 任务卡原文 | 本卡执行 | 原因 |
|---|---|---|---|
| 1 | 产出 `backend/app/ai/rerank/client.py` | 新增 `client.py` + `__init__.py` | 单文件容纳契约、DashScope 适配器、本地占位；门面统一导出 |
| 2 | 集成进 retriever：融合后取 top-30 → 重排 → 返回 top-6 | 新增 `retrieve_hybrid_reranked()`，`retrieve_hybrid()` 不变 | 保护 S1-4 已验收契约；新入口返回 `reranked` top-6 |
| 3 | 默认走厂商 Rerank API | 默认 `qwen3-rerank` | gte-rerank 已公告下线 |
| 4 | 本地模型实现仅留占位 | `LocalRerankClient.rerank()` 抛 `RerankError`，由上层降级 | 不伪造本地重排结果 |
| 5 | 记录本次调用耗时与花费 | `RerankInfo` + `rerank_call` 日志 + eval 汇总 | tokens 来自 `usage.total_tokens`，费用按 0.5 元/百万估算 |

## 4. 架构与数据流

```
retrieve_hybrid_reranked(session, query)
  └─ retrieve_hybrid()                       # S1-4：向量 + 全文 + RRF
       ├─ vector_hits (top_k=20)
       ├─ fulltext_hits (top_k=20)
       ├─ fused = rrf_fuse(...)              # 全量，保持 S1-4 行为
       └─ vector_ms / fulltext_ms / elapsed_ms
  └─ rerank_fused(query, fused, candidates=30, top_k=6)
       ├─ candidates = fused[:30]
       ├─ RerankClient.rerank(query, candidates, top_n=6)
       │    └─ DashScopeRerankClient → 一次 HTTP 请求
       ├─ 成功：按 score 降序，回填 rerank_score，取 top-6
       └─ RerankError：fused[:6] + rerank_info.fallback=True
  └─ RetrievalResult(fused=全量, reranked=top6, rerank_info=...)
```

关键点：

- 重排只作用于 `fused`，不重新查向量/全文
- 30 条候选是 RRF 全量排序的前 30；不足 30 时用全部
- 重排后的 `reranked` 是最终 top-6；`fused` 仍保留全量，方便 eval 对照
- `rerank_score` 只回填到 `reranked` 里的块；`fused` 里的块不带重排分

## 5. Rerank Client

### 5.1 文件

- `backend/app/ai/rerank/client.py`
  - `RerankError`
  - `RerankCandidate`（dataclass：`id: int`、`content: str`）
  - `RerankScore`（dataclass：`id: int`、`score: float`）
  - `RerankResponse`（dataclass：`model`、`scores`、`tokens`、`latency_ms`、`cost_yuan`）
  - `RerankClient`（ABC）
  - `DashScopeRerankClient`
  - `LocalRerankClient`
  - `get_rerank_client()`（`lru_cache`）
- `backend/app/ai/rerank/__init__.py`：门面导出上述类型

### 5.2 契约

```python
class RerankClient(ABC):
    model: str

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        """一次请求重排全部候选；返回按 score 降序的 [(id, score)]。"""
```

- 空 `candidates`：直接返回空 `RerankResponse`，不发 HTTP
- `top_n` 缺省为 `len(candidates)`；传 6 表示只要前 6
- 返回的 `RerankScore.id` 必须对应输入候选的 `id`
- 返回按 `score` 降序；同分按输入 index 升序（稳定）

### 5.3 DashScope 请求

```http
POST {RERANK_BASE_URL}/services/rerank/text-rerank/text-rerank
Authorization: Bearer {RERANK_API_KEY}
Content-Type: application/json
```

```json
{
  "model": "qwen3-rerank",
  "input": {
    "query": "函数的单调性怎么证明？",
    "documents": ["候选块 1", "候选块 2", "..."]
  },
  "parameters": {
    "return_documents": false,
    "top_n": 6
  }
}
```

响应：

```json
{
  "output": {
    "results": [
      {"index": 0, "relevance_score": 0.9334},
      {"index": 2, "relevance_score": 0.3410}
    ]
  },
  "usage": {"total_tokens": 79}
}
```

解析规则：

- `results` 必须是非空列表；否则 `RerankError`
- `index` 必须是 `0 <= index < len(candidates)` 的整数；越界/重复/缺失
  可用项按错误处理
- `relevance_score` 转 `float`
- 按 score 降序、index 升序排序
- `usage.total_tokens` 缺省按 0；费用 = `tokens * RERANK_PRICE_PER_MILLION / 1_000_000`

### 5.4 超时、重试、费用

- `timeout=30s`（Config 可改）
- 最多重试 2 次（共 3 次请求）
- 重试条件：`httpx.TimeoutException`、`httpx.TransportError`、HTTP
  429/500/502/503/504
- 不重试：400/401/403/404 等 4xx（参数/权限问题重试无意义）
- 退避：`min(2**attempt, 30) + jitter`；支持 `Retry-After`
- 401/403 的错误信息只写状态码与响应前 200 字符，绝不打印 Key
- 日志 `rerank_call` 字段：
  `scene=rerank, model, candidates, top_n, tokens, latency_ms, cost_yuan, truncated`
- `RerankResponse` 同时带 `tokens/latency_ms/cost_yuan/model`，供上层汇总

### 5.5 本地占位

```python
class LocalRerankClient(RerankClient):
    model = "local"

    def rerank(...):
        raise RerankError("LocalRerankClient 为占位实现：本次不引入本地重排模型")
```

`RERANK_PROVIDER=local` 时，retriever 捕获 `RerankError` 并降级；
不返回伪造的“按原顺序重排”分数。

### 5.6 Config

新增 `Settings` 字段（全部从 `.env` 读，Key 带 `repr=False`）：

```python
rerank_provider: Literal["dashscope", "local"] = "dashscope"
rerank_api_key: str = Field(default="", repr=False)
rerank_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
rerank_model: str = "qwen3-rerank"
rerank_timeout_seconds: float = 30.0
rerank_max_retries: int = 2
rerank_max_doc_tokens: int = 3600
rerank_candidates: int = 30
rerank_top_k: int = 6
rerank_price_per_million: float = 0.5
```

`model_validator` 复用 S1-3 模式：`rerank_api_key` 为空时回退
`dashscope_api_key`。`.env.example` 增加对应 `RERANK_*` 空值/默认值；
本地 `.env` 不提交。

## 6. Retriever 集成

### 6.1 数据模型扩展

```python
class RetrievedChunk(BaseModel):
    # S1-4 字段不变
    rerank_score: float | None = None


class RerankInfo(BaseModel):
    model: str
    candidates: int
    top_k: int
    tokens: int
    latency_ms: int
    cost_yuan: float
    fallback: bool = False
    error: str | None = None


class RetrievalResult(BaseModel):
    # S1-4 字段不变
    vector_ms: int = 0
    fulltext_ms: int = 0
    reranked: list[RetrievedChunk] = Field(default_factory=list)
    rerank_info: RerankInfo | None = None
```

S1-4 现有构造不传新字段，全部走默认值；12 条测试保持绿。

### 6.2 `retrieve_hybrid()` 计时

在 S1-4 原有流程里补：

```python
vector_started = time.perf_counter()
vector_hits = _vector_search(...)
vector_ms = int((time.perf_counter() - vector_started) * 1000)

fulltext_started = time.perf_counter()
fulltext_hits = _fulltext_search(...)
fulltext_ms = int((time.perf_counter() - fulltext_started) * 1000)
```

`elapsed_ms` 仍是整条 `retrieve_hybrid()` 的总耗时（含 Embedding）；
返回值写 `vector_ms`、`fulltext_ms`。空查询返回 0。

### 6.3 `rerank_fused()`

```python
def rerank_fused(
    query: str,
    fused: list[RetrievedChunk],
    *,
    candidates: int = 30,
    top_k: int = 6,
    client: RerankClient | None = None,
) -> tuple[list[RetrievedChunk], RerankInfo | None]:
    """取 fused[:candidates] 重排；失败回退 fused[:top_k]。"""
```

规则：

1. `candidates <= 0` 或 `top_k <= 0` → `ValueError`
2. `fused` 为空 → `([], None)`，不调 API
3. `selected = fused[:min(candidates, len(fused))]`
4. 调用 `(client or get_rerank_client()).rerank(...)`，`top_n=min(top_k, len(selected))`
5. 成功：
   - 把 `RerankScore` 按 `id` 映射回 `RetrievedChunk`
   - 只保留有分数的块，按 `(-score, 原始 fused 下标)` 排序
   - 取前 `top_k`，`model_copy(update={"rerank_score": score})`
   - `RerankInfo(candidates=len(selected), top_k=top_k, fallback=False, ...)`
6. 有效分数为空 → 视为失败，进入回退
7. `RerankError`：
   - `reranked = fused[:top_k]`（原顺序）
   - `RerankInfo(model=实际 client.model；client 未创建则 "unavailable",
     candidates=..., top_k=..., tokens=0, latency_ms=..., cost_yuan=0,
     fallback=True, error=str(exc))`
   - `logger.warning("rerank_fallback", extra={...})`
8. 其他异常（代码 bug、参数错误）不吞，继续向上抛

### 6.4 `retrieve_hybrid_reranked()`

```python
def retrieve_hybrid_reranked(
    session: Session,
    query: str,
    *,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    rerank_candidates: int | None = None,  # None → Settings.rerank_candidates（默认 30）
    rerank_top_k: int | None = None,       # None → Settings.rerank_top_k（默认 6）
    client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    subject_id: int | None = None,
    kp_ids: list[int] | None = None,
) -> RetrievalResult:
```

流程：

1. 解析 `rerank_candidates` / `rerank_top_k`：显式值优先，否则读
   `get_settings()`；两者任一 `<= 0` 立即 `ValueError`（早失败，不白跑检索）
2. `result = retrieve_hybrid(..., final_k=None, client=client, subject_id=..., kp_ids=...)`
3. 若 `result.fused` 为空：直接返回 `result`（`reranked=[]`、`rerank_info=None`）
4. `reranked, info = rerank_fused(..., candidates=rerank_candidates, top_k=rerank_top_k)`
5. `return result.model_copy(update={"reranked": reranked, "rerank_info": info})`

`fused` 不截断，保留完整 RRF 结果供 eval/调试；`reranked` 是最终 top-6。

### 6.5 日志

`retrieval_done` 增加字段：

- `vector_ms`、`fulltext_ms`（S1-4 两路 SQL 耗时）
- `rerank_used`、`rerank_fallback`、`rerank_tokens`、`rerank_ms`、`rerank_cost_yuan`
  由 `retrieve_hybrid_reranked()` 另打 `retrieval_reranked` 日志记录
  （`retrieve_hybrid()` 本身不知道 rerank，不在旧日志里伪造这些字段）

`rerank_call` 由 Client 打；`rerank_fallback` 由 `rerank_fused` 打。
所有日志只记长度/数量/分数，不记候选正文；Key 永不入日志。

## 7. 评测

### 7.0 语料扩容（2026-10-20）

原语料只有 3 份样张、38 块，top-30 会覆盖 79% 的语料，测不出“初筛→重排”的
筛选价值。经用户确认，先用**合成样张**扩容（不是真实学生数据，论文不得冒充
真实语料）：

| note_id | 文件 | 块数 | 说明 |
|---:|---|---:|---|
| 104 | 高中数学笔记-指数函数与对数函数.docx | 7 | 指对定义、运算、复合单调性错题 |
| 105 | 高中数学教材页-导数与函数极值.docx | 10 | 导数与单调性、极值 |
| 106 | 高中数学试卷-三角函数与数列综合测试.docx | 20 | 三角/数列，作为跨章节干扰 |

扩容后：**75 块 / 6 个 note**；top-30 覆盖约 40%，能体现初筛与重排的差异。
生成脚本在仓库外 `E:\BiShe-AIStudy\测试数据\_make_more_sample_docs.py`，使用
项目已有 `python-docx`，未新增依赖；样张去掉了真实学校/姓名。

S1-4 基线在扩容语料上重跑（10 问固定）：

```text
vector         hit@5=10/10 MRR@5=0.900
fulltext       hit@5=9/10  MRR@5=0.720
hybrid         hit@5=10/10 MRR@5=0.920
```

基线仍接近饱和，但 top-30 已不再覆盖大部分语料；Rerank 的价值主要看
“前 5 条里干扰块是否被压下去”，人工验收仍按 7/10 判断。

### 7.1 脚本变更

`scripts/retrieval_eval.py` 从三路改为四路：

- 纯向量
- 纯全文
- 混合（RRF）
- 混合 + Rerank

每题仍打印 top5；Rerank 路额外打印：

- `rerank_score`
- `fallback`（是/否）
- `candidates`
- `tokens`
- `latency_ms`
- `cost_yuan`

每题打印耗时：

```text
耗时: total=...ms vector=...ms fulltext=...ms rerank=...ms
```

末尾汇总：

```text
vector         hit@5=10/10 MRR@5=0.900
fulltext       hit@5=9/10  MRR@5=0.720
hybrid         hit@5=10/10 MRR@5=0.920
hybrid+rerank  hit@5=?/10  MRR@5=?
rerank fallback=0/10  avg_latency=...ms  total_cost=...元
```

`--debug` 打印每路完整候选与 RRF/重排明细；默认仍只打 top5。
问题与关键词沿用 S1-4 的 10 条，**运行前固定，不因结果修改**。

### 7.2 人工验收

用户逐题看“混合 top5”与“混合+Rerank top5”：

- 至少 **7/10** 题 Rerank 后更相关（任务卡验收）
- 记录具体题号、名次变化、失败题原因
- 若不足 7/10，如实报告；不修改问题/关键词/事后调参
- 若 Rerank 全部 fallback，说明 Key/模型不可用，验收不通过

## 8. 测试计划

### 8.1 Client（17 条；原计划 10 + 7 条执行中补的边界回归）

1. `test_rerank_success_sends_one_batch_and_sorts`：MockTransport 捕获请求体，
   验证一次请求、30 条 documents、`top_n=6`、乱序响应被正确映射排序
2. `test_rerank_truncates_query_and_documents`：超长 query/doc 截到 3,600
   tokens（tiktoken 解码验证），日志/字段标记 truncated
3. `test_rerank_retries_500_then_success`：第一次 500，第二次 200；sleep 被记录
4. `test_rerank_timeout_exhausts_retries`：连续超时 → `RerankError(retryable=True)`
5. `test_rerank_400_not_retried`：400 只请求一次 → `RerankError(retryable=False)`
6. `test_rerank_malformed_response_raises`：`output.results` 缺失/非列表
7. `test_rerank_empty_candidates_no_request`：空列表直接返回空 response
8. `test_local_rerank_raises`：本地占位抛 `RerankError`
9. `test_rerank_invalid_top_n`：`top_n<=0` → `ValueError`
10. `test_rerank_duplicate_index_raises`：重复/越界 index → `RerankError`
11. `test_rerank_top_level_not_object_raises`：响应顶层是 list → `RerankError`
12. `test_rerank_malformed_usage_tokens_defaults_zero`：`total_tokens=null` → 0
13. `test_rerank_index_out_of_range_raises`：index 越界 → `RerankError`
14. `test_rerank_429_retry_after_then_success`：429 + `Retry-After: 1` 后成功
15. `test_rerank_400_does_not_echo_body`：4xx 错误信息不回显响应正文
16. `test_rerank_tokenizer_failure_raises_rerank_error`：tiktoken 加载失败 →
    `RerankError`，保证 retriever 能降级
17. `test_rerank_partial_results_raises`：返回条数少于 `top_n` → `RerankError`

所有 HTTP 用 `httpx.MockTransport`，测试套件零真实网络。

### 8.2 Retriever（10 条；原计划 8 + 2 条边界回归）

1. `test_retrieve_hybrid_reranked_orders_by_score`：fake reranker 返回乱序分数，
   断言 `reranked` 顺序、`rerank_score`、`fused` 不变、`rerank_info` 正确
2. `test_retrieve_hybrid_reranked_falls_back_on_error`：fake 抛 `RerankError`，
   断言 `reranked == fused[:6]`、`fallback=True`、error 有值
3. `test_retrieve_hybrid_reranked_caps_candidates_at_30`：40 条 fused，
   fake 记录收到的候选数为 30
4. `test_retrieve_hybrid_reranked_empty_fused_skips_rerank`：空 fused 不调 reranker
5. `test_retrieve_hybrid_reranked_empty_query_skips_all`：空查询不 embedding、
   不 rerank
6. `test_retrieve_hybrid_reranked_invalid_params`：`rerank_candidates<=0` /
   `rerank_top_k<=0` → `ValueError`
7. `test_retrieve_hybrid_reranked_fallback_keeps_rrf_order`：回退后前 6 与
   `fused[:6]` 完全一致
8. `test_retrieve_hybrid_reranked_integration`：fake session + fake embedding +
   fake reranker 走通完整路径，`vector_ms/fulltext_ms >= 0`
9. `test_rerank_fused_propagates_non_rerank_error`：非 `RerankError` 不被吞
10. `test_rerank_fused_factory_error_falls_back`：门面构造失败也回退，
    `model="unavailable"`

S1-4 的 12 条 retriever 测试必须保持绿；`retrieve_hybrid` 返回的新字段
默认值为 0/空，不改变既有断言。

### 8.3 Config（3 条）

1. `test_rerank_defaults`：provider/model/base_url/limits/price 默认值
2. `test_rerank_key_falls_back_to_dashscope`：`RERANK_API_KEY=` 空时取
   `DASHSCOPE_API_KEY`
3. `test_rerank_key_explicit_wins_and_repr_hides`：显式 Key 优先，repr 不含 Key

### 8.4 数量

- 现有 93 条保持绿
- 新增 31 条（client 17 + retriever 10 + config 3 + eval 编码 1）
- 原计划 21 条（client 10 + retriever 8 + config 3）；执行中补 10 条边界回归
- 实测 **124 passed**；不得 FAIL/跳过，详见 §15

## 9. 配置与依赖

- 新增环境变量（同步 `.env.example`）：
  `RERANK_PROVIDER`、`RERANK_API_KEY`、`RERANK_BASE_URL`、`RERANK_MODEL`、
  `RERANK_TIMEOUT_SECONDS`、`RERANK_MAX_RETRIES`、`RERANK_MAX_DOC_TOKENS`、
  `RERANK_CANDIDATES`、`RERANK_TOP_K`、`RERANK_PRICE_PER_MILLION`
- 无新增依赖：`httpx`、`tiktoken`、`pydantic` 已在 requirements
- 本地 `.env` 只需已有 `DASHSCOPE_API_KEY`；`RERANK_API_KEY` 可留空自动回退
- `.env` 不提交，Key 不出 repr/日志

## 10. 验收标准

1. **单测**：`cd backend && ..\.venv\Scripts\python.exe -m pytest -q`
   全绿（计划预期 114，实测 124 passed；多 10 条边界回归，见 §15）
2. **真实评测**：`python scripts/retrieval_eval.py` 对 **75 块 / 6 个 note** 的
   样张语料跑完 10 问，打印四路 top5、四路 hit@5/MRR@5、rerank
   耗时/tokens/费用/fallback
3. **人工判断**：10 题中至少 7 题 Rerank 后 top5 更相关；把具体题号与理由
   写入 spec/PROGRESS
4. **降级**：注入 fake `RerankError` 时返回 `fused[:6]`，`fallback=True`，
   日志有 `rerank_fallback`；不抛异常
5. **批量**：一次请求传全部候选（MockTransport 断言 1 次 HTTP、30 条 documents）
6. **截断**：超长 query/doc 截到 3,600 tokens；不默认 512
7. **费用/耗时**：`RerankInfo` 与日志有 tokens/latency/cost；eval 有汇总
8. **安全**：无 Key 泄漏；本地 `.env` 不提交；测试零真实网络
9. **文档**：PROGRESS、DECISIONS D-018、spec/plan 实测回填；API/SCHEMA 不动

## 11. 风险与处理

| 风险 | 处理 |
|---|---|
| 75 块仍偏小，Rerank 后未必 7/10 更相关 | 如实跑、如实报；记录具体题号，不调问题/关键词粉饰 |
| 新增语料是合成样张，不能代表真实学习材料 | 明确标注“样张评测”；论文数据以真实材料为准，后续可替换重跑 |
| 用户 Key 无 qwen3-rerank 权限 | eval 显示 fallback；报告“验收不通过：API 不可用”，不伪造分数 |
| Rerank 很慢，拖垮链路 | 30s 超时 + 2 次重试 + 失败回退；eval 记录每路耗时 |
| 120k 请求上限被超 | 3,600 token/条、最多 30 条，上限 111.6k；超长仍截断 |
| tiktoken 与 Qwen tokenizer 不一致 | 10% 安全余量；若 API 仍 400，降级并记录，后续调低上限 |
| 响应 index 乱序/缺失 | 按 index 映射回候选 id；越界/重复抛 `RerankError` 并回退 |
| 本地占位被误当成“已重排” | 抛 `RerankError`，`fallback=True`，不生成假分数 |
| 重排分被误当概率/写库 | 只在内存 `rerank_score`；不写 SCHEMA，不用于拒答阈值 |

## 12. 与契约文档的关系

- **SCHEMA.md 不动**：`rerank_score` 是内存字段，不落库
- **API.md 不动**：S1-5 无 HTTP 接口
- **S1-4 spec**：`retrieve_hybrid()` 契约不变；新增入口单独文档
- **AGENTS §9.6**：本卡完成后补 `backend/app/ai/rerank/client.py` 锚点
- **DECISIONS**：新增 D-018，记录 qwen3-rerank、批量/截断/降级、成本与实测
- **PROGRESS**：记录四路实测、7/10 人工结论、fallback 次数、耗时/费用

## 13. 实施顺序（给 plan 的输入）

1. Config + `.env.example` + config 测试
2. `RerankError` / models / `RerankClient` 契约
3. `DashScopeRerankClient`（批量、截断、重试、解析、费用）+ MockTransport 测试
4. `LocalRerankClient` + 门面 `get_rerank_client()` + 测试
5. Retriever 模型扩展 + `rerank_fused()` + 测试
6. `retrieve_hybrid_reranked()` + 计时/集成测试
7. `retrieval_eval.py` 四路 + 真实运行
8. 用户肉眼验收（≥7/10）
9. 文档归档 + 提交

## 14. 自检

- [x] 目标/非目标清晰
- [x] 与任务卡逐条对应，偏离有原因
- [x] 厂商、模型、限制、价格有文档依据
- [x] 截断值有计算依据，不是 512
- [x] 降级路径明确，不吞非 `RerankError` 异常
- [x] 数据模型字段与 S1-4 兼容
- [x] 测试可用 MockTransport 零网络
- [x] 验收包含真实 API 与人工 7/10
- [x] 无 SCHEMA/API/新依赖
- [x] 风险含“API 不可用 / 75 块仍偏小 / 合成语料局限”

## 15. 实施回填（实测）

- 日期：2026-10-20；实现按 `docs/plan/s1-5-rerank.md` 执行，用户已确认 7/10 人工验收通过。
- 语料：**75 块 / 6 个 note**（101–106）。其中 104–106 为本卡新增的 3 份合成样张（指数/对数函数笔记 7 块、导数教材页 10 块、三角/数列试卷 20 块，共 37 块）；它们是“结构真的样张”，不是真实学生数据，评测结论必须带此限定。
- 测试：`pytest -q` → **124 passed, 1 warning**（S1-1 20 + S1-2 24 + S1-3 34 + S1-4 15 + S1-5 31）。比 plan 的 21 条多 10 条边界回归：Windows GBK 控制台、响应顶层非对象、`usage.total_tokens=null`、index 越界、429 + Retry-After、4xx 不回显正文、tiktoken 加载失败可降级、非 `RerankError` 不吞、门面构造失败回退、返回条数不足。warning 为既有 `StarletteDeprecationWarning`。
- 真实四路（10 问，`scripts/retrieval_eval.py`）：

```text
vector    hit@5=10/10  MRR@5=0.900
fulltext  hit@5=9/10   MRR@5=0.720
hybrid    hit@5=10/10  MRR@5=0.920
rerank    hit@5=10/10  MRR@5=0.950
rerank fallback=0/10  avg_latency=194ms  total_cost=¥0.015630
```

- 单题候选数 21–30（取决于 fused 实际条数），每次仍只发 1 个 HTTP 请求；最长单次 tokens 3,598，未触 4,000/120,000 上限。
- 人工验收（用户确认）：**7/10 更相关**——Q1 定义域、Q2 单调性定义、Q3 定义证明、Q5 二次函数最值、Q6 分段 `f(f(-1))`、Q7 `x+1/x` 证明、Q10 利润建模；**2/10 更差**——Q4 奇偶性（笔记封面进第 1，偶函数题掉出 top5）、Q9 原点对称（第 2/4 位是封面）；**1/10 持平**——Q8 奇函数解析式（目标题仍在第 1）。刚好达到 ≥7/10 验收线。
- 结果解读：`hit@5` 已饱和，关键词命中看不出“top5 噪声”；MRR 从 0.920 提到 0.950，提升有限。Q4/Q9 说明 rerank 也会被“标题/封面型”文本骗到；论文里应如实呈现这两类失败，而不是只报 10/10。
- 与 plan/spec 的偏离：
  1. 多 10 条边界回归测试（31 条新测试 / 124 总测试），原因见上；不影响检索逻辑。
  2. 候选数不是固定 30，而是 `min(30, len(fused))`；10 题里 21–30 不等，符合“最多 30”的原意。
  3. 评测输出中的真实校名/姓名已替换为“某中学/某老师”，不改变排名与分数。
- 文件：`backend/app/ai/rerank/{client.py,__init__.py}`、`backend/app/core/config.py`、`.env.example`、`backend/app/ai/rag/retriever.py`、`backend/tests/{test_rerank,test_retriever,test_config,test_eval_script}.py`、`scripts/retrieval_eval.py`、`eval/results/s1-5-rerank-eval.txt`；无 `SCHEMA.md`/`API.md`/`requirements.txt` 改动。
- 结论：S1-5 功能验收通过，但“合成样张 + 75 块 + hit@5 饱和”是明确局限；真实材料接入后应重跑同一脚本再更新论文数字。