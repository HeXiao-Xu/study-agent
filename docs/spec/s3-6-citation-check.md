# S3-6 拒答与引用校验 Spec

> 任务卡：`docs/AI协作开发实施计划.md` S3-6。产出：`services/citation_checker.py`。
> 状态：设计已确认（2026-10-31），待 spec 审阅。
> 前置：S3-5 已交付 SSE `meta/delta/done/error`、会话/消息/引用落库。

## 1. 目标

- 生成后校验答案中的引用：越界 `[n]`、整段无引用、部分块无引用。
- 有问题最多重试一次；仍不合格时按情况拒答或加“模型补充”声明。
- 拒答时返回结构化建议（换问法 / 补充笔记）。
- 保持 S3-5 的 SSE 协议兼容，只给 `done` 增加字段。

非目标：前端（S3-8）、会话列表、引用建议落库、`answer_question`/`scripts/ask.py` 改造（保持 S1-6 行为）、按知识点跳转（暂无稳定 kp 关联）、新表/迁移/依赖/配置。

## 2. 已确认决策

1. **输出策略**：先完整生成并校验，再通过 SSE 按块发送；不再逐 token 推送。首字延迟增加，但能保证重试/前缀不“先发后改”。
2. **检测粒度**：按段落/列表项/表格块检查；标题、代码块、纯公式块、补充声明块、拒答文案跳过。
3. **标注方式**：只给未引用块加前缀，不整段误伤；前缀固定为 `【以下为模型补充，未在你的资料中找到依据】`。
4. **重试失败**：第二轮仍无任何合法引用 → 拒答；有合法引用但部分块无引用/含越界编号 → 去掉越界编号，只标注未引用块，保留回答。
5. **拒答建议**：`done` 增加 `suggestions:[{type,text,note_id?}]` 与 `refusal_reason`；不落库，重新加载后不保留。
6. **接入范围**：只接 SSE 链路（`qa_service`），`answer_question` 保持 S1-6 的“非法引用重试后拒答”行为。
7. **数据边界**：不新增表/迁移；`message_citations` 仍只存最终正文中的合法 `[n]`。

## 3. 架构与数据流

```
POST /qa/ask
  → prepare_ask（同 S3-5：会话/历史/改写/检索/Prompt；user 消息已落）
  → SSE meta（全部上下文 citations）
  → 静默消费第一次 LLM 流（不向客户端发 delta）
  → citation_checker.check_answer(answer, context_size)
       ├ clean → final = answer
       ├ 有问题且允许重试 → 用纠正指令再生成一次（静默）
       │     ├ 仍无合法引用 → refusal
       │     └ 有合法引用 → strip_invalid + annotate_uncited
       └ 不允许重试 → 无合法引用则 refusal，否则 strip + annotate
  → 按块发 delta（final 文本）
  → 落 assistant（final/refusal + token_usage 聚合 + 合法 citations）
  → done（新增 refusal_reason/suggestions）
```

- `meta`、`delta`、`error` 名称不变；`delta` 由“token”变为“校验后的文本块”。
- 流开始后不抛 JSON 4xx/5xx；生成/校验失败发 `event: error`，不落 assistant。
- 断连仍不落 assistant；上游 LLM 关闭。

## 4. `citation_checker` 契约

`backend/app/services/citation_checker.py` 为纯函数模块，不依赖 DB/LLM/HTTP。

```python
SUPPLEMENT_PREFIX = "【以下为模型补充，未在你的资料中找到依据】"

@dataclass(frozen=True)
class CitationCheck:
    context_size: int
    valid_indices: list[int]
    invalid_indices: list[int]
    uncited_blocks: list[str]
    has_content: bool

    @property
    def has_valid_citation(self) -> bool: ...
    @property
    def needs_retry(self) -> bool: ...
    @property
    def is_clean(self) -> bool: ...

def split_blocks(answer: str) -> list[str]: ...
def check_answer(answer: str, *, context_size: int) -> CitationCheck: ...
def strip_invalid_citations(answer: str, *, context_size: int) -> str: ...
def annotate_uncited(answer: str, *, context_size: int) -> str: ...
def build_correction(check: CitationCheck) -> str: ...
```

### 4.1 分块

1. 统一 `\r\n`/`\r` 为 `\n`。
2. 按空行切段；段内遇到 Markdown 标题、列表项（`-/*/+` 或 `数字.`）、引用行（`>`）时另起一块，续行归入当前块。
3. 围栏代码块（``` / ~~~）整块标记为 `skip`；表格按空行段处理，不拆表头。
4. 保留原始块的换行与空白，供标注时还原。

### 4.2 跳过/实质块

跳过的块：
- 标题行（`^#{1,6}\s`）；
- 围栏代码块；
- 纯公式块（以 `$$`/`\[` 开头并结束，且无中文）；
- 已带 `SUPPLEMENT_PREFIX` 或 `【补充说明｜非你的资料】` 的块；
- 固定拒答文案（含“在你的笔记中没找到相关内容”）；
- 纯分隔线/空白。

实质块：含至少一个中文汉字，或去空白后长度 ≥ 20；纯数字/标点/LaTeX 公式不算实质块。

### 4.3 引用判定

- 合法引用：块内出现 `[n]` 且 `1 <= n <= context_size`。
- 越界引用：出现 `[n]` 但不在范围内，计入 `invalid_indices`。
- 块内有合法引用即视为已引用；只有越界编号不算已引用，最终去编号后按未引用处理。
- 整篇无合法引用 → `needs_retry=True`；`has_content=False` 表示空/只有跳过块。

## 5. 重试、拒答与标注

### 5.1 重试条件

`check.needs_retry` 为真且 `settings.qa_citation_max_retries >= 1` 时重试 **一次**：

- 空回答 / 无任何合法引用；
- 存在 `invalid_indices`；
- 存在 `uncited_blocks`。

纠正消息由 `build_correction(check)` 生成，包含：

- 可用编号范围 `[1]..[N]`；
- 未引用块数量；
- “每个知识陈述后加引用；资料不足的补充内容另起段并以固定前缀开头；不要解释校验过程”；
- 不复述上下文全文，避免二次膨胀。

### 5.2 最终判定

按顺序：

1. 最终文本为空/只有跳过块 → 拒答 `empty_answer`。
2. 最终无任何合法引用 → 拒答 `no_valid_citation`。
3. 有合法引用 → `strip_invalid_citations` 删越界编号；`annotate_uncited` 给每个未引用实质块前置：

```text
【以下为模型补充，未在你的资料中找到依据】
<原块>
```

4. 已带该前缀/`【补充说明｜非你的资料】` 的块不重复加。

拒答文案仍用 `REFUSAL_TEXT`；拒答时 `message.content_md=REFUSAL_TEXT`，citations 为空。

### 5.3 拒答建议

`done.suggestions` 固定返回：

```json
[
  {"type": "rephrase", "text": "换个问法，把问题拆得更具体"},
  {"type": "note", "text": "先补充相关笔记，或缩小检索范围"}
]
```

`type` 仅 `rephrase/note`；`note_id` 本轮为 `null`（不额外查笔记标题）。正常回答/chitchat 返回 `[]`。

`refusal_reason`：

| 值 | 触发 |
|---|---|
| `no_context` | 检索为空 |
| `low_score` | 最高重排分低于阈值 |
| `empty_answer` | 两轮都空/只有跳过块 |
| `no_valid_citation` | 两轮都没有合法引用 |

## 6. SSE 与 API 变更

`done` 新结构（向后兼容）：

```json
{
  "message_id": 2,
  "conversation_id": "1",
  "tokens": 1949,
  "latency_ms": 24472,
  "refused": false,
  "refusal_reason": null,
  "suggestions": []
}
```

- `tokens`：所有 LLM 尝试（首轮 + 重试）的 answer tokens + rewrite tokens。
- `message.token_usage`：同样聚合；`rewrite` 仍为 rewrite 对象。
- `model`：最后一次 LLM 的 model；拒答且无 LLM 调用时为 NULL。
- `delta`：校验后的文本块；拼接后必须等于最终正文（含前缀）。
- 无新事件、无新路由；`error` 仍 `{code:50000,message:"生成失败"}`。

### 6.1 断连

- `qa_service.stream_events(..., cancel_event: threading.Event | None = None)`；
- 静默消费阶段每收一个 chunk 检查 `cancel_event`；置位则关闭上游、直接返回，不落 assistant、不发 done；
- 路由 async 生成器 `finally` 置位 `cancel_event` 并 best-effort `events.close()`；不因断连产生 500；
- 服务端日志 `qa_stream_disconnected` 保留。

## 7. 测试

| 文件 | 约条数 | 覆盖 |
|---|---|---|
| `backend/tests/test_citation_checker.py` | 12 | 分块/跳过标题代码公式/合法引用/越界/无引用/多块/去编号/加前缀/已有声明不重复/空回答/纠正消息 |
| `backend/tests/test_qa_service.py`（改） | +5 | 一次通过不重试/无引用重试拒答/部分缺失重试标注/越界清理/断连 cancel_event |
| `backend/tests/test_qa_api.py`（改） | +2 | done 新字段/拒答 suggestions |
| `backend/tests/test_answerer.py`（改） | +1 | `stream_answer(messages=...)` 支持重试消息 |
| 既有 | 666 保持全绿 | 预计 **686 passed, 1 warning** |

外部 LLM/DB 全部 fake 或注入替身；真实调用只放验收。

## 8. 验收

1. `pytest -q` 全绿，记录实测数字。
2. 新增 `scripts/citation_eval.py`：固定 5 条“笔记里没有” + 5 条“部分有部分没有”，真实 LLM，逐条打印：
   - `refused`/`refusal_reason`
   - `uncited_blocks` 数量与前 40 字
   - 是否出现 `SUPPLEMENT_PREFIX`
   - `valid/invalid` 引用编号
3. 判定口径：
   - 5 条“笔记里没有”全部 `refused=true`。
   - 5 条“部分有部分没有”全部 `refused=false` 且至少 1 个块带前缀。
   - 任一条不符合则脚本退出非 0，不粉饰。
4. 真实 SSE 抽查一次：`meta` 后等待完整生成，再收到按块 `delta` 与 `done`；DB 的 assistant 正文含前缀（若部分缺失）、citations 只含合法编号。
5. 文档同步：`docs/API.md` §5 `done` 字段、`docs/PROGRESS.md`、`docs/DECISIONS.md`、任务卡 S3-6 勾选；无 SCHEMA 变更。

## 9. 已知限制

1. 校验后输出使首字延迟显著增加（真实 LLM 可能 10–30s）；S3-8 需 loading 态。
2. 块级检测是启发式：一段里只有末尾一个引用会视为整块已引用；不判断引用是否真正支持该句。
3. 重试仍可能失败；失败后只做“标注”或“拒答”，不保证答案正确。
4. 建议为固定文案，不按知识点个性化；`note_id` 暂为 null。
5. 建议不落库，刷新后丢失；S3-8 如需历史建议需加列。
6. 断连在静默生成阶段只能在下一次 chunk 到达时关闭上游；不保证立即停止计费。
7. `answer_question` 仍是旧策略，CLI 与 API 行为不完全一致；统一留到后续卡。

## 10. 实施记录（2026-11-01）

- 实际测试：新增 20 条（checker 12、answerer 1、service 5、API 2），全量 **686 passed, 1 warning**；基线 666。
- 真实 5+5：`scripts/citation_eval.py --user-id 18` **10/10 通过**。
  - 5 条无依据：3 条 `low_score`、2 条 `no_valid_citation`，全部 `refused=true`，`suggestions=2`。
  - 5 条部分覆盖：全部 `refused=false` 且带 `SUPPLEMENT_PREFIX`；valid 引用分别为 3/1/6/6/4 个。
- 真实 SSE 抽查（错位相减法步骤+历史，conversation 17 / message 32）：`meta` 3.10s、首个 `delta` 15.06s、4 个 delta、`done` 15.10s；`tokens=2759`、`latency_ms=14672`、`suggestions=[]`；DB 425 字、前缀 2 处、citations rank 1–3。
- 偏差：任务卡写“给答案加前缀”，按设计确认改为“只给未引用块加前缀”；`done.suggestions` 固定文案、`note_id=null`；“去看看某个知识点”暂用“补充相关笔记/缩小检索范围”表达，未做 kp 跳转。
- 既有断言调整：S3-5 的“首个 chunk 即 delta”“断连前收到 delta”两条改为校验后输出语义；未删除测试。