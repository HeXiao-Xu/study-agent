# S3-5 问答 API（SSE 流式）+ 会话/消息/引用落库 Spec

> 任务卡：`docs/AI协作开发实施计划.md` S3-5。产出：`api/v1/qa.py`、`services/qa_service.py`。
> 状态：设计已确认（2026-10-31），待 spec 审阅。

## 1. 目标

- 提供 `POST /api/v1/qa/ask`：先落 user 消息，再逐 token 推送 `meta/delta/done`；正常结束落 assistant 消息与被引用 citations。
- 提供 `GET /api/v1/qa/messages/{id}/citations`：本人消息的引用列表。
- 复用 S3-2 检索、S3-3 改写、S3-4 Prompt 版本；本轮只做会话/消息/引用表与流式链路。
- 客户端断开时关闭上游 LLM 流；不落半截 assistant。

非目标：会话列表/重命名/删除、前端问答页（S3-8）、S3-6 引用校验重试、S3-7 缓存/调用日志、限流（429 暂不实现）、题目/知识点引用（`question_id` 仅保留列）。

## 2. 已确认决策

1. **实现路线**：LLM 层加真实 `chat_stream`；answerer 抽出 `prepare_answer` + `stream_answer`；`qa_service` 编排，不复制检索/拒答规则。
2. **conversation_id**：JSON 中为十进制字符串（按 API.md），服务层解析为 BIGINT；事件里也返回字符串。message_id 用整数。
3. **scope**：新会话写入 `conversations.scope_json`；已有会话不传 scope 时继承库中值，显式传入则本次覆盖、不回写库。
4. **断连**：保留已落 user 消息，丢弃 assistant（不写半截回答）；关闭上游生成器。
5. **流中错误**：新增 `event: error`（`{code,message}`）后关闭；流开始前的错误仍走普通 JSON 错误壳。
6. **会话归属**：会话不存在或不属于当前学生统一 404/40400，不泄露存在性；仅 student 可访问。
7. **引用校验**：S3-5 流式输出不重试；结束后只把合法 `[n]` 对应的 citation 落库；无合法引用就落空 citations。S3-6 再做校验/标注。
8. **数据/接口边界**：只新增三张表、两个接口；不新增依赖/配置/Redis；不改检索/改写/Prompt 版本逻辑。

## 3. 架构与数据流

```
POST /api/v1/qa/ask
  → require_role("student")；QaAskRequest 校验
  → qa_service.prepare_ask(session, user_id, question, scope, conversation_id)
       ├ 找/建 conversation（标题=问题前 50 字；新会话存 scope）
       ├ 校验归属；已有会话解析 scope（请求覆盖或继承）
       ├ 读最近 6 条消息 → HistoryTurn（升序，排除当前问题）
       ├ 先落 user 消息并 commit
       ├ rewrite_query(question, history)
       │    ├ chitchat → kind=chitchat，reply 直接用
       │    └ 其余 → kind=rag；prepare_answer(
       │           question=原文, retrieval_query=改写后问题, scope=...)
       ├ refused（无上下文/低分）→ kind=refused
       ├ 取 active Prompt → qa/vN，渲染进 prepared.prompt
       └ 批量查 note 标题 → meta citations
  → StreamingResponse(qa_service.stream_events(plan))
       event: meta    {conversation_id,user_message_id,citations[]}
       event: delta   {text}
       event: done    {message_id,conversation_id,tokens,latency_ms,refused}
       结束：assistant 消息 + 被引用 citations 落库
```

- `prepare_ask` 在返回响应前完成改写/检索/上下文/Prompt，因此 4xx/5xx 还能走 JSON；流开始后只发 SSE。
- 流式生成在同步生成器里执行，`StreamingResponse` 在线程池迭代；不跨整个流持有请求 `Session`，最终落库用 `new_session()`。
- `message_citations` 只在流正常结束后写；断连/错误不写 assistant。

## 4. 数据模型（迁移 `0007_s3_5`）

### 4.1 conversations（SCHEMA §7.1）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| user_id | BIGINT | 否 | — | FK users.id |
| title | TEXT | 是 | — | 新会话取问题前 50 字 |
| scope_json | JSONB | 是 | — | `{subject_id?,folder?,start_date?,end_date?}` |
| created_at | TIMESTAMPTZ | 否 | now() | |

索引：`ix_conversations_user_id(user_id)`。

### 4.2 messages（SCHEMA §7.2）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| conversation_id | BIGINT | 否 | — | FK conversations.id，ON DELETE CASCADE |
| role | TEXT | 否 | — | `user/assistant/system`，TEXT+CHECK |
| content_md | TEXT | 否 | — | 消息 Markdown |
| token_usage | JSONB | 是 | — | 见 §4.4 |
| latency_ms | INTEGER | 是 | — | 本次生成总耗时 |
| model | TEXT | 是 | — | LLM 模型 |
| prompt_version | TEXT | 是 | — | RAG 为 `qa/vN`；chitchat 为 NULL |
| created_at | TIMESTAMPTZ | 否 | now() | |

索引：`ix_messages_conversation_id(conversation_id)`；CHECK `ck_messages_role`。

### 4.3 message_citations（SCHEMA §7.3）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT IDENTITY | 否 | 自增 | PK |
| message_id | BIGINT | 否 | — | FK messages.id，ON DELETE CASCADE |
| chunk_id | BIGINT | 是 | — | 引用切片 |
| question_id | BIGINT | 是 | — | 预留，本轮 NULL |
| note_id | BIGINT | 是 | — | 引用笔记 |
| score | NUMERIC | 是 | — | 重排分 |
| snippet | TEXT | 是 | — | 片段（≤200 字） |
| page_no | INTEGER | 是 | — | 页码 |
| bbox_json | JSONB | 是 | — | 预留，本轮 NULL |
| rank | INTEGER | 是 | — | 上下文编号 1..N |

索引：`ix_message_citations_message_id(message_id)`。

### 4.4 token_usage JSON

```json
{
  "prompt_tokens": 685,
  "completion_tokens": 862,
  "total_tokens": 1547,
  "cost_yuan": 0.002272,
  "rewrite": {
    "prompt_tokens": 300,
    "completion_tokens": 40,
    "total_tokens": 340,
    "cost_yuan": 0.0003,
    "degraded": false,
    "cache_hit": false
  }
}
```

- assistant 消息的总计 = 回答 LLM + 改写 LLM；无改写时 `rewrite=null`。
- `done.tokens` = `token_usage.total_tokens + rewrite.total_tokens`（本轮实际消耗总量）。
- `done.latency_ms` = 从 `prepare_ask` 开始到 done 的总耗时（含改写/检索/流式）。

## 5. AI 层

### 5.1 `LLMClient.chat_stream`

```python
@dataclass(frozen=True)
class LLMStreamChunk:
    text: str = ""
    response: LLMResponse | None = None

class LLMClient(ABC):
    def chat_stream(
        self, messages: list[LLMMessage], *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> Iterator[LLMStreamChunk]:
        # 默认实现：一次 chat，yield 完整 text，再 yield response
```

- `OpenAICompatibleLLMClient` 覆盖：`stream=true`、`stream_options={"include_usage": true}`，逐行解析 `data:`；`[DONE]` 结束。
- 首个 delta 前可重试连接/429/5xx；已输出 delta 后不重试，抛 `LLMError`。
- usage 优先取末端 `usage`；缺失时用 tiktoken 估算 prompt/completion 并算 cost。
- 关闭生成器/断连时退出 `httpx` stream 上下文；不吞 `GeneratorExit`；错误日志不带正文/Key。

### 5.2 answerer

```python
@dataclass(frozen=True)
class PreparedAnswer:
    retrieval: RetrievalResult
    built: BuiltContext
    prompt: str
    refused: AnswerResult | None
    retrieval_ms: int
    top_score: float | None
    degraded: bool

def prepare_answer(
    session, question, *, user_id, top_k=20, threshold=None,
    embedding_client=None, rerank_client=None,
    scope: RetrievalScope | None = None,
    retrieval_query: str | None = None,
    prompt_template: str | None = None,
) -> PreparedAnswer

@dataclass(frozen=True)
class AnswerChunk:
    text: str = ""
    response: LLMResponse | None = None

def stream_answer(
    prepared: PreparedAnswer, *, llm_client: LLMClient | None = None
) -> Iterator[AnswerChunk]
```

- `question` 只用于 Prompt；`retrieval_query` 默认 `question`，追问用改写结果检索。
- `prepare_answer` 保留原阈值/拒答/上下文/Prompt 行为；`answer_question` 改为调用它再走原引用校验/一次重试，既有测试不变。
- `stream_answer` 不重试引用；空流由 qa_service 按拒答处理。

## 6. qa_service

```python
@dataclass(frozen=True)
class QaPlan:
    user_id: int
    conversation_id: int
    user_message_id: int
    question: str
    kind: Literal["rag", "chitchat", "refused"]
    prepared: PreparedAnswer | None
    chitchat_reply: str | None
    citations: list[QaCitationMeta]
    prompt_version: str | None
    rewrite: RewriteResult | None
    started_at: float

def prepare_ask(
    session, *, user_id: int, question: str,
    scope: QaScopeIn | None, conversation_id: int | None,
) -> QaPlan

def stream_events(
    plan: QaPlan, *,
    llm_client: LLMClient | None = None,
    session_factory: Callable[[], Session] = new_session,
) -> Iterator[QaStreamEvent]

def get_message_citations(
    session, *, user_id: int, message_id: int,
) -> list[MessageCitation]
```

- `QaStreamEvent(event, data)`；`stream_events` 只产出事件，不拼 SSE 文本（路由负责 `event:`/`data:` 格式）。
- `prepare_ask` 事务：建会话 + 落 user 消息一次 commit；改写/检索失败向上抛（user 消息保留）。
- 会话归属：`Conversation.id + user_id` 同查；不存在/越权 `NotFoundError`。
- 历史：最近 6 条（`id DESC` 取再反转），只取 `user/assistant`，转 `HistoryTurn`；不含当前问题。
- chitchat：不检索、不取 QA Prompt；reply 为空时用 `FALLBACK_REPLY`；落 assistant，`prompt_version=None`。
- refused：不调 LLM，推固定 `REFUSAL_TEXT`，落 assistant，`refused=true`。
- RAG：流式累计文本；结束后 `extract_citation_indices` 过滤 `1..len(built.items)`，只落合法 citation；无合法引用落空列表。
- 落 assistant 后再发 done；落库失败发 error，不伪造 done。
- 断连（`GeneratorExit`/取消）：关闭上游生成器，不落 assistant；user 消息保留；不向已断开客户端写 error。

## 7. API

### 7.1 POST `/api/v1/qa/ask`

- 权限：`student`；teacher/parent/admin 403/40300；匿名 401/40100。
- 请求：

```json
{
  "question": "错位相减法怎么用",
  "scope": {"subject_id": 7, "folder": "函数"},
  "conversation_id": "12"
}
```

- `question` 1–500 字，strip 后非空；`scope` 只允许 `subject_id/folder/start_date/end_date`（extra forbid，日期范围校验）；`conversation_id` 可选，`^[1-9][0-9]{0,18}$`，解析成 int。
- 响应 `text/event-stream`，headers：`Cache-Control: no-cache`、`X-Accel-Buffering: no`。
- 事件（data 为单行 JSON，UTF-8）：

```text
event: meta
data: {"conversation_id":"12","user_message_id":30,"citations":[{"index":1,"note_id":55,"chunk_id":101,"title":"数列笔记","heading_path":"数列/错位相减法","page_no":null,"snippet":"..."}]}

event: delta
data: {"text":"错位相减法"}

event: done
data: {"message_id":31,"conversation_id":"12","tokens":1547,"latency_ms":21000,"refused":false}
```

- chitchat/refused 也先发 meta（citations 为空），再 delta（全文），再 done。
- 流中错误：

```text
event: error
data: {"code":50000,"message":"生成失败"}
```

- 流前错误：普通 JSON 错误壳；会话不存在/越权 404/40400；参数 422/42200；无 active Prompt 500/50000。

### 7.2 GET `/api/v1/qa/messages/{id}/citations`

- 权限：student；只允许本人消息（join conversations.user_id）。
- 出参：`Envelope[list[CitationRecordOut]]`，按 `rank ASC, id ASC`。
- `CitationRecordOut`：`id/message_id/chunk_id/note_id/question_id/score/snippet/page_no/bbox_json/rank`（表字段；不含 title/heading_path）。
- 不存在/越权：404/40400「消息不存在」。

## 8. 错误与边界

| 场景 | 行为 |
|---|---|
| conversation_id 非法格式 | 422/42200 |
| conversation 不存在/他人 | 404/40400 |
| scope 非法/日期倒置 | 422/42200 |
| 无 active Prompt | 流前 500/50000 |
| 检索/Embedding 失败 | 流前 500/50000；user 消息保留 |
| LLM 流中失败 | `event: error`，不落 assistant |
| 客户端断开 | 关闭上游，不落 assistant |
| 空回答 | 落固定拒答，done.refused=true |
| 无合法引用 | 回答照常，citations 空；S3-6 处理 |
| 429 | 本轮不实现限流，不返回 429 |

## 9. 测试

| 文件 | 约条数 | 覆盖 |
|---|---|---|
| `test_qa_models.py` | 3 | 三表字段/FK/CHECK/索引 |
| `test_llm_stream.py` | 5 | 默认降级、SSE 解析、usage 回退、首 delta 前重试、关闭 |
| `test_answerer.py`（改） | +3 | prepare 拒答/scope/retrieval_query；stream 累积/最终响应 |
| `test_qa_service.py` | 13 | 新建会话/scope 继承覆盖/越权 404/历史/改写 chitchat/refused/RAG 落库/citations/断连 |
| `test_qa_api.py` | 6 | SSE 帧/鉴权/参数/404/citations 200/404 |
| 既有 | 636 保持全绿 | 预计 **666 passed, 1 warning** |

外部 LLM/DB 全部 fake 或注入替身；真实调用只放验收。

## 10. 验收

1. `alembic upgrade head` → `0007_s3_5 (head)`；三表存在、CHECK/FK/索引正确。
2. 全量 `pytest -q` 666 绿。
3. 启动后端，用 user 18 的 token：
   ```bash
   curl -N -X POST http://127.0.0.1:8000/api/v1/qa/ask \
     -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
     -d '{"question":"错位相减法怎么用"}'
   ```
   看到 `meta` → 多个 `delta` → `done`；记录 conversation_id/message_id。
4. DB 确认 `messages` 有 user+assistant，`message_citations` 行数与回答引用一致。
5. 用同一 conversation_id 追问（如“那它的前提条件呢？”），确认走历史且仍返回 SSE；`messages` 增 2 行。
6. `GET /api/v1/qa/messages/{id}/citations` 返回引用；他人/不存在 404。
7. `curl --max-time 3` 中断一次，DB 无该轮 assistant；日志显示上游关闭；user 消息保留。
8. `deploy/README.md` 写明 Nginx `proxy_buffering off`、`proxy_read_timeout`、`X-Accel-Buffering`。

## 11. 已知限制

1. 只有 ask/citations，没有会话列表/重命名/删除（S3-8）。
2. 流式不做引用校验重试；无合法引用时回答仍输出（S3-6）。
3. 流前失败保留 user 消息，重试会产生重复 user 消息。
4. 限流 429 未实现；断连只保证关闭上游/不落 assistant，不保证计费停止。
5. 事件里 `error` 为新增事件，前端/S3-8 需识别。
6. 每轮多一次会话/消息查询与 Prompt 查询；无缓存（S3-7）。
7. `message_citations` 不存 title/heading_path，GET 只返回表字段。
8. 长会话只取最近 6 条做改写；更早条件可能丢。

## 12. 实施记录

- 2026-10-31 内联执行，7 个 Task 全部完成；新增 30 条测试，全量 **666 passed, 1 warning**。
- 迁移 `0007_s3_5` 已应用到本地 Postgres；三表、CHECK/FK/索引与 §7 一致。
- 真实验收：首问 meta 1 / delta 181 / done 1、24.480s、`done.tokens=1949`；DB assistant 落库 + 4 条 citations；追问 3.688s；chitchat 1.224s；不存在会话 404。
- 断连初版用同步生成器，uvicorn 取消时不会主动 `close()` 上游，日志也没有 `qa_stream_disconnected`；改为 async 路由 + `run_in_threadpool(next, ...)` + `finally: events.close()` 后，`curl --max-time 3` 中断能触发日志，DB 只留 user、无 assistant，上游不再写完成日志。
- 与 plan 的偏差：`PreparedAnswer.built` 使用 `BuiltContext | None` 类型；DECISIONS 按实际最大编号用 **D-039**（plan 原写 D-041）。