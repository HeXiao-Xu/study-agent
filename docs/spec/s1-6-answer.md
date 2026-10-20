# S1-6 带引用的回答生成 + 拒答 Spec

> 对应任务卡：`docs/AI协作开发实施计划.md` §S1-6（第 450–471 行）
> 状态：待用户评审
> 前置：S1-5 Rerank 已提交（`cf7e9fe`）；S1-4 `retrieval_eval.py` 可复跑

## 1. 目标

在命令行跑通：

```text
提问 → 混合检索 → Rerank → 上下文组装 → LLM 带引用回答 → 引用校验 → 无依据拒答
```

本卡只做单轮、单用户的 CLI 验证链路，不做 API/SSE/多轮对话。目标是拿到第一版真实可演示结果，并为 S1-7 的 20–30 条自测集提供可复用的 answerer。

## 2. 范围

### 2.1 做

1. LLM 适配器：OpenAI 兼容 `/chat/completions`，默认 DashScope `qwen-plus`。
2. 上下文组装：去重、按 rerank 分排序、4,000 token 预算内截断、编号 `[1]..[n]`。
3. Prompt 模板：`backend/app/ai/prompts/qa_v1.md`，Jinja2 渲染。
4. Answerer：调用 LLM、解析并校验引用、非法引用重试一次、低分拒答。
5. CLI：`scripts/ask.py` 单问与交互式问答，打印答案、引用来源、token、耗时、费用。
6. 阈值小校准：10 个应答题 + 5 个应拒题，只跑检索/rerank，不调用 LLM；完整校准留 S1-7。
7. 配置、`.env.example`、`requirements.txt`、测试、PROGRESS/DECISIONS。

### 2.2 不做

- 不建 `notes` / `files` 表，不补笔记标题、文件名；引用只显示 `note_id`、`source_file_id`、`page_no`、`heading_path`、片段。
- 不做 `POST /qa/ask`、SSE、流式输出、多轮会话、会话历史。
- 不做 query 改写、缓存、`llm_call_logs` 落库（S3-7）。
- 不做完整 20 个应答题 + 10 个应拒题的正式校准（S1-7）。
- 不引入 `openai` SDK，不引入本地 LLM。
- 不改 `docs/API.md`、`docs/SCHEMA.md`；不改已有 Alembic 迁移。

## 3. 现状与约束

### 3.1 已有能力

- `retrieve_hybrid_reranked()` 返回 `RetrievalResult`：
  - `reranked`：最多 6 条，已按 `rerank_score` 降序；
  - `fused`：完整 RRF 结果；
  - `rerank_info`：`fallback`、`model`、`tokens`、`latency_ms`、`cost_yuan`。
- `RetrievedChunk` 已有 `chunk_id`、`note_id`、`chunk_index`、`content`、`heading_path`、`page_no`、`chunk_type`、`rerank_score`。
- `NoteChunk` 表有 `source_file_id`，但 `RetrievedChunk` 尚未暴露；本卡补一个只读字段。
- 现有依赖有 `httpx`、`jinja2 3.1.6`（已随 FastAPI 安装）、`tiktoken`；`backend/requirements.txt` 尚未显式声明 Jinja2。
- 本地 `.env` 的 `LLM_API_KEY`、`LLM_BASE_URL` 为空；`DASHSCOPE_API_KEY` 非空。

### 3.2 数据层的限制

`notes` / `files` 表到 S2-1 才建，因此引用无法显示“笔记标题/文件名”。本卡明确降级为：

```text
笔记 #101 / 文件 #12 / 第 3 页 / 章节：函数/单调性
```

没有 `page_no` 时显示“页码未知”，没有 `source_file_id` 时显示“文件未知”，不伪造。

### 3.3 语言/模型

- 默认模型：`qwen-plus`（DashScope 北京区）。
- 默认 Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`。
- `LLM_API_KEY` 为空时回退 `DASHSCOPE_API_KEY`，与 S1-3/S1-5 的 Key 处理一致。
- 温度 `0.3`，最大输出 `1200` token；单轮，不启用多轮改写。
- 价格按北京区 `qwen-plus` 输入 `0.8 元/百万 token`、输出 `2.0 元/百万 token` 估算；价格只用于展示/统计，写成配置项，不参与逻辑判断。

### 3.4 语料缺口与补充

当前语料 75 块 / 6 note，但任务卡验收问题“错位相减法”在库内 **0 命中**：

```sql
select count(*) from note_chunks where content like '%错位相减%';  -- 0
```

为了让第一条真实验收能证明“带引用回答”，本卡补一份**合成样张**：

- 路径：`E:\BiShe-AIStudy\测试数据\高中数学笔记-数列求和错位相减.docx`（仓库外，不提交）
- 内容：适用条件、错位相减步骤、例题、易错点、总结口诀
- 入库：`note_id=107`、`user_id=1`、`source_file_id=107`，实测 8 块
- 性质：合成样张，不是真实学生数据；验收输出必须带此限定
- 这条语料只用于 S1-6 验收，不改变 S1-5 的 75 块评测结论；补后全库 83 块 / 7 note，如重跑 S1-5 四路，需单独记录 83 块新数字，不能混用

## 4. 设计决策

### 4.1 LLM 适配器用 httpx，不用 openai SDK

任务卡写的是“OpenAI 兼容 SDK”，但当前项目没有 `openai` 依赖，S1-3 embedding 已采用 httpx 手写适配器。为了保持重试、超时、日志、错误体不落库等行为可控，本卡沿用同一模式；用户已确认不引入 `openai`。

### 4.2 Prompt 用 Jinja2，存文件

Prompt 存在 `backend/app/ai/prompts/qa_v1.md`，用 `jinja2.Environment` + `StrictUndefined` 渲染，禁止在 Python 里手写长 Prompt。任务卡的 `prompts/qa_v1.md` 在本仓库落到 `backend/app/ai/prompts/`（与 AGENTS §3 目录约定一致）。

### 4.3 单轮、单 user_id

本卡 CLI 接受 `--user-id`，默认 1；不做 scope、多用户、多轮。S1-7 复用 answerer 时也只传单用户。

### 4.4 引用失败宁可拒答

引用是可溯源问答的核心。非法引用或没有引用时先重试一次；重试后仍不合法，返回固定拒答，不返回“看起来有答案但没有依据”的文本。这个选择比“删掉非法编号继续返回”更严格，符合方案“宁可拒答也不要瞎编”。

### 4.5 rerank 失败时不按 τ 拒答

τ 依赖 rerank 分数。如果 `rerank_info.fallback=True` 或所有 `rerank_score` 为 `None`，没有可信分数可比，此时：

- 不因阈值拒答；
- 用 RRF 顺序的 top6 继续组装/回答；
- `AnswerResult.degraded=True`；
- 日志记录 `rerank_fallback=True`。

理由：rerank 是加分项，不能把“rerank 网络失败”误判成“资料里没有”。如果上下文也为空，仍然拒答。

### 4.6 阈值 0.45（小校准后定稿）

默认 `QA_REFUSE_THRESHOLD=0.45`。2026-10-20 用 10 个应答题 + 5 个应拒题实测：

- 应答题 top1 最低 `0.4586`
- 应拒题 top1 最高 `0.4347`
- 间隔中点 `0.4467`；取整为 `0.45`

原计划的 `0.35` 无法分开（“今天北京天气”top1=`0.3780`，会被误送 LLM）。这不是硬编码校准结果：τ 仍是配置项，完整 20+10 在 S1-7 复核。

## 5. 架构与文件

```text
backend/app/ai/
├── llm/
│   ├── __init__.py          # 门面 get_llm_client()
│   ├── base.py              # LLMClient / LLMMessage / LLMResponse
│   ├── errors.py            # LLMError
│   └── openai_compat.py     # DashScope/OpenAI 兼容 HTTP 适配器
├── prompts/
│   └── qa_v1.md             # Jinja2 模板
└── rag/
    ├── prompt_builder.py    # build_context() / render_prompt()
    └── answerer.py          # answer_question() / AnswerResult

scripts/
├── ask.py                   # CLI
└── calibrate_refusal.py     # 15 题小校准，不调 LLM
```

### 5.1 `backend/app/ai/llm/base.py`

```python
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]

@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str

@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0

class LLMClient(ABC):
    model: str
    usage_tokens: int
    request_count: int

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        ...
```

### 5.2 `backend/app/ai/llm/errors.py`

```python
class LLMError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "openai_compat",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None: ...
```

错误信息不得包含 API Key、Prompt、上下文正文或厂商响应正文。

### 5.3 `backend/app/ai/llm/openai_compat.py`

```python
class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen-plus",
        timeout: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 1200,
        price_input_per_million: float = 0.8,
        price_output_per_million: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None: ...

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...
```

约定：

- endpoint：`{base_url.rstrip('/')}/chat/completions`。
- payload：
  ```json
  {
    "model": "qwen-plus",
    "messages": [{"role": "user", "content": "..."}],
    "temperature": 0.3,
    "max_tokens": 1200
  }
  ```
- Header：`Authorization: Bearer <key>`。
- 成功条件：HTTP `200 <= status < 300`；3xx 不当成功。
- 重试：`429/500/502/503/504` 与网络异常，最多 `max_retries` 次；4xx 不重试。
- 超时：`httpx.Timeout(timeout)`；网络异常抛 `LLMError(retryable=True)`。
- 响应解析：
  - `choices[0].message.content` 必须是非空字符串；
  - `usage.prompt_tokens` / `completion_tokens` 缺失或非法按 0；
  - `total_tokens` 缺失时用 prompt + completion；
  - 费用 = `prompt_tokens * input_price / 1e6 + completion_tokens * output_price / 1e6`；
  - 非法 JSON、空 choices、空 content → `LLMError(retryable=False)`。
- 错误信息只保留状态码/异常类型，不拼 `response.text`。
- `close()` 关闭 `httpx.Client`；进程级 `get_llm_client()` 用 `lru_cache`，CLI 退出时由进程回收，不额外做生命周期 hook。

### 5.4 `backend/app/ai/llm/__init__.py`

```python
@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        price_input_per_million=settings.llm_price_input_per_million,
        price_output_per_million=settings.llm_price_output_per_million,
    )
```

Key 为空时构造阶段抛 `LLMError`，CLI 明确报错；不在这里返回假回答。

## 6. 上下文组装

### 6.1 数据模型

在 `backend/app/ai/rag/prompt_builder.py`：

```python
CONTEXT_MAX_TOKENS = 4000

@dataclass(frozen=True)
class Citation:
    index: int
    note_id: int
    chunk_id: int
    source_file_id: int | None
    heading_path: str | None
    page_no: int | None
    snippet: str
    rerank_score: float | None

@dataclass(frozen=True)
class ContextItem:
    citation: Citation
    content: str
    tokens: int

@dataclass(frozen=True)
class BuiltContext:
    text: str
    items: list[ContextItem]
    tokens: int
    truncated: bool

def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int = CONTEXT_MAX_TOKENS,
) -> BuiltContext: ...
```

`RetrievedChunk` 增加字段：

```python
source_file_id: int | None = None
```

`_to_chunk()` 从 `NoteChunk.source_file_id` 填充；S1-4 既有断言不变。

### 6.2 排序与去重

1. 按 `rerank_score` 降序；`None` 视为没有分数，统一排在后面。
2. 分数相同时保留原 `reranked`/`fused` 顺序（稳定排序）。
3. 按 `chunk_id` 去重；保留排序后第一个（最高分）。
4. 如果全部 `rerank_score` 为 `None`，保持传入顺序，不伪造分数。

### 6.3 格式

每条：

```text
[1] 来源：笔记 #101 / 文件 #12 / 第 3 页 / 章节：函数/单调性
<正文>
```

- `source_file_id` 为空 → `文件未知`
- `page_no` 为空 → `页码未知`
- `heading_path` 为空 → `章节未标注`
- 正文不截断 Markdown/LaTeX，不转义（纯文本 Prompt）。

### 6.4 Token 预算

- 用 `tiktoken.get_encoding("cl100k_base")` 计数；与 S1-2 的预算口径一致。
- 每条先计 header，再计正文；总预算 `max_tokens` 包含 header。
- 如果当前条目完整放不下：
  - 剩余预算足够放 header + 至少 20 token 正文时，截断正文到剩余预算，`truncated=True`，停止追加后续条目；
  - 否则停止，不加入该条。
- 第一个条目都放不下时返回空 `BuiltContext`，由 answerer 按 `no_context` 拒答。
- `BuiltContext.tokens` 为最终 `text` 的 tiktoken 计数；`items` 只包含实际加入的条目。
- `Citation.snippet` 取实际加入正文的前 200 字符；CLI 用它展示片段。

### 6.5 Prompt 渲染

```python
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa_v1.md"

def render_prompt(
    context: str,
    question: str,
    *,
    template_path: Path | None = None,
) -> str: ...
```

- `jinja2.Environment(loader=FileSystemLoader(...), undefined=StrictUndefined, autoescape=False)`。
- 变量：`context`、`question`。
- 模板缺失/渲染失败 → `PromptTemplateError`（含路径，不含正文）。
- 本卡用一条 **user message** 发送渲染后的完整 Prompt；不拆 system/user，避免引入额外协议层。

### 6.6 Prompt 模板 `qa_v1.md`

内容采用《完整方案》附录 C1，原文如下：

```markdown
你是该学生的私人学习助理。请严格按以下规则回答：
1. 只能依据【参考资料】回答；资料中没有的内容，明确说"你的资料里没有相关内容"。
2. 每个来自资料的结论后必须标注引用编号，如 [1][2]；编号必须对应参考资料。
3. 若你要补充资料之外的通用知识，必须另起一段并加前缀"【补充说明｜非你的资料】"。
4. 数学推导分步骤写，公式用 LaTeX（行内 $...$，独立 $$...$$）。
5. 不要编造页码、题号、数据。

【参考资料】
{{ context }}

【学生提问】{{ question }}
```

模板文件本身不带 `{{` 以外的 Python 字符串拼接；版本号固定在文件名 `qa_v1`。

## 7. Answerer

### 7.1 结果模型

```python
RefusalReason = Literal[
    "no_context",
    "low_score",
    "citation_invalid",
    "empty_answer",
]

@dataclass(frozen=True)
class AnswerResult:
    answer: str
    refused: bool
    refusal_reason: RefusalReason | None
    citations: list[Citation]
    context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    retrieval_ms: int
    llm_ms: int
    latency_ms: int
    cost_yuan: float
    llm_calls: int
    citation_retry_count: int
    degraded: bool
    top_rerank_score: float | None
```

固定文案：

```python
REFUSAL_TEXT = "在你的笔记中没找到相关内容。可以换个问法，或先补充相关笔记。"
```

### 7.2 入口

```python
def answer_question(
    session: Session,
    question: str,
    *,
    user_id: int,
    top_k: int = 20,
    threshold: float | None = None,
    embedding_client: EmbeddingClient | None = None,
    rerank_client: RerankClient | None = None,
    llm_client: LLMClient | None = None,
) -> AnswerResult: ...
```

- `question.strip()` 为空 → `ValueError`。
- `threshold` 缺省取 `settings.qa_refuse_threshold`。
- 检索调用 `retrieve_hybrid_reranked(session, question, user_id=user_id, top_k=top_k, client=embedding_client, rerank_client=rerank_client)`。
- 不吞检索异常；DB/Embedding 错误向上抛，CLI 处理。

### 7.3 流程

```text
1. 检索
   └─ reranked 为空 → refused=no_context，不调 LLM
2. 计算 top_score = max(rerank_score)
   ├─ rerank_info.fallback 或 top_score is None → degraded=True，跳过阈值
   └─ top_score < threshold → refused=low_score，不调 LLM
3. build_context(reranked)
   └─ items 为空 → refused=no_context，不调 LLM
4. render_prompt(context.text, question)
5. 第一次 LLM 调用
6. 解析/校验引用
   ├─ 合法 → 返回 answer
   └─ 非法 → 重试 1 次（带上次回答 + 纠正指令）
        ├─ 合法 → 返回 answer
        └─ 仍非法/空 → refused=citation_invalid 或 empty_answer
```

### 7.4 引用校验

```python
_CITATION_RE = re.compile(r"\[(\d+)\]")

def extract_citation_indices(answer: str) -> list[int]: ...
def validate_citations(answer: str, *, context_size: int) -> tuple[bool, list[int]]: ...
```

规则：

- 提取所有 `[n]`，去重、升序。
- 非拒答答案必须有至少一个引用。
- 每个 `n` 必须满足 `1 <= n <= context_size`；否则非法。
- `[0]`、`[99]`、空引用都非法。
- 方括号里的非数字（如 `[补充]`）不算引用，但也不因为出现它而判非法。
- 引用编号必须与 `BuiltContext.items` 的下标一致（1-based）。

### 7.5 重试策略

第一次回答非法时，最多重试 `settings.qa_citation_max_retries` 次（默认 1）：

```python
messages = [
    LLMMessage("user", prompt),
    LLMMessage("assistant", first_answer or "(空回答)"),
    LLMMessage("user", correction_prompt),
]
```

纠正指令固定为：

```text
你上一次回答的引用编号不合法或缺失。本次可用的引用编号只有 [1]..[N]。
请重写回答，只使用这些编号；如果资料不足，直接回答"你的资料里没有相关内容"。
不要解释校验过程，不要使用不存在的编号。
```

- 重试仍非法：`answer=REFUSAL_TEXT`、`refused=True`、`refusal_reason="citation_invalid"`、`citations=[]`。
- 第一次空回答：按非法处理，重试一次；仍空 → `refusal_reason="empty_answer"`。
- `citation_retry_count` 为实际重试次数（0 或 1）。
- `llm_calls` 为实际逻辑调用次数（1 或 2；网络重试不算逻辑调用）。
- token/费用/llm_ms 累计所有逻辑调用。
- 重试时 LLM 抛 `LLMError` → 向上抛，不伪造拒答。

### 7.6 统计口径

- `retrieval_ms` = `result.elapsed_ms`。
- `llm_ms` = 所有逻辑调用 latency 之和。
- `latency_ms` = `retrieval_ms + llm_ms`。
- `context_tokens` = `BuiltContext.tokens`。
- `prompt_tokens` / `completion_tokens` / `total_tokens` / `cost_yuan` 累计所有逻辑调用。
- `degraded` = rerank 失败回退（`result.rerank_info.fallback`）或所有分数为空。
- `top_rerank_score` = 可用分数最大值；没有则为 `None`。

### 7.7 日志

`answerer` 记录：

```text
answer_done
  scene=qa
  user_id
  refused
  refusal_reason
  degraded
  top_rerank_score
  context_tokens
  llm_calls
  citation_retry_count
  prompt_tokens
  completion_tokens
  latency_ms
  cost_yuan
```

禁止把 question、context、answer 正文写入日志；日志只保留计数、状态、耗时、费用。

## 8. CLI

### 8.1 `scripts/ask.py`

用法：

```bash
python scripts/ask.py "我笔记里关于错位相减法是怎么总结的？"
python scripts/ask.py --user-id 1 "今天北京天气怎么样？"
python scripts/ask.py                  # 交互循环
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `question` | 无 | 位置参数；不传则进入 `input()` 循环 |
| `--user-id` | 1 | 用户 ID |
| `--top-k` | 20 | 每路候选数 |
| `--threshold` | 配置值 | 覆盖 τ，便于校准 |
| `--debug` | false | 额外打印检索/上下文统计，不打印正文日志 |

输出：

```text
问题：...
回答：
... [1] ...

引用：
[1] 笔记 #101 / 文件 #12 / 第 3 页 / 章节：函数/单调性
    片段：...

统计：refused=否 tokens=prompt/completion/total latency=retrieval+llm=total ms cost=¥...
```

拒答时：

```text
回答：
在你的笔记中没找到相关内容。可以换个问法，或先补充相关笔记。

统计：refused=是 reason=low_score ...
```

错误处理：

- `LLMError` → stderr 输出“LLM 调用失败：...”，返回 2。
- `PromptTemplateError` → stderr 输出模板路径/原因，返回 3。
- `OperationalError` → 提示启动 Postgres，返回 4。
- `EmbeddingError` → 返回 5。
- 其他异常不吞，交给 Python 堆栈（开发期便于定位）；不打印 Key/正文。

日志：

- CLI 调 `setup_logging(..., stream=sys.stderr)`，避免 JSON 日志混进 stdout 的答案。
- `setup_logging` 增加可选 `stream` 参数，默认 `sys.stdout`；不改变 `app.main` 的现有行为。

### 8.2 `scripts/calibrate_refusal.py`

- 10 个应答题：复用 S1-5 的 10 个问题（函数定义域、单调性、奇偶性、二次函数最值、分段函数、`x+1/x`、利润建模等）。
- 5 个应拒题：
  1. 今天北京天气怎么样？
  2. 怎么用 Python 写一个网页爬虫？
  3. 《红楼梦》的作者是谁？
  4. 出国留学需要准备哪些材料？
  5. 今天股市行情怎么样？
- 每题调用 `retrieve_hybrid_reranked()`，打印：问题、top1 rerank 分、top1 来源、fallback 标记。
- 汇总输出：
  - 应答题最低 top1 分；
  - 应拒题最高 top1 分；
  - 如果两者有间隔，打印“建议 τ 可取间隔中点”；没有间隔则打印“当前小样本无法给出稳定间隔，需扩充语料/换分数口径”。
- 只打印，不改配置、不写数据库、不调 LLM。
- 结果人工记录到 `eval/results/s1-6-refusal-calibration.txt`（真实运行输出；不要伪造）。

## 9. 配置

### 9.1 `backend/app/core/config.py`

新增/修改：

```python
# --- LLM（S1-6）---
llm_api_key: str = Field(default="", repr=False)
llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
llm_model: str = "qwen-plus"
llm_timeout_seconds: float = 60.0
llm_max_retries: int = 2
llm_temperature: float = 0.3
llm_max_output_tokens: int = 1200
llm_price_input_per_million: float = 0.8
llm_price_output_per_million: float = 2.0

# --- QA（S1-6）---
qa_context_max_tokens: int = 4000
qa_refuse_threshold: float = 0.45
qa_citation_max_retries: int = 1
```

`_fallback_dashscope_key()` 增加：

```python
if not self.llm_api_key:
    self.llm_api_key = self.dashscope_api_key
if not self.llm_base_url:
    # .env 里 LLM_BASE_URL= 是空字符串也会覆盖默认值，必须显式回退
    self.llm_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### 9.2 `.env.example`

在 LLM 段补：

```env
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
LLM_TEMPERATURE=0.3
LLM_MAX_OUTPUT_TOKENS=1200
LLM_PRICE_INPUT_PER_MILLION=0.8
LLM_PRICE_OUTPUT_PER_MILLION=2.0

# ===== QA（S1-6）=====
QA_CONTEXT_MAX_TOKENS=4000
QA_REFUSE_THRESHOLD=0.45
QA_CITATION_MAX_RETRIES=1
```

### 9.3 `backend/requirements.txt`

```text
# --- S1-6 问答 Prompt 渲染（已随 FastAPI 安装，显式锁定）---
jinja2==3.1.6
```

不新增 `openai`。

## 10. 错误与隐私

- 所有 API Key 只从 `Settings` 读，`repr=False`；日志/异常/traceback 不出现 Key。
- LLM 错误信息不拼厂商响应正文，避免 4xx 回显 Prompt/正文。
- `answer_done` 日志不含 question/context/answer。
- CLI 不打印完整上下文；`--debug` 只打印计数、分数、token、耗时，不打印正文。
- 评测/校准输出不写真实校名/姓名；如果问题里出现，脚本不额外打印来源全文以外的隐私字段。
- 不改 `.env`；只改 `.env.example`。

## 11. 测试

### 11.1 Prompt builder

1. `test_build_context_orders_by_rerank_and_dedupes`：乱序 + 重复 chunk_id，断言顺序、编号、去重。
2. `test_build_context_without_scores_keeps_input_order`：全 `None` 分数保持原序。
3. `test_build_context_respects_token_budget`：超预算时截断最后一条，`tokens <= max`。
4. `test_build_context_skips_when_header_exceeds_budget`：极小预算返回空。
5. `test_build_context_empty_chunks`：空列表返回空。
6. `test_build_context_citation_metadata`：`note_id/source_file_id/page_no/heading_path` 进入引用；缺失显示“未知”。
7. `test_render_prompt_renders_context_and_question`：Jinja2 变量替换。
8. `test_render_prompt_missing_template_raises`：抛 `PromptTemplateError`。

### 11.2 引用校验

9. `test_extract_citation_indices_dedupes_and_sorts`：`[2][1][2]` → `[1,2]`。
10. `test_validate_citations_accepts_valid`：`[1][2]`，context_size=2。
11. `test_validate_citations_rejects_out_of_range`：`[3]`，context_size=2。
12. `test_validate_citations_rejects_missing`：无引用非法。

### 11.3 Answerer

13. `test_answer_question_refuses_no_context_without_llm`：空 `reranked`，LLM 不被调用。
14. `test_answer_question_refuses_low_score_without_llm`：top score < τ，LLM 不被调用。
15. `test_answer_question_answers_with_citations`：fake LLM 返回带 `[1]`，断言答案/引用/统计。
16. `test_answer_question_retries_invalid_citation_once`：第一次 `[99]`，第二次 `[1]`，`citation_retry_count=1`。
17. `test_answer_question_refuses_after_citation_retry`：两次非法，返回 `REFUSAL_TEXT`、`reason=citation_invalid`。
18. `test_answer_question_empty_answer_retries_then_refuses`：两次空回答，`reason=empty_answer`。
19. `test_answer_question_rerank_fallback_skips_threshold`：fallback=True、无分数，仍调用 LLM，`degraded=True`。
20. `test_answer_question_does_not_swallow_llm_error`：fake LLM 抛 `LLMError`，向上抛。

### 11.4 LLM 适配器

21. `test_llm_chat_success_parses_usage_and_cost`：MockTransport 断言一次请求、模型、消息、temperature、max_tokens、usage、费用。
22. `test_llm_chat_retries_500_then_success`：两次请求，sleep 记录。
23. `test_llm_chat_400_not_retried`：只一次，`retryable=False`，错误不含响应正文。
24. `test_llm_chat_malformed_response_raises`：无 choices/空 content。
25. `test_llm_chat_missing_usage_defaults_zero`：无 usage 仍返回，cost=0。
26. `test_llm_missing_key_raises`：空 Key 构造抛 `LLMError`。

### 11.5 Config / scripts

27. `test_llm_defaults`：模型、base_url、温度、价格、预算、τ 默认值。
28. `test_llm_key_falls_back_to_dashscope`：`LLM_API_KEY=` 空时取 `DASHSCOPE_API_KEY`。
29. `test_llm_key_explicit_wins_and_repr_hides`：显式 Key 优先，repr 不含 Key。
30. `test_llm_base_url_empty_falls_back`：`LLM_BASE_URL=` 空字符串时回退默认 DashScope compatible URL。
31. `test_ask_script_importable` / `test_calibrate_script_importable`：脚本可 import，不执行真实网络（可用 `importlib`；若成本高则只做 CLI `--help` 子进程测试）。

plan 额外覆盖 3xx 非成功、响应顶层非对象、全部无分数降级、非法阈值，共 36 条用例；外部调用仍全部 mock。

所有 LLM/Embedding/Rerank 测试必须 mock；测试套件零真实外部调用。真实调用只放在人工验收命令里。

## 12. 验收

### 12.1 自动测试

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

要求全绿；新增测试数在 plan 中精确到条，实测数量回填 spec §15。

### 12.2 真实 CLI

```bash
cd E:\BiShe-AIStudy\study-agent
.venv\Scripts\python.exe scripts/ask.py "我笔记里关于错位相减法是怎么总结的？"
.venv\Scripts\python.exe scripts/ask.py "今天北京天气怎么样？"
.venv\Scripts\python.exe scripts/calibrate_refusal.py
```

验收标准：

1. 第一个问题：`refused=否`，回答至少含一个合法 `[n]`，引用列表能对应到 `note_id/page_no/heading_path`，不是空引用；必须能追到新增的 note 107（错位相减法样张）。
2. 第二个问题：`refused=是`，`reason` 为 `low_score` 或 `no_context`，**没有 LLM 调用**（看统计 `llm_calls=0`）。
3. 校准脚本输出 15 题分数；如果当前阈值无法分开应答题/应拒题，必须如实报告并调整，不得伪造。
4. 真实运行输出保存到 `eval/results/s1-6-qa-demo.txt` / `s1-6-refusal-calibration.txt`；不写真实校名/姓名。

### 12.3 人工判断

- 答案是否真的由引用片段支撑；
- 引用编号是否指向正确来源；
- 拒答是否干脆，不夹带“根据我的知识”式幻觉；
- 数学公式是否可读（LaTeX）。

## 13. 已知局限

- 引用没有笔记标题/文件名，只有 ID + 页码 + 章节；S2 建表后补。
- 只有 83 块 / 7 note 合成/样张语料（含本卡新增 note 107），阈值校准样本小；完整 20+10 在 S1-7。
- note 107 是为了让指定验收问题可答而新增的合成样张，不是真实学生数据；论文中必须标明，不能把 83 块数字与 S1-5 的 75 块数字混用。
- `hit@5` 饱和、rerank 对封面文本敏感的问题仍然存在；本卡不重新调 rerank。
- LLM 价格按北京区 qwen-plus 列表价估算，实际账单可能有折扣/缓存差异。
- 单轮、无 query 改写、无多轮指代消解；复杂追问可能检索不到。
- 引用校验是“编号存在性”校验，不判断引用是否真正支撑该句；语义支撑判断留人工/S1-7。

## 14. 风险与回退

| 风险 | 处理 |
|---|---|
| LLM Key 不可用 | CLI 明确报错，不伪造答案；`LLM_API_KEY` 可回退 `DASHSCOPE_API_KEY` |
| qwen-plus 不支持当前 base_url/参数 | 真实调用失败则按错误报告，不静默切换模型；base_url/model 可配置 |
| 引用编号总非法 | 重试 1 次；仍非法拒答，记录 `citation_invalid` |
| rerank 失败 | 跳过 τ，使用 RRF top6，`degraded=True` |
| 上下文超预算 | 按分数截断；不把超预算文本送 LLM |
| 0.45 分不开 | 校准脚本报告分布，调整 `QA_REFUSE_THRESHOLD` 并记录；不伪造通过 |
| 标题/文件名缺失 | 明确显示“笔记 #/文件 #/页码/章节”，不伪造 |

## 15. 实施回填

- 实际测试数量：**160 passed, 1 warning**（2026-10-20；基线 124 + 新增 36）
- note 107 实际块数：**8**；全库 **83 块 / 7 note**；`错位相减` 命中 5 行
- 真实 CLI 输出：`eval/results/s1-6-qa-demo.txt`
  - 错位相减：`refused=否`，4 条引用全部指向 note 107，`llm_calls=1`
  - 今天北京天气：`refused=是`，`reason=low_score`，`llm_calls=0`
- 校准 15 题分数：应答题 top1 最低 **0.4586**，应拒题 top1 最高 **0.4347**；间隔中点 **0.4467**；实际 τ=**0.45**
- 小校准输出：`eval/results/s1-6-refusal-calibration.txt`
- 与 plan 的偏离：
  1. 原默认 τ=0.35 实测无法分开，经用户确认改为 0.45；
  2. 原计划 note 107 预计 5–7 块，实测 8 块；
  3. `ask.py` / `calibrate_refusal.py` 增加 UTF-8 stdio 重配，避免 Windows GBK 控制台在 `¥`/公式字符上崩溃。
- 已知问题：
  1. 引用仍是 `note_id + source_file_id + page_no + heading_path`，无标题/文件名（S2 补）；
  2. 应答题最低分 0.4586 与 τ=0.45 只差 0.0086，阈值间隔很窄，S1-7 需用 20+10 复核；
  3. 引用校验只查编号存在性，不判断语义支撑。

## 16. 自检

- [x] 目标/范围/不做事项明确
- [x] 每个模块有输入输出与错误路径
- [x] Prompt 模板原文固定，无占位 TBD
- [x] 引用/拒答/重试规则可测试
- [x] 配置项与 `.env.example` 对齐
- [x] 无 API/SCHEMA/迁移改动
- [x] 真实验收命令可直接执行
- [x] 隐私边界明确：不记录正文/Key，不伪造标题