# S3-3 Query 改写与意图识别 — 设计 Spec

- 任务卡：`docs/AI协作开发实施计划.md` §14 S3-3
- 上游：S3-2 检索服务（`services/retrieval_service.py`）
- 下游：S3-5 问答 API（本服务由 S3-5 调用，本轮不暴露 HTTP 接口）
- 状态：设计已确认（2026-10-31），待 plan

## 1. 目标

把用户原始提问变成**可独立检索的查询**，并给出 4 类意图：

- `note_query`（查笔记）：问自己资料里记过的内容；
- `question_query`（查题）：要题、找题、问题目；
- `concept_explain`（概念解释）：问定义、性质、方法；
- `chitchat`（闲聊）：问候、感谢、与学习资料无关的对话，**不检索**。

多轮时用最近 3 轮补全指代（“那它的前提条件呢？” → “函数单调性的前提条件是什么？”）。结果做进程内缓存；LLM 失败不能拖垮问答，降级为原问题继续检索。

非目标：多查询变体/多路召回、HyDE、按意图改 scope、会话表/消息落库（S3-5）、Redis 缓存与 `llm_call_logs` 落库（S3-7）、HTTP 接口（S3-5）、Prompt 版本管理（S3-4）。

## 2. 已确认决策

1. **分层**：LLM/Prompt/严格 JSON 放 `ai/rag/query_rewriter.py`；业务编排（历史裁剪、缓存、降级）放 `services/query_rewrite.py`；遵守 AGENTS §4「AI 调用只在 ai/ 层」。
2. **历史来源**：调用方传 `history`（不含当前问题，时间升序）；S3-3 不查 `conversations/messages`，不被 S3-5 阻塞。
3. **意图用途**：只做流程分支（`chitchat` 不检索，其余三类同一套检索参数），**不按意图改 scope**。
4. **闲聊回复**：与分类/改写同一次 LLM 调用生成；失败降级为固定文案。
5. **失败降级**：LLM 超时/非 JSON/字段非法，重试 2 次后返回原问题、`intent=note_query`、`degraded=True`，检索继续。
6. **缓存**：进程内 LRU + TTL（默认 3600s / 256 条）；只缓存成功结果（不含降级）。S3-7 再统一换 Redis。
7. **验收入口**：只加 `scripts/rewrite_eval.py`，不加 HTTP 接口、不改 API.md/SCHEMA.md。

## 3. 架构与数据流

```text
S3-5（未来）: 读最近消息 → history
                    │
                    ▼
services/query_rewrite.rewrite_query(question, history)
   ├─ 裁剪最近 3 个 user 轮（每条内容截 300 字）
   ├─ 查进程缓存（key = v1 + 模型 + 问题 + 裁剪后历史）──命中──▶ RewriteResult(cache_hit=True)
   ├─ 未命中 → ai/rag/query_rewriter.rewrite_with_llm()
   │             └─ render rewrite_v1.md → LLM → 严格 JSON → Pydantic 校验 → 最多 2 次重试
   ├─ 成功 → 写缓存 → RewriteResult
   └─ 失败 → 原问题 + note_query + degraded=True（不写缓存）
                    │
                    ▼
S3-5: chitchat → 直接回 reply；其余 → retrieval_service.search_chunks(rewritten_query)
```

不改 `answer_question`、不改 `retrieval_service`、不加表/迁移、不加路由。

## 4. 数据模型

`backend/app/ai/rag/query_rewriter.py`：

```python
Intent = Literal["note_query", "question_query", "concept_explain", "chitchat"]

@dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str

class RewriteOutput(BaseModel):
    intent: Intent
    rewritten_query: str = Field(default="", max_length=500)
    is_followup: bool = False
    reply: str = Field(default="", max_length=200)

@dataclass(frozen=True)
class RewriteCall:
    output: RewriteOutput
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int

class RewriteError(Exception):
    # 只带异常类型/次数，不带 Prompt/正文；附带已发生的调用量，便于降级结果如实记账
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
```

校验规则（`RewriteOutput` model_validator）：

- `intent != "chitchat"` → `rewritten_query.strip()` 必须非空；
- `intent == "chitchat"` → `reply.strip()` 必须非空；
- 其余字段不合法由 Pydantic 直接拒绝。

`backend/app/services/query_rewrite.py`：

```python
@dataclass(frozen=True)
class RewriteResult:
    intent: Intent
    rewritten_query: str
    reply: str | None
    is_followup: bool
    degraded: bool
    cache_hit: bool
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int
    error: str | None            # 异常类型名，如 "LLMError" / "RewriteError"

def rewrite_query(
    question: str,
    *,
    history: list[HistoryTurn] | None = None,
    use_cache: bool = True,
    llm_client: LLMClient | None = None,
) -> RewriteResult: ...

def clear_cache() -> None: ...   # 测试/运维
```

## 5. AI 层

`rewrite_with_llm(question, *, history, llm_client=None, max_retries=2) -> RewriteCall`：

1. 渲染 `ai/prompts/rewrite_v1.md`（Jinja2，`StrictUndefined`；缺失/渲染失败抛 `RewriteError`）。
2. 首次调用 `client.chat(messages, temperature=0.0, max_tokens=settings.query_rewrite_max_tokens, scene="query_rewrite")`。
3. 解析 JSON（允许 ```json 围栏；取第一个 `{` 到最后一个 `}`）。
4. Pydantic 校验；失败则把“上次输出 + 校验错误摘要”追加到 messages 重试，最多 2 次。
5. 成功返回 `RewriteCall`（累计所有尝试的 tokens/cost/latency）；穷尽后抛 `RewriteError`（附累计调用量）。

Prompt 规则（`rewrite_v1.md`）：

```text
你是检索查询改写器，只输出 JSON，不要解释、不要 Markdown 围栏。
意图只能是：
- note_query：问学生自己笔记/资料里记过的内容
- question_query：要题、找题、问题目/练习题
- concept_explain：问定义、性质、方法、推导
- chitchat：问候、感谢、与学习无关的闲聊

规则：
1. 结合【最近对话】补全指代，把【当前问题】改写成脱离上下文也能检索的完整问题。
2. 只改写，不回答；不要添加资料中没有的信息。
3. 保留数学符号、公式、函数名、区间。
4. 无历史或当前问题已完整时，is_followup=false，rewritten_query 可与原问题相同。
5. chitchat 时 rewritten_query 为空串，reply 给 1–2 句轻量回复；其它意图 reply 为空串。

【最近对话】
{% for turn in history %}{{ "用户" if turn.role == "user" else "助手" }}：{{ turn.content }}
{% endfor %}
【当前问题】{{ question }}

输出 JSON：{"intent": "...", "rewritten_query": "...", "is_followup": true/false, "reply": "..."}
```

## 6. 服务层

### 6.1 入口校验

- `question.strip()` 为空 → `ValueError("question 不能为空")`；
- 去空白后长度 > 500 → `ValueError("question 过长")`；
- `history` 为 `None` 视为空列表。

### 6.2 历史裁剪

- 从后往前找第 3 个 `role=="user"` 的位置，切片到末尾；不足 3 轮则全保留。
- 每条 `content` 压空白后截 300 字；`assistant` 开头、末尾不完整轮次不特殊处理，原样保留。
- 返回按时间升序的 `list[HistoryTurn]`。

### 6.3 配置开关

`settings.query_rewrite_enabled == False`：

```python
RewriteResult(
    intent="note_query",
    rewritten_query=question.strip(),
    reply=None,
    is_followup=bool(history),
    degraded=False,
    cache_hit=False,
    llm_calls=0,
    prompt_tokens=0, completion_tokens=0, total_tokens=0,
    cost_yuan=0.0,
    latency_ms=0,
    error=None,
)
```

不读缓存、不写缓存、不调 LLM。

### 6.4 缓存

- 结构：模块级 `OrderedDict[str, _CacheEntry]`（`created_at` + `RewriteResult`）+ `threading.Lock`。
- key：`sha256(f"{REWRITE_PROMPT_VERSION}|{settings.llm_model}|{question}|{role}:{content}...")`。
- 命中且未过期：`dataclasses.replace(result, cache_hit=True, llm_calls=0, prompt_tokens=0, completion_tokens=0, total_tokens=0, cost_yuan=0.0, latency_ms=0)`；`move_to_end` 维护 LRU。
- 过期：删除后重算。
- 写入前若 `len >= query_rewrite_cache_size`，`popitem(last=False)` 淘汰最旧。
- 只写成功（`degraded=False`）结果；`use_cache=False` 时跳过读写。
- `clear_cache()` 清空；测试 autouse fixture 调用。

### 6.5 成功/降级

成功：直接映射 `RewriteCall`，`cache_hit=False`、`degraded=False`、`error=None`。

失败（捕获 `LLMError` 与 `RewriteError`，其它异常继续上抛）：

```python
RewriteResult(
    intent="note_query",
    rewritten_query=question.strip(),
    reply="我可以帮你查笔记、找题或解释概念。",
    is_followup=bool(history),
    degraded=True,
    cache_hit=False,
    llm_calls=error.llm_calls,           # RewriteError 有；LLMError 为 0
    prompt_tokens=..., completion_tokens=..., total_tokens=..., cost_yuan=...,
    latency_ms=<本次耗时>,
    error=type(exc).__name__,
)
```

`reply` 在降级时给固定文案，避免 S3-5 因 `reply=None` 无话可说；该结果不写缓存。

### 6.6 日志

`logger.info("query_rewrite_done", extra={scene, intent, is_followup, degraded, cache_hit, llm_calls, latency_ms, total_tokens, cost_yuan})`；不记问题/历史正文，不记 Key。

## 7. 配置（`core/config.py` + `.env.example`）

```dotenv
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_MAX_HISTORY_TURNS=3
QUERY_REWRITE_HISTORY_CONTENT_CHARS=300
QUERY_REWRITE_MAX_TOKENS=400
QUERY_REWRITE_CACHE_TTL_SECONDS=3600
QUERY_REWRITE_CACHE_SIZE=256
```

`Settings` 同名小写字段；`REWRITE_PROMPT_VERSION = "v1"` 为 `ai/rag/query_rewriter.py` 常量，不进环境变量。

## 8. 测试

全部 FakeLLM/FakeClient，不触库、不调外部 API。

| 文件 | 用例 |
|---|---|
| `tests/test_query_rewriter.py`（新增，10 条） | Prompt 含最近对话/当前问题；合法 JSON 解析；```json 围栏；非法 JSON 重试 3 次后 `RewriteError`；非闲聊空 `rewritten_query`、闲聊空 `reply`、未知 intent 各判失败（参数化 3 条）；传给 client 的 `scene/temperature/max_tokens` 正确；无历史不渲染空对话块；模板缺失抛错 |
| `tests/test_query_rewrite_service.py`（新增，13 条） | 空问题/超长问题 ValueError；5 轮只留最近 3 个 user 轮；单条截 300 字；成功字段映射；缓存命中不重复调用且指标归零；TTL 过期重算；不同历史不共享缓存；`use_cache=False` 不读写；LLMError 降级原问题 + `error="LLMError"`；`RewriteError` 降级并保留调用量；`enabled=false` 透传且不调 LLM；闲聊 reply 透传 |
| 既有 | 586 条保持全绿；`test_llm.py` 增 1 条 scene 日志用例（共 9）；预期全量 **610 passed** |

## 9. 验收

前置：真实 `.env`（DashScope LLM/Embedding）、Postgres 有 4 篇笔记/37 块、无 uvicorn 也可（脚本直连 DB）。

`scripts/rewrite_eval.py --user-id 18`（本库 `test1` 的 id 为 18；脚本默认 1，仅作占位）：

- 10 条固定指代追问，每条：`history=[上一轮用户问题, 上一轮助手回答（简短）]`，当前问题为“再详细解释一下，具体怎么做？”或含“它/那”的追问；
- 每问：`rewrite_query(use_cache=False)` → 打印 `intent / is_followup / rewritten_query / degraded`；
- 用 `rewritten_query` 调 `retrieval_service.search_chunks(..., top_k=3, rerank=False)`；
- 期望关键词来自 S1-5 固定问题集；top-3 任一命中内容含期望关键词记为命中；
- 汇总 hit@3，目标 **≥ 8/10**；未达标逐条打印原因，不调样本、不改判定。
- 另验：1 条“你好” → `intent=chitchat`、`reply` 非空、不检索；1 条无历史独立问题 → `is_followup=false`。

记录：脚本整段输出贴进 plan 执行记录；`llm_calls/tokens/cost` 如实记录。

### 实测（2026-10-31）

- 环境：真实 DashScope LLM + Embedding，Postgres `test1`（id=18）4 篇笔记/37 块；`--top-k 3 --user-id 18`。
- 结果：**hit@3 = 9/10，PASS**；`degraded=0/10`；tokens=3958，cost=¥0.003802；10 条均 `intent=concept_explain`、`is_followup=true`。
- 逐条改写：定义域求法；单调性定义的前提条件；单调递增证明步骤；奇偶函数图象特点；二次函数闭区间最值分类讨论；分段函数 `f(f(-1))` 求解步骤；`f(x)=x+1/x` 单调性详细证明；已知奇函数半区间解析式求另一侧的依据；图象关于原点对称的定义/充要条件/判断方法；商品定价最大利润建模步骤。
- 未命中：第 6 条改写正确（“分段函数 f(f(-1)) 的求解步骤”），但检索 top3 未召回目标块 `note 77 / chunk 11`（该块确实存在）；属检索召回问题，非改写偏移。按约定不改样本/关键词。
- 附加检查：`你好` → `intent=chitchat`、reply 非空；`函数的定义域怎么求？` → `is_followup=false`、改写保持原问题。

## 10. 已知限制

1. 缓存是进程内，多 worker/重启不共享；S3-7 换 Redis。
2. 意图分类依赖单次 LLM，可能把“查题”判成“概念解释”；不影响检索，只影响分支/文案。
3. 历史由调用方提供，S3-3 不校验历史真实性；S3-5 必须只传当前用户消息。
4. 只保留最近 3 个 user 轮，更早上下文丢失；单条截 300 字可能截断关键条件。
5. `chitchat` 判定错误会直接跳过检索；降级路径固定按 `note_query` 处理。
6. 失败调用可能已产生 token 费用，但 `LLMError` 场景拿不到 usage，只记 0；`RewriteError` 尽量带累计值。
7. 不生成多个查询变体，不做多路召回融合；检索仍是一次改写后查询。
8. 无 API/无前端，S3-5 接入前只能脚本验收。

## 11. 实施记录

- 提交：`371f33e`（AI 层）、`8c6db4e`（service）、`9f7d47b`（验收脚本）、文档提交随本文件。
- 交付：`ai/prompts/rewrite_v1.md`、`ai/rag/query_rewriter.py`、`services/query_rewrite.py`、`scripts/rewrite_eval.py`；`ai/llm/{base,openai_compat}.py` 增加可选 `scene`；`core/config.py` + `.env.example` 增加 6 个 `QUERY_REWRITE_*`。
- 测试：新增 `test_query_rewriter.py` 10 条、`test_query_rewrite_service.py` 13 条、`test_llm.py` 1 条；全量 **610 passed, 1 warning**。
- 验收：`scripts/rewrite_eval.py --user-id 18 --top-k 3` → hit@3 **9/10**、degraded 0、tokens 3958、cost ¥0.003802、PASS；闲聊/独立问题检查通过。
- 偏移：验收账号用 18（库内 `test1`），脚本默认仍为 1；未改样本/判定。第 6 条未命中为检索侧未召回 `note 77/chunk 11`，不改写逻辑。
- 边界：未新增 API/表/迁移/依赖，未改 `answer_question`、`retrieval_service`、`API.md`、`SCHEMA.md`、前端；缓存/日志落库留给 S3-7。