# S3-7 缓存 + LLM 调用日志 + 用量统计（spec）

- 任务卡：`docs/AI协作开发实施计划.md` §S3-7
- 状态：待用户确认
- 日期：2026-11-01
- 关联契约：`docs/SCHEMA.md` §8.4 / §10.14；`docs/API.md` §11；`AGENTS.md` §5、§9.2
- 用户已确认：日志范围、scene 扩展、缓存 key 语义、用量接口形状与 `done.cached`

## 1. 目标

1. 同一用户、同一规范化问题、同一 scope，24h 内第二次问答命中 Redis 缓存：跳过改写、检索、生成，响应明显更快，且不新增 `llm_call_logs`。
2. Embedding 按“模型 + 内容哈希”缓存到 Redis；缓存命中不调用厂商 API，也不写调用日志。
3. 每次 chat LLM 调用和每次 embedding 厂商调用落 `llm_call_logs`：scene/model/tokens/cost/latency/trace_id/user_id/status；写日志失败不能影响主链路。
4. 新增 `GET /api/v1/admin/usage?range=7d`，按天 × scene × model 返回 token、成本、调用数、平均延迟，并给出 totals。
5. 不改变已有 SSE 事件顺序；`done` 增补 `cached` 布尔值，旧字段保持兼容。

## 2. 非目标

- 不做语义缓存、相似问题缓存、跨用户共享答案。
- 不做笔记修改/Prompt 激活后的主动缓存失效；只靠 TTL。
- 不做 rerank 调用落库；`llm_call_logs.scene` 不增加 `rerank`。
- 不做 Redis 集群/分布式锁/缓存击穿保护；单进程同步客户端即可。
- 不做按用户筛选用量、导出报表、成本预算告警。
- 不把每条日志写进请求主事务；日志是 best-effort 旁路。

## 3. 契约变更（实现前先改契约文件）

### 3.1 SCHEMA §8.4 `llm_call_logs`

保留原有字段，明确：

| 字段 | 实现口径 |
|---|---|
| `user_id` | 从请求上下文取当前登录用户；脚本/后台无上下文时 NULL；`ON DELETE SET NULL` |
| `scene` | `qa / query_rewrite / kp_align / embed / mistake / gen / agent`（扩展后写进 CHECK） |
| `model` | 实际模型名（如 `qwen-plus`、`text-embedding-v4`） |
| `prompt_tokens` / `completion_tokens` | 成功调用填 usage；失败/中断为 NULL |
| `cost` | `NUMERIC(14,8)`，元；按 `core/config.py` 单价估算，禁止硬编码 |
| `latency_ms` | 本逻辑调用耗时（适配器内部重试包含在内） |
| `trace_id` | 请求上下文 trace_id；无上下文为 NULL |
| `status` | `success / failed`（S3-7 定稿；流式被客户端关闭按 failed 记） |

`SCHEMA §10.14` 同步扩展 scene 值集；`status` 值集补进 §10 枚举表。

### 3.2 API §11 用量接口

```http
GET /api/v1/admin/usage?range=7d
Authorization: Bearer <admin>
```

- `range`：`1d | 7d | 30d`，默认 `7d`；非法值 422/42200。
- 鉴权：`require_role("admin")`，非 admin 403/40300。
- 日期口径：UTC；`start_date` 含当天，`end_date` 为今天；`1d` 只含今天。
- 出参：

```json
{
  "code": 0,
  "message": "ok",
  "trace_id": "…",
  "data": {
    "range": "7d",
    "start_date": "2026-10-26",
    "end_date": "2026-11-01",
    "totals": {
      "calls": 12,
      "failed_calls": 0,
      "prompt_tokens": 1234,
      "completion_tokens": 567,
      "total_tokens": 1801,
      "cost_yuan": 0.00234,
      "avg_latency_ms": 1234
    },
    "items": [
      {
        "date": "2026-10-26",
        "scene": "qa",
        "model": "qwen-plus",
        "calls": 3,
        "failed_calls": 0,
        "prompt_tokens": 900,
        "completion_tokens": 300,
        "total_tokens": 1200,
        "cost_yuan": 0.0012,
        "avg_latency_ms": 1500
      }
    ]
  }
}
```

- `items` 按 `date ASC, scene ASC, model ASC`；没有数据时 `items=[]`、totals 全 0。
- `cost_yuan` 保留 8 位小数后转为 JSON number；NULL token/cost 聚合按 0。

### 3.3 API §5 `done` 事件

新增 `cached: bool`，缓存命中为 `true`，正常生成为 `false`；旧字段不变。缓存命中时：

- `tokens=0`（本次没有 LLM/embedding 调用）
- `latency_ms` 只含缓存读取、发送与落库耗时
- `refused/refusal_reason/suggestions` 取缓存中的原结果
- 仍生成新的 assistant 消息与 `message_citations`，会话历史可正常续聊

## 4. 缓存设计

### 4.1 通用 Redis 缓存层

新增 `app/core/cache.py`：

```python
class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_seconds: int) -> bool: ...
    def delete(self, key: str) -> None: ...
```

- `RedisCache`：`redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)`，懒连接。
- `get/set/delete` 捕获 Redis/网络异常，记 WARNING 并返回 miss/false；禁止把异常抛到问答主链路。
- `get_cache()` 进程内单例；测试用 `MemoryCache`（同文件提供，带 TTL）注入，不连真实 Redis。
- 配置：`CACHE_ENABLED` 总开关（默认 true）；关闭时 `get_cache()` 返回 no-op 实现。

### 4.2 QA 结果缓存

新增 `app/services/qa_cache_service.py`。

- key：`qa:v1:{user_id}:{scope_hash}:{question_hash}`
  - 规范化问题：`" ".join(question.split())`，再 SHA-256。
  - scope：`QaScopeIn.model_dump(mode="json")` 用 `json.dumps(sort_keys=True)` 后 SHA-256；`None` 也纳入。
  - **不包含会话历史**（用户确认）；多轮同问可能命中旧答案，作为已知限制写入 PROGRESS。
- value（JSON）：
  - `answer`：最终已校验/已加补充前缀的文本（拒答为 `REFUSAL_TEXT`）
  - `kind`：`rag / refused`
  - `refused`、`refusal_reason`、`suggestions`
  - `citations`：`index/note_id/chunk_id/title/heading_path/page_no/snippet/score`
  - `prompt_version`、`model`、`cached_at`
- TTL：`QA_CACHE_TTL_SECONDS=86400`。
- 命中时机：`prepare_ask` 创建/校验会话并落 user 消息后、`rewrite_query` 之前。命中直接返回带 `cached` 的 `QaPlan`，不查 Prompt、不改写、不检索。
- 写入时机：`stream_events` 成功落 assistant 消息后，写入 `rag` 或 `refused` 结果；生成失败/断连不写。
- 缓存命中仍走 `_persist_assistant`，用缓存 citations 重建 `message_citations`；assistant 的 `model/prompt_version` 取缓存值，`token_usage` 顶层为 0、`rewrite=null`。
- 缓存损坏/字段缺失：按 miss 处理并 best-effort delete，不抛错。

### 4.3 Embedding 内容缓存

新增 `app/ai/embedding/cached.py` 的 `CachedEmbeddingClient`，包装任意 `EmbeddingClient`：

- key：`embed:{model}:{dim}:{sha256(text)}`；value 为向量 JSON 数组。
- `encode(texts, on_batch=...)`：
  - 逐条查缓存，按原顺序回填；
  - 只把 miss 的文本交给 inner client；inner 返回后按序写缓存；
  - `on_batch` 只对真实厂商批次回调，tokens 仍只统计实际消耗；
  - 维度/条数校验保持原逻辑。
- TTL：`EMBEDDING_CACHE_TTL_SECONDS=604800`（7 天）。
- `get_embedding_client()` 按 `EMBEDDING_CACHE_ENABLED` 返回包装客户端；测试直接构造 inner 不受影响。
- 缓存命中不调用适配器，因此不会新增 `llm_call_logs`；缓存未命中才由适配器记 `scene=embed`。

## 5. LLM 调用日志

### 5.1 写入口

新增 `app/core/llm_log.py`：

```python
def record_llm_call(
    *, scene: str, model: str, status: str,
    prompt_tokens: int | None, completion_tokens: int | None,
    cost_yuan: float | None, latency_ms: int | None,
    user_id: int | None = None, trace_id: str | None = None,
) -> None
```

- 用 `new_session()` 独立事务插入；异常只 `logger.warning("llm_call_log_failed", exc_info=False)`，绝不回抛。
- `user_id` 默认取 `core.context` 当前用户；`trace_id` 默认取 `get_trace_id()`，无请求上下文时 NULL。
- 金额转 `Decimal(str(round(cost, 8)))`；禁止把 Prompt/回答正文写进日志。
- 新增 `set_current_user_id()`/`get_current_user_id()` 到 `core/context.py`；`api/deps.get_current_user` 登录成功后写入。

### 5.2 适配器埋点

- `OpenAICompatibleLLMClient` 增加 `log_calls: bool = False`：
  - 默认 false，避免现有单测直连适配器时访问数据库；
  - `get_llm_client()` 传 true。
  - `chat` 成功记 success；异常记 failed 后原样抛出。
  - `chat_stream` 正常结束记 success（一条逻辑调用一行）；异常或 `GeneratorExit` 记 failed 后原样抛出/返回。
- `OpenAICompatibleEmbeddingClient` 增加 `log_calls: bool = False` 和 `price_per_million`：
  - `get_embedding_client()` 传 true + `settings.embedding_price_per_million`；
  - 每个厂商批次成功/失败各一行 `scene=embed`。
- `ai/align/extractor.py` 调用改为 `scene="kp_align"`；`answerer` 保持 `qa`；`query_rewriter` 保持 `query_rewrite`。
- 流式调用被客户端取消时没有最终 usage，记 `failed`、token/cost 为 NULL；文档记录这一口径。

## 6. 用量统计

新增 `app/services/usage_service.py`：

```python
def get_usage(session: Session, *, range_key: str) -> UsageReport
```

- 解析 `range_key` → 天数；按 UTC 日历日计算 `start_date/end_date`。
- 单条 SQL 聚合：`date(created_at), scene, model`，`count(*)`、`sum(...)`、`avg(latency_ms)`、`sum(case status='failed')`；禁止 N+1。
- 使用 `func.coalesce(..., 0)`；`Decimal` 转 float 保留 8 位。
- 排序 `date, scene, model`；totals 由 items 在 SQL 侧或 Python 侧汇总（统一用一次查询结果）。
- 用量接口路由只做参数校验、调用 service、套 `Envelope`；不写 SQL。

## 7. 数据迁移

新增 `backend/alembic/versions/0008_s3_7_llm_call_logs.py`：

- 创建 `llm_call_logs`，字段按 SCHEMA §8.4；
- 约束：`ck_llm_call_logs_scene`、`ck_llm_call_logs_status`；
- 索引：`ix_llm_call_logs_user_id_created_at(user_id, created_at)`、`ix_llm_call_logs_scene(scene)`、`ix_llm_call_logs_trace_id(trace_id)`；
- `downgrade()` 对称删除索引和表；
- 不修改 0007 及更早迁移。

## 8. 配置

`core/config.py` 与 `.env.example` 新增：

```text
CACHE_ENABLED=true
QA_CACHE_ENABLED=true
QA_CACHE_TTL_SECONDS=86400
EMBEDDING_CACHE_ENABLED=true
EMBEDDING_CACHE_TTL_SECONDS=604800
```

不新增第三方依赖（`redis==5.3.1` 已在 requirements）。

## 9. 测试计划（全部 mock/内存，不触真实外部）

1. `test_cache.py`：MemoryCache TTL、RedisCache 异常 fail-open（fake client）、key 生成确定性。
2. `test_qa_cache.py`：payload 往返、规范化问题/scope 隔离、损坏 payload 当 miss。
3. `test_embedding_cached.py`：全命中不调 inner、部分命中只编码 miss、顺序保持、TTL 使用。
4. `test_llm_call_log.py`：成功/失败字段、Decimal 金额、异常不抛出；上下文字段。
5. `test_llm.py` / `test_llm_stream.py`：`log_calls=True` 时成功/失败各记一次；默认 false 不写。
6. `test_embedding_client.py`：批次成功/失败日志；默认不写。
7. `test_qa_service.py`：缓存命中跳过 rewrite/prepare、`cached=true`、tokens=0、citations 重建；缓存 miss 正常写；生成失败不写缓存。
8. `test_usage_service.py`：range 解析、按天/场景/模型聚合、空数据、NULL 处理。
9. `test_usage_api.py`：admin 200、非 admin 403、非法 range 422、响应结构。
10. `test_qa_api.py`：`done.cached` 默认 false 与 true 两种。

## 10. 真实验收（必须贴实测输出）

1. `alembic upgrade head`，确认 `llm_call_logs` 存在。
2. 用真实用户（`test1` id=18）连续问同一问题两次：
   - 第一次记录耗时、`llm_call_logs` 行数；
   - 第二次记录耗时、行数，要求无新增且明显更快；
   - 检查第二次 SSE `done.cached=true`、`tokens=0`，assistant 消息与 citations 仍落库。
3. 用 admin 调 `GET /api/v1/admin/usage?range=7d`，确认 items 有按天 token/cost，totals 正确；非法 range 422。
4. Embedding 缓存抽查：同一 query 连续检索两次，第二次无新增 `scene=embed` 日志。
5. 全量 pytest 无失败；新测试数、真实数字写回 PROGRESS/验收记录。

## 11. 决策记录

- **D-041（拟）**：QA 缓存命中在改写前发生，因此缓存 key 不含历史；命中也要落新消息，保证会话可续。
- 缓存/日志均为旁路：Redis 或 DB 故障只 WARNING，不影响问答；用量接口 DB 故障正常 500。
- 成本估算统一在适配器内按配置单价计算，usage 只聚合，不再二次换算。
- `llm_call_logs` 不存 Prompt/回答正文，避免学生数据与 prompt 泄漏。

## 12. 风险与限制

- 缓存忽略会话历史，多轮同问可能拿到旧答案；24h 内不随笔记/Prompt 变化失效。
- 缓存命中仍会写 assistant 消息与 citations，DB 写入失败会回 error（与正常生成一致）。
- 日志写库在请求路径内，增加约一次 DB 往返；DB 慢时可能拖慢响应，设为 best-effort 后仍可能超时。
- 流式取消/失败的 usage 未知，只能记 NULL，成本统计偏低。
- 缓存内容包含用户答案与引用片段，Redis 需按用户隔离 key；当前不加密。
- 用量按 UTC 日切，和用户本地时区可能差一天。

## 13. 实施记录（2026-11-02）

- 交付与 §1–§8 一致：`0008_s3_7`、`LLMCallLog`、`core/cache.py`、`services/qa_cache_service.py`、`ai/embedding/cached.py`、`core/llm_log.py`、适配器埋点、`services/usage_service.py`、`schemas/usage.py`、`GET /api/v1/admin/usage`、`qa_service` 缓存分支、`scripts/cache_eval.py`。
- 测试：新增 33 条，基线 686 → **719 passed, 1 warning**。偏差：缓存层 4 条（spec 估 3）；`done.cached` 的 true/false 由 `test_qa_cache_flow.py` 覆盖，未单独加 `test_qa_api.py` 用例。
- 真实验收：第一问 36.468s / 4251 tokens / 新增 4 条日志 / 缓存已写入；第二问 0.014s / 0 tokens / 0 条新增日志 / `cached=true` / 答案一致且落新消息。真实 admin 用量接口 200，累计 `totals.calls=8`、`total_tokens=8433`、`cost_yuan=0.010392`。
- 限制与 §12 一致；额外记录：缓存 key 不含 Prompt/模型版本，变更后需清 `qa:v1:*`；Redis 故障时连接超时为 0.5s。